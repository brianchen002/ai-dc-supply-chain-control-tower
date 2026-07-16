"""Supply Chain Control Tower — executive home page."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="AI DC Supply Chain Control Tower",
                   page_icon="🗼", layout="wide")

from dashboard.ui import (RISK_COLORS, SEVERITY_DOT, ai_client, bootstrap,
                          data_disclaimer, load_df, mode_caption, money,
                          sidebar_common)
from src.llm.workflows import executive_brief

conn = bootstrap()
sidebar_common()

st.title("🗼 AI Data Center Supply Chain Control Tower")
st.markdown("**Automated PO tracking, lead-time forecasting, and supply risk "
            "intelligence** for a rapidly scaling AI infrastructure buildout — "
            "8 data center sites, 12 equipment categories, 30 suppliers.")
data_disclaimer()
mode_caption()

# ---- KPIs --------------------------------------------------------------------
open_pos = load_df("""SELECT * FROM purchase_orders
                      WHERE procurement_status NOT IN ('Delivered','Cancelled')""")
delivered = load_df("""SELECT actual_delivery_date, supplier_committed_date, order_quantity
                       FROM purchase_orders WHERE procurement_status = 'Delivered'""")
prev_otd = None
if not delivered.empty:
    d = delivered.copy()
    d["on_time"] = (pd.to_datetime(d["actual_delivery_date"])
                    <= pd.to_datetime(d["supplier_committed_date"]) + pd.Timedelta(days=3))
    otd = d["on_time"].mean()
    recent = pd.to_datetime(d["actual_delivery_date"]) >= (pd.Timestamp.today() - pd.Timedelta(days=90))
    prev_otd = d.loc[~recent, "on_time"].mean()
    recent_otd = d.loc[recent, "on_time"].mean()

in_transit = open_pos[open_pos["shipment_status"].isin(["In Transit", "Customs", "Delayed"])]
at_risk = open_pos[open_pos["risk_level"].isin(["High", "Critical"])]
critical = open_pos[open_pos["risk_level"] == "Critical"]
readiness = load_df("SELECT * FROM site_readiness")

r1 = st.columns(5)
r1[0].metric("Total PO value", money(load_df(
    "SELECT SUM(total_order_value) v FROM purchase_orders WHERE procurement_status != 'Cancelled'").iloc[0, 0]))
r1[1].metric("Active POs", len(open_pos), help="Not yet delivered or cancelled")
r1[2].metric("In transit", len(in_transit),
             delta=money(in_transit["total_order_value"].sum()), delta_color="off")
r1[3].metric("POs at risk", len(at_risk),
             delta=money(at_risk["total_order_value"].sum()) + " exposed",
             delta_color="inverse")
r1[4].metric("Critical delays", len(critical),
             delta=f"{money(critical['total_order_value'].sum())} exposed",
             delta_color="inverse")

r2 = st.columns(5)
avg_lead = open_pos["current_expected_lead_time_days"].mean()
r2[0].metric("Avg expected lead time", f"{avg_lead:.0f} d",
             delta=f"{avg_lead - open_pos['planned_lead_time_days'].mean():+.0f} d vs plan",
             delta_color="inverse")
slipping = open_pos[open_pos["delay_days"] > 0]
r2[1].metric("Avg delay (slipping POs)", f"{slipping['delay_days'].mean():.0f} d",
             delta=f"{len(slipping)} POs slipping", delta_color="off")
if not delivered.empty:
    r2[2].metric("On-time delivery", f"{otd:.0%}",
                 delta=(f"{(recent_otd - prev_otd) * 100:+.0f} pts last 90d"
                        if prev_otd == prev_otd else None),
                 delta_color="normal")
sup_risk = load_df("""SELECT SUM(open_value) v FROM supplier_scorecard
                      WHERE supplier_risk_score >= 60""").iloc[0, 0] or 0
r2[3].metric("Supplier risk exposure", money(sup_risk),
             help="Open value with suppliers scoring ≥60 supplier risk")
r2[4].metric("Deployment readiness", f"{readiness['readiness_score'].mean():.0f}/100",
             delta=f"{(readiness['readiness_status'].isin(['At Risk', 'Critical'])).sum()} sites exposed",
             delta_color="inverse")

st.divider()

# ---- Charts -------------------------------------------------------------------
c1, c2, c3 = st.columns([1.4, 1, 1])
with c1:
    st.subheader("Open value by category")
    by_cat = (open_pos.groupby(["equipment_category", "risk_level"])["total_order_value"]
              .sum().reset_index())
    order = (open_pos.groupby("equipment_category")["total_order_value"]
             .sum().sort_values().index.tolist())
    fig = px.bar(by_cat, y="equipment_category", x="total_order_value", color="risk_level",
                 orientation="h", color_discrete_map=RISK_COLORS,
                 category_orders={"equipment_category": order,
                                  "risk_level": ["Critical", "High", "Moderate", "Low"]},
                 labels={"total_order_value": "open value ($)", "equipment_category": ""})
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="")
    st.plotly_chart(fig, width="stretch")

with c2:
    st.subheader("Pipeline status")
    stat = load_df("""SELECT procurement_status, COUNT(*) n FROM purchase_orders
                      WHERE procurement_status != 'Cancelled' GROUP BY 1""")
    fig = px.funnel(stat.set_index("procurement_status")
                    .reindex(["Ordered", "In Production", "Shipped", "Delivered"])
                    .reset_index(), x="n", y="procurement_status",
                    labels={"n": "", "procurement_status": ""})
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10))
    fig.update_traces(marker_color="#4F46E5")
    st.plotly_chart(fig, width="stretch")

with c3:
    st.subheader("Open PO risk mix")
    mix = open_pos["risk_level"].value_counts().reset_index()
    fig = px.pie(mix, names="risk_level", values="count", hole=0.55,
                 color="risk_level", color_discrete_map=RISK_COLORS,
                 category_orders={"risk_level": ["Critical", "High", "Moderate", "Low"]})
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="")
    st.plotly_chart(fig, width="stretch")

st.divider()

# ---- AI brief + alert feed -------------------------------------------------------
left, right = st.columns([1.3, 1])
with left:
    st.subheader("🤖 Executive brief")
    st.markdown("One click compresses the whole control tower — top escalations, "
                "systemic patterns, deployment impact — into a leadership brief.")
    if st.button("Generate executive brief", type="primary"):
        with st.spinner("Synthesizing the control-tower snapshot…"):
            st.session_state["brief"] = executive_brief(conn, ai_client())
    if "brief" in st.session_state:
        st.markdown(st.session_state["brief"]["text"])

with right:
    st.subheader("Live risk alerts")
    alerts = load_df("SELECT * FROM alerts LIMIT 12")
    n_all = load_df("SELECT COUNT(*) n FROM alerts").iloc[0, 0]
    st.caption(f"{n_all} open alerts — top 12 by severity")
    for _, a in alerts.iterrows():
        st.markdown(f"{SEVERITY_DOT[a['severity']]} **{a['alert_type']}** · {a['message']}")
