"""Lead-time forecasting — predicts actual delivery lead time (days) per PO.

Methodology (MODEL_DOCUMENTATION.md):
  * Training data: delivered POs only (the only rows with a realized outcome).
  * Split: time-based — the last TEST_SPLIT_MONTHS of order dates are held
    out. Random splits would leak future supplier behavior into training.
  * Models compared: Ridge (linear baseline), RandomForest,
    HistGradientBoosting. Metrics: MAE, RMSE, MAPE, R².
  * Selection: lowest test MAE wins; all results persisted for the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import (mean_absolute_error, mean_absolute_percentage_error,
                             mean_squared_error, r2_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config.settings import LEADTIME_TARGET, MODELS_DIR, TEST_SPLIT_MONTHS
from src.transformation.features import (ALL_FEATURES, CATEGORICAL_FEATURES,
                                          NUMERIC_FEATURES)


def time_split(feats: pd.DataFrame):
    """Closed-window cohort + time-based split.

    Delivered-only training data is right-censored: recently ordered POs
    only appear if they delivered *fast*, so a naive delivered-set split
    trains on the full delay distribution but tests on survivors. We
    therefore restrict both train and test to POs whose outcome window has
    closed — ordered early enough that even a 120-day delay would already
    be observed. (MODEL_DOCUMENTATION.md §3 discusses this bias.)
    """
    delivered = feats[feats["is_delivered"] == 1].copy()
    today = pd.Timestamp.today().normalize()
    window_closed = (delivered["order_date"]
                     + pd.to_timedelta(delivered["planned_lead_time_days"] + 120, unit="D")
                     ) <= today
    cohort = delivered[window_closed]
    cutoff = cohort["order_date"].max() - pd.DateOffset(months=TEST_SPLIT_MONTHS)
    train = cohort[cohort["order_date"] <= cutoff]
    test = cohort[cohort["order_date"] > cutoff]
    return train, test, cutoff


def _preprocessor(scale_numeric: bool = False) -> ColumnTransformer:
    steps = [("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
              CATEGORICAL_FEATURES)]
    if scale_numeric:
        steps.append(("num", StandardScaler(), NUMERIC_FEATURES))
    else:
        steps.append(("num", "passthrough", NUMERIC_FEATURES))
    return ColumnTransformer(steps)


def train_leadtime_models(feats: pd.DataFrame, verbose: bool = True) -> dict:
    train, test, cutoff = time_split(feats)
    X_tr, y_tr = train[ALL_FEATURES], train[LEADTIME_TARGET]
    X_te, y_te = test[ALL_FEATURES], test[LEADTIME_TARGET]

    candidates = {
        "Ridge (linear baseline)": Pipeline(
            [("pre", _preprocessor(scale_numeric=True)), ("model", Ridge(alpha=1.0))]),
        "Random Forest": Pipeline(
            [("pre", _preprocessor()), ("model", RandomForestRegressor(
                n_estimators=300, min_samples_leaf=3, random_state=7, n_jobs=-1))]),
        "Hist Gradient Boosting": Pipeline(
            [("pre", _preprocessor()), ("model", HistGradientBoostingRegressor(
                max_iter=400, learning_rate=0.06, max_depth=6, random_state=7))]),
    }

    # Naive baseline: predict the plan itself. The models' value-add is
    # everything they recover beyond this row.
    naive = X_te["planned_lead_time_days"]
    results = [{
        "model": "Naive (planned lead time)",
        "mae_days": round(float(mean_absolute_error(y_te, naive)), 2),
        "rmse_days": round(float(np.sqrt(mean_squared_error(y_te, naive))), 2),
        "mape_pct": round(float(mean_absolute_percentage_error(y_te, naive)) * 100, 2),
        "r2": round(float(r2_score(y_te, naive)), 3),
    }]
    fitted = {}
    for name, pipe in candidates.items():
        pipe.fit(X_tr, y_tr)
        pred = pipe.predict(X_te)
        results.append({
            "model": name,
            "mae_days": round(float(mean_absolute_error(y_te, pred)), 2),
            "rmse_days": round(float(np.sqrt(mean_squared_error(y_te, pred))), 2),
            "mape_pct": round(float(mean_absolute_percentage_error(y_te, pred)) * 100, 2),
            "r2": round(float(r2_score(y_te, pred)), 3),
        })
        fitted[name] = pipe

    best_name = min(results[1:], key=lambda r: r["mae_days"])["model"]
    best = fitted[best_name]
    for r in results:
        r["selected"] = r["model"] == best_name

    perm = permutation_importance(best, X_te, y_te, n_repeats=5, random_state=7,
                                  scoring="neg_mean_absolute_error")
    importance = sorted(
        [{"feature": f, "mae_impact_days": round(float(m), 2)}
         for f, m in zip(ALL_FEATURES, perm.importances_mean)],
        key=lambda d: -d["mae_impact_days"])[:10]

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(best, MODELS_DIR / "leadtime_model.joblib")
    meta = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "target": LEADTIME_TARGET,
        "train_rows": len(train), "test_rows": len(test),
        "split": f"time-based, test = orders after {cutoff.date()}",
        "results": results, "selected_model": best_name,
        "permutation_importance_top10": importance,
    }
    (MODELS_DIR / "leadtime_metrics.json").write_text(json.dumps(meta, indent=2))
    if verbose:
        print(f"Lead-time model: {best_name} "
              f"(MAE {min(r['mae_days'] for r in results)}d, "
              f"train {len(train)} / test {len(test)})")
    return {"model": best, "meta": meta}


def predict_open_orders(feats: pd.DataFrame, model) -> pd.DataFrame:
    """Predict lead time + delivery date for open POs."""
    open_rows = feats[feats["is_open"] == 1].copy()
    if open_rows.empty:
        return pd.DataFrame()
    pred = model.predict(open_rows[ALL_FEATURES])
    open_rows["predicted_lead_days"] = np.round(pred, 0)
    open_rows["predicted_delivery_date"] = (
        open_rows["order_date"] + pd.to_timedelta(open_rows["predicted_lead_days"], unit="D")
    ).dt.date.astype(str)
    return open_rows[["purchase_order_id", "predicted_lead_days", "predicted_delivery_date"]]
