import os
import shutil
import glob
import lightkurve as lk
import numpy as np
import logging
from typing import Tuple, Optional, List
from tenacity import retry, wait_exponential, stop_after_attempt
from config import MAX_SECTORS, LIGHTKURVE_CACHE_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def purge_cache_for_target(tic_id: str):
    """
    Clears intermediate raw FITS files from the lightkurve cache for a specific target
    to guarantee zero disk bloat.
    """
    try:
        tess_cache_dir = LIGHTKURVE_CACHE_DIR / "mastDownload" / "TESS"
        if tess_cache_dir.exists():
            target_id = ''.join(filter(str.isdigit, tic_id))
            if not target_id:
                return
            target_padded = target_id.zfill(16)
            pattern = str(tess_cache_dir / f"*-{target_padded}-*")
            matching_dirs = glob.glob(pattern)
            for dir_path in matching_dirs:
                shutil.rmtree(dir_path, ignore_errors=True)
                logger.info(f"Purged cache directory: {dir_path}")
    except Exception as e:
        logger.warning(f"Failed to purge cache for {tic_id}: {e}")

@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
def get_lightcurves(target: str) -> Optional[Tuple[lk.LightCurve, lk.LightCurve, lk.LightCurve, List[int]]]:
    """
    Queries MAST for the target.
    Returns:
      - lc_flat: Flattened light curve (window=401) for repeating BLS transits.
      - lc_unflat: Unflattened normalized light curve WITHOUT upper outlier clipping (preserves microlensing/flares & variables).
      - lc_wide_flat: Wide-flattened light curve (window=2001) for single transit detection.
      - sectors: List of observed sector numbers.
    """
    try:
        # Search SPOC first, fallback to QLP
        search_result = lk.search_lightcurve(target, author='SPOC')
        if len(search_result) == 0:
            search_result = lk.search_lightcurve(target, author='QLP')
            
        if len(search_result) == 0:
            logger.info(f"No lightcurve data found for {target}.")
            return None
            
        # Extract sectors
        try:
            if 'sequence_number' in search_result.table.colnames:
                sectors = sorted(list(set(int(s) for s in search_result.table['sequence_number'] if s is not None)))
            elif 'mission' in search_result.table.colnames:
                sectors = sorted(list(set(int(s.split()[-1]) for s in search_result.table['mission'] if 'Sector' in str(s))))
            else:
                sectors = []
        except Exception:
            sectors = []
            
        search_result = search_result[:MAX_SECTORS]
        lc_collection = search_result.download_all()
        if lc_collection is None or len(lc_collection) == 0:
            return None
            
        raw_lc = lc_collection.stitch()
        
        # Stream 2: Unflattened Normalized (Stream 2)
        # Spec 1.2: Remove sigma_upper clipping entirely to preserve positive flux excursions
        stream2_lc = raw_lc.remove_nans().normalize()
        
        # Stream 1: Standard Flattened (window=401) for BLS repeating transits
        # Only clip lower catastrophic systematic drops, NO sigma_upper clipping
        try:
            stream1_lc = stream2_lc.flatten(window_length=401)
        except Exception:
            stream1_lc = stream2_lc.flatten()
            
        # Stream 3: Wide-Flattened (window=2001) for Single-Transit Detection (Spec 1.1)
        try:
            n_points = len(stream2_lc.time)
            # Window length must be odd and less than length of lightcurve
            wide_win = min(2001, n_points - 1 if (n_points - 1) % 2 != 0 else n_points - 2)
            if wide_win > 200:
                wide_flat_lc = stream2_lc.flatten(window_length=wide_win)
            else:
                wide_flat_lc = stream1_lc
        except Exception:
            wide_flat_lc = stream1_lc
            
        return stream1_lc, stream2_lc, wide_flat_lc, sectors
        
    except Exception as e:
        logger.error(f"Error downloading data for {target}: {e}")
        return None
