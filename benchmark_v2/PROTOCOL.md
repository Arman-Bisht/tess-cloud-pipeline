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

---

## 6. Amendment (2026-10-24)

To ensure balanced and unambiguous representation among non-planetary signals, the non-planet cohort in each benchmark set ($N = 30$ per set) is strictly stratified as:
* **Exactly 15 TOI False Positives (`TOI_FP`):** Selected across diverse false positive mechanisms (centroid offsets, spectroscopic binaries, stellar activity/background blends) from the NASA Exoplanet Archive TOI catalog.
* **Exactly 15 Confirmed Eclipsing Binaries (`PRSA_EB`):** Selected from the Prša et al. (2022) TESS Eclipsing Binary Catalog (HLSP TESS-EB / VizieR J/ApJS/258/16).

All protocol rules apply uniformly to these subsets:
* Period constraints: Set A $P \le 8.7\,\text{d}$ for all rows; Set B $8.7 < P \le 20.0\,\text{d}$ for all rows.
* Multi-sector constraint: Set B targets must have $N_{\text{sectors}} \ge 2$ SPOC 2-minute cadence observation sectors.
* Brightness constraint: $T_{\text{mag}} \le 13.0$ for all targets.
* Stellar parameters: Authentic $R_\star > 0, M_\star > 0$ from TIC v8.2.
* Disjointness: Zero overlap with `burned_ids.txt`, `benchmark/targets.csv`, HD 10000–10744 survey footprint, and mutual disjointness (Set A $\cap$ Set B $= \emptyset$).

---

## 7. Amendment: Multi-Planet Hosts & Granular Recall/Specificity Protocols (2026-10-31)

