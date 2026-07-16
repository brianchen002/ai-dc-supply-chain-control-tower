"""Supplier performance analytics — scorecards and risk matrix."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Supplier Analytics — Control Tower",
                   page_icon="🏭", layout="wide")

from dashboard.ui import bootstrap, load_df, money, sidebar_common

conn = bootstrap()
sidebar_common()

st.title("🏭 Supplier Performance Analytics")
sc = load_df("SELECT * FROM supplier_scorecard")
st.markdown(f"{len(sc)} suppliers · {money(sc['open_value'].sum())} open value · "
            "scorecard dimensions are 0–100 (higher is better); the overall "
            "supplier risk score inverts and weights them.")

# ---- Risk matrix ---------------------------------------------------------------------
st.subheader("Supplier risk matrix")
mat = sc[sc["active_pos"] > 0].copy()
fig = px.scatter(
    mat, x="supply_chain_exposure", y="performance_risk",
    size="open_value", color="supplier_risk_score",
    color_continuous_scale=["#16A34A", "#EAB308", "#DC2626"],
    hover_name="supplier_name",
    hover_data={"open_value": ":$,.0f", "active_pos": True,
                "supply_chain_exposure": ":.0f", "performance_risk": ":.0f"},
    labels={"supply_chain_exposure": "Supply chain exposure →",
            "performance_risk": "Supplier performance risk →",
            "supplier_risk_score": "risk score"},
    size_max=52)
fig.add_hline(y=float(mat["performance_risk"].median()), line_dash="dot",
              line_color="#9CA3AF")
fig.add_vline(x=float(mat["supply_chain_exposure"].median()), line_dash="dot",
              line_color="#9CA3AF")
fig.add_annotation(x=mat["supply_chain_exposure"].max(), y=mat["performance_risk"].max(),
                   text="⚠ high exposure × high risk", showarrow=False,
                   xanchor="right", font=dict(color="#DC2626"))
fig.update_layout(height=440, margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, width="stretch")
st.caption("Bubble size = open PO value. Top-right quadrant = concentrated spend "
           "with underperforming suppliers — the dual-sourcing shortlist.")

st.divider()

# ---- Scorecard table -------------------------------------------------------------------
st.subheader("Supplier scorecards")
show = sc[["supplier_name", "categories", "active_pos", "open_value",
           "on_time_delivery_rate", "avg_realized_delay_days", "avg_lead_time_days",
           "capacity_utilization", "avg_open_delay_probability",
           "critical_equipment_exposure", "delivery_reliability",
           "lead_time_stability", "capacity_risk", "financial_exposure",
           "concentration_score", "supplier_risk_score"]]
st.dataframe(
    show, hide_index=True, width="stretch", height=420,
    column_config={
        "supplier_name": "Supplier", "categories": "Categories",
        "active_pos": "Active POs",
        "open_value": st.column_config.NumberColumn("Open value", format="$%.0f"),
        "on_time_delivery_rate": st.column_config.NumberColumn("OTD", format="percent"),
        "avg_realized_delay_days": st.column_config.NumberColumn("Avg delay (d)", format="%.1f"),
        "avg_lead_time_days": st.column_config.NumberColumn("Avg lead (d)", format="%.0f"),
        "capacity_utilization": st.column_config.NumberColumn("Capacity util", format="percent"),
        "avg_open_delay_probability": st.column_config.NumberColumn("Open P(delay)", format="percent"),
        "critical_equipment_exposure": st.column_config.NumberColumn("Critical exposure", format="$%.0f"),
        "delivery_reliability": st.column_config.ProgressColumn("Reliability", min_value=0, max_value=100, format="%.0f"),
        "lead_time_stability": st.column_config.ProgressColumn("Stability", min_value=0, max_value=100, format="%.0f"),
        "capacity_risk": st.column_config.ProgressColumn("Capacity", min_value=0, max_value=100, format="%.0f"),
        "financial_exposure": st.column_config.ProgressColumn("Exposure", min_value=0, max_value=100, format="%.0f"),
        "concentration_score": st.column_config.ProgressColumn("Diversification", min_value=0, max_value=100, format="%.0f"),
        "supplier_risk_score": st.column_config.NumberColumn("⚠ Risk score", format="%.1f"),
    })

st.divider()

# ---- Supplier deep dive -------------------------------------------------------------------
st.subheader("Supplier deep dive")
pick = st.selectbox("Supplier", sc.sort_values("open_value", ascending=False)["supplier_name"])
srow = sc.set_index("supplier_name").loc[pick]

c = st.columns(5)
c[0].metric("Overall risk score", f"{srow['supplier_risk_score']:.0f}/100",
            help="Higher = riskier")
c[1].metric("On-time delivery", f"{srow['on_time_delivery_rate']:.0%}"
            if pd.notna(srow["on_time_delivery_rate"]) else "—")
c[2].metric("Capacity utilization", f"{srow['capacity_utilization']:.0%}")
c[3].metric("Open exposure", money(srow["open_value"]))
c[4].metric("Critical equipment exposure", money(srow["critical_equipment_exposure"]))

d1, d2 = st.columns([1.2, 1])
with d1:
    trend = load_df("""SELECT strftime('%Y-%m', purchase_order_date) AS month,
                              AVG(actual_lead_time_days) AS avg_lead, COUNT(*) AS n
                       FROM purchase_orders
                       WHERE supplier_name = ? AND procurement_status = 'Delivered'
                       GROUP BY 1 ORDER BY 1""", (pick,))
    if len(trend) > 1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend["month"], y=trend["avg_lead"],
                                 mode="lines+markers", line=dict(color="#4F46E5"),
                                 name="avg lead time"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10),
                          title="Realized lead time by order month (worsening = rising)",
                          yaxis_title="days")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Not enough delivered history for a trend.")

with d2:
    open_sup = load_df("""SELECT purchase_order_id, equipment_category, destination_site,
                                 total_order_value, risk_level, current_eta
                          FROM purchase_orders
                          WHERE supplier_name = ?
                            AND procurement_status NOT IN ('Delivered','Cancelled')
                          ORDER BY total_order_value DESC LIMIT 10""", (pick,))
    st.markdown("**Largest open POs**")
    st.dataframe(open_sup, hide_index=True, width="stretch",
                 column_config={"total_order_value": st.column_config.NumberColumn(
                     "Value", format="$%.0f")})
