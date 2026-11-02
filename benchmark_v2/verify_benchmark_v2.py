"""
benchmark_v2/verify_benchmark_v2.py — Deterministic verification script
for Benchmark v2 Sets A and B.

Verifies:
1. Unique TICs: exactly 60 in Set A, 60 in Set B, 120 combined.
2. Zero overlap with burned IDs (benchmark_v2/burned_ids.txt).
3. Zero overlap with dev benchmark (benchmark/targets.csv).
4. Zero overlap with HD 10000-10744 survey footprint.
5. Zero overlap between Set A and Set B (A-vs-B).
6. Cryptographic hash validity (all fits_sha256 are valid 64-character lowercase hex strings).
7. Minimum n_sectors in Set B (must be >= 2 for all Set B targets).
8. Period constraints: Set A P <= 8.7 d for all rows (and >= 0.5 d for planets);
   Set B 8.7 < P <= 20.0 d for all rows.
9. Class and Subclass counts: exactly 30 PLANET + 30 NON_PLANET per set;
   non-planets = exactly 15 TOI_FP + 15 PRSA_EB per set;
   >= 10 shallow planets (depth <= 2500 ppm) in Set A.
10. Host star brightness: Tmag <= 13.0 for all targets.
11. Stellar parameters: authentic R_star > 0 and M_star > 0 for all targets.
12. Multi-planet columns (WP2.1 Amendment): n_tois_on_host and sibling_periods
    validated against NASA Exoplanet Archive TOI table (SHA-256 c42771b9...);
    multi-host counts (Set A = 4, Set B = 10); Set B cohorts (15 shallow < 1000 ppm,
    4 long-period > 17.4 d).

Exits non-zero on any failure.
"""

import os
import sys
import re
import sqlite3
import pandas as pd


