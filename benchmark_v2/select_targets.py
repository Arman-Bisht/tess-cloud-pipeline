"""
benchmark_v2/select_targets.py — Deterministic, reproducible target selection
for Benchmark v2 Sets A and B.

Pre-registers held-out evaluation sets adhering to:
- PRNG Seed: 7319042
- Set A (short-period): exactly 30 planets (>=10 shallow <= 2500 ppm, 0.5 <= P <= 8.7 d),
  30 non-planets (exactly 15 TOI_FP, 15 PRSA_EB, P <= 8.7 d), Tmag <= 13.0, R_star > 0, M_star > 0
- Set B (long-period / multi-sector): exactly 30 planets (8.7 < P <= 20.0 d),
  30 non-planets (exactly 15 TOI_FP, 15 PRSA_EB, 8.7 < P <= 20.0 d),
  Tmag <= 13.0, R_star > 0, M_star > 0, >= 2 SPOC sectors
- Exclusions: benchmark_v2/burned_ids.txt (120 IDs), benchmark/targets.csv (50 dev targets),
  HD 10000-10744 survey footprint, and mutual Set A vs Set B disjointness.
- Real fetch date: 2026-10-24
- Cryptographic SHA-256 computed directly from downloaded FITS bytes.
- Zero overlap and all catalog constraints strictly asserted before writing any output.
- Output requirement: Prints only counts.
"""

import os
import sys
import re
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
PRSA_URL = "https://archive.stsci.edu/hlsps/tess-ebs/hlsp_tess-ebs_tess_lcf-ffi_s0001-s0026_tess_v1.0_cat.csv"


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

    # Sort deterministically
    filtered = filtered.sort_values(by=["pl_orbper", "tid_int"]).reset_index(drop=True)
    return filtered


