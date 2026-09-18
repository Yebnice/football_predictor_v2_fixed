from __future__ import annotations
from datetime import datetime, timezone
import hashlib, random
from typing import Iterable
from .engine import FootballProbabilityEngine
from .schemas import Fixture, Slip

class SlipGenerator:
    def __init__(self, engine: FootballProbabilityEngine, min_confidence: float = .60, salt: str = "change-me"):
        self.engine = engine
        self.min_confidence = min_confidence
        self.salt = salt

    def eligible(self, fixtures: Iterable[Fixture]) -> list[dict]:
        pool = []
        for fx in fixtures:
            best = self.engine.shortlist(fx, self.min_confidence, 1)
            if not best:
                continue
            p = best[0]
            pool.append({"fixture_id": fx.fixture_id, "date": fx.date.isoformat(), "league": fx.league,
                         "home_team": fx.home_team, "away_team": fx.away_team, "market": p.market,
                         "selection": p.selection, "probability": p.probability, "fair_odds": p.fair_odds,
                         "market_odds": p.market_odds, "edge": p.edge})
        return pool

    def generate(self, period: str, fixtures: list[Fixture], count: int, slips: int, now: datetime | None = None) -> list[Slip]:
        now = now or datetime.now(timezone.utc)
        pool = self.eligible(fixtures)
        if len(pool) < count:
            raise ValueError(f"Only {len(pool)} eligible matches; need {count}.")
        if slips > 1 and len(pool) == count:
            raise ValueError(f"Need more than {count} eligible matches to create {slips} different slips.")
        out=[]; seen=set()
        max_attempts = max(25, slips * 10)
        for idx in range(1, slips+1):
            selected = None
            for attempt in range(max_attempts):
                seed = hashlib.sha256(f"{self.salt}|{period}|{now.date()}|{idx}|{attempt}".encode()).hexdigest()
                rng = random.Random(seed)
                # Weighted randomization: higher-probability selections are more likely, but not guaranteed.
                weights = [max(0.001, x["probability"] ** 4) for x in pool]
                remaining=list(pool); rem_weights=list(weights)
                candidate=[]
                while len(candidate) < count and remaining:
                    chosen_index = rng.choices(range(len(remaining)), weights=rem_weights, k=1)[0]
                    candidate.append(remaining.pop(chosen_index)); rem_weights.pop(chosen_index)
                signature = tuple(sorted(x["fixture_id"] for x in candidate))
                if signature not in seen:
                    selected = candidate
                    seen.add(signature)
                    out.append(Slip(period, idx, now, selected, seed))
                    break
            if selected is None:
                raise ValueError(f"Unable to generate {slips} unique slips from {len(pool)} eligible matches.")
        return out

    def daily(self, fixtures: list[Fixture]) -> Slip:
        eligible_count = len(self.eligible(fixtures))
        target = min(10, eligible_count)
        if target < 5:
            raise ValueError("Daily slip requires at least 5 eligible matches.")
        return self.generate("daily", fixtures, target, 1)[0]

    def weekly(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("weekly", fixtures, 20, 5)

    def monthly(self, fixtures: list[Fixture]) -> list[Slip]:
        eligible_count = len(self.eligible(fixtures))
        if eligible_count < 35:
            raise ValueError("Monthly package requires at least 35 eligible matches to make five distinct slips of 30+ matches.")
        # Keep at least five matches outside the selected size so five distinct combinations are possible.
        target = min(50, max(30, eligible_count - 5))
        return self.generate("monthly", fixtures, target, 5)
