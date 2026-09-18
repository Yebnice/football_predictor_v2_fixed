"""SQLite-backed storage for accounts, roles, and tips.

The original feature request asked to "enable Lovable Cloud" for this. Lovable
Cloud is a hosted backend tied to Lovable's own app-builder projects (it's
Supabase-based under the hood) — it isn't something that can be "enabled"
inside an existing, separately-hosted FastAPI/Streamlit codebase like this
one. This module is the functional equivalent built to fit this stack instead:
same data shape, same security posture (roles in their own table, checked
server-side, never trusted from client input), implemented with the stdlib +
sqlite3 rather than a third-party BaaS.

Security posture (mirrors what was asked for, adapted to plain SQL):
  - `profiles` holds identity only (email + password hash). No privilege flags
    live here, so no "edit my profile" endpoint can ever grant itself admin
    or VVIP access.
  - `user_roles` holds role grants (admin / vvip) as their own rows, and is
    only ever written by admin-only, server-verified code paths.
  - `has_role()` is the single function that answers "does this user have
    this role" — every authorization check in the app goes through it rather
    than re-implementing the query, mirroring the requested
    security-definer-function pattern (Postgres RLS isn't available in
    SQLite, so this is enforced in the FastAPI route layer instead — see
    app/auth.py's `require_role` dependency).

SQLite is deliberately the default here for a zero-setup local/dev experience.
For a real deployment where the local filesystem isn't persistent (e.g.
Render's free tier wipes local files on every spin-down), set DB_PATH to a
Postgres connection string instead — app/db.py detects the scheme and
switches backends transparently; the schema and nearly all queries below are
identical either way (see app/db.py's docstring for the two places that
aren't: placeholder style and grant_role's INSERT-OR-IGNORE).
"""
from __future__ import annotations
import time
import uuid
from typing import Any
from . import db as _db
from .migrations import run_migrations


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._is_pg = _db.is_postgres(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize the schema through the versioned migration system.

        Fail fast on migration errors instead of falling back to an incomplete
        schema and hiding the real connectivity/migration problem.
        """
        run_migrations(self.db_path)

    def _connect(self):
        return _db.connect(self.db_path)

    # ---- profiles -----------------------------------------------------
    def create_profile(self, email: str, password_hash: str, password_salt: str) -> str:
        user_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO profiles (user_id, email, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email.lower().strip(), password_hash, password_salt, time.time()),
            )
        return user_id

    def get_profile_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE email = ?", (email.lower().strip(),)).fetchone()
            return dict(row) if row else None

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def list_members(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT user_id, email, created_at FROM profiles ORDER BY created_at").fetchall()
            members = [dict(r) for r in rows]
            for m in members:
                m["roles"] = self.roles_for(m["user_id"])
        return members

    # ---- roles ----------------------------------------------------------
    def grant_role(self, user_id: str, role: str) -> None:
        with self._connect() as conn:
            if self._is_pg:
                conn.execute(
                    "INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id, role) DO NOTHING",
                    (user_id, role, time.time()),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role, granted_at) VALUES (?, ?, ?)",
                    (user_id, role, time.time()),
                )

    def revoke_role(self, user_id: str, role: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM user_roles WHERE user_id = ? AND role = ?", (user_id, role))

    def has_role(self, user_id: str, role: str) -> bool:
        """The single, server-side authority on role membership. Every
        authorization check in the app (see app/auth.py) goes through this
        rather than trusting a claim from the client or a cached token."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM user_roles WHERE user_id = ? AND role = ?", (user_id, role)
            ).fetchone()
            return row is not None

    def roles_for(self, user_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT role FROM user_roles WHERE user_id = ?", (user_id,)).fetchall()
            return [r["role"] for r in rows]

    def any_admin_exists(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM user_roles WHERE role = 'admin' LIMIT 1").fetchone()
            return row is not None

    # ---- tips -------------------------------------------------------------
    def create_tip(self, *, match: str, kickoff_time: str, market: str, selection: str,
                   odds: float | None, confidence: float | None, notes: str | None,
                   tier: str, created_by: str) -> dict[str, Any]:
        tip_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO tips (id, match, kickoff_time, market, selection, odds, confidence,
                   notes, tier, status, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (tip_id, match, kickoff_time, market, selection, odds, confidence, notes, tier,
                 created_by, now, now),
            )
        return self.get_tip(tip_id)

    def get_tip(self, tip_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tips WHERE id = ?", (tip_id,)).fetchone()
            return dict(row) if row else None

    def update_tip(self, tip_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get_tip(tip_id)
        fields["updated_at"] = time.time()
        columns = ", ".join(f"{k} = ?" for k in fields)
        with self._connect() as conn:
            conn.execute(f"UPDATE tips SET {columns} WHERE id = ?", (*fields.values(), tip_id))
        return self.get_tip(tip_id)

    def delete_tip(self, tip_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM tips WHERE id = ?", (tip_id,))
            return cur.rowcount > 0

    def list_tips(self, tier: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if tier:
                rows = conn.execute("SELECT * FROM tips WHERE tier = ? ORDER BY kickoff_time DESC", (tier,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tips ORDER BY kickoff_time DESC").fetchall()
            return [dict(r) for r in rows]

    def settled_tips_since(self, since_timestamp: float) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tips WHERE status IN ('won','lost') AND updated_at >= ? ORDER BY updated_at DESC",
                (since_timestamp,),
            ).fetchall()
            return [dict(r) for r in rows]
