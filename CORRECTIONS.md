# Scientific Corrections & Audit Log (CORRECTIONS.md)

This document transparently records all retracted early pipeline classifications, astrophysical corrections, and bug fixes applied to the **Astrohunter Pro** survey catalog. Maintaining an open, honest correction log is a cornerstone of reproducible astronomical science.

---

## 1. Retracted Early Exoplanet & Binary Classifications

### 1.1 HD 10647 (q¹ Eridani) — Non-Transiting Radial Velocity Host
* **Initial Exploratory Flag:** Classified in early scans as a "newly confirmed exoplanet discovery" based on a high Box Least Squares significance ($\text{SDE} = 70.8$).
* **Astrophysical Reality:** HD 10647 hosts $q^1\,\text{Eri}\,\text{b}$, a known radial-velocity exoplanet on a $989\,\text{day}$ orbit that **does not transit**. The periodic signal detected by TESS at $\sim 11.2\,\text{days}$ is non-transiting stellar variability (astrophysical origin not determined; likely rotational or chromospheric modulation), not a transit.
* **Correction:** Retracted exoplanet transit claim; cataloged as `KNOWN_RV_HOST_ROTATIONAL_VAR`.

### 1.2 Giant Host Short Dips (HD 10548, HD 10609, HD 10652, HD 10654, HD 10658)
* **Initial Exploratory Flag:** Logged as "long-period single-transit planet candidates" with solitary $\sim 3.6\,\text{hour}$ dips.
* **Astrophysical Reality:** The host stars are red giants with radii $R_* \in [13, 88]\,R_\odot$. For an orbit crossing an $88\,R_\odot$ giant ($M_* \approx 2.5\,M_\odot$), the surface circular speed is $v_{\text{circ}} = \sqrt{G M_* / R_*} \approx 73.6\,\text{km/s}$ (central crossing $T_{\text{cross, circ}} \approx 462\,\text{hours} \approx 19.3\,\text{days}$). The maximum possible bound Keplerian speed is the escape velocity $v_{\text{esc}} = \sqrt{2} \times v_{\text{circ}} \approx 104.1\,\text{km/s}$, defining the absolute physical minimum diameter crossing duration of $T_{\text{cross, min}} = 2 R_* / v_{\text{esc}} \approx 327\,\text{hours}$ ($13.6\,\text{days}$; or $517\,\text{hours}$ for $1.0\,M_\odot$). A $3.6\,\text{hour}$ dip implies an unphysical velocity exceeding $9,500\,\text{km/s}$ ($> 90\times v_{\text{esc}}$).
* **Correction:** Retracted exoplanet claims. Reclassified as **Tier C (Blended Background Binaries)** where an off-target eclipsing binary contaminates the TESS photometric aperture.

### 1.3 Unphysical Orbit Solutions (HD 10525, HD 10614, HD 10689, HD 10696)
* **Initial Exploratory Flag:** HD 10525 was initially flagged as an eclipsing binary with period $P = 0.6107\,\text{days}$ and host radius $R_* = 28.23\,R_\odot$.
* **Astrophysical Reality:** By Kepler's third law ($a \propto P^{2/3}$), a $0.61\,\text{day}$ orbit has a semi-major axis $a \approx 4.37\,R_\odot$. An orbit of $4.4\,R_\odot$ would sit deep inside the $28.2\,R_\odot$ stellar envelope.
* **Correction:** Enforced $a > R_*$ orbital separation constraint. HD 10525 ($P = 0.61\,\text{d}$) was reclassified as an unphysical orbit solution since $a=4.4\,R_\odot \ll 28.2\,R_\odot$ (astrophysical origin of variability not determined); HD 10689 was identified as a grid-edge boundary pileup ($P_{\text{grid}} = 20.0\,\text{d}$ vs VSX $P = 218.4\,\text{d}$).

### 1.4 Baseline Cycle Count Enforcement (HD 10605 & HD 10526)
* **Initial Flag:** Labeled Tier A in initial draft catalogs.
* **Astrophysical Reality:** On a single TESS sector baseline of $\sim 27.4\,\text{days}$, HD 10605 ($P = 15.17\,\text{d}$) observed only $1.8$ cycles, and HD 10526 ($P = 11.37\,\text{d}$) observed only $2.4$ cycles. Neither meets the required $N_{\text{cycles}} \ge 3.0$ threshold.
* **Correction:** Reclassified to **Tier C (Insufficient Baseline Coverage)** until multi-sector data confirms periodicity.