def fetch_candidate_prsa_ebs(burned_ids, dev_ids, survey_tics, survey_names):
    """Fetch Prsa et al. (2022) TESS Eclipsing Binary catalog and apply exclusions."""
    cache_path = os.path.expanduser("~/.cache/prsa_ebs.csv")
    if not os.path.exists(cache_path):
        resp = requests.get(PRSA_URL, timeout=60)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(resp.content)

    df = pd.read_csv(cache_path)
    df = df[
        (~df["tess_id"].isin(burned_ids)) &
        (~df["tess_id"].isin(dev_ids)) &
        (~df["tess_id"].isin(survey_tics)) &
        (df["Tmag"] <= 13.0) &
        (df["period"] > 0) &
        (df["prim_depth_pf"] > 0)
    ].copy()

    df["tid_int"] = df["tess_id"].astype(int)
    df["target_name"] = "TESS-EB TIC " + df["tid_int"].astype(str)
    df = df[~df["target_name"].isin(survey_names)].copy()

    # Sort deterministically
    df = df.sort_values(by=["period", "tid_int"]).reset_index(drop=True)
    return df


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

    # 2. Fetch candidates from TOI table and Prsa EB catalog
    cand_toi_df = fetch_candidate_tois(burned_ids, dev_ids, survey_tics, survey_names)
    cand_prsa_df = fetch_candidate_prsa_ebs(burned_ids, dev_ids, survey_tics, survey_names)

    # Candidate pools
    # Set B pools (8.7 < P <= 20.0 d)
    b_planets = cand_toi_df[
        (cand_toi_df["tfopwg_disp"].isin(["CP", "KP"])) &
        (cand_toi_df["pl_orbper"] > 8.7) &
        (cand_toi_df["pl_orbper"] <= 20.0)
    ].to_dict(orient="records")

    b_toi_fps = cand_toi_df[
        (cand_toi_df["tfopwg_disp"] == "FP") &
        (cand_toi_df["pl_orbper"] > 8.7) &
        (cand_toi_df["pl_orbper"] <= 20.0)
    ].to_dict(orient="records")

    b_prsa_ebs = cand_prsa_df[
        (cand_prsa_df["period"] > 8.7) &
        (cand_prsa_df["period"] <= 20.0)
    ].to_dict(orient="records")

    # Set A pools (P <= 8.7 d; for planets 0.5 <= P <= 8.7 d)
    a_planets_shallow = cand_toi_df[
        (cand_toi_df["tfopwg_disp"].isin(["CP", "KP"])) &
        (cand_toi_df["pl_orbper"] >= 0.5) &
        (cand_toi_df["pl_orbper"] <= 8.7) &
        (cand_toi_df["pl_trandep"] <= 2500)
    ].to_dict(orient="records")

    a_planets_rest = cand_toi_df[
        (cand_toi_df["tfopwg_disp"].isin(["CP", "KP"])) &
        (cand_toi_df["pl_orbper"] >= 0.5) &
        (cand_toi_df["pl_orbper"] <= 8.7) &
        (cand_toi_df["pl_trandep"] > 2500)
    ].to_dict(orient="records")

    a_toi_fps = cand_toi_df[
        (cand_toi_df["tfopwg_disp"] == "FP") &
        (cand_toi_df["pl_orbper"] <= 8.7)
    ].to_dict(orient="records")

    a_prsa_ebs = cand_prsa_df[
        (cand_prsa_df["period"] <= 8.7)
    ].to_dict(orient="records")

    # Shuffle pools with the protocol seed
    def shuffle_pool(pool):
        copied = list(pool)
        rng.shuffle(copied)
        return copied

    b_planets_shuffled = shuffle_pool(b_planets)
    b_toi_fps_shuffled = shuffle_pool(b_toi_fps)
    b_prsa_ebs_shuffled = shuffle_pool(b_prsa_ebs)

    a_shallow_shuffled = shuffle_pool(a_planets_shallow)
    a_rest_shuffled = shuffle_pool(a_planets_rest)
    a_toi_fps_shuffled = shuffle_pool(a_toi_fps)
    a_prsa_ebs_shuffled = shuffle_pool(a_prsa_ebs)

    # Global tracking of selected TIC IDs to guarantee uniqueness & disjointness
    used_tics = set(burned_ids | dev_ids | survey_tics)

    # -------------------------------------------------------------
    # Select Set B (30 planets, 15 TOI FPs, 15 Prsa EBs; all n_sectors >= 2)
    # -------------------------------------------------------------
    # Query observations and TIC parameters in batches
    probe_b_planets = [c["tid_int"] for c in b_planets_shuffled[:60]]
    probe_b_fps = [c["tid_int"] for c in b_toi_fps_shuffled[:40]]
    probe_b_ebs = [c["tid_int"] for c in b_prsa_ebs_shuffled[:40]]
    all_probe_b = probe_b_planets + probe_b_fps + probe_b_ebs

    obs_b = query_spoc_observations_batch(all_probe_b)
    params_b = query_tic_parameters_batch(all_probe_b)

    selected_b_planets = []
    for cand in b_planets_shuffled:
        if len(selected_b_planets) == 30:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_b.get(tid, [])
        unique_secs = {s["sector"]: s for s in secs}
        if len(unique_secs) >= 2 and tid in params_b:
            selected_b_planets.append((cand, "TOI"))
            used_tics.add(tid)

    selected_b_fps = []
    for cand in b_toi_fps_shuffled:
        if len(selected_b_fps) == 15:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_b.get(tid, [])
        unique_secs = {s["sector"]: s for s in secs}
        if len(unique_secs) >= 2 and tid in params_b:
            selected_b_fps.append((cand, "TOI"))
            used_tics.add(tid)

    selected_b_ebs = []
    for cand in b_prsa_ebs_shuffled:
        if len(selected_b_ebs) == 15:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_b.get(tid, [])
        unique_secs = {s["sector"]: s for s in secs}
        if len(unique_secs) >= 2 and tid in params_b:
            selected_b_ebs.append((cand, "PRSA"))
            used_tics.add(tid)

    if len(selected_b_planets) != 30:
        raise RuntimeError(f"Could not select 30 Set B planets (got {len(selected_b_planets)})")
    if len(selected_b_fps) != 15:
        raise RuntimeError(f"Could not select 15 Set B TOI FPs (got {len(selected_b_fps)})")
    if len(selected_b_ebs) != 15:
        raise RuntimeError(f"Could not select 15 Set B Prsa EBs (got {len(selected_b_ebs)})")

    # -------------------------------------------------------------
    # Select Set A (30 planets [>=10 shallow <= 2500 ppm], 15 TOI FPs, 15 Prsa EBs)
    # -------------------------------------------------------------
    probe_a_shallow = [c["tid_int"] for c in a_shallow_shuffled[:30] if c["tid_int"] not in used_tics]
    probe_a_rest = [c["tid_int"] for c in a_rest_shuffled[:40] if c["tid_int"] not in used_tics]
    probe_a_fps = [c["tid_int"] for c in a_toi_fps_shuffled[:35] if c["tid_int"] not in used_tics]
    probe_a_ebs = [c["tid_int"] for c in a_prsa_ebs_shuffled[:35] if c["tid_int"] not in used_tics]
    all_probe_a = probe_a_shallow + probe_a_rest + probe_a_fps + probe_a_ebs

    obs_a = query_spoc_observations_batch(all_probe_a)
    params_a = query_tic_parameters_batch(all_probe_a)

    selected_a_planets = []
    # 1. At least 10 shallow planets
    for cand in a_shallow_shuffled:
        if len(selected_a_planets) == 10:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a:
            selected_a_planets.append((cand, "TOI"))
            used_tics.add(tid)

    # 2. Remaining 20 planets (from rest, or shallow if rest runs out)
    for cand in a_rest_shuffled:
        if len(selected_a_planets) == 30:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a:
            selected_a_planets.append((cand, "TOI"))
            used_tics.add(tid)

    if len(selected_a_planets) < 30:
        for cand in a_shallow_shuffled:
            if len(selected_a_planets) == 30:
                break
            tid = cand["tid_int"]
            if tid in used_tics:
                continue
            secs = obs_a.get(tid, [])
            if len(secs) >= 1 and tid in params_a:
                selected_a_planets.append((cand, "TOI"))
                used_tics.add(tid)

    selected_a_fps = []
    for cand in a_toi_fps_shuffled:
        if len(selected_a_fps) == 15:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a:
            selected_a_fps.append((cand, "TOI"))
            used_tics.add(tid)

    selected_a_ebs = []
    for cand in a_prsa_ebs_shuffled:
        if len(selected_a_ebs) == 15:
            break
        tid = cand["tid_int"]
        if tid in used_tics:
            continue
        secs = obs_a.get(tid, [])
        if len(secs) >= 1 and tid in params_a:
            selected_a_ebs.append((cand, "PRSA"))
            used_tics.add(tid)

    if len(selected_a_planets) != 30:
        raise RuntimeError(f"Could not select 30 Set A planets (got {len(selected_a_planets)})")
    if len(selected_a_fps) != 15:
        raise RuntimeError(f"Could not select 15 Set A TOI FPs (got {len(selected_a_fps)})")
    if len(selected_a_ebs) != 15:
        raise RuntimeError(f"Could not select 15 Set A Prsa EBs (got {len(selected_a_ebs)})")

    # -------------------------------------------------------------
    # Build Record Structures
    # -------------------------------------------------------------
    rows_a = []
    for cand, kind in selected_a_planets + selected_a_fps + selected_a_ebs:
        tid = cand["tid_int"]
        p_info = params_a[tid]
        secs = sorted(obs_a[tid], key=lambda x: x["sector"])
        primary_sec = secs[0]

        if kind == "TOI":
            disp = cand["tfopwg_disp"]
            true_class = "PLANET" if disp in ["CP", "KP"] else "NON_PLANET"
            true_subclass = f"TOI_{disp}"
            period = float(cand["pl_orbper"])
            depth_ppm = float(cand["pl_trandep"])
            target_name = f"TOI {cand['toi']}"
            catalog_id = f"TOI-{cand['toi']}"
            catalog_url = f"https://exofop.ipac.caltech.edu/tess/target.php?id={tid}"
            source_catalog = f"NASA Exoplanet Archive TOI ({disp}) + TIC v8.2 (IV/39/tic82)"
        else:
            true_class = "NON_PLANET"
            true_subclass = "PRSA_EB"
            period = float(cand["period"])
            depth_ppm = float(cand["prim_depth_pf"] * 1e6)
            target_name = f"TESS-EB TIC {tid}"
            catalog_id = f"J/ApJS/258/16:TIC-{tid}"
            catalog_url = f"https://vizier.cds.unistra.fr/viz-bin/VizieR-5?-source=J/ApJS/258/16/tess-ebs&TIC={tid}"
            source_catalog = "Prsa et al. 2022 TESS EB Catalog (J/ApJS/258/16) + TIC v8.2 (IV/39/tic82)"

        rows_a.append({
            "target_name": target_name,
            "tic_id": tid,
            "true_class": true_class,
            "true_subclass": true_subclass,
            "catalog_period_d": period,
            "catalog_depth_ppm": depth_ppm,
            "r_star_rsun": float(p_info["r_star_rsun"]),
            "m_star_msun": float(p_info["m_star_msun"]),
            "tmag": float(p_info["tmag"]),
            "sector": primary_sec["sector"],
            "catalog_id": catalog_id,
            "catalog_url": catalog_url,
            "source_catalog": source_catalog,
            "source_date": FETCH_DATE,
            "s3_lc_key": primary_sec["s3_key"],
            "_filename": primary_sec["filename"],
        })

    rows_b = []
    for cand, kind in selected_b_planets + selected_b_fps + selected_b_ebs:
        tid = cand["tid_int"]
        p_info = params_b[tid]
        unique_secs_map = {}
        for s in obs_b[tid]:
            if s["sector"] not in unique_secs_map:
                unique_secs_map[s["sector"]] = s
        sorted_secs = [unique_secs_map[sec] for sec in sorted(unique_secs_map.keys())]
        eval_secs = sorted_secs[:2]
        primary_sec = eval_secs[0]

        if kind == "TOI":
            disp = cand["tfopwg_disp"]
            true_class = "PLANET" if disp in ["CP", "KP"] else "NON_PLANET"
            true_subclass = f"TOI_{disp}"
            period = float(cand["pl_orbper"])
            depth_ppm = float(cand["pl_trandep"])
            target_name = f"TOI {cand['toi']}"
            catalog_id = f"TOI-{cand['toi']}"
            catalog_url = f"https://exofop.ipac.caltech.edu/tess/target.php?id={tid}"
            source_catalog = f"NASA Exoplanet Archive TOI ({disp}) + TIC v8.2 (IV/39/tic82)"
        else:
            true_class = "NON_PLANET"
            true_subclass = "PRSA_EB"
            period = float(cand["period"])
            depth_ppm = float(cand["prim_depth_pf"] * 1e6)
            target_name = f"TESS-EB TIC {tid}"
            catalog_id = f"J/ApJS/258/16:TIC-{tid}"
            catalog_url = f"https://vizier.cds.unistra.fr/viz-bin/VizieR-5?-source=J/ApJS/258/16/tess-ebs&TIC={tid}"
            source_catalog = "Prsa et al. 2022 TESS EB Catalog (J/ApJS/258/16) + TIC v8.2 (IV/39/tic82)"

        rows_b.append({
            "target_name": target_name,
            "tic_id": tid,
            "true_class": true_class,
            "true_subclass": true_subclass,
            "catalog_period_d": period,
            "catalog_depth_ppm": depth_ppm,
            "r_star_rsun": float(p_info["r_star_rsun"]),
            "m_star_msun": float(p_info["m_star_msun"]),
            "tmag": float(p_info["tmag"]),
            "sector": primary_sec["sector"],
            "catalog_id": catalog_id,
            "catalog_url": catalog_url,
            "source_catalog": source_catalog,
            "source_date": FETCH_DATE,
            "s3_lc_key": primary_sec["s3_key"],
            "n_sectors": len(eval_secs),
            "sectors": ";".join(str(s["sector"]) for s in eval_secs),
            "_eval_secs": eval_secs,
        })

    # Download FITS light curves and compute authentic SHA-256
    download_tasks = []
    for r in rows_a:
        download_tasks.append((r["s3_lc_key"], r["_filename"]))
    for r in rows_b:
        for s in r["_eval_secs"]:
            download_tasks.append((s["s3_key"], s["filename"]))

    file_hashes = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(download_fits_and_hash, key, fn): fn for key, fn in download_tasks}
        for fut in as_completed(futs):
            fn = futs[fut]
            h = fut.result()
            file_hashes[fn] = h

    for r in rows_a:
        r["fits_sha256"] = file_hashes[r["_filename"]]
        del r["_filename"]

    rows_sectors_b = []
    for r in rows_b:
        primary_fn = r["_eval_secs"][0]["filename"]
        r["fits_sha256"] = file_hashes[primary_fn]
        for s in r["_eval_secs"]:
            rows_sectors_b.append({
                "target_name": r["target_name"],
                "tic_id": r["tic_id"],
                "sector": s["sector"],
                "filename": s["filename"],
                "s3_lc_key": s["s3_key"],
                "fits_sha256": file_hashes[s["filename"]],
                "source_date": FETCH_DATE,
            })
        del r["_eval_secs"]

    # -------------------------------------------------------------
    # STRICT ASSERTIONS BEFORE WRITING ANY FILE
    # -------------------------------------------------------------
    set_a_tics = {r["tic_id"] for r in rows_a}
    set_b_tics = {r["tic_id"] for r in rows_b}
    hex64_re = re.compile(r"^[0-9a-f]{64}$")

    # 1. Total counts
    assert len(rows_a) == 60, f"Set A count mismatch: {len(rows_a)} != 60"
    assert len(rows_b) == 60, f"Set B count mismatch: {len(rows_b)} != 60"
    assert len(set_a_tics) == 60, f"Set A duplicate TICs: {len(set_a_tics)}"
    assert len(set_b_tics) == 60, f"Set B duplicate TICs: {len(set_b_tics)}"

    # 2. Exclusions and Disjointness
    assert len(set_a_tics & burned_ids) == 0, "Set A overlaps with burned IDs"
    assert len(set_b_tics & burned_ids) == 0, "Set B overlaps with burned IDs"
    assert len(set_a_tics & dev_ids) == 0, "Set A overlaps with dev benchmark"
    assert len(set_b_tics & dev_ids) == 0, "Set B overlaps with dev benchmark"
    assert len(set_a_tics & survey_tics) == 0, "Set A overlaps with survey footprint"
    assert len(set_b_tics & survey_tics) == 0, "Set B overlaps with survey footprint"
    assert len(set_a_tics & set_b_tics) == 0, "Set A overlaps with Set B"

    # 3. Period constraints
    assert all(r["catalog_period_d"] <= 8.7 for r in rows_a), "Set A row with P > 8.7 d"
    assert all(r["catalog_period_d"] >= 0.5 for r in rows_a if r["true_class"] == "PLANET"), "Set A planet P < 0.5 d"
    assert all(8.7 < r["catalog_period_d"] <= 20.0 for r in rows_b), "Set B row out of period range (8.7, 20.0]"

    # 4. Class & Subclass constraints
    # Set A
    assert sum(1 for r in rows_a if r["true_class"] == "PLANET") == 30, "Set A != 30 planets"
    assert sum(1 for r in rows_a if r["true_class"] == "NON_PLANET") == 30, "Set A != 30 non-planets"
    assert sum(1 for r in rows_a if r["true_subclass"] == "TOI_FP") == 15, "Set A != 15 TOI_FP"
    assert sum(1 for r in rows_a if r["true_subclass"] == "PRSA_EB") == 15, "Set A != 15 PRSA_EB"
    assert sum(1 for r in rows_a if r["true_class"] == "PLANET" and r["catalog_depth_ppm"] <= 2500) >= 10, "Set A < 10 shallow planets"

    # Set B
    assert sum(1 for r in rows_b if r["true_class"] == "PLANET") == 30, "Set B != 30 planets"
    assert sum(1 for r in rows_b if r["true_class"] == "NON_PLANET") == 30, "Set B != 30 non-planets"
    assert sum(1 for r in rows_b if r["true_subclass"] == "TOI_FP") == 15, "Set B != 15 TOI_FP"
    assert sum(1 for r in rows_b if r["true_subclass"] == "PRSA_EB") == 15, "Set B != 15 PRSA_EB"
    assert all(r["n_sectors"] >= 2 for r in rows_b), "Set B row has n_sectors < 2"

    # 5. Brightness & Stellar parameters
    assert all(r["tmag"] <= 13.0 for r in rows_a + rows_b), "Target with Tmag > 13.0"
    assert all(r["r_star_rsun"] > 0 and r["m_star_msun"] > 0 for r in rows_a + rows_b), "Missing stellar params"

    # 6. Hashes
    assert all(hex64_re.match(r["fits_sha256"]) for r in rows_a + rows_b), "Invalid primary SHA-256"
    assert all(hex64_re.match(r["fits_sha256"]) for r in rows_sectors_b), "Invalid sector SHA-256"

    # -------------------------------------------------------------
    # Write CSVs
    # -------------------------------------------------------------
    out_dir = os.path.join(base_dir, "benchmark_v2")
    df_a = pd.DataFrame(rows_a)
    df_b = pd.DataFrame(rows_b)
    df_sec_b = pd.DataFrame(rows_sectors_b)

    df_a.to_csv(os.path.join(out_dir, "targets_set_a.csv"), index=False)
    df_b.to_csv(os.path.join(out_dir, "targets_set_b.csv"), index=False)
    df_sec_b.to_csv(os.path.join(out_dir, "sectors_set_b.csv"), index=False)

    # Output requirement: Prints ONLY counts
    print(f"Set A: {len(df_a)} targets (30 planets [{sum(df_a['catalog_depth_ppm'] <= 2500)} shallow], 15 TOI_FP, 15 PRSA_EB)")
    print(f"Set B: {len(df_b)} targets (30 planets, 15 TOI_FP, 15 PRSA_EB, min_sectors={df_b['n_sectors'].min()})")
    print(f"Set B sectors: {len(df_sec_b)} sector files")
    print(f"Exclusion overlaps: burned={len(set_a_tics & burned_ids) + len(set_b_tics & burned_ids)}, "
          f"dev={len(set_a_tics & dev_ids) + len(set_b_tics & dev_ids)}, "
          f"survey={len(set_a_tics & survey_tics) + len(set_b_tics & survey_tics)}, "
          f"A-vs-B={len(set_a_tics & set_b_tics)}")


if __name__ == "__main__":
    main()
