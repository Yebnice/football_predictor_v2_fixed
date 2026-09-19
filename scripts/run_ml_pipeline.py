"""Run the scheduled background ML lifecycle.
Usage:
  python scripts/run_ml_pipeline.py --mode daily
  python scripts/run_ml_pipeline.py --mode weekly
"""
from __future__ import annotations

import argparse
import json

from app.services.ml_pipeline import main


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), default="daily")
    args = parser.parse_args()
    result = main(args.mode)
    print(json.dumps({
        "run_id": result.run_id,
        "mode": result.mode,
        "status": result.status,
        "collected_matches": result.collected_matches,
        "training_rows": result.training_rows,
        "model_version": result.model_version,
        "model_trained": result.model_trained,
        "predictions_created": result.predictions_created,
        "ai_approved": result.ai_approved,
        "settled_predictions": result.settled_predictions,
        "validation_log_loss": result.validation_log_loss,
        "calibration_ece": result.calibration_ece,
        "performance_log_loss": result.performance_log_loss,
        "feature_drift_score": result.feature_drift_score,
        "drift_alert": result.drift_alert,
        "errors": result.errors or [],
    }, indent=2))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(cli())
