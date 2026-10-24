"""
benchmark_v2/select_targets.py — Deterministic, reproducible target selection
for Benchmark v2 Sets A and B.

Pre-registers held-out evaluation sets adhering to:
- PRNG Seed: 7319042
- Set A (short-period): 30 planets (>=10 shallow <= 2500 ppm), 30 non-planets, P <= 8.7 d, Tmag <= 13.0
- Set B (long-period / multi-sector): 30 planets, 30 non-planets, 8.7 < P <= 20.0 d, Tmag <= 13.0, >= 2 SPOC sectors
- Exclusions: benchmark_v2/burned_ids.txt (120 IDs), benchmark/targets.csv (50 dev targets),
  HD 10000-10744 survey footprint, and mutual Set A vs Set B disjointness.
- Real fetch date: 2026-10-24
- Cryptographic SHA-256 computed directly from downloaded FITS bytes.
- Zero overlap asserted before writing any output.
- Output requirement: Prints only counts.
"""

import os
import sys
import hashlib
import random
import sqlite3
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from astroquery.mast import Catalogs, Observations

SEED = 7319042
FETCH_DATE = "2026-10-24"
BENCHMARK_TIMEOUT = 30
CACHE_DIR = os.path.expanduser("~/.cache/lightkurve/mastDownload/TESS")


def load_exclusions(base_dir: str):
    """Load all exclusion sources and return sets of TIC IDs and target names."""
    # 1. Burned IDs (120 TICs)
    burned_path = os.path.join(base_dir, "benchmark_v2", "burned_ids.txt")
    if not os.path.exists(burned_path):
        raise FileNotFoundError(f"Missing burned IDs file: {burned_path}")
    with open(burned_path, "r", encoding="utf-8") as f:
        burned_ids = {int(line.strip()) for line in f if line.strip()}
    if len(burned_ids) != 120:
        raise ValueError(f"Expected 120 burned IDs, found {len(burned_ids)}")

    # 2. Development benchmark targets (50 TICs)
    dev_path = os.path.join(base_dir, "benchmark", "targets.csv")
    if not os.path.exists(dev_path):
        raise FileNotFoundError(f"Missing dev targets file: {dev_path}")
    dev_df = pd.read_csv(dev_path)
    dev_ids = {int(x) for x in dev_df["tic_id"]}
    if len(dev_ids) != 50:
        raise ValueError(f"Expected 50 dev targets, found {len(dev_ids)}")

    # 3. HD 10000-10744 footprint
    survey_names = {f"HD {i}" for i in range(10000, 10745)}
    survey_tics = set()

    db_path = os.path.join(base_dir, "astrohunter.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT tic_id, name FROM targets")
        for tid, name in c.fetchall():
            if name in survey_names or tid in survey_names:
                survey_names.add(str(name))
                if tid and str(tid).isdigit():
                    survey_tics.add(int(tid))
        c.execute("SELECT tic_id, name FROM signals")
        for tid, name in c.fetchall():
            if name in survey_names:
                if tid and str(tid).isdigit():
                    survey_tics.add(int(tid))
        conn.close()

    md_path = os.path.join(base_dir, "master_discoveries.csv")
    if os.path.exists(md_path):
        md_df = pd.read_csv(md_path)
        for _, row in md_df.iterrows():
            if str(row["name"]).startswith("HD 10"):
                survey_names.add(str(row["name"]))
                if pd.notna(row["tic_id"]) and str(row["tic_id"]).isdigit():
                    survey_tics.add(int(row["tic_id"]))

    return burned_ids, dev_ids, survey_tics, survey_names


def fetch_candidate_tois(burned_ids, dev_ids, survey_tics, survey_names):
    """Query candidates from NASA Exoplanet Archive TOI table and apply exclusions."""
    tap_url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
    q = (
        "select tid, toi, toidisplay, tfopwg_disp, pl_orbper, pl_trandep, "
        "st_tmag, st_rad, ra, dec from toi "
        "where st_tmag <= 13.0 and pl_orbper > 0 and pl_trandep > 0"
    )
    resp = requests.get(tap_url, params={"query": q, "format": "json"}, timeout=60)
    resp.raise_for_status()

    df = pd.DataFrame(resp.json())
    df = df[df["tfopwg_disp"].isin(["CP", "KP", "FP"])].copy()
    df = df[df["st_rad"] > 0].copy()
    df["tid_int"] = df["tid"].astype(int)
    df["target_name"] = "TOI " + df["toi"].astype(str)

    filtered = df[
        (~df["tid_int"].isin(burned_ids)) &
        (~df["tid_int"].isin(dev_ids)) &
        (~df["tid_int"].isin(survey_tics)) &
        (~df["target_name"].isin(survey_names))
    ].copy()

    # Sort deterministically before any sampling
    filtered = filtered.sort_values(by=["pl_orbper", "tid_int"]).reset_index(drop=True)
    return filtered


