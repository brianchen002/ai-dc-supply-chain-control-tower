"""Feature engineering for the two ML models.

Leakage policy (MODEL_DOCUMENTATION.md §3): every feature must be knowable
at purchase-order creation time. Outcome-adjacent fields (current_eta,
delay_days, statuses, actual dates, _true_arrival) are explicitly excluded.
`planned_lead_time_days` IS a legitimate feature — it is the plan agreed at
order time, and both models learn deviations from it.
"""
from __future__ import annotations

import pandas as pd

from config.settings import CONGESTED_ORIGINS, EQUIPMENT

CATEGORICAL_FEATURES = ["equipment_category", "supplier_name", "shipping_mode",
                        "origin_country"]
NUMERIC_FEATURES = [
    "order_quantity", "planned_lead_time_days", "supplier_capacity_utilization",
    "historical_supplier_delay_rate", "supplier_on_time_delivery_rate",
    "inventory_buffer_days", "supply_concentration", "criticality_rank",
    "alternative_supplier_available", "origin_congestion",
    "days_to_required_at_order", "slack_ratio", "order_month", "constrained_category",
]
ALL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

_CRIT_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def build_features(pos: pd.DataFrame) -> pd.DataFrame:
    """Return a modeling frame: features + targets + split helpers."""
    df = pos.copy()
    od = pd.to_datetime(df["purchase_order_date"])
    req = pd.to_datetime(df["required_on_site_date"])

    df["criticality_rank"] = df["equipment_criticality"].map(_CRIT_RANK)
    df["alternative_supplier_available"] = df["alternative_supplier_available"].astype(int)
    df["origin_congestion"] = df["origin_country"].map(CONGESTED_ORIGINS).fillna(0.0)
    df["days_to_required_at_order"] = (req - od).dt.days
    df["slack_ratio"] = (df["days_to_required_at_order"]
                         / df["planned_lead_time_days"].clip(lower=1)).round(3)
    df["order_month"] = od.dt.month
    df["order_date"] = od
    df["constrained_category"] = df["equipment_category"].map(
        {c: int(s["constrained"]) for c, s in EQUIPMENT.items()})

    keep = (["purchase_order_id", "order_date", "procurement_status",
             "total_order_value", "data_center_site"]
            + ALL_FEATURES
            + ["actual_lead_time_days", "missed_required_date"])
    out = df[keep].copy()
    out["is_delivered"] = (df["procurement_status"] == "Delivered").astype(int)
    out["is_open"] = (~df["procurement_status"].isin(["Delivered", "Cancelled"])).astype(int)
    return out
