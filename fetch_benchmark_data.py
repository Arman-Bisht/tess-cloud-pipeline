"""
fetch_benchmark_data.py — Reproducible downloader for the Astrohunter Pro Held-Out External TESS Benchmark.

Reads `benchmark/targets.csv` (confirmed TESS exoplanets, TOI false positives, and Prsa et al. 2022
TESS eclipsing binaries) and downloads each target's official NASA TESS SPOC 2-minute light curve
FITS file from the STScI AWS Open Data mirror (`https://s3.amazonaws.com/stpubdata/...`, with
MAST fallback and strict 30-second socket timeouts) into the local Lightkurve cache.
"""
import os
import sys
import socket
import argparse
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

BENCHMARK_TIMEOUT_SECONDS = 30
socket.setdefaulttimeout(BENCHMARK_TIMEOUT_SECONDS)


def fetch_single_target_fits(row, cache_base: str, timeout: int = BENCHMARK_TIMEOUT_SECONDS) -> dict:
    """Download or verify a single benchmark target's TESS SPOC FITS light curve."""
    tic_id = int(row["tic_id"])
    target_name = str(row["target_name"])
    s3_lc_key = str(row["s3_lc_key"]).strip()
    sector = int(row["sector"])

    fname = os.path.basename(s3_lc_key)
    stem = fname.replace("_lc.fits", "")
    dest_dir = os.path.join(cache_base, stem)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, fname)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) >= 10000:
        return {"tic_id": tic_id, "target_name": target_name, "path": dest_path, "status": "CACHED"}

    # Primary: Official STScI AWS Open Data S3 mirror
    s3_url = f"https://s3.amazonaws.com/stpubdata/{s3_lc_key}"
    try:
        resp = requests.get(s3_url, timeout=timeout)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        if os.path.getsize(dest_path) >= 10000:
            return {"tic_id": tic_id, "target_name": target_name, "path": dest_path, "status": "DOWNLOADED_S3"}
    except Exception as s3_err:
        # Fallback: MAST direct download API
        mast_url = f"https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:TESS/product/{fname}"
        try:
            resp = requests.get(mast_url, timeout=timeout)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            if os.path.getsize(dest_path) >= 10000:
                return {"tic_id": tic_id, "target_name": target_name, "path": dest_path, "status": "DOWNLOADED_MAST"}
        except Exception as mast_err:
            raise RuntimeError(
                f"Failed to download {target_name} (TIC {tic_id}, Sector {sector}) "
                f"from AWS S3 ({s3_err}) and MAST ({mast_err})"
            ) from mast_err

    raise RuntimeError(f"Downloaded file for {target_name} (TIC {tic_id}) is incomplete: {dest_path}")


def fetch_all_benchmark_data(
    targets_csv: str = None,
    cache_base: str = None,
    max_workers: int = 8,
) -> list:
    """Download all benchmark FITS light curves listed in `benchmark/targets.csv`."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if targets_csv is None:
        targets_csv = os.path.join(base_dir, "benchmark", "targets.csv")
    if cache_base is None:
        cache_base = os.path.expanduser("~/.cache/lightkurve/mastDownload/TESS")

    if not os.path.exists(targets_csv):
        raise FileNotFoundError(f"Benchmark targets file not found: {targets_csv}")

    df = pd.read_csv(targets_csv)
    n_rows = len(df)
    os.makedirs(cache_base, exist_ok=True)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(fetch_single_target_fits, row, cache_base): row["target_name"]
            for _, row in df.iterrows()
        }
        for fut in as_completed(futs):
            res = fut.result()
            results.append(res)

    if len(results) != n_rows:
        raise RuntimeError(f"Expected {n_rows} downloaded FITS files, got {len(results)}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch TESS SPOC 2-min light curves for benchmark/targets.csv")
    parser.add_argument("--targets", default=None, help="Path to benchmark/targets.csv")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download workers (default: 8)")
    args = parser.parse_args()

    res_list = fetch_all_benchmark_data(targets_csv=args.targets, max_workers=args.workers)
    n_cached = sum(1 for r in res_list if r["status"] == "CACHED")
    n_dl = len(res_list) - n_cached
    print(f"Verified {len(res_list)}/{len(res_list)} benchmark FITS light curves ({n_cached} cached, {n_dl} newly downloaded).")
