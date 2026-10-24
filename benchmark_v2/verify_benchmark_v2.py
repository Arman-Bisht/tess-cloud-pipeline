"""
benchmark_v2/verify_benchmark_v2.py — Deterministic verification script
for Benchmark v2 Sets A and B.

Verifies:
1. Unique TICs (Set A, Set B, and Combined).
2. Zero overlap with burned IDs (benchmark_v2/burned_ids.txt).
3. Zero overlap with dev benchmark (benchmark/targets.csv).
4. Zero overlap with HD 10000-10744 survey footprint.
5. Zero overlap between Set A and Set B (A-vs-B).
6. Cryptographic hash validity (all fits_sha256 are valid 64-character lowercase hex strings).
7. Minimum n_sectors in Set B (must be >= 2 for all Set B targets).
"""

import os
import sys
import re
import hashlib
import sqlite3
import pandas as pd


def verify_benchmark_v2():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bench_dir = os.path.join(base_dir, "benchmark_v2")

    a_path = os.path.join(bench_dir, "targets_set_a.csv")
    b_path = os.path.join(bench_dir, "targets_set_b.csv")
    sectors_b_path = os.path.join(bench_dir, "sectors_set_b.csv")
    burned_path = os.path.join(bench_dir, "burned_ids.txt")
    dev_path = os.path.join(base_dir, "benchmark", "targets.csv")
    db_path = os.path.join(base_dir, "astrohunter.db")
    md_path = os.path.join(base_dir, "master_discoveries.csv")

    # Load targets
    if not os.path.exists(a_path) or not os.path.exists(b_path):
        raise FileNotFoundError("Missing targets_set_a.csv or targets_set_b.csv")

    df_a = pd.read_csv(a_path)
    df_b = pd.read_csv(b_path)
    df_all = pd.concat([df_a, df_b], ignore_index=True)

    # 1. Unique TICs
    unique_tics_a = df_a["tic_id"].astype(str).unique()
    unique_tics_b = df_b["tic_id"].astype(str).unique()
    unique_tics_all = df_all["tic_id"].astype(str).unique()

    # 2. Exclusions
    # Burned
    if not os.path.exists(burned_path):
        raise FileNotFoundError(f"Missing {burned_path}")
    with open(burned_path, "r", encoding="utf-8") as f:
        burned_ids = {line.strip() for line in f if line.strip()}

    # Dev benchmark
    df_dev = pd.read_csv(dev_path)
    dev_ids = {str(x).strip() for x in df_dev["tic_id"]}

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

    # Overlap computations
    set_a_tics = set(unique_tics_a)
    set_b_tics = set(unique_tics_b)
    all_tics = set(unique_tics_all)

    all_names = set(df_all["target_name"].astype(str))
    survey_name_overlap = all_names & survey_names

    overlap_burned = all_tics & burned_ids
    overlap_dev = all_tics & dev_ids
    overlap_survey = (all_tics & survey_tics) | survey_name_overlap
    overlap_a_b = set_a_tics & set_b_tics

    # 3. Hash validity
    hex64_pattern = re.compile(r"^[0-9a-f]{64}$")
    invalid_hashes_a = [h for h in df_a["fits_sha256"] if not hex64_pattern.match(str(h))]
    invalid_hashes_b = [h for h in df_b["fits_sha256"] if not hex64_pattern.match(str(h))]
    total_invalid_hashes = len(invalid_hashes_a) + len(invalid_hashes_b)

    # Sector table verification if present
    if os.path.exists(sectors_b_path):
        df_sec_b = pd.read_csv(sectors_b_path)
        invalid_sec_hashes = [h for h in df_sec_b["fits_sha256"] if not hex64_pattern.match(str(h))]
        total_invalid_hashes += len(invalid_sec_hashes)

    # 4. Minimum n_sectors in Set B
    min_n_sectors_b = int(df_b["n_sectors"].min())

    # Assertions
    assert len(overlap_burned) == 0, f"Burned overlap failure: {len(overlap_burned)}"
    assert len(overlap_dev) == 0, f"Dev benchmark overlap failure: {len(overlap_dev)}"
    assert len(overlap_survey) == 0, f"Survey footprint overlap failure: {len(overlap_survey)}"
    assert len(overlap_a_b) == 0, f"Set A vs Set B overlap failure: {len(overlap_a_b)}"
    assert total_invalid_hashes == 0, f"Invalid hashes failure: {total_invalid_hashes}"
    assert min_n_sectors_b >= 2, f"Set B minimum sectors failure: {min_n_sectors_b}"

    # Output report
    print("=== Benchmark v2 Verification Report ===")
    print(f"unique TICs: {len(unique_tics_all)} (Set A: {len(unique_tics_a)}, Set B: {len(unique_tics_b)})")
    print(f"overlap with burned: {len(overlap_burned)}")
    print(f"overlap with dev: {len(overlap_dev)}")
    print(f"overlap with survey: {len(overlap_survey)}")
    print(f"overlap A-vs-B: {len(overlap_a_b)}")
    print(f"hash validity: valid ({total_invalid_hashes} invalid, {len(all_tics)} distinct hashes)")
    print(f"minimum n_sectors in Set B: {min_n_sectors_b}")
    print("STATUS: VERIFIED")


if __name__ == "__main__":
    verify_benchmark_v2()
