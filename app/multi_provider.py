from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
import logging

from .schemas import Fixture
from .data_providers import FootballProvider, _extract_1x2_odds

logger = logging.getLogger(__name__)


# API-Football -> TheSportsDB league IDs. This lets the app keep one public
# league selector while falling back to the free TheSportsDB feed when an
# API-Football free key cannot access the current season.
API_FOOTBALL_TO_THESPORTSDB: dict[str, str] = {
    "39": "4328",   # England Premier League
    "140": "4335",  # Spain La Liga
    "78": "4331",   # Germany Bundesliga
    "135": "4332",  # Italy Serie A
    "61": "4334",   # France Ligue 1
    "88": "4337",   # Netherlands Eredivisie
    "94": "4344",   # Portugal Primeira Liga
    "179": "4330",  # Scotland Premiership
    "144": "4338",  # Belgium Jupiler League
    "203": "4339",  # Turkey Super Lig
    "197": "4336",  # Greece Super League
    "218": "4621",  # Austria Bundesliga
    "207": "4675",  # Switzerland Super League
    "119": "4340",  # Denmark Superliga
    "103": "4358",  # Norway Eliteserien
    "113": "4347",  # Sweden Allsvenskan
    "106": "4422",  # Poland Ekstraklasa
    "345": "4631",  # Czech First League
    "210": "4629",  # Croatia HNL
    "286": "4671",  # Serbia Super Liga
    "283": "4691",  # Romania Liga I
    "333": "4354",  # Ukraine Premier League
    "235": "4355",  # Russia Premier League
    "233": "4829",  # Egypt Premier League
    "200": "4520",  # Morocco Botola
    "186": "4753",  # Algeria Ligue 1
    "202": "4828",  # Tunisia Ligue 1
    "288": "4802",  # South Africa Premier Soccer League
    "399": "4827",  # Nigeria NPFL
    "307": "4668",  # Saudi Pro League
    "301": "4678",  # UAE Pro League
    "305": "4663",  # Qatar Stars League
    "98": "4633",   # Japan J1 League
    "292": "4689",  # South Korea K League 1
    "253": "4346",  # USA MLS
    "71": "4351",   # Brazil Brasileirao
    "128": "4406",  # Argentina Primera Division
    "262": "4350",  # Mexico Primera League
    "239": "4497",  # Colombia Primera A
    "265": "4627",  # Chile Primera Division
    "242": "4686",  # Ecuador Serie A
    "268": "4432",  # Uruguay Primera Division
    "188": "4356",  # Australia A-League
}

# API-Football -> football-data.org competition codes for the competitions
# currently included in football-data.org's Free tier.
API_FOOTBALL_TO_FOOTBALL_DATA: dict[str, str] = {
    "39": "PL",    # England Premier League
    "140": "PD",   # Spain La Liga
    "78": "BL1",   # Germany Bundesliga
    "135": "SA",   # Italy Serie A
    "61": "FL1",   # France Ligue 1
    "88": "DED",   # Netherlands Eredivisie
    "94": "PPL",   # Portugal Primeira Liga
    "71": "BSA",   # Brazil Serie A
}

API_FOOTBALL_TO_OPENFOOTBALL: dict[str, str] = {
    "39": "en.1",
    "140": "es.1",
    "78": "de.1",
    "135": "it.1",
    "61": "fr.1",
    "88": "nl.1",
    "94": "pt.1",
}

