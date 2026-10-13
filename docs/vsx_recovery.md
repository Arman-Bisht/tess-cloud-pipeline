# AAVSO VSX Ground-Truth Variable Star Recovery

## Survey Footprint & Denominator

In the primary HD bright-star survey footprint (HD 10000 through HD 10729):
* **Total Scanned Stars:** 732 stars (497 observed in TESS 2-minute cadence, 235 with `NO_DATA`).
* **VSX Cross-Matches:** 34 stars match records in the AAVSO International Variable Star Index (VSX).
* **Stars with Published Periods:** **15 stars** have published catalog periods (19 stars have unmeasured periods in VSX, i.e., `NaN`).

---

## 1. Summary of Recovery Rates

| Regime | Catalog Filter | Recovered | Rate | 95% Wilson Score CI |
| :--- | :--- | :---: | :---: | :---: |
| **Unrestricted Published Periods** | All 15 published-period HD stars in survey footprint | 4 / 15 | **26.7%** | [10.9%, 52.0%] |
| **Search Grid Range** | $P \in [0.0333, 20.0]\,\text{d}$ ($f \le 30.0\,\text{d}^{-1}$) | 4 / 13 | **30.8%** | [12.7%, 57.6%] |
| **Single-Sector 3-Cycle Range** | $P \in [0.0333, 8.7]\,\text{d}$ ($N_{\text{cycles}} \ge 3.0$) | 4 / 12 | **33.3%** | [13.8%, 60.9%] |

### Excluded Targets by Grid Definition:
* **Excluded by Frequency Ceiling ($f > 30.0\,\text{d}^{-1}$):**
  * `HD 10676` ($P = 0.0146\,\text{d}$, frequency $68.5\,\text{d}^{-1}$): falls outside the Lomb-Scargle grid range ($f_{\max} = 30.0\,\text{d}^{-1}$, minimum period $48\,\text{min}$).
* **Excluded by Period Ceiling ($P > 20.0\,\text{d}$):**
  * `HD 10689` ($P = 218.37\,\text{d}$): exceeds the maximum pipeline search period of $20.0\,\text{days}$.
* **Excluded by Single-Sector 3-Cycle Rule ($P > 8.7\,\text{d}$):**
  * `HD 10516` ($P = 19.500\,\text{d}$): cannot satisfy the $N_{\text{cycles}} \ge 3.0$ transit requirement in a single 27.4-day sector.

---

## 2. Target-by-Target Ground-Truth Comparison Table

All 15 published-period HD survey stars:

| Target | Detected $P$ (d) | Catalog $P$ (d) | Ratio | VSX Type | Recovery Status | Notes on Discrepancy |
| :--- | :---: | :---: | :---: | :--- | :--- | :--- |
| **HD 10720** | **3.78442** | **3.7845** | **0.99998** | `EA` | **Recovered (Fundamental)** | Confirmed 0.002% period agreement (CF Hyi) |
| **HD 10502** | **0.0436** | **0.0436** | **1.0000** | `DSCTC` | **Recovered (Fundamental)** | Confirmed 62.8 min $\delta$ Scuti (HU Psc) |
| **HD 10081** | **0.7861** | **0.7852** | **1.0011** | `ACV` | **Recovered (Fundamental)** | Confirmed 0.11% period agreement (CD-68 66) |
| **HD 10040** | **0.6509** | **0.3258** | **1.9977** | `ESD\|EC` | **Recovered (Harmonic)** | Double-harmonic recovery of contact binary |
| **HD 10689** | 20.000 | 218.37 | 0.0916 | `MISC` | Not recovered | Exceeds pipeline search ceiling ($P_{\max} = 20.0\,\text{d}$) |
| **HD 10676** | 0.0469 | 0.0146 | 3.2123 | `VAR` | Not recovered | Catalog frequency ($68.5\,\text{d}^{-1}$) exceeds grid ceiling ($30\,\text{d}^{-1}$) |
| **HD 10516** | Unresolved | 19.500 | — | `GCAS` | Not recovered | Exceeds single-sector 3-cycle limit ($8.7\,\text{d}$) |
| **HD 10165** | 1.2807 | 1.3760 | 0.9307 | `VAR` | Mismatch | Cause not investigated |
| **HD 10260** | 5.0143 | 4.1257 | 1.2154 | `ROT` | Mismatch | Cause not investigated |
| **HD 10261** | 5.3253 | 0.9451 | 5.6346 | `MISC` | Mismatch | Cause not investigated |
| **HD 10293** | 4.0373 | 3.2187 | 1.2543 | `ROT` | Mismatch | Cause not investigated |
| **HD 10649** | 0.0488 | 0.0418 | 1.1675 | `PULS` | Mismatch | Cause not investigated |
| **HD 10655** | 4.8135 | 3.5474 | 1.3569 | `ROT` | Mismatch | Cause not investigated |
| **HD 10696** | 5.9591 | 2.6755 | 2.2273 | `VAR` | Mismatch | Cause not investigated |
| **HD 10560** | Unresolved | 3.2121 | — | `ACV:` | Not recovered | Cause not investigated |

---

## 3. External Instrument Control

* **WASP-126 b (`WASP-126`):**
  * Catalog transit period: $P = 3.2888\,\text{days}$.
  * Pipeline detected period: $P = 3.2889\,\text{days}$ ($1.0000\times$).
  * Maintained as an external photometric pipeline sanity control and strictly excluded from the HD survey denominator.
