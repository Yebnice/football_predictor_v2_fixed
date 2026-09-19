"""Simple database migration system for schema updates. Works against either
backend supported by app/db.py (SQLite file path or Postgres URL in DB_PATH).

Migrations are versioned and run in order.
"""
from __future__ import annotations
import time
from typing import Any, Callable
from contextlib import contextmanager
from . import db as _db

# Migration versions - each function represents a migration step
MIGRATIONS: dict[str, Callable[[Any], None]] = {}

def migration(version: str):
    """Decorator to register a migration function."""
    def decorator(func: Callable[[Any], None]):
        MIGRATIONS[version] = func
        return func
    return decorator


@migration("001_initial_schema")
def migrate_001_initial_schema(conn: Any):
    """Initial schema creation - profiles, user_roles, tips tables."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS profiles (
        user_id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        created_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_roles (
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        granted_at REAL NOT NULL,
        PRIMARY KEY (user_id, role),
        FOREIGN KEY (user_id) REFERENCES profiles(user_id)
    );

    CREATE TABLE IF NOT EXISTS tips (
        id TEXT PRIMARY KEY,
        match TEXT NOT NULL,
        kickoff_time TEXT NOT NULL,
        market TEXT NOT NULL,
        selection TEXT NOT NULL,
        odds REAL,
        confidence REAL,
        notes TEXT,
        tier TEXT NOT NULL CHECK (tier IN ('free', 'vvip')),
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'won', 'lost', 'void')),
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        FOREIGN KEY (created_by) REFERENCES profiles(user_id)
    );

    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at REAL NOT NULL
    );
    """)


@migration("003_add_ml_pipeline_tables")
def migrate_003_add_ml_pipeline_tables(conn: Any):
    """Persistent data/model/prediction tables for the background ML lifecycle."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ml_matches (
        fixture_id TEXT PRIMARY KEY,
        kickoff_utc TEXT NOT NULL,
        league TEXT NOT NULL,
        season TEXT,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        status TEXT NOT NULL,
        home_score INTEGER,
        away_score INTEGER,
        source_provider TEXT,
        collected_at REAL NOT NULL,
        raw_json TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ml_matches_kickoff ON ml_matches(kickoff_utc);
    CREATE INDEX IF NOT EXISTS idx_ml_matches_teams ON ml_matches(home_team, away_team);
    CREATE INDEX IF NOT EXISTS idx_ml_matches_status ON ml_matches(status);

    CREATE TABLE IF NOT EXISTS ml_feature_snapshots (
        fixture_id TEXT NOT NULL,
        as_of_utc TEXT NOT NULL,
        features_json TEXT NOT NULL,
        model_version TEXT,
        feature_hash TEXT,
        PRIMARY KEY (fixture_id, as_of_utc)
    );

    CREATE INDEX IF NOT EXISTS idx_ml_features_model ON ml_feature_snapshots(model_version);

    CREATE TABLE IF NOT EXISTS ml_models (
        model_version TEXT PRIMARY KEY,
        algorithm TEXT NOT NULL,
        trained_at REAL NOT NULL,
        training_rows INTEGER NOT NULL,
        metrics_json TEXT NOT NULL,
        artifact_json TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_ml_models_active ON ml_models(active, trained_at);

    CREATE TABLE IF NOT EXISTS ml_predictions (
        id TEXT PRIMARY KEY,
        fixture_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        predicted_at REAL NOT NULL,
        kickoff_utc TEXT NOT NULL,
        league TEXT NOT NULL,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        market TEXT NOT NULL,
        selection TEXT NOT NULL,
        probability REAL NOT NULL,
        fair_odds REAL,
        model_probability REAL NOT NULL,
        home_lambda REAL,
        away_lambda REAL,
        candidate_index INTEGER NOT NULL DEFAULT -1,
        ai_approved INTEGER NOT NULL DEFAULT 0,
        ai_review_score REAL,
        ai_rationale TEXT,
        risk_flags_json TEXT,
        reviewers_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending_ai',
        actual_outcome TEXT,
        won INTEGER,
        settled_at REAL,
        UNIQUE (fixture_id, model_version, market, selection)
    );

    CREATE INDEX IF NOT EXISTS idx_ml_predictions_kickoff ON ml_predictions(kickoff_utc);
    CREATE INDEX IF NOT EXISTS idx_ml_predictions_status ON ml_predictions(status, ai_approved);
    CREATE INDEX IF NOT EXISTS idx_ml_predictions_model ON ml_predictions(model_version);
    CREATE INDEX IF NOT EXISTS idx_ml_predictions_fixture ON ml_predictions(fixture_id);

    CREATE TABLE IF NOT EXISTS ml_runs (
        id TEXT PRIMARY KEY,
        run_type TEXT NOT NULL,
        started_at REAL NOT NULL,
        completed_at REAL,
        status TEXT NOT NULL,
        summary_json TEXT,
        errors_json TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ml_runs_started ON ml_runs(started_at);

    CREATE TABLE IF NOT EXISTS ml_drift (
        id TEXT PRIMARY KEY,
        checked_at REAL NOT NULL,
        model_version TEXT,
        feature_drift_score REAL,
        performance_log_loss REAL,
        validation_log_loss REAL,
        alert INTEGER NOT NULL DEFAULT 0,
        details_json TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ml_drift_checked ON ml_drift(checked_at);
    """);


@migration("002_add_tip_indexes")
def migrate_002_add_tip_indexes(conn: Any):
    """Add performance indexes for common queries."""
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_tips_kickoff_time ON tips(kickoff_time);
    CREATE INDEX IF NOT EXISTS idx_tips_status ON tips(status);
    CREATE INDEX IF NOT EXISTS idx_tips_tier ON tips(tier);
    CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role);
    """)


class MigrationRunner:
    """Handles running database migrations in order, against either backend
    app/db.py supports (SQLite file path or Postgres URL)."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        with _db.connect(self.db_path) as conn:
            yield conn

    def _ensure_migration_table(self, conn: Any):
        """Ensure the schema_migrations table exists."""
        conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at REAL NOT NULL
        )
        """)

    def _get_applied_migrations(self, conn: Any) -> set[str]:
        """Get set of already applied migration versions."""
        cursor = conn.execute("SELECT version FROM schema_migrations")
        return {row[0] if not isinstance(row, dict) else row["version"] for row in cursor.fetchall()}

    def _record_migration(self, conn: Any, version: str):
        """Record that a migration has been applied."""
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, time.time())
        )

    def run_migrations(self):
        """Run all pending migrations in order."""
        with self._connect() as conn:
            self._ensure_migration_table(conn)
            applied = self._get_applied_migrations(conn)

            # Get sorted migration versions
            pending = sorted(set(MIGRATIONS.keys()) - applied)

            if not pending:
                return  # No migrations to run

            for version in pending:
                if version not in MIGRATIONS:
                    raise ValueError(f"Migration {version} not found in MIGRATIONS dict")

                print(f"Running migration: {version}")
                MIGRATIONS[version](conn)
                self._record_migration(conn, version)
                print(f"Migration {version} completed")

            print(f"Applied {len(pending)} migration(s)")


def run_migrations(db_path: str = "data/predictor.sqlite3"):
    """Convenience function to run migrations for a database."""
    runner = MigrationRunner(db_path)
    runner.run_migrations()