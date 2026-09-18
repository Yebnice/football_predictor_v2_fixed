import unittest
from datetime import datetime, timezone

from app.schemas import Fixture, TeamDiscipline
from app.corners_cards import CornersCardsEngine, CORNER_LINES, CARD_LINES, TEAM_CORNER_LINES


def sample_fixture(**overrides) -> Fixture:
    defaults = dict(
        fixture_id="sample-1", date=datetime.now(timezone.utc),
        league="Premier League", season="2026", home_team="Arsenal", away_team="Everton",
        home_discipline=TeamDiscipline(corners_for_avg=6.1, corners_against_avg=3.9,
                                        cards_for_avg=1.3, cards_against_avg=2.1),
        away_discipline=TeamDiscipline(corners_for_avg=3.8, corners_against_avg=5.6,
                                        cards_for_avg=1.9, cards_against_avg=1.6),
    )
    defaults.update(overrides)
    return Fixture(**defaults)


class CornersCardsEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = CornersCardsEngine()

    def test_every_over_under_pair_sums_to_one(self):
        preds = {(m.market, m.selection): m.probability for m in self.engine.markets(sample_fixture())}
        for line in CORNER_LINES:
            self.assertAlmostEqual(preds[("Total Corners", f"Over {line}")] + preds[("Total Corners", f"Under {line}")], 1.0, places=6)
        for line in CARD_LINES:
            self.assertAlmostEqual(preds[("Total Cards", f"Over {line}")] + preds[("Total Cards", f"Under {line}")], 1.0, places=6)
        for team in ["Arsenal", "Everton"]:
            for line in TEAM_CORNER_LINES:
                market = f"{team} Corners"
                self.assertAlmostEqual(preds[(market, f"Over {line}")] + preds[(market, f"Under {line}")], 1.0, places=6)

    def test_probabilities_bounded(self):
        for m in self.engine.markets(sample_fixture()):
            self.assertGreaterEqual(m.probability, 0.0)
            self.assertLessEqual(m.probability, 1.0)

    def test_over_probability_decreases_as_line_rises(self):
        preds = {(m.market, m.selection): m.probability for m in self.engine.markets(sample_fixture())}
        corner_overs = [preds[("Total Corners", f"Over {line}")] for line in CORNER_LINES]
        self.assertEqual(corner_overs, sorted(corner_overs, reverse=True))
        card_overs = [preds[("Total Cards", f"Over {line}")] for line in CARD_LINES]
        self.assertEqual(card_overs, sorted(card_overs, reverse=True))

    def test_every_prediction_is_flagged_as_estimated(self):
        for m in self.engine.markets(sample_fixture()):
            self.assertTrue(m.metadata.get("estimated"))
            self.assertIn("not live match stats", m.metadata.get("basis", ""))

    def test_neutral_fixture_centers_near_league_average(self):
        # No discipline data at all -> both teams assumed average -> total
        # corners/cards should land close to the fixture's league averages,
        # i.e. Over on the middle line should sit close to a coin flip.
        fx = sample_fixture(home_discipline=TeamDiscipline(), away_discipline=TeamDiscipline())
        preds = {(m.market, m.selection): m.probability for m in self.engine.markets(fx)}
        # league_avg_corners=9.6 -> Over 9.5 should be roughly 50/50
        self.assertAlmostEqual(preds[("Total Corners", "Over 9.5")], 0.5, delta=0.15)
        # league_avg_cards=3.8 -> Over 3.5 should be roughly 50/50
        self.assertAlmostEqual(preds[("Total Cards", "Over 3.5")], 0.5, delta=0.2)

    def test_stronger_attacking_team_has_higher_corner_expectation(self):
        # Arsenal's corners_for_avg (6.1) is well above the neutral baseline;
        # its own market should reflect a higher expected count than Everton's.
        preds = {(m.market, m.metadata["expected"]) for m in self.engine.markets(sample_fixture())}
        arsenal_expected = next(v for m, v in preds if m == "Arsenal Corners")
        everton_expected = next(v for m, v in preds if m == "Everton Corners")
        self.assertGreater(arsenal_expected, everton_expected)

    def test_market_count_matches_spec(self):
        preds = self.engine.markets(sample_fixture())
        total_corner_preds = [m for m in preds if m.market == "Total Corners"]
        total_card_preds = [m for m in preds if m.market == "Total Cards"]
        team_corner_preds = [m for m in preds if m.market.endswith("Corners") and m.market != "Total Corners"]
        self.assertEqual(len(total_corner_preds), len(CORNER_LINES) * 2)
        self.assertEqual(len(total_card_preds), len(CARD_LINES) * 2)
        self.assertEqual(len(team_corner_preds), len(TEAM_CORNER_LINES) * 2 * 2)  # 2 teams


if __name__ == "__main__":
    unittest.main()
