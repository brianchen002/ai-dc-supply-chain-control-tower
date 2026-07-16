"""Delay-risk model — evaluation, threshold policy, per-PO explainability."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Delay Risk — Control Tower", page_icon="🎯", layout="wide")

from dashboard.ui import (RISK_COLORS, RISK_DOT, bootstrap, load_df,
                          model_meta, money, sidebar_common)

conn = bootstrap()
sidebar_common()

st.title("🎯 Purchase-Order Delay Risk")
meta = model_meta("delay")
sel_res = next((r for r in meta.get("results", []) if r.get("selected")), {})
st.markdown(
    f"Classifies whether each open PO will **miss its required-on-site date**. "
    f"Threshold policy: *{meta.get('threshold_policy', '')}* — recall is "
    f"prioritized because an unflagged infrastructure delay costs far more "
    f"than a false alarm.")

# ---- Evaluation ---------------------------------------------------------------------
c = st.columns(5)
c[0].metric("Selected model", sel_res.get("model", "—"))
c[1].metric("ROC-AUC", sel_res.get("roc_auc", "—"))
c[2].metric("Recall (miss-catchers)", sel_res.get("recall", "—"),
            help="Share of true delays the model catches at the operating threshold")
c[3].metric("Precision", sel_res.get("precision", "—"))
c[4].metric("F1", sel_res.get("f1", "—"))

left, right = st.columns([1, 1.4])
with left:
    st.subheader("Confusion matrix (test)")
    cm = sel_res.get("confusion_matrix", {})
    if cm:
        z = [[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]]
        fig = go.Figure(go.Heatmap(
            z=z, x=["Predicted on-time", "Predicted delay"],
            y=["Actually on-time", "Actually delayed"],
            text=[[str(v) for v in row] for row in z], texttemplate="%{text}",
            colorscale=[[0, "#EEF2FF"], [1, "#4F46E5"]], showscale=False))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Operating threshold {sel_res.get('threshold')} · "
                   f"{cm['fn']} missed delays vs {cm['fp']} false alarms — "
                   "the asymmetry is deliberate.")
    comp = pd.DataFrame(meta.get("results", []))
    if not comp.empty:
        show = comp[["model", "roc_auc", "precision", "recall", "f1", "threshold"]]
        show.columns = ["Model", "AUC", "Precision", "Recall", "F1", "Threshold"]
        st.dataframe(show, hide_index=True, width="stretch")

with right:
    st.subheader("Open-PO risk distribution")
    open_pos = load_df("""SELECT * FROM purchase_orders
                          WHERE procurement_status NOT IN ('Delivered','Cancelled')""")
    fig = px.histogram(open_pos, x="risk_score", color="risk_level", nbins=40,
                       color_discrete_map=RISK_COLORS,
                       category_orders={"risk_level": ["Critical", "High", "Moderate", "Low"]},
                       labels={"risk_score": "composite risk score (0–100)"})
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                      legend_title_text="", bargap=0.05)
    st.plotly_chart(fig, width="stretch")
    st.caption("Composite score = 45% model delay probability · 25% schedule slack · "
               "15% equipment criticality · 15% supply flexibility "
               "(weights in `config/settings.py`).")

st.divider()

# ---- Explainability showcase ---------------------------------------------------------
st.subheader("Why is this PO risky? — per-order drivers")
high = open_pos[open_pos["risk_level"].isin(["Critical", "High"])] \
    .sort_values(["risk_score", "total_order_value"], ascending=False)
st.caption(f"{len(high)} POs at High/Critical · {money(high['total_order_value'].sum())} exposed")

sel = st.selectbox(
    "High-risk purchase orders", high["purchase_order_id"],
    format_func=lambda p: (
        f"{p} · {high.set_index('purchase_order_id').loc[p, 'equipment_category']} · "
        f"risk {high.set_index('purchase_order_id').loc[p, 'risk_score']:.0f}"))
row = high.set_index("purchase_order_id").loc[sel]

e1, e2 = st.columns([1, 1])
with e1:
    st.markdown(
        f"### {sel}\n"
        f"{RISK_DOT[row['risk_level']]} **Delay probability: "
        f"{row['delay_probability']:.0%}** · risk score {row['risk_score']:.0f} "
        f"({row['risk_level']})\n\n"
        f"{row['order_quantity']}× {row['equipment_type']} · "
        f"{row['supplier_name']} → {row['destination_site']} · "
        f"{money(row['total_order_value'])}")
    st.markdown("**Primary risk drivers**")
    for d in json.loads(row["top_risk_drivers"] or "[]"):
        st.markdown(f"- {d}")
    st.markdown(f"**Recommended action:** {row['recommended_action']}")

with e2:
    st.markdown("**How drivers are derived**")
    st.markdown(
        "Two models share the work: the gradient-boosted / logistic champion "
        "produces the probability, and a standardized logistic model translates "
        "each PO's feature values into signed contributions. The top positive "
        "contributions become the plain-English drivers on the left — so every "
        "flag is auditable back to data the buyer can verify.")
    top_sup = (high.groupby("supplier_name")["total_order_value"].agg(["count", "sum"])
               .sort_values("sum", ascending=False).head(6).reset_index())
    top_sup.columns = ["Supplier", "High-risk POs", "Exposed value"]
    fig = px.bar(top_sup, x="Exposed value", y="Supplier", orientation="h",
                 text="High-risk POs")
    fig.update_traces(marker_color="#DC2626")
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")
