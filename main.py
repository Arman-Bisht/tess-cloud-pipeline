import logging
import concurrent.futures
import functions_framework
import os
import gc
from typing import Optional

# Local Process Priority Optimization (Spec 4.3)
try:
    import psutil
    p = psutil.Process(os.getpid())
    if hasattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS'):
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
except Exception:
    pass

from google.cloud import storage

from db import upsert_target, get_target_status, save_discovery, update_status
from downloader import get_lightcurves, purge_cache_for_target
from bls_engine import run_bls
from single_transit_engine import run_single_transit
from microlensing_engine import run_microlensing
from variable_engine import run_lomb_scargle
from vetter import vet_signals
from catalog_checker import check_catalog, get_final_status
from visualizer import save_diagnostic_plot
from notifier import dispatch_alert

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

def download_db():
    if not GCS_BUCKET_NAME:
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
    if not GCS_BUCKET_NAME:
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
    if status and status not in ["PENDING", "PROCESSING"]:
        logger.info(f"Target {tic_id} already processed with status: {status}")
        return
        
    upsert_target(tic_id, tic_id, 0.0, 0.0, "PROCESSING")
    
    try:
        lcs = get_lightcurves(tic_id)
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
        
        # 2. Multi-Engine Vetting & Gatekeepers (Spec 2.3 & 6.1)
        category, best_res = vet_signals(bls_res, ls_res, single_res, micro_res, lc_flat, lc_unflat, sectors)
        
        if category == "FALSE_POSITIVE":
            update_status(tic_id, "FALSE_POSITIVE")
            purge_cache_for_target(tic_id)
            return
            
        # 3. 15-Arcsecond Resilient Coordinate Cone Search (Spec 2.4)
        catalog_info = check_catalog(ra, dec, category, best_res.get('period'))
        final_status = get_final_status(category, catalog_info['is_known'], catalog_info['known_label'])
        
        # 4. Generate 5-Panel Diagnostic Plot (Spec 5.2)
        plot_path = save_diagnostic_plot(tic_id, final_status, lc_flat, lc_unflat, best_res, sectors)
        
        # 5. Persist to SQLite & Master CSV (Spec 3.3 & 3.4)
        update_status(tic_id, final_status)
        save_discovery(tic_id, tic_id, ra, dec, final_status, best_res, catalog_info, plot_path, sectors)
        
        # 6. Dispatch Multi-Channel Alerts if Unrecorded Discovery (Spec 4.2 & 5.1)
        if "UNRECORDED" in final_status:
            dispatch_alert(tic_id, tic_id, final_status, best_res, catalog_info, plot_path, sectors)
            
        # 7. Guaranteed Immediate Cache Cleanup (Spec 3.2)
        purge_cache_for_target(tic_id)
        
    except Exception as e:
        logger.error(f"Error executing target pipeline for {tic_id}: {e}")
        update_status(tic_id, f"ERROR: {str(e)[:64]}")
        purge_cache_for_target(tic_id)
    finally:
        # Explicit garbage collection between stars (Spec 4.1)
        gc.collect()

@functions_framework.http
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
        if not status or status in ["PENDING", "PROCESSING"]:
            targets_to_process.append(tic)
        if len(targets_to_process) >= batch_size:
            break
            
    if not targets_to_process:
        logger.info(f"No unprocessed targets left between {start_hd} and {end_hd}.")
        return 'Done', 200

    logger.info(f"Processing batch of {len(targets_to_process)} targets with {workers} workers...")
    
    # 3. Process Batch
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_target, tic): tic for tic in targets_to_process}
        for future in concurrent.futures.as_completed(futures):
            tic = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error(f"Error processing {tic}: {e}")
                
    # 4. Push persistent state
    upload_db()
    
    return 'Batch processed successfully', 200

if __name__ == "__main__":
    # Local CLI test execution
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "HD 10002"
    process_target(target)
