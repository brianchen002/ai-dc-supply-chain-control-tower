"""Lead-time forecasting — model comparison, importance, predictions."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Lead-Time Forecasting — Control Tower",
                   page_icon="⏱️", layout="wide")

from config.settings import MODELS_DIR
from dashboard.ui import bootstrap, load_df, model_meta, money, sidebar_common
from src.forecasting.leadtime_model import time_split
from src.transformation.features import ALL_FEATURES, build_features

conn = bootstrap()
sidebar_common()

st.title("⏱️ Lead-Time Forecasting")
meta = model_meta("leadtime")
st.markdown(
    f"Predicts each PO's **actual delivery lead time** from order-time features. "
    f"Trained on {meta.get('train_rows', '—')} delivered POs, evaluated on a "
    f"**{meta.get('split', '')}** — see `MODEL_DOCUMENTATION.md` for the "
    f"closed-window methodology that avoids survivorship leakage.")

# ---- Model comparison -------------------------------------------------------------
st.subheader("Model comparison")
res = pd.DataFrame(meta.get("results", []))
if not res.empty:
    naive_mae = res.loc[res["model"].str.startswith("Naive"), "mae_days"].iloc[0]
    best = res[res.get("selected", False) == True]  # noqa: E712
    best_mae = best["mae_days"].iloc[0]
    c = st.columns(4)
    c[0].metric("Selected model", best["model"].iloc[0])
    c[1].metric("Test MAE", f"{best_mae} days",
                delta=f"{(1 - best_mae / naive_mae) * 100:.0f}% better than plan",
                delta_color="normal")
    c[2].metric("Test RMSE", f"{best['rmse_days'].iloc[0]} days")
    c[3].metric("Test R²", f"{best['r2'].iloc[0]:.2f}")
    show = res[["model", "mae_days", "rmse_days", "mape_pct", "r2"]].copy()
    show.columns = ["Model", "MAE (days)", "RMSE (days)", "MAPE (%)", "R²"]
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption("The naive row predicts the plan itself (planned lead time) — the "
               "models' value-add is everything recovered beyond that baseline.")

# ---- Importance + scatter -----------------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("What drives lead time")
    imp = pd.DataFrame(meta.get("permutation_importance_top10", []))
    if not imp.empty:
        fig = px.bar(imp.sort_values("mae_impact_days"), x="mae_impact_days",
                     y="feature", orientation="h",
                     labels={"mae_impact_days": "MAE impact when shuffled (days)",
                             "feature": ""})
        fig.update_traces(marker_color="#4F46E5")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption("Permutation importance on the held-out test set.")

with right:
    st.subheader("Predicted vs actual (test set)")
    try:
        model = joblib.load(MODELS_DIR / "leadtime_model.joblib")
        pos = load_df("SELECT * FROM purchase_orders")
        feats = build_features(pos)
        _, test, _ = time_split(feats)
        test = test.copy()
        test["predicted"] = model.predict(test[ALL_FEATURES])
        fig = px.scatter(test, x="actual_lead_time_days", y="predicted",
                         color="equipment_category",
                         labels={"actual_lead_time_days": "actual lead time (days)",
                                 "predicted": "predicted (days)"})
        lo = min(test["actual_lead_time_days"].min(), test["predicted"].min())
        hi = max(test["actual_lead_time_days"].max(), test["predicted"].max())
        fig.add_shape(type="line", x0=lo, y0=lo, x1=hi, y1=hi,
                      line=dict(dash="dash", color="#9CA3AF"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                          legend_title_text="")
        st.plotly_chart(fig, width="stretch")
    except Exception as e:  # model file missing in a fresh checkout
        st.info(f"Run `python -m src.pipeline` to train models first. ({e})")

st.divider()

# ---- Where the model disagrees with supplier commitments ----------------------------
st.subheader("Model vs supplier commitments — biggest gaps on open POs")
open_pos = load_df("""SELECT purchase_order_id, supplier_name, equipment_category,
                             destination_site, total_order_value, original_eta,
                             current_eta, predicted_delivery_date, required_on_site_date
                      FROM purchase_orders
                      WHERE procurement_status NOT IN ('Delivered','Cancelled')
                        AND predicted_delivery_date IS NOT NULL""")
open_pos["model_vs_commit_days"] = (
    pd.to_datetime(open_pos["predicted_delivery_date"])
    - pd.to_datetime(open_pos["original_eta"])).dt.days
gaps = open_pos.sort_values("model_vs_commit_days", ascending=False).head(15)
st.dataframe(
    gaps, hide_index=True, width="stretch",
    column_config={
        "purchase_order_id": "PO", "supplier_name": "Supplier",
        "equipment_category": "Equipment", "destination_site": "Site",
        "total_order_value": st.column_config.NumberColumn("Value", format="$%.0f"),
        "original_eta": "Committed ETA", "current_eta": "Current ETA",
        "predicted_delivery_date": "Model-predicted delivery",
        "required_on_site_date": "Required on site",
        "model_vs_commit_days": st.column_config.NumberColumn(
            "Model vs commitment (d)", format="%.0f"),
    })
st.caption("POs where the model expects delivery far beyond the supplier's original "
           "commitment — early-warning list even before the supplier revises its ETA.")
