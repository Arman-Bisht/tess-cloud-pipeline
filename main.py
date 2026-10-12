import logging
import concurrent.futures
import os
import gc
from typing import Optional

# Optional Google Cloud dependencies
try:
    import functions_framework
except ImportError:
    functions_framework = None

try:
    from google.cloud import storage
except ImportError:
    storage = None

# Local Process Priority Optimization (Spec 4.3)
try:
    import psutil
    p = psutil.Process(os.getpid())
    if hasattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS'):
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
except Exception:
    pass

from db import upsert_target, get_target_status, save_discovery, update_status, get_max_hd_number, get_connection
from downloader import get_lightcurves, purge_cache_for_target, DownloadNetworkError
from bls_engine import run_bls
from single_transit_engine import run_single_transit
from microlensing_engine import run_microlensing
from variable_engine import run_lomb_scargle
from vetter import vet_signals, assign_tier
from catalog_checker import check_catalog, get_final_status, fetch_gaia_metadata
from visualizer import save_diagnostic_plot
from notifier import dispatch_alert

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

def download_db():
    if not GCS_BUCKET_NAME or storage is None:
        return
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob("astrohunter.db")
        if blob.exists():
            blob.download_to_filename("astrohunter.db")
            logger.info("Successfully downloaded SQLite state from GCS.")
    except Exception as e:
        logger.error(f"Failed to download DB from GCS: {e}")

def upload_db():
    if not GCS_BUCKET_NAME or storage is None:
        return
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob("astrohunter.db")
        blob.upload_from_filename("astrohunter.db")
        logger.info("Successfully uploaded SQLite state to GCS.")
    except Exception as e:
        logger.error(f"Failed to upload DB to GCS: {e}")

def process_target(tic_id: str):
    logger.info(f"Processing target: {tic_id}")
    status = get_target_status(tic_id)
    if status and status not in ["PENDING", "PROCESSING", "DOWNLOAD_ERROR"]:
        logger.info(f"Target {tic_id} already processed with status: {status}")
        return
        
    upsert_target(tic_id, tic_id, 0.0, 0.0, "PROCESSING")
    
    try:
        try:
            lcs = get_lightcurves(tic_id)
        except DownloadNetworkError as net_err:
            logger.warning(f"Transient MAST network error for {tic_id}: {net_err}")
            update_status(tic_id, "DOWNLOAD_ERROR")
            purge_cache_for_target(tic_id)
            return

        if not lcs:
            update_status(tic_id, "NO_DATA")
            purge_cache_for_target(tic_id)
            return
            
        lc_flat, lc_unflat, lc_wide_flat, sectors = lcs
        ra, dec = float(lc_unflat.ra), float(lc_unflat.dec)
        upsert_target(tic_id, tic_id, ra, dec, "PROCESSING")
        
        # 1. Run All Detection Engines
        bls_res = run_bls(lc_flat)
        single_res = run_single_transit(lc_wide_flat)
        micro_res = run_microlensing(lc_unflat)
        ls_res = run_lomb_scargle(lc_unflat)
        
        # 2. Fast TIC metadata query (R*, M*, Gaia ID) BEFORE vetting
        gaia_id, tmag, r_star, m_star = fetch_gaia_metadata(tic_id)
        
        # 3. Multi-Engine Vetting & Physical Gatekeepers (Keplerian orbit & giant duration)
        category, best_res = vet_signals(
            bls_res, ls_res, single_res, micro_res, 
            lc_flat, lc_unflat, sectors, 
            r_star=r_star, m_star=m_star, is_known=False, target_name=tic_id
        )
        
        if category == "FALSE_POSITIVE":
            update_status(tic_id, "FALSE_POSITIVE")
            purge_cache_for_target(tic_id)
            return
            
        # 4. Query full astronomical catalogs for surviving signals using actual WINNING period
        winning_period = best_res.get('period')
        catalog_info = check_catalog(
            ra, dec, category, winning_period, 
            tic_id=tic_id, star_name=tic_id,
            r_star=r_star, m_star=m_star, gaia_id=gaia_id, tmag=tmag
        )
        
        # If catalog indicates known variable/binary, re-vet tier with is_known=True
        if catalog_info.get('is_known'):
            best_res['tier'] = assign_tier(
                category,
                best_res.get('sde', 10.0),
                best_res.get('n_cycles', 3.0),
                best_res.get('sec_pass', True),
                best_res.get('centroid_status', 'NOT_RUN'),
                r_star=r_star,
                orbit_pass=best_res.get('orbit_phys_pass', True),
                dur_pass=best_res.get('dur_phys_pass', True),
                is_known=True
            )
            
        final_status = get_final_status(category, catalog_info['is_known'], catalog_info['known_label'])
        
        # 5. Generate 5-Panel Diagnostic Plot (Spec 5.2)
        plot_path = save_diagnostic_plot(tic_id, final_status, lc_flat, lc_unflat, best_res, sectors)
        
        # 6. Persist to SQLite & Master CSV (Spec 3.3 & 3.4)
        update_status(tic_id, final_status)
        save_discovery(tic_id, tic_id, ra, dec, final_status, best_res, catalog_info, plot_path, sectors)
        
        # 7. Dispatch Multi-Channel Alerts if Unlisted Discovery or Known Binary (Spec 4.2 & 5.1)
        if "UNLISTED" in final_status or "KNOWN_BINARY" in final_status:
            dispatch_alert(tic_id, tic_id, final_status, best_res, catalog_info, plot_path, sectors)
            
        # 8. Guaranteed Immediate Cache Cleanup (Spec 3.2)
        purge_cache_for_target(tic_id)
        
    except Exception as e:
        logger.error(f"Error executing target pipeline for {tic_id}: {e}")
        update_status(tic_id, f"ERROR: {str(e)[:64]}")
        purge_cache_for_target(tic_id)
    finally:
        # Explicit garbage collection between stars (Spec 4.1)
        gc.collect()

