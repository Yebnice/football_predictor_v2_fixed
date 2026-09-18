from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
import logging

from .schemas import Fixture
from .data_providers import FootballProvider, _extract_1x2_odds

logger = logging.getLogger(__name__)


class CompositeFootballProvider(FootballProvider):
    """Provider router with graceful fallback across multiple providers.

    The router deliberately keeps the normalized `FootballProvider` contract so
    the prediction engine does not care where data came from. In `fallback`
    mode the first provider that returns useful data wins. In `merge` mode all
    providers are queried and fixtures are de-duplicated by team names/date.
    Method-level lookups (details/events/lineups/odds) always fall through when
    the preferred provider has no data.
    """

    def __init__(self, providers: Iterable[tuple[str, FootballProvider]], mode: str = "fallback"):
        self.providers = list(providers)
        self.mode = mode if mode in {"fallback", "merge"} else "fallback"

    @property
    def provider_names(self) -> list[str]:
        return [name for name, _ in self.providers]

    def _ordered_for_fixture(self, fixture_id: str) -> list[tuple[str, FootballProvider]]:
        # Prefix-aware routing first. New providers should prefix IDs where
        # practical (e.g. thesportsdb-2494047, football-data-123).
        lower = fixture_id.lower()
        for idx, (name, provider) in enumerate(self.providers):
            if lower.startswith(f"{name.lower()}-"):
                return [(name, provider)] + self.providers[:idx] + self.providers[idx + 1:]
        return self.providers

    @staticmethod
    def _fixture_key(fx: Fixture) -> tuple[str, str, str, str]:
        return (
            fx.date.astimezone(timezone.utc).date().isoformat() if fx.date.tzinfo else fx.date.date().isoformat(),
            fx.home_team.strip().casefold(),
            fx.away_team.strip().casefold(),
            fx.league.strip().casefold(),
        )

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None,
                 minimum: int = 0) -> list[Fixture]:
        successful: list[tuple[str, list[Fixture]]] = []
        errors: list[str] = []
        collected: list[Fixture] = []
        collected_seen: set[tuple[str, str, str, str]] = set()
        minimum = max(0, int(minimum or 0))
        for name, provider in self.providers:
            try:
                rows = provider.fixtures(start, end, live=live, league=league, season=season)
                if rows:
                    successful.append((name, rows))
                    if self.mode == "fallback" and minimum <= 0:
                        for fx in rows:
                            fx.stats = {**(fx.stats or {}), "provider": name, "provider_chain_mode": self.mode}
                        return rows
                    if self.mode == "fallback" and minimum > 0:
                        for fx in rows:
                            key = self._fixture_key(fx)
                            if key in collected_seen:
                                continue
                            collected_seen.add(key)
                            fx.stats = {**(fx.stats or {}), "provider": name, "provider_chain_mode": self.mode}
                            collected.append(fx)
                        if len(collected) >= minimum:
                            return collected
            except (RuntimeError, ValueError, OSError) as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Football provider %s failed: %s", name, exc)
            except Exception as exc:  # HTTP clients may expose provider-specific exceptions.
                errors.append(f"{name}: {exc}")
                logger.warning("Football provider %s failed unexpectedly: %s", name, exc)

        if successful and self.mode == "merge":
            merged: list[Fixture] = []
            seen: dict[tuple[str, str, str, str], Fixture] = {}
            # Provider order is trusted: earlier providers win when the same
            # match is returned by multiple sources.
            for name, rows in successful:
                for fx in rows:
                    key = self._fixture_key(fx)
                    if key not in seen:
                        fx.stats = {**(fx.stats or {}), "provider": name, "provider_chain_mode": self.mode}
                        seen[key] = fx
                        merged.append(fx)
            return merged

        if self.mode == "fallback" and minimum > 0 and collected:
            # We got real data but not enough to satisfy the caller's package
            # requirement. Return it so the caller can report an honest
            # "need more fixtures" error rather than silently fabricating data.
            return collected
        if errors:
            raise RuntimeError("All configured football providers failed: " + " | ".join(errors))
        return []

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        errors: list[str] = []
        for name, provider in self._ordered_for_fixture(fixture_id):
            try:
                fx = provider.fixture_by_id(fixture_id)
                if fx:
                    # Preserve the primary provider's normalized fixture data,
                    # then opportunistically enrich it with 1X2 odds from an
                    # odds-capable provider when the primary source has none.
                    # This is especially useful with TheSportsDB-first routing:
                    # TheSportsDB supplies free fixtures/form and often exposes
                    # idAPIfootball, while API-Football can supply bookmaker odds.
                    if not fx.odds:
                        self._enrich_odds(fx, fixture_id)
                    fx.stats = {**(fx.stats or {}), "provider": name, "provider_chain_mode": self.mode}
                    return fx
            except (RuntimeError, ValueError, OSError) as exc:
                errors.append(f"{name}: {exc}")
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            logger.info("fixture_by_id(%s) had provider misses: %s", fixture_id, " | ".join(errors))
        return None

    def _enrich_odds(self, fx: Fixture, fixture_id: str) -> None:
        """Best-effort normalize 1X2 odds from an API-Football-like provider.

        The primary fixture provider remains authoritative for identity/form;
        this only fills the optional `Fixture.odds` field. It never raises.
        """
        api_id = (fx.stats or {}).get("api_football_id")
        for name, provider in self.providers:
            if name not in {"api-football", "api-sports", "apisports"}:
                continue
            candidate_id = str(api_id or fixture_id)
            try:
                raw = provider.odds(candidate_id)
                normalized = _extract_1x2_odds(raw, fx.home_team, fx.away_team)
                if normalized:
                    fx.odds = normalized
                    fx.stats = {**(fx.stats or {}), "odds_provider": name, "odds_fixture_id": candidate_id}
                    return
            except Exception as exc:
                logger.debug("%s odds enrichment failed for %s: %s", name, candidate_id, exc)

    def fixture_details(self, fixture_id: str) -> dict[str, Any]:
        for name, provider in self._ordered_for_fixture(fixture_id):
            try:
                data = provider.fixture_details(fixture_id)
                if data:
                    return {"provider": name, **data}
            except Exception as exc:
                logger.debug("%s fixture_details failed: %s", name, exc)
        return {}

    def events(self, fixture_id: str) -> list[dict[str, Any]]:
        for name, provider in self._ordered_for_fixture(fixture_id):
            try:
                data = provider.events(fixture_id)
                if data:
                    return [{"provider": name, **row} for row in data]
            except Exception as exc:
                logger.debug("%s events failed: %s", name, exc)
        return []

    def lineups(self, fixture_id: str) -> list[dict[str, Any]]:
        for name, provider in self._ordered_for_fixture(fixture_id):
            try:
                data = provider.lineups(fixture_id)
                if isinstance(data, dict):
                    # Some providers (currently Sofascore via EasySoccerData)
                    # return one structured dict containing both teams rather than
                    # a list of rows. Preserve that payload instead of iterating its keys.
                    return [{"provider": name, "data": data}]
                if data:
                    return [{"provider": name, **row} for row in data]
            except Exception as exc:
                logger.debug("%s lineups failed: %s", name, exc)
        return []

    def odds(self, fixture_id: str) -> dict[str, Any]:
        ordered = self._ordered_for_fixture(fixture_id)
        # First try the fixture id as supplied. This keeps native ids working.
        for name, provider in ordered:
            try:
                data = provider.odds(fixture_id)
                if data:
                    return {"provider": name, **data}
            except Exception as exc:
                logger.debug("%s odds failed: %s", name, exc)

        # Cross-provider bridge: TheSportsDB exposes idAPIfootball on many
        # events. When API-Football is configured, use that canonical id to get
        # bookmaker odds while keeping TheSportsDB as the free fixture source.
        try:
            fx = self.fixture_by_id(fixture_id)
            api_id = (fx.stats or {}).get("api_football_id") if fx else None
            if api_id:
                for name, provider in self.providers:
                    if name in {"api-football", "api-sports", "apisports"}:
                        data = provider.odds(str(api_id))
                        if data:
                            return {"provider": name, "bridged_from": fixture_id, **data}
        except Exception as exc:
            logger.debug("cross-provider odds bridge failed for %s: %s", fixture_id, exc)
        return {}

    def close(self) -> None:
        for _, provider in self.providers:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception("Failed to close football provider %s", type(provider).__name__)
