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
import json
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

    # ---- machine-learning lifecycle ------------------------------------
    def upsert_ml_matches(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        sql = """
            INSERT INTO ml_matches (
                fixture_id, kickoff_utc, league, season, home_team, away_team,
                status, home_score, away_score, source_provider, collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (fixture_id) DO UPDATE SET
                kickoff_utc=excluded.kickoff_utc,
                league=excluded.league,
                season=excluded.season,
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                status=excluded.status,
                home_score=excluded.home_score,
                away_score=excluded.away_score,
                source_provider=excluded.source_provider,
                collected_at=excluded.collected_at,
                raw_json=excluded.raw_json
        """
        with self._connect() as conn:
            for row in rows:
                conn.execute(sql, (
                    row["fixture_id"], row["kickoff_utc"], row["league"],
                    row.get("season"), row["home_team"], row["away_team"],
                    row.get("status", "scheduled"), row.get("home_score"),
                    row.get("away_score"), row.get("source_provider", ""),
                    row.get("collected_at", time.time()), row.get("raw_json", ""),
                ))

    def list_ml_matches(
        self,
        *,
        limit: int = 10000,
        finished_only: bool = False,
        since_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if finished_only:
            where.append("home_score IS NOT NULL AND away_score IS NOT NULL")
        if since_utc:
            where.append("kickoff_utc >= ?")
            params.append(since_utc)
        sql = "SELECT * FROM ml_matches"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY kickoff_utc ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def save_ml_feature_snapshot(
        self,
        *,
        fixture_id: str,
        as_of_utc: str,
        features: dict[str, Any],
        model_version: str | None,
        feature_hash: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ml_feature_snapshots
                    (fixture_id, as_of_utc, features_json, model_version, feature_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (fixture_id, as_of_utc) DO UPDATE SET
                    features_json=excluded.features_json,
                    model_version=excluded.model_version,
                    feature_hash=excluded.feature_hash
                """,
                (
                    fixture_id,
                    as_of_utc,
                    json.dumps(features, separators=(",", ":")),
                    model_version,
                    feature_hash,
                ),
            )

    def list_ml_feature_snapshots(
        self,
        *,
        model_version: str | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ml_feature_snapshots"
        params: list[Any] = []
        if model_version:
            sql += " WHERE model_version = ?"
            params.append(model_version)
        sql += " ORDER BY as_of_utc DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def create_ml_model(
        self,
        *,
        model_version: str,
        algorithm: str,
        trained_at: float,
        training_rows: int,
        metrics: dict[str, Any],
        artifact_json: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ml_models
                    (model_version, algorithm, trained_at, training_rows, metrics_json, artifact_json, active)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    model_version,
                    algorithm,
                    trained_at,
                    int(training_rows),
                    json.dumps(metrics, separators=(",", ":")),
                    artifact_json,
                ),
            )

    def update_ml_model_metrics(self, model_version: str, metrics: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE ml_models SET metrics_json = ? WHERE model_version = ?",
                (json.dumps(metrics, separators=(",", ":")), model_version),
            )

    def set_active_ml_model(self, model_version: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE ml_models SET active = 0 WHERE active = 1")
            conn.execute(
                "UPDATE ml_models SET active = 1 WHERE model_version = ?",
                (model_version,),
            )

    def get_active_ml_model(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ml_models WHERE active = 1 ORDER BY trained_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_ml_model(self, model_version: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ml_models WHERE model_version = ?",
                (model_version,),
            ).fetchone()
            return dict(row) if row else None

    def save_ml_prediction(
        self,
        *,
        prediction_id: str,
        fixture_id: str,
        model_version: str,
        predicted_at: float,
        kickoff_utc: str,
        league: str,
        home_team: str,
        away_team: str,
        market: str,
        selection: str,
        probability: float,
        fair_odds: float | None,
        model_probability: float,
        home_lambda: float | None,
        away_lambda: float | None,
        candidate_index: int,
        status: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ml_predictions (
                    id, fixture_id, model_version, predicted_at, kickoff_utc, league,
                    home_team, away_team, market, selection, probability, fair_odds,
                    model_probability, home_lambda, away_lambda, candidate_index,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (fixture_id, model_version, market, selection) DO UPDATE SET
                    predicted_at=excluded.predicted_at,
                    kickoff_utc=excluded.kickoff_utc,
                    league=excluded.league,
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    probability=excluded.probability,
                    fair_odds=excluded.fair_odds,
                    model_probability=excluded.model_probability,
                    home_lambda=excluded.home_lambda,
                    away_lambda=excluded.away_lambda,
                    candidate_index=excluded.candidate_index
                """,
                (
                    prediction_id, fixture_id, model_version, predicted_at, kickoff_utc,
                    league, home_team, away_team, market, selection, probability,
                    fair_odds, model_probability, home_lambda, away_lambda,
                    candidate_index, status,
                ),
            )

    def list_ml_predictions(
        self,
        *,
        limit: int = 10000,
        statuses: tuple[str, ...] = (),
        model_version: str | None = None,
        fixture_id: str | None = None,
        kickoff_from_utc: str | None = None,
        kickoff_to_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if model_version:
            where.append("model_version = ?")
            params.append(model_version)
        if fixture_id:
            where.append("fixture_id = ?")
            params.append(fixture_id)
        if kickoff_from_utc:
            where.append("kickoff_utc >= ?")
            params.append(kickoff_from_utc)
        if kickoff_to_utc:
            where.append("kickoff_utc <= ?")
            params.append(kickoff_to_utc)
        sql = "SELECT * FROM ml_predictions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY kickoff_utc ASC, predicted_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def approve_ml_prediction(
        self,
        *,
        fixture_id: str,
        model_version: str,
        market: str,
        selection: str,
        review_score: float,
        rationale: str,
        risk_flags: list[str],
        reviewers: list[str],
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ml_predictions
                SET ai_approved = 0, status = 'rejected_ai'
                WHERE fixture_id = ? AND model_version = ? AND status = 'pending_ai'
                """,
                (fixture_id, model_version),
            )
            conn.execute(
                """
                UPDATE ml_predictions
                SET ai_approved = 1,
                    status = 'approved',
                    ai_review_score = ?,
                    ai_rationale = ?,
                    risk_flags_json = ?,
                    reviewers_json = ?
                WHERE fixture_id = ? AND model_version = ?
                  AND market = ? AND selection = ? AND status = 'rejected_ai'
                """,
                (
                    max(0.0, min(1.0, float(review_score))),
                    rationale,
                    json.dumps(risk_flags or [], separators=(",", ":")),
                    json.dumps(reviewers or [], separators=(",", ":")),
                    fixture_id,
                    model_version,
                    market,
                    selection,
                ),
            )
            conn.execute(
                """
                UPDATE ml_predictions
                SET ai_approved = 0
                WHERE fixture_id = ? AND model_version = ? AND market = '1X2'
                """,
                (fixture_id, model_version),
            )

    def reject_pending_ml_predictions(self, *, fixture_id: str, model_version: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ml_predictions
                SET ai_approved = 0, status = 'rejected_ai'
                WHERE fixture_id = ? AND model_version = ? AND status = 'pending_ai'
                """,
                (fixture_id, model_version),
            )

    def settle_ml_prediction(
        self,
        *,
        prediction_id: str,
        actual_outcome: str,
        won: bool | None,
        settled_at: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ml_predictions
                SET actual_outcome = ?, won = ?, settled_at = ?,
                    status = CASE
                        WHEN status = 'internal' THEN 'settled_internal'
                        WHEN status = 'approved' THEN 'settled'
                        ELSE status
                    END
                WHERE id = ?
                """,
                (actual_outcome, None if won is None else int(bool(won)), settled_at, prediction_id),
            )

    def create_ml_run(
        self,
        run_id: str,
        run_type: str,
        started_at: float,
        status: str,
        summary: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ml_runs (id, run_type, started_at, status, summary_json, errors_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, run_type, started_at, status,
                    json.dumps(summary or {}, separators=(",", ":")),
                    json.dumps([], separators=(",", ":")),
                ),
            )

    def finish_ml_run(
        self,
        run_id: str,
        completed_at: float,
        status: str,
        summary: dict[str, Any],
        errors: list[str] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ml_runs
                SET completed_at = ?, status = ?, summary_json = ?, errors_json = ?
                WHERE id = ?
                """,
                (
                    completed_at,
                    status,
                    json.dumps(summary or {}, separators=(",", ":")),
                    json.dumps(errors or [], separators=(",", ":")),
                    run_id,
                ),
            )

    def list_ml_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ml_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def save_ml_drift(
        self,
        *,
        drift_id: str,
        checked_at: float,
        model_version: str | None,
        feature_drift_score: float | None,
        performance_log_loss: float | None,
        validation_log_loss: float | None,
        alert: bool,
        details: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ml_drift (
                    id, checked_at, model_version, feature_drift_score,
                    performance_log_loss, validation_log_loss, alert, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    drift_id,
                    checked_at,
                    model_version,
                    feature_drift_score,
                    performance_log_loss,
                    validation_log_loss,
                    int(bool(alert)),
                    json.dumps(details or {}, separators=(",", ":")),
                ),
            )

    def latest_ml_drift(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ml_drift ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

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
