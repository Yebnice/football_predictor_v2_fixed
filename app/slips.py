from __future__ import annotations
from datetime import datetime, timezone
import hashlib, random
from collections import Counter, defaultdict
from typing import Iterable
from .engine import FootballProbabilityEngine, TIP_MARKETS, TIP_TOTAL_GOALS_LINES, TIP_TEAM_GOALS_LINES, MAX_TIP_PROBABILITY
from .schemas import Fixture, Slip


PERIOD_RULES = {
    "daily": {"min_matches": 10, "max_matches": 15, "slips": 5},
    "weekly": {"min_matches": 20, "max_matches": 30, "slips": 5},
    "monthly": {"min_matches": 20, "max_matches": 50, "slips": 5},
}


def _tip_eligible(market) -> bool:
    if market.market == "Total Goals":
        return market.selection in TIP_TOTAL_GOALS_LINES
    if market.market in TIP_MARKETS:
        return True
    if market.market.endswith(" Goals"):
        return market.selection in TIP_TEAM_GOALS_LINES
    return False


def _family(market) -> str:
    """Group exact selections into broader outcome families for diversification."""
    text = str(market.selection or "").strip()
    if text in {"Home Win", "Draw", "Away Win"}:
        return text
    if text in {"1X", "X2", "12"}:
        return "Double Chance"
    if text in {"Yes", "No"} and market.market == "BTTS":
        return "BTTS"
    if text.startswith("Over "):
        return "Over"
    if text.startswith("Under "):
        return "Under"
    return market.market


