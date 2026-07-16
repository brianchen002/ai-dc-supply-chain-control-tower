"""Recommended-action engine for open purchase orders.

Deterministic rule ladder keyed on the risk drivers — the same
"explainable rules first" principle as the risk score. The optional LLM
layer (src/llm/workflows.py) narrates; it never decides the action.
"""
from __future__ import annotations

import json

import pandas as pd

from config.settings import EQUIPMENT


def recommend(row: pd.Series) -> str:
    level = row.get("risk_level", "Low")
    drivers = json.loads(row.get("top_risk_drivers") or "[]")
    drivers_text = " ".join(drivers).lower()
    modes = EQUIPMENT.get(row["equipment_category"], {}).get("modes", {})
    actions: list[str] = []

    if level in ("Critical", "High"):
        if "constrained" in drivers_text or "no qualified alternative" in drivers_text:
            actions.append("Escalate to supplier executive review — secure a committed production slot")
            if not row.get("alternative_supplier_available"):
                actions.append("Initiate alternative-supplier qualification")
        if row.get("shipping_mode") == "Ocean" and "Air" in modes:
            actions.append("Evaluate ocean→air conversion (~3–5 weeks transit saved)")
        if "schedule slack" in drivers_text or "required on site" in drivers_text:
            actions.append("Notify deployment PM — re-sequence installation around late arrival")
        if row.get("procurement_status") in ("Ordered", "In Production"):
            actions.append("Request production pull-in / earlier slot")
        if not actions:
            actions.append("Daily expedite review with supplier until ETA recovers")
    elif level == "Moderate":
        actions.append("Monitor weekly; hold contingency slot in install schedule")
    else:
        actions.append("On plan — standard tracking cadence")
    return " · ".join(actions[:3])


def add_recommendations(predictions: pd.DataFrame, pos: pd.DataFrame) -> pd.DataFrame:
    ctx = pos.set_index("purchase_order_id")
    merged = predictions.join(
        ctx[["equipment_category", "shipping_mode", "procurement_status",
             "alternative_supplier_available"]], on="purchase_order_id")
    predictions = predictions.copy()
    predictions["recommended_action"] = merged.apply(recommend, axis=1)
    return predictions
