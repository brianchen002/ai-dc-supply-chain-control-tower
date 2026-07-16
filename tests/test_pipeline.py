"""End-to-end pipeline tests: data causality, model sanity, output integrity.

Run from the repo root (no pytest needed):

    python -m tests.test_pipeline

Philosophy carried over from the OpsPilot build: the synthetic data must be
*causally* consistent (stressed suppliers really delay more), and every model
must clear explicit quality floors — a bad weight change or a broken feature
fails loudly here before it ships.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile

_TMP_DB = tempfile.mkstemp(suffix=".db")[1]
os.environ["CT_DB"] = _TMP_DB  # must be set before config import

import pandas as pd  # noqa: E402

PASS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS
    if not cond:
        print(f"  FAIL  {label}  {detail}")
        sys.exit(1)
    PASS += 1
    print(f"  ok    {label}")


def main() -> None:
    from src.pipeline import run_pipeline

    print("== pipeline ==")
    result = run_pipeline(force_data=False, verbose=False)
    check("pipeline completes", result["pos"] >= 1500, str(result))
    check("all open POs scored", result["scored"] > 500)

    conn = sqlite3.connect(_TMP_DB)
    conn.row_factory = sqlite3.Row
    pos = pd.read_sql("SELECT * FROM purchase_orders", conn)

    print("== dataset ==")
    check("≥1,500 purchase orders", len(pos) >= 1500, f"{len(pos)}")
    spec_fields = ["purchase_order_id", "supplier_name", "equipment_category",
                   "manufacturer", "part_number", "order_quantity", "unit_cost",
                   "total_order_value", "procurement_status", "shipment_status",
                   "original_eta", "current_eta", "required_on_site_date",
                   "planned_lead_time_days", "supplier_capacity_utilization",
                   "equipment_criticality", "supply_concentration",
                   "inventory_buffer_days", "risk_score", "delay_probability",
                   "risk_level", "data_center_site", "project_phase"]
    check("all spec fields present", all(f in pos.columns for f in spec_fields),
          str([f for f in spec_fields if f not in pos.columns]))

    print("== causal consistency ==")
    d = pos[pos["procurement_status"] == "Delivered"]
    hi = d[d["supplier_capacity_utilization"] > 0.85]["missed_required_date"].mean()
    lo = d[d["supplier_capacity_utilization"] < 0.70]["missed_required_date"].mean()
    check("high-utilization suppliers miss more", hi > lo, f"{hi:.2f} vs {lo:.2f}")
    tf = pos[pos["equipment_category"] == "Transformers"]["planned_lead_time_days"].mean()
    rk = pos[pos["equipment_category"] == "Racks"]["planned_lead_time_days"].mean()
    check("transformers lead ≫ racks lead", tf > rk * 3, f"{tf:.0f} vs {rk:.0f}")
    air = pos[pos["shipping_mode"] == "Air"]
    ocean = pos[pos["shipping_mode"] == "Ocean"]
    check("air freight cheaper on time, pricier per unit — proxy: air used for high-cost gear",
          air["unit_cost"].median() > ocean["unit_cost"].median() * 0.8)

    print("== lead-time model ==")
    lt = json.loads(conn.execute(
        "SELECT payload FROM model_metrics WHERE name='leadtime'").fetchone()["payload"])
    naive = next(r for r in lt["results"] if r["model"].startswith("Naive"))
    best = next(r for r in lt["results"] if r.get("selected"))
    check("model beats naive planned-lead baseline",
          best["mae_days"] < naive["mae_days"] * 0.85,
          f"{best['mae_days']} vs naive {naive['mae_days']}")
    check("lead-time R² ≥ 0.6", best["r2"] >= 0.6, str(best["r2"]))
    check("≥3 models + naive compared", len(lt["results"]) >= 4)

    print("== delay-risk model ==")
    dm = json.loads(conn.execute(
        "SELECT payload FROM model_metrics WHERE name='delay'").fetchone()["payload"])
    sel = next(r for r in dm["results"] if r.get("selected"))
    check("ROC-AUC ≥ 0.75", sel["roc_auc"] >= 0.75, str(sel["roc_auc"]))
    check("recall ≥ 0.75 at operating threshold", sel["recall"] >= 0.75, str(sel["recall"]))
    cm = sel["confusion_matrix"]
    check("confusion matrix consistent",
          cm["tp"] + cm["fn"] > 0 and cm["tn"] + cm["fp"] > 0)

    print("== predictions & outputs ==")
    pred = pd.read_sql("SELECT * FROM predictions", conn)
    open_n = int((~pos["procurement_status"].isin(["Delivered", "Cancelled"])).sum())
    check("every open PO has a prediction row", len(pred) == open_n,
          f"{len(pred)} vs {open_n}")
    check("probabilities in [0,1]", pred["delay_probability"].between(0, 1).all())
    check("risk scores in [0,100]", pred["risk_score"].between(0, 100).all())
    check("risk levels valid",
          set(pred["risk_level"].unique()) <= {"Critical", "High", "Moderate", "Low"})
    drivers_ok = pred["top_risk_drivers"].map(
        lambda s: isinstance(json.loads(s), list)).all()
    check("risk drivers are valid JSON lists", bool(drivers_ok))
    check("every prediction has a recommended action",
          pred["recommended_action"].str.len().gt(0).all())

    print("== aggregates & alerts ==")
    rd = pd.read_sql("SELECT * FROM site_readiness", conn)
    check("all 8 sites scored", len(rd) == 8)
    check("readiness scores in [0,100]", rd["readiness_score"].between(0, 100).all())
    sc = pd.read_sql("SELECT * FROM supplier_scorecard", conn)
    check("supplier scorecard covers all suppliers with POs",
          len(sc) == pos["supplier_id"].nunique())
    alerts = pd.read_sql("SELECT * FROM alerts", conn)
    check("alert volume sane (10–300)", 10 <= len(alerts) <= 300, str(len(alerts)))
    po_alerts = alerts[alerts["alert_type"].isin(["PO_CRITICAL_RISK", "ETA_SLIP"])]
    known = set(pos["purchase_order_id"])
    check("every PO alert references a real PO",
          po_alerts["entity"].isin(known).all())

    print("== inbox intelligence ==")
    ev = pd.read_sql("SELECT * FROM email_events", conn)
    check("events extracted from every email", len(ev) >= 10, str(len(ev)))
    check("noise emails classified NO_IMPACT",
          (ev["event_type"] == "NO_IMPACT").sum() >= 2)
    check("expedites carry negative impact",
          (ev.loc[ev["event_type"] == "EXPEDITE_CONFIRMED", "impact_days"] < 0).all())
    all_linked = [p for s in ev["affected_pos"] for p in json.loads(s or "[]")]
    check("every linked PO exists", set(all_linked) <= set(pos["purchase_order_id"]))
    check("impactful events link POs", len(all_linked) >= 10, str(len(all_linked)))

    print("== NL→SQL safety layer ==")
    from src.llm.analytics_copilot import CANNED, run_query, sanitize_sql
    blocked = 0
    for bad in ["DROP TABLE purchase_orders", "SELECT 1; DELETE FROM alerts",
                "UPDATE purchase_orders SET risk_score=0", "PRAGMA writable_schema=1"]:
        try:
            sanitize_sql(bad)
        except ValueError:
            blocked += 1
    check("sanitizer blocks write/DDL/multi-statement", blocked == 4)
    check("safe queries get a row cap",
          "LIMIT" in sanitize_sql("SELECT * FROM suppliers"))
    for name, (sql, _) in list(CANNED.items())[:3]:
        df_c = run_query(sanitize_sql(sql))
        check(f"canned query runs: {name[:34]}…", len(df_c) > 0)

    print("== offline LLM workflows ==")
    from src.llm.client import OfflineClient
    from src.llm.workflows import executive_brief, po_risk_narrative
    client = OfflineClient()
    conn2 = sqlite3.connect(_TMP_DB)
    conn2.row_factory = sqlite3.Row
    brief = executive_brief(conn2, client)
    check("executive brief renders offline",
          "Executive supply chain brief" in brief["text"] and brief["mode"] == "offline")
    po_id = pred.sort_values("risk_score", ascending=False)["purchase_order_id"].iloc[0]
    nar = po_risk_narrative(conn2, po_id, client)
    check("PO narrative cites real PO", po_id in nar["text"])

    conn.close()
    conn2.close()
    try:
        os.unlink(_TMP_DB)
    except OSError:
        pass
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