def query_spoc_observations_batch(tic_list, chunk_size=50):
    """Retrieve SPOC 2-minute cadence observation records for a list of TICs."""
    by_tic = {}
    for i in range(0, len(tic_list), chunk_size):
        chunk = tic_list[i:i + chunk_size]
        obs = Observations.query_criteria(
            provenance_name="SPOC",
            target_name=[str(x) for x in chunk],
            obs_collection="TESS"
        )
        lc_obs = [row for row in obs if str(row["dataURL"]).endswith("_lc.fits")]
        for row in lc_obs:
            tid = int(row["target_name"])
            sec = int(row["sequence_number"])
            fname = os.path.basename(str(row["dataURL"]))
            tid_str = f"{tid:016d}"
            s3_key = (
                f"tess/public/tid/s{sec:04d}/{tid_str[0:4]}/{tid_str[4:8]}/"
                f"{tid_str[8:12]}/{tid_str[12:16]}/{fname}"
            )
            by_tic.setdefault(tid, []).append({
                "sector": sec,
                "filename": fname,
                "s3_key": s3_key,
                "dataURL": str(row["dataURL"])
            })
    return by_tic


def query_tic_parameters_batch(tic_list, chunk_size=50):
    """Retrieve authentic stellar radius and mass from TIC v8.2."""
    params = {}
    for i in range(0, len(tic_list), chunk_size):
        chunk = tic_list[i:i + chunk_size]
        res = Catalogs.query_criteria(catalog="TIC", ID=chunk)
        for r in res:
            tid = int(r["ID"])
            rad = float(r["rad"]) if pd.notna(r["rad"]) and r["rad"] is not None else -1.0
            mass = float(r["mass"]) if pd.notna(r["mass"]) and r["mass"] is not None else -1.0
            tmag = float(r["Tmag"]) if pd.notna(r["Tmag"]) and r["Tmag"] is not None else -1.0
            if rad > 0 and mass > 0 and tmag > 0:
                params[tid] = {"r_star_rsun": rad, "m_star_msun": mass, "tmag": tmag}
    return params


