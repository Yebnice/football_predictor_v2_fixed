from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Iterable, Any
import time
import httpx
import logging
import threading

from .schemas import Fixture, TeamForm, TeamDiscipline

logger = logging.getLogger("football_predictor.data_providers")


class FootballProvider(ABC):
    @abstractmethod

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        raise NotImplementedError

    def fixture_details(self, fixture_id: str) -> dict[str, Any]:
        return {}

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        """Default fallback: scan a wide fixture window. Providers that can look
        up a single fixture directly (e.g. by id) should override this to avoid
        an expensive/unbounded bulk query per lookup."""
        now = datetime.now(timezone.utc)
        candidates = self.fixtures(now - timedelta(days=2), now + timedelta(days=35))
        return next((f for f in candidates if f.fixture_id == fixture_id), None)

    def events(self, fixture_id: str) -> list[dict[str, Any]]:
        return []

    def lineups(self, fixture_id: str) -> list[dict[str, Any]]:
        return []

    def odds(self, fixture_id: str) -> dict[str, Any]:
        return {}

class _TTLCache:
    """Minimal in-process TTL cache so repeated calls during a testing session
    (dashboard refreshes, retries) don't burn through a provider's daily quota.
    Not shared across processes/workers — good enough for local/live testing."""
    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            hit = self._store.get(key)
            if not hit:
                return None
            expires_at, value = hit
            if time.monotonic() > expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self.ttl, value)


