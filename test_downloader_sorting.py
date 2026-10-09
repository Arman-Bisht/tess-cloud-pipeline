import numpy as np
import lightkurve as lk
from astropy.time import Time
from downloader import sort_and_deduplicate_lightcurve

def test_downloader_chronological_sorting_and_deduplication():
    """
    Regression test for downloader lightcurve stitching:
    Ensures that out-of-order timestamps and duplicate timestamps across stitched sectors
    are strictly sorted chronologically and purged of duplicate timestamps by downloader.py.
    """
    # 1. Create artificial timestamps with out-of-order sectors and duplicate points
    t_sector1 = np.linspace(1300.0, 1327.0, 500)
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
    
    assert not np.all(np.diff(raw_lc.time.value) > 0), "Initial test array should NOT be monotonically sorted"
    
    # Call the actual sorting and deduplication function from downloader.py
    clean_lc = sort_and_deduplicate_lightcurve(raw_lc)
    t_clean = clean_lc.time.value
    
    # Assertions
    assert len(t_clean) < len(t_raw), "Duplicates should have been removed"
    assert np.all(np.diff(t_clean) > 0), "Cleaned timestamps MUST be strictly monotonically increasing"
    assert len(t_clean) == len(np.unique(t_clean)), "No duplicate timestamps should exist"
    
    print(f"Regression Test Passed: Cleaned {len(t_raw)} -> {len(t_clean)} strictly sorted unique points.")

if __name__ == "__main__":
    test_downloader_chronological_sorting_and_deduplication()
