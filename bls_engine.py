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
        
        # Evaluate BLS using a strictly bounded period grid to guarantee <1 second math time
        periods = np.linspace(BLS_MIN_PERIOD, min(BLS_MAX_PERIOD, 30.0), 10000)
        results = model.power(period=periods, duration=durations)
        
        power = results.power
        max_power_idx = np.argmax(power)
        
        # Compute SDE
        mean_power = np.mean(power)
        std_power = np.std(power)
        sde = (power[max_power_idx] - mean_power) / std_power if std_power > 0 else 0
        
        best_period = results.period[max_power_idx]
        best_epoch = results.transit_time[max_power_idx]
        best_depth = results.depth[max_power_idx]
        best_duration = results.duration[max_power_idx]
        
        return {
            "period": best_period,
            "epoch": best_epoch,
            "depth": best_depth,
            "duration": best_duration,
            "power": power[max_power_idx],
            "sde": sde,
            "model": model,
            "results": results
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"BLS error: {e}")
        return None
