import unittest
from datetime import datetime, timezone

from app.engine import FootballProbabilityEngine
from app.schemas import Fixture, TeamForm

class EngineTests(unittest.TestCase):
    def fixture(self):
        return Fixture("t1", datetime.now(timezone.utc), "Test", "2026", "Home", "Away",
                       home_elo=1600, away_elo=1500,
                       home_form=TeamForm(matches=10,wins=6,draws=2,losses=2,goals_for=18,goals_against=8),
                       away_form=TeamForm(matches=10,wins=4,draws=3,losses=3,goals_for=13,goals_against=12))
    def test_distribution(self):
        e=FootballProbabilityEngine(8)
        m=e.score_matrix(self.fixture())
        self.assertAlmostEqual(float(m.sum()),1.0,places=8)
    def test_markets_have_major_outcomes(self):
        e=FootballProbabilityEngine(8)
        ms=e.markets(self.fixture())
        names={(x.market,x.selection) for x in ms}
        for required in [("1X2","Home Win"),("1X2","Draw"),("1X2","Away Win"),("BTTS","Yes"),("Total Goals","Over 1.5"),("Correct Score","1-0")]:
            self.assertIn(required,names)
    def test_team_form_changes_expected_goals(self):
        e = FootballProbabilityEngine(8)
        neutral = self.fixture()
        strong = self.fixture()
        strong.home_form = TeamForm(matches=5, wins=5, draws=0, losses=0, goals_for=10, goals_against=2)
        weak = self.fixture()
        weak.home_form = TeamForm(matches=5, wins=0, draws=1, losses=4, goals_for=2, goals_against=10)
        strong_h, _ = e.expected_goals(strong)
        weak_h, _ = e.expected_goals(weak)
        neutral_h, _ = e.expected_goals(neutral)
        self.assertGreater(strong_h, neutral_h)
        self.assertLess(weak_h, neutral_h)
    def test_probabilities_bounded(self):
        e=FootballProbabilityEngine(8)
        for m in e.markets(self.fixture()):
            self.assertGreaterEqual(m.probability,0)
            self.assertLessEqual(m.probability,1)
    def test_total_goals_over_under_sum_to_one_and_match_brute_force(self):
        # Regression test: an earlier axis-only approximation for "Total Goals"
        # under/overcounted mixed home/away score combinations (e.g. 1-1 vs a
        # 2.5 line). Verify against a brute-force sum over the score matrix.
        e = FootballProbabilityEngine(8)
        fx = self.fixture()
        m = e.score_matrix(fx)
        n = m.shape[0]
        preds = {(x.market, x.selection): x.probability for x in e.markets(fx)}
        for total in [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]:
            k = int(total)
            brute_over = sum(m[i, j] for i in range(n) for j in range(n) if i + j > k)
            over = preds[("Total Goals", f"Over {total:.1f}")]
            under = preds[("Total Goals", f"Under {total:.1f}")]
            self.assertAlmostEqual(over, brute_over, places=6)
            self.assertAlmostEqual(over + under, 1.0, places=6)

if __name__ == '__main__':
    unittest.main()
