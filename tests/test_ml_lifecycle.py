"""Regression coverage for publication gates and result settlement."""
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.engine import FootballProbabilityEngine
from app.schemas import Fixture
from app.services.ml_pipeline import (
    _build_training_rows, build_features, create_background_predictions, performance_and_drift,
    settle_predictions,
)
from app.store import Store


class TestMLLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(str(Path(self.tmp.name) / "test.sqlite3"))
        self.kickoff = datetime.now(timezone.utc) + timedelta(days=1)
        self.fx = Fixture("match", self.kickoff, "League", "2026", "Alpha", "Beta")
        self.store.create_ml_model(
            model_version="model", algorithm="poisson_regression", trained_at=1,
            training_rows=50, metrics={"log_loss": 1.0}, artifact_json="{}",
        )

    def save(self, market, selection, status="approved", probability=0.6):
        self.store.save_ml_prediction(
            prediction_id=f"{market}:{selection}", fixture_id="match", model_version="model",
            predicted_at=1, kickoff_utc=self.kickoff.isoformat(), league="League",
            home_team="Alpha", away_team="Beta", market=market, selection=selection,
            probability=probability, fair_odds=1/probability, model_probability=probability,
            home_lambda=1.5, away_lambda=1.0, candidate_index=0, status=status,
        )

    def history(self, home_score, away_score, status="finished"):
        return [{"fixture_id": "match", "kickoff_utc": self.kickoff.isoformat(),
                 "home_team": "Alpha", "away_team": "Beta", "league": "League",
                 "home_score": home_score, "away_score": away_score, "status": status}]

    def approve(self, market, selection):
        self.store.approve_ml_prediction(
            fixture_id="match", model_version="model", market=market, selection=selection,
            review_score=0.9, rationale="Reviewed", risk_flags=[], reviewers=["test"],
        )

    def generate(self, market, selection):
        self.fx.home_xg, self.fx.away_xg = 1.5, 1.0
        candidate = next(
            row for row in FootballProbabilityEngine().markets(self.fx)
            if row.market == market and row.selection == selection
        )
        with patch("app.services.ml_pipeline._predict_artifact", return_value=(1.5, 1.0)), \
             patch("app.services.ml_pipeline._prediction_candidate_rows", return_value=(self.fx, [candidate])):
            create_background_predictions(
                self.store, FootballProbabilityEngine(), [self.fx], [], "model", {},
            )

    def test_double_chance_all_outcomes(self):
        for hs, aw, wins in [(2, 0, {"1X", "12"}), (1, 1, {"1X", "X2"}), (0, 2, {"X2", "12"})]:
            with self.subTest(score=(hs, aw)):
                with self.store._connect() as conn:
                    conn.execute("DELETE FROM ml_predictions")
                for selection in ("1X", "X2", "12"):
                    self.save("Double Chance", selection)
                self.assertEqual(settle_predictions(self.store, self.history(hs, aw)), 3)
                for row in self.store.list_ml_predictions():
                    self.assertEqual(bool(row["won"]), row["selection"] in wins)
                self.assertEqual(settle_predictions(self.store, self.history(hs, aw)), 0)

    def test_draw_no_bet_draw_is_void(self):
        for selection in ("Home", "Away"):
            self.save("Draw No Bet", selection)
        settle_predictions(self.store, self.history(1, 1))
        for row in self.store.list_ml_predictions():
            self.assertEqual(row["actual_outcome"], "Void")
            self.assertIsNone(row["won"])
            self.assertEqual(row["status"], "settled")

    def test_live_scores_do_not_settle_predictions_or_enter_training_history(self):
        self.save("BTTS", "Yes")
        for status in ("in_play", "scheduled", "postponed", "abandoned"):
            with self.subTest(status=status):
                rows = self.history(3, 2, status)
                self.assertEqual(settle_predictions(self.store, rows), 0)
                self.store.upsert_ml_matches(rows)
                self.assertEqual(self.store.list_ml_matches(finished_only=True), [])
                later = Fixture("next", self.kickoff + timedelta(days=1), "League", "2026", "Alpha", "Beta")
                self.assertEqual(build_features(later, rows)["home_gf_5"], 1.0)
                self.assertEqual(len(_build_training_rows(rows)[0]), 0)
        rows = self.history(3, 2, "FT")
        self.store.upsert_ml_matches(rows)
        self.assertEqual(len(self.store.list_ml_matches(finished_only=True)), 1)
        self.assertEqual(settle_predictions(self.store, rows), 1)

    def test_1x2_candidate_can_be_approved_and_evaluated(self):
        self.generate("1X2", "Home Win")
        self.approve("1X2", "Home Win")
        rows = self.store.list_ml_predictions(statuses=("approved",))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ai_approved"], 1)
        settle_predictions(self.store, self.history(2, 0))
        loss, _, _, details = performance_and_drift(self.store, "model")
        self.assertEqual(details["prediction_count"], 1)
        self.assertAlmostEqual(loss, -math.log(rows[0]["probability"]))

    def test_regeneration_requires_fresh_approval_and_clears_old_candidates(self):
        self.generate("BTTS", "Yes")
        self.approve("BTTS", "Yes")
        self.generate("Total Goals", "Over 2.5")
        self.assertEqual(self.store.list_ml_predictions(statuses=("approved",)), [])
        self.approve("Total Goals", "Over 2.5")
        self.generate("Total Goals", "Over 2.5")
        self.assertEqual(self.store.list_ml_predictions(statuses=("approved",)), [])
        pending = self.store.list_ml_predictions(statuses=("pending_ai",))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["ai_approved"], 0)
        self.assertIsNone(pending[0]["ai_review_score"])
        self.assertIsNone(pending[0]["ai_rationale"])
        self.approve("Total Goals", "Over 2.5")
        self.assertEqual(len(self.store.list_ml_predictions(statuses=("approved",))), 1)

    def test_settled_predictions_are_not_reopened_by_regeneration(self):
        self.generate("BTTS", "Yes")
        self.approve("BTTS", "Yes")
        settle_predictions(self.store, self.history(2, 1))
        before = self.store.list_ml_predictions()
        self.generate("BTTS", "Yes")
        self.assertEqual(self.store.list_ml_predictions(), before)

    def test_rejected_1x2_candidate_still_contributes_to_monitoring(self):
        self.generate("1X2", "Home Win")
        self.store.reject_pending_ml_predictions(fixture_id="match", model_version="model")
        settle_predictions(self.store, self.history(2, 0))
        loss, _, _, details = performance_and_drift(self.store, "model")
        self.assertEqual(details["prediction_count"], 1)
        self.assertTrue(math.isfinite(loss))
        self.assertEqual(settle_predictions(self.store, self.history(2, 0)), 0)


if __name__ == "__main__":
    unittest.main()
