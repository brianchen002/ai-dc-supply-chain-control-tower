"""Data validation stage — runs between ingestion and feature engineering.

Hard failures stop the pipeline (schema breaks, impossible values).
Soft warnings are reported but tolerated (they mirror real feed quirks).
Report is written to data/processed/validation_report.json.
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from config.settings import PROCESSED_DIR

REQUIRED_COLUMNS = [
    "purchase_order_id", "purchase_order_date", "supplier_id", "supplier_name",
    "equipment_category", "equipment_type", "manufacturer", "part_number",
    "order_quantity", "unit_cost", "total_order_value", "currency",
    "procurement_status", "buyer", "contract_type", "production_start_date",
    "supplier_committed_date", "original_eta", "current_eta",
    "actual_delivery_date", "required_on_site_date", "shipment_status",
    "shipping_mode", "origin_country", "destination_country", "destination_site",
    "freight_forwarder", "customs_status", "incoterm",
    "warehouse_receipt_status", "tracking_update_date",
    "planned_lead_time_days", "current_expected_lead_time_days",
    "actual_lead_time_days", "delay_days", "lead_time_variance",
    "supplier_capacity_utilization", "supplier_on_time_delivery_rate",
    "historical_supplier_delay_rate", "equipment_criticality",
    "supply_concentration", "alternative_supplier_available",
    "inventory_buffer_days", "deployment_dependency", "data_center_site",
    "planned_compute_capacity_mw", "planned_gpu_capacity", "project_phase",
    "required_capacity_date", "installation_start_date", "missed_required_date",
]

VALID = {
    "procurement_status": {"Ordered", "In Production", "Shipped", "Delivered", "Cancelled"},
    "shipment_status": {"Not Shipped", "In Transit", "Customs", "Delayed", "Delivered"},
    "shipping_mode": {"Air", "Ocean", "Truck"},
    "equipment_criticality": {"critical", "high", "medium", "low"},
}


def validate_purchase_orders(df: pd.DataFrame, write_report: bool = True) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"missing columns: {missing}")

    if df["purchase_order_id"].duplicated().any():
        errors.append("duplicate purchase_order_id values")

    for col, vocab in VALID.items():
        bad = set(df[col].dropna().unique()) - vocab
        if bad:
            errors.append(f"{col}: unexpected values {bad}")

    if (df["order_quantity"] <= 0).any():
        errors.append("non-positive order_quantity")
    if (df["unit_cost"] <= 0).any():
        errors.append("non-positive unit_cost")

    # total = qty × unit_cost (tolerance for rounding)
    mismatch = (df["total_order_value"] - df["order_quantity"] * df["unit_cost"]).abs() > 0.05
    if mismatch.any():
        errors.append(f"total_order_value mismatch on {int(mismatch.sum())} rows")

    # committed date must equal order date + planned lead
    od = pd.to_datetime(df["purchase_order_date"])
    committed = pd.to_datetime(df["supplier_committed_date"])
    drift = ((committed - od).dt.days - df["planned_lead_time_days"]).abs() > 1
    if drift.any():
        errors.append(f"committed date != order + planned lead on {int(drift.sum())} rows")

    delivered = df["procurement_status"] == "Delivered"
    if df.loc[delivered, "actual_delivery_date"].isna().any():
        errors.append("delivered POs missing actual_delivery_date")
    if df.loc[delivered, "actual_lead_time_days"].isna().any():
        errors.append("delivered POs missing actual_lead_time_days")

    # label consistency: delivered miss label must match actual vs required
    act = pd.to_datetime(df.loc[delivered, "actual_delivery_date"])
    req = pd.to_datetime(df.loc[delivered, "required_on_site_date"])
    label = df.loc[delivered, "missed_required_date"].astype(int)
    if ((act > req).astype(int) != label).any():
        errors.append("missed_required_date label inconsistent with delivery dates")

    open_mask = ~df["procurement_status"].isin(["Delivered", "Cancelled"])
    if df.loc[open_mask, "current_eta"].isna().any():
        warnings.append("open POs with null current_eta")
    stale = pd.to_datetime(df["tracking_update_date"]) < (
        pd.Timestamp.today().normalize() - pd.Timedelta(days=7))
    if stale.any():
        warnings.append(f"{int(stale.sum())} POs with tracking updates older than 7 days")

    ranges = {
        "supplier_capacity_utilization": (0, 1),
        "supplier_on_time_delivery_rate": (0, 1),
        "historical_supplier_delay_rate": (0, 1),
        "supply_concentration": (0, 1),
    }
    for col, (lo, hi) in ranges.items():
        if not df[col].between(lo, hi).all():
            errors.append(f"{col} outside [{lo}, {hi}]")

    report = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "rows": len(df),
        "errors": errors,
        "warnings": warnings,
        "status": "FAIL" if errors else "PASS",
    }
    if write_report:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        (PROCESSED_DIR / "validation_report.json").write_text(json.dumps(report, indent=2))
    if errors:
        raise ValueError(f"Validation failed: {errors}")
    return report
