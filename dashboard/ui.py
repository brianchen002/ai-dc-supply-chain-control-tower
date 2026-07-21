"""Shared dashboard helpers (not a page)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import DB_PATH
from src.db import get_connection
from src.llm.client import get_client

RISK_COLORS = {"Critical": "#DC2626", "High": "#EA580C",
               "Moderate": "#2563EB", "Low": "#9CA3AF"}
RISK_DOT = {"Critical": "🔴", "High": "🟠", "Moderate": "🔵", "Low": "⚪"}
READINESS_COLORS = {"Deployment Ready": "#16A34A", "On Track": "#2563EB",
                    "At Risk": "#EA580C", "Critical": "#DC2626"}
SEVERITY_DOT = {"critical": "🔴", "high": "🟠", "medium": "🔵"}


@st.cache_resource(show_spinner="Preparing data (first run executes the full pipeline)…")
def _connect():
    return get_connection()  # rebuilds automatically if DB is missing or corrupt


def bootstrap():
    """Self-healing connection: if the cached connection or its underlying
    file has gone bad, drop it, rebuild the database, and reconnect."""
    conn = _connect()
    try:
        conn.execute("SELECT 1 FROM purchase_orders LIMIT 1").fetchone()
        return conn
    except sqlite3.Error:
        _connect.clear()
        try:
            Path(DB_PATH).unlink()
        except OSError:
            pass
        return _connect()


@st.cache_resource
def ai_client():
    return get_client()


@st.cache_data(ttl=600)
def model_meta(name: str) -> dict:
    conn = bootstrap()
    row = conn.execute("SELECT payload FROM model_metrics WHERE name = ?", (name,)).fetchone()
    return json.loads(row["payload"]) if row else {}


def load_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, bootstrap(), params=params)


def money(x: float) -> str:
    if x is None or pd.isna(x):
        return "—"
    if abs(x) >= 1e9:
        return f"${x / 1e9:,.2f}B"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.1f}M"
    return f"${x:,.0f}"


def mode_caption() -> None:
    client = ai_client()
    icon = "🟢" if client.is_live else "⚪"
    st.caption(f"{icon} **AI narration:** {client.label} — deterministic models "
               "drive every number; the LLM only narrates. Set `ANTHROPIC_API_KEY` "
               "for live Claude narration.")


def data_disclaimer() -> None:
    st.caption("🏭 All data is **synthetically generated** (seeded, causally "
               "consistent) for demonstration. Manufacturer names are used for "
               "realism; figures are simulated.")


def sidebar_common() -> None:
    conn = bootstrap()
    with st.sidebar:
        st.markdown("### AI DC Supply Chain\n### Control Tower")
        n = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
        run = conn.execute("SELECT payload FROM model_metrics WHERE name='pipeline_run'").fetchone()
        run_at = json.loads(run["payload"])["run_at"][:16].replace("T", " ") if run else "—"
        st.caption(f"{n} purchase orders · pipeline run {run_at}")
        if st.button("↻ Re-run pipeline (fresh data)", width="stretch"):
            from src.pipeline import run_pipeline
            with st.spinner("Regenerating data and retraining models…"):
                run_pipeline(force_data=True, verbose=False)
            st.cache_resource.clear()
            st.cache_data.clear()
            st.rerun()
