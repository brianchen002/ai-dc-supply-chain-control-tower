"""Analytical aggregates: supplier scorecard and site readiness.

Formulas are deliberately transparent (weighted, documented) — same product
principle carried over from OpsPilot: explainable rules first, ML layered on
top. Weights live in config/settings.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import READINESS_BANDS, READINESS_WEIGHTS


def _minmax(s: pd.Series) -> pd.Series:
    rng = s.max() - s.min()
    return (s - s.min()) / rng if rng > 0 else pd.Series(0.5, index=s.index)


# ---------------------------------------------------------------------------
# Supplier scorecard
# ---------------------------------------------------------------------------

def supplier_scorecard(pos: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    df = pos.copy()
    delivered = df[df["procurement_status"] == "Delivered"].copy()
    open_pos = df[~df["procurement_status"].isin(["Delivered", "Cancelled"])].copy()
    if not predictions.empty:
        open_pos = open_pos.merge(predictions[["purchase_order_id", "delay_probability",
                                               "risk_level"]],
                                  on="purchase_order_id", how="left")

    delivered["on_time"] = (pd.to_datetime(delivered["actual_delivery_date"])
                            <= pd.to_datetime(delivered["supplier_committed_date"])
                            + pd.Timedelta(days=3)).astype(int)
    delivered["realized_delay"] = (
        pd.to_datetime(delivered["actual_delivery_date"])
        - pd.to_datetime(delivered["supplier_committed_date"])).dt.days.clip(lower=0)

    rows = []
    for sup, grp in df.groupby(["supplier_id", "supplier_name"]):
        sid, name = sup
        d = delivered[delivered["supplier_id"] == sid]
        o = open_pos[open_pos["supplier_id"] == sid]
        crit_open = o[o["equipment_criticality"] == "critical"]
        rows.append({
            "supplier_id": sid, "supplier_name": name,
            "categories": " | ".join(sorted(grp["equipment_category"].unique())),
            "active_pos": len(o),
            "open_value": round(o["total_order_value"].sum(), 0),
            "total_value": round(grp["total_order_value"].sum(), 0),
            "delivered_pos": len(d),
            "on_time_delivery_rate": round(d["on_time"].mean(), 3) if len(d) else None,
            "avg_realized_delay_days": round(d["realized_delay"].mean(), 1) if len(d) else None,
            "avg_lead_time_days": round(d["actual_lead_time_days"].mean(), 0) if len(d) else None,
            "lead_time_variance_days": round(d["actual_lead_time_days"].std(ddof=0), 1) if len(d) > 1 else 0.0,
            "capacity_utilization": grp["supplier_capacity_utilization"].iloc[0],
            "avg_open_delay_probability": (round(o["delay_probability"].mean(), 3)
                                           if len(o) and "delay_probability" in o else None),
            "critical_equipment_exposure": round(crit_open["total_order_value"].sum(), 0),
            "max_supply_concentration": round(grp["supply_concentration"].max(), 3),
        })
    sc = pd.DataFrame(rows)

    # Scorecard dimensions, 0–100 (higher = better except risk score)
    otd = sc["on_time_delivery_rate"].fillna(sc["on_time_delivery_rate"].median())
    sc["delivery_reliability"] = (otd * 100).round(0)
    sc["lead_time_stability"] = ((1 - _minmax(sc["lead_time_variance_days"].fillna(0))) * 100).round(0)
    sc["capacity_risk"] = ((1 - sc["capacity_utilization"]) * 100).round(0)
    sc["financial_exposure"] = ((1 - _minmax(sc["open_value"])) * 100).round(0)
    sc["concentration_score"] = ((1 - sc["max_supply_concentration"]) * 100).round(0)

    sc["supplier_risk_score"] = (100 - (
        0.30 * sc["delivery_reliability"] + 0.20 * sc["lead_time_stability"]
        + 0.20 * sc["capacity_risk"] + 0.15 * sc["financial_exposure"]
        + 0.15 * sc["concentration_score"])).round(1)

    # Risk-matrix axes
    sc["supply_chain_exposure"] = (
        0.6 * _minmax(sc["open_value"]) + 0.4 * sc["max_supply_concentration"]
    ).round(3) * 100
    sc["performance_risk"] = (
        0.5 * (1 - otd) * 100 + 0.5 * (sc["capacity_utilization"] * 100)
    ).round(1)
    return sc.sort_values("supplier_risk_score", ascending=False)


# ---------------------------------------------------------------------------
# Site readiness
# ---------------------------------------------------------------------------

def site_readiness(pos: pd.DataFrame, sites: pd.DataFrame,
                   predictions: pd.DataFrame) -> pd.DataFrame:
    df = pos[pos["procurement_status"] != "Cancelled"].copy()
    if not predictions.empty:
        df = df.merge(predictions[["purchase_order_id", "risk_level", "risk_score",
                                   "predicted_delivery_date"]],
                      on="purchase_order_id", how="left")
    today = pd.Timestamp.today().normalize()

    rows = []
    for _, site in sites.iterrows():
        code = site["data_center_site"]
        g = df[df["destination_site"] == code]
        crit = g[g["equipment_criticality"] == "critical"]
        open_g = g[~g["procurement_status"].isin(["Delivered"])]
        at_risk = open_g[open_g["risk_level"].isin(["High", "Critical"])] \
            if "risk_level" in open_g else open_g.iloc[0:0]

        delivered_pct = (g["procurement_status"] == "Delivered").mean() if len(g) else 0
        crit_delivered_pct = ((crit["procurement_status"] == "Delivered").mean()
                              if len(crit) else 1.0)
        at_risk_share = len(at_risk) / max(len(open_g), 1)
        days_to_required = (pd.Timestamp(site["required_capacity_date"]) - today).days
        schedule_pressure = float(np.clip(1 - days_to_required / 365, 0, 1))

        w = READINESS_WEIGHTS
        score = 100 * (w["delivered_pct"] * delivered_pct
                       + w["critical_delivered_pct"] * crit_delivered_pct
                       + w["at_risk_share"] * (1 - at_risk_share)
                       + w["schedule_pressure"] * (1 - schedule_pressure))
        status = next(band for cut, band in READINESS_BANDS if score >= cut)

        # Potential schedule impact: latest predicted arrival of critical open POs
        crit_open = crit[~crit["procurement_status"].isin(["Delivered"])]
        impact_days = 0
        if len(crit_open) and "predicted_delivery_date" in crit_open:
            pred = pd.to_datetime(crit_open["predicted_delivery_date"], errors="coerce")
            install = pd.Timestamp(site["installation_start_date"])
            impact_days = int(max(0, (pred.max() - install).days)) if pred.notna().any() else 0

        rows.append({
            "data_center_site": code, "metro": site["metro"], "region": site["region"],
            "project_phase": site["project_phase"],
            "planned_compute_capacity_mw": site["planned_compute_capacity_mw"],
            "planned_gpu_capacity": site["planned_gpu_capacity"],
            "required_capacity_date": site["required_capacity_date"],
            "installation_start_date": site["installation_start_date"],
            "total_pos": len(g),
            "delivered_pct": round(100 * delivered_pct, 1),
            "critical_delivered_pct": round(100 * crit_delivered_pct, 1),
            "open_pos": len(open_g),
            "at_risk_pos": len(at_risk),
            "value_at_risk": round(at_risk["total_order_value"].sum(), 0),
            "critical_outstanding": int(len(crit_open)),
            "readiness_score": round(score, 1),
            "readiness_status": status,
            "potential_schedule_impact_days": impact_days,
        })
    return pd.DataFrame(rows).sort_values("readiness_score")
