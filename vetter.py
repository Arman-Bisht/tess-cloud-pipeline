import numpy as np
import lightkurve as lk
from typing import Tuple, Dict, Any, Optional

def phase_fold_and_bin(lc: lk.LightCurve, period: float, epoch: float, bins: int = 100) -> Tuple[np.ndarray, np.ndarray]:
    folded = lc.fold(period=period, epoch_time=epoch)
    try:
        binned = folded.bin(time_bin_size=period/bins)
        return binned.time.value, binned.flux.value
    except Exception:
        return folded.time.value, folded.flux.value

def check_secondary_eclipse(lc: lk.LightCurve, period: float, epoch: float, primary_depth: float, duration: float) -> Tuple[bool, float]:
    """
    Tests phase 0.5.
    Returns (pass_filter, secondary_drop_fraction).
    If secondary flux drop > 20% of primary depth, classify as EB (pass_filter = False).
    """
    folded = lc.fold(period=period, epoch_time=epoch)
    phase = folded.time.value
    flux = folded.flux.value
    
    window = (duration / period) * 1.5
    mask = (np.abs(phase - 0.5) < window) | (np.abs(phase + 0.5) < window)
    if not np.any(mask):
        return True, 0.0
        
    sec_flux = flux[mask]
    baseline = np.nanmedian(flux)
    sec_depth = float(baseline - np.nanmin(sec_flux))
    
    ratio = (sec_depth / primary_depth) if primary_depth > 0 else 0.0
    is_pass = ratio <= 0.20
    return is_pass, ratio

def check_odd_even(lc: lk.LightCurve, period: float, epoch: float, duration: float) -> float:
    """
    Returns ratio of odd to even transit depths.
    In range [0.7, 1.3] = Planet.
    Outside = Period-doubled Eclipsing Binary.
    """
    folded = lc.fold(period=2.0 * period, epoch_time=epoch)
    phase = folded.time.value
    flux = folded.flux.value
    
    window = (duration / (2.0 * period)) * 1.5
    even_mask = np.abs(phase) < window
    odd_mask = (np.abs(phase - 0.5) < window) | (np.abs(phase + 0.5) < window)
    
    baseline = np.nanmedian(flux)
    even_depth = baseline - np.nanmin(flux[even_mask]) if np.any(even_mask) else 0.0
    odd_depth = baseline - np.nanmin(flux[odd_mask]) if np.any(odd_mask) else 0.0
    
    if even_depth <= 0 or odd_depth <= 0:
        return 1.0
        
    return float(odd_depth / even_depth)

def check_centroid_motion(lc: lk.LightCurve, period: Optional[float], epoch: Optional[float], duration: Optional[float]) -> Tuple[bool, str]:
    """
    Checks if the photocenter (centroid) shifts during transit, indicating a blended nearby star.
    Returns (is_target, status_description).
    """
    try:
        col_c = None
        row_c = None
        for col_name in ['centroid_col', 'mom_centr1', 'pos_corr1']:
            if hasattr(lc, col_name) and getattr(lc, col_name) is not None:
                col_c = np.array(getattr(lc, col_name).value, dtype=float)
                break
        for row_name in ['centroid_row', 'mom_centr2', 'pos_corr2']:
            if hasattr(lc, row_name) and getattr(lc, row_name) is not None:
                row_c = np.array(getattr(lc, row_name).value, dtype=float)
                break
                
        if col_c is None or row_c is None or period is None or epoch is None or duration is None:
            return True, "No centroid data (Passed)"
            
        t = lc.time.value
        mask = np.isfinite(t) & np.isfinite(col_c) & np.isfinite(row_c)
        t, col_c, row_c = t[mask], col_c[mask], row_c[mask]
        
        if len(t) < 50:
            return True, "Sparse centroid data (Passed)"
            
        phase = ((t - epoch + 0.5 * period) % period) / period - 0.5
        in_transit = np.abs(phase) < (duration / (2.0 * period))
        out_transit = ~in_transit
        
        if np.sum(in_transit) < 5 or np.sum(out_transit) < 20:
            return True, "Insufficient transit centroid points (Passed)"
            
        d_col = abs(np.median(col_c[in_transit]) - np.median(col_c[out_transit]))
        d_row = abs(np.median(row_c[in_transit]) - np.median(row_c[out_transit]))
        std_col = np.std(col_c[out_transit])
        std_row = np.std(row_c[out_transit])
        
        shift_sigma = max(d_col / max(1e-5, std_col), d_row / max(1e-5, std_row))
        if shift_sigma > 3.5:
            return False, f"Significant photocenter shift ({shift_sigma:.1f}σ) - likely blended star"
        return True, f"Clean ({shift_sigma:.1f}σ shift)"
    except Exception as e:
        return True, f"Centroid check bypassed ({e})"

def check_harmonics(period: float) -> bool:
    if period is None:
        return False
    artifacts = [0.5, 1.0, 2.0]
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

