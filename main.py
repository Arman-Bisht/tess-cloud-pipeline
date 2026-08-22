import logging
import concurrent.futures
import functions_framework
import os
from google.cloud import storage

from db import upsert_target, get_target_status, save_signal, update_status
from downloader import get_lightcurves, purge_cache_for_target
from bls_engine import run_bls
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
    
    lcs = get_lightcurves(tic_id)
    if not lcs:
        update_status(tic_id, "NO_DATA")
        return
        
    lc_flat, lc_unflat = lcs
    ra, dec = lc_unflat.ra, lc_unflat.dec
    upsert_target(tic_id, tic_id, ra, dec, "PROCESSING")
    
    bls_res = run_bls(lc_flat)
    ls_res = run_lomb_scargle(lc_unflat)
    category, best_res = vet_signals(bls_res, ls_res, lc_flat, lc_unflat)
    
    if category == "FALSE_POSITIVE":
        update_status(tic_id, "FALSE_POSITIVE")
        purge_cache_for_target(tic_id)
        return
        
    is_known, known_label = check_catalog(ra, dec, category, best_res.get('period', 0))
    final_status = get_final_status(category, is_known, known_label)
    
    update_status(tic_id, final_status)
    save_signal(tic_id, category, best_res)
    
    if "UNRECORDED" in final_status:
        plot_path = save_diagnostic_plot(tic_id, final_status, lc_flat, lc_unflat, bls_res, ls_res)
        dispatch_alert(tic_id, final_status, best_res, plot_path)
    else:
        purge_cache_for_target(tic_id)

@functions_framework.http
def serverless_entry(request):
    """HTTP Cloud Function entry point."""
    request_json = request.get_json(silent=True)
    if not request_json:
        return 'Invalid payload', 400
        
    start_hd = request_json.get('start_hd', 10000)
    end_hd = request_json.get('end_hd', 12000)
    batch_size = request_json.get('batch_size', 20)
    workers = request_json.get('workers', 4)
    
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

    logger.info(f"Processing batch of {len(targets_to_process)} targets...")
    
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
