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

CORE_MAJOR_LEAGUE_ALIASES = {
    "England — Premier League": ("premier league",),
    "Spain — LaLiga": ("laliga", "la liga"),
    "Germany — Bundesliga": ("bundesliga",),
    "Italy — Serie A": ("serie a",),
    "France — Ligue 1": ("ligue 1",),
    "Belgium — Jupiler Pro League": ("jupiler",),
    "Netherlands — Eredivisie": ("eredivisie",),
    "Portugal — Primeira Liga": ("primeira liga",),
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
            # Slip selections must carry a trustworthy competition label.
            # Unknown/missing league metadata is not safe for a packaged slip,
            # so leave those fixtures to the broad provider fetch without
            # allowing them into the final slip.
            league_name = str(getattr(fx, "league", "") or "").strip()
            if league_name.casefold() in {"", "unknown", "n/a", "none"}:
                continue
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
            count = int(count)
            if count < minimum or count > maximum:
                raise ValueError(
                    f"{period.title()} slip size must be {minimum}-{maximum} matches."
                )

        if len(fixture_ids) < minimum:
            raise ValueError(
                f"Only {len(fixture_ids)} eligible fixtures; "
                f"{period.title()} slips require at least {minimum}."
            )

        def league_text(value: str) -> str:
            return " ".join(
                str(value or "").strip().casefold().replace("-", " ").split()
            )

        major_to_fixtures: dict[str, list[str]] = defaultdict(list)
        for fixture_id in fixture_ids:
            league = league_text(by_fixture[fixture_id][0].get("league"))
            for major_name, aliases in CORE_MAJOR_LEAGUE_ALIASES.items():
                if any(alias in league for alias in aliases):
                    major_to_fixtures[major_name].append(fixture_id)
                    break

        available_majors = [
            name for name in CORE_MAJOR_LEAGUE_ALIASES
            if major_to_fixtures.get(name)
        ]

        family_to_fixtures: dict[str, list[str]] = defaultdict(list)
        for fixture_id in fixture_ids:
            for item in by_fixture[fixture_id]:
                family_to_fixtures[item["family"]].append(fixture_id)

        used_fixture_counts: Counter[str] = Counter()
        used_exact_outcomes: Counter[tuple[str, str, str]] = Counter()
        used_families: Counter[str] = Counter()

        def choose_candidate(
            candidates: list[dict],
            rng: random.Random,
            slip_family_counts: Counter[str],
            *,
            prefer_new_family: bool = True,
        ) -> dict:
            if not candidates:
                raise ValueError("No candidate markets available for fixture.")

            # Reused fixtures rotate through genuinely different exact outcomes
            # before repeating one already published in an earlier slip.
            min_exact = min(
                used_exact_outcomes[
                    (item["fixture_id"], item["market"], item["selection"])
                ]
                for item in candidates
            )
            fresh = [
                item for item in candidates
                if used_exact_outcomes[
                    (item["fixture_id"], item["market"], item["selection"])
                ] == min_exact
            ]

            if prefer_new_family:
                new_family = [
                    item for item in fresh
                    if slip_family_counts[item["family"]] == 0
                ]
                if new_family:
                    fresh = new_family

            weights = []
            for item in fresh:
                exact_key = (item["fixture_id"], item["market"], item["selection"])
                weights.append(
                    max(0.001, float(item["probability"]) ** 2.5)
                    * (1.0 / (1.0 + used_exact_outcomes[exact_key]))
                    * (1.0 / (1.0 + slip_family_counts[item["family"]]))
                    * (1.0 / (1.0 + used_families[item["family"]] * 0.15))
                )
            return dict(rng.choices(fresh, weights=weights, k=1)[0])

        def build_one_slip(
            slip_index: int,
            rng: random.Random,
            target: int,
        ) -> tuple[list[dict], tuple[str, ...]]:
            selected: list[dict] = []
            seeded_fixtures: set[str] = set()
            slip_family_counts: Counter[str] = Counter()

            def add_item(item: dict) -> None:
                selected.append(dict(item))
                fid = item["fixture_id"]
                seeded_fixtures.add(fid)
                slip_family_counts[item["family"]] += 1
                used_fixture_counts[fid] += 1
                used_exact_outcomes[
                    (fid, item["market"], item["selection"])
                ] += 1
                used_families[item["family"]] += 1

            # Reserve one fixture from every core major that has at least one
            # eligible fixture. The remaining slots are open to all leagues.
            major_order = (
                available_majors[slip_index - 1:]
                + available_majors[:slip_index - 1]
            )
            for major_name in major_order:
                if len(selected) >= target:
                    break
                candidates = [
                    fid for fid in dict.fromkeys(major_to_fixtures[major_name])
                    if fid not in seeded_fixtures
                ]
                if not candidates:
                    continue
                candidates.sort(key=lambda fid: (used_fixture_counts[fid], fid))
                fid = candidates[rng.randrange(min(len(candidates), 5))]
                add_item(
                    choose_candidate(
                        by_fixture[fid],
                        rng,
                        slip_family_counts,
                        prefer_new_family=True,
                    )
                )

            # Seed distinct market/outcome families before general filling.
            desired_family_count = min(5, len(family_to_fixtures), target)
            family_order = list(family_to_fixtures)
            rng.shuffle(family_order)
            for family in family_order:
                if (
                    len(selected) >= target
                    or len(slip_family_counts) >= desired_family_count
                ):
                    break
                candidates = [
                    fid for fid in dict.fromkeys(family_to_fixtures[family])
                    if fid not in seeded_fixtures
                ]
                if not candidates:
                    continue
                candidates.sort(key=lambda fid: (used_fixture_counts[fid], fid))
                fid = candidates[rng.randrange(min(len(candidates), 5))]
                family_candidates = [
                    item for item in by_fixture[fid]
                    if item["family"] == family
                ]
                add_item(
                    choose_candidate(
                        family_candidates,
                        rng,
                        slip_family_counts,
                        prefer_new_family=True,
                    )
                )

            available = [
                fid for fid in fixture_ids if fid not in seeded_fixtures
            ]
            while available and len(selected) < target:
                fixture_weights: list[tuple[str, float]] = []
                for fid in available:
                    best = 0.001
                    for item in by_fixture[fid]:
                        exact_key = (fid, item["market"], item["selection"])
                        best = max(
                            best,
                            max(0.001, float(item["probability"]) ** 2.5)
                            * (1.0 / (1.0 + used_exact_outcomes[exact_key]))
                            * (1.0 / (1.0 + used_fixture_counts[fid]))
                            * (1.0 / (1.0 + slip_family_counts[item["family"]]))
                            * (
                                1.0
                                / (1.0 + used_families[item["family"]] * 0.15)
                            ),
                        )
                    fixture_weights.append((fid, best))

                ids = [fid for fid, _ in fixture_weights]
                weights = [weight for _, weight in fixture_weights]
                fid = rng.choices(ids, weights=weights, k=1)[0]
                available.remove(fid)
                add_item(
                    choose_candidate(
                        by_fixture[fid],
                        rng,
                        slip_family_counts,
                        prefer_new_family=True,
                    )
                )

            if len(selected) != target:
                raise ValueError(
                    f"Unable to generate Slip #{slip_index} with {target} "
                    f"matches from {len(fixture_ids)} eligible fixtures."
                )

            signature = tuple(sorted(
                f"{item['fixture_id']}|{item['market']}|{item['selection']}"
                for item in selected
            ))
            return selected, signature

        out: list[Slip] = []
        used_signatures: set[tuple[str, ...]] = set()

        for slip_index in range(1, requested_slips + 1):
            seed = hashlib.sha256(
                f"{self.salt}|{period}|{now.date().isoformat()}|{slip_index}".encode()
            ).hexdigest()
            target = count if count is not None else self._target_size(
                period, random.Random(seed)
            )
            target = min(target, len(fixture_ids))

            success = False
            last_error: Exception | None = None

            # Every retry rebuilds the entire slip under the same rules. This
            # prevents a retry from accidentally dropping major coverage,
            # fixture uniqueness, or outcome diversification.
            for attempt in range(60):
                attempt_seed = hashlib.sha256(
                    f"{seed}|attempt|{attempt}".encode()
                ).hexdigest()
                rng = random.Random(attempt_seed)

                snapshot_fixture = used_fixture_counts.copy()
                snapshot_exact = used_exact_outcomes.copy()
                snapshot_family = used_families.copy()

                try:
                    selected, signature = build_one_slip(
                        slip_index, rng, target
                    )

                    if len(available_majors) <= target:
                        selected_leagues = {
                            league_text(item["league"]) for item in selected
                        }
                        missing = []
                        for major_name in available_majors:
                            aliases = CORE_MAJOR_LEAGUE_ALIASES[major_name]
                            if not any(
                                any(alias in league for alias in aliases)
                                for league in selected_leagues
                            ):
                                missing.append(major_name)
                        if missing:
                            raise ValueError(
                                "Missing major leagues: " + ", ".join(missing)
                            )

                    if signature in used_signatures:
                        raise ValueError("Duplicate slip signature")

                    out.append(
                        Slip(
                            period,
                            slip_index,
                            now,
                            selected,
                            seed,
                        )
                    )
                    used_signatures.add(signature)
                    success = True
                    break
                except Exception as exc:
                    last_error = exc
                    used_fixture_counts = snapshot_fixture
                    used_exact_outcomes = snapshot_exact
                    used_families = snapshot_family

            if not success:
                raise ValueError(
                    f"Unable to produce 5 different {period} slips from "
                    f"{len(fixture_ids)} eligible fixtures"
                    + (f": {last_error}" if last_error else ".")
                )

        # Final package-level validation is deliberately strict because this is
        # the last gate before the JSON is presented to the user.
        if len(out) != 5:
            raise ValueError("Slip package must contain exactly 5 slips.")

        for slip in out:
            expected_min, expected_max = rule["min_matches"], rule["max_matches"]
            if not expected_min <= len(slip.selections) <= expected_max:
                raise ValueError(
                    f"{period.title()} Slip #{slip.slip_number} is outside "
                    f"the {expected_min}-{expected_max} match range."
                )

            fixture_ids_in_slip = [
                str(item.get("fixture_id", "")) for item in slip.selections
            ]
            if len(fixture_ids_in_slip) != len(set(fixture_ids_in_slip)):
                raise ValueError(
                    f"Slip #{slip.slip_number} contains a duplicate fixture."
                )

            for item in slip.selections:
                if league_text(item.get("league")) in {"", "unknown", "n/a", "none"}:
                    raise ValueError(
                        f"Slip #{slip.slip_number} contains an unknown league."
                    )

        signatures = {
            tuple(sorted(
                f"{item['fixture_id']}|{item['market']}|{item['selection']}"
                for item in slip.selections
            ))
            for slip in out
        }
        if len(signatures) != 5:
            raise ValueError("Generated slip package contains duplicate slips.")

        return out

    def daily(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("daily", fixtures, None, 5)

    def weekly(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("weekly", fixtures, None, 5)

    def monthly(self, fixtures: list[Fixture]) -> list[Slip]:
        return self.generate("monthly", fixtures, None, 5)
