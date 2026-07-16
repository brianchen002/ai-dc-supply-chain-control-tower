"""End-to-end automated pipeline.

    synthetic sources → validation → feature engineering →
    lead-time model → delay-risk model → scoring → recommendations →
    aggregates (suppliers, sites, demand) → SQLite → alerts

Run:  python -m src.pipeline [--force-data]
Idempotent; ~20s on a laptop. The dashboard auto-runs this on first launch
if the database is missing.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import pandas as pd

from config.settings import PROCESSED_DIR
from src.alerts.engine import build_alerts
from src.data_generation.generate import generate_all
from src.db import write_tables
from src.ingestion.load import load_sources
from src.llm.client import OfflineClient
from src.llm.email_intel import extract_events
from src.forecasting.demand import demand_history_and_forecast, supply_vs_demand
from src.forecasting.leadtime_model import predict_open_orders, train_leadtime_models
from src.recommendations.engine import add_recommendations
from src.risk_model.delay_model import score_open_orders, train_delay_models
from src.transformation.aggregates import site_readiness, supplier_scorecard
from src.transformation.features import build_features
from src.validation.checks import validate_purchase_orders


def run_pipeline(force_data: bool = False, verbose: bool = True) -> dict:
    t0 = datetime.now()

    # 1. Ingestion (synthetic sources stand in for OMS/ERP/logistics feeds)
    generate_all(force=force_data, verbose=verbose)
    src_frames = load_sources()
    pos = src_frames["purchase_orders"]
    suppliers = src_frames["suppliers"]
    sites = src_frames["sites"]
    catalog = src_frames["equipment_catalog"]
    demand_plan = src_frames["demand_plan"]

    # 2. Validation (hard-fails the pipeline on contract breaks)
    report = validate_purchase_orders(pos)
    if verbose:
        print(f"Validation: {report['status']} "
              f"({len(report['warnings'])} warnings)")

    # 3. Feature engineering
    feats = build_features(pos)

    # 4. Lead-time forecasting (3-model comparison)
    lt = train_leadtime_models(feats, verbose=verbose)
    lt_pred = predict_open_orders(feats, lt["model"])

    # 5. Delay-risk classification + composite risk score + drivers
    dm = train_delay_models(feats, verbose=verbose)
    risk_pred = score_open_orders(feats, dm["model"], dm["explainer"])

    predictions = lt_pred.merge(risk_pred, on="purchase_order_id", how="outer")

    # 6. Recommended actions (rule ladder over model outputs)
    predictions = add_recommendations(predictions, pos)

    # 7. Enrich the PO table with model outputs
    pos_enriched = pos.drop(columns=["_true_arrival"]).merge(
        predictions, on="purchase_order_id", how="left")

    # 8. Aggregates
    scorecard = supplier_scorecard(pos_enriched, predictions)
    readiness = site_readiness(pos_enriched, sites, predictions)
    demand_fc = demand_history_and_forecast(pos)
    gap = supply_vs_demand(pos, demand_plan, predictions)

    # 9. Automated alerts (last stage — consumes everything above)
    alerts = build_alerts(pos_enriched, predictions, scorecard, readiness)

    # 10. Load SQLite for the dashboard
    metrics = pd.DataFrame([
        {"name": "leadtime", "payload": json.dumps(lt["meta"])},
        {"name": "delay", "payload": json.dumps(dm["meta"])},
        {"name": "pipeline_run", "payload": json.dumps(
            {"run_at": t0.isoformat(timespec="seconds"),
             "validation": report})},
    ])
    # 10b. Inbox intelligence — deterministic (offline) extraction runs in
    # the pipeline so tests can assert it; the dashboard re-runs with live
    # Claude when a key is present.
    emails = src_frames["supplier_emails"]
    open_enriched = pos_enriched[
        ~pos_enriched["procurement_status"].isin(["Delivered", "Cancelled"])]
    email_events = extract_events(
        emails, open_enriched, suppliers["supplier_name"].tolist(), OfflineClient())

    write_tables({
        "purchase_orders": pos_enriched, "suppliers": suppliers, "sites": sites,
        "equipment_catalog": catalog, "demand_plan": demand_plan,
        "predictions": predictions, "supplier_scorecard": scorecard,
        "site_readiness": readiness, "demand_forecast": demand_fc,
        "supply_gap": gap, "alerts": alerts, "model_metrics": metrics,
        "supplier_emails": emails, "email_events": email_events,
    })
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    took = (datetime.now() - t0).total_seconds()
    if verbose:
        print(f"Pipeline complete in {took:.1f}s — "
              f"{len(pos_enriched)} POs · {len(predictions)} scored · "
              f"{len(alerts)} alerts → SQLite")
    return {"pos": len(pos_enriched), "scored": len(predictions),
            "alerts": len(alerts), "seconds": took,
            "leadtime_meta": lt["meta"], "delay_meta": dm["meta"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-data", action="store_true",
                    help="regenerate synthetic sources before running")
    run_pipeline(force_data=ap.parse_args().force_data)
