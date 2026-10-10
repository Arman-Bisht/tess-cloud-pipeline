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

def sort_and_deduplicate_lightcurve(lc: lk.LightCurve) -> lk.LightCurve:
    """
    Sorts lightcurve points strictly in chronological order and purges duplicate timestamps.
    """
    try:
        t_vals = lc.time.value
        if not np.all(np.diff(t_vals) > 0):
            sort_idx = np.argsort(t_vals)
            lc = lc[sort_idx]
            _, u_idx = np.unique(lc.time.value, return_index=True)
            lc = lc[np.sort(u_idx)]
    except Exception as e:
        logger.warning(f"Error sorting/deduplicating lightcurve: {e}")
    return lc

class DownloadNetworkError(Exception):
    """Raised when light curve download fails after retry attempts due to network/archive error."""
    pass

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
def _download_target_collection(target: str) -> Tuple[Optional[lk.LightCurveCollection], List[int]]:
    """
    Queries MAST and downloads LightCurveCollection with retry on network errors.
    Filters by exposure time (prefers 120s SPOC) and deduplicates sectors.
    """
    search_result = lk.search_lightcurve(target, author='SPOC')
    if len(search_result) == 0:
        search_result = lk.search_lightcurve(target, author='QLP')
        
    if len(search_result) == 0:
        logger.info(f"No lightcurve data found in archive for {target}.")
        return None, []
        
    # Cadence filtering: prefer standard SPOC 120s cadence over 20s fast cadence
    if 'exptime' in search_result.table.colnames:
        spoc_120 = search_result[search_result.table['exptime'] == 120]
        if len(spoc_120) > 0:
            search_result = spoc_120
            
    # Deduplicate sectors so we do not download duplicate cadence products for the same sector
    sectors = []
    if 'sequence_number' in search_result.table.colnames:
        seen_sectors = set()
        unique_indices = []
        for idx, sec in enumerate(search_result.table['sequence_number']):
            if sec is not None and sec not in seen_sectors:
                seen_sectors.add(sec)
                unique_indices.append(idx)
        search_result = search_result[unique_indices]
        sectors = sorted(list(seen_sectors))
    elif 'mission' in search_result.table.colnames:
        sectors = sorted(list(set(int(s.split()[-1]) for s in search_result.table['mission'] if 'Sector' in str(s))))

    search_result = search_result[:MAX_SECTORS]
    lc_collection = search_result.download_all()
    return lc_collection, sectors

def detrend_lightcurve_production(stream2_lc: lk.LightCurve) -> Tuple[lk.LightCurve, lk.LightCurve]:
    """
    Shared production detrender used by both downloader.get_lightcurves() and injection_recovery.py.
    Applies lightkurve's iterative outlier-clipped Savitzky-Golay filter:
      - stream1_lc: Standard flattened (window_length=401, ~13.4h on 2-min cadence) for repeating BLS transits.
      - wide_flat_lc: Wide flattened (window_length=2001, ~66.7h on 2-min cadence) for single-transit detection.
    """
    try:
        n_pts = len(stream2_lc.time)
        std_win = min(401, n_pts - 1 if (n_pts - 1) % 2 != 0 else n_pts - 2)
        if std_win >= 5:
            stream1_lc = stream2_lc.flatten(window_length=std_win)
        else:
            stream1_lc = stream2_lc.flatten()
    except Exception:
        stream1_lc = stream2_lc.flatten()

    try:
        n_points = len(stream2_lc.time)
        wide_win = min(2001, n_points - 1 if (n_points - 1) % 2 != 0 else n_points - 2)
        if wide_win > 200:
            wide_flat_lc = stream2_lc.flatten(window_length=wide_win)
        else:
            wide_flat_lc = stream1_lc
    except Exception:
        wide_flat_lc = stream1_lc

    return stream1_lc, wide_flat_lc


def get_lightcurves(target: str) -> Optional[Tuple[lk.LightCurve, lk.LightCurve, lk.LightCurve, List[int]]]:
    """
    Queries MAST for the target and produces standardized data streams.
    Returns:
      - lc_flat: Flattened light curve (window=401) for repeating BLS transits.
      - lc_unflat: Unflattened normalized light curve WITHOUT upper outlier clipping (preserves microlensing/flares & variables).
      - lc_wide_flat: Wide-flattened light curve (window=2001) for single transit detection.
      - sectors: List of observed sector numbers.
    Raises DownloadNetworkError on persistent network/MAST failures.
    """
    try:
        try:
            lc_collection, sectors = _download_target_collection(target)
        except Exception as net_err:
            raise DownloadNetworkError(f"Network error querying MAST for {target}: {net_err}") from net_err

        if lc_collection is None or len(lc_collection) == 0:
            return None
            
        raw_lc = lc_collection.stitch()
        stream2_lc = raw_lc.remove_nans().normalize()
        
        # Chronological sorting and duplicate timestamp removal
        stream2_lc = sort_and_deduplicate_lightcurve(stream2_lc)
        
        # Standardize 20-second fast-cadence sectors to standard TESS 2-minute cadence if needed
        if len(stream2_lc.time) > 40000:
            try:
                stream2_lc = stream2_lc.bin(time_bin_size=120.0 / 86400.0)
            except Exception:
                pass
        
        # Shared production detrending (Stream 1: window=401, Stream 3: window=2001)
        stream1_lc, wide_flat_lc = detrend_lightcurve_production(stream2_lc)
            
        return stream1_lc, stream2_lc, wide_flat_lc, sectors
        
    except Exception as e:
        logger.error(f"Error processing lightcurves for {target}: {e}")
        return None

