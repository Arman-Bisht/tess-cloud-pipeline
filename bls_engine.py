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
        min_duration = 0.02
        
        # Determine effective contiguous baseline to prevent multi-year gap explosion
        dt = np.diff(t)
        gap_indices = np.where(dt > 5.0)[0]
        if len(gap_indices) > 0:
            chunk_starts = np.insert(gap_indices + 1, 0, 0)
            chunk_ends = np.append(gap_indices, len(t) - 1)
            chunk_baselines = [float(t[end] - t[start]) for start, end in zip(chunk_starts, chunk_ends)]
            effective_baseline = max(max(chunk_baselines), 27.0)
        else:
            effective_baseline = float(t[-1] - t[0]) if (t[-1] - t[0]) > 0 else 27.0

        # Frequency spacing scaled to effective contiguous baseline
        min_p = max(BLS_MIN_PERIOD, 0.4)
        max_p = min(BLS_MAX_PERIOD, 30.0)
        df = min_duration / (effective_baseline ** 2)
        min_freq = 1.0 / max_p
        max_freq = 1.0 / min_p
        nf = int(np.round((max_freq - min_freq) / df)) + 1
        
        # Cap initial coarse grid to at most 30,000 trial periods (uniform in frequency)
        # to ensure fast sub-5s execution across any multi-sector/multi-year baseline
        MAX_BLS_GRID = 30000
        if nf > MAX_BLS_GRID:
            nf = MAX_BLS_GRID
        freqs = np.linspace(max_freq, min_freq, nf)
        periods = 1.0 / freqs
            
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
        
        # Astropy BLS strictly requires all periods to be > duration
        min_allowed_period = max(coarse_dur * 1.05, BLS_MIN_PERIOD)
        max_fine_freq = min(1.0 / min_allowed_period, f_coarse + 1.5 * df_local)
        min_fine_freq = max(1.0 / BLS_MAX_PERIOD, f_coarse - 1.5 * df_local)
        if min_fine_freq >= max_fine_freq:
            min_fine_freq = max(1.0 / BLS_MAX_PERIOD, 0.98 * f_coarse)
            max_fine_freq = min(1.0 / min_allowed_period, 1.02 * f_coarse)
            
        fine_freqs = np.linspace(min_fine_freq, max_fine_freq, 150)
        fine_periods = 1.0 / fine_freqs
        fine_periods = np.sort(fine_periods)
        
        try:
            fine_results = model.power(period=fine_periods, duration=coarse_dur)
            fine_max_idx = np.argmax(fine_results.power)
            best_period = float(fine_results.period[fine_max_idx])
            best_epoch = float(fine_results.transit_time[fine_max_idx])
            best_depth = float(fine_results.depth[fine_max_idx])
            best_duration = float(fine_results.duration[fine_max_idx])
            fine_power = float(fine_results.power[fine_max_idx])
        except Exception:
            best_period = coarse_period
            best_epoch = float(results.transit_time[max_power_idx])
            best_depth = float(results.depth[max_power_idx])
            best_duration = coarse_dur
            fine_power = float(power[max_power_idx])
            fine_results = results
        
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