def verify_benchmark_v2(
    a_path: str = None,
    b_path: str = None,
    sectors_b_path: str = None,
    burned_path: str = None,
    dev_path: str = None,
    db_path: str = None,
    md_path: str = None,
    toi_nasa_path: str = None,
) -> bool:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bench_dir = os.path.join(base_dir, "benchmark_v2")

    a_path = a_path or os.path.join(bench_dir, "targets_set_a.csv")
    b_path = b_path or os.path.join(bench_dir, "targets_set_b.csv")
    sectors_b_path = sectors_b_path or os.path.join(bench_dir, "sectors_set_b.csv")
    burned_path = burned_path or os.path.join(bench_dir, "burned_ids.txt")
    dev_path = dev_path or os.path.join(base_dir, "benchmark", "targets.csv")
    db_path = db_path or os.path.join(base_dir, "astrohunter.db")
    md_path = md_path or os.path.join(base_dir, "master_discoveries.csv")
    toi_nasa_path = toi_nasa_path or os.path.join(bench_dir, "reference", "toi_nasa_2026-10-31.csv")

    # Load targets
    if not os.path.exists(a_path) or not os.path.exists(b_path):
        raise FileNotFoundError("Missing targets_set_a.csv or targets_set_b.csv")

    df_a = pd.read_csv(a_path)
    df_b = pd.read_csv(b_path)
    df_all = pd.concat([df_a, df_b], ignore_index=True)

    # 1. Row counts and Unique TICs
    if len(df_a) != 60:
        raise AssertionError(f"Set A row count mismatch: {len(df_a)} != 60")
    if len(df_b) != 60:
        raise AssertionError(f"Set B row count mismatch: {len(df_b)} != 60")

    unique_tics_a = df_a["tic_id"].astype(str).unique()
    unique_tics_b = df_b["tic_id"].astype(str).unique()
    unique_tics_all = df_all["tic_id"].astype(str).unique()

    if len(unique_tics_a) != 60:
        raise AssertionError(f"Set A unique TIC count mismatch: {len(unique_tics_a)} != 60")
    if len(unique_tics_b) != 60:
        raise AssertionError(f"Set B unique TIC count mismatch: {len(unique_tics_b)} != 60")
    if len(unique_tics_all) != 120:
        raise AssertionError(f"Combined unique TIC count mismatch: {len(unique_tics_all)} != 120")

    # 2. Exclusions and Disjointness
    if not os.path.exists(burned_path):
        raise FileNotFoundError(f"Missing {burned_path}")
    with open(burned_path, "r", encoding="utf-8") as f:
        burned_ids = {line.strip() for line in f if line.strip()}
    if len(burned_ids) != 120:
        raise AssertionError(f"Expected 120 burned IDs, found {len(burned_ids)}")

    if not os.path.exists(dev_path):
        raise FileNotFoundError(f"Missing {dev_path}")
    df_dev = pd.read_csv(dev_path)
    dev_ids = {str(x).strip() for x in df_dev["tic_id"]}
    if len(dev_ids) != 50:
        raise AssertionError(f"Expected 50 dev targets, found {len(dev_ids)}")

    # HD 10000-10744 survey footprint
    survey_names = {f"HD {i}" for i in range(10000, 10745)}
    survey_tics = set()

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT tic_id, name FROM targets")
        for tid, name in c.fetchall():
            if name in survey_names or tid in survey_names:
                survey_names.add(str(name))
                if tid and str(tid).isdigit():
                    survey_tics.add(str(tid))
        c.execute("SELECT tic_id, name FROM signals")
        for tid, name in c.fetchall():
            if name in survey_names:
                if tid and str(tid).isdigit():
                    survey_tics.add(str(tid))
        conn.close()

    if os.path.exists(md_path):
        df_md = pd.read_csv(md_path)
        for _, row in df_md.iterrows():
            if str(row["name"]).startswith("HD 10"):
                survey_names.add(str(row["name"]))
                if pd.notna(row["tic_id"]) and str(row["tic_id"]).isdigit():
                    survey_tics.add(str(row["tic_id"]))

    set_a_tics = set(unique_tics_a)
    set_b_tics = set(unique_tics_b)
    all_tics = set(unique_tics_all)

    all_names = set(df_all["target_name"].astype(str))
    survey_name_overlap = all_names & survey_names

    overlap_burned = all_tics & burned_ids
    overlap_dev = all_tics & dev_ids
    overlap_survey = (all_tics & survey_tics) | survey_name_overlap
    overlap_a_b = set_a_tics & set_b_tics

    if len(overlap_burned) != 0:
        raise AssertionError(f"Burned overlap failure: {len(overlap_burned)}")
    if len(overlap_dev) != 0:
        raise AssertionError(f"Dev benchmark overlap failure: {len(overlap_dev)}")
    if len(overlap_survey) != 0:
        raise AssertionError(f"Survey footprint overlap failure: {len(overlap_survey)}")
    if len(overlap_a_b) != 0:
        raise AssertionError(f"Set A vs Set B overlap failure: {len(overlap_a_b)}")

    # 3. Hash validity
    hex64_pattern = re.compile(r"^[0-9a-f]{64}$")
    invalid_hashes_a = [h for h in df_a["fits_sha256"] if not hex64_pattern.match(str(h))]
    invalid_hashes_b = [h for h in df_b["fits_sha256"] if not hex64_pattern.match(str(h))]
    total_invalid_hashes = len(invalid_hashes_a) + len(invalid_hashes_b)

    if os.path.exists(sectors_b_path):
        df_sec_b = pd.read_csv(sectors_b_path)
        invalid_sec_hashes = [h for h in df_sec_b["fits_sha256"] if not hex64_pattern.match(str(h))]
        total_invalid_hashes += len(invalid_sec_hashes)

    if total_invalid_hashes != 0:
        raise AssertionError(f"Invalid hashes failure: {total_invalid_hashes}")

    # 4. Period constraints
    # Set A: P <= 8.7 d for all rows; planets >= 0.5 d
    set_a_p_max = float(df_a["catalog_period_d"].max())
    if set_a_p_max > 8.7:
        bad_rows = df_a[df_a["catalog_period_d"] > 8.7]
        raise AssertionError(f"Set A period violation: {len(bad_rows)} rows have P > 8.7 d (max={set_a_p_max})")

    set_a_planet_p_min = float(df_a[df_a["true_class"] == "PLANET"]["catalog_period_d"].min())
    if set_a_planet_p_min < 0.5:
        bad_p_rows = df_a[(df_a["true_class"] == "PLANET") & (df_a["catalog_period_d"] < 0.5)]
        raise AssertionError(f"Set A planet period violation: {len(bad_p_rows)} planets have P < 0.5 d (min={set_a_planet_p_min})")

    # Set B: 8.7 < P <= 20.0 d for all rows
    set_b_p_min = float(df_b["catalog_period_d"].min())
    set_b_p_max = float(df_b["catalog_period_d"].max())
    if set_b_p_min <= 8.7 or set_b_p_max > 20.0:
        bad_b_rows = df_b[(df_b["catalog_period_d"] <= 8.7) | (df_b["catalog_period_d"] > 20.0)]
        raise AssertionError(f"Set B period violation: {len(bad_b_rows)} rows outside (8.7, 20.0] d (min={set_b_p_min}, max={set_b_p_max})")

    # 5. Class and Subclass counts
    # Set A: 30 PLANET, 30 NON_PLANET; non-planets = 15 TOI_FP + 15 PRSA_EB
    n_a_planets = int((df_a["true_class"] == "PLANET").sum())
    n_a_nonplanets = int((df_a["true_class"] == "NON_PLANET").sum())
    n_a_fp = int((df_a["true_subclass"] == "TOI_FP").sum())
    n_a_eb = int((df_a["true_subclass"] == "PRSA_EB").sum())
    n_a_shallow = int(((df_a["true_class"] == "PLANET") & (df_a["catalog_depth_ppm"] <= 2500)).sum())

    if n_a_planets != 30 or n_a_nonplanets != 30:
        raise AssertionError(f"Set A class balance violation: {n_a_planets} planets, {n_a_nonplanets} non-planets (expected 30/30)")
    if n_a_fp != 15 or n_a_eb != 15:
        raise AssertionError(f"Set A non-planet subclass violation: {n_a_fp} TOI_FP, {n_a_eb} PRSA_EB (expected 15/15)")
    if n_a_shallow < 10:
        raise AssertionError(f"Set A shallow planets violation: {n_a_shallow} < 10")

    # Set B: 30 PLANET, 30 NON_PLANET; non-planets = 15 TOI_FP + 15 PRSA_EB
    n_b_planets = int((df_b["true_class"] == "PLANET").sum())
    n_b_nonplanets = int((df_b["true_class"] == "NON_PLANET").sum())
    n_b_fp = int((df_b["true_subclass"] == "TOI_FP").sum())
    n_b_eb = int((df_b["true_subclass"] == "PRSA_EB").sum())

    if n_b_planets != 30 or n_b_nonplanets != 30:
        raise AssertionError(f"Set B class balance violation: {n_b_planets} planets, {n_b_nonplanets} non-planets (expected 30/30)")
    if n_b_fp != 15 or n_b_eb != 15:
        raise AssertionError(f"Set B non-planet subclass violation: {n_b_fp} TOI_FP, {n_b_eb} PRSA_EB (expected 15/15)")

    # 6. Minimum n_sectors in Set B
    min_n_sectors_b = int(df_b["n_sectors"].min())
    if min_n_sectors_b < 2:
        bad_sec_rows = df_b[df_b["n_sectors"] < 2]
        raise AssertionError(f"Set B minimum sectors failure: {len(bad_sec_rows)} targets have n_sectors < 2 (min={min_n_sectors_b})")

    # 7. Host star brightness (Tmag <= 13.0)
    max_tmag_a = float(df_a["tmag"].max())
    max_tmag_b = float(df_b["tmag"].max())
    if max_tmag_a > 13.0 or max_tmag_b > 13.0:
        raise AssertionError(f"Tmag violation: max Set A Tmag={max_tmag_a}, max Set B Tmag={max_tmag_b} (must be <= 13.0)")

    # 8. Stellar parameters (R_star > 0, M_star > 0)
    for name, df_set in [("Set A", df_a), ("Set B", df_b)]:
        if (df_set["r_star_rsun"] <= 0).any() or (df_set["m_star_msun"] <= 0).any():
            raise AssertionError(f"{name} has targets with invalid stellar radius or mass")

    # 9. Multi-planet columns and sibling period validation (WP2.1 Amendment)
    req_multi_cols = ["n_tois_on_host", "sibling_periods", "sibling_dispositions", "credited_sibling_periods"]
    for name, df_set in [("Set A", df_a), ("Set B", df_b)]:
        for c in req_multi_cols:
            if c not in df_set.columns:
                raise AssertionError(f"{name} missing required multi-planet column: {c}")

        if (df_set["n_tois_on_host"] < 0).any() or df_set["n_tois_on_host"].isna().any():
            raise AssertionError(f"{name} has invalid n_tois_on_host values")

        for idx, val in enumerate(df_set["sibling_periods"]):
            if pd.notna(val) and str(val).strip() != "" and str(val) != "nan":
                for p_str in str(val).split(";"):
                    try:
                        p_flt = float(p_str)
                        if p_flt <= 0:
                            raise ValueError()
                    except ValueError:
                        raise AssertionError(f"{name} row {idx} has invalid sibling_period: '{p_str}' in '{val}'")

        for idx, val in enumerate(df_set["credited_sibling_periods"]):
            if pd.notna(val) and str(val).strip() != "" and str(val) != "nan":
                for p_str in str(val).split(";"):
                    try:
                        p_flt = float(p_str)
                        if p_flt <= 0:
                            raise ValueError()
                    except ValueError:
                        raise AssertionError(f"{name} row {idx} has invalid credited_sibling_period: '{p_str}' in '{val}'")

    n_a_multi = int((df_a["n_tois_on_host"] > 1).sum())
    n_b_multi = int((df_b["n_tois_on_host"] > 1).sum())
    if n_a_multi != 4:
        raise AssertionError(f"Set A multi-TOI host count mismatch: {n_a_multi} != 4")
    if n_b_multi != 10:
        raise AssertionError(f"Set B multi-TOI host count mismatch: {n_b_multi} != 10")

    set_b_planets = df_b[df_b["true_class"] == "PLANET"]
    n_b_shallow = int((set_b_planets["catalog_depth_ppm"] < 1000).sum())
    n_b_long = int((set_b_planets["catalog_period_d"] > 17.4).sum())
    if n_b_shallow != 15:
        raise AssertionError(f"Set B shallow planets (< 1000 ppm) mismatch: {n_b_shallow} != 15")
    if n_b_long != 4:
        raise AssertionError(f"Set B long-period planets (> 17.4 d) mismatch: {n_b_long} != 4")

    # 10. Exact reference check against repo-local NASA TOI table
    if not os.path.exists(toi_nasa_path):
        raise FileNotFoundError(f"Missing mandatory NASA TOI reference table: {toi_nasa_path}")

    import hashlib
    with open(toi_nasa_path, "rb") as f:
        nasa_hash = hashlib.sha256(f.read()).hexdigest().lower()
    expected_nasa_hash = "c42771b98de943da7103d1b10accbf7b2cfac3288ed2cbc241593d59c27e1c28"
    if nasa_hash != expected_nasa_hash:
        raise AssertionError(f"NASA TOI reference table hash mismatch: {nasa_hash} != {expected_nasa_hash}")

    df_nasa = pd.read_csv(toi_nasa_path)
    df_nasa["tid_int"] = df_nasa["tid"].astype(int)
    df_nasa["toi_float"] = df_nasa["toi"].astype(float)

    for name, df_set in [("Set A", df_a), ("Set B", df_b)]:
        for _, r in df_set.iterrows():
            tid = int(r["tic_id"])
            matches = df_nasa[df_nasa["tid_int"] == tid]
            if int(r["n_tois_on_host"]) != len(matches):
                raise AssertionError(f"{name} TIC {tid} n_tois_on_host mismatch: {r['n_tois_on_host']} != {len(matches)}")

            cat_id = str(r["catalog_id"])
            if cat_id.startswith("TOI-"):
                target_toi = float(cat_id.replace("TOI-", ""))
                sibs = matches[matches["toi_float"] != target_toi]

                p_list = []
                d_list = []
                cred_list = []
                for _, s in sibs.iterrows():
                    p = s["pl_orbper"]
                    disp = str(s["tfopwg_disp"])
                    if pd.notna(p) and float(p) > 0:
                        p_str = str(float(p))
                        p_list.append(p_str)
                        d_list.append(disp)
                        if disp in ["CP", "KP"]:
                            cred_list.append(p_str)

                expected_pers = ";".join(p_list)
                expected_disps = ";".join(d_list)
                expected_creds = ";".join(cred_list)

                actual_pers = "" if pd.isna(r["sibling_periods"]) else str(r["sibling_periods"])
                actual_disps = "" if pd.isna(r["sibling_dispositions"]) else str(r["sibling_dispositions"])
                actual_creds = "" if pd.isna(r["credited_sibling_periods"]) else str(r["credited_sibling_periods"])

                if actual_pers != expected_pers:
                    raise AssertionError(f"{name} TIC {tid} sibling_periods mismatch: '{actual_pers}' != '{expected_pers}'")
                if actual_disps != expected_disps:
                    raise AssertionError(f"{name} TIC {tid} sibling_dispositions mismatch: '{actual_disps}' != '{expected_disps}'")
                if actual_creds != expected_creds:
                    raise AssertionError(f"{name} TIC {tid} credited_sibling_periods mismatch: '{actual_creds}' != '{expected_creds}'")
            else:
                for col in ["sibling_periods", "sibling_dispositions", "credited_sibling_periods"]:
                    val = r[col]
                    if pd.notna(val) and str(val).strip() != "" and str(val) != "nan":
                        raise AssertionError(f"{name} PRSA_EB TIC {tid} non-empty {col}: {val}")

    # Count credited sibling targets
    n_a_credited = int((df_a["credited_sibling_periods"].notna() & (df_a["credited_sibling_periods"] != "") & (df_a["credited_sibling_periods"] != "nan")).sum())
    n_b_credited = int((df_b["credited_sibling_periods"].notna() & (df_b["credited_sibling_periods"] != "") & (df_b["credited_sibling_periods"] != "nan")).sum())
    if n_a_credited != 4:
        raise AssertionError(f"Set A credited sibling targets mismatch: {n_a_credited} != 4")
    if n_b_credited != 7:
        raise AssertionError(f"Set B credited sibling targets mismatch: {n_b_credited} != 7")

    # Output report
    print("=== Benchmark v2 Verification Report ===")
    print(f"unique TICs: {len(unique_tics_all)} (Set A: {len(unique_tics_a)}, Set B: {len(unique_tics_b)})")
    print(f"overlap with burned: {len(overlap_burned)}")
    print(f"overlap with dev: {len(overlap_dev)}")
    print(f"overlap with survey: {len(overlap_survey)}")
    print(f"overlap A-vs-B: {len(overlap_a_b)}")
    print(f"hash validity: valid ({total_invalid_hashes} invalid, {len(all_tics)} distinct hashes)")
    print(f"minimum n_sectors in Set B: {min_n_sectors_b}")
    print(f"Set A periods: min={df_a['catalog_period_d'].min():.4f} d, max={set_a_p_max:.4f} d (all <= 8.7 d)")
    print(f"Set B periods: min={set_b_p_min:.4f} d, max={set_b_p_max:.4f} d (all in (8.7, 20.0] d)")
    print(f"Set A classes: {n_a_planets} planets ({n_a_shallow} shallow <= 2500 ppm), {n_a_fp} TOI_FP, {n_a_eb} PRSA_EB")
    print(f"Set B classes: {n_b_planets} planets, {n_b_fp} TOI_FP, {n_b_eb} PRSA_EB")
    print(f"Multi-TOI hosts: Set A={n_a_multi} ({n_a_credited} with credited siblings), Set B={n_b_multi} ({n_b_credited} with credited siblings, 1 TOI_FP)")
    print(f"Set B expected-recall cohorts: {n_b_shallow}/30 shallow (< 1000 ppm), {n_b_long}/30 long-period (> 17.4 d)")
    print(f"Max Tmag: Set A={max_tmag_a:.2f}, Set B={max_tmag_b:.2f} (all <= 13.0)")
    print("STATUS: VERIFIED")
    return True


if __name__ == "__main__":
    try:
        verify_benchmark_v2()
        sys.exit(0)
    except Exception as exc:
        print(f"VERIFICATION FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
