"""Corners and cards market estimator.

Deliberately separate from FootballProbabilityEngine (goals): this module has
its own inputs (TeamDiscipline averages + league averages) and its own,
simpler model. Corners and cards are each modeled as independent Poisson
counts for the home and away side; because the sum of two independent Poisson
variables is itself Poisson (rate = sum of the two rates), "total" markets
don't need a 2D score grid the way goals' BTTS/correct-score markets do.

These are model estimates from team/league averages, not scraped live match
stats (no provider here supplies real corner/card counts yet). Every
prediction this module returns carries metadata={"estimated": True, ...} so
callers can label it as such and nobody mistakes it for hard data.
"""
from __future__ import annotations
from math import exp, factorial

from .schemas import Fixture, MarketPrediction

# Modeling assumptions (not sourced statistics): corners skew mildly toward
# the home side (more sustained attacking possession), while cards skew
# mildly toward the away side (more time spent defending/committing fouls).
# Tune these once you have real per-league data; until then they're neutral
# nudges, not claims about any specific league.
HOME_ADVANTAGE_CORNERS = 1.08
HOME_ADVANTAGE_CARDS = 0.95

CORNER_LINES = [8.5, 9.5, 10.5, 11.5]
CARD_LINES = [2.5, 3.5, 4.5]
TEAM_CORNER_LINES = [3.5, 4.5, 5.5]


def _rate(value: float | None, fallback: float) -> float:
    return value if value is not None else fallback


def _poisson_pmf(lam: float, max_k: int) -> list[float]:
    lam = max(lam, 0.01)
    return [exp(-lam) * lam**k / factorial(k) for k in range(max_k + 1)]


def _over_probability(lam: float, threshold: float, max_k: int = 30) -> float:
    """P(X > threshold) for X ~ Poisson(lam), threshold typically a .5 line."""
    k = int(threshold)
    pmf = _poisson_pmf(lam, max_k)
    under_or_equal = sum(pmf[: k + 1])
    return max(0.0, min(1.0, 1 - under_or_equal))


class CornersCardsEngine:
    """Estimates corners/cards markets from team and league averages."""

    def _lambdas(self, fx: Fixture) -> tuple[float, float, float, float]:
        half_corners = fx.league_avg_corners / 2
        half_cards = fx.league_avg_cards / 2
        hd, ad = fx.home_discipline, fx.away_discipline

        home_corner_attack = _rate(hd.corners_for_avg, half_corners) / half_corners
        away_corner_defense = _rate(ad.corners_against_avg, half_corners) / half_corners
        away_corner_attack = _rate(ad.corners_for_avg, half_corners) / half_corners
        home_corner_defense = _rate(hd.corners_against_avg, half_corners) / half_corners
        lam_home_corners = half_corners * home_corner_attack * away_corner_defense * HOME_ADVANTAGE_CORNERS
        lam_away_corners = half_corners * away_corner_attack * home_corner_defense

        home_card_rate = _rate(hd.cards_for_avg, half_cards) / half_cards
        away_card_rate = _rate(ad.cards_for_avg, half_cards) / half_cards
        lam_home_cards = half_cards * home_card_rate * HOME_ADVANTAGE_CARDS
        lam_away_cards = half_cards * away_card_rate * (2 - HOME_ADVANTAGE_CARDS)

        return (max(0.2, lam_home_corners), max(0.2, lam_away_corners),
                max(0.05, lam_home_cards), max(0.05, lam_away_cards))

    @staticmethod
    def _fair(p: float) -> float | None:
        return round(1 / p, 4) if p > 0 else None

    def _mp(self, market: str, selection: str, p: float, expected: float) -> MarketPrediction:
        p = max(0.0001, min(0.9999, p))
        return MarketPrediction(
            market=market, selection=selection, probability=round(p, 4),
            fair_odds=self._fair(p), market_odds=None, edge=None, confidence=round(p, 4),
            metadata={
                "estimated": True,
                "basis": "team and league corner/card averages, not live match stats",
                "expected": round(expected, 2),
            },
        )

    def markets(self, fx: Fixture) -> list[MarketPrediction]:
        lam_hc, lam_ac, lam_hcards, lam_acards = self._lambdas(fx)
        total_corners_lambda = lam_hc + lam_ac
        total_cards_lambda = lam_hcards + lam_acards
        preds: list[MarketPrediction] = []

        for line in CORNER_LINES:
            over = _over_probability(total_corners_lambda, line)
            preds.append(self._mp("Total Corners", f"Over {line}", over, total_corners_lambda))
            preds.append(self._mp("Total Corners", f"Under {line}", 1 - over, total_corners_lambda))

        for line in CARD_LINES:
            over = _over_probability(total_cards_lambda, line)
            preds.append(self._mp("Total Cards", f"Over {line}", over, total_cards_lambda))
            preds.append(self._mp("Total Cards", f"Under {line}", 1 - over, total_cards_lambda))

        for team_name, lam in [(fx.home_team, lam_hc), (fx.away_team, lam_ac)]:
            market = f"{team_name} Corners"
            for line in TEAM_CORNER_LINES:
                over = _over_probability(lam, line)
                preds.append(self._mp(market, f"Over {line}", over, lam))
                preds.append(self._mp(market, f"Under {line}", 1 - over, lam))

        return preds
