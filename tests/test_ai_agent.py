import json
import types
import unittest
from unittest.mock import MagicMock

from app.engine import FootballProbabilityEngine
from app.schemas import Fixture, TeamForm
from app.services.ai_agent import AIPredictionAgent


class FakeProvider:
    def fixture_by_id(self, fixture_id):
        return None

    def fixture_details(self, fixture_id):
        return {}

    def odds(self, fixture_id):
        return {}

    def head_to_head(self, home_team_id, away_team_id, limit=5):
        return []

    def lineups(self, fixture_id):
        return []


class AgentTests(unittest.TestCase):
    @staticmethod
    def fixtures(n=20):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        out = []
        for i in range(n):
            out.append(
                Fixture(
                    str(i),
                    now + timedelta(hours=i + 1),
                    ["Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1"][i % 5],
                    "2026",
                    f"Home {i}",
                    f"Away {i}",
                    home_elo=1600 + i,
                    away_elo=1500,
                    home_form=TeamForm(
                        matches=10, wins=6, draws=2, losses=2,
                        goals_for=18, goals_against=8,
                    ),
                    away_form=TeamForm(
                        matches=10, wins=4, draws=3, losses=3,
                        goals_for=13, goals_against=12,
                    ),
                )
            )
        return out

    def test_candidate_output_is_model_derived(self):
        engine = FootballProbabilityEngine()
        agent = AIPredictionAgent(engine, FakeProvider(), min_confidence=0.5)
        fx = self.fixtures(1)[0]
        candidates = agent._candidate_payload(engine, fx)
        self.assertTrue(candidates)
        self.assertTrue(all("market" in row and "selection" in row for row in candidates))
        self.assertTrue(all(0.0 <= row["model_probability"] <= 0.75 for row in candidates))

    def test_invalid_ai_candidate_index_is_rejected(self):
        engine = FootballProbabilityEngine()
        agent = AIPredictionAgent(engine, FakeProvider(), min_confidence=0.5)
        fx = self.fixtures(1)[0]
        records, _ = agent._build_records([fx], candidate_limit=1, deep_evidence_limit=0)
        invalid = agent._validate_model_decisions(
            [{
                "fixture_id": fx.fixture_id,
                "candidate_index": 999,
                "approved": True,
                "review_score": 1.0,
                "rationale": "invented",
                "risk_flags": [],
            }],
            records,
            "gemini",
        )
        self.assertEqual(invalid, {})

    def test_unconfigured_agent_does_not_fabricate(self):
        engine = FootballProbabilityEngine()
        agent = AIPredictionAgent(engine, FakeProvider(), min_confidence=0.5)
        run = agent.review_fixtures(self.fixtures(10), candidate_limit=10, deep_evidence_limit=2)
        self.assertEqual(run.decisions, {})
        self.assertTrue(run.errors)

    def test_merge_prefers_supported_high_probability_candidate(self):
        engine = FootballProbabilityEngine()
        agent = AIPredictionAgent(engine, FakeProvider(), min_confidence=0.5)
        fx = self.fixtures(1)[0]
        records, _ = agent._build_records([fx], candidate_limit=1, deep_evidence_limit=0)
        candidates = records[0]["candidates"]
        first = candidates[0]
        second = candidates[1] if len(candidates) > 1 else first

        from app.services.ai_agent import AgentDecision

        gemini = {
            fx.fixture_id: AgentDecision(
                fx.fixture_id, second["candidate_index"], second["market"],
                second["selection"], True, 0.95, "Gemini", reviewers=("gemini",)
            )
        }
        groq = {
            fx.fixture_id: AgentDecision(
                fx.fixture_id, first["candidate_index"], first["market"],
                first["selection"], True, 0.70, "Groq", reviewers=("groq",)
            )
        }
        merged = agent._merge_decisions(gemini, groq, records)
        self.assertEqual(merged[fx.fixture_id].market, first["market"])
        self.assertEqual(merged[fx.fixture_id].selection, first["selection"])
        self.assertEqual(merged[fx.fixture_id].reviewers, ("gemini", "groq"))


if __name__ == "__main__":
    unittest.main()
