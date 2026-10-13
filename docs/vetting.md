# Vetting Pipeline & Engine Architecture

## Overview

Astrohunter Pro processes NASA TESS light curves through a three-stage automated pipeline:
1. **Photometric Ingestion & Detrending:** Multi-stream preparation.
2. **Multi-Engine Signal Search:** Periodic transits (BLS), stellar variability (Lomb-Scargle), and solitary dips (Single-Transit Engine).
3. **Astrophysical & Centroid Vetting:** Automated physics gates, catalog cross-matching, centroid tests, and tier assignment.

---

## 1. Photometric Ingestion & Detrending

The ingestion layer (`downloader.py`) queries MAST via `lightkurve` and processes TESS data into three parallel streams:

| Stream | Processing Method | Purpose |
| :--- | :--- | :--- |
| **Stream 1 (`lc_flat`)** | Outlier-clipped Savitzky-Golay polynomial flatten (`window_length=401`, ~13.4 hours on 2-min cadence) | Repeating periodic transit search via BLS |
| **Stream 2 (`lc_unflat`)** | Normalized flux without upper-outlier clipping or polynomial flattening | Periodic stellar variability search via Lomb-Scargle; preserves astrophysical amplitudes |
| **Stream 3 (`lc_wide_flat`)** | Wide Savitzky-Golay polynomial flatten (`window_length=2001`, ~66.7 hours on 2-min cadence) | Deep isolated solitary transit search |

---

## 2. Signal Search Engines

### Box Least Squares (BLS) Engine (`bls_engine.py`)
- **Period Range:** $P \in [0.4, 20.0]\,\text{days}$ (configured via `BLS_MIN_PERIOD`, `BLS_MAX_PERIOD`).
- **Transit Duration:** Grid evaluated across durations $0.05 \le q \le 0.15$ of period.
- **Significance Metric:** Signal Detection Efficiency (SDE):
  $$\text{SDE} = \frac{\text{Power}_{\text{max}} - \langle \text{Power} \rangle}{\sigma_{\text{Power}}}$$
- **Automated Gate:** Nominal threshold $\text{SDE} \ge 10.0$ and transit count $N_{\text{transits}} \ge 3.0$.

### Lomb-Scargle Periodogram (`variable_engine.py`)
- **Frequency Range:** $f \in [0.05, 30.0]\,\text{days}^{-1}$ (periods from $0.0333\,\text{d}$ to $20.0\,\text{d}$).
- **Input Data:** Unflattened normalized stream (`lc_unflat`) to prevent distortion or attenuation of stellar pulsations and rotational modulation.
- **Harmonic Detection:** Automatically scans for $2f$ and $3f$ harmonic components.

### Single-Transit Engine (`single_transit_engine.py`)
- Scans `lc_wide_flat` for isolated single-transit dips when no periodic signal achieves $\text{SDE} \ge 10.0$.
- Requires duration $T \le 0.5\,\text{d}$ and dip significance $\text{SNR} \ge 7.0$.

---

## 3. Vetting Chain & False-Positive Elimination

Candidate signals pass through the vetting chain (`vetter.py`):

1. **Secondary Eclipse Check:**
   Phase folds at $\phi = 0.5 \pm 0.05$. Signals with a significant secondary eclipse ($\delta_{\text{sec}} / \delta_{\text{pri}} > 0.15$) are classified as `ECLIPSING_BINARY`.
2. **Odd-Even Depth Consistency:**
   Compares odd-numbered transits against even-numbered transits. Ratios deviating significantly indicate alternating eclipses from an eclipsing binary with twice the detected orbital period.
3. **Physical Gating:**
   Evaluates companion radius ($R_{\text{comp}} \le 2.0\,R_{\text{Jup}}$), orbital semi-major axis ($a > R_\star$), and giant transit durations ([`docs/validation.md`](validation.md)).
4. **Centroid & TPF Difference Imaging:**
   Calculates lightcurve flux-weighted moment shifts and TPF difference-image offsets relative to target WCS coordinates.
5. **Catalog Cross-Matching (`catalog_checker.py`):**
   Queries live NASA TOI tables, AAVSO VSX, SIMBAD TAP, and TESS Eclipsing Binary catalogs to identify previously known targets.

---

## 4. Automated Classification & Tier Definitions

| Classification Tier | Criteria | Interpretation |
| :--- | :--- | :--- |
| **Tier A** | Passes all automated tests: $\text{SDE} \ge 10.0$, odd/even consistent, no secondary eclipse, physical radius $\le 2.0\,R_{\text{Jup}}$, $a > R_\star$, centroid offset $\le 0.96\,\text{px}$ (and below per-star null ceiling). | **Passes automated checks; not astrophysical validation.** (Benchmark shows 28.1% false-positive contamination). |
| **Tier B** | Passes transit criteria but lacks centroid confirmation (`NOT_RUN`), has marginal centroid offset ($0.96 < \Delta r \le 1.5\,\text{px}$), or host star parameters are missing from catalogs (`Unconstrained Parameters`). | **Plausible candidate requiring further photometric review.** |
| **Tier C** | Flagged by automated filters: baseline coverage $N_{\text{cycles}} < 3$, boundary pileup ($P \approx 20\,\text{d}$), unphysical orbit ($a \le R_\star$), or significant centroid shift ($\Delta r > 1.5\,\text{px}$). | **High-probability false alarm or background blend.** |
| **False Positive** | Clear secondary eclipse, companion radius $> 2.0\,R_{\text{Jup}}$, or cataloged eclipsing binary. | **Rejected as non-planet astrophysical or instrumental false positive.** |

---

## 5. Diagnostic Visualization (`visualizer.py`)

Every candidate meeting vetting thresholds outputs a standardized 5-panel scientific diagnostic figure:
* **Panel 1:** Full detrended multi-sector light curve with cadence quality flags.
* **Panel 2:** Phase-folded transit with best-fit trapezoidal or limb-darkened model.
* **Panel 3:** Periodogram spectrum (BLS or Lomb-Scargle) illustrating peak prominence and SDE.
* **Panel 4:** Pixel-level Target Pixel File (TPF) difference image displaying photocenter position relative to catalog WCS coordinates.
* **Panel 5:** Summary metadata panel reporting stellar parameters, catalog cross-matches, and vetting metric values.
