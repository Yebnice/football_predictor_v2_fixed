import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.engine import FootballProbabilityEngine
from app.services.ai_agent import AIPredictionAgent
from app.services.ml_pipeline import (
    FEATURE_NAMES,
    _build_training_rows,
    build_features,
    train_poisson_model,
)
from app.store import Store


class TestBackgroundMLPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        import os
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _history(self):
        rows = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        teams = ["Alpha FC", "Beta FC", "Gamma FC", "Delta FC"]
        day = 0
        for round_no in range(30):
            pairs = [(teams[0], teams[1]), (teams[2], teams[3])] if round_no % 2 == 0 else [(teams[1], teams[2]), (teams[3], teams[0])]
            for home, away in pairs:
                hs = 1 + (round_no % 3 == 0)
                aw = 0 if round_no % 4 else 1
                dt = base + timedelta(days=day)
                rows.append({
                    "fixture_id": f"f-{day}",
                    "kickoff_utc": dt.isoformat(),
                    "league": "Test League",
                    "season": "2025/26",
                    "home_team": home,
                    "away_team": away,
                    "home_score": hs,
                    "away_score": aw,
                    "status": "finished",
                    "source_provider": "test",
                    "collected_at": dt.timestamp(),
                    "raw_json": "{}",
                })
                day += 1
        return rows

    def test_feature_vector_has_expected_names_and_no_future_rows(self):
        history = self._history()
        fx = type("FX", (), {
            "date": datetime.fromisoformat(history[-1]["kickoff_utc"]),
            "league": "Test League",
            "home_team": history[-1]["home_team"],
            "away_team": history[-1]["away_team"],
        })()
        features = build_features(fx, history)
        self.assertEqual(list(features.keys()), list(FEATURE_NAMES))
        self.assertGreater(features["home_gf_5"], 0.0)

    def test_trained_poisson_model_records_metrics_and_artifact(self):
        history = self._history()
        X, y, meta = _build_training_rows(history)
        self.assertGreaterEqual(len(X), 40)
        version, metrics, trained = train_poisson_model(
            self.store,
            history,
            max_goals=8,
            force=True,
        )
        self.assertTrue(trained)
        self.assertIsNotNone(version)
        self.assertIn("log_loss", metrics)
        self.assertIn("calibration_ece", metrics)
        active = self.store.get_active_ml_model()
        self.assertIsNotNone(active)
        artifact = json.loads(active["artifact_json"])
        self.assertEqual(artifact["algorithm"], "poisson_regression")
        self.assertEqual(artifact["feature_names"], list(FEATURE_NAMES))

    def test_ai_prompt_accepts_background_model_context(self):
        agent = AIPredictionAgent(
            FootballProbabilityEngine(),
            provider=object(),
            min_confidence=0.60,
        )
        prompt = agent._prompt(
            [{
                "fixture": {"fixture_id": "fixture-1"},
                "candidates": [],
                "deep_evidence": {},
            }],
            background_context={
                "algorithm": "poisson_regression",
                "validation_log_loss": 0.95,
                "calibration_ece": 0.08,
                "drift_alert": False,
            },
        )
        self.assertIn("BACKGROUND PIPELINE CONTEXT", prompt)
        self.assertIn("validation_log_loss", prompt)


if __name__ == "__main__":
    unittest.main()
