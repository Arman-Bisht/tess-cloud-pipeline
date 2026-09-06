import numpy as np
from scipy.optimize import curve_fit
from scipy.stats import skew
from typing import Dict, Any, Optional
import lightkurve as lk
import logging

logger = logging.getLogger(__name__)

def paczynski_model(t: np.ndarray, t0: float, u0: float, tE: float, F0: float = 1.0) -> np.ndarray:
    """
    Standard Paczynski (1986) point-source point-lens (PSPL) magnification model.
    t0: peak amplification time (days)
    u0: impact parameter in units of Einstein radii (u0 > 0)
    tE: Einstein radius crossing time (days)
    F0: baseline unmagnified flux
    """
    # Prevent division by zero and excessive numbers
    tau = (t - t0) / np.maximum(tE, 1e-4)
    u = np.sqrt(u0**2 + tau**2)
    u = np.maximum(u, 1e-5)
    
    A = (u**2 + 2.0) / (u * np.sqrt(u**2 + 4.0))
    return F0 * A

def run_microlensing(lc_unflat: lk.LightCurve) -> Optional[Dict[str, Any]]:
    """
    Searches for smooth, symmetrical, multi-day gravitational microlensing events.
    Fits Paczynski PSPL curve and performs flare/asymmetry vetoes.
    """
    try:
        t = lc_unflat.time.value
        y = lc_unflat.flux.value
        mask = np.isfinite(t) & np.isfinite(y)
        t, y = t[mask], y[mask]
        
        if len(t) < 500:
            return None
            
        med_flux = np.nanmedian(y)
        # Robust standard deviation via Median Absolute Deviation (MAD)
        # Prevents the large microlensing peak from inflating the noise estimate
        std_flux = float(1.4826 * np.nanmedian(np.abs(y - med_flux)))
        
        # Look for significant positive excursions (> 5 sigma above baseline)
        pos_excursion = y - med_flux
        max_idx = np.argmax(pos_excursion)
        peak_amp = pos_excursion[max_idx]
        
        # Require peak amplification of at least 5% (F/F0 >= 1.05) and > 4*std
        if peak_amp < max(0.05, 4.0 * std_flux):
            return None
            
        candidate_t0 = t[max_idx]
        
        # Zoom in around candidate peak (+/- 15 days or lightcurve extent)
        window = 15.0
        zoom_mask = np.abs(t - candidate_t0) <= window
        t_zoom = t[zoom_mask]
        y_zoom = y[zoom_mask]
        
        if len(t_zoom) < 50:
            return None
            
        # Veto 1: Check asymmetry before fitting
        # Fast rise / slow decay indicates stellar flare, NOT symmetric microlensing
        left_mask = (t_zoom < candidate_t0) & (t_zoom >= candidate_t0 - 5.0)
        right_mask = (t_zoom > candidate_t0) & (t_zoom <= candidate_t0 + 5.0)
        
        if np.sum(left_mask) > 10 and np.sum(right_mask) > 10:
            left_mean_rise = np.mean(y_zoom[left_mask]) - med_flux
            right_mean_decay = np.mean(y_zoom[right_mask]) - med_flux
            
            # If decay is 3x longer/stronger than rise (classic flare profile)
            if right_mean_decay > 3.0 * max(1e-4, left_mean_rise):
                logger.debug(f"Candidate at t0={candidate_t0:.2f} rejected as asymmetric flare.")
                return None
                
        # Initial guesses for Paczynski: t0, u0, tE, F0
        # A_max = (u0^2+2)/(u0*sqrt(u0^2+4)) ~ 1/u0 for small u0
        f_max = (med_flux + peak_amp) / med_flux
        approx_u0 = min(1.0, max(0.01, 1.0 / f_max))
        p0 = [candidate_t0, approx_u0, 3.0, med_flux]
        
        # Lock tE to physically plausible bounds for TESS sectors
        # A single TESS sector is ~27 days; a tE > 50 days cannot be distinguished from a trend
        total_time_span = float(t_zoom[-1] - t_zoom[0])
        max_phys_tE = min(50.0, max(5.0, total_time_span * 1.2))
        
        bounds = (
            [candidate_t0 - 2.0, 0.001, 0.5, med_flux - 0.05],
            [candidate_t0 + 2.0, 1.5, max_phys_tE, med_flux + 0.05]
        )
        
        try:
            popt, pcov = curve_fit(
                paczynski_model, 
                t_zoom, 
                y_zoom, 
                p0=p0, 
                bounds=bounds, 
                maxfev=3000
            )
            fit_t0, fit_u0, fit_tE, fit_F0 = popt
            
            # Discard if fit pegged against the boundary (unconstrained fit on noisy flat data)
            if fit_tE >= (max_phys_tE - 0.5) or fit_tE <= 0.51:
                logger.debug(f"Candidate at t0={candidate_t0:.2f} pegged at tE boundary ({fit_tE:.2f} d). Discarded.")
                return None
                
            # Discard based on Einstein crossing time tE criteria:
            if fit_tE < 0.5 or fit_tE > 50.0:
                return None
                
            model_flux = paczynski_model(t_zoom, *popt)
            residuals = y_zoom - model_flux
            chi2 = np.sum(residuals**2) / max(1, len(y_zoom) - 4)
            
            null_chi2 = np.sum((y_zoom - fit_F0)**2) / max(1, len(y_zoom) - 1)
            delta_chi2 = null_chi2 - chi2
            
            # Calculate symmetry ratio of residuals
            peak_mask = np.abs(t_zoom - fit_t0) <= (fit_tE * 0.5)
            if np.sum(peak_mask) < 15 or delta_chi2 <= 0:
                return None
                
            max_magnification = (fit_u0**2 + 2.0) / (fit_u0 * np.sqrt(fit_u0**2 + 4.0))
            sde = (max_magnification - 1.0) / (std_flux / med_flux) if std_flux > 0 else 10.0
            
            # Check residual skewness (flares leave strong skewed residuals)
            res_skew = abs(float(skew(residuals[peak_mask])))
            if res_skew > 1.5:
                # Discard asymmetric/flare residuals
                return None
                
            return {
                "epoch": float(fit_t0),
                "u0": float(fit_u0),
                "tE": float(fit_tE),
                "baseline_flux": float(fit_F0),
                "amplitude": float(max_magnification - 1.0),
                "depth": float(max_magnification - 1.0),
                "duration": float(fit_tE * 2.0),
                "sde": float(sde),
                "period": None, # Non-periodic
                "t_zoom": t_zoom,
                "y_zoom": y_zoom,
                "model_flux": model_flux,
                "chi2": float(chi2)
            }
        except Exception as e:
            logger.debug(f"Paczynski curve fit failed: {e}")
            return None
            
        return None
    except Exception as e:
        logger.error(f"Microlensing engine error: {e}")
        return None