API_FOOTBALL_TO_BIGBALLS: dict[str, str] = {
    "39": "epl",
    "140": "laliga",
    "78": "bundesliga",
    "135": "serie-a",
    "61": "ligue-1",
}



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
        # The sidebar sends API-Football numeric league IDs. Never let a
        # fallback provider answer with an unrelated default league when the
        # selected competition list cannot be represented in that provider's
        # native ID system. Returning the wrong league is worse than returning
        # an empty result.
        api_league_selection = False
        if isinstance(league, str):
            tokens = [x.strip() for x in league.split(",") if x.strip()]
            api_league_selection = bool(tokens) and all(token.isdigit() for token in tokens)
        elif isinstance(league, int):
            api_league_selection = True

        for name, provider in self.providers:
            if api_league_selection and name not in {
                "api-football", "api-sports", "apisports",
                "bigballsdata", "big-balls-data", "bigballs",
                "football-data", "football-data-org", "football-data.org",
                "isportsapi", "isports",
                "thesportsdb", "the-sports-db", "thesportsdb-v1",
                "openfootball", "open-football", "football-json",
                "bsd", "bzzoiro", "bzzoiro-sports-data",
            }:
                continue
            try:
                if name in {"api-football", "api-sports", "apisports"}:
                    provider_league = league
                    provider_season = season
                    rows = provider.fixtures(
                        start, end, live=live, league=provider_league, season=provider_season
                    )
                elif name in {"bsd", "bzzoiro", "bzzoiro-sports-data"} and api_league_selection:
                    tokens = [str(league)] if isinstance(league, int) else [
                        x.strip() for x in str(league).split(",") if x.strip()
                    ]
                    rows = []
                    for token in dict.fromkeys(tokens):
                        rows.extend(
                            provider.fixtures(
                                start, end, live=live, league=token, season=season
                            )
                        )
                elif name in {"bigballsdata", "big-balls-data", "bigballs"} and api_league_selection:
                    tokens = [str(league)] if isinstance(league, int) else [x.strip() for x in str(league).split(",") if x.strip()]
                    mapped = [API_FOOTBALL_TO_BIGBALLS[token] for token in tokens if token in API_FOOTBALL_TO_BIGBALLS]
                    rows = []
                    if mapped:
                        for slug in dict.fromkeys(mapped):
                            rows.extend(provider.fixtures(start, end, live=live, league=slug, season=season))
                    else:
                        rows = provider.fixtures(start, end, live=live, league=None, season=season)
                elif name in {"football-data", "football-data-org", "football-data.org"} and api_league_selection:
                    tokens = [str(league)] if isinstance(league, int) else [x.strip() for x in str(league).split(",") if x.strip()]
                    translated = [API_FOOTBALL_TO_FOOTBALL_DATA[token] for token in tokens if token in API_FOOTBALL_TO_FOOTBALL_DATA]
                    if translated:
                        rows = []
                        for competition in dict.fromkeys(translated):
                            rows.extend(
                                provider.fixtures(
                                    start, end, live=live, league=competition, season=season
                                )
                            )
                    else:
                        rows = []
                elif name in {"allsportsapi", "all-sports-api", "allsports"} and api_league_selection:
                    # AllSportsAPI uses its own league IDs. This adapter does not
                    # currently expose a league catalogue, so skip numeric-league
                    # translation here and allow the next mapped provider to try.
                    rows = []
                elif name in {"openfootball", "open-football", "football-json"} and api_league_selection:
                    tokens = [str(league)] if isinstance(league, int) else [x.strip() for x in str(league).split(",") if x.strip()]
                    translated = [API_FOOTBALL_TO_OPENFOOTBALL[token] for token in tokens if token in API_FOOTBALL_TO_OPENFOOTBALL]
                    rows = []
                    provider_season = season
                    for code in dict.fromkeys(translated):
                        rows.extend(
                            provider.fixtures(
                                start, end, live=live, league=code, season=provider_season
                            )
                        )
                elif name in {"thesportsdb", "the-sports-db", "thesportsdb-v1"} and api_league_selection:
                    # Translate the app's API-Football numeric league selection
                    # into TheSportsDB's league namespace and query each selected
                    # competition separately.
                    tokens = [str(league)] if isinstance(league, int) else [x.strip() for x in str(league).split(",") if x.strip()]
                    translated = []
                    for token in tokens:
                        db_league = API_FOOTBALL_TO_THESPORTSDB.get(token)
                        if db_league:
                            translated.append(db_league)
                    rows = []
                    provider_season = season
                    if provider_season is not None:
                        try:
                            provider_season = f"{int(provider_season)}-{int(provider_season) + 1}"
                        except (TypeError, ValueError):
                            pass
                    for db_league in translated:
                        rows.extend(
                            provider.fixtures(
                                start, end, live=live, league=db_league, season=provider_season
                            )
                        )
                else:
                    provider_league = None
                    rows = provider.fixtures(
                        start, end, live=live, league=provider_league, season=season
                    )
                # Do not treat structurally empty fixtures as useful data. A
                # provider can return rows with missing participants when its
                # upstream schema changes; those rows must not block a later
                # provider in the fallback chain.
                usable = [
                    fx for fx in rows
                    if str(getattr(fx, "home_team", "") or "").strip().casefold() not in {"", "unknown"}
                    and str(getattr(fx, "away_team", "") or "").strip().casefold() not in {"", "unknown"}
                ]
                if usable:
                    successful.append((name, usable))
                    rows = usable
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
        """Best-effort odds enrichment from configured odds-capable providers.

        BSD exposes free consensus 1X2 prices directly from the event odds
        endpoint; API-Football remains supported as another optional source.
        """
        for name, provider in self.providers:
            if name not in {"bsd", "bzzoiro", "bzzoiro-sports-data", "api-football", "api-sports", "apisports"}:
                continue
            try:
                candidate_id = fixture_id
                if name in {"api-football", "api-sports", "apisports"}:
                    candidate_id = str((fx.stats or {}).get("api_football_id") or fixture_id)
                    raw = provider.odds(candidate_id)
                    normalized = _extract_1x2_odds(raw, fx.home_team, fx.away_team)
                else:
                    raw = provider.odds(candidate_id)
                    odds = raw.get("odds") if isinstance(raw, dict) else None
                    normalized = {}
                    if isinstance(odds, dict):
                        for source, target in {"home_win": "home", "draw": "draw", "away_win": "away"}.items():
                            try:
                                if odds.get(source) is not None:
                                    normalized[target] = float(odds[source])
                            except (TypeError, ValueError):
                                pass
                if normalized:
                    fx.odds = normalized
                    fx.stats = {**(fx.stats or {}), "odds_provider": name, "odds_fixture_id": candidate_id}
                    return
            except Exception as exc:
                logger.debug("%s odds enrichment failed for %s: %s", name, fixture_id, exc)

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

    def head_to_head(self, home_team_id: int | str, away_team_id: int | str, limit: int = 5) -> list[dict[str, Any]]:
        for name, provider in self.providers:
            try:
                data = provider.head_to_head(home_team_id, away_team_id, limit=limit)
                if data:
                    return data
            except Exception as exc:
                logger.debug("%s head-to-head failed: %s", name, exc)
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