def download_fits_and_hash(s3_key: str, filename: str) -> str:
    """Download FITS light curve from AWS S3 (or MAST fallback) and compute SHA-256."""
    stem = filename.replace("_lc.fits", "")
    dest_dir = os.path.join(CACHE_DIR, stem)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) >= 10000:
        with open(dest_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    # 1. Primary: STScI AWS Open Data S3 mirror
    s3_url = f"https://s3.amazonaws.com/stpubdata/{s3_key}"
    try:
        r = requests.get(s3_url, timeout=BENCHMARK_TIMEOUT)
        if r.status_code == 200 and len(r.content) >= 10000:
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return hashlib.sha256(r.content).hexdigest()
    except Exception:
        pass

    # 2. Fallback: MAST API
    mast_url = f"https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:TESS/product/{filename}"
    try:
        r = requests.get(mast_url, timeout=BENCHMARK_TIMEOUT)
        if r.status_code == 200 and len(r.content) >= 10000:
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return hashlib.sha256(r.content).hexdigest()
    except Exception as err:
        raise RuntimeError(f"Failed to fetch {filename} from AWS S3 and MAST: {err}") from err

    raise RuntimeError(f"Could not retrieve complete FITS file: {filename}")


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rng = random.Random(SEED)

    # 1. Load exclusions
    burned_ids, dev_ids, survey_tics, survey_names = load_exclusions(base_dir)

    # 2. Fetch candidates from TOI
    cand_df = fetch_candidate_tois(burned_ids, dev_ids, survey_tics, survey_names)

    # Separate candidate pools
    cand_a_planets = cand_df[(cand_df["tfopwg_disp"].isin(["CP", "KP"])) & (cand_df["pl_orbper"] >= 0.5) & (cand_df["pl_orbper"] <= 8.7)].copy()
    cand_a_fps = cand_df[(cand_df["tfopwg_disp"] == "FP") & (cand_df["pl_orbper"] <= 8.7)].copy()

    cand_b_planets = cand_df[(cand_df["tfopwg_disp"].isin(["CP", "KP"])) & (cand_df["pl_orbper"] > 8.7) & (cand_df["pl_orbper"] <= 20.0)].copy()
    cand_b_fps = cand_df[(cand_df["tfopwg_disp"] == "FP") & (cand_df["pl_orbper"] > 8.7) & (cand_df["pl_orbper"] <= 20.0)].copy()

    def shuffle_ids(id_list):
        shuffled = list(id_list)
        rng.shuffle(shuffled)
        return shuffled

    # 3. Select Set B first (must satisfy strict >= 2 SPOC sectors constraint)
    pool_b_p = shuffle_ids(cand_b_planets["tid_int"].unique())
    pool_b_fp = shuffle_ids(cand_b_fps["tid_int"].unique())

    obs_b = query_spoc_observations_batch(pool_b_p[:60] + pool_b_fp[:60])
    params_b = query_tic_parameters_batch(pool_b_p[:60] + pool_b_fp[:60])

    selected_b_planets = []
    for tid in pool_b_p:
        if len(selected_b_planets) == 30:
            break
        secs = obs_b.get(tid, [])
        unique_secs = {s["sector"]: s for s in secs}
        if len(unique_secs) >= 2 and tid in params_b:
            selected_b_planets.append(tid)

    selected_b_fps = []
    for tid in pool_b_fp:
        if len(selected_b_fps) == 30:
            break
        secs = obs_b.get(tid, [])
        unique_secs = {s["sector"]: s for s in secs}
        if len(unique_secs) >= 2 and tid in params_b:
            selected_b_fps.append(tid)

    if len(selected_b_planets) != 30 or len(selected_b_fps) != 30:
        raise RuntimeError("Failed to select 30 planets and 30 FPs for Set B")

    set_b_tics = set(selected_b_planets + selected_b_fps)

    # 4. Select Set A (ensuring disjointness from Set B and >=10 shallow planets)
    cand_a_p_shallow = cand_a_planets[cand_a_planets["pl_trandep"] <= 2500]
    cand_a_p_rest = cand_a_planets[cand_a_planets["pl_trandep"] > 2500]

    shallow_tids = shuffle_ids([t for t in cand_a_p_shallow["tid_int"].unique() if t not in set_b_tics])
    rest_tids = shuffle_ids([t for t in cand_a_p_rest["tid_int"].unique() if t not in set_b_tics])
    fp_a_tids = shuffle_ids([t for t in cand_a_fps["tid_int"].unique() if t not in set_b_tics])

    obs_a = query_spoc_observations_batch(shallow_tids[:20] + rest_tids[:35] + fp_a_tids[:50])
    params_a = query_tic_parameters_batch(shallow_tids[:20] + rest_tids[:35] + fp_a_tids[:50])

    selected_a_shallow = []
    for tid in shallow_tids:
        if len(selected_a_shallow) == 10:
            break
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a:
            selected_a_shallow.append(tid)

    selected_a_planets = list(selected_a_shallow)
    for tid in rest_tids:
        if len(selected_a_planets) == 30:
            break
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a and tid not in selected_a_planets:
            selected_a_planets.append(tid)

    selected_a_fps = []
    for tid in fp_a_tids:
        if len(selected_a_fps) == 30:
            break
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a:
            selected_a_fps.append(tid)

    if len(selected_a_planets) != 30 or len(selected_a_fps) != 30:
        raise RuntimeError("Failed to select 30 planets and 30 FPs for Set A")

    set_a_tics = set(selected_a_planets + selected_a_fps)

    # 5. Build record structures and fetch light curves with hashes
    toi_map = {int(r["tid_int"]): r for _, r in cand_df.iterrows()}

    # Set A records
    rows_a = []
    all_download_jobs = []

    for tid in selected_a_planets + selected_a_fps:
        row_info = toi_map[tid]
        p_info = params_a[tid]
        secs = sorted(obs_a[tid], key=lambda x: x["sector"])
        primary_sec = secs[0]

        disp = row_info["tfopwg_disp"]
        true_class = "PLANET" if disp in ["CP", "KP"] else "NON_PLANET"
        true_subclass = f"TOI_{disp}"

        rows_a.append({
            "target_name": row_info["target_name"],
            "tic_id": tid,
            "true_class": true_class,
            "true_subclass": true_subclass,
            "catalog_period_d": float(row_info["pl_orbper"]),
            "catalog_depth_ppm": float(row_info["pl_trandep"]),
            "r_star_rsun": float(p_info["r_star_rsun"]),
            "m_star_msun": float(p_info["m_star_msun"]),
            "tmag": float(p_info["tmag"]),
            "sector": primary_sec["sector"],
            "catalog_id": f"TOI-{row_info['toi']}",
            "catalog_url": f"https://exofop.ipac.caltech.edu/tess/target.php?id={tid}",
            "source_catalog": f"NASA Exoplanet Archive TOI ({disp}) + TIC v8.2 (IV/39/tic82)",
            "source_date": FETCH_DATE,
            "s3_lc_key": primary_sec["s3_key"],
            "_filename": primary_sec["filename"],
        })

    # Set B records
    rows_b = []
    rows_sectors_b = []

    for tid in selected_b_planets + selected_b_fps:
        row_info = toi_map[tid]
        p_info = params_b[tid]
        # Collect unique sectors sorted by sector number
        unique_secs_map = {}
        for s in obs_b[tid]:
            if s["sector"] not in unique_secs_map:
                unique_secs_map[s["sector"]] = s
        sorted_secs = [unique_secs_map[sec] for sec in sorted(unique_secs_map.keys())]

        if len(sorted_secs) < 2:
            raise RuntimeError(f"Target {tid} has fewer than 2 sectors ({len(sorted_secs)})")

        # Select the 2 primary sectors for multi-sector evaluation
        eval_secs = sorted_secs[:2]
        primary_sec = eval_secs[0]

        disp = row_info["tfopwg_disp"]
        true_class = "PLANET" if disp in ["CP", "KP"] else "NON_PLANET"
        true_subclass = f"TOI_{disp}"

        rows_b.append({
            "target_name": row_info["target_name"],
            "tic_id": tid,
            "true_class": true_class,
            "true_subclass": true_subclass,
            "catalog_period_d": float(row_info["pl_orbper"]),
            "catalog_depth_ppm": float(row_info["pl_trandep"]),
            "r_star_rsun": float(p_info["r_star_rsun"]),
            "m_star_msun": float(p_info["m_star_msun"]),
            "tmag": float(p_info["tmag"]),
            "sector": primary_sec["sector"],
            "catalog_id": f"TOI-{row_info['toi']}",
            "catalog_url": f"https://exofop.ipac.caltech.edu/tess/target.php?id={tid}",
            "source_catalog": f"NASA Exoplanet Archive TOI ({disp}) + TIC v8.2 (IV/39/tic82)",
            "source_date": FETCH_DATE,
            "s3_lc_key": primary_sec["s3_key"],
            "n_sectors": len(eval_secs),
            "sectors": ";".join(str(s["sector"]) for s in eval_secs),
            "_eval_secs": eval_secs,
        })

    # Download FITS and compute authentic SHA-256
    file_hashes = {}
    download_tasks = []

    for r in rows_a:
        download_tasks.append((r["s3_lc_key"], r["_filename"]))

    for r in rows_b:
        for s in r["_eval_secs"]:
            download_tasks.append((s["s3_key"], s["filename"]))

    # Deduplicate download tasks
    unique_download_tasks = list({fname: (s3_key, fname) for s3_key, fname in download_tasks}.values())

    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {
            ex.submit(download_fits_and_hash, s3_key, fname): fname
            for s3_key, fname in unique_download_tasks
        }
        for fut in as_completed(futures):
            fname = futures[fut]
            file_hashes[fname] = fut.result()

    # Assign verified hashes to Set A
    for r in rows_a:
        fname = r["_filename"]
        r["fits_sha256"] = file_hashes[fname]
        del r["_filename"]

    # Assign verified hashes to Set B and build sector table
    for r in rows_b:
        eval_secs = r["_eval_secs"]
        sec_hashes = [file_hashes[s["filename"]] for s in eval_secs]
        r["fits_sha256"] = sec_hashes[0]
        r["sectors_sha256"] = ";".join(sec_hashes)

        for s, h in zip(eval_secs, sec_hashes):
            rows_sectors_b.append({
                "tic_id": r["tic_id"],
                "target_name": r["target_name"],
                "sector": s["sector"],
                "s3_lc_key": s["s3_key"],
                "fits_sha256": h,
                "source_date": FETCH_DATE,
            })
        del r["_eval_secs"]

    # 6. ASSERT zero overlap across all exclusion sets before writing output
    overlap_a_burned = set_a_tics & burned_ids
    overlap_b_burned = set_b_tics & burned_ids
    overlap_a_dev = set_a_tics & dev_ids
    overlap_b_dev = set_b_tics & dev_ids
    overlap_a_survey = set_a_tics & survey_tics
    overlap_b_survey = set_b_tics & survey_tics
    overlap_a_b = set_a_tics & set_b_tics

    all_names_a = {r["target_name"] for r in rows_a}
    all_names_b = {r["target_name"] for r in rows_b}
    overlap_names_survey = (all_names_a | all_names_b) & survey_names

    assert len(overlap_a_burned) == 0, f"Set A overlaps burned IDs: {len(overlap_a_burned)}"
    assert len(overlap_b_burned) == 0, f"Set B overlaps burned IDs: {len(overlap_b_burned)}"
    assert len(overlap_a_dev) == 0, f"Set A overlaps dev benchmark: {len(overlap_a_dev)}"
    assert len(overlap_b_dev) == 0, f"Set B overlaps dev benchmark: {len(overlap_b_dev)}"
    assert len(overlap_a_survey) == 0, f"Set A overlaps survey TICs: {len(overlap_a_survey)}"
    assert len(overlap_b_survey) == 0, f"Set B overlaps survey TICs: {len(overlap_b_survey)}"
    assert len(overlap_names_survey) == 0, f"Targets overlap survey names: {len(overlap_names_survey)}"
    assert len(overlap_a_b) == 0, f"Set A overlaps Set B: {len(overlap_a_b)}"

    assert len(rows_a) == 60, f"Set A must have 60 rows, got {len(rows_a)}"
    assert len(rows_b) == 60, f"Set B must have 60 rows, got {len(rows_b)}"
    assert all(r["n_sectors"] >= 2 for r in rows_b), "All Set B targets must have >= 2 sectors"

    # 7. Write output files
    df_out_a = pd.DataFrame(rows_a)
    df_out_b = pd.DataFrame(rows_b)
    df_out_sectors_b = pd.DataFrame(rows_sectors_b)

    out_dir = os.path.join(base_dir, "benchmark_v2")
    os.makedirs(out_dir, exist_ok=True)

    a_path = os.path.join(out_dir, "targets_set_a.csv")
    b_path = os.path.join(out_dir, "targets_set_b.csv")
    sectors_b_path = os.path.join(out_dir, "sectors_set_b.csv")

    df_out_a.to_csv(a_path, index=False)
    df_out_b.to_csv(b_path, index=False)
    df_out_sectors_b.to_csv(sectors_b_path, index=False)

    # 8. Print ONLY counts (hard requirement)
    n_burned = len(burned_ids)
    n_dev = len(dev_ids)
    n_survey_tics = len(survey_tics)
    n_survey_names = len(survey_names)

    n_cand_eligible = len(cand_df)

    n_a_planets = len(selected_a_planets)
    n_a_shallow = len(selected_a_shallow)
    n_a_fps = len(selected_a_fps)
    n_a_total = len(rows_a)

    n_b_planets = len(selected_b_planets)
    n_b_fps = len(selected_b_fps)
    n_b_total = len(rows_b)
    min_b_sectors = min(r["n_sectors"] for r in rows_b)

    n_unique_tics = len(set_a_tics | set_b_tics)
    n_files_downloaded = len(unique_download_tasks)
    n_b_sector_rows = len(rows_sectors_b)

    print(f"Exclusion counts:")
    print(f"  burned_ids: {n_burned}")
    print(f"  dev_targets: {n_dev}")
    print(f"  survey_tics: {n_survey_tics}")
    print(f"  survey_names: {n_survey_names}")
    print(f"Candidate counts:")
    print(f"  candidate_eligible: {n_cand_eligible}")
    print(f"Set A selection counts:")
    print(f"  planets: {n_a_planets}")
    print(f"  shallow_planets: {n_a_shallow}")
    print(f"  non_planets: {n_a_fps}")
    print(f"  total: {n_a_total}")
    print(f"Set B selection counts:")
    print(f"  planets: {n_b_planets}")
    print(f"  non_planets: {n_b_fps}")
    print(f"  total: {n_b_total}")
    print(f"  minimum_sectors: {min_b_sectors}")
    print(f"Disjointness assertion counts:")
    print(f"  overlap_burned: {len(overlap_a_burned | overlap_b_burned)}")
    print(f"  overlap_dev: {len(overlap_a_dev | overlap_b_dev)}")
    print(f"  overlap_survey: {len(overlap_a_survey | overlap_b_survey | overlap_names_survey)}")
    print(f"  overlap_a_b: {len(overlap_a_b)}")
    print(f"Provenance verification counts:")
    print(f"  unique_tics: {n_unique_tics}")
    print(f"  files_downloaded: {n_files_downloaded}")
    print(f"  sectors_set_b_rows: {n_b_sector_rows}")


if __name__ == "__main__":
    main()