class TheSportsDBProvider(FootballProvider):
    """Free TheSportsDB V1 adapter.

    TheSportsDB documents V1 as its free API. The shared key `123` is intended
    for free access; premium keys add higher limits and V2. This adapter only
    relies on documented V1 endpoints and deliberately returns a normalized
    Fixture so it can sit behind CompositeFootballProvider.
    """
    def __init__(self, api_key: str = "123", league_id: int | str = 4328,
                 base_url: str = "https://www.thesportsdb.com/api/v1/json",
                 timeout: float = 20.0, cache_ttl_seconds: float = 120.0):
        self.api_key = str(api_key or "123")
        self.league_id = str(league_id or "4328")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        self._cache = _TTLCache(cache_ttl_seconds) if cache_ttl_seconds > 0 else None

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        url = f"{self.base_url}/{self.api_key}/{endpoint}"
        key = f"{url}?{sorted(params.items())}"
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        r = self.client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict):
            raise RuntimeError("TheSportsDB returned a non-object JSON payload")
        if self._cache is not None:
            self._cache.set(key, payload)
        return payload

    @staticmethod
    def _parse_dt(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        raw = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = datetime.strptime(value[:10], "%Y-%m-%d")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _team_name(row: dict[str, Any], side: str) -> str:
        """Extract a team name from current/legacy TheSportsDB response shapes."""
        if side == "home":
            keys = ("strHomeTeam", "homeTeam", "home_team", "home", "homeTeamName", "homeName")
        else:
            keys = ("strAwayTeam", "awayTeam", "away_team", "away", "awayTeamName", "awayName")
        value = _first(row, *keys, default="")
        if isinstance(value, dict):
            value = _first(value, "display_name", "displayName", "name", "shortName", "teamName", default="")
        return str(value or "").strip()

    def _normalize_event(self, row: dict[str, Any]) -> Fixture:
        home_score = row.get("intHomeScore")
        away_score = row.get("intAwayScore")
        try:
            home_score = int(home_score) if home_score not in (None, "", "null") else None
        except (TypeError, ValueError):
            home_score = None
        try:
            away_score = int(away_score) if away_score not in (None, "", "null") else None
        except (TypeError, ValueError):
            away_score = None

        status_raw = str(row.get("strStatus") or row.get("status") or "scheduled").strip().lower()
        status = {
            "ns": "scheduled", "tbd": "scheduled", "not started": "scheduled",
            "1h": "in_play", "ht": "paused", "2h": "in_play", "et": "in_play",
            "p": "in_play", "bt": "paused", "ft": "finished",
            "aet": "finished", "pen": "finished",
            "match finished": "finished", "finished": "finished",
            "match finished after extra time": "finished",
            "match finished after penalty": "finished",
            "susp": "suspended", "suspended": "suspended",
            "int": "interrupted", "interrupted": "interrupted",
            "pst": "postponed", "postponed": "postponed",
            "canc": "cancelled", "cancelled": "cancelled",
            "abd": "abandoned", "abandoned": "abandoned",
            "awd": "technical_loss", "wo": "walkover",
        }.get(status_raw, status_raw)

        raw_home = self._team_name(row, "home")
        raw_away = self._team_name(row, "away")

        # Accept alternate event-name formats emitted by compatible normalized
        # feeds. Never invent a team name; only split an explicit match name.
        if not raw_home or not raw_away:
            event_name = str(_first(
                row, "strEvent", "name", "short_name", "shortName", default=""
            )).strip()
            for separator in (" vs ", " v ", " at ", " @ "):
                if separator in event_name:
                    left, right = [part.strip() for part in event_name.split(separator, 1)]
                    if not raw_home:
                        raw_home = left
                    if not raw_away:
                        raw_away = right
                    break

        return Fixture(
            fixture_id=f"thesportsdb-{row.get('idEvent') or row.get('id')}",
            date=self._parse_dt(
                row.get("strTimestamp") or row.get("dateEvent") or row.get("strTime") or row.get("date")
            ),
            league=str(row.get("strLeague") or row.get("league") or "Unknown"),
            season=str(row.get("strSeason") or row.get("season") or "Unknown"),
            home_team=raw_home or "Unknown",
            away_team=raw_away or "Unknown",
            status=status,
            home_score=home_score,
            away_score=away_score,
            stats={
                "source": "thesportsdb",
                "home_team_id": row.get("idHomeTeam"),
                "away_team_id": row.get("idAwayTeam"),
                "home_badge": row.get("strHomeTeamBadge"),
                "away_badge": row.get("strAwayTeamBadge"),
                "venue": row.get("strVenue"),
                "event_status_raw": row.get("strStatus"),
                "api_football_id": row.get("idAPIfootball"),
            },
        )

    @staticmethod
    def _form_from_rows(rows: list[dict[str, Any]], team_name: str, before: datetime | None = None, n: int = 5) -> TeamForm:
        """Build recent form using only completed matches strictly before the target fixture.

        The season endpoint contains the whole season, so a backtest/past-date
        query must not use results that happened after the fixture being predicted.
        The previous implementation could leak future results into historical form.
        """
        target = team_name.strip().casefold()
        matches_rows: list[tuple[datetime, dict[str, Any]]] = []
        for row in rows:
            home = str(row.get("strHomeTeam") or "").strip()
            away = str(row.get("strAwayTeam") or "").strip()
            if target not in {home.casefold(), away.casefold()}:
                continue
            try:
                hs = int(row.get("intHomeScore"))
                aw = int(row.get("intAwayScore"))
            except (TypeError, ValueError):
                continue
            dt = TheSportsDBProvider._parse_dt(row.get("strTimestamp") or row.get("dateEvent") or row.get("strTime"))
            if before is not None and dt >= before:
                continue
            matches_rows.append((dt, row))

        matches_rows.sort(key=lambda item: item[0], reverse=True)
        wins = draws = losses = gf = ga = 0.0
        for _, row in matches_rows[:n]:
            home = str(row.get("strHomeTeam") or "").strip()
            try:
                hs = int(row.get("intHomeScore"))
                aw = int(row.get("intAwayScore"))
            except (TypeError, ValueError):
                continue
            if home.casefold() == target:
                gf += hs; ga += aw
                if hs > aw: wins += 1
                elif hs == aw: draws += 1
                else: losses += 1
            else:
                gf += aw; ga += hs
                if aw > hs: wins += 1
                elif aw == hs: draws += 1
                else: losses += 1

        counted = int(wins + draws + losses)
        return TeamForm(matches=counted, wins=int(wins), draws=int(draws), losses=int(losses),
                        goals_for=gf, goals_against=ga)
    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        if live:
            raise ValueError(
                "TheSportsDB V1 free API does not provide live scores. "
                "Use API-Football or another live-score provider for live mode."
            )
        league_id = str(league or self.league_id)
        # Free V1 provides league-centric upcoming/past feeds. For longer
        # windows (e.g. Monthly slips) the season endpoint is more complete and
        # costs one request; short windows use the lighter next/past feeds.
        rows: list[dict[str, Any]] = []
        window_days = max(0, (end - start).total_seconds() / 86400)
        # The free league-next endpoint is currently returning only one event
        # (verified on 2026-09-18), which is insufficient for the app's daily
        # 5-10 pick package and weekly 20-pick package. Use the documented
        # season schedule feed for all non-live windows so we get the complete
        # schedule and avoid silently producing under-filled slips.
        if not live:
            season_label = str(season) if season else (
                f"{start.year}-{start.year + 1}"
                if start.month >= 7
                else f"{start.year - 1}-{start.year}"
            )
            try:
                season_rows = self._get(
                    "eventsseason.php", {"id": league_id, "s": season_label}
                ).get("events") or []
                rows += season_rows

                # The free V1 season feed can legitimately return an empty
                # event list even when the rolling upcoming feed has fixtures.
                # Do not mistake an empty successful response for "no matches";
                # fall back to the documented rolling feeds so the dashboard
                # remains useful.
                if not season_rows:
                    now = datetime.now(timezone.utc)
                    if end >= now:
                        rows += self._get(
                            "eventsnextleague.php", {"id": league_id}
                        ).get("events") or []
                    if start <= now:
                        rows += self._get(
                            "eventspastleague.php", {"id": league_id}
                        ).get("events") or []
            except httpx.HTTPError:
                # Some league/season combinations may not expose the season feed.
                # Fall back to the rolling endpoints rather than failing the provider.
                now = datetime.now(timezone.utc)
                if end >= now:
                    rows += self._get(
                        "eventsnextleague.php", {"id": league_id}
                    ).get("events") or []
                if start <= now:
                    rows += self._get(
                        "eventspastleague.php", {"id": league_id}
                    ).get("events") or []
        else:
            # Free V1 doesn't provide live scores; this branch is normally rejected above.
            rows += self._get("eventsnextleague.php", {"id": league_id}).get("events") or []
        past_rows = [r for r in rows if str(r.get("strStatus") or "").strip().upper() in {"FT", "AET", "PEN", "MATCH FINISHED", "FINISHED", "MATCH FINISHED AFTER EXTRA TIME", "MATCH FINISHED AFTER PENALTY"}
                     and r.get("intHomeScore") not in (None, "") and r.get("intAwayScore") not in (None, "")]
        form_cache: dict[tuple[str, str], TeamForm] = {}
        out = []
        seen: set[str] = set()
        for row in rows:
            fx = self._normalize_event(row)
            if fx.fixture_id in seen:
                continue
            seen.add(fx.fixture_id)
            # Season filtering is useful when the free feed spans a boundary.
            if season is not None and str(season) not in fx.season:
                continue
            if start <= fx.date <= end:
                hkey = (fx.home_team.casefold(), fx.date.isoformat())
                akey = (fx.away_team.casefold(), fx.date.isoformat())
                if hkey not in form_cache:
                    form_cache[hkey] = self._form_from_rows(past_rows, fx.home_team, before=fx.date)
                if akey not in form_cache:
                    form_cache[akey] = self._form_from_rows(past_rows, fx.away_team, before=fx.date)
                fx.home_form = form_cache[hkey]
                fx.away_form = form_cache[akey]
                out.append(fx)
        out.sort(key=lambda x: x.date)
        return out

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        event_id = fixture_id.removeprefix("thesportsdb-")
        payload = self._get("lookupevent.php", {"id": event_id})
        rows = payload.get("events") or []
        if not rows:
            return None

        raw = rows[0]
        fx = self._normalize_event(raw)
        # `lookupevent.php` gives the event itself but not a ready-made recent-
        # form series. The list endpoint does enrich form, so reuse it here.
        # This keeps `/match/{id}/markets` and the Streamlit detail view from
        # silently reverting to neutral 1500-ELO/empty-form defaults after the
        # fixture list already had real recent-form data. TheSportsDB's season
        # endpoint is cached, so selecting several matches is inexpensive within
        # the configured TTL.
        try:
            enriched = self.fixtures(
                fx.date - timedelta(days=1),
                fx.date + timedelta(days=1),
                league=self.league_id,
                season=fx.season,
            )
            match = next((candidate for candidate in enriched if candidate.fixture_id == fx.fixture_id), None)
            if match is not None:
                fx.home_form = match.home_form
                fx.away_form = match.away_form
        except Exception as exc:
            logger.debug("TheSportsDB form enrichment failed for %s: %s", fixture_id, exc)
        return fx

    def close(self) -> None:
        self.client.close()


class FootballDataOrgProvider(FootballProvider):
    """Adapter for football-data.org v4.

    The free plan is currently intended for registered clients and exposes
    fixtures/schedules/tables for a limited set of competitions at 10 calls/min.
    Match scores/schedules on the free plan are delayed, so this provider is a
    planning/analysis source rather than a true live-score source.
    """
    def __init__(self, api_key: str, base_url: str = "https://api.football-data.org/v4",
                 default_competition: str = "PL", timeout: float = 20.0,
                 cache_ttl_seconds: float = 120.0, enrich_form: bool = False):
        if not api_key:
            raise ValueError("FOOTBALL_DATA_API_KEY is required when football-data is enabled")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_competition = default_competition or "PL"
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"X-Auth-Token": self.api_key, "Accept": "application/json"},
            timeout=timeout,
        )
        self._cache = _TTLCache(cache_ttl_seconds) if cache_ttl_seconds > 0 else None
        self.enrich_form = enrich_form

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        key = f"{path}?{sorted(params.items())}"
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        r = self.client.get(path, params=params)
        if r.status_code == 429:
            raise RuntimeError("football-data.org rate limit hit (free plan is 10 requests/minute)")
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict):
            raise RuntimeError("football-data.org returned an unexpected JSON payload")
        if self._cache is not None:
            self._cache.set(key, payload)
        return payload

    @staticmethod
    def _normalize_match(row: dict[str, Any]) -> Fixture:
        score = row.get("score") or {}
        full = score.get("fullTime") or {}
        comp = row.get("competition") or {}
        season = row.get("season") or {}
        status = str(row.get("status") or "SCHEDULED").lower()
        # Normalize common football-data statuses to our internal vocabulary.
        status = {
            "scheduled": "scheduled", "timed": "scheduled", "in_play": "in_play",
            "paused": "paused", "finished": "finished", "postponed": "postponed",
            "suspended": "suspended", "cancelled": "cancelled",
        }.get(status, status)
        date_raw = row.get("utcDate")
        dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00")) if date_raw else datetime.now(timezone.utc)
        return Fixture(
            fixture_id=f"football-data-{row.get('id')}",
            date=dt,
            league=str(comp.get("name") or "Unknown"),
            season=str(season.get("startDate", "Unknown"))[:4],
            home_team=str((row.get("homeTeam") or {}).get("name") or "Home"),
            away_team=str((row.get("awayTeam") or {}).get("name") or "Away"),
            status=status,
            home_score=full.get("home"),
            away_score=full.get("away"),
            stats={
                "source": "football-data",
                "competition_code": comp.get("code"),
                "matchday": row.get("matchday"),
                "venue": row.get("venue"),
            },
        )

    def _resolve_competition(self, league: int | str | None) -> str:
        # football-data uses competition codes (e.g. PL) rather than numeric ids.
        return str(league or self.default_competition)

    @staticmethod
    def _form_from_rows(rows: list[dict[str, Any]], team_name: str, before: datetime | None = None, n: int = 5) -> TeamForm:
        target = team_name.strip().casefold()
        matches: list[tuple[datetime, dict[str, Any]]] = []
        for row in rows:
            home = str((row.get("homeTeam") or {}).get("name") or "").strip()
            away = str((row.get("awayTeam") or {}).get("name") or "").strip()
            if target not in {home.casefold(), away.casefold()}:
                continue
            status = str(row.get("status") or "").upper()
            if status not in {"FINISHED", "FINISHED_AFTER_EXTRA_TIME", "FINISHED_AFTER_PENALTIES"}:
                continue
            score = row.get("score") or {}
            full = score.get("fullTime") or {}
            hs, aw = full.get("home"), full.get("away")
            if hs is None or aw is None:
                continue
            try:
                dt = datetime.fromisoformat(str(row.get("utcDate")).replace("Z", "+00:00"))
                hs, aw = int(hs), int(aw)
            except (TypeError, ValueError):
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if before is not None and dt >= before:
                continue
            matches.append((dt, row))
        matches.sort(key=lambda item: item[0], reverse=True)
        wins = draws = losses = 0
        gf = ga = 0.0
        for _, row in matches[:n]:
            home = str((row.get("homeTeam") or {}).get("name") or "").strip()
            full = (row.get("score") or {}).get("fullTime") or {}
            hs, aw = int(full.get("home")), int(full.get("away"))
            if home.casefold() == target:
                gf, ga = gf + hs, ga + aw
                if hs > aw: wins += 1
                elif hs == aw: draws += 1
                else: losses += 1
            else:
                gf, ga = gf + aw, ga + hs
                if aw > hs: wins += 1
                elif aw == hs: draws += 1
                else: losses += 1
        return TeamForm(matches=wins + draws + losses, wins=wins, draws=draws, losses=losses,
                        goals_for=gf, goals_against=ga)

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        competition = self._resolve_competition(league)
        if live:
            raise ValueError("football-data.org free plan does not provide a reliable live-score feed")
        params: dict[str, Any] = {
            "dateFrom": start.date().isoformat(),
            "dateTo": end.date().isoformat(),
        }
        if season is not None:
            params["season"] = season
        payload = self._get(f"/competitions/{competition}/matches", params)
        rows = payload.get("matches", [])
        fixtures = [self._normalize_match(row) for row in rows]
        # Do not rely solely on upstream filtering. A provider, proxy, cache, or
        # future API behavior change can return a superset of the requested
        # window; returning it would contaminate daily/weekly/monthly slips.
        fixtures = [fx for fx in fixtures if start <= fx.date <= end]
        if self.enrich_form and fixtures:
            history_start = start - timedelta(days=370)
            history_end = max(end, start)
            history_params = {
                "dateFrom": history_start.date().isoformat(),
                "dateTo": history_end.date().isoformat(),
                "status": "FINISHED",
                "limit": 500,
            }
            try:
                history_payload = self._get(f"/competitions/{competition}/matches", history_params)
                history_rows = history_payload.get("matches", [])
                form_cache: dict[tuple[str, str], TeamForm] = {}
                for fx in fixtures:
                    if not (start <= fx.date <= end):
                        continue
                    hk = (fx.home_team.casefold(), fx.date.isoformat())
                    ak = (fx.away_team.casefold(), fx.date.isoformat())
                    if hk not in form_cache:
                        form_cache[hk] = self._form_from_rows(history_rows, fx.home_team, before=fx.date)
                    if ak not in form_cache:
                        form_cache[ak] = self._form_from_rows(history_rows, fx.away_team, before=fx.date)
                    fx.home_form, fx.away_form = form_cache[hk], form_cache[ak]
            except (RuntimeError, httpx.HTTPError):
                logger.warning("football-data.org form enrichment failed; returning fixtures without enriched form")
        return fixtures

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        event_id = fixture_id.removeprefix("football-data-")
        payload = self._get(f"/matches/{event_id}")
        return self._normalize_match(payload) if payload else None

    def close(self) -> None:
        self.client.close()


