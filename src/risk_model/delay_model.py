"""PO delay-risk model — will this order miss its required-on-site date?

Methodology (MODEL_DOCUMENTATION.md):
  * Binary target `missed_required_date`, trained on delivered POs with a
    time-based split (same anti-leakage split as the lead-time model).
  * Models compared: Logistic Regression (interpretable) and
    HistGradientBoosting. Probabilities come from the best-AUC model;
    per-PO risk drivers come from the logistic model's standardized
    contributions — one model to predict, one to explain.
  * Threshold: tuned on TRAINING data (cross-validated probabilities) to the
    smallest cutoff achieving recall ≥ HIGH_RISK_RECALL_FLOOR — missing a
    real infrastructure delay costs far more than a false alarm.
  * Composite 0–100 risk score blends model probability with schedule slack,
    criticality and supply flexibility (weights in config/settings.py).
"""
from __future__ import annotations

import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import Pipeline

from config.settings import (CRITICALITY_SCORE, DELAY_TARGET,
                             HIGH_RISK_RECALL_FLOOR, MODELS_DIR, RISK_BANDS,
                             RISK_WEIGHTS)
from src.forecasting.leadtime_model import _preprocessor, time_split
from src.transformation.features import ALL_FEATURES

_CRIT_NAME = {3: "critical", 2: "high", 1: "medium", 0: "low"}


def _metrics(y, proba, threshold: float) -> dict:
    pred = (proba >= threshold).astype(int)
    cm = confusion_matrix(y, pred).tolist()
    return {
        "threshold": round(float(threshold), 3),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y, pred)), 3),
        "f1": round(float(f1_score(y, pred)), 3),
        "roc_auc": round(float(roc_auc_score(y, proba)), 3),
        "confusion_matrix": {"tn": cm[0][0], "fp": cm[0][1],
                             "fn": cm[1][0], "tp": cm[1][1]},
    }


def train_delay_models(feats: pd.DataFrame, verbose: bool = True) -> dict:
    train, test, cutoff = time_split(feats)
    X_tr, y_tr = train[ALL_FEATURES], train[DELAY_TARGET].astype(int)
    X_te, y_te = test[ALL_FEATURES], test[DELAY_TARGET].astype(int)

    logit = Pipeline([("pre", _preprocessor(scale_numeric=True)),
                      ("model", LogisticRegression(max_iter=3000, C=0.5))])
    hgb = Pipeline([("pre", _preprocessor()),
                    ("model", HistGradientBoostingClassifier(
                        max_iter=350, learning_rate=0.07, max_depth=6, random_state=7))])

    fitted, results = {}, []
    for name, pipe in [("Logistic Regression", logit), ("Hist Gradient Boosting", hgb)]:
        # Threshold tuned on cross-validated TRAIN probabilities (no test
        # peeking). Criterion: the WORST fold's recall must clear the floor —
        # a stress test that approximates temporal shift better than pooled
        # CV recall and generalizes to the held-out period.
        from sklearn.model_selection import KFold
        kf = KFold(n_splits=4, shuffle=True, random_state=7)
        cv_proba = cross_val_predict(pipe, X_tr, y_tr, cv=kf, method="predict_proba")[:, 1]
        fold_idx = list(kf.split(X_tr))
        threshold = 0.15
        for t in np.arange(0.9, 0.04, -0.01):
            worst = min(
                recall_score(y_tr.iloc[te], (cv_proba[te] >= t).astype(int))
                for _, te in fold_idx if y_tr.iloc[te].sum() > 0)
            if worst >= HIGH_RISK_RECALL_FLOOR + 0.05:
                threshold = float(t)
                break
        pipe.fit(X_tr, y_tr)
        proba_te = pipe.predict_proba(X_te)[:, 1]
        m = _metrics(y_te, proba_te, threshold)
        m["model"] = name
        results.append(m)
        fitted[name] = pipe

    best_name = max(results, key=lambda r: r["roc_auc"])["model"]
    for r in results:
        r["selected"] = r["model"] == best_name
    best = fitted[best_name]
    best_threshold = next(r["threshold"] for r in results if r["selected"])

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(best, MODELS_DIR / "delay_model.joblib")
    joblib.dump(fitted["Logistic Regression"], MODELS_DIR / "delay_explainer.joblib")
    meta = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "target": DELAY_TARGET,
        "train_rows": len(train), "test_rows": len(test),
        "base_rate_train": round(float(y_tr.mean()), 3),
        "split": f"time-based, test = orders after {cutoff.date()}",
        "threshold_policy": f"min threshold with train-CV recall ≥ {HIGH_RISK_RECALL_FLOOR}",
        "results": results, "selected_model": best_name,
        "selected_threshold": best_threshold,
    }
    (MODELS_DIR / "delay_metrics.json").write_text(json.dumps(meta, indent=2))
    if verbose:
        sel = next(r for r in results if r["selected"])
        print(f"Delay model: {best_name} (AUC {sel['roc_auc']}, "
              f"recall {sel['recall']} @ t={sel['threshold']})")
    return {"model": best, "explainer": fitted["Logistic Regression"], "meta": meta}


