"""Publish the canonical background ML prediction manifest.

This file is intentionally small and contains only non-secret, AI-approved
prediction data needed by the public Streamlit slip generator. GitHub Actions
writes it after a successful daily/weekly pipeline run so Streamlit Cloud
does not need access to the ML database or a Render backend.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.store import Store


MANIFEST_PATH = Path("data/latest_ml_manifest.json")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _kickoff(row: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(
            str(row.get("kickoff_utc") or "").replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except Exception:
        return None


def main() -> int:
    store = Store(settings.db_path)
    now = _now()
    horizon = now + timedelta(days=31)

    active = store.get_active_ml_model()
    model_version = str(active.get("model_version") or "") if active else ""

    # Do not read approved predictions until the latest *completed*
    # pipeline run has been identified, because another concurrent job may
    # already have switched the active model while it is still running.
    completed_runs = [
        row for row in (store.list_ml_runs(limit=100) or [])
        if str(row.get("status") or "").strip().casefold() == "completed"
    ]
    completed_runs.sort(
        key=lambda row: float(row.get("completed_at") or row.get("started_at") or 0),
        reverse=True,
    )
    latest_run = completed_runs[0] if completed_runs else None

    selected_model_version = ""
    selected_model = active
    summary = {}
    if latest_run:
        try:
            summary = json.loads(latest_run.get("summary_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            summary = {}
        selected_model_version = str(summary.get("model_version") or "")
        if selected_model_version:
            candidate_model = store.get_ml_model(selected_model_version)
            if candidate_model:
                selected_model = candidate_model

    kwargs = {
        "limit": 5000,
        "statuses": ("approved",),
    }
    if selected_model_version:
        kwargs["model_version"] = selected_model_version

    rows = store.list_ml_predictions(**kwargs)
    future_rows = []
    for row in rows:
        kickoff = _kickoff(row)
        if kickoff is None or kickoff < now or kickoff > horizon:
            continue
        future_rows.append({
            "fixture_id": str(row.get("fixture_id") or ""),
            "kickoff_utc": kickoff.isoformat(),
            "league": str(row.get("league") or ""),
            "home_team": str(row.get("home_team") or ""),
            "away_team": str(row.get("away_team") or ""),
            "market": str(row.get("market") or ""),
            "selection": str(row.get("selection") or ""),
            "probability": row.get("probability"),
            "fair_odds": row.get("fair_odds"),
            "model_probability": row.get("model_probability"),
            "home_lambda": row.get("home_lambda"),
            "away_lambda": row.get("away_lambda"),
            "candidate_index": row.get("candidate_index"),
            "model_version": str(row.get("model_version") or ""),
            "ai_review_score": row.get("ai_review_score"),
            "ai_rationale": str(row.get("ai_rationale") or ""),
            "risk_flags": json.loads(row.get("risk_flags_json") or "[]"),
            "reviewers": json.loads(row.get("reviewers_json") or "[]"),
        })

    future_rows.sort(key=lambda row: row["kickoff_utc"])

    # Preserve the last known-good manifest during transient/failed AI runs.
    # A completed run with zero approved predictions is not allowed to erase a
    # previously published package.
    if latest_run is None or int(summary.get("ai_approved") or 0) <= 0 or not future_rows:
        if MANIFEST_PATH.exists():
            print("No newly completed run with approved predictions; preserving existing ML manifest.")
            return 0
        raise RuntimeError(
            "No completed background ML run with approved predictions is available to publish."
        )

    drift = store.latest_ml_drift()

    metrics = {}
    if selected_model:
        try:
            metrics = json.loads(selected_model.get("metrics_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metrics = {}

    manifest = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "source": "github_actions_background_ml",
        "model": {
            "version": selected_model_version or None,
            "algorithm": selected_model.get("algorithm") if selected_model else None,
            "trained_at": selected_model.get("trained_at") if selected_model else None,
            "training_rows": selected_model.get("training_rows", 0) if selected_model else 0,
            "validation_log_loss": metrics.get("log_loss"),
            "calibration_ece": metrics.get("calibration_ece"),
        },
        "last_run": latest_run,
        "drift": drift,
        "approved_predictions_count": len(future_rows),
        "predictions": future_rows,
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        f"Published {len(future_rows)} approved predictions to "
        f"{MANIFEST_PATH} for model {model_version or 'none'}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
