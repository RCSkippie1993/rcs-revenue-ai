from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "revenue_agent.db"

POSTGRES_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS opportunities (
        id SERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        title TEXT NOT NULL,
        audience TEXT,
        offer TEXT,
        channel TEXT,
        estimated_price_zar DOUBLE PRECISION,
        score DOUBLE PRECISION,
        rationale TEXT,
        status TEXT NOT NULL DEFAULT 'new'
    )""",
    """CREATE TABLE IF NOT EXISTS approvals (
        id SERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        action_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
    )""",
    """CREATE TABLE IF NOT EXISTS revenue_events (
        id SERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        source TEXT NOT NULL,
        amount_zar DOUBLE PRECISION NOT NULL,
        note TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS execution_packages (
        id SERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        opportunity_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        package_markdown TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft'
    )""",
    """CREATE TABLE IF NOT EXISTS prospect_batches (
        id SERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        package_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        batch_markdown TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft'
    )""",
]

SQLITE_SCHEMA = """
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
    status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE IF NOT EXISTS prospect_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    package_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    batch_markdown TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
);
"""

class PostgresCompatConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        # pandas.read_sql_query expects a standard DB-API connection exposing cursor().
        return self._conn.cursor(*args, **kwargs)

    def execute(self, sql, params=None):
        return self._conn.execute(sql.replace("?", "%s"), params or ())

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()


def connect():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(database_url, row_factory=dict_row)
        conn = PostgresCompatConnection(raw)
        for statement in POSTGRES_SCHEMA:
            conn.execute(statement)
        raw.commit()
        return conn

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SQLITE_SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
