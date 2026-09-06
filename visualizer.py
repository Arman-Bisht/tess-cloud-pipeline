import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import lightkurve as lk
from typing import Dict, Any, Optional, List
from pathlib import Path
from config import DISCOVERIES_DIR

def save_diagnostic_plot(tic_id: str, 
                         category: str, 
                         lc_flat: lk.LightCurve, 
                         lc_unflat: lk.LightCurve, 
                         best_res: Dict[str, Any],
                         sectors: Optional[List[int]] = None) -> str:
    """
    Generates publication-quality 5-Panel Diagnostic Sheet meeting Section 5.2 specification:
    Panel 1: Raw / Unflattened LC
    Panel 2: Flattened LC
    Panel 3: Phased LC (two cycles side-by-side, phase 0-2) or Event Zoom
    Panel 4: Periodogram (BLS / Lomb-Scargle power with peak & SDE) or Model Fit
    Panel 5: Secondary Eclipse (Phase 0.5 zoom) or Odd/Even transit check
    
    Includes mandatory 4-corner text overlays:
    - Top-left: Star Name + TIC ID
    - Top-right: Period + SDE
    - Bottom-left: Transits / cycles observed
    - Bottom-right: TESS sectors used
    """
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 1.0, 1.0])
    
    period = best_res.get('period')
    sde = best_res.get('sde', 0.0)
    epoch = best_res.get('epoch')
    depth = best_res.get('depth', 0.0)
    duration = best_res.get('duration', 0.1)
    cycles = best_res.get('cycles', 1.0)
    sectors_str = ", ".join(map(str, sectors)) if sectors else "TESS"
    
    # Text overlay strings
    period_str = f"P = {period:.4f} d" if period is not None else "Single Event"
    sde_str = f"SDE = {sde:.1f}"
    cycles_str = f"Cycles: {cycles:.1f}" if cycles else "N/A"
    sec_str = f"Sectors: {sectors_str}"

    def add_corner_annotations(ax):
        # Adds the 4 mandatory overlays to panel
        ax.text(0.01, 0.95, f"{tic_id}", transform=ax.transAxes, fontsize=9,
                fontweight='bold', va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))
        ax.text(0.99, 0.95, f"{period_str} | {sde_str}", transform=ax.transAxes, fontsize=9,
                va='top', ha='right',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))
        ax.text(0.01, 0.05, cycles_str, transform=ax.transAxes, fontsize=8,
                va='bottom', ha='left',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))
        ax.text(0.99, 0.05, sec_str, transform=ax.transAxes, fontsize=8,
                va='bottom', ha='right',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))

    # ==========================================
    # Panel 1: Raw / Unflattened LC (Full width)
    # ==========================================
    ax1 = fig.add_subplot(gs[0, :])
    t_unflat = lc_unflat.time.value
    y_unflat = lc_unflat.flux.value
    mask1 = np.isfinite(t_unflat) & np.isfinite(y_unflat)
    ax1.plot(t_unflat[mask1], y_unflat[mask1], '.k', markersize=2, alpha=0.5)
    ax1.set_title(f"Panel 1: Raw / Unflattened Light Curve — {tic_id}", fontsize=12, fontweight='bold')
    ax1.set_xlabel("Time (BJD)", fontsize=10)
    ax1.set_ylabel("Normalized Flux", fontsize=10)
    add_corner_annotations(ax1)

    # ==========================================
    # Panel 2: Flattened LC
    # ==========================================
    ax2 = fig.add_subplot(gs[1, 0])
    t_flat = lc_flat.time.value
    y_flat = lc_flat.flux.value
    mask2 = np.isfinite(t_flat) & np.isfinite(y_flat)
    ax2.plot(t_flat[mask2], y_flat[mask2], '.k', markersize=2, alpha=0.4)
    ax2.set_title("Panel 2: Flattened / Detrended Light Curve", fontsize=11, fontweight='bold')
    ax2.set_xlabel("Time (BJD)", fontsize=9)
    ax2.set_ylabel("Detrended Flux", fontsize=9)
    add_corner_annotations(ax2)

    # ==========================================
    # Panel 3: Phased LC (2 cycles side-by-side)
    # ==========================================
    ax3 = fig.add_subplot(gs[1, 1])
    if period is not None and epoch is not None:
        folded = lc_flat.fold(period=period, epoch_time=epoch)
        ph = folded.time.value
        flx = folded.flux.value
        # Plot 2 cycles side-by-side (phase 0 to 2)
        ph_2cycle = np.concatenate([ph, ph + 1.0])
        flx_2cycle = np.concatenate([flx, flx])
        ax3.plot(ph_2cycle, flx_2cycle, '.k', markersize=2, alpha=0.25)
        
        # Binned average overplotted
        try:
            binned = folded.bin(time_bin_size=period/80)
            b_ph = binned.time.value
            b_flx = binned.flux.value
            b_ph_2 = np.concatenate([b_ph, b_ph + 1.0])
            b_flx_2 = np.concatenate([b_flx, b_flx])
            ax3.plot(b_ph_2, b_flx_2, 'ro', markersize=3, label='Binned')
        except Exception:
            pass
        ax3.set_xlim(-0.2, 1.8)
        ax3.set_title(f"Panel 3: Phased Light Curve (2 Cycles, P={period:.4f} d)", fontsize=11, fontweight='bold')
        ax3.set_xlabel("Phase (0 to 2)", fontsize=9)
        ax3.set_ylabel("Normalized Flux", fontsize=9)
    elif "SINGLE_TRANSIT" in category and 't_zoom' in best_res:
        ax3.plot(best_res['t_zoom'], best_res['y_zoom'], '.k', markersize=3, alpha=0.4)
        ax3.plot(best_res['t_zoom'], best_res['model_flux'], 'r-', lw=2, label='Trapezoid Fit')
        ax3.set_title(f"Panel 3: Single Transit Zoom & Fit (t0={epoch:.3f})", fontsize=11, fontweight='bold')
        ax3.set_xlabel("Time (BJD)", fontsize=9)
        ax3.set_ylabel("Flux", fontsize=9)
        ax3.legend(loc='lower right', fontsize=8)
    elif "MICROLENSING" in category and 't_zoom' in best_res:
        ax3.plot(best_res['t_zoom'], best_res['y_zoom'], '.k', markersize=3, alpha=0.4)
        ax3.plot(best_res['t_zoom'], best_res['model_flux'], 'r-', lw=2, label='Paczyński PSPL Fit')
        ax3.set_title(f"Panel 3: Paczyński Microlensing Zoom (t0={epoch:.3f})", fontsize=11, fontweight='bold')
        ax3.set_xlabel("Time (BJD)", fontsize=9)
        ax3.set_ylabel("Magnified Flux", fontsize=9)
        ax3.legend(loc='upper right', fontsize=8)
    else:
        # Variable star phased
        if period is not None:
            folded = lc_unflat.fold(period=period)
            ph = folded.time.value
            flx = folded.flux.value
            ax3.plot(np.concatenate([ph, ph+1.0]), np.concatenate([flx, flx]), '.k', markersize=2, alpha=0.3)
            ax3.set_title(f"Panel 3: Phased Variable Light Curve (P={period:.4f} d)", fontsize=11, fontweight='bold')
            ax3.set_xlabel("Phase", fontsize=9)
            ax3.set_ylabel("Normalized Flux", fontsize=9)
    add_corner_annotations(ax3)

    # ==========================================
    # Panel 4: Periodogram / Model Evaluation
    # ==========================================
    ax4 = fig.add_subplot(gs[2, 0])
    if 'results' in best_res:
        # BLS Periodogram
        res = best_res['results']
        ax4.plot(res.period, res.power, 'k-', lw=0.8)
        ax4.axvline(period, color='r', linestyle='--', alpha=0.7, label=f"Peak: {period:.4f}d")
        ax4.set_title(f"Panel 4: BLS Periodogram (SDE = {sde:.1f})", fontsize=11, fontweight='bold')
        ax4.set_xlabel("Period (days)", fontsize=9)
        ax4.set_ylabel("BLS Power", fontsize=9)
        ax4.legend(loc='upper right', fontsize=8)
    elif 'frequency_grid' in best_res:
        # Lomb-Scargle Periodogram
        f_grid = best_res['frequency_grid']
        p_grid = best_res['power_grid']
        fap = best_res.get('fap', 1.0)
        ax4.plot(f_grid, p_grid, 'k-', lw=0.8)
        ax4.axvline(best_res['frequency'], color='r', linestyle='--', alpha=0.7, label=f"Freq: {best_res['frequency']:.3f} c/d")
        ax4.set_title(f"Panel 4: Lomb-Scargle Periodogram (FAP = {fap:.1e})", fontsize=11, fontweight='bold')
        ax4.set_xlabel("Frequency (cycles/day)", fontsize=9)
        ax4.set_ylabel("LS Power", fontsize=9)
        ax4.legend(loc='upper right', fontsize=8)
    elif "MICROLENSING" in category:
        # Residuals of Paczynski fit
        resids = best_res['y_zoom'] - best_res['model_flux']
        ax4.plot(best_res['t_zoom'], resids, '.b', markersize=2, alpha=0.5)
        ax4.axhline(0, color='r', linestyle='--', alpha=0.7)
        ax4.set_title(f"Panel 4: Fit Residuals (Chi2/dof = {best_res.get('chi2', 1.0):.2f})", fontsize=11, fontweight='bold')
        ax4.set_xlabel("Time (BJD)", fontsize=9)
        ax4.set_ylabel("Residuals", fontsize=9)
    else:
        # Single transit SNR summary
        ax4.axis('off')
        ax4.text(0.5, 0.5, f"Single Transit Candidate\nSNR: {best_res.get('snr', 0):.1f}\nImpact b: {best_res.get('impact_parameter', 0):.2f}\nDuration: {best_res.get('duration_hours', 0):.1f} h", 
                 ha='center', va='center', fontsize=12,
                 bbox=dict(boxstyle='round,pad=0.5', facecolor='#f0f0f0'))
    add_corner_annotations(ax4)

    # ==========================================
    # Panel 5: Secondary Eclipse / Odd-Even / Diagnostics
    # ==========================================
    ax5 = fig.add_subplot(gs[2, 1])
    if "EXOPLANET" in category and period is not None and epoch is not None:
        # Odd vs Even Transit Check
        folded_2x = lc_flat.fold(period=2.0*period, epoch_time=epoch)
        ax5.plot(folded_2x.time.value, folded_2x.flux.value, '.k', markersize=2, alpha=0.25)
        ax5.axvline(0, color='r', linestyle='--', alpha=0.6, label='Even (Phase 0.0)')
        ax5.axvline(0.5, color='b', linestyle='--', alpha=0.6, label='Odd (Phase 0.5)')
        ax5.axvline(-0.5, color='b', linestyle='--', alpha=0.6)
        oe_ratio = best_res.get('odd_even_ratio', 1.0)
        ax5.set_xlim(-0.75, 0.75)
        ax5.set_title(f"Panel 5: Odd/Even Check (Ratio = {oe_ratio:.2f})", fontsize=11, fontweight='bold')
        ax5.set_xlabel("Phase (Double Period)", fontsize=9)
        ax5.set_ylabel("Flux", fontsize=9)
        ax5.legend(loc='upper right', fontsize=8)
    elif "ECLIPSING_BINARY" in category and period is not None and epoch is not None:
        # Phase 0.5 Secondary Eclipse Zoom
        folded = lc_flat.fold(period=period, epoch_time=epoch)
        ax5.plot(folded.time.value, folded.flux.value, '.k', markersize=2, alpha=0.35)
        ax5.axvline(0.5, color='r', linestyle='--', alpha=0.7, label='Phase 0.5')
        ax5.set_xlim(0.35, 0.65)
        sec_ratio = best_res.get('sec_ratio', 0.0)
        ax5.set_title(f"Panel 5: Secondary Eclipse Zoom (Drop = {sec_ratio*100:.1f}%)", fontsize=11, fontweight='bold')
        ax5.set_xlabel("Phase", fontsize=9)
        ax5.set_ylabel("Flux", fontsize=9)
        ax5.legend(loc='upper right', fontsize=8)
    elif "VARIABLE_STAR" in category and period is not None:
        # Sinusoidal Fit
        folded = lc_unflat.fold(period=period)
        ax5.plot(folded.time.value, folded.flux.value, '.k', markersize=2, alpha=0.25)
        model_t = np.linspace(-0.5, 0.5, 100) * period
        model_y = best_res['ls_model'].model(model_t + lc_unflat.time.value[0], best_res['frequency'])
        ax5.plot(np.linspace(-0.5, 0.5, 100), model_y, 'r-', lw=2, label='Harmonic Model')
        harm_str = f"Harmonics: {best_res.get('harmonics', [])}"
        ax5.set_title(f"Panel 5: Harmonic Fit ({harm_str})", fontsize=11, fontweight='bold')
        ax5.set_xlabel("Phase", fontsize=9)
        ax5.set_ylabel("Normalized Flux", fontsize=9)
        ax5.legend(loc='upper right', fontsize=8)
    else:
        # Centroid / Diagnostic Info
        ax5.axis('off')
        c_status = best_res.get('centroid_desc', 'Clean photocenter')
        tier = best_res.get('tier', 'A')
        ax5.text(0.5, 0.5, f"Vetting & Quality Control\nTier: {tier} Candidate\nCentroid: {c_status}\nOdd/Even Ratio: {best_res.get('odd_even_ratio', 1.0):.2f}",
                 ha='center', va='center', fontsize=12,
                 bbox=dict(boxstyle='round,pad=0.5', facecolor='#e8f4f8'))
    add_corner_annotations(ax5)

    plt.tight_layout()
    safe_cat = category.replace(' ', '_')
    filename = DISCOVERIES_DIR / f"{tic_id}_{safe_cat}_5panel.png"
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    return str(filename)
