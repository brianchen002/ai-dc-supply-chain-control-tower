"""Purchase order tracking — filterable, sortable, risk-flagged."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

st.set_page_config(page_title="PO Tracking — Control Tower", page_icon="📦", layout="wide")

from dashboard.ui import (RISK_DOT, ai_client, bootstrap, load_df,
                          mode_caption, money, sidebar_common)
from src.llm.workflows import po_risk_narrative

conn = bootstrap()
sidebar_common()

st.title("📦 Purchase Order Tracking")
st.markdown("Every open order with live status, model-predicted delay risk and a "
            "recommended action. High-risk rows carry a colored risk marker.")

df = load_df("SELECT * FROM purchase_orders WHERE procurement_status != 'Cancelled'")
df["delivery_month"] = pd.to_datetime(
    df["current_eta"].fillna(df["actual_delivery_date"])).dt.strftime("%Y-%m")
sites = load_df("SELECT data_center_site, region FROM sites")
df = df.merge(sites, left_on="destination_site", right_on="data_center_site",
              how="left", suffixes=("", "_site"))

# ---- Filters --------------------------------------------------------------------
f = st.columns(4)
sup_sel = f[0].multiselect("Supplier", sorted(df["supplier_name"].unique()))
cat_sel = f[1].multiselect("Equipment category", sorted(df["equipment_category"].unique()))
site_sel = f[2].multiselect("Data center", sorted(df["destination_site"].unique()))
region_sel = f[3].multiselect("Region", sorted(df["region"].dropna().unique()))
g = st.columns(4)
risk_sel = g[0].multiselect("Risk level", ["Critical", "High", "Moderate", "Low"])
ship_sel = g[1].multiselect("Shipment status", sorted(df["shipment_status"].unique()))
proc_sel = g[2].multiselect("Procurement status", sorted(df["procurement_status"].unique()))
month_sel = g[3].multiselect("Delivery month", sorted(df["delivery_month"].dropna().unique()))

view = df.copy()
for col, sel in [("supplier_name", sup_sel), ("equipment_category", cat_sel),
                 ("destination_site", site_sel), ("region", region_sel),
                 ("risk_level", risk_sel), ("shipment_status", ship_sel),
                 ("procurement_status", proc_sel), ("delivery_month", month_sel)]:
    if sel:
        view = view[view[col].isin(sel)]

# ---- Sorting ---------------------------------------------------------------------
sort_by = st.selectbox("Sort by", [
    "Highest risk", "Largest financial exposure", "Longest delay",
    "Closest required-on-site date", "Largest deployment impact"])
crit_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
view["_deploy_impact"] = (view["total_order_value"]
                          * view["equipment_criticality"].map(crit_rank))
sort_map = {
    "Highest risk": ("risk_score", False),
    "Largest financial exposure": ("total_order_value", False),
    "Longest delay": ("delay_days", False),
    "Closest required-on-site date": ("required_on_site_date", True),
    "Largest deployment impact": ("_deploy_impact", False),
}
col, asc = sort_map[sort_by]
view = view.sort_values(col, ascending=asc, na_position="last")

view["risk"] = view["risk_level"].map(RISK_DOT).fillna("✅") + " " + view["risk_level"].fillna("Delivered")
st.caption(f"{len(view)} POs · {money(view['total_order_value'].sum())} total value")

st.dataframe(
    view[["purchase_order_id", "risk", "supplier_name", "equipment_category",
          "destination_site", "total_order_value", "procurement_status",
          "shipment_status", "original_eta", "current_eta",
          "required_on_site_date", "delay_days", "delay_probability",
          "risk_score", "recommended_action"]],
    width="stretch", hide_index=True, height=460,
    column_config={
        "purchase_order_id": "PO",
        "risk": "Risk",
        "supplier_name": "Supplier",
        "equipment_category": "Equipment",
        "destination_site": "Site",
        "total_order_value": st.column_config.NumberColumn("Value", format="$%.0f"),
        "procurement_status": "Procurement",
        "shipment_status": "Shipment",
        "original_eta": "Original ETA",
        "current_eta": "Current ETA",
        "required_on_site_date": "Required on site",
        "delay_days": st.column_config.NumberColumn("Delay (d)", format="%.0f"),
        "delay_probability": st.column_config.NumberColumn("P(delay)", format="percent"),
        "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100,
                                                      format="%.0f"),
        "recommended_action": "Recommended action",
    },
)

st.divider()

# ---- PO detail --------------------------------------------------------------------
st.subheader("PO detail")
open_view = view[~view["procurement_status"].isin(["Delivered"])]
if open_view.empty:
    st.info("No open POs in the current filter.")
    st.stop()
sel = st.selectbox("Inspect a purchase order", open_view["purchase_order_id"],
                   format_func=lambda p: (
                       f"{p} · {open_view.set_index('purchase_order_id').loc[p, 'equipment_category']}"
                       f" · {money(open_view.set_index('purchase_order_id').loc[p, 'total_order_value'])}"))
row = open_view.set_index("purchase_order_id").loc[sel]

d1, d2 = st.columns([1, 1.15])
with d1:
    st.markdown(f"### {sel} — {row['equipment_type']}")
    st.markdown(
        f"{RISK_DOT.get(row['risk_level'], '⚪')} **{row['risk_level']}** "
        f"(score {row['risk_score']:.0f}, P(delay) {row['delay_probability']:.0%})")
    st.markdown(
        f"**{row['order_quantity']}×** from **{row['supplier_name']}** "
        f"({row['manufacturer']}, {row['origin_country']}) → **{row['destination_site']}** · "
        f"{money(row['total_order_value'])}\n\n"
        f"Ordered {row['purchase_order_date']} · {row['shipping_mode']} via "
        f"{row['freight_forwarder']} ({row['incoterm']}) · customs: {row['customs_status']}\n\n"
        f"Original ETA **{row['original_eta']}** → current ETA **{row['current_eta']}** · "
        f"required on site **{row['required_on_site_date']}** · "
        f"model-predicted delivery **{row.get('predicted_delivery_date') or '—'}**")
    drivers = json.loads(row.get("top_risk_drivers") or "[]")
    if drivers:
        st.markdown("**Primary risk drivers**")
        for d in drivers:
            st.markdown(f"- {d}")
    st.markdown(f"**Recommended action:** {row['recommended_action']}")

with d2:
    st.markdown("### 🤖 Supplier-call prep note")
    if st.button("Generate narrative", type="primary", key=f"nar_btn_{sel}"):
        with st.spinner("Composing…"):
            st.session_state[f"nar_result_{sel}"] = po_risk_narrative(conn, sel, ai_client())
    res = st.session_state.get(f"nar_result_{sel}")
    if res:
        st.markdown(res["text"])
        st.caption(f"mode: {res['mode']}")
    else:
        st.caption("A ≤120-word brief for the buyer heading into the supplier call — "
                   "grounded in this PO's model outputs.")
mode_caption()
