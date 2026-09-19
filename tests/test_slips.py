import unittest
from datetime import datetime, timedelta, timezone

from app.schemas import Fixture, TeamForm
from app.engine import FootballProbabilityEngine
from app.slips import SlipGenerator


class SlipTests(unittest.TestCase):
    def fixtures(self, n):
        now = datetime.now(timezone.utc)
        leagues = ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]
        out = []
        for i in range(n):
            out.append(
                Fixture(
                    str(i),
                    now + timedelta(hours=i + 1),
                    leagues[i % len(leagues)],
                    "2026",
                    f"H{i}",
                    f"A{i}",
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

    def test_daily_five_slips_and_range(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "x")
        slips = gen.daily(self.fixtures(80))
        self.assertEqual(len(slips), 5)
        self.assertTrue(all(10 <= len(s.selections) <= 15 for s in slips))
        signatures = {
            tuple(sorted(f"{x['fixture_id']}|{x['market']}|{x['selection']}" for x in s.selections))
            for s in slips
        }
        self.assertEqual(len(signatures), 5)

    def test_weekly_five_slips_and_range(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "x")
        slips = gen.weekly(self.fixtures(120))
        self.assertEqual(len(slips), 5)
        self.assertTrue(all(20 <= len(s.selections) <= 30 for s in slips))
        signatures = {
            tuple(sorted(f"{x['fixture_id']}|{x['market']}|{x['selection']}" for x in s.selections))
            for s in slips
        }
        self.assertEqual(len(signatures), 5)

    def test_monthly_five_slips_and_range(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "x")
        slips = gen.monthly(self.fixtures(180))
        self.assertEqual(len(slips), 5)
        self.assertTrue(all(20 <= len(s.selections) <= 50 for s in slips))
        signatures = {
            tuple(sorted(f"{x['fixture_id']}|{x['market']}|{x['selection']}" for x in s.selections))
            for s in slips
        }
        self.assertEqual(len(signatures), 5)

    def test_generated_slips_never_contain_unknown_leagues(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "no-unknown")
        for slip in gen.daily(self.fixtures(80)):
            self.assertTrue(all(
                str(item.get("league", "")).strip().casefold() not in {"", "unknown", "n/a", "none"}
                for item in slip.selections
            ))

    def test_one_selection_per_fixture_per_slip(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "x")
        for slip in gen.weekly(self.fixtures(120)):
            ids = [x["fixture_id"] for x in slip.selections]
            self.assertEqual(len(ids), len(set(ids)))

    def test_each_slip_includes_available_core_major_leagues(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "major-coverage")
        slips = gen.daily(self.fixtures(80))
        required = {
            "EPL": ("epl", "premier league"),
            "La Liga": ("la liga", "laliga"),
            "Bundesliga": ("bundesliga",),
            "Serie A": ("serie a",),
            "Ligue 1": ("ligue 1",),
        }
        for slip in slips:
            leagues = " | ".join(str(x["league"]).casefold() for x in slip.selections)
            for aliases in required.values():
                self.assertTrue(any(alias in leagues for alias in aliases))

    def test_different_outcomes_when_multiple_are_available(self):
        gen = SlipGenerator(FootballProbabilityEngine(), 0.5, "x")
        slips = gen.weekly(self.fixtures(120))
        signatures = []
        for slip in slips:
            signatures.append({
                (x["fixture_id"], x["market"], x["selection"])
                for x in slip.selections
            })
        # The package should not collapse into the same exact outcome set.
        self.assertGreater(
            len(set().union(*signatures) - set.intersection(*signatures)),
            0,
        )


if __name__ == "__main__":
    unittest.main()
