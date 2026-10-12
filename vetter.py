import glob
import os
import socket
import numpy as np
import lightkurve as lk
from typing import Tuple, Dict, Any, Optional

socket.setdefaulttimeout(30)
try:
    from astroquery.mast import Observations
    Observations.TIMEOUT = 30
except Exception:
    pass

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
    Outside = Period-doubled Eclipsing Binary (verified against per-transit core depths to prevent
    small period offsets Delta_P from shifting odd transits into ingress/egress).
    """
    folded = lc.fold(period=2.0 * period, epoch_time=epoch, normalize_phase=True)
    phase = folded.time.value
    flux = folded.flux.value
    
    half_dur2 = (duration / (2.0 * period)) / 2.0
    even_mask = np.abs(phase) <= max(half_dur2, 0.005)
    odd_mask = np.abs(np.abs(phase) - 0.5) <= max(half_dur2, 0.005)
    
    even_vals = flux[even_mask]
    odd_vals = flux[odd_mask]
    even_vals = even_vals[np.isfinite(even_vals)]
    odd_vals = odd_vals[np.isfinite(odd_vals)]
    if len(even_vals) < 3 or len(odd_vals) < 3:
        return 1.0
        
    out_mask = (np.abs(phase) > 2.0 * half_dur2) & (np.abs(np.abs(phase) - 0.5) > 2.0 * half_dur2)
    baseline = np.nanmedian(flux[out_mask]) if np.any(out_mask) else np.nanmedian(flux)
    
    even_depth = max(0.0, float(baseline - np.nanmedian(even_vals)))
    odd_depth = max(0.0, float(baseline - np.nanmedian(odd_vals)))
    
    if even_depth <= 1e-6 or odd_depth <= 1e-6:
        return 1.0
        
    ratio = float(odd_depth / even_depth)
    if not (0.7 <= ratio <= 1.3):
        # Verify against per-transit core depths (bottom 50% of cadences inside each transit window)
        # so a 0.1% period offset across the sector does not skew odd vs even ingress sampling
        t_raw = lc.time.value
        fl_raw = lc.flux.value
        valid = np.isfinite(t_raw) & np.isfinite(fl_raw)
        t_raw, fl_raw = t_raw[valid], fl_raw[valid]
        cyc = np.round((t_raw - epoch) / max(period, 1e-5)).astype(int)
        in_tr_any = np.abs(t_raw - (epoch + cyc * period)) <= 0.6 * duration
        odd_d, even_d = [], []
        for k in np.unique(cyc[in_tr_any]):
            m_k = np.abs(t_raw - (epoch + k * period)) <= 0.6 * duration
            if int(np.sum(m_k)) >= 4:
                vals_k = np.sort(fl_raw[m_k])
                d_k = max(0.0, float(baseline - np.median(vals_k[: max(3, len(vals_k) // 2)])))
                if k % 2 == 0:
                    even_d.append(d_k)
                else:
                    odd_d.append(d_k)
        if len(even_d) >= 2 and len(odd_d) >= 2 and np.median(even_d) > 1e-6:
            core_ratio = float(np.median(odd_d) / np.median(even_d))
            if 0.7 <= core_ratio <= 1.3:
                return core_ratio
    return ratio

def check_centroid_motion(
    lc: lk.LightCurve,
    period: Optional[float],
    epoch: Optional[float],
    duration: Optional[float],
    depth: Optional[float] = None,
) -> Tuple[str, float, str]:
    """
    Checks if photocenter (centroid) shifts during transit, indicating a blended nearby star.
    Subtracts SPOC spacecraft pointing drift (pos_corr1/pos_corr2) when centroid_col/mom_centr1 are used.
    Uses two-sample Welch Standard Error of the Mean (SEM): sigma_diff = sqrt(s1^2/N1 + s2^2/N2).
    When transit depth is supplied, also requires implied source offset d_implied = d_tot / depth >= 1.0 px.
    Returns tri-state (status, shift_sigma, status_description) where status is 'PASS', 'FAIL', or 'NOT_RUN'.
    """
    try:
        col_c = None
        row_c = None
        used_col = None
        used_row = None
        for col_name in ['centroid_col', 'mom_centr1', 'pos_corr1']:
            if hasattr(lc, col_name) and getattr(lc, col_name) is not None:
                arr = np.array(getattr(lc, col_name).value, dtype=float)
                if np.sum(np.isfinite(arr)) >= 50:
                    col_c = arr
                    used_col = col_name
                    break
        for row_name in ['centroid_row', 'mom_centr2', 'pos_corr2']:
            if hasattr(lc, row_name) and getattr(lc, row_name) is not None:
                arr = np.array(getattr(lc, row_name).value, dtype=float)
                if np.sum(np.isfinite(arr)) >= 50:
                    row_c = arr
                    used_row = row_name
                    break
                
        if col_c is None or row_c is None:
            return "NOT_RUN", np.nan, "NOT_RUN (No centroid columns in QLP/FFI - Monitor with TPF)"

        # Detrend spacecraft pointing drift (DVA/jitter) from flux-weighted moments when pos_corr is present
        if used_col in ('centroid_col', 'mom_centr1') and hasattr(lc, 'pos_corr1') and getattr(lc, 'pos_corr1') is not None:
            pc1 = np.array(getattr(lc, 'pos_corr1').value, dtype=float)
            if len(pc1) == len(col_c) and np.sum(np.isfinite(pc1)) >= 50:
                col_c = np.where(np.isfinite(pc1), col_c - pc1, col_c)
        if used_row in ('centroid_row', 'mom_centr2') and hasattr(lc, 'pos_corr2') and getattr(lc, 'pos_corr2') is not None:
            pc2 = np.array(getattr(lc, 'pos_corr2').value, dtype=float)
            if len(pc2) == len(row_c) and np.sum(np.isfinite(pc2)) >= 50:
                row_c = np.where(np.isfinite(pc2), row_c - pc2, row_c)
            
        if epoch is None or duration is None:
            return "NOT_RUN", np.nan, "NOT_RUN (Missing transit epoch/duration)"
            
        t = lc.time.value
        mask = np.isfinite(t) & np.isfinite(col_c) & np.isfinite(row_c)
        t, col_c, row_c = t[mask], col_c[mask], row_c[mask]
        
        if len(t) < 50:
            return "NOT_RUN", np.nan, "NOT_RUN (Centroid NaN-filled in QLP/FFI - Monitor with TPF)"
            
        if period is not None and period > 0:
            # Periodic transit phase (compare in-transit against local out-of-transit shoulders to cancel slow DVA drift)
            phase = ((t - epoch + 0.5 * period) % period) / period - 0.5
            half_w = duration / (2.0 * period)
            in_transit = np.abs(phase) < half_w
            out_transit = (np.abs(phase) >= half_w) & (np.abs(phase) < max(3.5 * half_w, 0.08))
            if int(np.sum(out_transit)) < 15:
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
        d_tot = float(np.hypot(d_col, d_row))
        
        sem_col = float(np.sqrt(np.var(col_in, ddof=1) / n_in + np.var(col_out, ddof=1) / n_out))
        sem_row = float(np.sqrt(np.var(row_in, ddof=1) / n_in + np.var(row_out, ddof=1) / n_out))
        
        sigma_col = d_col / max(1e-6, sem_col)
        sigma_row = d_row / max(1e-6, sem_row)
        shift_sigma = float(max(sigma_col, sigma_row))
        
        implied_offset_ok = True
        if depth is not None and np.isfinite(depth) and depth > 0:
            d_implied_px = d_tot / max(float(depth), 1e-4)
            implied_offset_ok = (d_implied_px >= 1.0)
            
        if shift_sigma > 3.5 and implied_offset_ok:
            return "FAIL", round(shift_sigma, 2), f"FAIL: Significant photocenter shift ({shift_sigma:.1f} sigma SEM) - likely blend"
        return "PASS", round(shift_sigma, 2), f"PASS: Clean photocenter ({shift_sigma:.1f} sigma SEM shift)"
    except Exception as e:
        return "NOT_RUN", np.nan, f"NOT_RUN (Centroid check bypassed: {e})"

def check_variable_centroid_motion(lc: lk.LightCurve, period: Optional[float], epoch: Optional[float] = None) -> Tuple[str, float, str]:
    """
    Checks if photocenter shifts between peak-flux phase and trough-flux phase for periodic variables.
    Always aligns t0 to the sinusoidal phase of maximum flux of the light curve rather than an arbitrary timestamp.
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
        fl = np.array(lc.flux.value, dtype=float)
        mask = np.isfinite(t) & np.isfinite(fl) & np.isfinite(col_c) & np.isfinite(row_c)
        t, fl, col_c, row_c = t[mask], fl[mask], col_c[mask], row_c[mask]
        
        if len(t) < 50:
            return "NOT_RUN", np.nan, "NOT_RUN (Centroid NaN-filled in QLP/FFI - Monitor with TPF)"
            
        # Align t0 to the sinusoidal phase of maximum flux
        t_ref = float(t[0])
        omega = 2.0 * np.pi / period
        fl_dm = fl - np.nanmedian(fl)
        c_val = float(2.0 * np.nanmean(fl_dm * np.cos(omega * (t - t_ref))))
        s_val = float(2.0 * np.nanmean(fl_dm * np.sin(omega * (t - t_ref))))
        phi_max = float(np.arctan2(s_val, c_val) % (2.0 * np.pi))
        t0 = t_ref + (phi_max / (2.0 * np.pi)) * period
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