PER_TARGET_TIMEOUT_SECONDS = 180

def run_target_with_watchdog(tic_id: str, timeout_sec: float = PER_TARGET_TIMEOUT_SECONDS, target_fn=None) -> bool:
    """
    Executes process_target(tic_id) in a daemon thread under a strict per-target watchdog timeout.
    Using a daemon=True threading.Thread (rather than ThreadPoolExecutor, whose non-daemon workers
    are joined by concurrent.futures.thread._python_exit at interpreter shutdown) guarantees both:
      1. Immediate return when timeout_sec expires, and
      2. Zero process hang at interpreter exit if an abandoned network thread is still blocked.
    Returns True if completed within timeout_sec, False if timed out or errored.
    """
    import threading
    fn = target_fn if target_fn is not None else process_target
    err_holder = []

    def _worker():
        try:
            fn(tic_id)
        except Exception as exc:
            err_holder.append(exc)

    worker_thread = threading.Thread(target=_worker, name=f"watchdog-{tic_id}", daemon=True)
    worker_thread.start()
    worker_thread.join(timeout=timeout_sec)
    if worker_thread.is_alive():
        logger.error(f"Watchdog timeout ({timeout_sec}s) exceeded for {tic_id}; marking DOWNLOAD_ERROR.")
        update_status(tic_id, "DOWNLOAD_ERROR")
        purge_cache_for_target(tic_id)
        return False
    if err_holder:
        logger.error(f"Error processing {tic_id}: {err_holder[0]}")
        return False
    return True

