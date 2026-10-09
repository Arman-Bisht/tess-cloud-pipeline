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
        # Use uncertainties if available and finite, else estimate from scatter
        if hasattr(lc, 'flux_err') and lc.flux_err is not None:
            dy = np.array(lc.flux_err.value, dtype=float)
            if not np.all(np.isfinite(dy)) or np.all(dy <= 0):
                dy = np.full_like(y, np.nanstd(y) if np.nanstd(y) > 0 else 0.001)
        else:
            dy = np.full_like(y, np.nanstd(y) if np.nanstd(y) > 0 else 0.001)
        
        # Remove NaNs again just in case
        mask = np.isfinite(y) & np.isfinite(t) & np.isfinite(dy)
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
        min_p = max(BLS_MIN_PERIOD, 0.5)
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
        valid_mask = np.isfinite(power)
        if not np.any(valid_mask):
            return None
        valid_indices = np.where(valid_mask)[0]
        best_valid_idx = np.argmax(power[valid_mask])
        max_power_idx = valid_indices[best_valid_idx]
        
        # Compute SDE strictly over finite power values
        mean_power = float(np.mean(power[valid_mask]))
        std_power = float(np.std(power[valid_mask]))
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
            fine_power_arr = fine_results.power
            fine_mask = np.isfinite(fine_power_arr)
            if np.any(fine_mask):
                fine_valid_idx = np.where(fine_mask)[0]
                fine_best_idx = fine_valid_idx[np.argmax(fine_power_arr[fine_mask])]
                best_period = float(fine_results.period[fine_best_idx])
                best_epoch = float(fine_results.transit_time[fine_best_idx])
                best_depth = float(fine_results.depth[fine_best_idx])
                best_duration = float(fine_results.duration[fine_best_idx])
                fine_power = float(fine_results.power[fine_best_idx])
            else:
                raise ValueError("No finite fine power")
        except Exception:
            best_period = coarse_period
            best_epoch = float(results.transit_time[max_power_idx])
            best_depth = float(results.depth[max_power_idx])
            best_duration = coarse_dur
            fine_power = float(power[max_power_idx])
            fine_results = results
        
        # Estimate period uncertainty from FWHM of the fine period peak
        used_periods = fine_periods if fine_results is not results else periods
        half_power = mean_power + 0.5 * (fine_power - mean_power)
        peak_indices = np.where(np.isfinite(fine_results.power) & (fine_results.power >= half_power))[0]
        if len(peak_indices) > 1:
            period_err = float(abs(used_periods[peak_indices[-1]] - used_periods[peak_indices[0]]) / 2.355)
        else:
            period_err = float(abs(used_periods[1] - used_periods[0])) if len(used_periods) > 1 else 0.001
        
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