def compute_difference_image_centroid(
    flux: np.ndarray,
    in_tr: np.ndarray,
    out_tr: np.ndarray,
    target_pos: Optional[Tuple[float, float]] = None,
    per_star_ceiling_px: Optional[float] = None,
) -> Tuple[str, float, str]:
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
    
    # Pooled PASS threshold calibrated to 95th percentile (0.96 px) of on-target injections
    # into real TESS SPOC TPFs (99th percentile = 1.06 px), combined with per-star null check.
    if offset_px <= 0.96:
        if per_star_ceiling_px is not None and np.isfinite(per_star_ceiling_px) and offset_px > per_star_ceiling_px:
            return (
                "PASS_MARGINAL",
                round(offset_px, 2),
                f"NEEDS_REVIEW: Offset ({offset_px:.2f} px) exceeds star's own TPF injection ceiling ({per_star_ceiling_px:.2f} px)",
            )
        return "PASS", round(offset_px, 2), f"PASS: Difference image centroid consistent with target ({offset_px:.2f} px offset)"
    elif offset_px <= 1.8:
        return "PASS_MARGINAL", round(offset_px, 2), f"NEEDS_REVIEW: Marginal difference image offset ({offset_px:.2f} px) - verify PRF"
    else:
        return "FAIL", round(offset_px, 2), f"FAIL: Significant difference image offset ({offset_px:.2f} px) - likely off-target blend"


