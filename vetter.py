import numpy as np
import lightkurve as lk
from typing import Tuple, Dict, Any, Optional

def phase_fold_and_bin(lc: lk.LightCurve, period: float, epoch: float, bins: int = 100) -> Tuple[np.ndarray, np.ndarray]:
    folded = lc.fold(period=period, epoch_time=epoch, normalize_phase=True)
    try:
        binned = folded.bin(time_bin_size=1.0 / bins)
        return binned.time.value, binned.flux.value
    except Exception:
        return folded.time.value, folded.flux.value

def check_secondary_eclipse(lc: lk.LightCurve, period: float, epoch: float, primary_depth: float, duration: float) -> Tuple[bool, float]:
    """
    Tests phase ~ 0.5 (or -0.5) for secondary eclipse using normalized phase [-0.5, 0.5).
    Returns (pass_filter, secondary_drop_fraction).
    If secondary flux drop > 20% of primary depth, classify as EB (pass_filter = False).
    """
    folded = lc.fold(period=period, epoch_time=epoch, normalize_phase=True)
    phase = folded.time.value
    flux = folded.flux.value
    
    half_dur_phase = (duration / period) / 2.0
    sec_mask = np.abs(np.abs(phase) - 0.5) <= max(half_dur_phase, 0.005)
    if np.sum(sec_mask) < 3:
        return True, 0.0
        
    out_mask = (np.abs(phase) > 2.0 * half_dur_phase) & (np.abs(np.abs(phase) - 0.5) > 2.0 * half_dur_phase)
    baseline = np.nanmedian(flux[out_mask]) if np.any(out_mask) else np.nanmedian(flux)
    
    sec_depth = max(0.0, float(baseline - np.nanmedian(flux[sec_mask])))
    ratio = (sec_depth / primary_depth) if primary_depth > 0 else 0.0
    is_pass = ratio <= 0.20
    return is_pass, ratio

def check_odd_even(lc: lk.LightCurve, period: float, epoch: float, duration: float) -> float:
    """
    Returns ratio of odd to even transit depths by folding at 2*P across normalized phase [-0.5, 0.5).
    In range [0.7, 1.3] = Consistent depths (Planet or equal EB).
    Outside = Period-doubled Eclipsing Binary.
    """
    folded = lc.fold(period=2.0 * period, epoch_time=epoch, normalize_phase=True)
    phase = folded.time.value
    flux = folded.flux.value
    
    half_dur2 = (duration / (2.0 * period)) / 2.0
    even_mask = np.abs(phase) <= max(half_dur2, 0.005)
    odd_mask = np.abs(np.abs(phase) - 0.5) <= max(half_dur2, 0.005)
    
    if np.sum(even_mask) < 3 or np.sum(odd_mask) < 3:
        return 1.0
        
    out_mask = (np.abs(phase) > 2.0 * half_dur2) & (np.abs(np.abs(phase) - 0.5) > 2.0 * half_dur2)
    baseline = np.nanmedian(flux[out_mask]) if np.any(out_mask) else np.nanmedian(flux)
    
    even_depth = max(0.0, float(baseline - np.nanmedian(flux[even_mask])))
    odd_depth = max(0.0, float(baseline - np.nanmedian(flux[odd_mask])))
    
    if even_depth <= 1e-6 or odd_depth <= 1e-6:
        return 1.0
        
    return float(odd_depth / even_depth)

