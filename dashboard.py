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


def query_df(conn, sql, params=None):
    cur = conn.execute(sql, params or ())
    rows = cur.fetchall()
    if rows:
        first = rows[0]
        if hasattr(first, "keys"):
            return pd.DataFrame([dict(row) for row in rows])
        columns = [desc.name if hasattr(desc, "name") else desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=columns)
    columns = [desc.name if hasattr(desc, "name") else desc[0] for desc in (cur.description or [])]
    return pd.DataFrame(columns=columns)


def load_data():
    with connect() as conn:
        # Remove the two malformed placeholder rows created by the early tool-call prototype.
        conn.execute("DELETE FROM opportunities WHERE title=? AND audience=?", ("title", "audience"))
        opps = query_df(conn, "SELECT * FROM opportunities ORDER BY score DESC, id DESC")
        packages = query_df(conn, "SELECT * FROM execution_packages ORDER BY id DESC")
        batches = query_df(conn, "SELECT * FROM prospect_batches ORDER BY id DESC")
        approvals = query_df(conn, "SELECT * FROM approvals ORDER BY id DESC")
        revenue = query_df(conn, "SELECT * FROM revenue_events ORDER BY id DESC")
    return opps, packages, batches, approvals, revenue


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def run_revenue_sprint():
    from agents import Runner
    from app.agents import sprint_scout

    prompt = """
Find exactly two current low-capital online commercial opportunities for Rikus in South Africa using his
strengths in B2B business, professional services, contract/document workflows, business development and content.
Target the first R10,000 in attributable online revenue. Use current web evidence. Return only validated,
substantive opportunities through the typed output schema. Do not contact anyone or take external action.
"""
    result = Runner.run_sync(sprint_scout, prompt)
    if result.interruptions:
        raise RuntimeError("Opportunity research unexpectedly requested approval.")

    batch = result.final_output
    candidates = list(batch.opportunities)
    if len(candidates) != 2:
        raise RuntimeError(f"Expected exactly 2 opportunities, received {len(candidates)}.")

    with connect() as conn:
        conn.execute("DELETE FROM opportunities WHERE title=? AND audience=?", ("title", "audience"))
        for item in candidates:
            conn.execute(
                """INSERT INTO opportunities
                (created_at,title,audience,offer,channel,estimated_price_zar,score,rationale,status)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    now_iso(), item.title, item.audience, item.offer, item.channel,
                    float(item.estimated_price_zar), float(item.score), item.rationale, "new"
                ),
            )

    memo_lines = ["## Revenue Sprint 001", "", "Two validated opportunities were researched and saved:", ""]
    for idx, item in enumerate(candidates, start=1):
        memo_lines.extend([
            f"### {idx}. {item.title}",
            f"**Audience:** {item.audience}",
            f"**Offer:** {item.offer}",
            f"**Channel:** {item.channel}",
            f"**Price hypothesis:** R{item.estimated_price_zar:,.0f}",
            f"**Score:** {item.score:.0f}/100",
            f"**Rationale:** {item.rationale}",
            "",
        ])
    return "\n".join(memo_lines)


def build_execution_package(row):
    from agents import Runner
    from app.agents import execution_agent

    row_id = safe_int(row.get("id"))
    if row_id is None:
        raise RuntimeError("Opportunity has an invalid database ID.")
    prompt = f"""
Build an approval-ready commercial execution package for this opportunity.
Opportunity ID: {row_id}
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
            (now_iso(), row_id, str(row["title"]), output, "draft"),
        )
        conn.execute("UPDATE opportunities SET status='package_ready' WHERE id=?", (row_id,))
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

    package_id = safe_int(pkg.get("id"))
    if package_id is None:
        raise RuntimeError("Package has an invalid database ID.")
    prompt = f"""
Research the first prospect batch for this approved commercial package.
Package ID: {package_id}
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
            (now_iso(), package_id, str(pkg["title"]), output, "draft"),
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


def maybe_auto_build_first_batch(packages, batches, api_ready):
    if os.getenv("AUTO_BUILD_PROSPECT_BATCH_ONCE", "0") != "1" or not api_ready:
        return None
    if packages.empty or "status" not in packages.columns:
        return None

    approved = packages[packages.status == "approved"].copy()
    if approved.empty:
        return None
    if "id" in approved.columns:
        approved = approved.sort_values("id", ascending=False)

    for _, pkg in approved.iterrows():
        pkg_id = safe_int(pkg.get("id"))
        if pkg_id is None:
            continue
        matching = batches[batches.package_id == pkg_id] if not batches.empty and "package_id" in batches.columns else pd.DataFrame()
        if not matching.empty:
            continue

        session_key = f"auto_prospect_attempted_{pkg_id}"
        if st.session_state.get(session_key):
            return None
        st.session_state[session_key] = True

        try:
            build_prospect_batch(pkg)
            return f"Prospect batch automatically created for approved package #{pkg_id}. Nothing was sent."
        except Exception as exc:
            logger.exception("Automatic prospect batch failed")
            return f"Automatic prospect batch failed: {type(exc).__name__}: {exc}"
    return None


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
    with st.spinner("Researching and validating two opportunities..."):
        try:
            ok, detail = api_diagnostic()
            if not ok:
                st.error("Revenue Sprint did not start because the API check failed.")
                st.code(detail)
            else:
                memo = run_revenue_sprint()
                st.session_state["last_sprint"] = memo
                st.success("Revenue Sprint 001 completed and saved two validated opportunities.")
                st.rerun()
        except Exception as exc:
            logger.exception("Revenue Sprint failed")
            st.error("Revenue Sprint failed.")
            st.code(f"{type(exc).__name__}: {exc}")

opps, packages, batches, approvals, revenue = load_data()

auto_batch_result = maybe_auto_build_first_batch(packages, batches, api_ready)
if auto_batch_result:
    if auto_batch_result.startswith("Prospect batch automatically created"):
        st.session_state["auto_batch_result"] = auto_batch_result
        st.rerun()
    else:
        st.error(auto_batch_result)

if "auto_batch_result" in st.session_state:
    st.success(st.session_state.pop("auto_batch_result"))

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Opportunities", len(opps))
c2.metric("Packages", len(packages))
c3.metric("Prospect batches", len(batches))
c4.metric("Pending approvals", int((approvals.status == "pending").sum()) if not approvals.empty and "status" in approvals.columns else 0)
c5.metric("Revenue logged", f"R{pd.to_numeric(revenue.get('amount_zar', pd.Series(dtype=float)), errors='coerce').fillna(0).sum():,.2f}" if not revenue.empty else "R0.00")

if "last_sprint" in st.session_state:
    with st.expander("Latest Revenue Sprint memo"):
        st.markdown(st.session_state["last_sprint"])

st.subheader("Opportunity Pipeline")
if opps.empty:
    st.info("No opportunities yet. Run Revenue Sprint 001 once.")
else:
    for _, row in opps.iterrows():
        row_id = safe_int(row.get("id"))
        score = safe_float(row.get("score"))
        price = safe_float(row.get("estimated_price_zar"))
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(f"### {row.get('title', 'Untitled opportunity')}")
                st.write(f"**Audience:** {row.get('audience', '')}")
                st.write(f"**Offer:** {row.get('offer', '')}")
                st.write(f"**Primary channel:** {row.get('channel', '')}")
                st.write(f"**Why it may work:** {row.get('rationale', '')}")
            with right:
                st.metric("Score", f"{score:.0f}/100" if score is not None else "—")
                st.metric("Price hypothesis", f"R{price:,.0f}" if price is not None else "—")
                st.caption(f"Status: {row.get('status', 'new')}")
                if row_id is None:
                    st.error("Invalid legacy opportunity row. It will be ignored.")
                    continue
                existing = packages[packages.opportunity_id == row_id] if not packages.empty and "opportunity_id" in packages.columns else pd.DataFrame()
                if existing.empty:
                    if st.button("Develop package", key=f"develop_{row_id}", type="primary", disabled=not api_ready):
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
        pkg_id = safe_int(pkg.get("id"))
        if pkg_id is None:
            continue
        with st.container(border=True):
            header_left, header_right = st.columns([4, 1])
            with header_left:
                st.markdown(f"### {pkg.get('title', 'Untitled package')}")
            with header_right:
                st.write(f"**{str(pkg.get('status', 'draft')).upper()}**")
            with st.expander("View commercial package", expanded=pkg.get("status") == "draft"):
                st.markdown(pkg.get("package_markdown", ""))
            if pkg.get("status") == "draft":
                a, b, _ = st.columns([1, 1, 4])
                if a.button("Approve package", key=f"approve_{pkg_id}", type="primary"):
                    set_package_status(pkg_id, "approved")
                    st.success("Approved. No outreach has been sent.")
                    st.rerun()
                if b.button("Reject", key=f"reject_{pkg_id}"):
                    set_package_status(pkg_id, "rejected")
                    st.rerun()
            elif pkg.get("status") == "approved":
                matching = batches[batches.package_id == pkg_id] if not batches.empty and "package_id" in batches.columns else pd.DataFrame()
                if matching.empty:
                    if st.button("Build first prospect batch", key=f"prospects_{pkg_id}", type="primary", disabled=not api_ready):
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
        batch_id = safe_int(batch.get("id"))
        if batch_id is None:
            continue
        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            with h1:
                st.markdown(f"### {batch.get('title', 'Prospect batch')} — Batch #{batch_id}")
            with h2:
                st.write(f"**{str(batch.get('status', 'draft')).upper()}**")
            st.markdown(batch.get("batch_markdown", ""))
            if batch.get("status") == "draft":
                a, b, _ = st.columns([1.4, 1, 3.6])
                if a.button("Approve batch content", key=f"approve_batch_{batch_id}", type="primary"):
                    approve_prospect_batch(batch_id)
                    st.success("Batch content approved. Sending remains separately gated.")
                    st.rerun()
                if b.button("Reject batch", key=f"reject_batch_{batch_id}"):
                    reject_prospect_batch(batch_id)
                    st.rerun()
            elif batch.get("status") == "content_approved":
                st.success("Content approved. External sending is still pending explicit approval and a connected sending channel.")

with st.expander("Approval Queue", expanded=True):
    st.dataframe(approvals, width="stretch", hide_index=True)

with st.expander("Revenue Events"):
    st.dataframe(revenue, width="stretch", hide_index=True)

st.caption("Guardrail: RCS Revenue AI does not send outreach, publish content, spend money, or enter commitments without explicit human approval.")