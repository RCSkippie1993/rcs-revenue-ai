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

from app.db import connect, now_iso

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rcs-revenue-ai")

st.set_page_config(page_title="RCS Revenue AI", page_icon="💼", layout="wide")
st.title("RCS Revenue AI")
st.caption("Commercial execution console: opportunity → package → approval → revenue")


def load_data():
    with connect() as conn:
        opps = pd.read_sql_query("SELECT * FROM opportunities ORDER BY score DESC, id DESC", conn)
        packages = pd.read_sql_query("SELECT * FROM execution_packages ORDER BY id DESC", conn)
        approvals = pd.read_sql_query("SELECT * FROM approvals ORDER BY id DESC", conn)
        revenue = pd.read_sql_query("SELECT * FROM revenue_events ORDER BY id DESC", conn)
    return opps, packages, approvals, revenue


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


def build_execution_package(row):
    from agents import Runner
    from app.agents import execution_agent

    prompt = f"""
Build an approval-ready commercial execution package for this opportunity.
Opportunity ID: {int(row['id'])}
Title: {row['title']}
Audience: {row.get('audience', '')}
Current offer hypothesis: {row.get('offer', '')}
Primary channel: {row.get('channel', '')}
Estimated price ZAR: {row.get('estimated_price_zar', '')}
Opportunity score: {row.get('score', '')}
Rationale: {row.get('rationale', '')}

The operator is in South Africa. Optimize for reaching the first R10,000 in attributable revenue with low capital.
Prepare material for human approval only. Do not send, publish, spend money, or invent named prospects.
"""
    result = asyncio.run(Runner.run(execution_agent, prompt))
    if result.interruptions:
        raise RuntimeError("Execution package unexpectedly requested an external action.")
    output = str(result.final_output)
    with connect() as conn:
        conn.execute(
            "INSERT INTO execution_packages (created_at, opportunity_id, title, package_markdown, status) VALUES (?,?,?,?,?)",
            (now_iso(), int(row["id"]), str(row["title"]), output, "draft"),
        )
        conn.execute("UPDATE opportunities SET status='package_ready' WHERE id=?", (int(row["id"]),))
    return output


def set_package_status(package_id: int, status: str):
    with connect() as conn:
        conn.execute("UPDATE execution_packages SET status=? WHERE id=?", (status, package_id))
        if status == "approved":
            pkg = conn.execute("SELECT opportunity_id FROM execution_packages WHERE id=?", (package_id,)).fetchone()
            if pkg:
                conn.execute("UPDATE opportunities SET status='approved_for_execution' WHERE id=?", (pkg["opportunity_id"],))


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
        st.error("The OpenAI API connection failed.")
        st.code(detail)

if st.sidebar.button("Run Revenue Sprint 001", disabled=not api_ready):
    with st.spinner("Researching opportunities..."):
        try:
            ok, detail = api_diagnostic()
            if not ok:
                st.error("Revenue Sprint did not start because the API check failed.")
                st.code(detail)
            else:
                from agents import Runner
                from app.agents import manager
                from app.run import START_PROMPT
                result = asyncio.run(Runner.run(manager, START_PROMPT))
                if result.interruptions:
                    st.warning("The run paused for approval. No gated external action was executed.")
                else:
                    st.session_state["last_sprint"] = str(result.final_output)
                    st.success("Revenue Sprint 001 completed.")
                    st.rerun()
        except Exception as exc:
            logger.exception("Revenue Sprint failed")
            st.error("Revenue Sprint failed.")
            st.code(f"{type(exc).__name__}: {exc}")

opps, packages, approvals, revenue = load_data()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Opportunities", len(opps))
c2.metric("Packages", len(packages))
c3.metric("Pending approvals", int((approvals.status == "pending").sum()) if not approvals.empty else 0)
c4.metric("Revenue logged", f"R{revenue.amount_zar.sum():,.2f}" if not revenue.empty else "R0.00")

if "last_sprint" in st.session_state:
    with st.expander("Latest Revenue Sprint memo"):
        st.markdown(st.session_state["last_sprint"])

st.subheader("Opportunity Pipeline")
if opps.empty:
    st.info("No opportunities yet. Run Revenue Sprint 001 once.")
else:
    for _, row in opps.iterrows():
        score = row.get("score", 0)
        price = row.get("estimated_price_zar", 0)
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(f"### {row['title']}")
                st.write(f"**Audience:** {row.get('audience', '')}")
                st.write(f"**Offer:** {row.get('offer', '')}")
                st.write(f"**Primary channel:** {row.get('channel', '')}")
                st.write(f"**Why it may work:** {row.get('rationale', '')}")
            with right:
                st.metric("Score", f"{score:.0f}/100" if pd.notna(score) else "—")
                st.metric("Price hypothesis", f"R{price:,.0f}" if pd.notna(price) else "—")
                st.caption(f"Status: {row.get('status', 'new')}")
                existing = packages[packages.opportunity_id == int(row["id"])] if not packages.empty else pd.DataFrame()
                if existing.empty:
                    if st.button("Develop package", key=f"develop_{int(row['id'])}", type="primary", disabled=not api_ready):
                        with st.spinner("Building offer, pricing, copy and 7-day sales plan..."):
                            try:
                                build_execution_package(row)
                                st.success("Execution package created.")
                                st.rerun()
                            except Exception as exc:
                                logger.exception("Package build failed")
                                st.error(f"Package build failed: {type(exc).__name__}: {exc}")
                else:
                    st.success("Execution package ready")

st.subheader("Execution Packages")
if packages.empty:
    st.info("Choose an opportunity above and click Develop package.")
else:
    for _, pkg in packages.iterrows():
        with st.container(border=True):
            header_left, header_right = st.columns([4, 1])
            with header_left:
                st.markdown(f"### {pkg['title']}")
            with header_right:
                st.write(f"**{str(pkg['status']).upper()}**")
            st.markdown(pkg["package_markdown"])
            if pkg["status"] == "draft":
                a, b, _ = st.columns([1, 1, 4])
                if a.button("Approve package", key=f"approve_{int(pkg['id'])}", type="primary"):
                    set_package_status(int(pkg["id"]), "approved")
                    st.success("Approved. No outreach has been sent.")
                    st.rerun()
                if b.button("Reject", key=f"reject_{int(pkg['id'])}"):
                    set_package_status(int(pkg["id"]), "rejected")
                    st.rerun()
            elif pkg["status"] == "approved":
                st.success("Approved for the next execution stage. No external action has been taken yet.")

with st.expander("Approval Queue"):
    st.dataframe(approvals, width="stretch", hide_index=True)

with st.expander("Revenue Events"):
    st.dataframe(revenue, width="stretch", hide_index=True)

st.caption("Guardrail: RCS Revenue AI does not send outreach, publish content, spend money, or enter commitments without explicit human approval.")
