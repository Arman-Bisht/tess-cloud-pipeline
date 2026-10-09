import numpy as np
from astropy.timeseries import BoxLeastSquares
from typing import Dict, Any, Optional
import lightkurve as lk
from config import BLS_MIN_PERIOD, BLS_MAX_PERIOD

def run_bls(lc: lk.LightCurve) -> Optional[Dict[str, Any]]:
    """
    Runs Box Least Squares on the lightcurve to find transit signals.
    Computes Signal Detection Efficiency (SDE).
    """
    try:
        t = lc.time.value
        y = lc.flux.value
        # Use uncertainties if available, else ones
        dy = lc.flux_err.value if lc.flux_err is not None else np.ones_like(y)
        
        # Remove NaNs again just in case
        mask = np.isfinite(y) & np.isfinite(t)
        t, y, dy = t[mask], y[mask], dy[mask]
        
        if len(t) < 100:
            return None
            
        model = BoxLeastSquares(t, y, dy=dy)
        
        # Create duration grid (e.g. 0.02 to 0.25 days, which is ~30 mins to 6 hours)
        durations = np.linspace(0.02, 0.25, 20)
        
        # Evaluate BLS using an oversampled frequency-uniform period grid
        try:
            periods = model.autoperiod(durations, minimum_period=BLS_MIN_PERIOD, maximum_period=min(BLS_MAX_PERIOD, 30.0), frequency_factor=4.0)
        except Exception:
            periods = np.linspace(BLS_MIN_PERIOD, min(BLS_MAX_PERIOD, 30.0), 10000)
            
        results = model.power(period=periods, duration=durations)
        
        power = results.power
        max_power_idx = np.argmax(power)
        
        # Compute SDE
        mean_power = float(np.mean(power))
        std_power = float(np.std(power))
        sde = (float(power[max_power_idx]) - mean_power) / std_power if std_power > 0 else 0.0
        
        coarse_period = float(results.period[max_power_idx])
        coarse_dur = float(results.duration[max_power_idx])
        
        # Local fine-grid zoom (+/- 1.5 frequency bins around peak) to eliminate grid quantization
        df_local = 1.0 / (t[-1] - t[0]) if (t[-1] - t[0]) > 0 else 0.05
        f_coarse = 1.0 / coarse_period
        fine_freqs = np.linspace(max(1.0 / BLS_MAX_PERIOD, f_coarse - 1.5 * df_local), f_coarse + 1.5 * df_local, 150)
        fine_periods = 1.0 / fine_freqs
        fine_results = model.power(period=fine_periods, duration=coarse_dur)
        
        fine_max_idx = np.argmax(fine_results.power)
        best_period = float(fine_results.period[fine_max_idx])
        best_epoch = float(fine_results.transit_time[fine_max_idx])
        best_depth = float(fine_results.depth[fine_max_idx])
        best_duration = float(fine_results.duration[fine_max_idx])
        fine_power = float(fine_results.power[fine_max_idx])
        
        # Estimate period uncertainty from FWHM of the fine period peak
        half_power = mean_power + 0.5 * (fine_power - mean_power)
        peak_indices = np.where(fine_results.power >= half_power)[0]
        if len(peak_indices) > 1:
            period_err = float(abs(fine_periods[peak_indices[-1]] - fine_periods[peak_indices[0]]) / 2.355)
        else:
            period_err = float(abs(fine_periods[1] - fine_periods[0]))
        
        return {
            "period": best_period,
            "period_err": period_err,
            "epoch": best_epoch,
            "depth": best_depth,
            "duration": best_duration,
            "power": fine_power,
            "sde": sde,
            "model": model,
            "results": results
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"BLS error: {e}")
        return None