---

## 2. Algorithmic & Software Bug Fixes

| Bug ID | Component | Defect Description | Mathematical & Code Resolution |
| :--- | :--- | :--- | :--- |
| **BUG-01** | `vetter.py` | Lightkurve `lc.fold()` returns time in **days**, not normalized phase $[-0.5, 0.5]$. Checking `np.abs(phase - 0.5) < window` tested $t = 0.5\,\text{days}$, missing secondary eclipses for any period other than $1.0\,\text{day}$. | Added `normalize_phase=True` to `lc.fold()` and set eclipse search window to $\phi \in [-0.5, 0.5]$. Replaced `nanmin` with binned medians to prevent noise-spike bias. |
| **BUG-02** | `vetter.py` | Centroid shift significance divided mean shift by per-cadence scatter $\sigma$ rather than standard error $\text{SEM} = \sigma / \sqrt{N}$, understating shift significance by $\sim \sqrt{N}$. | Implemented two-sample Welch standard error $\text{SEM} = \sqrt{\sigma_{\text{in}}^2/N_{\text{in}} + \sigma_{\text{out}}^2/N_{\text{out}}}$. Made centroid checking strictly tri-state (`PASS`, `FAIL`, `NOT_RUN`) and required measured `PASS` for Tier A. |
| **BUG-03** | `vetter.py` / `db.py` | Physical orbit ($a > R_*$) and duration checks were defined but not invoked in `vet_signals()`. `db.py` overrode tier assignment using only four flag columns. | Wired `check_orbit_physical_separation` and `check_transit_duration_physical` directly into `vet_signals()`. Derived tier confidence strictly from unified metrics. |
| **BUG-04** | `bls_engine.py` / `variable_engine.py` | Fixed linear period grids produced false precision (e.g. reporting exact grid step $10.64627\,\text{d}$ and $17.53407\,\text{d}$). Multi-year baselines stalled BLS evaluation. | Switched to frequency-uniform oversampled grids capped at 30,000 points with local fine-subgrid peak refinement and peak-width / FWHM period uncertainty estimates ($\sigma_P$). |
| **BUG-05** | `downloader.py` | `get_lightcurves` swallowed all network exceptions and returned `None`, preventing Tenacity `@retry` from recovering transient MAST drops and turning transient timeouts into permanent `NO_DATA`. | Propagated network exceptions to trigger exponential retry; added cadence filtering (`exptime=120`) to eliminate duplicate mixed cadences. |
| **BUG-06** | Test Suite | `test_pipeline_upgrades.py` called `save_discovery` and appended synthetic test star `HD_TEST_SINGLE` to production CSV. | Purged test row from catalog; isolated tests from production database and CSV. |
| **BUG-07** | `vetter.py` | In `vet_signals()`, the BLS branch required `... and centroid_pass` for exoplanet candidates. When centroid was unmeasured (`NOT_RUN`), `centroid_pass` was `False`, causing clean planet candidates to be mislabeled as `ECLIPSING_BINARY`. | Changed condition to `centroid_status != "FAIL"`. Unmeasured centroids now classify as `CANDIDATE_EXOPLANET` and are gated to Tier B by `assign_tier()`. |
| **BUG-08** | `main.py` | `process_target()` line 71 returned early if status was not `["PENDING", "PROCESSING"]`, preventing targets with transient download errors from ever being retried. | Added `"DOWNLOAD_ERROR"` to the allowable retry states in `main.py`, `serverless_entry()`, and `run_local_scan()`. |
| **BUG-09** | Engines & Catalog | Discrete grid artifacts produced duplicate periods across unrelated stars (`10.64627 d` and `17.53407 d`), while the catalog lacked honest period uncertainties and centroid statuses. | Implemented fine subgrid peak zooming and FWHM $\sigma_P$ calculation; resolved grid duplicates (HD 10555: $10.962 \pm 0.406\,\text{d}$; HD 10614: $10.834 \pm 0.398\,\text{d}$; HD 10594: $17.550 \pm 0.011\,\text{d}$; HD 10648: $20.000 \pm 0.787\,\text{d}$). Added Target Pixel File (TPF) photocenter difference imaging (`check_tpf_centroid_motion`, `check_tpf_variable_centroid_motion`), empirically confirming HD 10528 as Tier A ($0.96\,\sigma$ SEM shift). |
| **BUG-10** | `vetter.py` | Direct flux-weighted centroiding pulls toward nearby static neighbor stars when the target dims during transit, causing false $5\sigma+$ blend failures on real on-target transits. Centroid `FAIL` also prematurely condemned candidates to Tier C. | Implemented Kepler/TESS SPOC Difference Imaging ($\Delta I = I_{\text{out}} - I_{\text{in}}$) per Bryson et al. (2013), canceling static neighbor flux to zero and measuring offset against target WCS coordinates. Softened centroid `FAIL` to Tier B ("Blend Alert / Needs Manual Review") rather than Tier C. |

