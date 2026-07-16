# Model Documentation

Two supervised models power the control tower, plus a transparent demand
forecast. All figures below are from a representative pipeline run (July
2026); dates anchor to run time, so exact values shift slightly per
regeneration. Reproduce with `python -m src.pipeline --force-data`;
metrics persist to `data/processed/models/*.json` and the `model_metrics`
table.

---

## 1. Prediction targets

| Model | Target | Type | Used for |
|---|---|---|---|
| Lead-time forecaster | `actual_lead_time_days` (order → delivery) | regression | predicted delivery dates for open POs; early warning vs supplier commitments |
| Delay-risk classifier | `missed_required_date` (arrival > required-on-site) | binary classification | delay probability, composite risk score, alert triage |

## 2. Feature engineering

All features are **knowable at PO creation time** (`src/transformation/features.py`):

- **Categorical:** equipment category, supplier, shipping mode, origin country
  (one-hot, unknown-safe).
- **Numeric:** order quantity, planned lead time, supplier capacity
  utilization, historical supplier delay rate, supplier OTD rate, inventory
  buffer days, supply concentration, criticality rank, alternative-supplier
  flag, origin congestion index, days-to-required at order, slack ratio
  (days-to-required ÷ planned lead), order month, constrained-category flag.

**Excluded to prevent target leakage:** `current_eta`,
`current_expected_lead_time_days`, `delay_days`, all statuses, actual dates,
and the generator's ground-truth arrival. `planned_lead_time_days` is a
legitimate feature — it is the plan agreed at order time; the models learn
deviations from it.

## 3. Data split — the censoring problem

Only delivered POs have outcomes, and delivered-only data is
**right-censored**: a PO ordered recently appears only if it delivered fast.
A naive time split therefore trains on the full delay distribution but tests
on survivors — in early iterations the models *lost to the naive baseline*
because of this shift.

**Fix — closed-window cohort:** train and test only on POs whose outcome
window has fully closed (`order_date + planned_lead + 120d ≤ today`), i.e.
even a 120-day delay would already be observed. Within the cohort the split
is **time-based** (last 4 months of order dates held out). Representative
cohort: ~316 train / ~145 test.

## 4. Lead-time forecasting

Candidates (scikit-learn pipelines, one-hot + passthrough/scaled numerics):

| Model | MAE (d) | RMSE (d) | R² |
|---|---|---|---|
| Naive — predict the plan | 26.5 | 41.0 | 0.47 |
| Ridge (linear baseline) | 17.8 | 23.6 | 0.82 |
| **Random Forest (selected)** | **17.0** | **22.3** | **0.84** |
| Hist Gradient Boosting | 17.6 | 23.8 | 0.82 |

Selection: lowest test MAE. The selected model cuts planning error by ~36%
vs trusting supplier-committed lead times. Top permutation-importance
features: planned lead time, supplier capacity utilization, category,
origin congestion, slack ratio.

## 5. Delay-risk classification

Candidates: Logistic Regression (interpretable) and HistGradientBoosting.
**Threshold policy:** missing a real infrastructure delay costs far more
than a false alarm, so the operating threshold is the highest cutoff whose
**worst cross-validation fold** achieves recall ≥ 0.85 on training data
(no test peeking). Selection: highest test ROC-AUC.

Representative test results (base rate ≈ 30%):

| Model | ROC-AUC | Precision | Recall | F1 | Threshold |
|---|---|---|---|---|---|
| **Logistic Regression (selected)** | **0.935** | 0.70 | **0.91** | 0.79 | 0.27 |
| Hist Gradient Boosting | 0.931 | 0.68 | 0.91 | 0.78 | 0.15 |

Confusion matrix (selected, test): TP 39 · FN 4 · FP 17 · TN 85 — the model
catches ~9 in 10 true delays at the cost of ~1 false alarm per 2 true calls,
an asymmetry chosen deliberately.

**Explainability.** The champion produces probabilities; a standardized
logistic model translates each PO's features into signed contributions.
Top positive contributions render as plain-English drivers, e.g.:

> **PO-1047 — delay probability 82%**
> - Supplier capacity utilization 93% — above stress threshold
> - InfiniBand Switches — supply-constrained category
> - Historical supplier delay rate 22% — above benchmark
> - Thin schedule slack: 28d to required date vs 140d planned lead
> - No qualified alternative supplier

**Composite risk score (0–100)** blends the probability with business
exposure — 45% delay probability, 25% schedule slack, 15% equipment
criticality, 15% supply flexibility (concentration + no-alternative) —
banded Critical ≥75 / High ≥55 / Moderate ≥35 / Low. Weights in
`config/settings.py`.

## 6. Demand forecast

Monthly ordered units per category form ≤18-point series, so the forecast is
a deliberately simple **linear trend with residual-based 80% intervals** —
an over-parameterized time-series model would be noise-fitting at this
length. Supply-gap analysis compares planned site demand against expected
deliveries from open POs (model-predicted delivery dates where available).

## 7. Limitations

1. **Censoring is inherent** to delivered-only training; the closed-window
   cohort mitigates but shrinks training data.
2. **Long-lead categories are sparse** in any closed cohort (transformer
   leads exceed the observable window) — their predictions extrapolate from
   shared features (supplier utilization, origin, quantities), not from many
   observed transformer outcomes.
3. **Synthetic-data ceiling:** the causal generator is the ground truth, so
   headline metrics flatter what real feeds would yield; the methodology
   (cohorting, recall-first thresholds, driver explanations) is the
   transferable part, not the AUC.
4. **No online learning or drift monitoring** — the pipeline retrains from
   scratch each run; production would add scheduled retraining with metric
   tracking and champion/challenger promotion.

## 8. Business interpretation

- Trusting supplier commitments alone leaves ~26 days of average planning
  error on this book; the forecaster cuts that to ~17 and, more usefully,
  flags **which specific POs** the plan is most wrong about — before the
  supplier revises an ETA.
- At the operating threshold, procurement reviews ~1.4 flagged POs for every
  true future miss, and ~91% of true misses surface with median multi-week
  warning — enough to expedite, re-route or re-sequence installs.
- The scenario page turns the same machinery into planning: e.g. a 30%
  InfiniBand lead-time shock immediately reprices the at-risk book and the
  site readiness picture.
