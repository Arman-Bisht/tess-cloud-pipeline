import numpy as np
from scipy.optimize import curve_fit
from scipy.ndimage import uniform_filter1d
from typing import Dict, Any, Optional
import lightkurve as lk
import logging

logger = logging.getLogger(__name__)

def trapezoid_transit_model(t: np.ndarray, t0: float, depth: float, duration: float, ingress_ratio: float, baseline: float = 1.0) -> np.ndarray:
    """
    Trapezoidal transit approximation to Mandel-Agol.
    t0: transit center time (BJD)
    depth: fractional depth (e.g. 0.01 for 1%)
    duration: full transit duration (days)
    ingress_ratio: fraction of duration spent in ingress/egress (0.05 to 0.45)
    baseline: out-of-transit flux
    """
    flux = np.full_like(t, baseline, dtype=float)
    t_in = ingress_ratio * duration
    half_dur = duration / 2.0
    dt = np.abs(t - t0)
    
    # In transit bottom
    bottom_mask = dt <= (half_dur - t_in)
    flux[bottom_mask] = baseline - depth
    
    # Ingress / Egress slopes
    slope_mask = (dt > (half_dur - t_in)) & (dt < half_dur)
    if np.any(slope_mask) and t_in > 0:
        frac = (half_dur - dt[slope_mask]) / t_in
        flux[slope_mask] = baseline - depth * np.clip(frac, 0.0, 1.0)
        
    return flux

def limb_darkened_transit_model(t: np.ndarray, t0: float, depth: float, duration: float, u1: float = 0.3, u2: float = 0.3, baseline: float = 1.0) -> np.ndarray:
    """
    Quadratic limb-darkened geometric transit profile approximation.
    Produces smooth ingress and egress shoulders parameterized by limb-darkening coefficients (u1, u2).
    """
    z = np.abs(t - t0) / np.maximum(duration / 2.0, 1e-4)
    flux = np.full_like(t, baseline, dtype=float)
    in_transit = z < 1.0
    if np.any(in_transit):
        mu = np.sqrt(np.clip(1.0 - z[in_transit]**2, 0.0, 1.0))
        ld_profile = 1.0 - u1 * (1.0 - mu) - u2 * (1.0 - mu)**2
        ld_norm = max(0.1, 1.0 - u1 - u2)
        scale = ld_profile / ld_norm
        flux[in_transit] = baseline - depth * np.clip(scale, 0.0, 1.2)
    return flux

