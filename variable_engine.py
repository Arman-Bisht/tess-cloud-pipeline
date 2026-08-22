import numpy as np
from astropy.timeseries import LombScargle
from typing import Dict, Any, Optional
import lightkurve as lk
from config import LS_MIN_FREQ, LS_MAX_FREQ

def run_lomb_scargle(lc: lk.LightCurve) -> Optional[Dict[str, Any]]:
    """
    Runs Lomb-Scargle periodogram to find stellar pulsations and rotational modulations.
    """
    try:
        t = lc.time.value
        y = lc.flux.value
        dy = lc.flux_err.value if lc.flux_err is not None else np.ones_like(y)
        
        mask = np.isfinite(y) & np.isfinite(t)
        t, y, dy = t[mask], y[mask], dy[mask]
        
        if len(t) < 100:
            return None
            
        ls = LombScargle(t, y, dy)
        freqs = np.linspace(LS_MIN_FREQ, LS_MAX_FREQ, 10000)
        power = ls.power(freqs)
        frequency = freqs
        
        best_idx = np.argmax(power)
        best_freq = frequency[best_idx]
        best_period = 1.0 / best_freq
        best_power = power[best_idx]
        
        # False Alarm Probability (Baluev method is robust)
        try:
            fap = ls.false_alarm_probability(best_power, method='baluev')
        except:
            fap = ls.false_alarm_probability(best_power)
            
        # Amplitude estimation (peak-to-peak approximation or amplitude from model)
        model_t = np.linspace(0, best_period, 100)
        model_y = ls.model(model_t, best_freq)
        amplitude = np.ptp(model_y) / 2.0  # semi-amplitude
        
        return {
            "period": best_period,
            "frequency": best_freq,
            "fap": float(fap),
            "amplitude": float(amplitude),
            "power": float(best_power),
            "ls_model": ls,
            "frequency_grid": frequency,
            "power_grid": power
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Lomb-Scargle error: {e}")
        return None
