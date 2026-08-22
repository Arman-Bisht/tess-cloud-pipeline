import os
import shutil
import glob
import lightkurve as lk
import numpy as np
import logging
from typing import Tuple, Optional
from tenacity import retry, wait_exponential, stop_after_attempt
from config import MAX_SECTORS, LIGHTKURVE_CACHE_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def purge_cache_for_target(tic_id: str):
    """
    Clears intermediate raw FITS files from the lightkurve cache for a specific target
    to prevent disk bloat.
    """
    # Lightkurve caches in ~/.lightkurve/cache/mastDownload/TESS
    try:
        tess_cache_dir = LIGHTKURVE_CACHE_DIR / "mastDownload" / "TESS"
        if tess_cache_dir.exists():
            # Extract number from TIC ID
            target_id = ''.join(filter(str.isdigit, tic_id))
            if not target_id:
                return
            
            # Pad with zeros to 16 digits as MAST does
            target_padded = target_id.zfill(16)
            
            # Find directories matching this target
            pattern = str(tess_cache_dir / f"*-{target_padded}-*")
            matching_dirs = glob.glob(pattern)
            
            for dir_path in matching_dirs:
                shutil.rmtree(dir_path, ignore_errors=True)
                logger.info(f"Purged cache directory: {dir_path}")
    except Exception as e:
        logger.warning(f"Failed to purge cache for {tic_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
def get_lightcurves(target: str) -> Optional[Tuple[lk.LightCurve, lk.LightCurve]]:
    """
    Queries MAST for the target. Returns Stream 1 (flattened) and Stream 2 (unflattened normalized),
    or None if no data.
    """
    try:
        # Try SPOC first
        search_result = lk.search_lightcurve(target, author='SPOC')
        if len(search_result) == 0:
            # Fallback to QLP
            search_result = lk.search_lightcurve(target, author='QLP')
            
        if len(search_result) == 0:
            logger.info(f"No lightcurve data found for {target}.")
            return None
            
        # Limit to MAX_SECTORS
        search_result = search_result[:MAX_SECTORS]
        
        # Download and stitch
        lc_collection = search_result.download_all()
        if lc_collection is None or len(lc_collection) == 0:
            return None
            
        raw_lc = lc_collection.stitch()
        
        # Stream 2: Unflattened Normalized (for Lomb-Scargle)
        # Drop NaNs, normalize
        stream2_lc = raw_lc.remove_nans().normalize()
        
        # Stream 1: Flattened (for BLS transits)
        # Savitzky-Golay flattened, window=401
        try:
            stream1_lc = stream2_lc.flatten(window_length=401).remove_outliers(sigma_upper=4, sigma_lower=float('inf'))
        except Exception:
            # Fallback if window_length is too large for the lightcurve
            stream1_lc = stream2_lc.flatten().remove_outliers(sigma_upper=4, sigma_lower=float('inf'))
            
        return stream1_lc, stream2_lc
        
    except Exception as e:
        logger.error(f"Error downloading data for {target}: {e}")
        return None