class ApiFootballProvider(FootballProvider):
    """Adapter for API-Football v3 at https://v3.football.api-sports.io.

    Authentication uses the documented x-apisports-key header. The adapter keeps
    provider-specific JSON out of the prediction engine by normalizing it to our
    internal Fixture schema.

    Free-plan note: API-Football's free tier caps requests at 100/day and, per
    their own docs, restricts most competitions to a specific (often older,
    e.g. 2021) season rather than the current one. If a `fixtures()` call for
    the current season returns an empty list on a free key, pass an explicit
    `season=` for that competition's free-tier season, or check `/status` to
    see which seasons your key actually covers.
    """
    def __init__(self, api_key: str, base_url: str = "https://v3.football.api-sports.io",
                 timeout: float = 30.0, cache_ttl_seconds: float = 60.0,
                 preferred_bookmaker: str = "", enrich_list_fixtures: bool = False,
                 fetch_discipline_stats: bool = False):
        if not api_key:
            raise ValueError("API_FOOTBALL_KEY is required when FOOTBALL_PROVIDER=api-football")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.preferred_bookmaker = preferred_bookmaker
        # Off by default: enriching every fixture in a list view costs up to
        # 2 extra /fixtures calls per unique team (form) plus 1 per fixture
        # (odds), which can blow through the free plan's 100/day cap fast.
        # Turn on once you're on a plan with quota to spare.
        self.enrich_list_fixtures = enrich_list_fixtures
        # Off by default and independent of enrich_list_fixtures: corners/cards
        # come from /fixtures/statistics, which is one extra call *per historical
        # match* (not per team), so a 5-match lookback costs ~5-10 calls per team
        # — expensive even for a single fixture_by_id() lookup, let alone a list.
        self.fetch_discipline_stats = fetch_discipline_stats
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key, "Accept": "application/json"},
            timeout=self.timeout,
        )
        self._cache = _TTLCache(cache_ttl_seconds) if cache_ttl_seconds > 0 else None

    def _get(self, path: str, params: dict[str, Any] | None = None, cacheable: bool = True) -> dict[str, Any]:
        params = params or {}
        cache_key = f"{path}?{sorted(params.items())}"
        if self._cache is not None and cacheable:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        response = self.client.get(path, params=params)
        if getattr(response, "status_code", None) == 429:
            raise RuntimeError(
                "API-Football rate limit hit (HTTP 429). The free plan allows 100 requests/day "
                "and a per-minute cap; wait for the quota to reset or upgrade your plan."
            )
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"API-Football error: {errors}")
        if self._cache is not None and cacheable:
            self._cache.set(cache_key, payload)
        return payload

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        if live:
            params: dict[str, Any] = {"live": "all"}
        else:
            params = {"from": start.date().isoformat(), "to": end.date().isoformat()}
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        payload = self._get("/fixtures", params, cacheable=not live)
        rows = payload.get("response", [])
        out = [_normalize_api_football_fixture(row) for row in rows]
        if not live:
            out = [fx for fx in out if start <= fx.date <= end]
        if self.enrich_list_fixtures:
            self._enrich_fixtures_batch(out, rows)
        return out

    def _enrich_fixtures_batch(self, fixtures: list[Fixture], rows: list[dict[str, Any]]) -> None:
        """Fill in form (and odds, best-effort) for every fixture in a list response.

        Form is keyed by team + target fixture date so historical fixtures in the
        same response cannot reuse a later form snapshot. The provider-level HTTP
        cache still deduplicates the underlying team-history request."""
        # Form must be keyed by team + target fixture date. Reusing one snapshot
        # for every fixture in a date range can leak later results into earlier
        # fixtures in the same list. The provider-level HTTP cache still avoids
        # repeating the underlying team-history request for the same team.
        form_by_target: dict[tuple[int, str], TeamForm] = {}
        for fx, row in zip(fixtures, rows):
            teams = row.get("teams", {})
            home_id = (teams.get("home") or {}).get("id")
            away_id = (teams.get("away") or {}).get("id")
            target_key = fx.date.isoformat()
            if home_id:
                hk = (home_id, target_key)
                if hk not in form_by_target:
                    form_by_target[hk] = self._recent_form(home_id, before=fx.date, n=20)
                fx.home_form = form_by_target[hk]
            if away_id:
                ak = (away_id, target_key)
                if ak not in form_by_target:
                    form_by_target[ak] = self._recent_form(away_id, before=fx.date, n=20)
                fx.away_form = form_by_target[ak]
            try:
                fx.odds = _extract_1x2_odds(self.odds(fx.fixture_id), fx.home_team, fx.away_team,
                                             self.preferred_bookmaker)
            except (RuntimeError, httpx.HTTPError):
                pass  # Odds are optional context; a failed lookup shouldn't block the list.

    def fixture_details(self, fixture_id: str) -> dict[str, Any]:
        response = self._get("/fixtures", {"id": _api_football_event_id(fixture_id)}).get("response", [])
        return response[0] if response else {}

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        """Look up a single fixture directly and enrich it with each team's recent
        form and 1X2 odds, so predictions reflect the actual teams involved instead
        of the schema's neutral defaults (1500 elo, empty form for both sides)."""
        row = self.fixture_details(fixture_id)
        if not row:
            return None
        fx = _normalize_api_football_fixture(row)
        teams = row.get("teams", {})
        home_id = (teams.get("home") or {}).get("id")
        away_id = (teams.get("away") or {}).get("id")
        fx.home_form = self._recent_form(home_id, before=fx.date, n=20)
        fx.away_form = self._recent_form(away_id, before=fx.date, n=20)
        if self.fetch_discipline_stats:
            fx.home_discipline = self._recent_discipline(home_id, exclude_fixture_id=fx.fixture_id)
            fx.away_discipline = self._recent_discipline(away_id, exclude_fixture_id=fx.fixture_id)
        try:
            fx.odds = _extract_1x2_odds(self.odds(fixture_id), fx.home_team, fx.away_team, self.preferred_bookmaker)
        except (RuntimeError, httpx.HTTPError):
            pass  # Odds are optional context; a failed lookup shouldn't block a prediction.
        return fx

    def _recent_form(self, team_id: int | None, before: datetime | None = None,
                     exclude_fixture_id: str | None = None, n: int = 5) -> TeamForm:
        if not team_id:
            return TeamForm()
        # Ask for a larger recent window when predicting historical fixtures,
        # then filter locally to matches strictly before the target date. This
        # prevents future-result leakage while still keeping the request cheap
        # enough for the provider cache to reuse the team history payload.
        request_n = max(n, 20) if before is not None else n
        try:
            payload = self._get("/fixtures", {"team": team_id, "last": request_n})
        except (RuntimeError, httpx.HTTPError):
            return TeamForm()
        wins = draws = losses = 0
        goals_for = goals_against = 0.0
        counted = 0
        for row in payload.get("response", []):
            fx_row = row.get("fixture", {})
            if exclude_fixture_id and str(fx_row.get("id")) == _api_football_event_id(exclude_fixture_id):
                continue
            if before is not None:
                row_date = fx_row.get("date")
                if row_date:
                    try:
                        row_dt = datetime.fromisoformat(str(row_date).replace("Z", "+00:00"))
                        if row_dt.tzinfo is None:
                            row_dt = row_dt.replace(tzinfo=timezone.utc)
                        if row_dt >= before:
                            continue
                    except ValueError:
                        continue
            goals = row.get("goals", {})
            teams = row.get("teams", {})
            is_home = (teams.get("home") or {}).get("id") == team_id
            gf = goals.get("home") if is_home else goals.get("away")
            ga = goals.get("away") if is_home else goals.get("home")
            if gf is None or ga is None:
                continue
            counted += 1
            goals_for += gf
            goals_against += ga
            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1
        return TeamForm(matches=counted, wins=wins, draws=draws, losses=losses,
                         goals_for=goals_for, goals_against=goals_against)

    def _recent_discipline(self, team_id: int | None, exclude_fixture_id: str | None = None,
                            n: int = 5) -> TeamDiscipline:
        """Real corners/cards averages from API-Football's per-fixture
        statistics, replacing corners_cards.py's neutral league-average
        fallback with actual recent data for this team. Costs one
        /fixtures/statistics call per historical match (not cached across
        different teams), so this is only called when fetch_discipline_stats
        is explicitly enabled."""
        if not team_id:
            return TeamDiscipline()
        try:
            payload = self._get("/fixtures", {"team": team_id, "last": n, "status": "FT"})
        except (RuntimeError, httpx.HTTPError):
            return TeamDiscipline()
        corners_for = corners_against = cards_for = cards_against = 0.0
        counted = 0
        for row in payload.get("response", []):
            fixture_id = (row.get("fixture") or {}).get("id")
            if fixture_id is None:
                continue
            if exclude_fixture_id and str(fixture_id) == str(exclude_fixture_id):
                continue
            try:
                stats_payload = self._get("/fixtures/statistics", {"fixture": fixture_id})
            except (RuntimeError, httpx.HTTPError):
                continue
            entries = stats_payload.get("response", [])
            mine = next((e for e in entries if (e.get("team") or {}).get("id") == team_id), None)
            theirs = next((e for e in entries if (e.get("team") or {}).get("id") != team_id), None)
            if not mine:
                continue
            corners_for += _stat_value(mine, "Corner Kicks")
            corners_against += _stat_value(theirs, "Corner Kicks") if theirs else 0.0
            cards_for += _stat_value(mine, "Yellow Cards") + _stat_value(mine, "Red Cards")
            cards_against += (_stat_value(theirs, "Yellow Cards") + _stat_value(theirs, "Red Cards")) if theirs else 0.0
            counted += 1
        if not counted:
            return TeamDiscipline()
        return TeamDiscipline(
            corners_for_avg=corners_for / counted,
            corners_against_avg=corners_against / counted,
            cards_for_avg=cards_for / counted,
            cards_against_avg=cards_against / counted,
        )

    def events(self, fixture_id: str) -> list[dict[str, Any]]:
        return self._get("/fixtures/events", {"fixture": _api_football_event_id(fixture_id)}, cacheable=False).get("response", [])

    def lineups(self, fixture_id: str) -> list[dict[str, Any]]:
        return self._get("/fixtures/lineups", {"fixture": _api_football_event_id(fixture_id)}, cacheable=False).get("response", [])

    def odds(self, fixture_id: str) -> dict[str, Any]:
        response = self._get("/odds", {"fixture": _api_football_event_id(fixture_id)}).get("response", [])
        return response[0] if response else {}


