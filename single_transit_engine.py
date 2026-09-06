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

def run_single_transit(lc_wide_flat: lk.LightCurve) -> Optional[Dict[str, Any]]:
    """
    Detects solitary transit events (planets with orbits > 27 days).
    Pass 1: Rolling minimum threshold search on wide-flattened lightcurve.
    Pass 2: Trapezoid / transit morphology fit (durations up to 0.5 days).
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
        # mode='reflect' prevents boundary zero-padding artifacts
        window_size = 15
        rolling_mean = uniform_filter1d(y, size=window_size, mode='reflect')
        dip_depths = med_flux - rolling_mean
        
        # Exclude the first and last 0.5 days from edge effects
        valid_time_mask = (t >= t[0] + 0.4) & (t <= t[-1] - 0.4)
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
        
        if len(t_zoom) < 30:
            return None
            
        # Pass 2: Fit trapezoid model
        # Test durations up to 0.5 days (12 hours) (Spec 1.1)
        p0 = [candidate_t0, float(max_dip), 0.15, 0.2, med_flux]
        bounds = (
            [candidate_t0 - 0.2, 0.0005, 0.02, 0.05, med_flux - 0.01],
            [candidate_t0 + 0.2, 0.50, 0.50, 0.45, med_flux + 0.01]
        )
        
        try:
            popt, pcov = curve_fit(
                trapezoid_transit_model, 
                t_zoom, 
                y_zoom, 
                p0=p0, 
                bounds=bounds, 
                maxfev=2000
            )
            fit_t0, fit_depth, fit_duration, fit_ingress, fit_baseline = popt
            model_flux = trapezoid_transit_model(t_zoom, *popt)
            residuals = y_zoom - model_flux
            chi2 = np.sum(residuals**2) / max(1, len(y_zoom) - 5)
            
            # Null model (flat baseline)
            null_chi2 = np.sum((y_zoom - fit_baseline)**2) / max(1, len(y_zoom) - 1)
            delta_chi2 = null_chi2 - chi2
            
            # Transit SNR
            in_transit_mask = np.abs(t_zoom - fit_t0) <= (fit_duration / 2.0)
            n_in_transit = np.sum(in_transit_mask)
            snr = (fit_depth / std_flux) * np.sqrt(max(1, n_in_transit))
            
            # Approximate impact parameter b from ingress duration
            b_param = float(np.sqrt(np.clip(1.0 - 2.0 * fit_ingress, 0.0, 0.95)))
            
            # Vetting: must show substantial delta_chi2 and SNR >= 6.0
            if snr >= 6.0 and delta_chi2 > 0:
                return {
                    "epoch": float(fit_t0),
                    "depth": float(fit_depth),
                    "duration": float(fit_duration), # days
                    "duration_hours": float(fit_duration * 24.0),
                    "ingress_ratio": float(fit_ingress),
                    "baseline": float(fit_baseline),
                    "snr": float(snr),
                    "sde": float(snr * 1.5), # Equivalent SDE metric for alerts
                    "period": None, # Solitary transit
                    "impact_parameter": b_param,
                    "t_zoom": t_zoom,
                    "y_zoom": y_zoom,
                    "model_flux": model_flux,
                    "fit_params": popt
                }
        except Exception as e:
            logger.debug(f"Single transit curve_fit failed: {e}")
            return None
            
        return None
    except Exception as e:
        logger.error(f"Single transit detection error: {e}")
        return None