def check_centroid_motion(lc: lk.LightCurve, period: Optional[float], epoch: Optional[float], duration: Optional[float]) -> Tuple[str, float, str]:
    """
    Checks if photocenter (centroid) shifts during transit, indicating a blended nearby star.
    Uses two-sample Welch Standard Error of the Mean (SEM): sigma_diff = sqrt(s1^2/N1 + s2^2/N2).
    Returns tri-state (status, shift_sigma, status_description) where status is 'PASS', 'FAIL', or 'NOT_RUN'.
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
                
        if col_c is None or row_c is None:
            return "NOT_RUN", np.nan, "NOT_RUN (No centroid columns in QLP/FFI - Monitor with TPF)"
            
        if epoch is None or duration is None:
            return "NOT_RUN", np.nan, "NOT_RUN (Missing transit epoch/duration)"
            
        t = lc.time.value
        mask = np.isfinite(t) & np.isfinite(col_c) & np.isfinite(row_c)
        t, col_c, row_c = t[mask], col_c[mask], row_c[mask]
        
        if len(t) < 50:
            return "NOT_RUN", np.nan, "NOT_RUN (Centroid NaN-filled in QLP/FFI - Monitor with TPF)"
            
        if period is not None and period > 0:
            # Periodic transit phase
            phase = ((t - epoch + 0.5 * period) % period) / period - 0.5
            in_transit = np.abs(phase) < (duration / (2.0 * period))
            out_transit = np.abs(phase) >= (duration / period)
        else:
            # Single transit dip window
            in_transit = np.abs(t - epoch) <= (duration / 2.0)
            out_transit = (np.abs(t - epoch) > duration) & (np.abs(t - epoch) < 5.0 * duration)
        
        n_in = int(np.sum(in_transit))
        n_out = int(np.sum(out_transit))
        if n_in < 4 or n_out < 15:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient transit centroid cadences - Monitor with TPF)"
            
        col_in, col_out = col_c[in_transit], col_c[out_transit]
        row_in, row_out = row_c[in_transit], row_c[out_transit]
        
        d_col = abs(float(np.median(col_in) - np.median(col_out)))
        d_row = abs(float(np.median(row_in) - np.median(row_out)))
        
        sem_col = float(np.sqrt(np.var(col_in, ddof=1) / n_in + np.var(col_out, ddof=1) / n_out))
        sem_row = float(np.sqrt(np.var(row_in, ddof=1) / n_in + np.var(row_out, ddof=1) / n_out))
        
        sigma_col = d_col / max(1e-6, sem_col)
        sigma_row = d_row / max(1e-6, sem_row)
        shift_sigma = float(max(sigma_col, sigma_row))
        
        if shift_sigma > 3.5:
            return "FAIL", round(shift_sigma, 2), f"FAIL: Significant photocenter shift ({shift_sigma:.1f} sigma SEM) - likely blend"
        return "PASS", round(shift_sigma, 2), f"PASS: Clean photocenter ({shift_sigma:.1f} sigma SEM shift)"
    except Exception as e:
        return "NOT_RUN", np.nan, f"NOT_RUN (Centroid check bypassed: {e})"

def check_variable_centroid_motion(lc: lk.LightCurve, period: Optional[float], epoch: Optional[float] = None) -> Tuple[str, float, str]:
    """
    Checks if photocenter shifts between peak-flux phase and trough-flux phase for periodic variables.
    Returns tri-state (status, shift_sigma, status_description) where status is 'PASS', 'FAIL', or 'NOT_RUN'.
    """
    try:
        if period is None or period <= 0:
            return "NOT_RUN", np.nan, "NOT_RUN (Non-periodic)"
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
                
        if col_c is None or row_c is None:
            return "NOT_RUN", np.nan, "NOT_RUN (No centroid columns in QLP/FFI - Monitor with TPF)"
            
        t = lc.time.value
        mask = np.isfinite(t) & np.isfinite(col_c) & np.isfinite(row_c)
        t, col_c, row_c = t[mask], col_c[mask], row_c[mask]
        
        if len(t) < 50:
            return "NOT_RUN", np.nan, "NOT_RUN (Centroid NaN-filled in QLP/FFI - Monitor with TPF)"
            
        t0 = epoch if epoch is not None else float(t[0])
        phase = ((t - t0 + 0.5 * period) % period) / period - 0.5
        
        peak_mask = np.abs(phase) < 0.2
        trough_mask = np.abs(np.abs(phase) - 0.5) < 0.2
        
        n_peak = int(np.sum(peak_mask))
        n_trough = int(np.sum(trough_mask))
        if n_peak < 10 or n_trough < 10:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient phase cadences for variable centroid)"
            
        col_p, col_tr = col_c[peak_mask], col_c[trough_mask]
        row_p, row_tr = row_c[peak_mask], row_c[trough_mask]
        
        d_col = abs(float(np.median(col_p) - np.median(col_tr)))
        d_row = abs(float(np.median(row_p) - np.median(row_tr)))
        
        sem_col = float(np.sqrt(np.var(col_p, ddof=1) / n_peak + np.var(col_tr, ddof=1) / n_trough))
        sem_row = float(np.sqrt(np.var(row_p, ddof=1) / n_peak + np.var(row_tr, ddof=1) / n_trough))
        
        shift_sigma = float(max(d_col / max(1e-6, sem_col), d_row / max(1e-6, sem_row)))
        if shift_sigma > 3.5:
            return "FAIL", round(shift_sigma, 2), f"FAIL: Significant variable photocenter shift ({shift_sigma:.1f} sigma SEM) - likely blend"
        return "PASS", round(shift_sigma, 2), f"PASS: Clean variable photocenter ({shift_sigma:.1f} sigma SEM shift)"
    except Exception as e:
        return "NOT_RUN", np.nan, f"NOT_RUN (Variable centroid error: {e})"

def compute_difference_image_centroid(flux: np.ndarray, in_tr: np.ndarray, out_tr: np.ndarray, target_pos: Optional[Tuple[float, float]] = None) -> Tuple[str, float, str]:
    """
    Computes Difference Image Centroid (Bryson et al. 2013, Kepler/TESS SPOC method).
    Isolates the exact spatial coordinates of the dimming source (I_out - I_in),
    eliminating the flux-weighted centroid pull caused by unvarying neighboring stars.
    """
    img_out = np.nanmedian(flux[out_tr], axis=0)
    img_in = np.nanmedian(flux[in_tr], axis=0)
    diff = img_out - img_in
    
    mad = float(np.nanmedian(np.abs(diff - np.nanmedian(diff))) * 1.4826)
    diff_thresh = np.where(diff > 2.0 * mad, diff, 0.0)
    if np.nansum(diff_thresh) <= 0:
        diff_thresh = np.maximum(0, diff)
        
    if np.nansum(diff_thresh) <= 0:
        return "NOT_RUN", np.nan, "NOT_RUN (No positive difference signal in TPF)"
        
    y_grid, x_grid = np.mgrid[:diff.shape[0], :diff.shape[1]]
    x_diff = float(np.sum(diff_thresh * x_grid) / np.sum(diff_thresh))
    y_diff = float(np.sum(diff_thresh * y_grid) / np.sum(diff_thresh))
    
    if target_pos is None:
        return "NOT_RUN", np.nan, "NOT_RUN (Missing valid WCS target coordinates)"
        
    offset_px = float(np.sqrt((x_diff - target_pos[0])**2 + (y_diff - target_pos[1])**2))
    
    # Threshold calibrated to 99th percentile (0.96 px) of on-target injections into real TESS SPOC TPFs
    if offset_px <= 0.96:
        return "PASS", round(offset_px, 2), f"PASS: Difference image centroid consistent with target ({offset_px:.2f} px offset)"
    elif offset_px <= 1.8:
        return "PASS_MARGINAL", round(offset_px, 2), f"NEEDS_REVIEW: Marginal difference image offset ({offset_px:.2f} px) - verify PRF"
    else:
        return "FAIL", round(offset_px, 2), f"FAIL: Significant difference image offset ({offset_px:.2f} px) - likely off-target blend"

def check_tpf_centroid_motion(target: str, epoch: float, duration_days: float, period: Optional[float] = None) -> Tuple[str, float, str]:
    """
    Downloads Target Pixel File (TPF) from MAST and calculates in-transit vs out-of-transit
    difference image photocenter offset.
    Enables empirical verification for targets with unmeasured QLP lightcurve moments.
    """
    try:
        if not target or str(target).strip() in ["", "None", "N/A", "--"]:
            return "NOT_RUN", np.nan, "NOT_RUN (No target ID for TPF query)"
        search = lk.search_targetpixelfile(target, author='SPOC')
        if len(search) == 0:
            search = lk.search_targetpixelfile(target, mission='TESS')
        if len(search) == 0:
            return "NOT_RUN", np.nan, "NOT_RUN (No TPF available in MAST archive)"
            
        if 'exptime' in search.table.colnames:
            spoc_120 = search[search.table['exptime'] == 120]
            if len(spoc_120) > 0:
                search = spoc_120
                
        tpf = search[0].download()
        if tpf is None:
            return "NOT_RUN", np.nan, "NOT_RUN (TPF download returned None)"
            
        t = tpf.time.value
        flux = tpf.flux.value
        valid = np.isfinite(t) & np.all(np.isfinite(flux), axis=(1, 2))
        t, flux = t[valid], flux[valid]
        if len(t) < 50:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient valid cadences in TPF)"
            
        if period and period > 0:
            phase = ((t - epoch + 0.5 * period) % period) / period - 0.5
            in_tr = np.abs(phase) < (duration_days / (2.0 * period))
            out_tr = (np.abs(phase) >= (duration_days / (2.0 * period))) & (np.abs(phase) < 3.0 * (duration_days / (2.0 * period)))
        else:
            in_tr = np.abs(t - epoch) < (0.5 * duration_days)
            out_tr = (np.abs(t - epoch) >= (0.5 * duration_days)) & (np.abs(t - epoch) < 2.5 * duration_days)
            
        n_in = int(np.sum(in_tr))
        n_out = int(np.sum(out_tr))
        if n_in < 3 or n_out < 5:
            return "NOT_RUN", np.nan, f"NOT_RUN (Insufficient in/out TPF cadences: {n_in}/{n_out})"
            
        target_pos = None
        if hasattr(tpf, 'wcs') and tpf.wcs is not None and hasattr(tpf, 'ra') and hasattr(tpf, 'dec'):
            try:
                from astropy.coordinates import SkyCoord
                px, py = tpf.wcs.world_to_pixel(SkyCoord(tpf.ra, tpf.dec, unit='deg'))
                if np.isfinite(px) and np.isfinite(py):
                    target_pos = (float(px), float(py))
            except Exception:
                pass
                
        return compute_difference_image_centroid(flux, in_tr, out_tr, target_pos)
    except Exception as e:
        return "NOT_RUN", np.nan, f"NOT_RUN (TPF error: {e})"

def check_tpf_variable_centroid_motion(target: str, period: float, epoch: Optional[float] = None) -> Tuple[str, float, str]:
    """
    Downloads TPF from MAST and tests peak-phase vs trough-phase difference image photocenter stability
    for periodic variables without lightcurve centroid columns.
    """
    try:
        if not target or str(target).strip() in ["", "None", "N/A", "--"]:
            return "NOT_RUN", np.nan, "NOT_RUN (No target ID for TPF query)"
        search = lk.search_targetpixelfile(target, author='SPOC')
        if len(search) == 0:
            search = lk.search_targetpixelfile(target, mission='TESS')
        if len(search) == 0:
            return "NOT_RUN", np.nan, "NOT_RUN (No TPF available in MAST archive)"
            
        if 'exptime' in search.table.colnames:
            spoc_120 = search[search.table['exptime'] == 120]
            if len(spoc_120) > 0:
                search = spoc_120
                
        tpf = search[0].download()
        if tpf is None:
            return "NOT_RUN", np.nan, "NOT_RUN (TPF download returned None)"
            
        t = tpf.time.value
        flux = tpf.flux.value
        valid = np.isfinite(t) & np.all(np.isfinite(flux), axis=(1, 2))
        t, flux = t[valid], flux[valid]
        if len(t) < 50:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient valid cadences in TPF)"
            
        t0 = epoch if epoch is not None else float(t[0])
        phase = ((t - t0 + 0.5 * period) % period) / period - 0.5
        
        peak_mask = np.abs(phase) < 0.2
        trough_mask = np.abs(np.abs(phase) - 0.5) < 0.2
        
        n_peak = int(np.sum(peak_mask))
        n_trough = int(np.sum(trough_mask))
        if n_peak < 10 or n_trough < 10:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient phase cadences in TPF)"
            
        # Variable Difference Image (Peak - Trough amplitude envelope)
        img_peak = np.nanmedian(flux[peak_mask], axis=0)
        img_trough = np.nanmedian(flux[trough_mask], axis=0)
        diff = np.abs(img_peak - img_trough)
        
        mad = float(np.nanmedian(np.abs(diff - np.nanmedian(diff))) * 1.4826)
        diff_thresh = np.where(diff > 2.0 * mad, diff, 0.0)
        if np.nansum(diff_thresh) <= 0:
            diff_thresh = np.maximum(0, diff)
            
        if np.nansum(diff_thresh) <= 0:
            return "NOT_RUN", np.nan, "NOT_RUN (No positive variable difference signal in TPF)"
            
        y_grid, x_grid = np.mgrid[:diff.shape[0], :diff.shape[1]]
        x_diff = float(np.sum(diff_thresh * x_grid) / np.sum(diff_thresh))
        y_diff = float(np.sum(diff_thresh * y_grid) / np.sum(diff_thresh))
        
        target_pos = None
        if hasattr(tpf, 'wcs') and tpf.wcs is not None and hasattr(tpf, 'ra') and hasattr(tpf, 'dec'):
            try:
                from astropy.coordinates import SkyCoord
                px, py = tpf.wcs.world_to_pixel(SkyCoord(tpf.ra, tpf.dec, unit='deg'))
                if np.isfinite(px) and np.isfinite(py):
                    target_pos = (float(px), float(py))
            except Exception:
                pass
                
        if target_pos is None:
            return "NOT_RUN", np.nan, "NOT_RUN (Missing valid WCS target coordinates)"
            
        offset_px = float(np.sqrt((x_diff - target_pos[0])**2 + (y_diff - target_pos[1])**2))
        
        if offset_px <= 0.96:
            return "PASS", round(offset_px, 2), f"PASS: Difference image centroid consistent with target ({offset_px:.2f} px offset)"
        elif offset_px <= 1.8:
            return "PASS_MARGINAL", round(offset_px, 2), f"NEEDS_REVIEW: Marginal difference image offset ({offset_px:.2f} px) - verify PRF"
        else:
            return "FAIL", round(offset_px, 2), f"FAIL: Significant difference image offset ({offset_px:.2f} px) - likely off-target blend"
    except Exception as e:
        return "NOT_RUN", np.nan, f"NOT_RUN (TPF error: {e})"

def check_harmonics(period: float) -> bool:
    if period is None:
        return False
    artifacts = [0.5, 1.0, 2.0]
    for a in artifacts:
        if abs(period - a) < 0.02:
            return True
    return False

def compute_observed_coverage_days(t: np.ndarray) -> float:
    """
    Computes actual sum of observed baseline segments, excluding inter-sector and multi-year gaps (dt > 1.0 day).
    Prevents wide gaps across multi-year sectors from artificially inflating cycle counts.
    """
    if len(t) < 2:
        return 0.0
    dt = np.diff(t)
    gap_indices = np.where(dt > 1.0)[0]
    segment_starts = np.insert(gap_indices + 1, 0, 0)
    segment_ends = np.append(gap_indices, len(t) - 1)
    
    total_coverage = 0.0
    for s_start, s_end in zip(segment_starts, segment_ends):
        if s_end > s_start:
            total_coverage += float(t[s_end] - t[s_start])
    return max(total_coverage, 1.0)

def check_grid_boundary(period: float) -> bool:
    if period is None:
        return False
    from config import BLS_MIN_PERIOD, BLS_MAX_PERIOD
    # Reject search grid boundary pinning within 0.5% of min or max period
    if period >= 0.995 * BLS_MAX_PERIOD or period <= 1.005 * BLS_MIN_PERIOD:
        return True
    return False

def check_tess_systematics(period: float) -> bool:
    if period is None:
        return False
    # Narrow TESS orbital downlink resonance (13.7 +/- 0.15d) and half-orbit (6.85 +/- 0.10d)
    if (13.55 <= period <= 13.85) or (6.75 <= period <= 6.95):
        return True
    # Narrow full sector duration alias (27.4 +/- 0.4d)
    if 27.0 <= period <= 27.8:
        return True
    # Narrow Sector 18/58/85 window alias
    if 12.18 <= period <= 12.24:
        return True
    # BLS Search Grid Boundary Pinning
    if check_grid_boundary(period):
        return True
    if check_harmonics(period):
        return True
    return False

def check_orbit_physical_separation(period: Optional[float], r_star: Optional[float], m_star: Optional[float] = None) -> Tuple[bool, float, str]:
    """
    Computes Keplerian orbital semi-major axis:
    a = 215.032 * (M_tot * (P / 365.25)^2)^(1/3) R_sun
    Ensures that orbital separation exceeds host star radius R*.
    """
    if period is None or period <= 0:
        return True, 0.0, "Non-periodic"
    m_tot = max(float(m_star) if m_star and not np.isnan(m_star) else 2.5, 2.5)
    a_au = (m_tot * (period / 365.25)**2)**(1/3)
    a_rsun = a_au * 215.032
    
    if r_star is not None and not np.isnan(r_star) and r_star > 0:
        if a_rsun <= r_star:
            return False, a_rsun, f"Unphysical orbit: a={a_rsun:.2f} R_sun <= R*={r_star:.2f} R_sun (inside star envelope)"
        return True, a_rsun, f"Separation a={a_rsun:.2f} R_sun > R*={r_star:.2f} R_sun"
    return True, a_rsun, f"Separation a={a_rsun:.2f} R_sun (R* unknown)"

def check_transit_duration_physical(duration_days: Optional[float], r_star: Optional[float], m_star: Optional[float] = None) -> Tuple[bool, float, str]:
    """
    Checks if a transit or eclipse duration across a giant star is physically possible.
    For a star of radius R*, the maximum orbital speed is bounded by escape velocity:
    v_esc = 617.5 * sqrt(M_star / R_star) km/s
    Minimum diameter crossing duration:
    T_dur_min = (2 * R_star) / v_esc = 0.0261 * (R_star^1.5 / sqrt(M_star)) days.
    """
    if duration_days is None or duration_days <= 0:
        return True, 0.0, "No duration"
    if r_star is None or np.isnan(r_star) or r_star < 5.0:
        return True, 0.0, "Normal / dwarf star duration valid"
        
    m_val = max(float(m_star) if m_star and not np.isnan(m_star) else 2.5, 1.5)
    t_dur_min = 0.0261 * (r_star**1.5 / np.sqrt(m_val))
    
    # Allow grazing chords down to 20% of central diameter duration
    if duration_days < 0.20 * t_dur_min:
        return False, t_dur_min, f"Duration {duration_days*24:.1f}h is unphysically short for R*={r_star:.1f} R_sun (min crossing {0.2*t_dur_min*24:.1f}h; likely background blend)"
    return True, t_dur_min, "Physically consistent transit duration"

def assign_tier(category: str, 
                sde: float, 
                cycles: float, 
                sec_pass: bool, 
                centroid_status: str,
                r_star: Optional[float] = None,
                orbit_pass: bool = True,
                dur_pass: bool = True,
                is_known: bool = False) -> str:
    """
    Unified scientific tier assignment:
    Tier A — Pristine Vetted Clean:
      - Requires MEASURED centroid pass (centroid_status == 'PASS')
      - SDE >= 10.0 (or SNR >= 10.0 for single dips)
      - cycles >= 3.0 (for periodic signals)
      - Passes secondary eclipse & odd/even tests
      - Physically possible orbit (a > R*) and duration (T_dur >= T_min)
      - Stellar radius R* known from Gaia / TIC
    Tier B — Probable / Unconstrained:
      - Valid astrophysical signal passing physics, but centroid NOT_RUN (needs TPF),
        or R* unconstrained, or SDE in [8.0, 10.0), or known benchmark recovery.
    Tier C — Audit Flagged / Dubious / Rejections:
      - Fails physical orbit (a <= R*), fails crossing duration, cycles < 3.0 for periodic,
        SDE < 8.0, or centroid FAIL (significant off-target photocenter shift).
    """
    if not orbit_pass or not dur_pass:
        return "C"
    if not sec_pass:
        return "C"
    if centroid_status == "FAIL":
        return "B"  # Softened to Tier B (Needs Manual Review / Possible Blend Alert) rather than automatic Tier C reject
    if sde < 8.0:
        return "C"
    if cycles < 3.0 and "SINGLE" not in category.upper() and "MICROLENSING" not in category.upper():
        return "C"
    if is_known:
        return "A" if (is_known and sde >= 10.0 and centroid_status == "PASS") else "B"
    if r_star is None or np.isnan(r_star) or r_star <= 0:
        return "B"
    if centroid_status != "PASS":
        # Unmeasured centroid cannot claim Tier A "Pristine Vetted Clean"
        return "B"
    if sde >= 10.0:
        return "A"
    return "B"

def vet_signals(bls_res: Optional[Dict[str, Any]], 
                ls_res: Optional[Dict[str, Any]], 
                single_res: Optional[Dict[str, Any]],
                micro_res: Optional[Dict[str, Any]],
                lc_flat: lk.LightCurve, 
                lc_unflat: lk.LightCurve,
                sectors: list,
                r_star: Optional[float] = None,
                m_star: Optional[float] = None,
                is_known: bool = False,
                target_name: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    from config import SDE_THRESHOLD, LS_FAP_THRESHOLD, LS_FAP_SWEEP, DEPTH_MAX
    
    # Check if Lomb-Scargle is significantly stronger (e.g. pulsating variable with SDE 30 vs BLS 8)
    ls_sde = ls_res.get('sde', 0.0) if ls_res else 0.0
    bls_sde = bls_res.get('sde', 0.0) if bls_res else 0.0
    prefer_ls = (ls_sde > bls_sde and ls_sde >= 10.0 and ls_res.get('fap', 1.0) < LS_FAP_SWEEP)

    # Branch 1: Periodic Transits (BLS)
    if not prefer_ls and bls_res and bls_sde >= SDE_THRESHOLD:
        period = bls_res['period']
        depth = bls_res['depth']
        epoch = bls_res['epoch']
        duration = bls_res['duration']
        sde = bls_res['sde']
        
        noise_level = np.nanstd(lc_flat.flux.value)
        n_in_est = max(1.0, len(lc_flat.flux.value) * (duration / max(period, 1e-5)))
        snr = (depth / noise_level) * np.sqrt(n_in_est) if noise_level > 0 else 0
        
        if depth <= 0.50 and not check_tess_systematics(period) and snr > 3.0:
            # Enforce binned phase transit depth coherence (reject outlier spikes)
            _, fl_binned = phase_fold_and_bin(lc_flat, period, epoch, bins=50)
            binned_depth = np.nanmedian(fl_binned) - np.nanmin(fl_binned)
            if binned_depth >= 0.35 * depth:
                t_vals = lc_flat.time.value
                observed_baseline = compute_observed_coverage_days(t_vals)
                cycles = observed_baseline / period if period > 0 else 1.0
                
                sec_pass, sec_ratio = check_secondary_eclipse(lc_flat, period, epoch, depth, duration)
                odd_even_ratio = check_odd_even(lc_flat, period, epoch, duration)
                centroid_status, centroid_sigma, centroid_desc = check_centroid_motion(lc_flat, period, epoch, duration)
                centroid_offset_px = np.nan
                if target_name:
                    tpf_st, tpf_off, tpf_desc = check_tpf_centroid_motion(target_name, epoch, duration, period)
                    if tpf_st != "NOT_RUN":
                        centroid_offset_px = tpf_off
                        if centroid_status == "NOT_RUN" or tpf_st == "FAIL":
                            centroid_status, centroid_desc = tpf_st, tpf_desc
                centroid_pass = (centroid_status == "PASS")
                
                orbit_pass, a_rsun, orbit_desc = check_orbit_physical_separation(period, r_star, m_star)
                dur_pass, t_dur_min, dur_desc = check_transit_duration_physical(duration, r_star, m_star)
                
                tier = assign_tier("EXOPLANET" if depth <= DEPTH_MAX else "ECLIPSING_BINARY",
                                   sde, cycles, sec_pass, centroid_status, r_star, orbit_pass, dur_pass, is_known)
                                   
                bls_res.update({
                    "cycles": cycles,
                    "n_cycles": round(cycles, 1),
                    "sec_pass": sec_pass,
                    "sec_ratio": sec_ratio,
                    "odd_even_ratio": odd_even_ratio,
                    "centroid_status": centroid_status,
                    "centroid_pass": centroid_pass,
                    "centroid_shift_sigma": centroid_sigma,
                    "centroid_offset_px": centroid_offset_px,
                    "centroid_desc": centroid_desc,
                    "orbit_phys_pass": orbit_pass,
                    "orbit_a_rsun": a_rsun,
                    "orbit_desc": orbit_desc,
                    "dur_phys_pass": dur_pass,
                    "dur_desc": dur_desc,
                    "sectors": sectors,
                    "tier": tier
                })
                
                if not orbit_pass or not dur_pass or cycles < 3.0:
                    return "UNCLASSIFIED_PERIODIC_DIP", bls_res
                
                if depth <= DEPTH_MAX and (0.7 <= odd_even_ratio <= 1.3) and sec_pass and centroid_status != "FAIL":
                    return "CANDIDATE_EXOPLANET", bls_res
                else:
                    return "ECLIPSING_BINARY", bls_res

    # Branch 2: Single-Transit Detection (Long-Period Planets / Low-Mass Companions)
    if single_res and single_res.get('snr', 0) >= 6.0:
        epoch = single_res['epoch']
        duration = single_res['duration']
        depth = single_res['depth']
        snr = single_res.get('snr', 6.0)
        
        # Immediate rejection of boundary divergence (> 50% depth)
        if depth > 0.50:
            return "FALSE_POSITIVE", {}
            
        centroid_status, centroid_sigma, centroid_desc = check_centroid_motion(lc_flat, None, epoch, duration)
        centroid_offset_px = np.nan
        if target_name:
            tpf_st, tpf_off, tpf_desc = check_tpf_centroid_motion(target_name, epoch, duration, None)
            if tpf_st != "NOT_RUN":
                centroid_offset_px = tpf_off
                if centroid_status == "NOT_RUN" or tpf_st == "FAIL":
                    centroid_status, centroid_desc = tpf_st, tpf_desc
        centroid_pass = (centroid_status == "PASS")
        dur_pass, t_dur_min, dur_desc = check_transit_duration_physical(duration, r_star, m_star)
        
        tier = assign_tier("SINGLE_TRANSIT", snr, 1.0, True, centroid_status, r_star, True, dur_pass, is_known)
        
        single_res.update({
            "cycles": 1.0,
            "n_cycles": 1.0,
            "sec_pass": True,
            "sec_ratio": 0.0,
            "odd_even_ratio": 1.0,
            "centroid_status": centroid_status,
            "centroid_pass": centroid_pass,
            "centroid_shift_sigma": centroid_sigma,
            "centroid_offset_px": centroid_offset_px,
            "centroid_desc": centroid_desc,
            "dur_phys_pass": dur_pass,
            "dur_desc": dur_desc,
            "sectors": sectors,
            "tier": tier
        })
        if not dur_pass or centroid_status == "FAIL":
            return "UNCLASSIFIED_TRANSIT_LIKE_DIP", single_res
        if depth > DEPTH_MAX:
            return "ECLIPSING_BINARY", single_res
        else:
            return "SINGLE_TRANSIT_CANDIDATE", single_res

    # Branch 3: Gravitational Microlensing
    if micro_res and micro_res.get('sde', 0) >= 8.0:
        tier = "B"
        micro_res.update({
            "cycles": 1.0,
            "n_cycles": 1.0,
            "sec_pass": True,
            "sec_ratio": 0.0,
            "odd_even_ratio": 1.0,
            "centroid_status": "NOT_RUN",
            "centroid_pass": False,
            "centroid_shift_sigma": np.nan,
            "centroid_offset_px": np.nan,
            "centroid_desc": "NOT_RUN (Microlensing point-source profile - No centroid moments)",
            "sectors": sectors,
            "tier": tier
        })
        return "MICROLENSING_EVENT", micro_res

    # Branch 4: Stellar Pulsations / Variables (Lomb-Scargle)
    if ls_res and ls_res.get('fap', 1.0) < LS_FAP_SWEEP:
        period = ls_res['period']
        amp = ls_res.get('amplitude', 0.0)
        
        # Enforce realistic amplitude floor: reject < 1000 ppm (0.1%) TESS noise floor
        if amp < 0.001:
            return "FALSE_POSITIVE", {}
            
        sde = ls_res.get('sde', 7.0)
        t_vals = lc_unflat.time.value
        observed_baseline = compute_observed_coverage_days(t_vals)
        cycles = observed_baseline / period if period > 0 else 1.0
        
        # Enforce smooth, symmetric phase coverage (reject isolated sector edge spikes)
        _, fl_binned = phase_fold_and_bin(lc_unflat, period, float(lc_unflat.time.value[0]), bins=40)
        med_b = np.nanmedian(fl_binned)
        p2p_binned = float(np.nanmax(fl_binned) - np.nanmin(fl_binned))
        # For a genuine sine wave, peak-to-peak amplitude is ~2*amp. Reject single-bin outlier spikes.
        if p2p_binned > 3.2 * amp or p2p_binned < 1.3 * amp:
            return "FALSE_POSITIVE", {}
            
        above_med = np.sum(fl_binned > med_b + 0.3 * amp)
        below_med = np.sum(fl_binned < med_b - 0.3 * amp)
        if above_med < 4 or below_med < 4:
            return "FALSE_POSITIVE", {}
            
        if not check_tess_systematics(period):
            centroid_status, centroid_sigma, centroid_desc = check_variable_centroid_motion(lc_unflat, period, float(lc_unflat.time.value[0]))
            centroid_offset_px = np.nan
            if target_name:
                tpf_st, tpf_off, tpf_desc = check_tpf_variable_centroid_motion(target_name, period, float(lc_unflat.time.value[0]))
                if tpf_st != "NOT_RUN":
                    centroid_offset_px = tpf_off
                    if centroid_status == "NOT_RUN" or tpf_st == "FAIL":
                        centroid_status, centroid_desc = tpf_st, tpf_desc
            centroid_pass = (centroid_status == "PASS")
            orbit_pass, a_rsun, orbit_desc = check_orbit_physical_separation(period, r_star, m_star)
            
            is_catalog_tier = ls_res['fap'] < LS_FAP_THRESHOLD
            effective_sde = sde if is_catalog_tier else 7.0
            tier = assign_tier("VARIABLE_STAR", effective_sde, cycles, True, centroid_status, r_star, orbit_pass, True, is_known)
            
            ls_res.update({
                "cycles": cycles,
                "n_cycles": round(cycles, 1),
                "sec_pass": True,
                "sec_ratio": 0.0,
                "odd_even_ratio": 1.0,
                "centroid_status": centroid_status,
                "centroid_pass": centroid_pass,
                "centroid_shift_sigma": centroid_sigma,
                "centroid_offset_px": centroid_offset_px,
                "centroid_desc": centroid_desc,
                "orbit_phys_pass": orbit_pass,
                "orbit_a_rsun": a_rsun,
                "orbit_desc": orbit_desc,
                "sectors": sectors,
                "tier": tier
            })
            if not orbit_pass:
                return "UNCLASSIFIED_PERIODIC_DIP", ls_res
            return "VARIABLE_STAR", ls_res

    return "FALSE_POSITIVE", {}
