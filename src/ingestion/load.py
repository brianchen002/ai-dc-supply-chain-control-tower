"""Ingestion stage — lands source feeds as DataFrames.

In this prototype the feeds are the synthetic CSVs in data/synthetic/.
In production this module is the integration seam: OMS/ERP purchase-order
webhooks, WMS inventory snapshots, carrier tracking pulls and the
infrastructure deployment plan would land here, each mapped to the same
frames the rest of the pipeline consumes.
"""
from __future__ import annotations

import pandas as pd

from config.settings import SYNTHETIC_DIR

SOURCES = ["purchase_orders", "suppliers", "sites", "equipment_catalog",
           "demand_plan", "supplier_emails"]


def load_sources() -> dict[str, pd.DataFrame]:
    missing = [s for s in SOURCES if not (SYNTHETIC_DIR / f"{s}.csv").exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing source feeds {missing} — run "
            f"`python -m src.data_generation.generate` first."
        )
    return {s: pd.read_csv(SYNTHETIC_DIR / f"{s}.csv") for s in SOURCES}
