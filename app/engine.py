from __future__ import annotations
from math import exp, factorial
from typing import Iterable
import numpy as np

from .schemas import Fixture, MarketPrediction

# Markets considered fit to publish as a "tip". Deliberately excludes wide
# Total-Goals lines (e.g. Under 5.5), winning margins, and correct scores:
# after truncating/renormalizing the Poisson grid, those markets are almost
# always mathematically lopsided (P > 0.9) without carrying any real betting
# edge. Similar tip products restrict themselves to 1X2, Double Chance, BTTS,
# DNB, and Over/Under on a standard line for this reason.
#
# "1X2" selections are Home Win / Draw / Away Win — this is what covers
# "home or away to win" (Home Win and Away Win are both 1X2 selections; a
# genuine 2-way "which team wins, ignoring draws" market isn't something the
# score grid can price on its own since draws are a real, non-excludable
# outcome — Double Chance below is the standard way books handle that).
TIP_MARKETS = {"1X2", "Draw No Bet", "Double Chance", "BTTS", "Total Goals"}
TIP_TOTAL_GOALS_LINES = {"Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5"}
# Standard line for a single team's own goals market (e.g. "Arsenal Goals",
# "Chelsea Goals" — labeled by team name in markets(), not literally
# "Home Goals"/"Away Goals"). 1.5 is the conventional single-team O/U line.
TIP_TEAM_GOALS_LINES = {"Over 1.5", "Under 1.5"}
# Upper bound on P(event) for a shortlisted tip. Excluding near-certainties
# (P > this) keeps the shortlist to genuinely selective picks instead of
# restating "this team probably won't score 6".
MAX_TIP_PROBABILITY = 0.90

# Dixon-Coles (1997) low-score correlation. Independent Poisson underprices
# 0-0/1-1 and overprices 1-0/0-1 relative to observed football results; this
# reweights exactly those four cells before renormalizing. rho is negative in
# almost all fitted leagues (roughly -0.05 to -0.15); 0 disables it entirely.
DEFAULT_RHO = -0.1


def _dixon_coles_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1 - (lam * mu * rho)
    if x == 0 and y == 1:
        return 1 + (lam * rho)
    if x == 1 and y == 0:
        return 1 + (mu * rho)
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _is_tip_eligible(mp: MarketPrediction) -> bool:
    if mp.market == "Total Goals":
        return mp.selection in TIP_TOTAL_GOALS_LINES
    if mp.market in TIP_MARKETS:
        return True
    if mp.market.endswith(" Goals"):
        # Per-team goals market, e.g. "Arsenal Goals" / "Chelsea Goals" —
        # this is what covers "home goals over/under" and "away goals
        # over/under"; it's just labeled with the actual team name rather
        # than the literal words "home"/"away" (see markets() below).
        return mp.selection in TIP_TEAM_GOALS_LINES
    return False


