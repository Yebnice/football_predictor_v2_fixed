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

    kwargs = {
        "limit": 5000,
        "statuses": ("approved",),
    }
    if model_version:
        kwargs["model_version"] = model_version

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

    latest_run = (store.list_ml_runs(limit=1) or [None])[0]
    drift = store.latest_ml_drift()

    metrics = {}
    if active:
        try:
            metrics = json.loads(active.get("metrics_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metrics = {}

    manifest = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "source": "github_actions_background_ml",
        "model": {
            "version": model_version or None,
            "algorithm": active.get("algorithm") if active else None,
            "trained_at": active.get("trained_at") if active else None,
            "training_rows": active.get("training_rows", 0) if active else 0,
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
