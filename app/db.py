from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "revenue_agent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    audience TEXT,
    offer TEXT,
    channel TEXT,
    estimated_price_zar REAL,
    score REAL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS revenue_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    amount_zar REAL NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS execution_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    opportunity_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    package_markdown TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
"""

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
