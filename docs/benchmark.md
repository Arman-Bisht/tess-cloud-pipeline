# Development Benchmark Evaluation & Protocol

## Benchmark Design & Scope

The development benchmark evaluates pipeline classification accuracy, sensitivity, and specificity across **50 real TESS targets** with published ground-truth dispositions:
* **28 Confirmed Transiting Planets:** Curated from the NASA Exoplanet Archive ($P \le 20.0\,\text{days}$, depths from $234\,\text{ppm}$ to $28,000\,\text{ppm}$).
* **22 Non-Planets:** Curated from the TESS Eclipsing Binary Catalog (Prša et al. 2022), false-positive TOIs (spectroscopic and centroid false positives), and variable stars.

Source metadata and parameters are cataloged in [`benchmark/targets.csv`](../benchmark/targets.csv) and results in [`benchmark/results.csv`](../benchmark/results.csv).

---

## 1. Headline Classification Metrics

Evaluated across the 50 development benchmark targets ($N = 50$, 28 planets, 22 non-planets):

| Metric | Count / Fraction | Value | 95% Wilson Score Interval |
| :--- | :---: | :---: | :---: |
| **Planet Recall (Sensitivity)** | $24 / 28$ | **85.7%** | [68.5%, 94.3%] |
| **Non-Planet Specificity** | $17 / 22$ | **77.3%** | [56.6%, 89.9%] |
| **Sample Precision (PPV)** | $24 / 29$ | **82.8%** | [65.5%, 92.4%] |
| **Overall Classification Accuracy** | $41 / 50$ | **82.0%** | [69.2%, 90.2%] |
| **Positive Likelihood Ratio ($LR+$)** | — | **3.77** | — |

*Benchmark Majority Baseline:* A trivial classifier predicting "planet" for all targets scores 56.0%.

---

## 2. Prevalence & The Blind Survey Regime Statement

The benchmark sample prevalence ($\pi = 28/50 = 56\%$) reflects a curated, roughly balanced test set. However, positive predictive value (precision) depends strongly on underlying true prevalence $\pi$:

$$\text{Precision}(\pi) = \frac{\text{TPR} \times \pi}{\text{TPR} \times \pi + \text{FPR} \times (1 - \pi)}$$

| Survey Regime | True Prevalence ($\pi$) | Precision (PPV) | Practical Interpretation |
| :--- | :---: | :---: | :--- |
| **Curated Benchmark** | $56.0\%$ | **82.8%** | Controlled test of pipeline discrimination |
| **Balanced Validation** | $50.0\%$ | **79.0%** | Standard ML evaluation benchmark |
| **Enriched TOI Follow-up** | $10.0\%$ | **29.5%** | Pre-filtered transit-like candidates |
| **Blind Field Survey** | **$2.0\%$** | **7.1%** | **Realistic untargeted field star survey** |

> **Scientific Regime Statement:** In an untargeted blind survey where true transiting planet occurrence among field stars is $\sim 1 - 2\%$, an automated positive trigger achieves an expected precision of only **$\approx 7.1\%$**. Consequently, automated Tier A candidates must be regarded strictly as prioritized candidate lists for multi-instrument follow-up, never as validated discoveries.

---

## 3. Tier Distribution & False-Positive Contamination

Cross-tabulation of true class against automated pipeline tier:

| True Classification | Tier A | Tier B | Tier C | Total |
| :--- | :---: | :---: | :---: | :---: |
| **PLANET** | 23 | 3 | 2 | 28 |
| **NON_PLANET** | 9 | 8 | 5 | 22 |
| **Total** | **32** | **11** | **7** | **50** |

### Tier A Reliability
Of the 32 targets assigned Tier A by automated gating, **9 are non-planets** (**28.1% false-positive contamination rate**).

The 9 non-planets passing automated Tier A checks:
1. **TOI 1292.01** (TIC 199688472): False-positive TOI.
2. **TOI 1370.01** (TIC 155114483): False-positive TOI.
3. **TOI 1423.01** (TIC 346418409): False-positive TOI.
4. **TOI 1615.01** (TIC 317507345): False-positive TOI.
5. **TOI 1637.01** (TIC 286355915): False-positive TOI.
6. **TOI 1645.01** (TIC 184679932): False-positive TOI.
7. **TESS-EB TIC 307990280**: Eclipsing binary from Prša et al. (2022).
8. **TESS-EB TIC 391906858**: Eclipsing binary from Prša et al. (2022).
9. **TESS-EB TIC 30313682**: Eclipsing binary from Prša et al. (2022).

These false positives passed automated centroid and depth checks because the photometric signals are either on-target eclipsing binaries (where centroid shifts are near zero) or subtle blends falling inside the $\sim 1\,\text{px}$ resolution limit.

---

## 4. Analysis of False Negatives (Planets Missed)

The pipeline produced 4 false negatives (confirmed planets not classified as `CANDIDATE_EXOPLANET`):

| Target | TIC ID | Catalog $P$ (d) | Catalog Depth (ppm) | Pipeline Category | Detected $P$ (d) | Cause of Miss |
| :--- | :--- | :---: | :---: | :--- | :---: | :--- |
| **TOI 1269.01** | TIC 201170701 | 8.0939 | 234 | `UNCLASSIFIED_PERIODIC_DIP` | 4.0487 | Period-halving harmonic alias ($P/2$) and shallow depth |
| **TOI 1478.01** | TIC 409794136 | 10.7766 | 6220 | `VARIABLE_STAR` | 0.9451 | Dominant stellar variability; transit not prioritized (cause not investigated) |
| **TOI 1670.01** | TIC 441739020 | 10.9844 | 990 | `ECLIPSING_BINARY` | 10.9846 | Classified as EB by automated vetting (cause not investigated) |
| **TOI 1749.01** | TIC 460205581 | 4.4928 | 610 | `ECLIPSING_BINARY` | 4.4930 | Classified as EB by automated vetting (cause not investigated) |

*Policy on Causal Claims:* Unless supported by a specific empirical test, causes for pipeline discrepancies are recorded as "not investigated".
