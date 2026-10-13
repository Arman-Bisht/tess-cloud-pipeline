# Changelog

All notable changes to the `tess-cloud-pipeline` (Astrohunter Pro) project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.7.0] - 2026-10-12

### Added
- **50-Target Balanced External TESS Benchmark** (`benchmark/targets.csv` and `benchmark/results.csv`): 28 confirmed transiting exoplanets (16 TOI CP, 12 TOI KP) and 22 non-planets/false positives (13 TOI FP, 9 Prša et al. 2022 TESS EBs) strictly disjoint from the HD 10000–10730 tuning footprint.
- **TIC v8.2 Ground-Truth Provenance**: Populated authentic stellar radii and masses from TIC v8.2 (`VizieR IV/39/tic82`), with ExoFOP/VizieR URLs and catalog dates.
- **Automated S3/MAST Benchmark Fetcher** (`fetch_benchmark_data.py`): Downloads all 50 SPOC 2-minute FITS files directly from the STScI AWS Open Data S3 mirror (`stpubdata`) with MAST fallback.
- **Offline Benchmark Verification** (`verify_external_benchmark_results`): Validates confusion matrix, Wilson score confidence intervals, and majority-class baseline comparisons in CI without network downloads.
- **Cross-Platform Linux-Clean Lockfile** (`requirements-lock.txt`): Re-resolved 102 pure cross-platform packages with zero platform-specific or extraneous packages, verified on Ubuntu in CI.

### Changed
- Production-faithful blind evaluation (`is_known=False`) in `run_external_tess_benchmark`.
- Enforced hard `RuntimeError` guard if any benchmark target FITS file is missing (`n_evaluated < n_rows`).
- Replaced `ThreadPoolExecutor` worker with daemon `threading.Thread` in `run_target_with_watchdog` to eliminate process hangs during interpreter exit.

---

## [2.6.0] - 2026-10-12

### Added
- **Non-blocking per-target watchdog**: `shutdown(wait=False, cancel_futures=True)` with 30s socket/astroquery timeouts.
- **TPF significance gate**: 5σ spatial + 5σ temporal peak-box check returning `NOT_RUN` on signal-free TPFs.
- **Generic TIC lookup**: Replaced hardcoded dictionary with dynamic 16-digit zero-padded TIC cache resolution.

---

## [2.5.0] - 2026-10-10

### Added
- **Quadrature Phase Alignment for Variable Stars**: Peak-vs-trough difference imaging tested across cardinal phases (0, 0.25, 0.50, 0.75).
- **Per-Star Null Calibration**: Measured TPF photocenter offsets evaluated against star-specific injection null distributions.
- **Giant Rotation Speed Sanity Check** (`check_giant_rotation_sanity`): Flags unphysical implied equatorial speeds $v_{\text{eq}} > 35\,\text{km/s}$ on evolved giants ($R_\star \ge 5\,R_\odot$).
- Read-only `--offline` mode for `calibrate_tpf_threshold.py`.

### Changed
- Demoted `HD 10661` (measured TPF offset exceeds per-star null) and `HD 10669` (implied $v_{\text{eq}} = 81.5\,\text{km/s}$) to Tier B.

---

## [2.4.0] - 2026-10-10

### Added
- **Shared Production Detrender** (`detrend_lightcurve_production`): Shared between pipeline and synthetic injection-recovery harness on 2-minute cadence baselines.
- Single-transit TPF sector coverage guard: Returns `NOT_RUN` when dip epoch lacks TPF coverage.
- 40-target synthetic planet vs. false-positive regression benchmark.

---

## [2.3.0] - 2026-10-10

### Added
- `centroid_offset_px` column in master catalog.
- Reproducible TPF threshold calibration artifact (`tpf_threshold_calibration.json`).
- Full-pipeline completeness grid (750 simulations) and empirical false-alarm rate calibration (60 realizations).

---

## [2.2.0] - 2026-10-09

### Added
- Target Pixel File (TPF) difference-image centroiding engine for repeating transit and variable signals.
- Subgrid peak zooming and FWHM period uncertainty estimates ($\sigma_P$).

---

## [2.1.0] - 2026-10-08

### Added
- Physical Keplerian orbital separation check ($a > R_\star$).
- Transit crossing duration minimum check on giant hosts ($T_{\text{dur}} \ge T_{\text{cross, min}}$).
- Two-sample Welch standard error (SEM) centroid motion gating.

---

## [2.0.0] - 2026-10-08

### Added
- Box Least Squares (BLS) transit engine, Lomb-Scargle periodicity engine, Single-Transit outlier detector, and Microlensing detector.
- Multi-catalog cross-referencing (AAVSO VSX, SIMBAD, NASA Exoplanet Archive, TESS-EB, Gaia DR3).
- 5-panel scientific diagnostic plot generation.

---

## [1.0.0] - 2026-10-07

### Added
- Initial pipeline prototype for ingestion and basic detrending of NASA TESS light curves.
