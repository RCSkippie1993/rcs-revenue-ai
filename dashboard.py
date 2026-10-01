from pathlib import Path
import asyncio
import logging
import os
import sys

import pandas as pd
import streamlit as st
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.db import connect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rcs-revenue-ai")

st.set_page_config(page_title="RCS Revenue AI", page_icon="💼", layout="wide")
st.title("RCS Revenue AI")
st.caption("Opportunity pipeline, approvals and attributable revenue")


def load_data():
    with connect() as conn:
        opps = pd.read_sql_query("SELECT * FROM opportunities ORDER BY score DESC, id DESC", conn)
        approvals = pd.read_sql_query("SELECT * FROM approvals ORDER BY id DESC", conn)
        revenue = pd.read_sql_query("SELECT * FROM revenue_events ORDER BY id DESC", conn)
    return opps, approvals, revenue


def api_diagnostic():
    model = os.getenv("REVENUE_AGENT_MODEL", "gpt-5.6-luna")
    try:
        client = OpenAI()
        response = client.responses.create(
            model=model,
            input="Reply with exactly: API OK",
            max_output_tokens=64,
        )
        text = getattr(response, "output_text", "") or "API OK"
        return True, f"{model}: {text.strip()}"
    except Exception as exc:
        logger.exception("OpenAI API diagnostic failed")
        return False, f"{type(exc).__name__}: {exc}"


st.sidebar.header("Revenue Operator")
api_ready = bool(os.getenv("OPENAI_API_KEY"))
if api_ready:
    st.sidebar.success("OpenAI API key configured")
else:
    st.sidebar.error("OPENAI_API_KEY is not configured")

if st.sidebar.button("Test OpenAI connection", disabled=not api_ready):
    with st.spinner("Testing API access..."):
        ok, detail = api_diagnostic()
    if ok:
        st.sidebar.success(detail)
    else:
        st.error("The OpenAI API connection failed. This is usually an API billing, model-access, or key issue.")
        st.code(detail)

if st.sidebar.button("Run Revenue Sprint 001", type="primary", disabled=not api_ready):
    with st.spinner("Researching and building the first revenue experiment..."):
        try:
            ok, detail = api_diagnostic()
            if not ok:
                st.error("Revenue Sprint did not start because the OpenAI API check failed.")
                st.code(detail)
            else:
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
            logger.exception("Revenue Sprint failed")
            st.error("Revenue Sprint failed after the API connection test passed.")
            st.code(f"{type(exc).__name__}: {exc}")

if "last_sprint" in st.session_state:
    st.subheader("Latest Revenue Sprint")
    st.markdown(st.session_state["last_sprint"])

opps, approvals, revenue = load_data()

c1, c2, c3 = st.columns(3)
c1.metric("Opportunities", len(opps))
c2.metric("Pending approvals", int((approvals.status == "pending").sum()) if not approvals.empty else 0)
c3.metric("Revenue logged", f"R{revenue.amount_zar.sum():,.2f}" if not revenue.empty else "R0.00")

st.subheader("Opportunity Pipeline")
st.dataframe(opps, width="stretch", hide_index=True)
st.subheader("Approval Queue")
st.dataframe(approvals, width="stretch", hide_index=True)
st.subheader("Revenue Events")
st.dataframe(revenue, width="stretch", hide_index=True)
