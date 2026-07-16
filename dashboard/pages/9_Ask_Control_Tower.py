"""Ask the Control Tower — natural language questions over the analytics DB."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

st.set_page_config(page_title="Ask the Control Tower", page_icon="💬", layout="wide")

from dashboard.ui import ai_client, bootstrap, mode_caption, sidebar_common
from src.llm.analytics_copilot import CANNED, ask, ask_canned

conn = bootstrap()
sidebar_common()

st.title("💬 Ask the Control Tower")
st.markdown(
    "Ask operational questions in plain language — the LLM writes a **read-only "
    "SQL query** against the analytics database, runs it through a safety layer "
    "(SELECT-only, denylisted keywords, row caps, read-only connection), and "
    "interprets the result. Every generated query is shown for audit.")
mode_caption()

client = ai_client()

# ---- Prepared question library (works in every mode) ---------------------------------
st.subheader("Question library" + ("" if client.is_live else " (offline mode)"))
cols = st.columns(2)
for i, name in enumerate(CANNED):
    if cols[i % 2].button(name, key=f"canned_{i}", width="stretch"):
        st.session_state["ct_result"] = ask_canned(name)
        st.session_state["ct_question"] = name

# ---- Free-form (live only) --------------------------------------------------------------
st.subheader("Free-form question")
if client.is_live:
    q = st.chat_input("e.g. Which InfiniBand POs for PHX-04 are at risk, by value?")
    if q:
        with st.spinner("Writing and running the query…"):
            st.session_state["ct_result"] = ask(q, client)
            st.session_state["ct_question"] = q
else:
    st.caption("⚪ Free-form NL→SQL needs live AI (`ANTHROPIC_API_KEY`). The "
               "prepared library above covers the most common operational "
               "questions and runs fully offline — an honest capability "
               "boundary, stated in the UI.")

# ---- Result ------------------------------------------------------------------------------
res = st.session_state.get("ct_result")
if res:
    st.divider()
    st.markdown(f"**Q: {st.session_state.get('ct_question', '')}**")
    if res.get("df") is not None:
        st.markdown(res["answer"])
        st.dataframe(res["df"], hide_index=True, width="stretch")
        with st.expander("SQL used (audit trail)"):
            st.code(res["sql"], language="sql")
        st.caption(f"mode: {res['mode']} · rows: {len(res['df'])}")
    else:
        st.warning(res["answer"])
