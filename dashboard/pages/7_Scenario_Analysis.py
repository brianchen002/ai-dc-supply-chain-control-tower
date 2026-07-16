"""Scenario analysis — interactive what-if planning over the open PO book.

The engine applies documented, deterministic adjustments on top of the
model outputs (logit shifts sized from the generator's causal coefficients,
ETA shifts proportional to planned lead time). It is an approximation for
planning conversations — not a re-run of the ML pipeline — and says so.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Scenario Analysis — Control Tower",
                   page_icon="🧪", layout="wide")

from dashboard.ui import bootstrap, load_df, money, sidebar_common

conn = bootstrap()
sidebar_common()

st.title("🧪 Scenario Analysis")
st.markdown("Stress-test the open order book: shift supplier and logistics "
            "assumptions and see purchase-order risk, deployment readiness and "
            "supply gaps respond. Adjustments are calibrated to the same causal "
            "coefficients the risk model learned from.")

# ---- Presets --------------------------------------------------------------------------
PRESETS = {
    "IB lead times +30%": {"ib_lead": 30},
    "Transformer capacity −20%": {"tf_cap": 20},
    "GPU demand +50%": {"gpu_demand": 50},
    "Air freight for critical": {"air_critical": True},
    "Second source qualified": {"alt_qualified": True},
}
pc = st.columns(len(PRESETS) + 1)
for i, (name, vals) in enumerate(PRESETS.items()):
    if pc[i].button(name, width="stretch"):
        st.session_state.update({f"sc_{k}": v for k, v in vals.items()})
if pc[-1].button("Reset", width="stretch", type="secondary"):
    for k in list(st.session_state):
        if k.startswith("sc_"):
            del st.session_state[k]

s1, s2, s3, s4 = st.columns(4)
ib_lead = s1.slider("InfiniBand lead-time increase (%)", 0, 50, key="sc_ib_lead")
tf_cap = s2.slider("Transformer supplier capacity decline (%)", 0, 40, key="sc_tf_cap")
gpu_demand = s3.slider("GPU demand growth (%)", 0, 100, key="sc_gpu_demand")
glob_lead = s4.slider("Global lead-time increase (%)", 0, 30, key="sc_glob_lead")
t1, t2, t3 = st.columns(3)
air_critical = t1.toggle("Air freight for critical equipment", key="sc_air_critical")
alt_qualified = t2.toggle("Secondary supplier qualified (constrained categories)", key="sc_alt_qualified")
buffer_add = t3.slider("Extra inventory safety buffer (days)", 0, 30, key="sc_buffer")

# ---- Scenario engine --------------------------------------------------------------------
pos = load_df("""SELECT * FROM purchase_orders
                 WHERE procurement_status NOT IN ('Delivered','Cancelled')""")
pos["p0"] = pos["delay_probability"].clip(0.01, 0.99)
pos["eta0"] = pd.to_datetime(pos["predicted_delivery_date"].fillna(pos["current_eta"]))
pos["required_dt"] = pd.to_datetime(pos["required_on_site_date"])

logit = np.log(pos["p0"] / (1 - pos["p0"]))
eta_shift = np.zeros(len(pos))

is_ib = pos["equipment_category"] == "InfiniBand Switches"
logit += np.where(is_ib, 2.2 * ib_lead / 100, 0)
eta_shift += np.where(is_ib, pos["planned_lead_time_days"] * ib_lead / 100, 0)

is_tf = pos["equipment_category"] == "Transformers"
logit += np.where(is_tf, 3.2 * tf_cap / 100, 0)
eta_shift += np.where(is_tf, pos["planned_lead_time_days"] * tf_cap / 100 * 0.5, 0)

logit += 1.5 * glob_lead / 100
eta_shift += pos["planned_lead_time_days"] * glob_lead / 100

if air_critical:
    conv = (pos["equipment_criticality"] == "critical") & (pos["shipping_mode"] == "Ocean")
    logit -= np.where(conv, 0.45 + 0.8 * 0.25, 0)
    eta_shift -= np.where(conv, 25, 0)

if alt_qualified:
    helped = (pos["alternative_supplier_available"] == 0) & \
             pos["equipment_category"].isin(
                 ["NVIDIA GPU Systems", "InfiniBand Switches", "Transformers",
                  "Backup Generators", "GPU Servers", "Cooling Systems"])
    logit -= np.where(helped, 0.9, 0)

pos["p1"] = 1 / (1 + np.exp(-logit))
pos["eta1"] = pos["eta0"] + pd.to_timedelta(np.round(eta_shift), unit="D")
buffer_dt = pd.to_timedelta(buffer_add, unit="D")

pos["at_risk0"] = (pos["p0"] > 0.5) | (pos["eta0"] > pos["required_dt"])
pos["at_risk1"] = (pos["p1"] > 0.5) | (pos["eta1"] > pos["required_dt"] + buffer_dt)
pos["late_days0"] = (pos["eta0"] - pos["required_dt"]).dt.days.clip(lower=0)
pos["late_days1"] = ((pos["eta1"] - (pos["required_dt"] + buffer_dt))
                     .dt.days.clip(lower=0))

# ---- Before / after KPIs -------------------------------------------------------------------
k = st.columns(5)
n0, n1 = int(pos["at_risk0"].sum()), int(pos["at_risk1"].sum())
v0 = pos.loc[pos["at_risk0"], "total_order_value"].sum()
v1 = pos.loc[pos["at_risk1"], "total_order_value"].sum()
d0, d1 = pos["late_days0"].mean(), pos["late_days1"].mean()
k[0].metric("POs at risk", n1, delta=f"{n1 - n0:+d} vs baseline", delta_color="inverse")
k[1].metric("Financial exposure", money(v1), delta=f"{money(v1 - v0)}", delta_color="inverse")
k[2].metric("Avg days late vs required", f"{d1:.1f}", delta=f"{d1 - d0:+.1f} d",
            delta_color="inverse")
crit_sites0 = pos.loc[pos["at_risk0"] & (pos["equipment_criticality"] == "critical"),
                      "destination_site"].nunique()
crit_sites1 = pos.loc[pos["at_risk1"] & (pos["equipment_criticality"] == "critical"),
                      "destination_site"].nunique()
k[3].metric("Sites with critical equipment at risk", crit_sites1,
            delta=f"{crit_sites1 - crit_sites0:+d}", delta_color="inverse")

gpu_cats = ["GPU Servers", "NVIDIA GPU Systems", "InfiniBand Switches"]
gap = load_df("SELECT * FROM supply_gap")
future = gap[gap["month"] >= pd.Timestamp.today().strftime("%Y-%m")].copy()
future["planned_demand"] = np.where(
    future["equipment_category"].isin(gpu_cats),
    future["planned_demand"] * (1 + gpu_demand / 100), future["planned_demand"])
short0 = (gap[gap["month"] >= pd.Timestamp.today().strftime("%Y-%m")]
          .assign(g=lambda d: d["planned_demand"] - d["expected_deliveries"])["g"]
          .clip(lower=0).sum())
short1 = (future["planned_demand"] - future["expected_deliveries"]).clip(lower=0).sum()
k[4].metric("Equipment shortage (units)", f"{short1:,.0f}",
            delta=f"{short1 - short0:+,.0f}", delta_color="inverse")

if gpu_demand > 0:
    accel = (future[future["equipment_category"].isin(gpu_cats)]
             .assign(g=lambda d: (d["planned_demand"] - d["expected_deliveries"]).clip(lower=0))
             .groupby("equipment_category")["g"].sum())
    st.warning("**Required procurement acceleration:** " + " · ".join(
        f"{cat}: +{int(units):,} units" for cat, units in accel.items() if units > 0))

st.divider()

# ---- Category impact + movers ----------------------------------------------------------------
c1, c2 = st.columns([1.1, 1])
with c1:
    st.subheader("Value at risk by category — baseline vs scenario")
    by_cat = pos.groupby("equipment_category").apply(
        lambda g: pd.Series({
            "baseline": g.loc[g["at_risk0"], "total_order_value"].sum(),
            "scenario": g.loc[g["at_risk1"], "total_order_value"].sum()}),
        include_groups=False).reset_index()
    by_cat = by_cat.sort_values("scenario", ascending=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=by_cat["equipment_category"], x=by_cat["baseline"],
                         name="baseline", orientation="h", marker_color="#9CA3AF"))
    fig.add_trace(go.Bar(y=by_cat["equipment_category"], x=by_cat["scenario"],
                         name="scenario", orientation="h", marker_color="#DC2626"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                      barmode="group", xaxis_title="value at risk ($)",
                      legend_title_text="")
    st.plotly_chart(fig, width="stretch")

with c2:
    st.subheader("Biggest movers")
    pos["p_shift"] = pos["p1"] - pos["p0"]
    movers = pos.reindex(pos["p_shift"].abs().sort_values(ascending=False).index).head(12)
    show = movers[["purchase_order_id", "equipment_category", "destination_site",
                   "total_order_value", "p0", "p1"]].copy()
    show[["p0", "p1"]] = (show[["p0", "p1"]] * 100).round(0)
    st.dataframe(
        show, hide_index=True, width="stretch", height=420,
        column_config={
            "purchase_order_id": "PO", "equipment_category": "Category",
            "destination_site": "Site",
            "total_order_value": st.column_config.NumberColumn("Value", format="$%.0f"),
            "p0": st.column_config.NumberColumn("P(delay) base", format="%.0f%%"),
            "p1": st.column_config.NumberColumn("P(delay) scenario", format="%.0f%%"),
        })

st.caption("Scenario engine = documented logit/ETA adjustments over model outputs "
           "(coefficients mirror the causal generator) — an approximation for "
           "planning, not a pipeline re-run. Buffer days shift the effective "
           "required-on-site date.")