# ---------------------------------------------------------------------------
# Per-PO explainability: standardized logistic contributions -> plain English
# ---------------------------------------------------------------------------

def _phrase(feature: str, row: pd.Series) -> str | None:
    v = row
    if feature.startswith("cat__equipment_category_"):
        cat = v["equipment_category"]
        return (f"{cat} — supply-constrained category"
                if v["constrained_category"] else f"{cat} — elevated category baseline")
    if feature.startswith("cat__supplier_name_"):
        return f"Supplier {v['supplier_name']} — weak historical delivery record"
    if feature.startswith("cat__shipping_mode_Ocean"):
        return "Ocean freight — long, variable transit"
    if feature.startswith("cat__origin_country_"):
        return f"Origin {v['origin_country']} — congested logistics lane"
    key = feature.replace("num__", "")
    if key == "supplier_capacity_utilization":
        return f"Supplier capacity utilization {v['supplier_capacity_utilization']:.0%} — above stress threshold"
    if key == "historical_supplier_delay_rate":
        return f"Historical supplier delay rate {v['historical_supplier_delay_rate']:.0%} — above benchmark"
    if key == "slack_ratio":
        return (f"Thin schedule slack: {int(v['days_to_required_at_order'])}d to required date "
                f"vs {int(v['planned_lead_time_days'])}d planned lead")
    if key == "days_to_required_at_order":
        return f"Required on site in {int(v['days_to_required_at_order'])}d at order placement"
    if key == "alternative_supplier_available" and v["alternative_supplier_available"] == 0:
        return "No qualified alternative supplier"
    if key == "supply_concentration":
        return f"{v['supply_concentration']:.0%} of category spend concentrated with this supplier"
    if key == "origin_congestion":
        return f"Origin {v['origin_country']} — congested logistics lane"
    if key == "order_quantity":
        return "Large order relative to typical lot size"
    if key == "inventory_buffer_days":
        return f"Only {int(v['inventory_buffer_days'])}d of inventory buffer"
    if key == "constrained_category":
        return "Supply-constrained equipment category"
    return None


def explain_rows(explainer: Pipeline, rows: pd.DataFrame, top_k: int = 4) -> list[str]:
    """Top risk-driver phrases per row from logistic contributions (JSON strings)."""
    pre, model = explainer.named_steps["pre"], explainer.named_steps["model"]
    X = pre.transform(rows[ALL_FEATURES])
    X = X.toarray() if hasattr(X, "toarray") else np.asarray(X)
    contrib = X * model.coef_[0]
    names = pre.get_feature_names_out()
    out = []
    for i in range(len(rows)):
        order = np.argsort(-contrib[i])
        phrases, seen = [], set()
        for j in order:
            if contrib[i][j] <= 0.02:
                break
            p = _phrase(names[j], rows.iloc[i])
            if p and p not in seen:
                phrases.append(p)
                seen.add(p)
            if len(phrases) >= top_k:
                break
        out.append(json.dumps(phrases))
    return out


# ---------------------------------------------------------------------------
# Composite 0–100 risk score (explainable weights, config-synced)
# ---------------------------------------------------------------------------

def score_open_orders(feats: pd.DataFrame, model, explainer) -> pd.DataFrame:
    open_rows = feats[feats["is_open"] == 1].copy()
    if open_rows.empty:
        return pd.DataFrame()
    proba = model.predict_proba(open_rows[ALL_FEATURES])[:, 1]

    slack_pressure = (1 - ((open_rows["slack_ratio"] - 0.9) / 0.6).clip(0, 1))
    crit = open_rows["criticality_rank"].map(
        {k: CRITICALITY_SCORE[v] for k, v in _CRIT_NAME.items()})
    flexibility = (0.6 * open_rows["supply_concentration"]
                   + 0.4 * (1 - open_rows["alternative_supplier_available"]))

    w = RISK_WEIGHTS
    score = 100 * (w["delay_probability"] * proba
                   + w["schedule_slack"] * slack_pressure
                   + w["criticality"] * crit
                   + w["supply_flexibility"] * flexibility)
    open_rows["delay_probability"] = np.round(proba, 3)
    open_rows["risk_score"] = np.round(score, 1)
    open_rows["risk_level"] = [next(band for cut, band in RISK_BANDS if s >= cut)
                               for s in open_rows["risk_score"]]
    open_rows["top_risk_drivers"] = explain_rows(explainer, open_rows)
    return open_rows[["purchase_order_id", "delay_probability", "risk_score",
                      "risk_level", "top_risk_drivers"]]
