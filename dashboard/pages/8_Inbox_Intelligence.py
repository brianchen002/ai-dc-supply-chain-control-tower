"""Inbox intelligence — supplier emails → structured risk events."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Inbox Intelligence — Control Tower",
                   page_icon="📧", layout="wide")

from dashboard.ui import ai_client, bootstrap, load_df, mode_caption, money, sidebar_common
from src.llm.email_intel import process_inbox

conn = bootstrap()
sidebar_common()

st.title("📧 Inbox Intelligence")
st.markdown(
    "The earliest delay signals live in **text, not in databases** — a supplier "
    "email saying *\"shipments may slip ~2 weeks\"* exists in no system field. "
    "This page turns the inbox into structured risk events, links them to real "
    "purchase orders, and quantifies the impact on delay probability. "
    "**This is the LLM doing what the ML models cannot: reading.**")
mode_caption()

client = ai_client()
events = load_df("SELECT * FROM email_events")
emails = load_df("SELECT * FROM supplier_emails ORDER BY received DESC")

top = st.columns([1.4, 1])
with top[0]:
    st.caption(f"{len(emails)} messages in the demo inbox · "
               f"{len(events[events['event_type'] != 'NO_IMPACT'])} risk events "
               f"extracted ({events['extraction_mode'].iloc[0] if len(events) else '—'} mode)")
with top[1]:
    if client.is_live and st.button("🤖 Re-extract with live Claude", type="primary"):
        with st.spinner("Reading the inbox…"):
            st.session_state["live_events"] = process_inbox(conn, client)
    if "live_events" in st.session_state:
        events = st.session_state["live_events"]
        st.caption("Showing live-Claude extraction (session only)")

# ---- Event table -----------------------------------------------------------------
impactful = events[events["event_type"] != "NO_IMPACT"].copy()
noise = events[events["event_type"] == "NO_IMPACT"]

EVENT_ICON = {"LEAD_TIME_SLIP": "🔴", "ALLOCATION_CUT": "🟠",
              "LOGISTICS_DISRUPTION": "🟡", "QUALITY_HOLD": "🟠",
              "EXPEDITE_CONFIRMED": "🟢"}

st.subheader("Extracted risk events")
if impactful.empty:
    st.info("No impactful events extracted.")
else:
    show = impactful.copy()
    show["event"] = show["event_type"].map(EVENT_ICON).fillna("⚪") + " " + show["event_type"]
    show["linked_pos"] = show["affected_pos"].map(lambda s: len(json.loads(s or "[]")))
    st.dataframe(
        show[["email_id", "event", "supplier", "impact_days", "confidence",
              "linked_pos", "matched_by", "summary"]],
        hide_index=True, width="stretch",
        column_config={
            "email_id": "Msg", "event": "Event", "supplier": "Supplier",
            "impact_days": st.column_config.NumberColumn(
                "Impact (d)", format="%+.0f",
                help="Negative = pull-in / earlier delivery"),
            "confidence": st.column_config.ProgressColumn(
                "Confidence", min_value=0, max_value=1, format="%.2f"),
            "linked_pos": "POs linked", "matched_by": "Linked via",
            "summary": "Summary",
        })
    st.caption(f"{len(noise)} messages correctly classified as no-impact "
               "(invoices, marketing) and suppressed.")

st.divider()

# ---- Event drill-down ----------------------------------------------------------------
st.subheader("Event → purchase-order impact")
if not impactful.empty:
    pick = st.selectbox(
        "Event", impactful["email_id"],
        format_func=lambda e: (
            f"{e} · {impactful.set_index('email_id').loc[e, 'event_type']} · "
            f"{impactful.set_index('email_id').loc[e, 'summary'][:60]}"))
    ev = impactful.set_index("email_id").loc[pick]
    src = emails.set_index("email_id").loc[pick]

    c1, c2 = st.columns([1, 1.2])
    with c1:
        st.markdown(f"**From:** `{src['from_addr']}` · {src['received']}")
        st.markdown(f"**Subject:** {src['subject']}")
        st.text(src["body"])
    with c2:
        adj = pd.DataFrame(json.loads(ev["risk_adjustments"] or "[]"))
        if adj.empty:
            linked = json.loads(ev["affected_pos"] or "[]")
            st.info("No probability shift (zero/unknown impact), "
                    + (f"but linked to: {', '.join(linked)}" if linked
                       else "and no POs could be linked."))
        else:
            adj["Δ"] = (adj["p_after"] - adj["p_before"]).round(3)
            st.markdown(f"**{len(adj)} purchase orders affected** · "
                        f"{money(adj['value'].sum())} exposure · "
                        f"impact {ev['impact_days']:+.0f} days")
            st.dataframe(
                adj[["po", "value", "p_before", "p_after", "Δ"]],
                hide_index=True, width="stretch",
                column_config={
                    "po": "PO", "value": st.column_config.NumberColumn("Value", format="$%.0f"),
                    "p_before": st.column_config.ProgressColumn(
                        "P(delay) before", min_value=0, max_value=1, format="%.2f"),
                    "p_after": st.column_config.ProgressColumn(
                        "P(delay) after", min_value=0, max_value=1, format="%.2f"),
                    "Δ": st.column_config.NumberColumn("Shift", format="%+.3f"),
                })
            st.caption("Probability shift = calibrated logit adjustment sized by "
                       "impact days (src/llm/email_intel.py). In production these "
                       "events would feed the risk model as features and trigger "
                       "re-scoring — here they overlay it.")

st.divider()

# ---- Raw inbox --------------------------------------------------------------------------
st.subheader("Raw inbox")
for _, m in emails.iterrows():
    with st.expander(f"{m['received']} · {m['from_addr']} — {m['subject']}"):
        st.text(m["body"])