def serverless_entry(request):
    """HTTP Cloud Function entry point."""
    request_json = request.get_json(silent=True)
    if not request_json:
        return 'Invalid payload', 400
        
    start_hd = request_json.get('start_hd', 10000)
    end_hd = request_json.get('end_hd', 12000)
    batch_size = request_json.get('batch_size', 20)
    # Recommended workers 2-3 to respect free tier memory limits (Spec 4.1)
    workers = min(3, request_json.get('workers', 2))
    
    # 1. Pull persistent state
    download_db()
    
    # 2. Determine next unprocessed targets in range
    targets_to_process = []
    for i in range(start_hd, end_hd + 1):
        tic = f"HD {i}"
        status = get_target_status(tic)
        if not status or status in ["PENDING", "PROCESSING", "DOWNLOAD_ERROR"]:
            targets_to_process.append(tic)
        if len(targets_to_process) >= batch_size:
            break
            
    if not targets_to_process:
        logger.info(f"No unprocessed targets left between {start_hd} and {end_hd}.")
        return 'Done', 200

    logger.info(f"Processing batch of {len(targets_to_process)} targets with {workers} workers...")
    
    # 3. Process Batch with non-blocking per-target timeout protection
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {executor.submit(process_target, tic): tic for tic in targets_to_process}
        for future, tic in list(futures.items()):
            try:
                future.result(timeout=PER_TARGET_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                logger.error(f"Timeout ({PER_TARGET_TIMEOUT_SECONDS}s) processing {tic}; marking DOWNLOAD_ERROR.")
                update_status(tic, "DOWNLOAD_ERROR")
                purge_cache_for_target(tic)
            except Exception as e:
                logger.error(f"Error processing {tic}: {e}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
                
    # 4. Push persistent state
    upload_db()
    
    return 'Batch processed successfully', 200

if functions_framework is not None:
    serverless_entry = functions_framework.http(serverless_entry)
    
def run_local_scan(start_hd: Optional[int] = None, 
                   end_hd: Optional[int] = None, 
                   count: Optional[int] = None, 
                   workers: int = 1):
    """
    Scans HD targets locally from start_hd up to end_hd (or count).
    If start_hd is None, automatically detects the highest HD processed so far and resumes.
    """
    if start_hd is None:
        start_hd = get_max_hd_number() + 1
        
    if end_hd is None:
        if count is not None:
            end_hd = start_hd + count - 1
        else:
            end_hd = start_hd + 50 # Default batch of 50
            
    logger.info(f"🔭 Starting Astrohunter scan from HD {start_hd} to HD {end_hd} (workers={workers})...")
    
    # 1. Prepend any targets already marked PENDING in the SQLite database
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT tic_id FROM targets WHERE status = 'PENDING'")
    pending_db = [r['tic_id'] for r in c.fetchall()]
    conn.close()

    # 2. Add sequential HD range
    targets = [f"HD {i}" for i in range(start_hd, end_hd + 1)]
    
    # Filter out already processed targets, deduplicating order
    unprocessed = []
    seen = set()
    for tic in pending_db + targets:
        if tic not in seen:
            seen.add(tic)
            st = get_target_status(tic)
            if not st or st in ["PENDING", "PROCESSING", "DOWNLOAD_ERROR"]:
                unprocessed.append(tic)
            
    logger.info(f"Identified {len(unprocessed)} targets to search in this run.")
    
    if workers > 1:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {executor.submit(process_target, tic): tic for tic in unprocessed}
            for future, tic in list(futures.items()):
                try:
                    future.result(timeout=PER_TARGET_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    logger.error(f"Timeout ({PER_TARGET_TIMEOUT_SECONDS}s) processing {tic}; marking DOWNLOAD_ERROR.")
                    update_status(tic, "DOWNLOAD_ERROR")
                    purge_cache_for_target(tic)
                except Exception as e:
                    logger.error(f"Error processing {tic}: {e}")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    else:
        for idx, tic in enumerate(unprocessed, 1):
            logger.info(f"[{idx}/{len(unprocessed)}] Scanning {tic}...")
            run_target_with_watchdog(tic, timeout_sec=PER_TARGET_TIMEOUT_SECONDS)
                
    logger.info("✨ Astrohunter scan finished successfully.")

def print_summary():
    """Prints a formatted summary of the discovery catalog and batch progress."""
    import pandas as pd
    import sqlite3
    from config import MASTER_CSV_PATH, DB_PATH
    
    total_surveyed = 0
    with_data = 0
    false_positives = 0
    no_data_count = 0
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM targets")
            total_surveyed = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM targets WHERE status != 'NO_DATA' AND status NOT LIKE 'ERROR%'")
            with_data = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM targets WHERE status = 'FALSE_POSITIVE'")
            false_positives = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM targets WHERE status = 'NO_DATA'")
            no_data_count = c.fetchone()[0]
            conn.close()
        except Exception:
            pass

    df = pd.DataFrame()
    if MASTER_CSV_PATH.exists():
        try:
            df = pd.read_csv(MASTER_CSV_PATH)
        except Exception:
            pass
            
    n_disc = len(df)
    tier_a = len(df[df['confidence'].str.contains('Tier A', na=False)]) if not df.empty else 0
    tier_b = len(df[df['confidence'].str.contains('Tier B', na=False)]) if not df.empty else 0
    tier_c = len(df[df['confidence'].str.contains('Tier C', na=False)]) if not df.empty else 0
    
    unrec_var = len(df[df['category'] == 'UNLISTED_NEEDS_VETTING_VARIABLE_STAR_CANDIDATE']) if not df.empty else 0
    unrec_eb = len(df[df['category'] == 'UNLISTED_NEEDS_VETTING_ECLIPSING_BINARY_CANDIDATE']) if not df.empty else 0
    unrec_transit = len(df[df['category'] == 'UNLISTED_NEEDS_VETTING_LOW_MASS_COMPANION_OR_GRAZING_EB']) if not df.empty else 0
    benchmarks = len(df[df['confidence'].str.contains('Benchmark|Recovery', na=False)]) if not df.empty else 0

    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("\n" + "=" * 64)
    print("ASTROHUNTER PRO -- VETTED CANDIDATE CATALOG STATUS")
    print("=" * 64)
    print(f"Total Stars in Survey Footprint:     {total_surveyed}")
    print(f"Stars Analyzed with TESS Data:       {with_data}")
    print(f"Targets without TESS Observations:   {no_data_count}")
    print(f"Vetted Catalog Records Logged:       {n_disc}")
    print("-" * 64)
    print("Quality & Vetting Confidence Breakdown:")
    print(f"  [+] Tier A (Pristine Vetted Clean):        {tier_a}")
    print(f"  [*] Tier B (Probable / Unconstrained):     {tier_b}")
    print(f"  [-] Tier C (Audit Flagged / Rejected):     {tier_c}")
    print("-" * 64)
    print("Astrophysical Classes in Master Catalog:")
    print(f"  • Unlisted Eclipsing Binaries:             {unrec_eb}")
    print(f"  • Unlisted High-Amplitude Variables:       {unrec_var}")
    print(f"  • Low-Mass Companion / Grazing EBs:        {unrec_transit}")
    print(f"  • Ground-Truth Benchmark Controls:         {benchmarks}")
    print(f"  • Pipeline Systematic Rejections (FP):     {false_positives} targets")
    print("=" * 64 + "\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Astrohunter Pro Exoplanet & Variable Star Hunter")
    parser.add_argument("target", nargs="?", default=None, help="Target name to process (e.g. 'HD 10521' or 'TIC 278682559')")
    parser.add_argument("--scan", action="store_true", help="Run local scan mode")
    parser.add_argument("--start", type=int, default=None, help="Starting HD number (default: auto-resume)")
    parser.add_argument("--end", type=int, default=None, help="Ending HD number")
    parser.add_argument("--count", type=int, default=None, help="Number of HD stars to scan")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent workers (default 1)")
    parser.add_argument("--summary", action="store_true", help="Show discovery catalog summary & progress towards 50-100 batch")
    
    args = parser.parse_args()
    
    if args.summary:
        print_summary()
    elif args.target and not args.scan and args.start is None:
        process_target(args.target)
    else:
        run_local_scan(start_hd=args.start, end_hd=args.end, count=args.count, workers=args.workers)


