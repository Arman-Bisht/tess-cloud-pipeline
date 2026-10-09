# Scientific Corrections & Audit Log (CORRECTIONS.md)

This document transparently records all retracted early pipeline classifications, astrophysical corrections, and bug fixes applied to the **Astrohunter Pro** survey catalog. Maintaining an open, honest correction log is a cornerstone of reproducible astronomical science.

---

## 1. Retracted Early Exoplanet & Binary Classifications

### 1.1 HD 10647 (q¹ Eridani) — Non-Transiting Radial Velocity Host
* **Initial Exploratory Flag:** Classified in early scans as a "newly confirmed exoplanet discovery" based on a high Box Least Squares significance ($\text{SDE} = 70.8$).
* **Astrophysical Reality:** HD 10647 hosts $q^1\,\text{Eri}\,\text{b}$, a known radial-velocity exoplanet on a $989\,\text{day}$ orbit that **does not transit**. The periodic signal detected by TESS is stellar rotational modulation ($\sim 11.2\,\text{days}$) driven by starspots, not a transit.
* **Correction:** Retracted exoplanet transit claim; cataloged as `KNOWN_RV_HOST_ROTATIONAL_VAR`.

### 1.2 Giant Host Short Dips (HD 10548, HD 10609, HD 10652, HD 10654, HD 10658)
* **Initial Exploratory Flag:** Logged as "long-period single-transit planet candidates" with solitary $\sim 3.6\,\text{hour}$ dips.
* **Astrophysical Reality:** The host stars are red giants with radii $R_* \in [13, 88]\,R_\odot$. For an orbit crossing an $88\,R_\odot$ giant, the escape velocity is $\sim 65\,\text{km/s}$, requiring a minimum central transit duration of $T_{\text{cross}} \ge 65\,\text{hours}$. A $3.6\,\text{hour}$ dip implies an unphysical crossing velocity exceeding $9,500\,\text{km/s}$ ($> 50\times v_{\text{esc}}$).
* **Correction:** Retracted exoplanet claims. Reclassified as **Tier C (Blended Background Binaries)** where an off-target eclipsing binary contaminates the TESS photometric aperture.

### 1.3 Unphysical Orbit Solutions (HD 10525, HD 10614, HD 10689, HD 10696)
* **Initial Exploratory Flag:** HD 10525 was initially flagged as an eclipsing binary with period $P = 0.6107\,\text{days}$ and host radius $R_* = 28.23\,R_\odot$.
* **Astrophysical Reality:** By Kepler's third law ($a \propto P^{2/3}$), a $0.61\,\text{day}$ orbit has a semi-major axis $a \approx 4.37\,R_\odot$. An orbit of $4.4\,R_\odot$ would sit deep inside the $28.2\,R_\odot$ stellar envelope.
* **Correction:** Enforced $a > R_*$ orbital separation constraint. HD 10525 was reclassified as an envelope-pulsating giant; HD 10689 was identified as a grid-edge boundary pileup ($P_{\text{grid}} = 20.0\,\text{d}$ vs VSX $P = 218.4\,\text{d}$).

### 1.4 Baseline Cycle Count Enforcement (HD 10605 & HD 10526)
* **Initial Flag:** Labeled Tier A in initial draft catalogs.
* **Astrophysical Reality:** On a single TESS sector baseline of $\sim 27.4\,\text{days}$, HD 10605 ($P = 15.17\,\text{d}$) observed only $1.8$ cycles, and HD 10526 ($P = 11.37\,\text{d}$) observed only $2.4$ cycles. Neither meets the required $N_{\text{cycles}} \ge 3.0$ threshold.
* **Correction:** Reclassified to **Tier C (Insufficient Baseline Coverage)** until multi-sector data confirms periodicity.

---

## 2. Algorithmic & Software Bug Fixes

| Bug ID | Component | Defect Description | Mathematical & Code Resolution |
| :--- | :--- | :--- | :--- |
| **BUG-01** | `vetter.py` | Lightkurve `lc.fold()` returns time in **days**, not normalized phase $[-0.5, 0.5]$. Checking `np.abs(phase - 0.5) < window` tested $t = 0.5\,\text{days}$, missing secondary eclipses for any period other than $1.0\,\text{day}$. | Added `normalize_phase=True` to `lc.fold()` and set eclipse search window to $\phi \in [-0.5, 0.5]$. Replaced `nanmin` with binned medians to prevent noise-spike bias. |
| **BUG-02** | `vetter.py` | Centroid shift significance divided mean shift by per-cadence scatter $\sigma$ rather than standard error $\text{SEM} = \sigma / \sqrt{N}$, understating shift significance by $\sim \sqrt{N}$. | Implemented two-sample Welch standard error $\text{SEM} = \sqrt{\sigma_{\text{in}}^2/N_{\text{in}} + \sigma_{\text{out}}^2/N_{\text{out}}}$. Allowed centroid vetting to run on single transit dips. |
| **BUG-03** | `vetter.py` / `db.py` | Physical orbit ($a > R_*$) and duration checks were defined but not invoked in `vet_signals()`. `db.py` overrode tier assignment using only four flag columns. | Wired `check_orbit_physical_separation` and `check_transit_duration_physical` directly into `vet_signals()`. Derived tier confidence strictly from unified metrics. |
| **BUG-04** | `bls_engine.py` / `variable_engine.py` | Fixed linear period grids produced false precision (e.g. reporting exact grid step $10.64627\,\text{d}$ and $17.53407\,\text{d}$). | Switched to frequency-uniform oversampled grids (`autoperiod`) with local fine-subgrid peak refinement and formal FWHM period uncertainties ($\sigma_P$). |
| **BUG-05** | `downloader.py` | `get_lightcurves` swallowed all network exceptions and returned `None`, preventing Tenacity `@retry` from recovering transient MAST drops and turning transient timeouts into permanent `NO_DATA`. | Propagated network exceptions to trigger exponential retry; added cadence filtering (`exptime=120`) to eliminate duplicate mixed cadences. |
| **BUG-06** | Test Suite | `test_pipeline_upgrades.py` called `save_discovery` and appended synthetic test star `HD_TEST_SINGLE` to production CSV. | Purged test row from catalog; isolated tests from production database and CSV. |

---

## 3. Ground-Truth Recovery Accounting

* **Sample Footprint:** 732 HD stars (497 observed by TESS, 235 with no TESS observations).
* **VSX Matches:** 34 stars match AAVSO VSX records (19 have unmeasured/NaN periods; 15 have published periods).
* **Recoveries:** **4 of 15** ($26.7\%$) with usable published periods:
  * 3 fundamental recoveries ($1.0\times$): HD 10720 ($0.03\%$ difference), HD 10502 ($1.000\times$), HD 10081 ($1.001\times$).
  * 1 harmonic recovery ($2.0\times$): HD 10040 ($1.998\times$, contact binary).
* **External Control:** WASP-126 b ($1.000\times$) is reported as an external non-HD instrument control and strictly excluded from the HD survey denominator.
