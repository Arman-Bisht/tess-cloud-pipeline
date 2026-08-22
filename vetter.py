import numpy as np
import lightkurve as lk
from typing import Tuple, Dict, Any, Optional

def phase_fold_and_bin(lc: lk.LightCurve, period: float, epoch: float, bins: int = 100) -> Tuple[np.ndarray, np.ndarray]:
    folded = lc.fold(period=period, epoch_time=epoch)
    # Binning to reduce noise
    try:
        binned = folded.bin(time_bin_size=period/bins)
        return binned.time.value, binned.flux.value
    except Exception:
        return folded.time.value, folded.flux.value

def check_secondary_eclipse(lc: lk.LightCurve, period: float, epoch: float, primary_depth: float, duration: float) -> bool:
    """
    Returns True if secondary eclipse is < 20% of primary depth (pass), False otherwise (fail/binary).
    """
    folded = lc.fold(period=period, epoch_time=epoch)
    
    phase = folded.time.value
    flux = folded.flux.value
    
    window = (duration / period) * 1.5
    
    mask = (np.abs(phase - 0.5) < window) | (np.abs(phase + 0.5) < window)
    if not np.any(mask):
        return True # Can't see it, assume pass
        
    sec_flux = flux[mask]
    baseline = np.nanmedian(flux)
    sec_depth = baseline - np.nanmin(sec_flux)
    
    return sec_depth < (0.2 * primary_depth)

def check_odd_even(lc: lk.LightCurve, period: float, epoch: float, duration: float) -> float:
    """
    Returns ratio of odd/even transit depths. If ~1, it's a planet. If significantly different, binary.
    """
    folded = lc.fold(period=2*period, epoch_time=epoch)
    phase = folded.time.value
    flux = folded.flux.value
    
    window = (duration / (2*period)) * 1.5
    
    even_mask = np.abs(phase) < window
    odd_mask = (np.abs(phase - 0.5) < window) | (np.abs(phase + 0.5) < window)
    
    baseline = np.nanmedian(flux)
    
    even_depth = baseline - np.nanmin(flux[even_mask]) if np.any(even_mask) else 0
    odd_depth = baseline - np.nanmin(flux[odd_mask]) if np.any(odd_mask) else 0
    
    if even_depth <= 0 or odd_depth <= 0:
        return 1.0 # Assume same if missing
        
    return odd_depth / even_depth

def check_harmonics(period: float) -> bool:
    if period is None:
        return False
    artifacts = [0.5, 1.0, 2.0] # Common mathematical echoes
    for a in artifacts:
        if abs(period - a) < 0.02:
            return True
    return False

def check_tess_systematics(period: float) -> bool:
    if period is None:
        return False
    if 13.0 < period < 15.0 or 26.5 < period < 28.5:
        return True
    if check_harmonics(period):
        return True
    return False

def vet_signals(bls_res: Optional[Dict[str, Any]], ls_res: Optional[Dict[str, Any]], lc_flat: lk.LightCurve, lc_unflat: lk.LightCurve) -> Tuple[str, Dict[str, Any]]:
    from config import SDE_THRESHOLD, DEPTH_MAX, LS_FAP_THRESHOLD
    
    is_planet = False
    is_eb = False
    is_var = False
    
    best_res = {}
    
    if bls_res and bls_res['sde'] > SDE_THRESHOLD:
        period = bls_res['period']
        depth = bls_res['depth']
        
        noise_level = np.nanstd(lc_flat.flux.value)
        snr = depth / noise_level if noise_level > 0 else 0
        
        if not check_tess_systematics(period) and snr > 3.0:
            epoch = bls_res['epoch']
            duration = bls_res['duration']
            best_res = bls_res
            
            if depth > DEPTH_MAX:
                is_eb = True
            else:
                sec_pass = check_secondary_eclipse(lc_flat, period, epoch, depth, duration)
                odd_even_ratio = check_odd_even(lc_flat, period, epoch, duration)
                
                if 0.7 <= odd_even_ratio <= 1.3 and sec_pass:
                    is_planet = True
                else:
                    is_eb = True
                    
    if ls_res and ls_res['fap'] < LS_FAP_THRESHOLD:
        period = ls_res['period']
        if not is_planet and not is_eb and not check_tess_systematics(period):
            is_var = True
            best_res = ls_res
            
    if is_planet:
        return "CANDIDATE_EXOPLANET", best_res
    elif is_eb:
        return "ECLIPSING_BINARY", best_res
    elif is_var:
        return "VARIABLE_STAR", best_res
    
    return "FALSE_POSITIVE", {}
