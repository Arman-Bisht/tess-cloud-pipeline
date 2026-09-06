import numpy as np
from astropy.timeseries import LombScargle
from typing import Dict, Any, Optional, List
import lightkurve as lk
from config import LS_MIN_FREQ, LS_MAX_FREQ

def detect_harmonics(ls: LombScargle, base_freq: float, power_grid: np.ndarray, freq_grid: np.ndarray) -> List[float]:
    """
    Checks if prominent power exists at 2*f and 3*f harmonics.
    """
    harmonics = []
    max_power = np.max(power_grid)
    for mult in [2.0, 3.0]:
        h_freq = base_freq * mult
        if h_freq <= freq_grid[-1]:
            idx = np.argmin(np.abs(freq_grid - h_freq))
            # If power at harmonic is at least 15% of peak power
            if power_grid[idx] > 0.15 * max_power:
                harmonics.append(round(mult, 1))
    return harmonics

def run_lomb_scargle(lc: lk.LightCurve) -> Optional[Dict[str, Any]]:
    """
    Runs Lomb-Scargle periodogram on unflattened data to detect stellar pulsations,
    rotational modulations, and eclipsing binaries.
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
        freqs = np.linspace(LS_MIN_FREQ, LS_MAX_FREQ, 15000)
        power = ls.power(freqs)
        
        best_idx = np.argmax(power)
        best_freq = freqs[best_idx]
        best_period = 1.0 / best_freq
        best_power = power[best_idx]
        
        # Calculate SDE for Lomb-Scargle
        mean_power = np.mean(power)
        std_power = np.std(power)
        ls_sde = (best_power - mean_power) / std_power if std_power > 0 else 0.0
        
        # False Alarm Probability (Baluev method)
        try:
            fap = float(ls.false_alarm_probability(best_power, method='baluev'))
        except Exception:
            fap = float(ls.false_alarm_probability(best_power))
            
        # Check harmonics (2f, 3f)
        harmonics = detect_harmonics(ls, best_freq, power, freqs)
        
        # Amplitude estimation (peak-to-peak semi-amplitude)
        model_t = np.linspace(0, best_period, 100)
        model_y = ls.model(model_t, best_freq)
        amplitude = float(np.ptp(model_y) / 2.0)
        
        # Approximate depth for EBs (peak-to-trough drop)
        depth = float(np.ptp(model_y) / np.nanmedian(y)) if np.nanmedian(y) > 0 else amplitude
        
        return {
            "period": float(best_period),
            "frequency": float(best_freq),
            "fap": float(fap),
            "amplitude": float(amplitude),
            "depth": float(depth),
            "power": float(best_power),
            "sde": float(ls_sde),
            "harmonics": harmonics,
            "ls_model": ls,
            "frequency_grid": freqs,
            "power_grid": power,
            "trend_method": "Unflattened Normalized Flux (Stream 2)"
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Lomb-Scargle error: {e}")
        return None
