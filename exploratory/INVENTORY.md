# Exploratory Scan Outputs Inventory & Quarantine Log

**Status:** Quarantined & Archived  
**Date Logged:** 2026-10-13  
**Policy:** All files and rows cataloged herein are strictly **exploratory, not validated**. Under no circumstances do these exploratory data feed into any benchmark, threshold tuning, or candidate submission set.

---

## 1. Provenance & Execution Record

* **Execution Command:** `python main.py --scan --start 10730 --count 15`
* **Execution Timestamp:** 2026-10-12 15:12 UTC – 15:42 UTC
* **Pipeline Version:** `v2.7.0`
* **Git SHA at Execution:** `dfd223a` (subsequently amended to `52b6bb8` to include the daemon-thread watchdog fix, tagged as `v2.7.0-dev-frozen`)
* **Survey Range Scanned:** HD 10730 through HD 10744 (15 targets evaluated)
  * Stars with TESS observations: 12
  * Pipeline rejections (`FALSE_POSITIVE`): 7 targets (HD 10730, 10731, 10734, 10735, 10736, 10737, 10740, 10742)
  * Transient download/network timeouts (`DOWNLOAD_ERROR`): 3 targets (HD 10732, 10738, 10743)
  * Candidate signals identified: 5 targets

---

## 2. Answers to Specific Review Questions

### Question 1: What was the "ad-hoc exploratory run" previously reverted in `master_discoveries.csv`?
During the live test of the scanning script in the previous turn, the command `python main.py --scan --start 10730 --count 15` was executed to verify that continuous scanning operates on workstation hardware. When `main.py` finished scanning HD 10730–10744, `save_discovery()` automatically appended 5 candidate rows to `master_discoveries.csv`. Because CI (`.github/workflows/ci.yml` line 49) explicitly asserts `assert len(df) == 34` (the 34 surveyed records for HD 10000–10729 forming the v2.7.0 frozen baseline), those 5 exploratory candidate rows were reverted from `master_discoveries.csv` so the repository remained on its clean baseline.

### Question 2: Which command produced it?
The command was:
```powershell
python main.py --scan --start 10730 --count 15
```

### Question 3: Did the revert lose any data?
**No data was lost.**
1. All 15 target scan records and all 5 signal records remain stored in the local SQLite database `astrohunter.db` (in the `targets` table and `signals` table, IDs 410 through 414).
2. All 5-panel diagnostic plots generated during that run were copied to the project directory and are quarantined below.
3. The exact 5 candidate rows are exported and archived in `exploratory/2026-10-13/exploratory_candidates_hd10730_10744.csv`.
4. `master_discoveries.csv` retains its 34 audited records matching `v2.7.0-dev-frozen` commit `52b6bb8`.

---

## 3. Database State (`astrohunter.db`)

* **Total rows in `targets`:** 747
  * HD 10000–10729 baseline: 732 targets
  * HD 10730–10744 exploratory scan: 15 targets
* **Total rows in `signals`:** 39
  * HD 10000–10729 baseline: 34 records
  * HD 10730–10744 exploratory scan: 5 records (IDs 410 to 414)

### Breakdown of the 5 Exploratory Candidates (Exploratory, Not Validated)