def assign_tier(category: str, sde: float, cycles: float, sec_pass: bool, is_known: bool) -> str:
    """
    Tier A — Solid: Clear phased LC, clean periodogram, no VSX, >= 3 cycles, SDE >= 10.
    Tier B — Probable: 7 <= SDE < 10, or fewer cycles.
    Tier C — Dubious: Weak signal, alias, or conflicting data.
    """
    if sde < 7.0:
        return "C"
    if is_known:
        return "B"
    if sde >= 10.0 and cycles >= 3.0 and sec_pass:
        return "A"
    elif sde >= 7.0:
        return "B"
    return "C"

def vet_signals(bls_res: Optional[Dict[str, Any]], 
                ls_res: Optional[Dict[str, Any]], 
                single_res: Optional[Dict[str, Any]],
                micro_res: Optional[Dict[str, Any]],
                lc_flat: lk.LightCurve, 
                lc_unflat: lk.LightCurve,
                sectors: list) -> Tuple[str, Dict[str, Any]]:
    from config import SDE_THRESHOLD, LS_FAP_THRESHOLD, LS_FAP_SWEEP, DEPTH_MAX
    
    # Branch 1: Periodic Transits (BLS)
    if bls_res and bls_res.get('sde', 0) >= SDE_THRESHOLD:
        period = bls_res['period']
        depth = bls_res['depth']
        epoch = bls_res['epoch']
        duration = bls_res['duration']
        sde = bls_res['sde']
        
        noise_level = np.nanstd(lc_flat.flux.value)
        snr = depth / noise_level if noise_level > 0 else 0
        
        if not check_tess_systematics(period) and snr > 3.0:
            # Calculate number of observed cycles
            time_span = float(lc_flat.time.value[-1] - lc_flat.time.value[0])
            cycles = time_span / period if period > 0 else 1.0
            
            sec_pass, sec_ratio = check_secondary_eclipse(lc_flat, period, epoch, depth, duration)
            odd_even_ratio = check_odd_even(lc_flat, period, epoch, duration)
            centroid_pass, centroid_desc = check_centroid_motion(lc_flat, period, epoch, duration)
            
            bls_res.update({
                "cycles": cycles,
                "sec_pass": sec_pass,
                "sec_ratio": sec_ratio,
                "odd_even_ratio": odd_even_ratio,
                "centroid_pass": centroid_pass,
                "centroid_desc": centroid_desc,
                "sectors": sectors
            })
            
            # Spec 1.3: Remove 3% depth ceiling entirely for EBs.
            # Planets: depth <= DEPTH_MAX, odd/even in [0.7, 1.3], no secondary eclipse (>20%), clean centroid.
            if depth <= DEPTH_MAX and (0.7 <= odd_even_ratio <= 1.3) and sec_pass and centroid_pass:
                bls_res['tier'] = assign_tier("EXOPLANET", sde, cycles, sec_pass, False)
                return "CANDIDATE_EXOPLANET", bls_res
            else:
                bls_res['tier'] = assign_tier("ECLIPSING_BINARY", sde, cycles, sec_pass, False)
                return "ECLIPSING_BINARY", bls_res

    # Branch 2: Single-Transit Detection (Long-Period Planets)
    if single_res and single_res.get('snr', 0) >= 6.0:
        epoch = single_res['epoch']
        duration = single_res['duration']
        depth = single_res['depth']
        sde = single_res['sde']
        centroid_pass, centroid_desc = check_centroid_motion(lc_flat, None, epoch, duration)
        
        single_res.update({
            "cycles": 1.0,
            "sec_pass": True,
            "sec_ratio": 0.0,
            "odd_even_ratio": 1.0,
            "centroid_pass": centroid_pass,
            "centroid_desc": centroid_desc,
            "sectors": sectors,
            "tier": "A" if sde >= 10.0 and centroid_pass else "B"
        })
        return "SINGLE_TRANSIT_CANDIDATE", single_res

    # Branch 3: Gravitational Microlensing
    if micro_res and micro_res.get('sde', 0) >= 7.0:
        micro_res.update({
            "cycles": 1.0,
            "sec_pass": True,
            "sec_ratio": 0.0,
            "odd_even_ratio": 1.0,
            "centroid_pass": True,
            "centroid_desc": "Symmetric magnification fit",
            "sectors": sectors,
            "tier": "A" if micro_res['sde'] >= 10.0 else "B"
        })
        return "MICROLENSING_EVENT", micro_res

    # Branch 4: Stellar Pulsations / Variables (Lomb-Scargle)
    if ls_res and ls_res.get('fap', 1.0) < LS_FAP_SWEEP:
        period = ls_res['period']
        sde = ls_res.get('sde', 7.0)
        time_span = float(lc_unflat.time.value[-1] - lc_unflat.time.value[0])
        cycles = time_span / period if period > 0 else 1.0
        
        if not check_tess_systematics(period):
            is_catalog_tier = ls_res['fap'] < LS_FAP_THRESHOLD
            tier = "A" if (is_catalog_tier and sde >= 10.0 and cycles >= 3.0) else "B"
            ls_res.update({
                "cycles": cycles,
                "sec_pass": True,
                "sec_ratio": 0.0,
                "odd_even_ratio": 1.0,
                "centroid_pass": True,
                "centroid_desc": "Periodic variability",
                "sectors": sectors,
                "tier": tier
            })
            return "VARIABLE_STAR", ls_res

    return "FALSE_POSITIVE", {}
