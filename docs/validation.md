# Validation and Centroid Methodology

## Automated Gating vs. Astrophysical Validation

Astrohunter Pro implements an automated signal filtering and classification pipeline for TESS light curves. In automated pipelines, passing automated tests must **never** be equated with astrophysical validation:

> **Tier A Definition:** "Passes automated pipeline checks; not astrophysical validation."

In the 50-target development benchmark ([`docs/benchmark.md`](benchmark.md)), **9 of the 32 targets assigned Tier A were non-planets** (eclipsing binaries, blend contamination, or stellar variability). Any exoplanet claim requires rigorous multi-instrument follow-up (high-resolution spectroscopy, ground-based transit depth verification, speckle imaging), which is beyond the scope of automated photometric pipelines.

---

## 1. Physical Gating Constraints

Automated transit and companion checks evaluate physical boundary conditions:

### Companion Radius Gating
Using stellar radii from Gaia DR3 or the TIC v8.2 catalog:
$$R_{\text{comp}} = R_\star \sqrt{\delta}$$
where $\delta$ is the fractional transit depth. Electron degeneracy limits substantiate an upper physical ceiling for gas giant planets of $R_{\text{comp}} \le 2.0\,R_{\text{Jup}}$. Signals exceeding this threshold represent stellar companions (eclipsing binaries) or uncataloged background blend contamination. When host star parameters are unavailable from catalogs, candidates cannot be physically bounded and are capped at Tier B (`Unconstrained Parameters`).

### Keplerian Orbit Separation Constraint
For detected orbital period $P$ (days) and stellar parameters ($M_\star, R_\star$):
$$a = \left( \frac{G M_\star P^2}{4 \pi^2} \right)^{1/3}$$
Signals with orbital semi-major axis $a \le R_\star$ imply a companion orbiting inside the stellar envelope, a physical impossibility that rejects the transit solution.

### Transit Duration Boundary
For spherical central transits, the maximum theoretical duration is:
$$T_{\text{max}} = \frac{P R_\star}{\pi a}$$
Transit signals on giant stars ($R_\star > 5\,R_\odot$) whose detected durations fall orders of magnitude below physical chord transit times indicate localized instrumental artifacts or unassociated background variations.

---

## 2. Centroid and Difference-Image Vetting

Photocenter shifts are evaluated to flag background eclipsing binaries (EBs) blended within the large $21''$ TESS pixel footprint.

### Blend Resolution Limit
> **Empirical Resolution Limit:** Difference-image centroid vetting reliably excludes blended contaminants only beyond approximately **1.0 pixel** ($21''$). Blends within $0.0 - 0.9\,\text{px}$ cannot be distinguished from on-target signals by single-pixel difference imaging alone.

### Centroid Check Implementations
1. **Lightcurve Flux-Weighted Centroid Shifts (`centroid_sigma`):**
   Calculates the center-of-mass shift between in-transit and out-of-transit cadences using local shoulder cadences ($|\phi| \in [0.5\,q, 3.5\,q]$). Significance is evaluated via two-sample Welch standard error of the mean (SEM):
   $$\text{SEM} = \sqrt{\frac{\sigma_{\text{in}}^2}{N_{\text{in}}} + \frac{\sigma_{\text{out}}^2}{N_{\text{out}}}}$$
   $$\sigma_{\text{shift}} = \frac{\Delta r}{\text{SEM}}$$

2. **TPF Difference-Image Photocenter Offsets (`centroid_offset_px`):**
   Subtracts the mean in-transit Target Pixel File (TPF) image from the mean out-of-transit reference image:
   $$I_{\text{diff}} = \langle I_{\text{out}} \rangle - \langle I_{\text{in}} \rangle$$
   The point-spread photocenter is fitted to $I_{\text{diff}}$ and compared to the target's WCS coordinates.

3. **Empirical Threshold Calibration (`tpf_threshold_calibration.json`):**
   - Pooled 100-realization 95th-percentile offset ceiling on on-target transits: **0.96 px**.
   - Per-star null ceiling ($p95 + 2 \times \text{IQR}$) calibrated individually for audited stars (e.g., HD 10661 ceiling = 0.37 px).
   - Signals with $\Delta r > 0.96\,\text{px}$ or exceeding their per-star null ceiling are demoted from Tier A to Tier B or Tier C.

4. **Variable-Star Peak-vs-Trough Difference Imaging:**
   For periodic variables identified via Lomb-Scargle, difference imaging is performed between phase quarters:
   $$I_{\text{diff, var}} = \langle I_{\phi \in [0.15, 0.35]} \rangle - \langle I_{\phi \in [0.65, 0.85]} \rangle$$
   Evaluated across all 4 reference phase offsets ($0.0, 0.125, 0.25, 0.375$) with a mandatory 5$\sigma$ amplitude coherence gate.