---

## 3. Ground-Truth Recovery Accounting

* **Sample Footprint:** 732 HD stars (497 observed by TESS, 235 with no TESS observations).
* **VSX Matches:** 34 stars match AAVSO VSX records (19 have unmeasured/NaN periods; 15 have published periods).
* **Recoveries:** **4 of 15** ($26.7\%$) with usable published periods:
  * 3 fundamental recoveries ($1.0\times$): HD 10720 ($0.03\%$ difference), HD 10502 ($1.000\times$), HD 10081 ($1.001\times$).
  * 1 harmonic recovery ($2.0\times$): HD 10040 ($1.998\times$, contact binary).
* **External Control:** WASP-126 b ($1.000\times$) is reported as an external non-HD instrument control and strictly excluded from the HD survey denominator.

---

## 4. Empirical Completeness Matrix & False-Alarm Rate (FAR) Calibration

To replace heuristic sensitivity assumptions with empirical bounds, [`injection_recovery.py`](injection_recovery.py) evaluated synthetic transits and pure-noise baselines:

### 4.1 2D Recovery Completeness Grid ($P \times \text{Depth}$)
* **$100\%$ Recovery Floor:** Any transit signal with depth $\ge 2500\,\text{ppm}$ ($0.25\%$) is recovered at $100\%$ efficiency across all periods from $0.8\,\text{d}$ to $12.0\,\text{d}$.
* **Moderate Depth ($1000\,\text{ppm}$):** $100\%$ recovery for $P \le 7.0\,\text{d}$; $67\%$ recovery at $P = 12.0\,\text{d}$ due to fewer in-transit cadences in a 27.4-day sector.
* **Shallow Dips ($500\,\text{ppm}$):** $100\%$ at $P = 0.8\,\text{d}$ (many transit cycles), $33\%$ at $P = 1.5\,\text{d}$, and $0\%$ at $P \ge 3.5\,\text{d}$ (approaching the single-sector TESS pink noise ceiling).

### 4.2 False-Alarm Rate (FAR) vs. SDE Threshold
Evaluated across 35 independent noise realizations over the full 30,000-trial BLS search grid:
* **Mean Noise SDE:** $8.03 \pm 0.71$ (95th percentile noise ceiling: $9.42$).
* **$\text{SDE} \ge 6.0$:** $\text{FAR} = 100.0\%$
* **$\text{SDE} \ge 7.0$:** $\text{FAR} = 88.6\%$
* **$\text{SDE} \ge 8.0$:** $\text{FAR} = 45.7\%$ (without vetting filters)
* **$\text{SDE} \ge 9.0$:** $\text{FAR} = 11.4\%$
* **$\text{SDE} \ge 10.0$:** $\mathbf{\text{FAR} = 0.0\%}$
* **Conclusion:** In wide blind searches without vetting, an unconstrained BLS peak reaches $\text{SDE} \sim 8 - 9$ by chance. Pristine Tier A classification strictly demands $\text{SDE} \ge 10.0$ or measured centroid confirmation, while $\text{SDE} \in [8.0, 10.0)$ requires passing secondary eclipse and duration filters.
