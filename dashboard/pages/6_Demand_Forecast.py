"""Demand forecasting — future demand vs confirmed supply, gap detection."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Demand Forecast — Control Tower",
                   page_icon="📈", layout="wide")

from dashboard.ui import bootstrap, load_df, sidebar_common

conn = bootstrap()
sidebar_common()

st.title("📈 Demand Forecasting & Supply Gaps")
st.markdown("Historical order demand with a trend forecast (80% confidence band), "
            "checked against planned site demand and expected deliveries from "
            "open POs — the gap view answers *are current orders sufficient for "
            "planned capacity expansion?*")

fc = load_df("SELECT * FROM demand_forecast")
gap = load_df("SELECT * FROM supply_gap")

cat = st.selectbox("Equipment category", sorted(fc["equipment_category"].unique()),
                   index=sorted(fc["equipment_category"].unique()).index("GPU Servers")
                   if "GPU Servers" in fc["equipment_category"].unique() else 0)

# ---- History + forecast --------------------------------------------------------------
sub = fc[fc["equipment_category"] == cat].sort_values("month")
hist = sub[sub["kind"] == "history"]
fore = sub[sub["kind"] == "forecast"]

fig = go.Figure()
fig.add_trace(go.Bar(x=hist["month"], y=hist["units"], name="historical orders",
                     marker_color="#C7D2FE"))
if not fore.empty:
    fig.add_trace(go.Scatter(x=fore["month"], y=fore["hi"], mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fore["month"], y=fore["lo"], mode="lines",
                             line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(79,70,229,0.15)", name="80% interval"))
    fig.add_trace(go.Scatter(x=fore["month"], y=fore["units"], mode="lines+markers",
                             line=dict(color="#4F46E5", dash="dash"), name="forecast"))
fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                  yaxis_title="units ordered / forecast", legend_title_text="")
st.plotly_chart(fig, width="stretch")
st.caption("Forecast = linear demand trend with residual-based intervals — "
           "deliberately simple for an 18-point monthly series "
           "(`MODEL_DOCUMENTATION.md §6`).")

st.divider()

# ---- Supply vs demand ------------------------------------------------------------------
st.subheader("Planned demand vs confirmed inbound supply")
site_options = ["All sites"] + sorted(gap["site"].dropna().unique().tolist())
site_pick = st.selectbox("Site", site_options)

gsub = gap[gap["equipment_category"] == cat].copy()
if site_pick != "All sites":
    gsub = gsub[gsub["site"] == site_pick]
monthly = (gsub.groupby("month")[["planned_demand", "expected_deliveries"]]
           .sum().reset_index().sort_values("month"))
monthly = monthly[monthly["month"] >= pd.Timestamp.today().strftime("%Y-%m")]
monthly["gap"] = monthly["planned_demand"] - monthly["expected_deliveries"]

fig2 = go.Figure()
fig2.add_trace(go.Bar(x=monthly["month"], y=monthly["planned_demand"],
                      name="planned demand", marker_color="#9CA3AF"))
fig2.add_trace(go.Bar(x=monthly["month"], y=monthly["expected_deliveries"],
                      name="expected deliveries (open POs)", marker_color="#4F46E5"))
fig2.add_trace(go.Scatter(x=monthly["month"], y=monthly["gap"], mode="lines+markers",
                          name="supply gap", line=dict(color="#DC2626")))
fig2.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), barmode="group",
                   yaxis_title="units", legend_title_text="")
st.plotly_chart(fig2, width="stretch")

shortfall = monthly[monthly["gap"] > 0]
if not shortfall.empty:
    total_gap = int(shortfall["gap"].sum())
    st.error(f"⚠ **Supply gap:** planned demand exceeds confirmed inbound supply by "
             f"**{total_gap} units of {cat}** across {len(shortfall)} months "
             f"({', '.join(shortfall['month'].tolist()[:4])}"
             f"{'…' if len(shortfall) > 4 else ''}). Procurement should raise or "
             f"accelerate POs now — current orders are NOT sufficient for the "
             f"planned expansion.")
else:
    st.success(f"Confirmed inbound supply covers planned {cat} demand in every "
               "forecast month for this selection.")

# ---- Cross-category gap summary ----------------------------------------------------------
st.subheader("Where demand outruns supply (all categories)")
summary = (gap[gap["month"] >= pd.Timestamp.today().strftime("%Y-%m")]
           .groupby("equipment_category")[["planned_demand", "expected_deliveries"]]
           .sum().reset_index())
summary["gap_units"] = summary["planned_demand"] - summary["expected_deliveries"]
summary["coverage"] = (summary["expected_deliveries"]
                       / summary["planned_demand"].replace(0, float("nan")))
summary = summary.sort_values("gap_units", ascending=False)
st.dataframe(
    summary, hide_index=True, width="stretch",
    column_config={
        "equipment_category": "Category",
        "planned_demand": "Planned demand (units)",
        "expected_deliveries": "Confirmed inbound (units)",
        "gap_units": st.column_config.NumberColumn("Gap (units)", format="%.0f"),
        "coverage": st.column_config.NumberColumn("Coverage", format="percent"),
    })
st.caption("Positive gap = procurement timing risk: planned capacity needs more "
           "units than open POs will deliver in the window.")
