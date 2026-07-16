"""Infrastructure readiness — supply chain performance → deployment schedules."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Infrastructure Readiness — Control Tower",
                   page_icon="🏗️", layout="wide")

from dashboard.ui import READINESS_COLORS, RISK_DOT, bootstrap, load_df, money, sidebar_common

conn = bootstrap()
sidebar_common()

st.title("🏗️ Infrastructure Deployment Readiness")
st.markdown("Connects supply chain performance to data center deployment: each "
            "site's readiness score blends delivered %, critical-equipment "
            "delivery, at-risk POs and schedule pressure "
            "(weights in `config/settings.py`).")

rd = load_df("SELECT * FROM site_readiness ORDER BY readiness_score")

# ---- Site cards -----------------------------------------------------------------------
cols = st.columns(4)
for i, (_, s) in enumerate(rd.iterrows()):
    with cols[i % 4]:
        color = READINESS_COLORS[s["readiness_status"]]
        st.markdown(
            f"<div style='border:1px solid #E5E7EB;border-left:6px solid {color};"
            f"border-radius:8px;padding:10px 14px;margin-bottom:12px'>"
            f"<b>{s['data_center_site']}</b> · {s['metro']}<br>"
            f"<span style='color:{color};font-weight:600'>{s['readiness_status']}"
            f" · {s['readiness_score']:.0f}/100</span><br>"
            f"<small>{s['planned_compute_capacity_mw']} MW · "
            f"{int(s['planned_gpu_capacity']):,} GPUs · {s['project_phase']}<br>"
            f"required {s['required_capacity_date']}</small></div>",
            unsafe_allow_html=True)

# ---- Readiness table ----------------------------------------------------------------------
st.subheader("Site detail")
st.dataframe(
    rd[["data_center_site", "metro", "readiness_status", "readiness_score",
        "delivered_pct", "critical_delivered_pct", "open_pos", "at_risk_pos",
        "value_at_risk", "critical_outstanding", "potential_schedule_impact_days",
        "required_capacity_date"]],
    hide_index=True, width="stretch",
    column_config={
        "data_center_site": "Site", "metro": "Metro",
        "readiness_status": "Status",
        "readiness_score": st.column_config.ProgressColumn("Readiness", min_value=0,
                                                           max_value=100, format="%.0f"),
        "delivered_pct": st.column_config.NumberColumn("Delivered %", format="%.0f%%"),
        "critical_delivered_pct": st.column_config.NumberColumn("Critical delivered %",
                                                                format="%.0f%%"),
        "open_pos": "Open POs", "at_risk_pos": "At-risk POs",
        "value_at_risk": st.column_config.NumberColumn("Value at risk", format="$%.0f"),
        "critical_outstanding": "Critical outstanding",
        "potential_schedule_impact_days": st.column_config.NumberColumn(
            "Schedule impact (d)", format="%.0f",
            help="Latest model-predicted arrival of critical equipment vs installation start"),
        "required_capacity_date": "Required capacity",
    })

st.divider()

# ---- Per-site drill-down ---------------------------------------------------------------
st.subheader("What is blocking each site?")
pick = st.selectbox("Site", rd["data_center_site"])
srow = rd.set_index("data_center_site").loc[pick]

c = st.columns(4)
c[0].metric("Readiness", f"{srow['readiness_score']:.0f}/100", srow["readiness_status"],
            delta_color="off")
c[1].metric("Value at risk", money(srow["value_at_risk"]))
c[2].metric("Critical items outstanding", int(srow["critical_outstanding"]))
c[3].metric("Potential schedule impact", f"{int(srow['potential_schedule_impact_days'])} d",
            help="vs installation start date")

blockers = load_df("""SELECT purchase_order_id, equipment_category, equipment_type,
                             supplier_name, total_order_value, risk_level, risk_score,
                             current_eta, predicted_delivery_date, required_on_site_date,
                             recommended_action
                      FROM purchase_orders
                      WHERE destination_site = ?
                        AND procurement_status NOT IN ('Delivered','Cancelled')
                        AND equipment_criticality = 'critical'
                      ORDER BY risk_score DESC""", (pick,))
blockers["risk"] = blockers["risk_level"].map(RISK_DOT) + " " + blockers["risk_level"]
st.markdown(f"**Critical-path equipment still inbound ({len(blockers)})**")
st.dataframe(
    blockers[["purchase_order_id", "risk", "equipment_type", "supplier_name",
              "total_order_value", "current_eta", "predicted_delivery_date",
              "required_on_site_date", "recommended_action"]],
    hide_index=True, width="stretch",
    column_config={"total_order_value": st.column_config.NumberColumn("Value", format="$%.0f")})

worst = blockers.head(3)
if not worst.empty:
    st.markdown("**Recommended operational actions**")
    for _, b in worst.iterrows():
        st.markdown(f"- `{b['purchase_order_id']}` ({b['equipment_type']}): "
                    f"{b['recommended_action']}")
    if int(srow["potential_schedule_impact_days"]) > 0:
        st.markdown(f"- Site PM: hold a re-sequencing review — critical equipment is "
                    f"predicted up to **{int(srow['potential_schedule_impact_days'])} days** "
                    f"past installation start; identify install work that can proceed "
                    f"without the late items.")
