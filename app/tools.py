from __future__ import annotations
from agents import function_tool
from .db import connect, now_iso

@function_tool
def save_opportunity(
    title: str,
    audience: str,
    offer: str,
    channel: str,
    estimated_price_zar: float,
    score: float,
    rationale: str,
) -> str:
    """Save a commercially promising opportunity to the pipeline."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO opportunities
            (created_at,title,audience,offer,channel,estimated_price_zar,score,rationale)
            VALUES (?,?,?,?,?,?,?,?)""",
            (now_iso(), title, audience, offer, channel, estimated_price_zar, score, rationale),
        )
    return f"Saved opportunity: {title}"

@function_tool(needs_approval=True)
def queue_external_action(action_type: str, payload: str) -> str:
    """Queue an external action such as publishing, sending outreach, spending money or changing a live offer. Always requires human approval."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO approvals (created_at, action_type, payload) VALUES (?,?,?)",
            (now_iso(), action_type, payload),
        )
    return f"Queued approval: {action_type}"

@function_tool
def log_revenue(source: str, amount_zar: float, note: str = "") -> str:
    """Record realized revenue. Only use for revenue supplied by a trusted integration or the human operator."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO revenue_events (created_at,source,amount_zar,note) VALUES (?,?,?,?)",
            (now_iso(), source, amount_zar, note),
        )
    return f"Logged R{amount_zar:,.2f} from {source}"
