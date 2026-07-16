"""Automated risk alerts — the last stage of the pipeline.

Alert conditions are data-state rules (same detection philosophy retained
from OpsPilot's exception engine): an alert exists because the condition is
true in the data, never because someone typed it in.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd


def build_alerts(pos_enriched: pd.DataFrame, predictions: pd.DataFrame,
                 scorecard: pd.DataFrame, readiness: pd.DataFrame) -> pd.DataFrame:
    """`pos_enriched` must already carry model columns (risk_level, ...).

    Alerting is deliberately gated to fight alert fatigue: only material,
    time-relevant slips page a human; the rest stay visible in the dashboard.
    """
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    enriched = pos_enriched

    days_to_required = (
        pd.to_datetime(enriched["required_on_site_date"])
        - pd.Timestamp.today().normalize()).dt.days

    crit = enriched[
        enriched["risk_level"].eq("Critical")
        & ((enriched["total_order_value"] > 1_000_000) | (days_to_required <= 45))]
    crit = crit.sort_values(["risk_score", "total_order_value"],
                            ascending=False).head(60)  # page humans about the top N only
    for _, r in crit.iterrows():
        rows.append({
            "severity": "critical", "alert_type": "PO_CRITICAL_RISK",
            "entity": r["purchase_order_id"],
            "message": (f"{r['purchase_order_id']} ({r['equipment_category']}, "
                        f"${r['total_order_value']:,.0f} → {r['destination_site']}) "
                        f"delay probability {r['delay_probability']:.0%}, "
                        f"risk score {r['risk_score']:.0f}."),
        })

    open_mask = ~enriched["procurement_status"].isin(["Delivered", "Cancelled"])
    slipped = enriched[open_mask
                       & (enriched["delay_days"].fillna(0) > 21)
                       & (enriched["total_order_value"] > 500_000)
                       & (days_to_required <= 120)
                       & ~enriched["risk_level"].eq("Critical")]  # already alerted above
    slipped = slipped.sort_values("delay_days", ascending=False).head(60)
    for _, r in slipped.iterrows():
        rows.append({
            "severity": "high" if r["delay_days"] > 35 else "medium",
            "alert_type": "ETA_SLIP",
            "entity": r["purchase_order_id"],
            "message": (f"{r['purchase_order_id']} current ETA has slipped "
                        f"{int(r['delay_days'])}d past the original commitment "
                        f"({r['supplier_name']}, {r['equipment_category']}, "
                        f"required on site in {int(days_to_required[r.name])}d)."),
        })

    for _, s in readiness.iterrows():
        if s["readiness_status"] in ("Critical", "At Risk"):
            rows.append({
                "severity": "critical" if s["readiness_status"] == "Critical" else "high",
                "alert_type": "SITE_READINESS",
                "entity": s["data_center_site"],
                "message": (f"{s['data_center_site']} ({s['metro']}) readiness "
                            f"{s['readiness_score']:.0f}/100 — {s['at_risk_pos']} POs at risk, "
                            f"${s['value_at_risk']:,.0f} value at risk, "
                            f"{s['critical_outstanding']} critical items outstanding."),
            })

    weak = scorecard[(scorecard["on_time_delivery_rate"].fillna(1) < 0.70)
                     & (scorecard["active_pos"] >= 3)]
    for _, s in weak.iterrows():
        rows.append({
            "severity": "high", "alert_type": "SUPPLIER_DETERIORATION",
            "entity": s["supplier_name"],
            "message": (f"{s['supplier_name']} on-time delivery "
                        f"{s['on_time_delivery_rate']:.0%} with {s['active_pos']} active POs "
                        f"(${s['open_value']:,.0f} open)."),
        })

    conc = scorecard[(scorecard["max_supply_concentration"] > 0.6)
                     & (scorecard["avg_open_delay_probability"].fillna(0) > 0.35)]
    for _, s in conc.iterrows():
        rows.append({
            "severity": "medium", "alert_type": "CONCENTRATION_RISK",
            "entity": s["supplier_name"],
            "message": (f"{s['max_supply_concentration']:.0%} of a category's spend sits with "
                        f"{s['supplier_name']} while its open-PO delay probability averages "
                        f"{s['avg_open_delay_probability']:.0%} — single-source exposure."),
        })

    alerts = pd.DataFrame(rows)
    if not alerts.empty:
        alerts["created_at"] = now
        sev_rank = {"critical": 0, "high": 1, "medium": 2}
        alerts = alerts.sort_values(["severity"], key=lambda s: s.map(sev_rank))
        alerts.insert(0, "alert_id", [f"ALT-{i + 1:04d}" for i in range(len(alerts))])
    return alerts
