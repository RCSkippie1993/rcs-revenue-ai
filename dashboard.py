from pathlib import Path
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
st.caption("Commercial execution console: opportunity → package → prospects → approval → revenue")


def load_data():
    with connect() as conn:
        opps = pd.read_sql_query("SELECT * FROM opportunities ORDER BY score DESC, id DESC", conn)
        packages = pd.read_sql_query("SELECT * FROM execution_packages ORDER BY id DESC", conn)
        batches = pd.read_sql_query("SELECT * FROM prospect_batches ORDER BY id DESC", conn)
        approvals = pd.read_sql_query("SELECT * FROM approvals ORDER BY id DESC", conn)
        revenue = pd.read_sql_query("SELECT * FROM revenue_events ORDER BY id DESC", conn)
    return opps, packages, batches, approvals, revenue


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
    result = Runner.run_sync(execution_agent, prompt)
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


def build_prospect_batch(pkg):
    from agents import Runner
    from app.agents import prospect_agent

    prompt = f"""
Research the first prospect batch for this approved commercial package.
Package ID: {int(pkg['id'])}
Offer title: {pkg['title']}
Approved package content:

{pkg['package_markdown']}

Research 15 real prospects, primarily in South Africa. Use current public web evidence and include source URLs.
Draft personalized outreach, but do not contact anyone or submit any form.
"""
    result = Runner.run_sync(prospect_agent, prompt)
    if result.interruptions:
        raise RuntimeError("Prospect research unexpectedly requested an external action.")
    output = str(result.final_output)
    with connect() as conn:
        conn.execute(
            "INSERT INTO prospect_batches (created_at, package_id, title, batch_markdown, status) VALUES (?,?,?,?,?)",
            (now_iso(), int(pkg["id"]), str(pkg["title"]), output, "draft"),
        )
    return output


def approve_prospect_batch(batch_id: int):
    with connect() as conn:
        batch = conn.execute("SELECT * FROM prospect_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            return
        conn.execute("UPDATE prospect_batches SET status='content_approved' WHERE id=?", (batch_id,))
        existing = conn.execute(
            "SELECT id FROM approvals WHERE action_type='send_outreach_batch' AND payload LIKE ? AND status='pending'",
            (f'%\"batch_id\": {batch_id}%',),
        ).fetchone()
        if not existing:
            payload = f'{{"batch_id": {batch_id}, "title": "{str(batch["title"]).replace(chr(34), chr(39))}", "instruction": "Human-approved prospect content. External sending still requires a separate explicit approval and connected sending channel."}}'
            conn.execute(
                "INSERT INTO approvals (created_at, action_type, payload, status) VALUES (?,?,?,?)",
                (now_iso(), "send_outreach_batch", payload, "pending"),
            )


def reject_prospect_batch(batch_id: int):
    with connect() as conn:
        conn.execute("UPDATE prospect_batches SET status='rejected' WHERE id=?", (batch_id,))


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
                result = Runner.run_sync(manager, START_PROMPT)
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

opps, packages, batches, approvals, revenue = load_data()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Opportunities", len(opps))
c2.metric("Packages", len(packages))
c3.metric("Prospect batches", len(batches))
c4.metric("Pending approvals", int((approvals.status == "pending").sum()) if not approvals.empty else 0)
c5.metric("Revenue logged", f"R{revenue.amount_zar.sum():,.2f}" if not revenue.empty else "R0.00")

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
            with st.expander("View commercial package", expanded=pkg["status"] == "draft"):
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
                matching = batches[batches.package_id == int(pkg["id"])] if not batches.empty else pd.DataFrame()
                if matching.empty:
                    if st.button("Build first prospect batch", key=f"prospects_{int(pkg['id'])}", type="primary", disabled=not api_ready):
                        with st.spinner("Researching 15 real prospects and drafting personalized outreach..."):
                            try:
                                build_prospect_batch(pkg)
                                st.success("Prospect batch created. Nothing was sent.")
                                st.rerun()
                            except Exception as exc:
                                logger.exception("Prospect batch failed")
                                st.error(f"Prospect batch failed: {type(exc).__name__}: {exc}")
                else:
                    st.success("Prospect batch ready below")

st.subheader("Prospect & Outreach Batches")
if batches.empty:
    st.info("Approve a commercial package, then build its first prospect batch.")
else:
    for _, batch in batches.iterrows():
        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            with h1:
                st.markdown(f"### {batch['title']} — Batch #{int(batch['id'])}")
            with h2:
                st.write(f"**{str(batch['status']).upper()}**")
            st.markdown(batch["batch_markdown"])
            if batch["status"] == "draft":
                a, b, _ = st.columns([1.4, 1, 3.6])
                if a.button("Approve batch content", key=f"approve_batch_{int(batch['id'])}", type="primary"):
                    approve_prospect_batch(int(batch["id"]))
                    st.success("Batch content approved. Sending remains separately gated.")
                    st.rerun()
                if b.button("Reject batch", key=f"reject_batch_{int(batch['id'])}"):
                    reject_prospect_batch(int(batch["id"]))
                    st.rerun()
            elif batch["status"] == "content_approved":
                st.success("Content approved. External sending is still pending explicit approval and a connected sending channel.")

with st.expander("Approval Queue", expanded=True):
    st.dataframe(approvals, width="stretch", hide_index=True)

with st.expander("Revenue Events"):
    st.dataframe(revenue, width="stretch", hide_index=True)

st.caption("Guardrail: RCS Revenue AI does not send outreach, publish content, spend money, or enter commitments without explicit human approval.")
