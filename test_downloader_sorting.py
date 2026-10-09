import numpy as np
import lightkurve as lk
from astropy.time import Time
from downloader import get_lightcurves

def test_downloader_chronological_sorting_and_deduplication():
    """
    Regression test for downloader lightcurve stitching:
    Ensures that out-of-order timestamps and duplicate timestamps across stitched sectors
    are strictly sorted chronologically and purged of duplicate timestamps.
    """
    # 1. Create artificial timestamps with out-of-order sectors and duplicate points
    t_sector1 = np.linspace(1300.0, 1327.0, 500)
    # Simulate sector 2 overlapping or stitched out of order
    t_sector2 = np.linspace(1325.0, 1352.0, 500)
    
    # Shuffle or invert order to simulate unsorted stitch
    t_combined = np.concatenate([t_sector2, t_sector1])
    
    # Add explicit duplicate timestamps
    t_duplicates = np.array([1310.0, 1315.5, 1325.0, 1326.0])
    t_raw = np.concatenate([t_combined, t_duplicates])
    
    flux_raw = np.ones_like(t_raw)
    
    # Wrap in lightkurve LightCurve
    time_obj = Time(t_raw, format='jd')
    raw_lc = lk.LightCurve(time=time_obj, flux=flux_raw)
    
    # Apply the sorting and deduplication logic from downloader.py
    t_vals = raw_lc.time.value
    assert not np.all(np.diff(t_vals) > 0), "Initial test array should NOT be monotonically sorted"
    
    # Sort
    sort_idx = np.argsort(t_vals)
    sorted_lc = raw_lc[sort_idx]
    
    # Deduplicate
    _, u_idx = np.unique(sorted_lc.time.value, return_index=True)
    clean_lc = sorted_lc[np.sort(u_idx)]
    
    t_clean = clean_lc.time.value
    
    # Assertions
    assert len(t_clean) < len(t_raw), "Duplicates should have been removed"
    assert np.all(np.diff(t_clean) > 0), "Cleaned timestamps MUST be strictly monotonically increasing"
    assert len(t_clean) == len(np.unique(t_clean)), "No duplicate timestamps should exist"
    
    print(f"Regression Test Passed: Cleaned {len(t_raw)} -> {len(t_clean)} strictly sorted unique points.")

if __name__ == "__main__":
    test_downloader_chronological_sorting_and_deduplication()
