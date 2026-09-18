"""Dual-backend connection helper: SQLite (development default, zero setup) or a
real Postgres URL (for deployments where the local filesystem isn't
persistent — e.g. Render's free tier wipes local files on every spin-down).

DB_PATH doubles as either a local file path or a full Postgres connection
string; is_postgres() distinguishes the two by scheme. Store and
MigrationRunner both go through connect() here instead of calling sqlite3
directly, so the rest of the app (queries, schema) doesn't need to know or
care which backend is active — see their docstrings for what stayed the
same and what's SQLite-vs-Postgres-specific (only "?" vs "%s" placeholders
and one INSERT-OR-IGNORE-vs-ON-CONFLICT difference; the schema/CHECK
constraints/indexes are valid SQL in both).
"""
from __future__ import annotations
import logging
import os
import sqlite3
from urllib.parse import urlparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("football_predictor.db")


def is_postgres(db_path: str) -> bool:
    return db_path.startswith("postgres://") or db_path.startswith("postgresql://")


def _running_on_known_serverless_host() -> bool:
    """Best-effort detection of hosts with NO persistent local filesystem at
    all, ever — not even across a single deploy's restarts. Vercel sets
    VERCEL=1 on every function invocation (documented); AWS Lambda (which
    several other "serverless Python" hosts are built on) sets
    AWS_LAMBDA_FUNCTION_NAME. This is deliberately narrower than "any host
    that might lose local files" (see _running_on_render below, which is a
    warning rather than a hard block, since Render CAN persist local files
    on a paid plan with a Disk attached)."""
    return bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _running_on_render() -> bool:
    """Render always sets RENDER=true (documented:
    render.com/docs/environment-variables). Unlike Vercel, this alone doesn't
    mean "no persistent disk" — Render's free plan has no disk, but a paid
    plan with a Disk attached at this exact path is fine. So this only
    triggers a warning, not the hard failure Vercel gets."""
    return os.environ.get("RENDER") == "true"


def _looks_like_supabase_direct_host(db_path: str) -> bool:
    """Return True for Supabase's direct `db.<project>.supabase.co` host.

    Supabase documents direct database connections on free plans as IPv6-only,
    while Render services commonly run IPv4-only. The shared Supabase pooler is
    the compatible route for Render.
    """
    if not is_postgres(db_path):
        return False
    try:
        host = (urlparse(db_path).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host.startswith("db.") and host.endswith(".supabase.co")


def assert_safe_for_current_host(db_path: str) -> None:
    """Call this once at startup (see app/api.py). Refuses to boot with a
    clear, actionable error instead of letting Store's first write fail with
    a bare 'read-only file system' / silently-reset-data bug on a host whose
    local filesystem isn't persistent across invocations. Where the host
    *might* be fine (Render on a paid plan with a Disk), this warns instead
    of blocking — see _running_on_render's docstring."""
    if db_path == ":memory:":
        return  # explicit in-memory DB is a deliberate, understood choice (e.g. tests)
    if is_postgres(db_path):
        if _running_on_render() and _looks_like_supabase_direct_host(db_path):
            raise RuntimeError(
                "DB_PATH uses Supabase's direct db.<project>.supabase.co endpoint. "
                "On Supabase free plans that route is IPv6-only, while Render services "
                "are IPv4-only. Use the Supabase Connect dialog's shared Session pooler "
                "connection string instead (normally port 5432), or another IPv4-compatible "
                "database endpoint."
            )
        return
    if _running_on_known_serverless_host():
        raise RuntimeError(
            "DB_PATH is a local SQLite file path, but this looks like a serverless host "
            "(Vercel/Lambda-style) with no persistent local filesystem — writes here would "
            "either fail outright or silently vanish between invocations. Set DB_PATH to a "
            "real Postgres connection string instead, e.g. from a free Supabase or Neon "
            "project: DB_PATH=postgresql://user:password@host:5432/dbname"
        )
    if _running_on_render():
        logger.warning(
            "DB_PATH is a local SQLite file path and this is running on Render. Render's "
            "FREE plan has no persistent disk — local files are wiped on every spin-down, "
            "so your admin/tips data WILL be lost. This is safe to ignore only if you're on "
            "a paid plan with a Disk mounted at this exact path (see render.yaml). "
            "Otherwise, set DB_PATH to a Postgres connection string (see DEPLOY_RENDER.md)."
        )


class _PGCursorWrapper:
    """Makes a psycopg2 (RealDictCursor) connection quack like sqlite3's
    Connection: `.execute(sql, params)` directly on the connection object,
    "?" placeholders (translated to "%s"), and `.executescript()` for
    multi-statement schema blocks — psycopg2 runs a semicolon-separated
    script fine in one `execute()` call as long as no params are passed."""

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executescript(self, sql: str) -> None:
        self._conn.cursor().execute(sql)


@contextmanager
def connect(db_path: str) -> Iterator[Any]:
    """Yields a connection-like object with `.execute()`/`.executescript()`,
    auto-committing on success and always closing. Rows behave like dicts
    either way (sqlite3.Row / psycopg2 RealDictRow both support `dict(row)`
    and `row["column"]`), so calling code needs zero backend-specific logic
    beyond the two spots noted in db.is_postgres()'s docstring above."""
    if is_postgres(db_path):
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(db_path, cursor_factory=psycopg2.extras.RealDictCursor)
        wrapper = _PGCursorWrapper(conn)
        try:
            yield wrapper
            conn.commit()
        finally:
            conn.close()
    else:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
