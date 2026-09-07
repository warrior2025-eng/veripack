"""
Database access layer for VeriPack.

Why raw SQLite instead of SQLAlchemy/PostgreSQL (as specified in the PRD):
this build environment has no network access, so `pip install sqlalchemy
psycopg2` and any PostgreSQL client cannot be fetched. SQLite ships with the
Python standard library, so it is the only option that is actually real and
runnable here.

The schema (schema.sql) is written to be a near-direct PostgreSQL port:
surrogate integer keys, explicit foreign keys, ISO-8601 timestamps as TEXT
(Postgres: TIMESTAMPTZ), and JSON stored as TEXT (Postgres: JSONB). Porting
means: swap this module's connection function for a psycopg2/SQLAlchemy
engine, keep schema.sql (translated to Postgres DDL) as an Alembic initial
migration, and keep every other module unchanged since they only depend on
the `get_db()` cursor interface below.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DB_PATH = os.environ.get("VERIPACK_DB_PATH", str(BASE_DIR / "storage" / "veripack.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_local = threading.local()


def _connect():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn():
    """Return a thread-local connection (SQLite connections are not
    thread-safe to share across threads)."""
    if not hasattr(_local, "conn"):
        _local.conn = _connect()
    return _local.conn


@contextmanager
def get_db():
    """Context manager yielding a cursor; commits on success, rolls back on
    exception. Mirrors the "session" pattern services would use with an ORM."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(reset: bool = False):
    """Create tables from schema.sql. If reset=True, delete the existing
    database file first (used by scripts/reset_db.py, never by the running
    application)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = _connect()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


def to_json(value) -> str:
    return json.dumps(value)


def from_json(value, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
