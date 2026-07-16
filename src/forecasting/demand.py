"""Demand forecasting — forward-looking equipment demand vs confirmed supply.

Approach (documented in MODEL_DOCUMENTATION.md §6): monthly ordered
quantities per category form a short (≤18 point) series, so the forecast is
a transparent linear trend with residual-based confidence intervals rather
than an over-parameterized time-series model. Supply gaps compare planned
demand (site ramp plans) against expected deliveries from open POs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FORECAST_MONTHS = 6


def demand_history_and_forecast(pos: pd.DataFrame) -> pd.DataFrame:
    df = pos[pos["procurement_status"] != "Cancelled"].copy()
    df["month"] = pd.to_datetime(df["purchase_order_date"]).dt.to_period("M")
    hist = (df.groupby(["equipment_category", "month"])["order_quantity"]
            .sum().reset_index())

    rows = []
    for cat, g in hist.groupby("equipment_category"):
        g = g.sort_values("month")
        # Drop the partial current month from trend fitting
        series = g.iloc[:-1] if len(g) > 3 else g
        y = series["order_quantity"].to_numpy(dtype=float)
        x = np.arange(len(y))
        for _, r in g.iterrows():
            rows.append({"equipment_category": cat,
                         "month": str(r["month"]), "kind": "history",
                         "units": int(r["order_quantity"]), "lo": None, "hi": None})
        if len(y) >= 4:
            slope, intercept = np.polyfit(x, y, 1)
            resid_std = float(np.std(y - (slope * x + intercept)))
            last_month = g["month"].max()
            for h in range(1, FORECAST_MONTHS + 1):
                m = last_month + h
                pred = max(0.0, slope * (len(y) - 1 + h) + intercept)
                rows.append({
                    "equipment_category": cat, "month": str(m), "kind": "forecast",
                    "units": int(round(pred)),
                    "lo": int(max(0, round(pred - 1.28 * resid_std))),
                    "hi": int(round(pred + 1.28 * resid_std)),
                })
    return pd.DataFrame(rows)


def supply_vs_demand(pos: pd.DataFrame, demand_plan: pd.DataFrame,
                     predictions: pd.DataFrame) -> pd.DataFrame:
    """Monthly planned demand vs expected deliveries per category (+ per site)."""
    open_pos = pos[~pos["procurement_status"].isin(["Delivered", "Cancelled"])].copy()
    if not predictions.empty:
        open_pos = open_pos.merge(
            predictions[["purchase_order_id", "predicted_delivery_date"]],
            on="purchase_order_id", how="left")
        eta = open_pos["predicted_delivery_date"].fillna(open_pos["current_eta"])
    else:
        eta = open_pos["current_eta"]
    open_pos["delivery_month"] = pd.to_datetime(eta, errors="coerce").dt.to_period("M").astype(str)

    inbound = (open_pos.groupby(["equipment_category", "data_center_site", "delivery_month"])
               ["order_quantity"].sum().reset_index()
               .rename(columns={"delivery_month": "month",
                                "order_quantity": "expected_deliveries",
                                "data_center_site": "site"}))

    plan = demand_plan.rename(columns={"data_center_site": "site",
                                       "planned_units": "planned_demand"}).copy()
    plan["month"] = pd.to_datetime(plan["month"]).dt.to_period("M").astype(str)

    merged = plan.merge(inbound, on=["equipment_category", "site", "month"], how="outer")
    merged["planned_demand"] = merged["planned_demand"].fillna(0).astype(int)
    merged["expected_deliveries"] = merged["expected_deliveries"].fillna(0).astype(int)
    merged["supply_gap"] = merged["planned_demand"] - merged["expected_deliveries"]
    return merged.sort_values(["equipment_category", "site", "month"])