| Star | TIC ID | Period | Depth / Amp | SDE | Centroid Status | Initial Tier | Exploratory Classification Label | Notes |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| **HD 10732** | `HD 10732` | `Single` | $2.28\%$ | 19.1 | `PASS` ($0.27\,\text{px}$) | Tier A | `UNLISTED_NEEDS_VETTING_SINGLE_TRANSIT_CANDIDATE` | *Exploratory, not validated.* Inspection of diagnostic plot shows dip driven by 2 outlier cadences. |
| **HD 10733** | `HD 10733` | $5.08987\,\text{d}$ | $0.44\%$ amp | 70.4 | `PASS` ($0.64\,\text{px}$) | Tier A | `POSSIBLE_NEIGHBOR_NEEDS_REVIEW` | *Exploratory, not validated.* High-SDE sinusoidal modulation across 10 sectors; nearby VSX variable within $60''$. |
| **HD 10739** | `HD 10739` | $0.64350\,\text{d}$ | $20\,\text{ppm}$ | 12.4 | `PASS_MARGINAL` ($0.99\,\text{px}$) | Tier B | `UNLISTED_NEEDS_VETTING_CANDIDATE_EXOPLANET` | *Exploratory, not validated.* Visual binary (`** F5V`), marginal offset, missing Gaia DR3 parameters. |
| **HD 10741** | `HD 10741` | $17.82027\,\text{d}$ | $9.04\%$ | 10.6 | `NOT_RUN` | Tier B | `UNLISTED_NEEDS_VETTING_ECLIPSING_BINARY` | *Exploratory, not validated.* Eclipsing binary candidate across 3 sectors ($N_{\text{cycles}} = 4.3$). |
| **HD 10744** | `HD 10744` | $0.63024\,\text{d}$ | $120\,\text{ppm}$ | 9.1 | `FAIL` ($104.1\sigma$) | Tier C | `UNLISTED_NEEDS_VETTING_UNCLASSIFIED_PERIODIC_DIP` | *Exploratory, not validated.* Rejected: inside host star envelope ($a \le R_\star$) and severe photocenter shift. |

---

## 4. Quarantined Files & SHA-256 Checksums

The following files are quarantined in `exploratory/2026-10-13/`:

| Quarantined Path | SHA-256 Checksum | Description |
| :--- | :--- | :--- |
| `2026-10-13/astrohunter.db` | `79924c0af94b0231ad896d2b169bd88fc037c674b7115ab3df639771dc650af3` | Snapshot of SQLite state with 747 targets and 39 signals |
| `2026-10-13/exploratory_candidates_hd10730_10744.csv` | `7b9e885be7ae25d9547932baee50b5c5d313091607ca586afca8ecb1ba188c4d` | CSV export of the 5 exploratory candidate rows |
| `2026-10-13/plots/HD_10732_UNLISTED_NEEDS_VETTING_SINGLE_TRANSIT_CANDIDATE_5panel.png` | `fc0f2d3c9bf6d2bae56defc006be808d3954be864d2914a3d901ca52ffc695db` | 5-panel plot for HD 10732 exploratory candidate |
| `2026-10-13/plots/HD_10733_POSSIBLE_NEIGHBOR_NEEDS_REVIEW_5panel.png` | `9a15cbd29d40c2294d629ca1cbf7d2590b431bef8fa34522439387b6f292712d` | 5-panel plot for HD 10733 exploratory candidate |
| `2026-10-13/plots/HD_10739_UNLISTED_NEEDS_VETTING_CANDIDATE_EXOPLANET_5panel.png` | `b99aa91fd3a10b090f6f49a5f81d9bc4e797e1952b58c85524ca121a9f0a917c` | 5-panel plot for HD 10739 exploratory candidate |
| `2026-10-13/plots/HD_10741_UNLISTED_NEEDS_VETTING_ECLIPSING_BINARY_5panel.png` | `6574b62e1d2ec66221f51ce18600e8885db09a11e60ef3a57385560577a39b5e` | 5-panel plot for HD 10741 exploratory candidate |
| `2026-10-13/plots/HD_10744_UNLISTED_NEEDS_VETTING_UNCLASSIFIED_PERIODIC_DIP_5panel.png` | `6f775bfd36ba633d0807b0d8fb4b979acd04ab25e64ef6cba86afebf2344479e` | 5-panel plot for HD 10744 exploratory candidate |
| `2026-10-13/plots/HD_TEST_SINGLE_SINGLE_TRANSIT_CANDIDATE_5panel.png` | `032d8015d79164e4c0f7409b620e3f651c6b8c789b490b01ef7e16d5f4a56715` | Diagnostic plot generated during pipeline testing |
| `2026-10-13/plots/test_alert.png` | `0e3f8ecd1291e1bd1462e71c076ef0a9007b75cc00a6b336414bfd6befb542de` | Diagnostic plot generated by test_alert.py |