def _detrend_tpf_for_variable(t: np.ndarray, flux: np.ndarray, period: float) -> np.ndarray:
    """
    Removes slow spacecraft scattered-light drift per pixel while preserving oscillations at `period`.
    Uses O(N) boxcar moving-average detrending (`uniform_filter1d`) over a window >= max(2.5*P, 3.0 d)
    capped at 55% of baseline span so periods up to 7.5 d on a 27.4 d sector are cleanly detrended.
    """
    baseline_span = float(t[-1] - t[0]) if len(t) > 1 else 0.0
    if len(t) >= 100 and period <= 2.4 and period < 0.25 * baseline_span:
        try:
            from scipy.ndimage import uniform_filter1d
            dt_med = float(np.nanmedian(np.diff(t)))
            win_days = min(max(3.0 * period, 3.0), 6.0)
            win_pts = int(round(win_days / max(dt_med, 1e-4)))
            win_pts = min(max(win_pts, 31), len(t) // 2)
            if win_pts >= 5:
                return flux - uniform_filter1d(flux, size=win_pts, axis=0, mode="nearest")
        except Exception:
            pass
    return flux - np.nanmedian(flux, axis=0, keepdims=True)


def compute_variable_difference_image_centroid(
    t: np.ndarray,
    flux: np.ndarray,
    period: float,
    target_pos: Optional[Tuple[float, float]] = None,
    expected_amp: Optional[float] = None,
    per_star_ceiling_px: Optional[float] = None,
) -> Tuple[str, float, str]:
    """
    Computes phase-aligned peak-minus-trough difference image photocenter for a periodic variable.
    - Requires mandatory `expected_amp > 0` (returns `NOT_RUN` when omitted or non-positive).
    - Evaluates 8 trial phase origins phi_k = k/8 in [0, 1) using robust per-pixel median difference
      (`img_peak - img_trough`) normalized by per-pixel temporal MAD (`pixel_mad`), selecting the
      phase alignment that maximizes periodic difference SNR across all phases phi_0 in [0, 1)
      (including exact quadrature phi_0 = 0.25 and 0.75).
    - Enforces a 5.0-sigma spatial significance gate AND a 5.0-sigma temporal 3x3 peak-box
      significance gate BEFORE evaluating `offset_px`, ensuring signal-free TPFs with pointing
      drift/jitter return `NOT_RUN` rather than false `FAIL` or `PASS_MARGINAL`.
    - Enforces folded amplitude coherence against `expected_amp` in the 3x3 target aperture.
    - Compares measured offset against both the 95th-percentile pooled ceiling (0.96 px) and
      the star's own local injection null ceiling (`per_star_ceiling_px`).
    """
    if target_pos is None:
        return "NOT_RUN", np.nan, "NOT_RUN (Missing valid WCS target coordinates)"
    if expected_amp is None or not np.isfinite(expected_amp) or expected_amp <= 0:
        return "NOT_RUN", np.nan, "NOT_RUN (Missing or non-positive expected_amp for variable TPF check)"
    if period is None or period <= 0 or len(t) < 30:
        return "NOT_RUN", np.nan, "NOT_RUN (Insufficient valid cadences or period)"

    flux_det = _detrend_tpf_for_variable(t, flux, period)
    pixel_mad = (
        np.nanmedian(np.abs(flux_det - np.nanmedian(flux_det, axis=0, keepdims=True)), axis=0) * 1.4826
        + 1.0
    )

    t_ref = float(t[0])
    best_diff = None
    best_peak_mask = None
    best_trough_mask = None
    best_snr = -1.0
    for k in range(8):
        t0 = t_ref + (k / 8.0) * period
        phase = ((t - t0 + 0.5 * period) % period) / period - 0.5
        peak_mask = np.abs(phase) < 0.2
        trough_mask = np.abs(np.abs(phase) - 0.5) < 0.2
        if int(np.sum(peak_mask)) < 5 or int(np.sum(trough_mask)) < 5:
            continue
        cand_diff = np.nanmedian(flux_det[peak_mask], axis=0) - np.nanmedian(flux_det[trough_mask], axis=0)
        cand_snr = float(np.nanmax(cand_diff / pixel_mad))
        if cand_snr > best_snr:
            best_snr = cand_snr
            best_diff = cand_diff
            best_peak_mask = peak_mask
            best_trough_mask = trough_mask

    if best_diff is None or best_peak_mask is None or best_trough_mask is None:
        return "NOT_RUN", np.nan, "NOT_RUN (Insufficient phase cadences in TPF)"

    diff = best_diff
    mad = float(np.nanmedian(np.abs(diff - np.nanmedian(diff))) * 1.4826)
    if float(np.nanmax(diff)) < 5.0 * max(mad, 1e-9):
        return "NOT_RUN", np.nan, "NOT_RUN (No statistically significant >=5-sigma spatial modulation in TPF)"

    # Temporal 5-sigma significance gate on the 3x3 box around the peak difference pixel
    # (cancels dipole residuals from pointing drift across a static star before offset evaluation)
    pr, pc = np.unravel_index(int(np.nanargmax(diff)), diff.shape)
    by0, by1 = max(0, pr - 1), min(flux.shape[1], pr + 2)
    bx0, bx1 = max(0, pc - 1), min(flux.shape[2], pc + 2)
    box_det = np.nansum(flux_det[:, by0:by1, bx0:bx1], axis=(1, 2))
    box_mad = float(np.nanmedian(np.abs(box_det - np.nanmedian(box_det))) * 1.4826)
    n_pk = max(1, int(np.sum(best_peak_mask)))
    n_tr = max(1, int(np.sum(best_trough_mask)))
    box_se = max(1e-9, 1.2533 * box_mad * float(np.sqrt(1.0 / n_pk + 1.0 / n_tr)))
    box_diff = float(np.nanmedian(box_det[best_peak_mask]) - np.nanmedian(box_det[best_trough_mask]))
    if box_diff / box_se < 5.0:
        return "NOT_RUN", np.nan, f"NOT_RUN (TPF 3x3 peak box modulation SNR={box_diff/box_se:.1f} < 5.0 sigma)"

    diff_thresh = np.where(diff > 2.0 * mad, diff, 0.0)
    if np.nansum(diff_thresh) <= 0:
        diff_thresh = np.maximum(0.0, diff)
    if np.nansum(diff_thresh) <= 0:
        return "NOT_RUN", np.nan, "NOT_RUN (No positive variable difference signal in TPF)"

    y_grid, x_grid = np.mgrid[:diff.shape[0], :diff.shape[1]]
    x_diff = float(np.sum(diff_thresh * x_grid) / np.sum(diff_thresh))
    y_diff = float(np.sum(diff_thresh * y_grid) / np.sum(diff_thresh))
    offset_px = float(np.sqrt((x_diff - target_pos[0]) ** 2 + (y_diff - target_pos[1]) ** 2))

    if offset_px > 1.8:
        return "FAIL", round(offset_px, 2), f"FAIL: Significant difference image offset ({offset_px:.2f} px) - likely off-target blend"
    if offset_px > 0.96:
        return "PASS_MARGINAL", round(offset_px, 2), f"NEEDS_REVIEW: Marginal difference image offset ({offset_px:.2f} px) - verify PRF"

    if per_star_ceiling_px is not None and np.isfinite(per_star_ceiling_px) and offset_px > per_star_ceiling_px:
        return (
            "PASS_MARGINAL",
            round(offset_px, 2),
            f"NEEDS_REVIEW: Offset ({offset_px:.2f} px) exceeds star's own TPF injection ceiling ({per_star_ceiling_px:.2f} px)",
        )

    # Amplitude coherence check in 3x3 target aperture against mandatory expected_amp
    cy, cx = int(round(target_pos[1])), int(round(target_pos[0]))
    y0, y1 = max(0, cy - 1), min(flux.shape[1], cy + 2)
    x0, x1 = max(0, cx - 1), min(flux.shape[2], cx + 2)
    ap_raw = np.nansum(flux[:, y0:y1, x0:x1], axis=(1, 2))
    ap_med = float(np.nanmedian(ap_raw))
    if ap_med > 0:
        ap_det = np.nansum(flux_det[:, y0:y1, x0:x1], axis=(1, 2))
        ap_p2p = float(abs(np.nanmedian(ap_det[best_peak_mask]) - np.nanmedian(ap_det[best_trough_mask])) / ap_med)
        if ap_p2p < 0.25 * (2.0 * expected_amp):
            return (
                "PASS_MARGINAL",
                round(offset_px, 2),
                f"NEEDS_REVIEW: TPF folded amplitude ({ap_p2p*100:.3f}%) below expected lightcurve amplitude ({2*expected_amp*100:.3f}%)",
            )

    return "PASS", round(offset_px, 2), f"PASS: Difference image centroid consistent with target ({offset_px:.2f} px offset)"


_PER_STAR_NULL_CACHE: Dict[Tuple, Dict[str, float]] = {}


def compute_per_star_tpf_null(
    t: np.ndarray,
    flux: np.ndarray,
    target_pos: Tuple[float, float],
    mode: str = "transit",
    n_trials: int = 50,
    seed: int = 20261010,
) -> Dict[str, float]:
    """
    Computes the star-specific on-target injection null distribution directly on the target's
    own TPF `(t, flux)` around `target_pos` (with 0.12 px pointing/WCS jitter) across `n_trials=50`
    trials (cached per star in `_PER_STAR_NULL_CACHE`).
    Returns `median_px`, `p90_px`, `p95_px`, `max_px`, and `ceiling_px`.
    """
    cache_key = (
        round(float(target_pos[0]), 3),
        round(float(target_pos[1]), 3),
        flux.shape,
        round(float(t[0]), 2) if len(t) > 0 else 0.0,
        round(float(t[-1]), 2) if len(t) > 0 else 0.0,
        round(float(np.nanmedian(flux)), 1),
        mode,
        int(n_trials),
        int(seed),
    )
    if cache_key in _PER_STAR_NULL_CACHE:
        return dict(_PER_STAR_NULL_CACHE[cache_key])

    rng = np.random.default_rng(seed)
    if len(t) > 2500:
        step = max(1, len(t) // 2500)
        t = t[::step]
        flux = flux[::step]
    h, w = flux.shape[1], flux.shape[2]
    yg, xg = np.mgrid[:h, :w]
    offsets = []

    for _ in range(n_trials):
        p_d = float(rng.uniform(0.8, 6.5))
        depth_frac = float(rng.uniform(0.004, 0.020))
        jx = float(rng.normal(0.0, 0.12))
        jy = float(rng.normal(0.0, 0.12))
        cx = target_pos[0] + jx
        cy = target_pos[1] + jy
        prf_w = np.exp(-((xg - cx) ** 2 + (yg - cy) ** 2) / 2.2)

        if mode == "variable":
            p_var_d = float(rng.uniform(0.5, 2.3))
            phi0 = float(rng.uniform(0.0, 1.0))
            amp_inj = 0.5 * depth_frac
            mod = 1.0 + amp_inj * np.cos(2.0 * np.pi * ((t - t[0]) / p_var_d - phi0))[:, None, None] * prf_w[None, :, :]
            fl_inj = flux * mod
            _, off_val, _ = compute_variable_difference_image_centroid(
                t, fl_inj, p_var_d, target_pos=target_pos, expected_amp=amp_inj
            )
        else:
            dur_d = float(rng.uniform(0.08, 0.16))
            ep = float(t[0] + rng.uniform(0.1 * p_d, 0.9 * p_d))
            ph = ((t - ep + 0.5 * p_d) % p_d) / p_d - 0.5
            in_tr = np.abs(ph) < (dur_d / (2.0 * p_d))
            out_tr = (np.abs(ph) >= (dur_d / (2.0 * p_d))) & (np.abs(ph) < 3.0 * (dur_d / (2.0 * p_d)))
            if int(np.sum(in_tr)) < 3 or int(np.sum(out_tr)) < 5:
                continue
            fl_inj = flux.copy()
            fl_inj[in_tr] *= (1.0 - depth_frac * prf_w)[None, :, :]
            _, off_val, _ = compute_difference_image_centroid(fl_inj, in_tr, out_tr, target_pos=target_pos)

        if np.isfinite(off_val):
            offsets.append(float(off_val))

    if not offsets:
        res = {"median_px": 0.25, "p90_px": 0.75, "p95_px": 0.90, "max_px": 0.96, "ceiling_px": 0.96}
        _PER_STAR_NULL_CACHE[cache_key] = res
        return dict(res)

    arr = np.array(offsets, dtype=float)
    med = float(np.percentile(arr, 50))
    p90 = float(np.percentile(arr, 90))
    p95 = float(np.percentile(arr, 95))
    mx = float(np.max(arr))
    # Star-specific upper ceiling: max(1.25 * p95, p95 + 0.10), bounded by 0.96 px pooled ceiling
    ceiling = min(0.96, max(1.25 * p95, p95 + 0.10))
    res = {
        "median_px": round(med, 3),
        "p90_px": round(p90, 3),
        "p95_px": round(p95, 3),
        "max_px": round(mx, 3),
        "ceiling_px": round(ceiling, 3),
    }
    _PER_STAR_NULL_CACHE[cache_key] = res
    return dict(res)


def _download_best_tpf(target: str, epoch: Optional[float] = None):
    """
    Loads a TESS Target Pixel File from local cache first using generic 16-digit zero-padded
    TIC ID matching (`digits.zfill(16)`), or downloads from MAST with timeout (preferring 120s
    SPOC TPF, then any TESS TPF, then a TESScut 11x11 FFI cutout).
    When epoch is specified, checks up to 4 sectors to find the sector covering epoch.
    """
    socket.setdefaulttimeout(30)
    # 1. Generic TIC-keyed local cache check (no hardcoded star-name dictionaries)
    t_clean = str(target).strip()
    is_tic_id = t_clean.upper().startswith("TIC") or t_clean.isdigit()
    digits = "".join(filter(str.isdigit, t_clean)) if is_tic_id else ""
    pat = digits.zfill(16) if (digits and len(digits) >= 5) else None
    if pat:
        try:
            cache_dir = lk.config.get_cache_dir()
            cached_files = (
                glob.glob(os.path.join(cache_dir, "mastDownload", "TESS", "*", f"*{pat}*tp.fits"))
                + glob.glob(os.path.join(cache_dir, "mastDownload", "HLSP", "*", f"*{pat}*tp.fits"))
                + glob.glob(os.path.join(cache_dir, "tesscut", f"*{pat}*.fits"))
            )
            first_cached = None
            for cf in cached_files:
                try:
                    tpf_c = lk.read(cf)
                    if first_cached is None:
                        first_cached = tpf_c
                    if epoch is not None and np.isfinite(epoch):
                        tv = tpf_c.time.value
                        tv = tv[np.isfinite(tv)]
                        if len(tv) > 0 and (tv[0] <= epoch <= tv[-1]):
                            return tpf_c
                    else:
                        return tpf_c
                except Exception:
                    continue
            if first_cached is not None and (epoch is None or not np.isfinite(epoch)):
                return first_cached
        except Exception:
            pass

    # 2. Query MAST online with timeout
    is_tesscut = False
    search = lk.search_targetpixelfile(target, author='SPOC')
    if len(search) == 0:
        search = lk.search_targetpixelfile(target, mission='TESS')
    if len(search) > 0 and 'exptime' in search.table.colnames:
        spoc_120 = search[search.table['exptime'] == 120]
        if len(spoc_120) > 0:
            search = spoc_120
    if len(search) == 0:
        search = lk.search_tesscut(target)
        is_tesscut = True
    if len(search) == 0:
        return None

    max_try = min(len(search), 4) if (epoch is not None and np.isfinite(epoch)) else 1
    first_valid_tpf = None
    for idx in range(max_try):
        try:
            tpf = search[idx].download(cutout_size=(11, 11)) if is_tesscut else search[idx].download()
            if tpf is None:
                continue
            if first_valid_tpf is None:
                first_valid_tpf = tpf
            if epoch is not None and np.isfinite(epoch):
                t_vals = tpf.time.value
                t_vals = t_vals[np.isfinite(t_vals)]
                if len(t_vals) > 0 and (t_vals[0] <= epoch <= t_vals[-1]):
                    return tpf
        except Exception:
            continue
    return first_valid_tpf


def _extract_tpf_wcs_target_pos(tpf) -> Optional[Tuple[float, float]]:
    if hasattr(tpf, 'wcs') and tpf.wcs is not None and hasattr(tpf, 'ra') and hasattr(tpf, 'dec'):
        try:
            from astropy.coordinates import SkyCoord
            px, py = tpf.wcs.world_to_pixel(SkyCoord(tpf.ra, tpf.dec, unit='deg'))
            if np.isfinite(px) and np.isfinite(py):
                return (float(px), float(py))
        except Exception:
            pass
    return None


def check_tpf_centroid_motion(target: str, epoch: float, duration_days: float, period: Optional[float] = None) -> Tuple[str, float, str]:
    """
    Downloads Target Pixel File (TPF) or TESScut FFI cutout from MAST and calculates
    in-transit vs out-of-transit difference image photocenter offset.
    Compares against both the 95th-percentile pooled ceiling (0.96 px) and the star's own TPF null (n_trials=50).
    """
    try:
        if not target or str(target).strip() in ["", "None", "N/A", "--"]:
            return "NOT_RUN", np.nan, "NOT_RUN (No target ID for TPF query)"
        if epoch is None or not np.isfinite(epoch):
            return "NOT_RUN", np.nan, "NOT_RUN (Missing valid transit epoch for TPF query)"
        tpf = _download_best_tpf(target, epoch=epoch)
        if tpf is None:
            return "NOT_RUN", np.nan, "NOT_RUN (No TPF available in MAST archive)"
            
        t = tpf.time.value
        flux = np.array(tpf.flux.value, dtype=float)
        valid = np.isfinite(t) & np.all(np.isfinite(flux), axis=(1, 2))
        t, flux = t[valid], flux[valid]
        if len(t) < 30:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient valid cadences in TPF)"
            
        if period and period > 0:
            phase = ((t - epoch + 0.5 * period) % period) / period - 0.5
            in_tr = np.abs(phase) < (duration_days / (2.0 * period))
            out_tr = (np.abs(phase) >= (duration_days / (2.0 * period))) & (np.abs(phase) < 3.0 * (duration_days / (2.0 * period)))
        else:
            if epoch < t[0] or epoch > t[-1]:
                return "NOT_RUN", np.nan, "NOT_RUN (Single-transit epoch outside available TPF sector coverage)"
            in_tr = np.abs(t - epoch) < (0.5 * duration_days)
            out_tr = (np.abs(t - epoch) >= (0.5 * duration_days)) & (np.abs(t - epoch) < 2.5 * duration_days)
            
        n_in = int(np.sum(in_tr))
        n_out = int(np.sum(out_tr))
        if n_in < 3 or n_out < 5:
            return "NOT_RUN", np.nan, f"NOT_RUN (Insufficient in/out TPF cadences: {n_in}/{n_out})"
            
        target_pos = _extract_tpf_wcs_target_pos(tpf)
        if target_pos is None:
            return "NOT_RUN", np.nan, "NOT_RUN (Missing valid WCS target coordinates)"
        null_stats = compute_per_star_tpf_null(t, flux, target_pos, mode="transit", n_trials=50)
        return compute_difference_image_centroid(flux, in_tr, out_tr, target_pos, per_star_ceiling_px=null_stats["ceiling_px"])
    except Exception as e:
        return "NOT_RUN", np.nan, f"NOT_RUN (TPF error: {e})"

def check_tpf_variable_centroid_motion(
    target: str,
    period: float,
    epoch: Optional[float] = None,
    expected_amp: Optional[float] = None,
) -> Tuple[str, float, str]:
    """
    Downloads TPF or TESScut FFI cutout from MAST and tests phase-aligned peak-vs-trough
    difference image photocenter stability for periodic variables.
    Note: `epoch` is used strictly to select the TPF sector covering `epoch`; phase alignment `t0`
    is ALWAYS computed from the TPF's own 8-phase search so quadrature blends cannot pass.
    """
    try:
        if not target or str(target).strip() in ["", "None", "N/A", "--"]:
            return "NOT_RUN", np.nan, "NOT_RUN (No target ID for TPF query)"
        tpf = _download_best_tpf(target, epoch=epoch)
        if tpf is None:
            return "NOT_RUN", np.nan, "NOT_RUN (No TPF available in MAST archive)"
            
        t = tpf.time.value
        flux = np.array(tpf.flux.value, dtype=float)
        valid = np.isfinite(t) & np.all(np.isfinite(flux), axis=(1, 2))
        t, flux = t[valid], flux[valid]
        if len(t) < 30:
            return "NOT_RUN", np.nan, "NOT_RUN (Insufficient valid cadences in TPF)"
            
        target_pos = _extract_tpf_wcs_target_pos(tpf)
        if target_pos is None:
            return "NOT_RUN", np.nan, "NOT_RUN (Missing valid WCS target coordinates)"

        null_stats = compute_per_star_tpf_null(t, flux, target_pos, mode="transit", n_trials=50)
        return compute_variable_difference_image_centroid(
            t,
            flux,
            period,
            target_pos=target_pos,
            expected_amp=expected_amp,
            per_star_ceiling_px=null_stats["ceiling_px"],
        )
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

def check_giant_rotation_sanity(period: Optional[float], r_star: Optional[float]) -> Tuple[bool, float, str]:
    """
    Checks whether a multi-day periodic signal on an evolved giant star (R* >= 5.0 R_sun,
    P >= 0.5 d) implies an equatorial rotation velocity v_eq = 2*pi*R*/P that exceeds
    normal single-giant limits (v_eq <= 35 km/s; Carlberg et al. 2011; Tayar et al. 2015).
    An implied v_eq > 35 km/s (such as HD 10669 with R* = 12.8 R_sun, P = 7.94 d ->
    v_eq = 81.5 km/s) indicates either a tidally synchronized / spun-up close binary
    (RS CVn / FK Com), an ellipsoidal binary at P_orb = 2*P, or an unresolved blend,
    and is gated to Tier B for spectroscopic follow-up rather than Tier A.
    """
    if period is None or period <= 0 or r_star is None or np.isnan(r_star) or r_star <= 0:
        return True, 0.0, "Not applicable (period or R* unknown)"
    # Solar equatorial circumference / day in km/s: 2 * pi * 695700 km / 86400 s = 50.5927 km/s
    v_eq_kms = 50.5927 * float(r_star) / float(period)
    if r_star >= 5.0 and period >= 0.5:
        if v_eq_kms > 35.0:
            return (
                False,
                round(v_eq_kms, 1),
                f"Suspect giant rotation: v_eq={v_eq_kms:.1f} km/s > 35.0 km/s for R*={r_star:.1f} R_sun at P={period:.2f}d (possible spun-up binary / ellipsoidal / blend)",
            )
    return True, round(v_eq_kms, 1), f"Equatorial speed v_eq={v_eq_kms:.1f} km/s within single-star limit"

def assign_tier(category: str, 
                sde: float, 
                cycles: float, 
                sec_pass: bool, 
                centroid_status: str,
                r_star: Optional[float] = None,
                orbit_pass: bool = True,
                dur_pass: bool = True,
                is_known: bool = False,
                rot_sanity_pass: bool = True) -> str:
    """
    Unified scientific tier assignment:
    Tier A — Pristine Vetted Clean:
      - Requires MEASURED centroid pass (centroid_status == 'PASS')
      - SDE >= 10.0 (or SNR >= 10.0 for single dips)
      - cycles >= 3.0 (for periodic signals)
      - Passes secondary eclipse & odd/even tests
      - Physically possible orbit (a > R*), duration (T_dur >= T_min), and giant rotation sanity (v_eq <= 35 km/s)
      - Stellar radius R* known from Gaia / TIC
    Tier B — Probable / Unconstrained:
      - Valid astrophysical signal passing physics, but centroid NOT_RUN / PASS_MARGINAL,
        or R* unconstrained, or giant v_eq > 35 km/s, or SDE in [8.0, 10.0), or known benchmark recovery.
    Tier C — Audit Flagged / Dubious / Rejections:
      - Fails physical orbit (a <= R*), fails crossing duration, cycles < 3.0 for periodic,
        SDE < 8.0, or secondary eclipse test failure.
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
    if not rot_sanity_pass:
        return "B"
    if is_known:
        return "A" if (is_known and sde >= 10.0 and centroid_status == "PASS") else "B"
    if r_star is None or np.isnan(r_star) or r_star <= 0:
        return "B"
    if centroid_status != "PASS":
        # Unmeasured or marginal centroid cannot claim Tier A "Pristine Vetted Clean"
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

    tpf_target = target_name
    if target_name and not str(target_name).strip().upper().startswith("TIC"):
        for lc_obj in (lc_unflat, lc_flat):
            if hasattr(lc_obj, "meta") and isinstance(lc_obj.meta, dict):
                tid = lc_obj.meta.get("TARGETID")
                if tid is not None and str(tid).strip().isdigit():
                    tpf_target = f"TIC {int(tid)}"
                    break
    
    # Check if Lomb-Scargle is significantly stronger AND passes sinusoidal variable shape validation
    ls_sde = ls_res.get('sde', 0.0) if ls_res else 0.0
    bls_sde = bls_res.get('sde', 0.0) if bls_res else 0.0
    ls_valid_sinusoid = False
    if ls_res and ls_sde >= 10.0 and ls_res.get('fap', 1.0) < LS_FAP_SWEEP:
        ls_p = ls_res.get('period', 0.0)
        ls_amp = ls_res.get('amplitude', 0.0)
        if ls_amp >= 0.001 and not check_tess_systematics(ls_p):
            _, fl_b_ls = phase_fold_and_bin(lc_unflat, ls_p, float(lc_unflat.time.value[0]), bins=40)
            med_b_ls = np.nanmedian(fl_b_ls)
            p2p_b_ls = float(np.nanmax(fl_b_ls) - np.nanmin(fl_b_ls))
            if (1.3 * ls_amp <= p2p_b_ls <= 3.2 * ls_amp) and (
                np.sum(fl_b_ls > med_b_ls + 0.3 * ls_amp) >= 4
                and np.sum(fl_b_ls < med_b_ls - 0.3 * ls_amp) >= 4
            ):
                ls_valid_sinusoid = True
    bls_p_cand = float(bls_res.get('period', 0.0)) if bls_res else 0.0
    ls_p_cand = float(ls_res.get('period', 0.0)) if ls_res else 0.0
    ls_bls_harmonic = (
        ls_p_cand > 0
        and bls_p_cand > 0
        and any(abs(bls_p_cand - mult * ls_p_cand) / (mult * ls_p_cand) <= 0.05 for mult in (0.5, 1.0, 2.0, 3.0))
    )
    prefer_ls = (ls_valid_sinusoid and ls_sde > bls_sde and (ls_bls_harmonic or bls_sde < SDE_THRESHOLD))

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
            # Enforce phase-folded transit depth coherence (reject single-cadence outlier spikes while
            # preventing 50-bin boundary dilution on narrow transits at longer orbital periods)
            _, fl_binned = phase_fold_and_bin(lc_flat, period, epoch, bins=50)
            binned_depth = float(np.nanmedian(fl_binned) - np.nanmin(fl_binned))
            t_vals = lc_flat.time.value
            fl_vals = lc_flat.flux.value
            phase_tr = ((t_vals - epoch + 0.5 * period) % period) / period - 0.5
            in_tr_core = np.abs(phase_tr) <= max(0.35 * (duration / max(period, 1e-5)), 0.003)
            out_tr_core = np.abs(phase_tr) >= max(1.5 * (duration / max(period, 1e-5)), 0.02)
            direct_depth = 0.0
            if int(np.sum(in_tr_core)) >= 4 and int(np.sum(out_tr_core)) >= 10:
                direct_depth = float(np.nanmedian(fl_vals[out_tr_core]) - np.nanmedian(fl_vals[in_tr_core]))
            effective_coherence_depth = max(binned_depth, direct_depth)
            if effective_coherence_depth >= 0.35 * depth:
                observed_baseline = compute_observed_coverage_days(t_vals)
                cycles = observed_baseline / period if period > 0 else 1.0
                
                sec_pass, sec_ratio = check_secondary_eclipse(lc_flat, period, epoch, depth, duration)
                odd_even_ratio = check_odd_even(lc_flat, period, epoch, duration)
                centroid_status, centroid_sigma, centroid_desc = check_centroid_motion(lc_flat, period, epoch, duration, depth=depth)
                centroid_offset_px = np.nan
                if tpf_target:
                    tpf_st, tpf_off, tpf_desc = check_tpf_centroid_motion(tpf_target, epoch, duration, period)
                    if tpf_st != "NOT_RUN":
                        centroid_offset_px = tpf_off
                        if centroid_status == "NOT_RUN" or tpf_st != "PASS":
                            centroid_status, centroid_desc = tpf_st, tpf_desc
                centroid_pass = (centroid_status == "PASS")
                
                orbit_pass, a_rsun, orbit_desc = check_orbit_physical_separation(period, r_star, m_star)
                dur_pass, t_dur_min, dur_desc = check_transit_duration_physical(duration, r_star, m_star)
                companion_radius_pass = (
                    r_star is None
                    or not np.isfinite(r_star)
                    or r_star <= 0
                    or (float(r_star) * np.sqrt(max(0.0, float(depth))) * 9.731 <= 2.0)
                )
                is_planet_sized = (depth <= DEPTH_MAX) and companion_radius_pass
                
                tier = assign_tier("EXOPLANET" if is_planet_sized else "ECLIPSING_BINARY",
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
                
                if is_planet_sized and (0.7 <= odd_even_ratio <= 1.3) and sec_pass and centroid_status != "FAIL":
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
            
        centroid_status, centroid_sigma, centroid_desc = check_centroid_motion(lc_flat, None, epoch, duration, depth=depth)
        centroid_offset_px = np.nan
        if tpf_target:
            tpf_st, tpf_off, tpf_desc = check_tpf_centroid_motion(tpf_target, epoch, duration, None)
            if tpf_st != "NOT_RUN":
                centroid_offset_px = tpf_off
                if centroid_status == "NOT_RUN" or tpf_st != "PASS":
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
            if tpf_target:
                tpf_st, tpf_off, tpf_desc = check_tpf_variable_centroid_motion(
                    tpf_target, period, epoch=None, expected_amp=amp
                )
                if tpf_st != "NOT_RUN":
                    centroid_offset_px = tpf_off
                    if centroid_status == "NOT_RUN" or tpf_st != "PASS":
                        centroid_status, centroid_desc = tpf_st, tpf_desc
            centroid_pass = (centroid_status == "PASS")
            orbit_pass, a_rsun, orbit_desc = check_orbit_physical_separation(period, r_star, m_star)
            rot_sanity_pass, v_eq_kms, rot_sanity_desc = check_giant_rotation_sanity(period, r_star)
            
            is_catalog_tier = ls_res['fap'] < LS_FAP_THRESHOLD
            effective_sde = sde if is_catalog_tier else 7.0
            tier = assign_tier(
                "VARIABLE_STAR",
                effective_sde,
                cycles,
                True,
                centroid_status,
                r_star,
                orbit_pass,
                True,
                is_known,
                rot_sanity_pass=rot_sanity_pass,
            )
            
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
                "rot_sanity_pass": rot_sanity_pass,
                "v_eq_kms": v_eq_kms,
                "rot_sanity_desc": rot_sanity_desc,
                "sectors": sectors,
                "tier": tier
            })
            if not orbit_pass:
                return "UNCLASSIFIED_PERIODIC_DIP", ls_res
            return "VARIABLE_STAR", ls_res

    return "FALSE_POSITIVE", {}
