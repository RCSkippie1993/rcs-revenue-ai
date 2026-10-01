from pathlib import Path
import asyncio
import os
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.db import connect

st.set_page_config(page_title="RCS Revenue AI", page_icon="💼", layout="wide")
st.title("RCS Revenue AI")
st.caption("Opportunity pipeline, approvals and attributable revenue")


def load_data():
    with connect() as conn:
        opps = pd.read_sql_query("SELECT * FROM opportunities ORDER BY score DESC, id DESC", conn)
        approvals = pd.read_sql_query("SELECT * FROM approvals ORDER BY id DESC", conn)
        revenue = pd.read_sql_query("SELECT * FROM revenue_events ORDER BY id DESC", conn)
    return opps, approvals, revenue


st.sidebar.header("Revenue Operator")
api_ready = bool(os.getenv("OPENAI_API_KEY"))
if api_ready:
    st.sidebar.success("OpenAI API connected")
else:
    st.sidebar.error("OPENAI_API_KEY is not configured")

if st.sidebar.button("Run Revenue Sprint 001", type="primary", disabled=not api_ready):
    with st.spinner("Researching and building the first revenue experiment..."):
        try:
            from agents import Runner
            from app.agents import manager
            from app.run import START_PROMPT

            result = asyncio.run(Runner.run(manager, START_PROMPT))
            if result.interruptions:
                st.warning("The run paused for approval. No gated external action was executed.")
                for item in result.interruptions:
                    st.write(item)
            else:
                st.session_state["last_sprint"] = str(result.final_output)
                st.success("Revenue Sprint 001 completed.")
        except Exception as exc:
            st.exception(exc)

if "last_sprint" in st.session_state:
    st.subheader("Latest Revenue Sprint")
    st.markdown(st.session_state["last_sprint"])

opps, approvals, revenue = load_data()

c1, c2, c3 = st.columns(3)
c1.metric("Opportunities", len(opps))
c2.metric("Pending approvals", int((approvals.status == "pending").sum()) if not approvals.empty else 0)
c3.metric("Revenue logged", f"R{revenue.amount_zar.sum():,.2f}" if not revenue.empty else "R0.00")

st.subheader("Opportunity Pipeline")
st.dataframe(opps, use_container_width=True, hide_index=True)
st.subheader("Approval Queue")
st.dataframe(approvals, use_container_width=True, hide_index=True)
st.subheader("Revenue Events")
st.dataframe(revenue, use_container_width=True, hide_index=True)