def _stat_value(entry: dict[str, Any] | None, stat_type: str) -> float:
    """Pull a named value (e.g. 'Corner Kicks', 'Yellow Cards') out of one
    team's entry in API-Football's /fixtures/statistics response
    (entry['statistics'] = [{'type': ..., 'value': ...}, ...])."""
    if not entry:
        return 0.0
    for stat in entry.get("statistics", []):
        if stat.get("type") == stat_type:
            try:
                return float(stat.get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _api_football_event_id(fixture_id: str | int) -> str:
    """Return the provider-native numeric API-Football fixture id.

    CompositeFootballProvider prefixes API-Football ids so they cannot collide
    with numeric ids from other providers. All API-Football endpoint methods
    therefore strip that prefix before sending the id upstream.
    """
    raw = str(fixture_id)
    return raw.removeprefix("api-football-")


def _normalize_api_football_fixture(row: dict[str, Any]) -> Fixture:
    fx = row.get("fixture", {})
    teams = row.get("teams", {})
    league = row.get("league", {})
    goals = row.get("goals", {})
    score = row.get("score", {})
    dt_raw = fx.get("date")
    dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00")) if dt_raw else datetime.now(timezone.utc)
    status_obj = fx.get("status") or {}
    status = str(status_obj.get("short", "NS"))

    return Fixture(
        fixture_id=f"api-football-{fx.get("id")}",
        date=dt,
        league=str(league.get("name", "Unknown")),
        season=str(league.get("season", "Unknown")),
        home_team=str((teams.get("home") or {}).get("name", "Home")),
        away_team=str((teams.get("away") or {}).get("name", "Away")),
        status=status,
        home_score=goals.get("home"),
        away_score=goals.get("away"),
        stats={
            "source": "api-football",
            "venue": ((fx.get("venue") or {}).get("name")),
            "timezone": fx.get("timezone"),
            "periods": score.get("periods", {}),
        },
    )


_ODDS_LABEL_ALIASES = {
    "home": "home", "1": "home",
    "draw": "draw", "x": "draw", "tie": "draw",
    "away": "away", "2": "away",
}


def _extract_1x2_odds(odds_row: dict[str, Any], home_team: str | None = None,
                       away_team: str | None = None, preferred_bookmaker: str = "") -> dict[str, float]:
    """Pull a Home/Draw/Away price out of API-Football's odds response shape
    (response[].bookmakers[].bets[] where bet name == 'Match Winner').

    Previously this only recognized the literal labels "home"/"draw"/"away"
    and always used whichever bookmaker came first in the array. Some
    bookmakers label the same market "1"/"X"/"2", or use the actual team name
    instead of "Home"/"Away" — those fell through silently before. This also
    prefers a configured bookmaker (more consistent pricing across fixtures)
    when one is set and present, falling back to the first usable bookmaker.
    """
    bookmakers = (odds_row or {}).get("bookmakers", [])
    if preferred_bookmaker:
        target = preferred_bookmaker.strip().lower()
        preferred = [b for b in bookmakers if str(b.get("name", "")).strip().lower() == target]
        others = [b for b in bookmakers if b not in preferred]
        bookmakers = preferred + others
    home_l = (home_team or "").strip().lower()
    away_l = (away_team or "").strip().lower()
    for bookmaker in bookmakers:
        for bet in bookmaker.get("bets", []):
            if bet.get("name") != "Match Winner":
                continue
            row_out: dict[str, float] = {}
            for value in bet.get("values", []):
                label = str(value.get("value", "")).strip().lower()
                try:
                    price = float(value.get("odd"))
                except (TypeError, ValueError):
                    continue
                key = _ODDS_LABEL_ALIASES.get(label)
                if key is None and home_l and label == home_l:
                    key = "home"
                elif key is None and away_l and label == away_l:
                    key = "away"
                if key:
                    row_out[key] = price
            if row_out:
                return row_out  # First bookmaker (preferred, if configured) with a usable market is enough.
    return {}


def _normalize_fixture(row: dict) -> Fixture:
    teams = row.get("teams", {})
    goals = row.get("goals", row.get("score", {}))
    league = row.get("league", {})
    fixture = row.get("fixture", row)
    date_raw = fixture.get("date") or row.get("date")
    dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00")) if date_raw else datetime.now(timezone.utc)
    return Fixture(
        fixture_id=f"generic-{fixture.get('id') or row.get('id')}",
        date=dt,
        league=str(league.get("name", "Unknown")),
        season=str(league.get("season", "Unknown")),
        home_team=str(teams.get("home", {}).get("name", row.get("home_team", "Home"))),
        away_team=str(teams.get("away", {}).get("name", row.get("away_team", "Away"))),
        status=str(fixture.get("status", {}).get("short", row.get("status", "scheduled"))),
        home_score=goals.get("home"), away_score=goals.get("away"),
        odds=row.get("odds", {}), stats=row.get("statistics", {}) or {},
    )


def build_provider_from_settings(settings: Any) -> FootballProvider:
    """Build a provider from the application's Settings object.

    Keeping this mapping in one place prevents the FastAPI backend and
    Streamlit frontend from silently drifting apart when new provider settings
    are added.
    """
    return build_provider(
        settings.football_provider,
        settings.football_api_base_url,
        settings.api_football_key or settings.football_api_key,
        cache_ttl_seconds=settings.provider_cache_ttl_seconds,
        sofascore_browser_path=settings.sofascore_browser_path or None,
        livescorefootball_league=settings.livescorefootball_league or None,
        odds_preferred_bookmaker=settings.odds_preferred_bookmaker,
        api_football_enrich_lists=settings.api_football_enrich_lists,
        api_football_fetch_discipline=settings.api_football_fetch_discipline,
        football_data_api_key=settings.football_data_api_key,
        football_data_base_url=settings.football_data_base_url,
        football_data_competition=settings.football_data_competition,
        football_data_enrich_form=settings.football_data_enrich_form,
        thesportsdb_api_key=settings.thesportsdb_api_key,
        thesportsdb_base_url=settings.thesportsdb_base_url,
        thesportsdb_league_id=settings.thesportsdb_league_id,
        provider_chain=settings.football_provider_chain,
        provider_mode=settings.football_provider_mode,
    )


def build_provider(name: str, base_url: str, api_key: str, cache_ttl_seconds: float = 60.0,
                    sofascore_browser_path: str | None = None,
                    livescorefootball_league: str | None = None,
                    odds_preferred_bookmaker: str = "",
                    api_football_enrich_lists: bool = False,
                    api_football_fetch_discipline: bool = False,
                    football_data_api_key: str = "",
                    football_data_base_url: str = "",
                    football_data_competition: str = "PL",
                    football_data_enrich_form: bool = False,
                    thesportsdb_api_key: str = "123",
                    thesportsdb_base_url: str = "",
                    thesportsdb_league_id: str = "4328",
                    provider_chain: str = "",
                    provider_mode: str = "fallback") -> FootballProvider:
    """Build either one provider or a configurable provider chain.

    `name=auto` (or a comma-separated `provider_chain`) enables the router.
    Providers that require credentials are skipped when their credential is
    absent, so a fresh install can immediately use TheSportsDB's free V1 API.
    """
    normalized = (name or "auto").lower().strip()
    chain_spec = provider_chain.strip() if provider_chain else (name if "," in name else "")
    if normalized in {"auto", "multi", "composite", "fallback"}:
        chain_spec = provider_chain.strip() or "thesportsdb,api-football,football-data,livescorefootball,sofascore"
    if chain_spec:
        from .multi_provider import CompositeFootballProvider
        providers: list[tuple[str, FootballProvider]] = []
        for item in [x.strip() for x in chain_spec.split(",") if x.strip()]:
            key = item.lower().replace("_", "-")
            try:
                provider = build_provider(
                    key, base_url, api_key, cache_ttl_seconds,
                    sofascore_browser_path=sofascore_browser_path,
                    livescorefootball_league=livescorefootball_league,
                    odds_preferred_bookmaker=odds_preferred_bookmaker,
                    api_football_enrich_lists=api_football_enrich_lists,
                    api_football_fetch_discipline=api_football_fetch_discipline,
                    football_data_api_key=football_data_api_key,
                    football_data_base_url=football_data_base_url,
                    football_data_competition=football_data_competition,
                    football_data_enrich_form=football_data_enrich_form,
                    thesportsdb_api_key=thesportsdb_api_key,
                    thesportsdb_base_url=thesportsdb_base_url,
                    thesportsdb_league_id=thesportsdb_league_id,
                )
            except ValueError as exc:
                # Missing optional credentials should not make the entire chain
                # unusable. Explicitly selected single providers still raise.
                if key in {"api-football", "api-sports", "apisports"} and not api_key:
                    continue
                if key in {"football-data", "football-data-org"} and not football_data_api_key:
                    continue
                logger.warning("Skipping unavailable provider %s: %s", item, exc)
                continue
            except Exception as exc:
                # Auto mode is intentionally resilient to optional dependencies
                # such as Playwright/Chromium for Sofascore. A broken optional
                # adapter should not prevent the rest of the free chain from working.
                if not chain_spec:
                    raise
                logger.warning("Skipping provider %s during chain setup: %s", item, exc)
                continue
            providers.append((key, provider))
        if not providers:
            raise ValueError("No usable football providers are configured")
        return CompositeFootballProvider(providers, mode=provider_mode)

    if normalized in {"api-football", "api_football", "apisports", "api-sports"}:
        return ApiFootballProvider(api_key=api_key, base_url=base_url or "https://v3.football.api-sports.io",
                                    cache_ttl_seconds=cache_ttl_seconds,
                                    preferred_bookmaker=odds_preferred_bookmaker,
                                    enrich_list_fixtures=api_football_enrich_lists,
                                    fetch_discipline_stats=api_football_fetch_discipline)
    if normalized in {"football-data", "football-data-org", "football-data.org"}:
        return FootballDataOrgProvider(api_key=football_data_api_key or api_key,
                                       base_url=football_data_base_url or "https://api.football-data.org/v4",
                                       default_competition=football_data_competition or "PL",
                                       cache_ttl_seconds=cache_ttl_seconds,
                                       enrich_form=football_data_enrich_form)
    if normalized in {"thesportsdb", "the-sports-db", "thesportsdb-v1"}:
        return TheSportsDBProvider(api_key=thesportsdb_api_key or "123",
                                   league_id=thesportsdb_league_id or "4328",
                                   base_url=thesportsdb_base_url or "https://www.thesportsdb.com/api/v1/json",
                                   cache_ttl_seconds=max(cache_ttl_seconds, 60.0))
    if normalized == "sofascore":
        return SofascoreProvider(browser_path=sofascore_browser_path, cache_ttl_seconds=cache_ttl_seconds)
    if normalized in {"livescorefootball", "livescore-football", "worldcup26"}:
        return LivescoreFootballProvider(base_url=base_url or "https://worldcup26.ir",
                                         default_league=livescorefootball_league,
                                         cache_ttl_seconds=cache_ttl_seconds)
    return GenericFootballRESTProvider(base_url, api_key)


class LivescoreFootballProvider(FootballProvider):
    """Adapter for rezarahiminia/livescoreFootball (worldcup26.ir) — a free,
    open-source, no-API-key club-football service covering England and Spain
    (Premier League, EFL, FA Cup, LaLiga, LaLiga 2, Copa del Rey, women's
    competitions) as of the version this was built against.

    Verified directly against the project's GitHub README before writing
    this (github.com/rezarahiminia/livescoreFootball) rather than trusting a
    third-party description: the architecture claim (a separate listener
    writes to MongoDB; this API only reads, so customer requests never touch
    an upstream provider) and the endpoint list below are both taken from the
    primary source. Two things are NOT verified, because this environment
    has no network path to worldcup26.ir to sanity-check a live response:
      - The exact JSON field names inside each fixture/summary/standings
        object. The README only says responses use a "stable
        provider-compatible shape" without naming the provider. This adapter
        therefore checks several plausible key names per field rather than
        assuming one — if fields still come back empty, log a real response
        and adjust `_normalize_livescorefootball_fixture` to match.
      - Actual uptime/rate-limit behavior in production. Per the project's
        own docs, API-key issuance and per-customer quotas are "not
        implemented yet" — meaning today's no-key access is a current state,
        not a documented guarantee, and could change without notice.
      - No odds are provided by this source at all (not a gap in this
        adapter — the upstream project doesn't have them), so `/value-bets`
        will always be empty for fixtures from this provider.

    League selection: unlike ApiFootballProvider's numeric league ids, this
    service uses its own string slugs (e.g. "eng.1" for the Premier League,
    "esp.1" for LaLiga — see GET /get/soccer/leagues for the full list).
    There is no single "all leagues" fixtures endpoint, so a `league` slug is
    required for every call; pass one explicitly or set a default via
    `default_league` / `LIVESCOREFOOTBALL_LEAGUE` in .env.
    """
    def __init__(self, base_url: str = "https://worldcup26.ir", default_league: str | None = None,
                 timeout: float = 20.0, cache_ttl_seconds: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.default_league = default_league
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout,
                                    headers={"Accept": "application/json"})
        self._cache = _TTLCache(cache_ttl_seconds) if cache_ttl_seconds > 0 else None

    def _get(self, path: str, params: dict[str, Any] | None = None, cacheable: bool = True,
              _retries: int = 3) -> dict[str, Any]:
        params = params or {}
        cache_key = f"{path}?{sorted(params.items())}"
        if self._cache is not None and cacheable:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        backoff = 1.0
        for attempt in range(_retries + 1):
            response = self.client.get(path, params=params)
            if getattr(response, "status_code", None) == 429:
                # The service documents a public rate limit (120 req/min per
                # the public release notes document 1000 requests/IP/60s;
                # back off and retry rather than surfacing a 429 immediately.
                # straight to the caller, honoring Retry-After if it's sent.
                if attempt == _retries:
                    raise RuntimeError(
                        "livescoreFootball rate limit hit (HTTP 429) after retries — "
                        "the public tier is capped at 1000 requests per IP every 60 seconds."
                    )
                wait = float(response.headers.get("Retry-After", backoff))
                time.sleep(wait)
                backoff *= 2
                continue
            response.raise_for_status()
            payload = response.json()
            if self._cache is not None and cacheable:
                self._cache.set(cache_key, payload)
            return payload
        return {}  # unreachable; keeps type-checkers happy

    def _require_league(self, league: str | None) -> str:
        league = league or self.default_league
        if not league:
            raise ValueError(
                "LivescoreFootballProvider requires a league slug (e.g. 'eng.1', 'esp.1') — "
                "there is no all-leagues fixtures endpoint on this service. Pass league= "
                "explicitly or set LIVESCOREFOOTBALL_LEAGUE in .env. See GET /get/soccer/leagues "
                "for the full slug list."
            )
        return league

    def _get_all_pages(self, path: str, params: dict[str, Any], row_keys: tuple[str, ...],
                       cacheable: bool = True, max_pages: int = 20) -> list[dict[str, Any]]:
        """The service's README documents a paginated list response, but not
        the exact pagination field names, so this checks several plausible
        conventions (page/currentPage + totalPages/pages/hasMore/has_next) and
        stops as soon as none of them indicate another page — including on
        page 1, so a genuinely unpaginated response still works unchanged."""
        all_rows: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            page_params = dict(params)
            if page > 1:
                page_params["page"] = page
            payload = self._get(path, page_params, cacheable=cacheable)
            rows = _extract_rows(payload, row_keys)
            all_rows.extend(rows)
            if not isinstance(payload, dict) or not rows:
                break
            total_pages = payload.get("totalPages") or payload.get("pages")
            has_more = payload.get("hasMore")
            if has_more is None:
                has_more = payload.get("has_next")
            current_page = payload.get("currentPage") or payload.get("page") or page
            if total_pages is not None:
                if current_page >= total_pages:
                    break
            elif has_more is not None:
                if not has_more:
                    break
            else:
                break  # No pagination metadata recognized: assume a single page.
            page += 1
        return all_rows

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        league_slug = self._require_league(league)
        if live:
            payload = self._get(f"/get/soccer/{league_slug}/scoreboard",
                                 {"dates": datetime.now(timezone.utc).strftime("%Y%m%d")}, cacheable=False)
            rows = _extract_rows(payload, ("events", "games", "matches", "data"))
        else:
            params = {"status": "all", "from": start.strftime("%Y%m%d"), "to": end.strftime("%Y%m%d")}
            rows = self._get_all_pages(f"/get/soccer/{league_slug}/fixtures", params,
                                        ("fixtures", "events", "games", "matches", "data"))
        return [_normalize_livescorefootball_fixture(row, league_slug) for row in rows]

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        parsed = _parse_livescorefootball_id(fixture_id)
        if not parsed:
            return None
        league_slug, event_id = parsed
        try:
            payload = self._get(f"/get/soccer/{league_slug}/summary", {"event": event_id})
        except httpx.HTTPError:
            return None
        row = payload.get("match") or payload.get("event") or payload.get("data") or payload
        if not row:
            return None
        return _normalize_livescorefootball_fixture(row, league_slug)

    def events(self, fixture_id: str) -> list[dict[str, Any]]:
        parsed = _parse_livescorefootball_id(fixture_id)
        if not parsed:
            return []
        league_slug, event_id = parsed
        try:
            payload = self._get(f"/get/soccer/{league_slug}/events/{event_id}/plays", cacheable=False)
        except httpx.HTTPError:
            return []
        return _extract_rows(payload, ("plays", "events", "data"))

    # lineups()/odds() intentionally not overridden: this source doesn't
    # expose rosters as a separate lookup beyond the clubs endpoint, and has
    # no odds at all — the base class's empty defaults are the honest answer.


def _extract_rows(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """This provider's exact response envelope isn't confirmed (see
    LivescoreFootballProvider's docstring), so check several plausible
    wrapper keys before giving up, rather than assuming one."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_livescorefootball_id(fixture_id: str) -> tuple[str, str] | None:
    prefix = "livescorefootball-"
    if not fixture_id.startswith(prefix):
        return None
    rest = fixture_id[len(prefix):]
    if "-" not in rest:
        return None
    league_slug, event_id = rest.split("-", 1)
    return league_slug, event_id


def _first(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _normalize_livescorefootball_fixture(row: dict[str, Any], league_slug: str) -> Fixture:
    """Normalize the stable livescoreFootball event shape.

    The service's current public documentation uses nested `home`/`away`
    objects with `display_name`/`name`, nested scores, and a nested status
    object. Keep compatibility with older flat aliases as well.
    """
    event_id = str(_first(row, "id", "eventId", "event_id", "matchId", default="")).strip()

    home = _first(row, "homeTeam", "home_team", "home", default={})
    away = _first(row, "awayTeam", "away_team", "away", default={})

    def participant_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(_first(
                value, "display_name", "displayName", "name", "shortName", "teamName", default=""
            )).strip()
        return str(value or "").strip()

    home_name = participant_name(home) or str(_first(
        row, "homeTeamName", "home_team_name", "homeName", default=""
    )).strip()
    away_name = participant_name(away) or str(_first(
        row, "awayTeamName", "away_team_name", "awayName", default=""
    )).strip()

    # Some payloads expose a human-readable event name; use it only when the
    # explicit participant fields are absent.
    if not home_name or not away_name:
        event_name = str(_first(
            row, "short_name", "shortName", "name", default=""
        )).strip()
        for separator in (" at ", " vs ", " v "):
            if separator in event_name:
                left, right = [part.strip() for part in event_name.split(separator, 1)]
                if not home_name:
                    home_name = left
                if not away_name:
                    away_name = right
                break

    date_raw = _first(row, "date", "kickoff", "startTime", "start_time", "utcDate")
    try:
        date = (
            datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
            if date_raw else datetime.now(timezone.utc)
        )
    except ValueError:
        date = datetime.now(timezone.utc)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    raw_status = _first(row, "status", "state", default="scheduled")
    if isinstance(raw_status, dict):
        status = str(_first(
            raw_status, "state", "name", "description", "short_detail", default="scheduled"
        ))
    else:
        status = str(raw_status or "scheduled")

    def score_for(participant: Any, flat_keys: tuple[str, ...]) -> Any:
        if isinstance(participant, dict):
            value = _first(
                participant, "score", "currentScore", "current_score", default=None
            )
            if isinstance(value, dict):
                value = _first(value, "current", "value", "score", default=None)
            if value not in (None, ""):
                return value
        return _first(row, *flat_keys, default=None)

    home_score = score_for(home, ("homeScore", "home_score"))
    away_score = score_for(away, ("awayScore", "away_score"))

    def to_int(value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    league_name = str(_first(
        row, "league_name", "leagueName", "competitionName", "note", default=""
    )).strip()
    if not league_name:
        league_name = {
            "eng.1": "Premier League",
            "esp.1": "LaLiga",
            "esp.2": "LaLiga 2",
            "eng.2": "EFL Championship",
        }.get(league_slug, league_slug)

    season_value = _first(row, "season", default="")
    if isinstance(season_value, dict):
        season_value = _first(season_value, "year", "name", "slug", default="")

    return Fixture(
        fixture_id=f"livescorefootball-{league_slug}-{event_id}",
        date=date,
        league=league_name,
        season=str(season_value or ""),
        home_team=home_name or "Unknown",
        away_team=away_name or "Unknown",
        status=status,
        home_score=to_int(home_score),
        away_score=to_int(away_score),
        stats={
            "source": "livescorefootball",
            "league_slug": league_slug,
            "venue": (
                (row.get("venue") or {}).get("name")
                if isinstance(row.get("venue"), dict) else row.get("venue")
            ),
        },
    )


class SofascoreProvider(FootballProvider):
    """Scores/fixtures-only adapter over the third-party `EasySoccerData` (`esd`)
    package, which scrapes Sofascore.

    Deliberately scoped down from ApiFootballProvider: Sofascore's public site
    has no bookmaker odds, so `odds()` is left at the base class's empty-dict
    default and `edge`/value-bet output will always be null for this provider.
    Use it for fixtures/results only, exactly as requested; keep an odds-capable
    provider (e.g. ApiFootballProvider) for value-bet analysis.

    IMPORTANT — this is not a lightweight REST client. `esd`'s Sofascore module
    drives a real headless Chromium browser via Playwright to get past
    Sofascore's bot protection (see its `SofascoreService.__init_playwright`).
    That means, compared to ApiFootballProvider:
      - Extra dependencies: `pip install EasySoccerData playwright`, then
        `playwright install chromium` (or point `browser_path` at an existing
        Chrome/Chromium binary). These are NOT in requirements.txt — see
        requirements-optional.txt — so the base app install stays light.
      - Heavier runtime footprint: a live browser process per instance
        (~150-300MB RAM), multi-second startup, and no request-level timeout
        control the way httpx gives you.
      - Likely unsuitable for typical free-tier PaaS web dynos without a
        custom Docker image that bundles Chromium.
      - It works by circumventing Sofascore's bot detection rather than
        calling a documented, sanctioned API — treat it as a fragile fallback
        for scores/fixtures smoke-testing, not a production data source, and
        review Sofascore's terms of service before relying on it.
      - Licensing: `EasySoccerData` is distributed under GPL-3.0 (per its own
        PyPI metadata). That's a copyleft license; if you intend to distribute
        or run this app commercially, get that combination checked against
        GPL-3.0's terms before shipping — this comment is a fact, not legal
        advice, and the rest of this project has no such restriction.
      - Packaging note: `EasySoccerData`'s own PyPI metadata only declares
        `httpx` as a dependency, but its Sofascore module unconditionally
        `import`s `playwright` — a plain `pip install EasySoccerData` will
        raise `ModuleNotFoundError` on a clean environment unless you also
        install `playwright` yourself and run `playwright install chromium`.
        requirements-optional.txt below already does the former for you.

    `get_events()` upstream only accepts a single date (or `live=True`), not a
    range, so `fixtures()` loops one browser call per calendar day in
    [start, end]. To keep that bounded, ranges wider than `max_days_per_call`
    (default 14) raise a ValueError instead of silently making a lot of calls.
    """
    def __init__(self, browser_path: str | None = None, cache_ttl_seconds: float = 60.0,
                 max_days_per_call: int = 14):
        try:
            import esd  # noqa: F401  (imported lazily so this stays an optional dependency)
        except ImportError as exc:
            raise ImportError(
                "FOOTBALL_PROVIDER=sofascore requires the optional 'EasySoccerData' and "
                "'playwright' packages (pip install -r requirements-optional.txt), plus a "
                "Chromium browser (playwright install chromium)."
            ) from exc
        self._esd = esd
        self.max_days_per_call = max_days_per_call
        self._client = esd.SofascoreClient(browser_path=browser_path)
        self._cache = _TTLCache(cache_ttl_seconds) if cache_ttl_seconds > 0 else None

    def close(self) -> None:
        """Release the underlying browser/Playwright resources. Call this on
        app shutdown — the browser process otherwise stays alive for the life
        of the Python process."""
        self._client.close()

    def _cached(self, key: str, fetch):
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        value = fetch()
        if self._cache is not None:
            self._cache.set(key, value)
        return value

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        if live:
            events = self._cached("sofascore:live", lambda: self._client.get_events(live=True))
            return [_normalize_sofascore_event(e) for e in events]

        if league is not None and season is not None:
            # Sofascore's own numeric tournament/season ids (find via .search()),
            # not API-Football's ids — documented in the test guide.
            events = self._cached(
                f"sofascore:tournament:{league}:{season}",
                lambda: self._client.get_tournament_events(tournament_id=league, season_id=season, upcoming=True),
            )
            return [_normalize_sofascore_event(e) for e in events
                    if start <= _event_datetime(e) <= end]

        span_days = (end.date() - start.date()).days
        if span_days > self.max_days_per_call:
            raise ValueError(
                f"Sofascore date range spans {span_days} days; each day is a separate "
                f"browser call, so this provider caps ranges at {self.max_days_per_call} days. "
                "Narrow the range or pass league+season to use a single tournament lookup instead."
            )
        seen: dict[int, Any] = {}
        for offset in range(span_days + 1):
            day = (start.date() + timedelta(days=offset)).isoformat()
            events = self._cached(f"sofascore:date:{day}", lambda d=day: self._client.get_events(date=d))
            for event in events:
                seen[event.id] = event
        return [_normalize_sofascore_event(e) for e in seen.values()
                if start <= _event_datetime(e) <= end]

    def fixture_by_id(self, fixture_id: str) -> Fixture | None:
        raw_id = _strip_sofascore_prefix(fixture_id)
        if raw_id is None:
            return None
        try:
            event = self._client.get_event(raw_id)
        except Exception:  # esd raises plain Exception subtypes for a 404/parse failure
            return None
        if event is None:
            return None
        fx = _normalize_sofascore_event(event)
        fx.home_form = self._recent_form(event.home_team.id, exclude_event_id=event.id)
        fx.away_form = self._recent_form(event.away_team.id, exclude_event_id=event.id)
        return fx

    def _recent_form(self, team_id: int | None, exclude_event_id: int | None = None, n: int = 5) -> TeamForm:
        if not team_id:
            return TeamForm()
        try:
            events = self._client.get_team_events(team_id, upcoming=False)
        except Exception:
            return TeamForm()
        wins = draws = losses = 0
        goals_for = goals_against = 0.0
        counted = 0
        for event in events:
            if exclude_event_id is not None and event.id == exclude_event_id:
                continue
            status_type = getattr(event.status.type, "value", str(event.status.type))
            if status_type != "finished":
                continue
            is_home = event.home_team.id == team_id
            gf = event.home_score.current if is_home else event.away_score.current
            ga = event.away_score.current if is_home else event.home_score.current
            if gf is None or ga is None:
                continue
            counted += 1
            goals_for += gf
            goals_against += ga
            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1
            if counted >= n:
                break
        return TeamForm(matches=counted, wins=wins, draws=draws, losses=losses,
                         goals_for=goals_for, goals_against=goals_against)

    def events(self, fixture_id: str) -> list[dict[str, Any]]:
        import dataclasses
        raw_id = _strip_sofascore_prefix(fixture_id)
        if raw_id is None:
            return []
        try:
            incidents = self._client.get_match_incidents(raw_id)
        except Exception:
            return []
        return [dataclasses.asdict(i) if dataclasses.is_dataclass(i) else i for i in incidents]

    def lineups(self, fixture_id: str) -> dict[str, Any]:
        import dataclasses
        raw_id = _strip_sofascore_prefix(fixture_id)
        if raw_id is None:
            return {}
        try:
            lineups = self._client.get_match_lineups(raw_id)
        except Exception:
            return {}
        return dataclasses.asdict(lineups) if dataclasses.is_dataclass(lineups) else lineups

    # odds() intentionally not overridden: Sofascore's free site has no
    # bookmaker odds, so the base class's `{}` default is the honest answer.


def _event_datetime(event: Any) -> datetime:
    return datetime.fromtimestamp(event.start_timestamp, tz=timezone.utc)


def _strip_sofascore_prefix(fixture_id: str) -> int | None:
    prefix = "sofascore-"
    raw = fixture_id[len(prefix):] if fixture_id.startswith(prefix) else fixture_id
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _normalize_sofascore_event(event: Any) -> Fixture:
    status_type = getattr(event.status.type, "value", str(event.status.type))
    return Fixture(
        fixture_id=f"sofascore-{event.id}",
        date=_event_datetime(event),
        league=event.tournament.name,
        season="",  # Not exposed on Event itself; would need a separate
                    # get_tournament_seasons() call to resolve.
        home_team=event.home_team.name,
        away_team=event.away_team.name,
        status=status_type,
        home_score=event.home_score.current if status_type != "notstarted" else None,
        away_score=event.away_score.current if status_type != "notstarted" else None,
        stats={
            "source": "sofascore",
            "status_description": event.status.description,
            "tournament_id": event.tournament.id,
            "slug": event.slug,
        },
    )


class GenericFootballRESTProvider(FootballProvider):
    """Generic normalized adapter for another REST provider."""
    def __init__(self, base_url: str, api_key: str, fixtures_path: str = "/fixtures"):
        if not base_url or not api_key:
            raise ValueError("Generic REST provider requires base_url and api_key")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.fixtures_path = fixtures_path

    def fixtures(self, start: datetime, end: datetime, live: bool = False,
                 league: int | str | None = None, season: int | str | None = None) -> list[Fixture]:
        params = {"from": start.date().isoformat(), "to": end.date().isoformat()}
        if live:
            params["live"] = "true"
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        headers = {"Authorization": f"Bearer {self.api_key}"}
        r = httpx.get(f"{self.base_url}{self.fixtures_path}", params=params, headers=headers, timeout=30)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("response", payload.get("data", payload if isinstance(payload, list) else []))
        return [_normalize_fixture(row) for row in rows]
