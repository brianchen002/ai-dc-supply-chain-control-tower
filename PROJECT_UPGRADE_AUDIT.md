# Project Upgrade Audit

**From:** OpsPilot — AI-Enabled Supply Chain Operations Copilot (B2B distributor
fulfillment prototype, Streamlit + SQLite + pluggable LLM)
**To:** AI Data Center Supply Chain Control Tower — Automated PO Tracking,
Lead-Time Forecasting, and Supply Risk Intelligence

This document records what was retained, modified, added and fixed in the
upgrade, per the upgrade brief. The predecessor's product documentation is
preserved under `docs/archive/opspilot/`.

---

## 1. Existing features retained (reused directly or with minor edits)

| Asset | Where it lives now | Notes |
|---|---|---|
| Pluggable LLM client (Anthropic API ⇄ deterministic offline fallback, Streamlit-secrets aware) | `src/llm/client.py` | Reused nearly verbatim — one import path change. The "LLM narrates, rules decide" contract carries over. |
| Mount-safe SQLite loader (build in temp file, byte-copy over destination; env-overridable DB path) | `src/db.py` | Pattern retained; rewritten around `DataFrame.to_sql`. |
| Config-as-single-source-of-truth (every business constant in one module, doc-code sync convention) | `config/settings.py` | Expanded from ~20 constants to the full causal-generation, scoring and modeling parameter set. |
| Synthetic-data architecture: seeded, causal, state-derived issues (never hardcoded outcomes) | `src/data_generation/generate.py` | The single most valuable carry-over. OpsPilot derived *exceptions* from state; the control tower derives *delays and risk labels* from a ground-truth causal process the ML models must rediscover. |
| Self-consistency test philosophy (assert the data's causality and the outputs' integrity, not just "it runs") | `tests/test_pipeline.py` | 26 checks, same style as OpsPilot's 22. |
| Streamlit multi-page app structure, theming, sidebar dataset panel, AI-mode badge, synthetic-data disclaimer | `dashboard/` + `.streamlit/config.toml` | Layout patterns and theme retained; every page rebuilt for the new domain. |
| Repo hygiene: MIT license, .gitignore, README conventions | root | Retained and updated. |

## 2. Existing features modified (same idea, new domain)

- **Explainable 0–100 scoring.** OpsPilot's fulfillment priority score
  (weighted, component-decomposable) became the composite **PO risk score**
  (45% model delay probability · 25% schedule slack · 15% criticality ·
  15% supply flexibility). The principle — no black-box rankings — is
  unchanged; the inputs now include an ML probability.
- **Exception engine → alert engine.** State-derived exception detection
  became `src/alerts/engine.py`: alerts exist because a data condition is true
  (critical model risk, ETA slip, site readiness, supplier deterioration,
  concentration), now with explicit anti-fatigue gating (value/time gates,
  top-N caps).
- **LLM workflows.** OpsPilot's daily digest → **executive brief**; per-exception
  recommendations → **per-PO supplier-call narrative**. Same offline/live dual
  path; the SOP-RAG Q&A workflow was dropped (no SOP corpus in this domain).
- **Recommended actions.** The rule-ladder recommendation engine was rebuilt
  for procurement levers (expedite, ocean→air, alternative-supplier
  qualification, pull-in, schedule re-sequencing).

## 3. New functionality added

1. **ML lead-time forecasting** (`src/forecasting/leadtime_model.py`) — Ridge /
   Random Forest / HistGradientBoosting compared against a naive
   planned-lead baseline; MAE/RMSE/MAPE/R²; permutation importance;
   predictions for every open PO.
2. **ML delay-risk classification** (`src/risk_model/delay_model.py`) —
   logistic + gradient boosting, recall-first threshold policy, calibrated
   0–100 risk score, and **per-PO plain-English risk drivers** from
   standardized logistic contributions.
3. **Automated modular ETL pipeline** (`src/pipeline.py`) — generation →
   validation → feature engineering → two models → scoring → recommendations →
   aggregates → SQLite → alerts, one command, ~6s.
4. **Data validation stage** (`src/validation/checks.py`) with a written
   JSON report and hard pipeline failure on contract breaks.
5. **Supplier intelligence** — scorecard (6 dimensions + overall risk score)
   and an exposure × performance risk matrix.
6. **Infrastructure readiness** — per-site readiness score linking supply
   chain state to deployment schedules, with schedule-impact estimates.
7. **Demand forecasting & supply-gap analysis** — trend forecast with
   confidence intervals; planned demand vs confirmed inbound supply by
   category/site/month.
8. **Interactive scenario analysis** — seven levers (IB lead times,
   transformer capacity, GPU demand growth, global lead times, air-freight
   conversion, second-source qualification, safety buffer) with before/after
   risk, exposure and shortage deltas.
9. **Model documentation and a training notebook** (`MODEL_DOCUMENTATION.md`,
   `notebooks/model_development.ipynb`, executed with outputs).

## 4. Technical weaknesses corrected during the upgrade

- **Survivorship/censoring leakage in model evaluation.** Delivered-only
  training data is right-censored (recent orders appear only if they delivered
  fast). First-pass models *lost to the naive baseline* on a naive split.
  Fixed with a **closed-window cohort**: train/test restricted to POs whose
  outcome window (planned lead + 120d) has fully closed, then split by time.
- **Threshold overfitting.** A pooled CV recall target produced thresholds
  that missed the recall floor on the time-shifted test set. Fixed with a
  **worst-fold recall criterion** (every CV fold must clear the floor).
- **Alert fatigue by construction.** Ungated alerting produced 390–519 alerts.
  Fixed with materiality gates (value, time-to-required) and top-N caps
  (~150 alerts on a representative run).
- **Weak regression signal.** Initially delay *magnitude* was mostly noise, so
  lead-time models couldn't beat the plan. The generator now extends delay
  duration under stress (utilization, congestion, constrained categories) —
  matching reality and giving the regressor honest signal.
- **Uniform site risk.** Sites originally drew identical PO risk mixes;
  per-site schedule tightness now produces a meaningful readiness spread.

## 5. Remaining limitations

- **Synthetic data.** Causally consistent but cleaner than reality: no data
  entry errors, no supplier communication lag, no partial shipments/splits,
  no currency movements. A production deployment would revalidate detection
  precision against historical data first (the archived OpsPilot pilot plan's
  phase-0 replay pattern applies directly).
- **Long-lead sparsity.** Transformers/generators rarely close their outcome
  window inside an 18-month history, so they are underrepresented in model
  training; their predictions are partially extrapolated (flagged in
  MODEL_DOCUMENTATION §7).
- **Scenario engine is an approximation** — documented logit/ETA adjustments
  over model outputs, not a pipeline re-run.
- **No write-back or user auth.** The platform recommends; execution and
  role-based access remain out of scope, as in the predecessor.
- **Batch, not streaming.** The pipeline is a one-command batch; production
  would ingest OMS/ERP/carrier webhooks incrementally.
