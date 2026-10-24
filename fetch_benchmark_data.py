"""
fetch_benchmark_data.py — Reproducible downloader for the Astrohunter Pro Held-Out External TESS Benchmark.

Reads target CSVs (`benchmark/targets.csv` or `benchmark_v2/*.csv`) and downloads each target's official
NASA TESS SPOC 2-minute light curve FITS file from the STScI AWS Open Data mirror
(`https://s3.amazonaws.com/stpubdata/...`, with MAST fallback and strict 30-second socket timeouts)
into the local Lightkurve cache (`~/.cache/lightkurve/mastDownload/TESS/<stem>/<filename>`).

Supports `--verify` mode to report per-file MATCH, MISMATCH, or MISSING status without downloading.
"""
import os
import sys
import socket
import hashlib
import argparse
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

BENCHMARK_TIMEOUT_SECONDS = 30
socket.setdefaulttimeout(BENCHMARK_TIMEOUT_SECONDS)


def compute_file_sha256(filepath: str) -> str:
    """Compute SHA-256 hexadecimal digest of a file on disk."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_benchmark_hashes(
    targets_csv: str = None,
    cache_base: str = None,
) -> dict:
    """Verify local cached FITS files against SHA-256 hashes recorded in targets_csv."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if targets_csv is None:
        targets_csv = os.path.join(base_dir, "benchmark", "targets.csv")
    if cache_base is None:
        cache_base = os.path.expanduser("~/.cache/lightkurve/mastDownload/TESS")

    if not os.path.exists(targets_csv):
        raise FileNotFoundError(f"Benchmark targets file not found: {targets_csv}")

    df = pd.read_csv(targets_csv)
    has_hash_col = "fits_sha256" in df.columns

    results = []
    for _, row in df.iterrows():
        target_name = str(row.get("target_name", f"TIC {row.get('tic_id', 'unknown')}"))
        tic_id = row.get("tic_id", "")
        s3_key = str(row.get("s3_lc_key", "")).strip()
        fname = os.path.basename(s3_key)
        stem = fname.replace("_lc.fits", "")
        file_path = os.path.join(cache_base, stem, fname)

        expected_hash = str(row["fits_sha256"]).strip() if has_hash_col and pd.notna(row["fits_sha256"]) else None

        if not os.path.exists(file_path):
            status = "MISSING"
            actual_hash = None
        else:
            actual_hash = compute_file_sha256(file_path)
            if expected_hash:
                status = "MATCH" if actual_hash == expected_hash else "MISMATCH"
            else:
                status = "EXISTS_NO_HASH"

        results.append({
            "target_name": target_name,
            "tic_id": tic_id,
            "filename": fname,
            "path": file_path,
            "status": status,
            "expected_hash": expected_hash,
            "actual_hash": actual_hash,
        })
        print(f"[{status}] {target_name} (TIC {tic_id}): {fname}")

    counts = {
        "MATCH": sum(1 for r in results if r["status"] == "MATCH"),
        "MISMATCH": sum(1 for r in results if r["status"] == "MISMATCH"),
        "MISSING": sum(1 for r in results if r["status"] == "MISSING"),
        "EXISTS_NO_HASH": sum(1 for r in results if r["status"] == "EXISTS_NO_HASH"),
        "TOTAL": len(results),
    }

    print("\n--- Hash Verification Summary ---")
    print(f"Total files checked: {counts['TOTAL']}")
    print(f"  MATCH:          {counts['MATCH']}")
    print(f"  MISMATCH:       {counts['MISMATCH']}")
    print(f"  MISSING:        {counts['MISSING']}")
    if counts["EXISTS_NO_HASH"] > 0:
        print(f"  EXISTS_NO_HASH: {counts['EXISTS_NO_HASH']}")

    return {"results": results, "counts": counts}


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

    expected_hash = str(row["fits_sha256"]).strip() if "fits_sha256" in row and pd.notna(row["fits_sha256"]) else None

    if os.path.exists(dest_path) and os.path.getsize(dest_path) >= 10000:
        if expected_hash:
            actual_hash = compute_file_sha256(dest_path)
            if actual_hash == expected_hash:
                return {"tic_id": tic_id, "target_name": target_name, "path": dest_path, "status": "CACHED"}
        else:
            return {"tic_id": tic_id, "target_name": target_name, "path": dest_path, "status": "CACHED"}

    # Primary: Official STScI AWS Open Data S3 mirror
    s3_url = f"https://s3.amazonaws.com/stpubdata/{s3_lc_key}"
    try:
        resp = requests.get(s3_url, timeout=timeout)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        if os.path.getsize(dest_path) >= 10000:
            if expected_hash:
                actual_hash = compute_file_sha256(dest_path)
                if actual_hash != expected_hash:
                    raise ValueError(f"Downloaded hash mismatch for {fname}: got {actual_hash}, expected {expected_hash}")
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
                if expected_hash:
                    actual_hash = compute_file_sha256(dest_path)
                    if actual_hash != expected_hash:
                        raise ValueError(f"Downloaded hash mismatch for {fname}: got {actual_hash}, expected {expected_hash}")
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
    parser = argparse.ArgumentParser(description="Fetch and verify TESS SPOC 2-min light curves for benchmark targets")
    parser.add_argument("--targets", default=None, help="Path to targets CSV (default: benchmark/targets.csv)")
    parser.add_argument("--cache-dir", default=None, help="Path to local cache directory")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download workers (default: 8)")
    parser.add_argument("--verify", action="store_true", help="Verify SHA-256 hashes of cached files without downloading")
    args = parser.parse_args()

    if args.verify:
        summary = verify_benchmark_hashes(targets_csv=args.targets, cache_base=args.cache_dir)
        counts = summary["counts"]
        if counts["MISMATCH"] > 0 or counts["MISSING"] > 0:
            sys.exit(1)
        sys.exit(0)
    else:
        res_list = fetch_all_benchmark_data(targets_csv=args.targets, cache_base=args.cache_dir, max_workers=args.workers)
        n_cached = sum(1 for r in res_list if r["status"] == "CACHED")
        n_dl = len(res_list) - n_cached
        print(f"Verified {len(res_list)}/{len(res_list)} benchmark FITS light curves ({n_cached} cached, {n_dl} newly downloaded).")