class SlipGenerator:
    """Generate deterministic, reproducible slip packages with diversification.

    Product rules:
      - exactly five slips per daily/weekly/monthly package;
      - daily: 10-15 selections/slip;
      - weekly: 20-30 selections/slip;
      - monthly: 20-50 selections/slip;
      - one selection per fixture within a slip;
      - different fixture combinations across slips whenever the fixture pool
        makes that possible;
      - when a fixture must be reused across slips, prefer a different market
        outcome for that fixture;
      - only publishable model markets in the configured probability band are
        eligible; no synthetic selections are created.
    """

    def __init__(self, engine: FootballProbabilityEngine, min_confidence: float = .60, salt: str = "change-me"):
        self.engine = engine
        self.min_confidence = float(min_confidence)
        self.salt = salt

    def eligible(self, fixtures: Iterable[Fixture]) -> list[dict]:
        pool: list[dict] = []
        for fx in fixtures:
            candidates = [
                m for m in self.engine.markets(fx)
                if _tip_eligible(m)
                and self.min_confidence <= m.probability <= MAX_TIP_PROBABILITY
            ]
            # Keep a small set of genuinely different outcomes per fixture.
            # This prevents the generator from seeing one fixture as hundreds of
            # equivalent candidates while still allowing outcome diversification.
            candidates.sort(key=lambda m: m.probability, reverse=True)
            seen_family: set[str] = set()
            for p in candidates:
                family = _family(p)
                if family in seen_family:
                    continue
                seen_family.add(family)
                pool.append({
                    "fixture_id": fx.fixture_id,
                    "date": fx.date.isoformat(),
                    "league": fx.league,
                    "home_team": fx.home_team,
                    "away_team": fx.away_team,
                    "market": p.market,
                    "selection": p.selection,
                    "probability": p.probability,
                    "fair_odds": p.fair_odds,
                    "market_odds": p.market_odds,
                    "edge": p.edge,
                    "family": family,
                })
        return pool

    @staticmethod
    def _target_size(period: str, rng: random.Random) -> int:
        rule = PERIOD_RULES.get(period)
        if not rule:
            raise ValueError(f"Unsupported slip period: {period}")
        return rng.randint(rule["min_matches"], rule["max_matches"])

    def generate(
        self,
        period: str,
        fixtures: list[Fixture],
        count: int | None,
        slips: int | None,
        now: datetime | None = None,
    ) -> list[Slip]:
        period = period.strip().lower()
        rule = PERIOD_RULES.get(period)
        if not rule:
            raise ValueError(f"Unsupported slip period: {period}")

        now = now or datetime.now(timezone.utc)
        requested_slips = int(slips if slips is not None else rule["slips"])
        if requested_slips != 5:
            raise ValueError("This package format requires exactly 5 slips.")

        pool = self.eligible(fixtures)
        by_fixture: dict[str, list[dict]] = defaultdict(list)
        for item in pool:
            by_fixture[item["fixture_id"]].append(item)

        fixture_ids = list(by_fixture)
        minimum = rule["min_matches"]
        maximum = rule["max_matches"]
        if count is not None:
            # Legacy callers can still provide a fixed size, but it must remain
            # inside the product rule for the selected period.
            count = int(count)
            if count < minimum or count > maximum:
                raise ValueError(f"{period.title()} slip size must be {minimum}-{maximum} matches.")
        if len(fixture_ids) < minimum:
            raise ValueError(
                f"Only {len(fixture_ids)} eligible fixtures; {period.title()} slips require at least {minimum}."
            )

        out: list[Slip] = []
        used_signatures: set[tuple[str, ...]] = set()
        used_fixture_counts: Counter[str] = Counter()
        used_exact_outcomes: Counter[tuple[str, str, str]] = Counter()
        used_families: Counter[str] = Counter()

        for slip_index in range(1, requested_slips + 1):
            seed = hashlib.sha256(
                f"{self.salt}|{period}|{now.date().isoformat()}|{slip_index}".encode()
            ).hexdigest()
            rng = random.Random(seed)
            target = count if count is not None else self._target_size(period, rng)
            # Never exceed the available unique fixtures. The lower bound is
            # checked above, so this still stays inside the product range.
            target = min(target, len(fixture_ids))
            selected: list[dict] = []
            slip_family_counts: Counter[str] = Counter()

            # Seed the slip with several different outcome families when the
            # available pool supports them. This prevents a package from
            # collapsing into dozens of "Under" selections.
            family_to_fixtures: dict[str, list[str]] = defaultdict(list)
            for fixture_id in fixture_ids:
                for item in by_fixture[fixture_id]:
                    family_to_fixtures[item["family"]].append(fixture_id)

            family_order = list(family_to_fixtures)
            rng.shuffle(family_order)
            desired_family_count = min(4, len(family_order), target)
            seeded_fixtures: set[str] = set()
            for family in family_order:
                if len(slip_family_counts) >= desired_family_count:
                    break
                candidates = [
                    fid for fid in dict.fromkeys(family_to_fixtures[family])
                    if fid not in seeded_fixtures
                ]
                if not candidates:
                    continue
                # Prefer fixtures that have been used less often in earlier slips.
                candidates.sort(key=lambda fid: (used_fixture_counts[fid], fid))
                fid = candidates[rng.randrange(min(len(candidates), 5))]
                family_candidates = [
                    item for item in by_fixture[fid] if item["family"] == family
                ]
                chosen = rng.choice(family_candidates)
                selected.append(dict(chosen))
                seeded_fixtures.add(fid)
                slip_family_counts[family] += 1
                used_fixture_counts[fid] += 1
                used_exact_outcomes[(fid, chosen["market"], chosen["selection"])] += 1
                used_families[family] += 1

            # Sample without replacement by fixture for the remaining slots. Lower-use fixtures and
            # higher-probability outcomes are preferred, but the RNG seed makes
            # each package reproducible.
            available = list(fixture_ids)
            while available and len(selected) < target:
                weighted: list[tuple[str, float]] = []
                for fixture_id in available:
                    candidates = by_fixture[fixture_id]
                    best_weight = 0.0
                    for item in candidates:
                        exact_key = (fixture_id, item["market"], item["selection"])
                        reuse_penalty = 1.0 / (1.0 + used_exact_outcomes[exact_key])
                        fixture_penalty = 1.0 / (1.0 + used_fixture_counts[fixture_id])
                        family_penalty = 1.0 / (1.0 + slip_family_counts[item["family"]] + used_families[item["family"]] * 0.15)
                        best_weight = max(
                            best_weight,
                            max(0.001, float(item["probability"]) ** 2.5)
                            * reuse_penalty
                            * fixture_penalty
                            * family_penalty,
                        )
                    weighted.append((fixture_id, best_weight))

                ids = [x[0] for x in weighted]
                weights = [x[1] for x in weighted]
                fixture_id = rng.choices(ids, weights=weights, k=1)[0]
                available.remove(fixture_id)

                candidates = sorted(
                    by_fixture[fixture_id],
                    key=lambda item: (
                        1.0 / (1.0 + used_exact_outcomes[
                            (fixture_id, item["market"], item["selection"])
                        ]),
                        1.0 / (1.0 + used_fixture_counts[fixture_id]),
                        float(item["probability"]),
                    ),
                    reverse=True,
                )
                # Randomly choose among the strongest candidates to avoid five
                # slips collapsing onto the same exact market outcome.
                top = candidates[: min(3, len(candidates))]
                choice_weights = [
                    max(0.001, float(item["probability"]) ** 2.5)
                    * (1.0 / (1.0 + used_exact_outcomes[
                        (fixture_id, item["market"], item["selection"])
                    ]))
                    * (1.0 / (1.0 + slip_family_counts[item["family"]]))
                    * (1.0 / (1.0 + used_families[item["family"]] * 0.15))
                    for item in top
                ]
                chosen = rng.choices(top, weights=choice_weights, k=1)[0]
                selected.append(dict(chosen))
                used_fixture_counts[fixture_id] += 1
                used_exact_outcomes[
                    (fixture_id, chosen["market"], chosen["selection"])
                ] += 1
                slip_family_counts[chosen["family"]] += 1
                used_families[chosen["family"]] += 1

            if len(selected) < target:
                raise ValueError(
                    f"Unable to generate Slip #{slip_index} with {target} matches from "
                    f"{len(fixture_ids)} eligible fixtures."
                )

            signature = tuple(sorted(
                f"{x['fixture_id']}|{x['market']}|{x['selection']}" for x in selected
            ))
            # With a sufficiently large pool this should always be unique. When
            # the pool is small, try several deterministic alternatives before
            # failing instead of silently duplicating a slip.
            if signature in used_signatures:
                for retry in range(1, 25):
                    retry_seed = hashlib.sha256(
                        f"{seed}|retry|{retry}".encode()
                    ).hexdigest()
                    retry_rng = random.Random(retry_seed)
                    rng_backup = rng
                    rng = retry_rng
                    selected_retry: list[dict] = []
                    available_retry = list(fixture_ids)
                    while available_retry and len(selected_retry) < target:
                        fid = retry_rng.choice(available_retry)
                        available_retry.remove(fid)
                        candidates = by_fixture[fid]
                        selected_retry.append(
                            dict(retry_rng.choice(candidates[: min(5, len(candidates))]))
                        )
                    if len(selected_retry) == target:
                        retry_signature = tuple(sorted(
                            f"{x['fixture_id']}|{x['market']}|{x['selection']}"
                            for x in selected_retry
                        ))
                        if retry_signature not in used_signatures:
                            selected = selected_retry
                            signature = retry_signature
                            rng = rng_backup
                            break
                    rng = rng_backup

            if signature in used_signatures:
                raise ValueError(
                    f"Unable to produce 5 different {period} slips from "
                    f"{len(fixture_ids)} eligible fixtures."
                )

            used_signatures.add(signature)
            # The file format stores only the selection fields; family is an
            # internal diversification aid and is intentionally not exported.
            for item in selected:
                item.pop("family", None)
            out.append(Slip(period, slip_index, now, selected, seed))

        return out

    def daily(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("daily", fixtures, None, 5)

    def weekly(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("weekly", fixtures, None, 5)

    def monthly(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("monthly", fixtures, None, 5)