### (a) Multi-Planet Columns & Reference Catalog Provenance
To rigorously evaluate pipeline behavior in multi-transiting exoplanet systems and multi-signal host architectures, two dedicated provenance columns are incorporated into `targets_set_a.csv` and `targets_set_b.csv`:
* **`n_tois_on_host`:** Non-negative integer indicating the total count of TOIs associated with the target host star (`tic_id`) in the NASA Exoplanet Archive TOI reference table. Stars not indexed in the TOI table (e.g. standalone Prša et al. 2022 EBs) have `n_tois_on_host = 0`.
* **`sibling_periods`:** Semicolon-delimited string of orbital periods (in days) for all other TOIs on the same host star (excluding the target's own catalog period, and omitting entries with undefined/NaN periods). If the host star has only a single TOI (`n_tois_on_host <= 1`) or is not a TOI target, `sibling_periods` is an empty string (`""`).

These columns are constructed deterministically from the user-provided canonical NASA Exoplanet Archive TOI table:
* **Reference Table File:** `D:\exo_planet\toi_nasa.csv`
* **Download Date:** `2026-10-31`
* **Cryptographic SHA-256 Checksum:** `c42771b98de943da7103d1b10accbf7b2cfac3288ed2cbc241593d59c27e1c28`

### (b) Strict and Sibling-Aware Recall Definitions
Planetary signal recovery (`true_class == 'PLANET'`, $N = 30$ in Set A, $N = 30$ in Set B) is evaluated under two explicit protocols:
1. **Strict Recall:** A planet is recalled if and only if the top detected transit period $P_{\text{det}}$ matches the target's pre-registered catalog period $P_{\text{cat}}$ within standard period tolerance ($|\Delta P / P_{\text{cat}}| \le 1.0\%$, including direct harmonic matching at $P/2$ or $2P$), and passes all pipeline vetting criteria.
2. **Sibling-Aware Recall:** On multi-planet host stars (`n_tois_on_host > 1`), if the pipeline's primary detection instead matches one of the documented sibling planets in the same system (matching any period in `sibling_periods` within $|\Delta P / P_{\text{sib}}| \le 1.0\%$) and passes vetting as a planet candidate, the detection is credited as valid under sibling-aware recall. This accounts for astrophysical competition where a sibling planet exhibits higher signal-to-noise or shorter period, dominating the primary BLS peak.

### (c) Specificity With and Without Non-Planet Rows on Hosts With Other TOIs
Rejection performance (`true_class == 'NON_PLANET'`, $N = 30$ in Set A, $N = 30$ in Set B) is evaluated under two distinct scopes:
1. **Overall Specificity:** Evaluated across all 30 non-planetary targets per set (15 `TOI_FP` + 15 `PRSA_EB`). A target passes specificity if the pipeline rejects the signal (classifies as non-planet / false alarm / eclipsing binary).
2. **Isolated-Host Specificity (excluding hosts with other TOIs):** Evaluated after excluding non-planet targets that reside on host stars possessing other documented TOIs (`n_tois_on_host > 1` for `TOI_FP`, or `n_tois_on_host > 0` for `PRSA_EB`). Specifically:
   * In Set B, `TOI 2448.01` (`TOI_FP`, TIC 231721005) shares its host with planetary candidate `TOI 2448.02` ($P = 19.757918\,\text{d}$).
   * In addition, three eclipsing binary hosts (`TESS-EB TIC 313506357` in Set A; `TESS-EB TIC 260128333` and `TESS-EB TIC 308050066` in Set B) have associated TOI entries.
   Reporting specificity both across the full cohort and restricted to isolated hosts ensures transparent diagnostics: genuine planet detections on multi-signal hosts are not conflated with false-positive vetting failures.

### (d) Expected-Recall Statement
Set B evaluates challenging long-period and shallow-transit observational regimes:
* **15 of 30 Set B planets** feature shallow transit depths under 1,000 ppm ($< 1000\,\text{ppm}$).
* **4 of 30 Set B planets** feature orbital periods $P > \sim 17.4\,\text{days}$ (`TOI 1055.01` at $17.47\,\text{d}$, `TOI 3362.01` at $18.10\,\text{d}$, `TOI 560.02` at $18.88\,\text{d}$, and `TOI 5065.01` at $19.49\,\text{d}$).
Within 2-sector SPOC observations (effective baseline 27–54 days), orbital periods near 17–20 days yield only 2 to 3 transit events, while sub-1,000 ppm signals approach the photometric noise floor of TESS. Benchmark recall on Set B is naturally constrained by these observational physical limits, establishing a realistic sensitivity baseline.

### (e) Evaluation Reporting Mandate
The final held-out benchmark evaluation (WP8) will explicitly report all of the following:
1. Strict Recall (Set A, Set B, and Combined).
2. Sibling-Aware Recall (Set A, Set B, and Combined).
3. Overall Specificity (Set A, Set B, and Combined).
4. Isolated-Host Specificity (excluding non-planet targets on hosts with other TOIs).
5. Granular recall broken down by transit depth bins ($< 1000\,\text{ppm}$, $1000\text{–}2500\,\text{ppm}$, $> 2500\,\text{ppm}$) and orbital period bins.

---

## 8. Amendment: Credited Sibling Periods & Period Matching Pre-Registration (2026-11-02)

### (a) Credited Sibling Periods & Non-Confirmed Dispositions
To prevent false-alarm credits in multi-planet recall assessment, sibling signals are strictly partitioned by their confirmation status in the reference catalog (`benchmark_v2/reference/toi_nasa_2026-10-31.csv`):
* **`sibling_dispositions`:** Semicolon-delimited list recording the TFOPWG disposition of each sibling in `sibling_periods` in identical order (e.g. `CP;PC` or `KP;KP`).
* **`credited_sibling_periods`:** Semicolon-delimited list containing **ONLY** siblings whose TFOPWG disposition is confirmed planet (`CP`) or known planet (`KP`).
* **Non-Credited Dispositions:** Sibling entries classified as Planet Candidate (`PC`), Ambiguous Planet Candidate (`APC`), False Alarm (`FA`), or False Positive (`FP`) are cataloged in `sibling_periods` and `sibling_dispositions` for full observational transparency, but are **never** included in `credited_sibling_periods` and cannot credit a detection toward recall. Specifically:
  * In Set A, `TOI 1782.02` records sibling `TOI 1782.03` (`PC`, $18.7559765\,\text{d}$), which is uncredited; only `TOI 1782.01` (`CP`, $4.9877056\,\text{d}$) is credited.
  * In Set B, `TOI 712.01` records sibling `TOI 712.03` (`FA`, $53.746482\,\text{d}$), which is uncredited; `TOI 1670.02` records sibling `TOI 1670.03` (`PC`, $123.050751\,\text{d}$), which is uncredited; and `TOI 2081.01` records sibling `TOI 2081.02` (`PC`, $5.1096561\,\text{d}$), yielding an empty credited list.
  * `TOI 2448.01` (`TOI_FP`) records sibling candidate `TOI 2448.02` (`PC`, $19.757918\,\text{d}$), yielding an empty credited list.
  * `TOI 2319.02` (`TOI_KP`) has sibling `TOI 2319.01` classified as `CP`, but because `TOI 2319.01` has no orbital period recorded in the reference table (`pl_orbper` is NaN/null), it receives an empty credited list (`""`).

### (b) Pre-Registered Sibling-Aware Recall Definition
Sibling-aware recall is formally defined as:
* A planetary target (`true_class == 'PLANET'`) is successfully recalled if and only if the primary detected period $P_{\text{det}}$ matches either:
  1. The target's pre-registered catalog period $P_{\text{cat}}$ within the primary period tolerance ($|\Delta P / P_{\text{cat}}| \le 1.0\%$, including direct harmonic matching at $P/2$ or $2P$), **OR**
  2. Any orbital period explicitly listed in `credited_sibling_periods` within the same tolerance ($|\Delta P / P_{\text{cred}}| \le 1.0\%$, including $P/2$ or $2P$),
  AND the signal satisfies all pipeline vetting criteria. Matches to unconfirmed (`PC`, `APC`) or spurious (`FA`, `FP`) siblings receive zero recall credit.

### (c) Specificity "With" and "Without" Hosts Bearing Any Other TOI
Specificity evaluates the rejection of non-planetary targets (`true_class == 'NON_PLANET'`, $N = 30$ in Set A, $N = 30$ in Set B):
* **Specificity "With" (Overall):** Evaluated across all 30 non-planet targets per set (15 `TOI_FP` + 15 `PRSA_EB`). A target passes specificity if the pipeline rejects the candidate (classifies as non-planet / false alarm / eclipsing binary).
* **Specificity "Without" (Isolated Hosts):** Evaluated after excluding non-planet targets residing on any host star cataloged with any other TOI in the reference catalog (`n_tois_on_host > 1` for `TOI_FP`, or `n_tois_on_host > 0` for `PRSA_EB`).
  * In Set B, this excludes `TOI 2448.01` (`TOI_FP` with candidate sibling `TOI 2448.02`), `TESS-EB TIC 260128333` (EB host with `TOI 1338.01`), and `TESS-EB TIC 308050066` (EB host with `TOI 679.01`).
  * In Set A, this excludes `TESS-EB TIC 313506357` (EB host with `TOI 1383.01`).
  This dual reporting isolates true classifier rejection accuracy from cases where a pipeline detects a genuine astrophysical planet or candidate on a multi-signal host.

### (d) Pre-Registration of Period Matching Window: 1.0% Primary vs. 2.0% Sensitivity Analysis
* **Primary Metric (1.0% Tolerance):** High-precision SPOC 2-minute cadence data over 27- to 54-day baselines yields typical period determination accuracy within $\pm 0.1\%\text{--}0.5\%$ for bona fide planetary transits. A tight 1.0% window (with $P/2$ and $2P$ harmonics) is pre-registered as the primary matching standard to minimize accidental matches to stellar rotation, instrumental quasi-periodicities, or unrelated signals.
* **Secondary Sensitivity Analysis (2.0% Tolerance):** While the earlier development benchmark (`benchmark/targets.csv`) employed a wider 2.0% window during preliminary heuristic tuning, Benchmark v2 mandates 1.0% as the primary pre-registered standard. To ensure direct continuity and backwards comparability with development benchmark publications, the held-out evaluation in WP8 will also report performance under 2.0% tolerance as a formal sensitivity analysis.
