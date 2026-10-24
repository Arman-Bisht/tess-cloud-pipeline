# Benchmark v2 Selection Protocol & Pre-Registration

**Protocol Status:** Registered & Locked  
**Registration Date:** 2026-10-24  
**PRNG Seed:** `7319042`  
**Pipeline Execution Policy:** Strictly Held-Out (No pipeline runs, no light-curve inspection)

---

## 1. Objective & Evaluation Design

Benchmark v2 defines an external, held-out validation suite designed to evaluate pipeline sensitivity, specificity, period recovery, and multi-sector vetting capabilities on real NASA TESS SPOC 2-minute cadence data.

The suite is partitioned into two mutually exclusive sets:
* **Set A (Short-Period Benchmark, $N = 60$):** Targets evaluated under single-sector conditions with periods $P \le 8.7\,\text{days}$.
* **Set B (Long-Period / Multi-Sector Benchmark, $N = 60$):** Targets evaluated under multi-sector conditions with periods $8.7 < P \le 20.0\,\text{days}$.

Neither set is ever used for parameter tuning, threshold calibration, or iterative algorithmic adjustments.

---

## 2. Selection Rules & Stratification

Target selection is fully deterministic and rule-based, executed programmatically via `benchmark_v2/select_targets.py` using random seed **`7319042`**. Hand-picking targets is strictly prohibited.

### Set A: Short-Period Regime ($P \le 8.7\,\text{d}$)
* **Total Sample Size:** 60 targets.
* **Class Balance:**
  * **30 Confirmed/Known Planets (`PLANET`):**
    * Dispositions: `TOI_CP` (Confirmed Planet) or `TOI_KP` (Known Planet) from the NASA Exoplanet Archive TOI catalog.
    * Period range: $0.5 \le P \le 8.7\,\text{days}$.
    * Host star brightness: TESS magnitude $T_{\text{mag}} \le 13.0$.
    * Depth diversity: At least 10 shallow planetary transits with depth $\le 2500\,\text{ppm}$.
  * **30 Non-Planetary Signals (`NON_PLANET`):**
    * Dispositions: Diverse false positives (`TOI_FP`) across spectroscopic, centroid, and stellar false-positive classifications, and/or confirmed eclipsing binaries (`PRSA_EB`) from Prša et al. (2022).
    * Period range: $P \le 8.7\,\text{days}$.
    * Host star brightness: $T_{\text{mag}} \le 13.0$.
* **Cadence & Light Curve:** One verified SPOC 2-minute light curve FITS file fetched from the AWS Open Data mirror (`s3://stpubdata/tess/public/...`) or MAST.

### Set B: Long-Period / Multi-Sector Regime ($8.7 < P \le 20.0\,\text{d}$)
* **Total Sample Size:** 60 targets.
* **Class Balance:**
  * **30 Confirmed/Known Planets (`PLANET`):**
    * Dispositions: `TOI_CP` or `TOI_KP`.
    * Period range: $8.7 < P \le 20.0\,\text{days}$.
    * Host star brightness: $T_{\text{mag}} \le 13.0$.
  * **30 Non-Planetary Signals (`NON_PLANET`):**
    * Dispositions: Diverse false positives (`TOI_FP`) and/or eclipsing binaries (`PRSA_EB`).
    * Period range: $8.7 < P \le 20.0\,\text{days}$.
    * Host star brightness: $T_{\text{mag}} \le 13.0$.
* **Mandatory Multi-Sector Coverage:**
  * Every target in Set B **must have at least 2 distinct SPOC 2-minute cadence observation sectors** ($N_{\text{sectors}} \ge 2$).
  * The selection pipeline must reject and fail any candidate target possessing fewer than 2 sectors.
  * For each target, the catalog records `n_sectors`, the list of all available `sectors`, and cryptographic SHA-256 hashes for all associated sector FITS files.

---

## 3. Mandatory Exclusion Sources & Disjointness Assertions

Before finalizing and writing any target list, the selection pipeline MUST explicitly load all exclusion sources and assert zero overlap ($N_{\text{overlap}} = 0$):

1. **Burned IDs Exclusion (`benchmark_v2/burned_ids.txt`):**
   * Discards all targets evaluated or sampled during previous exploratory/discarded runs.
   * File SHA-256 Checksum: `b7c527cb982ac10a35b7a1f09c65bd6945f8f91455ce731de453bd4d9fdbcd08`
   * Line Count: `120` lines (120 burned TIC IDs).
   * *Per privacy and governance protocol, the raw burned IDs are maintained in `benchmark_v2/burned_ids.txt` (excluded from git tracking) and not listed in this document.*
2. **Development Benchmark Exclusion (`benchmark/targets.csv`):**
   * All 50 development benchmark targets ($28$ planets, $22$ non-planets) used for baseline tuning.
3. **Survey Footprint Exclusion (HD 10000–10744):**
   * All 745 stars within the exploratory and production survey range HD 10000 through HD 10744 cataloged in `astrohunter.db`, `master_discoveries.csv`, and exploratory logs.
4. **Mutual Set Disjointness:**
   * Strict separation between Set A and Set B: Set A $\cap$ Set B $= \emptyset$.

Any overlap detected during selection halts execution immediately with an assertion error.

---

## 4. Provenance & Cryptographic Integrity Standards

Every record in Benchmark v2 must satisfy strict provenance requirements:
* **Stellar Parameters:** Authentic stellar radius ($R_\star > 0$) and stellar mass ($M_\star > 0$) queried directly from TIC v8.2 (`IV/39/tic82`). Default, synthetic, or unverified values are forbidden.
* **Catalog Traceability:** Each row includes `catalog_id` (e.g., `TOI-xxx.xx`), `catalog_url` (canonical Exoplanet Archive / ExoFOP URL), and `source_catalog`.
* **Real Fetch Dates:** `source_date` must reflect the actual calendar date (`2026-10-24`) on which the FITS file was retrieved from the network.
* **Authentic Hashes:** SHA-256 checksums must be computed directly from the downloaded byte stream of each FITS file on disk. Copying hashes from previous records is strictly disallowed.
* **Network Transparency:** If any required FITS file cannot be retrieved from AWS S3 or MAST, the fetcher must halt and report the failure; it must never proceed with missing or placeholder data.

---

## 5. Verification Protocol

A committed, deterministic verification script (`benchmark_v2/verify_benchmark_v2.py` or equivalent) verifies:
1. Total unique TIC IDs across Set A and Set B.
2. Overlap checks:
   * Overlap with `burned_ids.txt` $= 0$.
   * Overlap with 50 dev targets (`benchmark/targets.csv`) $= 0$.
   * Overlap with HD 10000–10744 survey footprint $= 0$.
   * Overlap between Set A and Set B $= 0$.
3. Cryptographic hash validity (all `fits_sha256` are valid 64-character lowercase hexadecimal strings matching downloaded files).
4. Multi-sector constraint: Minimum $N_{\text{sectors}} \ge 2$ for all Set B targets.