def run_single_transit(lc_wide_flat: lk.LightCurve) -> Optional[Dict[str, Any]]:
    """
    Detects solitary transit events (planets with orbits > 27 days).
    Pass 1: Rolling minimum threshold search on wide-flattened lightcurve.
    Pass 2: Mandel-Agol limb-darkened transit fit, with automatic fallback to Trapezoid if divergence occurs.
    """
    try:
        t = lc_wide_flat.time.value
        y = lc_wide_flat.flux.value
        mask = np.isfinite(t) & np.isfinite(y)
        t, y = t[mask], y[mask]
        
        if len(t) < 500:
            return None
            
        std_flux = np.nanstd(y)
        med_flux = np.nanmedian(y)
        
        # Pass 1: Rolling window search for deep, localized dips using uniform_filter1d
        window_size = 15
        rolling_mean = uniform_filter1d(y, size=window_size, mode='reflect')
        dip_depths = med_flux - rolling_mean
        
        # Exclude the first and last 0.4 days from overall time series, as well as all inter-sector / downlink gaps (> 0.5 d)
        valid_time_mask = (t >= t[0] + 0.4) & (t <= t[-1] - 0.4)
        dt_gaps = np.diff(t)
        gap_indices = np.where(dt_gaps > 0.5)[0]
        for g_idx in gap_indices:
            gap_start = t[g_idx]
            gap_end = t[g_idx + 1]
            valid_time_mask &= ~((t >= gap_start - 0.4) & (t <= gap_end + 0.4))

        if not np.any(valid_time_mask):
            return None
            
        dip_depths_valid = np.where(valid_time_mask, dip_depths, 0.0)
        min_idx = np.argmax(dip_depths_valid)
        max_dip = dip_depths_valid[min_idx]
        
        # Threshold: at least 4 sigma dip
        if max_dip < 4.0 * std_flux:
            return None
            
        candidate_t0 = t[min_idx]
        
        # Extract transit neighborhood (+/- 0.8 days around candidate_t0)
        zoom_mask = np.abs(t - candidate_t0) <= 0.8
        t_zoom = t[zoom_mask]
        y_zoom = y[zoom_mask]
        
        # Require sufficient points and verified baseline both before and after candidate transit
        if len(t_zoom) < 30:
            return None
            
        pre_pts = np.sum(t_zoom < candidate_t0 - 0.1)
        post_pts = np.sum(t_zoom > candidate_t0 + 0.1)
        if pre_pts < 10 or post_pts < 10:
            return None
            
        # Pass 2: Fit Transit Model (Mandel-Agol first, fallback to Trapezoid)
        model_flux = None
        fit_t0 = candidate_t0
        fit_depth = float(max_dip)
        fit_duration = 0.15
        fit_ingress = 0.2
        fit_baseline = med_flux
        fit_method = "Trapezoid"
        fit_succeeded = False
        
        # 1. Attempt Mandel-Agol limb-darkened fit first
        try:
            ma_p0 = [candidate_t0, float(max_dip), 0.15, 0.3, 0.3, med_flux]
            ma_bounds = (
                [candidate_t0 - 0.2, 0.0005, 0.02, 0.0, 0.0, med_flux - 0.01],
                [candidate_t0 + 0.2, 0.50, 0.50, 0.8, 0.8, med_flux + 0.01]
            )
            popt_ma, _ = curve_fit(limb_darkened_transit_model, t_zoom, y_zoom, p0=ma_p0, bounds=ma_bounds, maxfev=1500)
            fit_t0, fit_depth, fit_duration, _, _, fit_baseline = popt_ma
            model_flux = limb_darkened_transit_model(t_zoom, *popt_ma)
            fit_method = "Limb-Darkened Geometric Fit"
            fit_succeeded = True
        except Exception as ma_err:
            logger.debug(f"Limb-darkened fit failed to converge ({ma_err}). Falling back to robust Trapezoid fit.")

        # 2. Fallback to Trapezoid fit if Mandel-Agol failed
        if not fit_succeeded:
            try:
                trap_p0 = [candidate_t0, float(max_dip), 0.15, 0.2, med_flux]
                trap_bounds = (
                    [candidate_t0 - 0.2, 0.0005, 0.02, 0.05, med_flux - 0.01],
                    [candidate_t0 + 0.2, 0.50, 0.50, 0.45, med_flux + 0.01]
                )
                popt_trap, _ = curve_fit(trapezoid_transit_model, t_zoom, y_zoom, p0=trap_p0, bounds=trap_bounds, maxfev=2000)
                fit_t0, fit_depth, fit_duration, fit_ingress, fit_baseline = popt_trap
                model_flux = trapezoid_transit_model(t_zoom, *popt_trap)
                fit_method = "Trapezoid (Fallback)"
                fit_succeeded = True
            except Exception as trap_err:
                logger.debug(f"Trapezoid fit also failed: {trap_err}")
                return None

        if not fit_succeeded or model_flux is None:
            return None
            
        residuals = y_zoom - model_flux
        chi2 = np.sum(residuals**2) / max(1, len(y_zoom) - 5)
        null_chi2 = np.sum((y_zoom - fit_baseline)**2) / max(1, len(y_zoom) - 1)
        delta_chi2 = null_chi2 - chi2
        
        # Transit SNR and in-transit fit fidelity check
        in_transit_mask = np.abs(t_zoom - fit_t0) <= (fit_duration / 2.0)
        n_in_transit = np.sum(in_transit_mask)
        if n_in_transit < 4:
            return None

        # Check out-of-transit baseline isolation and stability
        if np.any(~in_transit_mask):
            rms_out = float(np.sqrt(np.mean(residuals[~in_transit_mask]**2)))
            out_flux = y_zoom[~in_transit_mask]
            # Smooth out-of-transit flux over 5 cadences to test for coherent secondary dips rather than single-point noise
            out_smooth = uniform_filter1d(out_flux, size=min(5, len(out_flux))) if len(out_flux) >= 5 else out_flux
            out_min = float(np.nanmin(out_smooth))
            dip_threshold = max(0.5 * fit_depth, 3.5 * std_flux)
            if out_min < fit_baseline - dip_threshold:
                logger.debug(f"Rejected non-isolated single transit: out_min={out_min:.4f} < threshold={fit_baseline - dip_threshold:.4f}")
                return None
            noise_ceiling = min(3.0 * std_flux, 0.01)
            if rms_out > noise_ceiling:
                logger.debug(f"Rejected single transit due to unstable local baseline: rms_out={rms_out:.4f} > noise_ceiling={noise_ceiling:.4f}")
                return None
        else:
            rms_out = std_flux

        snr = float((fit_depth / std_flux) * np.sqrt(max(1, n_in_transit)))
        
        if snr >= 6.0 and delta_chi2 > 0:
            return {
                "epoch": float(fit_t0),
                "depth": float(fit_depth),
                "duration": float(fit_duration), # days
                "duration_hours": float(fit_duration * 24.0),
                "ingress_ratio": float(fit_ingress),
                "baseline": float(fit_baseline),
                "snr": float(snr),
                "sde": float(snr), # For single transits, significance metric is transit SNR (no periodogram SDE)
                "period": None,
                "fit_method": fit_method,
                "t_zoom": t_zoom,
                "y_zoom": y_zoom,
                "model_flux": model_flux
            }
            
        return None
    except Exception as e:
        logger.error(f"Single transit detection error: {e}")
        return None
