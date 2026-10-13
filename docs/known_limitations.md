# Known Limitations & Systematic Flaws

This document inventories known physical and algorithmic bounds of the Astrohunter Pro photometric pipeline.

---

## 1. Blend Resolution Floor ($\sim 1.0\,\text{Pixel}$)

* **Astrophysical Basis:** TESS utilizes wide-field optics with a plate scale of **$21''$ per pixel**. The Point Spread Function (PSF) spans multiple pixels (FWHM $\sim 1.5 - 2.0\,\text{px}$).
* **Algorithmic Limit:** Difference-image photocenter calculation reliably resolves background eclipsing binaries and blends only when the angular separation exceeds **$\approx 1.0\,\text{pixel}$** ($21''$).
* **Consequence:** Contaminating background stars or grazing eclipsing binaries located within $0.0 - 0.9\,\text{px}$ cannot be distinguished from host-star transits by single-pixel difference imaging alone. High-resolution speckle imaging or adaptive optics follow-up is necessary to confirm target isolation.

---

## 2. Search Baseline & Single-Sector Limits ($N_{\text{cycles}} \ge 3.0$)

* **Sector Duration:** A standard TESS observation sector spans approximately **$27.4\,\text{days}$**, interrupted by a $\sim 1.5\,\text{day}$ perigee data gap.
* **Cycle Rule:** Reliable transit identification and odd-even validation require at least 3 distinct transits ($N_{\text{cycles}} \ge 3.0$).
* **Effective Single-Sector Limit:** On single-sector light curves, requiring 3 cycles restricts the maximum recoverable period to:
  $$P_{\text{max, 1-sector}} \approx \frac{26.0\,\text{d}}{3.0} \approx 8.7\,\text{days}$$
* **Grid Edge Artifacts:** While the BLS engine searches up to $P_{\max} = 20.0\,\text{days}$, periods between $8.7\,\text{d}$ and $20.0\,\text{d}$ in a single sector exhibit only 1 or 2 events, producing elevated false-alarm rates and grid-edge pileup. Multi-sector stitching is required to survey periods beyond $8.7\,\text{d}$.

---

## 3. Detrender Attenuation on Long-Duration Transits

* **Current Architecture:** Photometric detrending employs `lightkurve.flatten()` (iterative outlier-clipped Savitzky-Golay polynomial filtering) with a fixed window of 401 cadences (~13.4 hours on 2-minute cadence).
* **Limitation:** In unmasked polynomial flattening, data points within wide or shallow transits bias the baseline fit downward, reducing the recovered transit depth and lowering signal detection efficiency. Masked iterative detrending and biweight filters are scheduled for implementation in Work Package 3.

---

## 4. Grazing Eclipsing Binary Disguise

* **Vetting Challenge:** Eclipsing binaries with grazing geometries or low-mass stellar companions can produce shallow, V-shaped eclipses with weak or undetectable secondary eclipses ($\delta_{\text{sec}} \le 0.15\,\delta_{\text{pri}}$).
* **Benchmark Evidence:** In the 50-target development benchmark, 9 eclipsing binaries and false positives were classified as Tier A candidates because their secondary eclipses fell below automated detection thresholds.

---

## 5. Catalog Parameter Incompleteness

* **Physical Constraints:** Physical radius boundaries ($R_{\text{comp}} \le 2.0\,R_{\text{Jup}}$) and Keplerian orbital separation checks ($a > R_\star$) require host star radius $R_\star$ and mass $M_\star$.
* **Mitigation:** Targets lacking host star radius or mass in Gaia DR3 and the TIC v8.2 catalog cannot undergo physical companion sizing. The pipeline deliberately refuses to invent default parameters, demoting such targets to Tier B (`Unconstrained Parameters`).

---

## 6. Policy on Causal Claims

* In accordance with scientific integrity standards, the pipeline documentation and reports **do not attribute** any missed detection, period mismatch, or false alarm to specific physical mechanisms (such as spot migration, differential rotation, multi-mode pulsation, or aliasing) unless an explicit diagnostic test demonstrates the cause. Where no empirical test has been executed, causes are recorded as **"not investigated"**.
