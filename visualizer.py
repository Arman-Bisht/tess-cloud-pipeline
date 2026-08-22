import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import lightkurve as lk
from typing import Dict, Any, Optional
from pathlib import Path
from config import DISCOVERIES_DIR

def save_diagnostic_plot(tic_id: str, 
                         category: str, 
                         lc_flat: lk.LightCurve, 
                         lc_unflat: lk.LightCurve, 
                         bls_res: Optional[Dict[str, Any]], 
                         ls_res: Optional[Dict[str, Any]]) -> str:
    fig = plt.figure(figsize=(15, 12))
    
    # Grid spec
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1])
    
    # Top Panel: Full stitched light curve
    ax_top = fig.add_subplot(gs[0, :])
    if category in ["CANDIDATE_EXOPLANET", "ECLIPSING_BINARY"] and bls_res:
        ax_top.plot(lc_flat.time.value, lc_flat.flux.value, '.k', markersize=2, alpha=0.5)
        ax_top.set_title(f"Flattened Light Curve - {tic_id}")
    else:
        ax_top.plot(lc_unflat.time.value, lc_unflat.flux.value, '.k', markersize=2, alpha=0.5)
        ax_top.set_title(f"Unflattened Light Curve - {tic_id}")
    ax_top.set_xlabel("Time (BJD)")
    ax_top.set_ylabel("Normalized Flux")
    
    if ("EXOPLANET" in category or "ECLIPSING_BINARY" in category) and bls_res:
        # Middle Left: BLS Periodogram
        ax_ml = fig.add_subplot(gs[1, 0])
        bls_results = bls_res['results']
        ax_ml.plot(bls_results.period, bls_results.power, 'k-')
        ax_ml.axvline(bls_res['period'], color='r', linestyle='--', alpha=0.5)
        ax_ml.set_title(f"BLS Periodogram (SDE = {bls_res['sde']:.2f})")
        ax_ml.set_xlabel("Period (days)")
        ax_ml.set_ylabel("Power")
        
        # Middle Right: Phase Folded
        ax_mr = fig.add_subplot(gs[1, 1])
        folded = lc_flat.fold(period=bls_res['period'], epoch_time=bls_res['epoch'])
        ax_mr.plot(folded.time.value, folded.flux.value, '.k', markersize=2, alpha=0.3)
        try:
            binned = folded.bin(time_bin_size=bls_res['period']/100)
            ax_mr.plot(binned.time.value, binned.flux.value, 'ro', markersize=4)
        except:
            pass
        ax_mr.set_title(f"Phase Folded (P={bls_res['period']:.4f} d)")
        ax_mr.set_xlabel("Phase")
        
        # Bottom Left: Odd vs Even
        ax_bl = fig.add_subplot(gs[2, 0])
        folded_2x = lc_flat.fold(period=2*bls_res['period'], epoch_time=bls_res['epoch'])
        ax_bl.plot(folded_2x.time.value, folded_2x.flux.value, '.k', markersize=2, alpha=0.3)
        ax_bl.axvline(0, color='r', alpha=0.3)
        ax_bl.axvline(-0.5, color='b', alpha=0.3)
        ax_bl.axvline(0.5, color='b', alpha=0.3)
        ax_bl.set_title("Odd/Even Transit Check")
        ax_bl.set_xlim(-0.75, 0.75)
        
        # Bottom Right: Secondary Eclipse Window
        ax_br = fig.add_subplot(gs[2, 1])
        ax_br.plot(folded.time.value, folded.flux.value, '.k', markersize=2, alpha=0.5)
        ax_br.set_xlim(0.4, 0.6)
        ax_br.set_ylim(np.nanmedian(folded.flux.value) - 2*bls_res['depth'], np.nanmedian(folded.flux.value) + bls_res['depth'])
        ax_br.set_title("Secondary Eclipse Check (Phase ~0.5)")
        
    elif "VARIABLE_STAR" in category and ls_res:
        # Middle Left: LS Periodogram
        ax_ml = fig.add_subplot(gs[1, 0])
        ax_ml.plot(ls_res['frequency_grid'], ls_res['power_grid'], 'k-')
        ax_ml.axvline(ls_res['frequency'], color='r', linestyle='--', alpha=0.5)
        ax_ml.set_title(f"Lomb-Scargle (FAP = {ls_res['fap']:.1e})")
        ax_ml.set_xlabel("Frequency (c/d)")
        ax_ml.set_ylabel("Power")
        
        # Middle Right: Phase Folded
        ax_mr = fig.add_subplot(gs[1, 1])
        folded = lc_unflat.fold(period=ls_res['period'])
        ax_mr.plot(folded.time.value, folded.flux.value, '.k', markersize=2, alpha=0.3)
        ax_mr.set_title(f"Phase Folded (P={ls_res['period']:.4f} d)")
        
        # Bottom Left: Sinusoidal fit
        ax_bl = fig.add_subplot(gs[2, 0])
        ax_bl.plot(folded.time.value, folded.flux.value, '.k', markersize=2, alpha=0.3)
        model_t = np.linspace(-0.5, 0.5, 100) * ls_res['period']
        model_y = ls_res['ls_model'].model(model_t + lc_unflat.time.value[0], ls_res['frequency'])
        ax_bl.plot(np.linspace(-0.5, 0.5, 100), model_y, 'r-', lw=2)
        ax_bl.set_title("Sinusoidal Fit")
        
        # Bottom Right: Info
        ax_br = fig.add_subplot(gs[2, 1])
        ax_br.axis('off')
        info_text = f"Amplitude: {ls_res['amplitude']:.5f}\nFreq: {ls_res['frequency']:.4f} c/d"
        ax_br.text(0.5, 0.5, info_text, fontsize=14, ha='center', va='center')
        
    plt.tight_layout()
    filename = DISCOVERIES_DIR / f"{tic_id}_{category}.png"
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    return str(filename)