class FootballProbabilityEngine:
    """Score-distribution-first engine. Produces coherent probabilities across markets."""
    def __init__(self, max_goals: int = 8, rho: float = DEFAULT_RHO):
        self.max_goals = max(4, max_goals)
        self.rho = rho

    def expected_goals(self, fx: Fixture) -> tuple[float, float]:
        # Baseline from ELO + form; xG takes precedence when provided.
        if fx.home_xg is not None and fx.away_xg is not None:
            return max(.05, fx.home_xg), max(.05, fx.away_xg)
        elo_diff = (fx.home_elo - fx.away_elo) / 400.0
        home_strength = 0.15 + 0.45 * elo_diff + 0.10 * fx.home_form.points_per_game
        away_strength = 0.05 - 0.35 * elo_diff + 0.08 * fx.away_form.points_per_game
        # Use per-match rates, not the raw n-match totals TeamForm stores —
        # otherwise changing the form window (e.g. last-5 to last-10) silently
        # inflates attack/defence without the underlying form actually changing.
        home_attack = max(0.15, 1.15 + 0.045 * fx.home_form.goals_for_per_game - 0.02 * fx.home_form.goals_against_per_game)
        away_attack = max(0.10, 0.95 + 0.045 * fx.away_form.goals_for_per_game - 0.02 * fx.away_form.goals_against_per_game)
        lam_h = np.clip(home_attack + home_strength, 0.2, 4.5)
        lam_a = np.clip(away_attack + away_strength, 0.15, 4.0)
        return float(lam_h), float(lam_a)

    def score_matrix(self, fx: Fixture) -> np.ndarray:
        lh, la = self.expected_goals(fx)
        h = np.array([exp(-lh) * lh**i / factorial(i) for i in range(self.max_goals + 1)])
        a = np.array([exp(-la) * la**i / factorial(i) for i in range(self.max_goals + 1)])
        m = np.outer(h, a)
        if self.rho:
            for x, y in ((0, 0), (0, 1), (1, 0), (1, 1)):
                m[x, y] *= _dixon_coles_tau(x, y, lh, la, self.rho)
            m = np.clip(m, 0.0, None)  # tau can't legally drive a cell negative
            # at sane |rho|, but clip defensively before renormalizing anyway.
        return m / m.sum()

    @staticmethod
    def _fair(p: float) -> float | None:
        return round(1/p, 4) if p > 0 else None

    def markets(self, fx: Fixture) -> list[MarketPrediction]:
        m = self.score_matrix(fx)
        n = m.shape[0]
        # Grid of home/away goal totals, used to compute exact P(total goals > k)
        # instead of an axis-only approximation that misses mixed-score combinations.
        i_idx, j_idx = np.indices((n, n))
        total_idx = i_idx + j_idx
        preds: list[MarketPrediction] = []
        home = float(np.tril(m, -1).sum())
        draw = float(np.trace(m))
        away = float(np.triu(m, 1).sum())
        for label, p in [("Home Win", home), ("Draw", draw), ("Away Win", away)]:
            key = label.lower().replace(" ", "_")
            mo = fx.odds.get("home" if key.startswith("home") else "draw" if key.startswith("draw") else "away")
            preds.append(self._mp("1X2", label, p, mo))
        preds += [
            self._mp("Double Chance", "1X", home + draw),
            self._mp("Double Chance", "X2", draw + away),
            self._mp("Double Chance", "12", home + away),
            self._mp("Draw No Bet", "Home", home/(home+away) if home+away else 0),
            self._mp("Draw No Bet", "Away", away/(home+away) if home+away else 0),
            self._mp("BTTS", "Yes", 1 - m[0,:].sum() - m[:,0].sum() + m[0,0]),
            self._mp("BTTS", "No", m[0,:].sum() + m[:,0].sum() - m[0,0]),
        ]
        for total in np.arange(.5, 6.0, 1.0):
            k = int(np.floor(total))
            over = float(m[total_idx > k].sum())
            under = 1 - over
            preds += [self._mp("Total Goals", f"Over {total:.1f}", over), self._mp("Total Goals", f"Under {total:.1f}", under)]
        for team_name, axis in [(fx.home_team, 0), (fx.away_team, 1)]:
            marginal = m.sum(axis=1 if axis == 0 else 0)
            for total in np.arange(.5, 4.0, 1.0):
                k = int(np.floor(total))
                over = float(marginal[k+1:].sum()) if k+1 < n else 0.0
                under = 1 - over
                preds += [self._mp(f"{team_name} Goals", f"Over {total:.1f}", over), self._mp(f"{team_name} Goals", f"Under {total:.1f}", under)]
        # Correct scores / winning margins
        flat = []
        for i in range(n):
            for j in range(n):
                flat.append((float(m[i,j]), f"{i}-{j}"))
        for p, score in sorted(flat, reverse=True)[:10]:
            preds.append(self._mp("Correct Score", score, p))
        for margin in [1,2,3]:
            hp = float(sum(m[i,j] for i in range(n) for j in range(n) if i-j == margin))
            ap = float(sum(m[i,j] for i in range(n) for j in range(n) if j-i == margin))
            if margin == 3:
                hp = float(sum(m[i,j] for i in range(n) for j in range(n) if i-j >= 3))
                ap = float(sum(m[i,j] for i in range(n) for j in range(n) if j-i >= 3))
            preds += [self._mp("Winning Margin", f"Home by {margin}" if margin<3 else "Home by 3+", hp), self._mp("Winning Margin", f"Away by {margin}" if margin<3 else "Away by 3+", ap)]
        # Capability hooks; no fake probabilities without the underlying provider data.
        return sorted(preds, key=lambda x: x.probability, reverse=True)

    def _mp(self, market: str, selection: str, p: float, market_odds: float | None = None) -> MarketPrediction:
        p = float(np.clip(p, 0.0001, 0.9999))
        edge = ((market_odds * p) - 1) if market_odds and market_odds > 1 else None
        conf = round(p, 4)
        return MarketPrediction(market, selection, p, self._fair(p), market_odds, edge, conf)

    def shortlist(self, fx: Fixture, min_conf: float = 0.60, top_n: int = 3,
                  max_conf: float = MAX_TIP_PROBABILITY) -> list[MarketPrediction]:
        """Publishable tips: inspect all supported standard markets, then rank the
        probability-valid candidates. A higher ceiling prevents a single low-risk
        total-goals line from crowding every fixture out of the published market set.
        [min_conf, max_conf] so we don't advertise a >90% "tip" that's just
        the shape of a truncated Poisson grid, and ranked by edge vs the
        bookmaker's price when odds exist (else by probability, still within
        the band) rather than by raw P(event)."""
        candidates = [
            x for x in self.markets(fx)
            if _is_tip_eligible(x) and min_conf <= x.probability <= max_conf
        ]
        if any(x.edge is not None for x in candidates):
            candidates.sort(key=lambda x: (x.edge if x.edge is not None else float("-inf")), reverse=True)
        else:
            candidates.sort(key=lambda x: x.probability, reverse=True)
        return candidates[:top_n]
