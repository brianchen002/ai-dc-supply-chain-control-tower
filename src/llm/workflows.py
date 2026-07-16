"""LLM narration workflows (ported from OpsPilot's pluggable AI layer).

Two workflows sit on top of the deterministic pipeline:

    1. executive_brief()  — control-tower snapshot → leadership brief.
    2. po_risk_narrative() — one PO's model outputs → supplier-call prep note.

Same contract as before: with ANTHROPIC_API_KEY set the composition is done
by Claude under grounding guardrails; without it, a deterministic template
composes the same structure from the same data. Mode is always surfaced.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd

from src.llm.prompts import (CONTROL_TOWER_SYSTEM, EXECUTIVE_BRIEF_USER,
                             PO_NARRATIVE_USER)


def _snapshot(conn: sqlite3.Connection) -> dict:
    q = lambda sql: pd.read_sql_query(sql, conn)  # noqa: E731
    kpi = q("""SELECT COUNT(*) n, SUM(total_order_value) v FROM purchase_orders
               WHERE procurement_status NOT IN ('Delivered','Cancelled')""").iloc[0]
    top = q("""SELECT purchase_order_id, equipment_category, destination_site,
                      total_order_value, delay_probability, risk_score, top_risk_drivers
               FROM purchase_orders WHERE risk_level = 'Critical'
               ORDER BY risk_score DESC, total_order_value DESC LIMIT 5""")
    top_rows = top.to_dict("records")
    for r in top_rows:
        drivers = json.loads(r.pop("top_risk_drivers") or "[]")
        r["primary_driver"] = drivers[0] if drivers else "n/a"
    supplier_hot = q("""SELECT supplier_name, COUNT(*) n_critical,
                               SUM(total_order_value) value
                        FROM purchase_orders WHERE risk_level IN ('Critical','High')
                        GROUP BY supplier_name ORDER BY n_critical DESC LIMIT 4""")
    sites = q("""SELECT data_center_site, metro, readiness_status, readiness_score,
                        at_risk_pos, value_at_risk FROM site_readiness
                 WHERE readiness_status IN ('Critical','At Risk')
                 ORDER BY readiness_score""")
    risk_counts = q("""SELECT risk_level, COUNT(*) n FROM purchase_orders
                       WHERE risk_level IS NOT NULL GROUP BY risk_level""")
    return {
        "open_pos": int(kpi["n"]), "open_value_usd": round(float(kpi["v"] or 0)),
        "risk_counts": dict(zip(risk_counts["risk_level"], risk_counts["n"].astype(int))),
        "top_critical_pos": top_rows,
        "supplier_hotspots": supplier_hot.to_dict("records"),
        "sites_exposed": sites.to_dict("records"),
    }


def executive_brief(conn: sqlite3.Connection, client) -> dict:
    data = _snapshot(conn)
    if client.is_live:
        text = client.complete(
            CONTROL_TOWER_SYSTEM,
            EXECUTIVE_BRIEF_USER.format(data_json=json.dumps(data, indent=1)),
            max_tokens=1000)
    else:
        text = _compose_brief(data)
    return {"text": text, "mode": "live" if client.is_live else "offline"}


def _compose_brief(d: dict) -> str:
    rc = d["risk_counts"]
    lines = ["### Executive supply chain brief", ""]
    lines.append(
        f"**{d['open_pos']} open purchase orders (${d['open_value_usd']:,}) — "
        f"{rc.get('Critical', 0)} critical and {rc.get('High', 0)} high-risk.**")
    lines += ["", "**Top escalations**", ""]
    for i, p in enumerate(d["top_critical_pos"][:3], 1):
        lines.append(
            f"{i}. `{p['purchase_order_id']}` {p['equipment_category']} → "
            f"{p['destination_site']} · ${p['total_order_value']:,.0f} · "
            f"P(delay) {p['delay_probability']:.0%} · {p['primary_driver']}")
    lines += ["", "**Systemic patterns**", ""]
    hs = d["supplier_hotspots"]
    if hs and hs[0]["n_critical"] >= 3:
        lines.append(f"- {hs[0]['supplier_name']} carries {hs[0]['n_critical']} "
                     f"high/critical POs (${hs[0]['value']:,.0f}) — concentrated exposure.")
    if len(hs) > 1 and hs[1]["n_critical"] >= 3:
        lines.append(f"- {hs[1]['supplier_name']}: {hs[1]['n_critical']} high/critical POs.")
    if not lines[-1].startswith("-"):
        lines.append("- No single-supplier concentration among critical POs today.")
    lines += ["", "**Deployment impact**", ""]
    if d["sites_exposed"]:
        for s in d["sites_exposed"][:3]:
            lines.append(f"- {s['data_center_site']} ({s['metro']}): "
                         f"{s['readiness_status']} at {s['readiness_score']:.0f}/100 — "
                         f"{s['at_risk_pos']} POs / ${s['value_at_risk']:,.0f} at risk.")
    else:
        lines.append("- All sites currently On Track or better.")
    lines += ["", "**Recommended focus**", ""]
    lines.append("1. Procurement — run the critical-PO escalation list with the top "
                 "supplier(s) above; secure committed slots this week.")
    lines.append("2. Logistics — review ocean→air conversion for critical POs with "
                 "thin schedule slack.")
    if d["sites_exposed"]:
        lines.append(f"3. Site PM ({d['sites_exposed'][0]['data_center_site']}) — "
                     "re-sequence installation around late critical equipment; "
                     "confirm revised energization plan with finance.")
    else:
        lines.append("3. Finance — refresh exposure view after this week's deliveries.")
    return "\n".join(lines)


def po_risk_narrative(conn: sqlite3.Connection, po_id: str, client) -> dict:
    row = pd.read_sql_query(
        "SELECT * FROM purchase_orders WHERE purchase_order_id = ?", conn, params=(po_id,))
    if row.empty:
        return {"text": f"{po_id} not found.", "mode": "error"}
    r = row.iloc[0].to_dict()
    ctx = {k: r.get(k) for k in (
        "purchase_order_id", "supplier_name", "equipment_category", "equipment_type",
        "order_quantity", "total_order_value", "destination_site",
        "required_on_site_date", "current_eta", "predicted_delivery_date",
        "delay_probability", "risk_score", "risk_level", "recommended_action")}
    ctx["top_risk_drivers"] = json.loads(r.get("top_risk_drivers") or "[]")

    if client.is_live:
        text = client.complete(
            CONTROL_TOWER_SYSTEM,
            PO_NARRATIVE_USER.format(context_json=json.dumps(ctx, indent=1)),
            max_tokens=400)
    else:
        drivers = "; ".join(ctx["top_risk_drivers"][:3]) or "no dominant driver"
        text = (
            f"**{ctx['purchase_order_id']}** — {ctx['order_quantity']}× "
            f"{ctx['equipment_type']} from {ctx['supplier_name']} for "
            f"{ctx['destination_site']} (${ctx['total_order_value']:,.0f}). "
            f"The model puts delay probability at {ctx['delay_probability']:.0%} "
            f"(risk {ctx['risk_level']}, {ctx['risk_score']:.0f}/100), driven by: {drivers}. "
            f"Recommended action: {ctx['recommended_action']}. "
            f"On the call: push for a committed recovery date no later than "
            f"{ctx['required_on_site_date']}, and written confirmation of the "
            f"production slot.")
    return {"text": text, "mode": "live" if client.is_live else "offline"}
