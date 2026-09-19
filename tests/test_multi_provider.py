import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from app.data_providers import AllSportsAPIProvider, ISportsAPIProvider, FootballDataOrgProvider, TheSportsDBProvider, OpenFootballProvider, BSDProvider, build_provider, build_provider_from_settings
from app.multi_provider import CompositeFootballProvider
from app.schemas import Fixture, TeamForm


class Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TestISportsAPIProvider(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_normalizes_livescore_response(self, mock_get):
        kickoff = int(datetime(2026, 9, 18, 20, tzinfo=timezone.utc).timestamp())
        mock_get.return_value = Resp({"code": 0, "message": "success", "data": [{
            "matchId": "123456",
            "leagueId": "39",
            "leagueName": "England Premier League",
            "matchTime": kickoff,
            "status": 1,
            "homeId": "1",
            "homeName": "Arsenal",
            "awayId": "2",
            "awayName": "Chelsea",
            "homeScore": 1,
            "awayScore": 0,
            "homeCorner": 3,
            "awayCorner": 1,
            "homeYellow": 1,
            "awayYellow": 0,
            "season": "2026",
        }]})
        p = ISportsAPIProvider("key", cache_ttl_seconds=0)
        rows = p.fixtures(
            datetime(2026, 9, 18, 19, tzinfo=timezone.utc),
            datetime(2026, 9, 18, 21, tzinfo=timezone.utc),
            live=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fixture_id, "isports-123456")
        self.assertEqual(rows[0].status, "in_play")
        self.assertEqual(rows[0].stats["home_corner"], 3)
        self.assertEqual(mock_get.call_args.kwargs["params"]["api_key"], "key")

class TestAllSportsAPIProvider(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_normalizes_fixture_response(self, mock_get):
        mock_get.return_value = Resp({"success": 1, "result": [{
            "event_key": "11205",
            "event_date": "2026-09-19",
            "event_time": "18:30",
            "event_home_team": "Newcastle Jets",
            "home_team_key": "1056",
            "event_away_team": "Brisbane Roar",
            "away_team_key": "399",
            "event_final_result": "",
            "event_status": "NS",
            "event_live": "0",
            "country_name": "Australia",
            "league_name": "A-League",
            "league_key": "49",
            "event_stadium": "McDonald Jones Stadium",
        }]})
        p = AllSportsAPIProvider("key", cache_ttl_seconds=0)
        rows = p.fixtures(
            datetime(2026, 9, 19, tzinfo=timezone.utc),
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fixture_id, "allsports-11205")
        self.assertEqual(rows[0].home_team, "Newcastle Jets")
        self.assertEqual(rows[0].stats["league_id"], "49")
        self.assertEqual(mock_get.call_args.kwargs["params"]["met"], "Fixtures")
        self.assertEqual(mock_get.call_args.kwargs["params"]["APIkey"], "key")

    @patch("app.data_providers.httpx.Client.get")
    def test_livescore_uses_documented_endpoint(self, mock_get):
        mock_get.return_value = Resp({"success": 1, "result": [{
            "event_key": "11205",
            "event_date": "2026-09-19",
            "event_time": "18:30",
            "event_home_team": "Newcastle Jets",
            "event_away_team": "Brisbane Roar",
            "event_live": "1",
            "event_status": "74",
            "country_name": "Australia",
            "league_name": "A-League",
            "league_key": "49",
        }]})
        p = AllSportsAPIProvider("key", cache_ttl_seconds=0)
        rows = p.fixtures(
            datetime(2026, 9, 19, 18, tzinfo=timezone.utc),
            datetime(2026, 9, 19, 20, tzinfo=timezone.utc),
            live=True,
        )
        self.assertEqual(rows[0].status, "in_play")
        self.assertEqual(mock_get.call_args.kwargs["params"]["met"], "Livescore")


class TestBSDProvider(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_normalizes_fixture(self, mock_get):
        mock_get.return_value = Resp({
            "id": 223510,
            "event_date": "2026-09-19T15:00:00+00:00",
            "status": "notstarted",
            "league": {"id": 10, "name": "Premier League"},
            "season": {"id": 2026, "name": "Premier League 2026/27"},
            "home_team": {"id": 1, "name": "Arsenal"},
            "away_team": {"id": 2, "name": "Chelsea"},
            "home_score": None,
            "away_score": None,
            "has_xg": True,
        })
        p = BSDProvider("key", cache_ttl_seconds=0)
        fx = p._normalise(mock_get.return_value.json())
        self.assertEqual(fx.fixture_id, "bsd-223510")
        self.assertEqual(fx.home_team, "Arsenal")
        self.assertEqual(fx.status, "scheduled")
        self.assertEqual(fx.stats["league_id"], 10)
        self.assertEqual(p.client.headers["Authorization"], "Token key")

    def test_normalizes_documented_consensus_odds(self):
        out = BSDProvider._normalise_odds({
            "event_id": 223510,
            "odds": {
                "match_winner": {"home": 2.10, "draw": 3.20, "away": 3.60},
                "over_under": {"over_25": 2.05, "under_25": 1.78},
                "btts": {"yes": 2.00, "no": 1.80},
            },
        })
        self.assertEqual(out["home"], 2.10)
        self.assertEqual(out["draw"], 3.20)
        self.assertEqual(out["away"], 3.60)
        self.assertEqual(out["over_2.5"], 2.05)
        self.assertEqual(out["under_2.5"], 1.78)
        self.assertEqual(out["btts_yes"], 2.00)
        self.assertEqual(out["btts_no"], 1.80)

    @patch("app.data_providers.httpx.Client.get")
    def test_fixture_by_id_enriches_form_and_odds(self, mock_get):
        detail = {
            "id": 223510,
            "kickoff": "2026-09-19T15:00:00+00:00",
            "status": "upcoming",
            "league": {"id": 10, "name": "Premier League"},
            "season": {"id": 2026, "name": "Premier League 2026/27"},
            "home_team": {"id": 1, "name": "Arsenal"},
            "away_team": {"id": 2, "name": "Chelsea"},
        }
        history_home = {
            "results": [
                {"id": 1, "kickoff": "2026-09-10T15:00:00+00:00", "status": "finished",
                 "home_team": {"id": 1, "name": "Arsenal"}, "away_team": {"id": 3, "name": "Everton"},
                 "home_score": 2, "away_score": 0}
            ]
        }
        history_away = {
            "results": [
                {"id": 2, "kickoff": "2026-09-10T15:00:00+00:00", "status": "finished",
                 "home_team": {"id": 4, "name": "West Ham"}, "away_team": {"id": 2, "name": "Chelsea"},
                 "home_score": 0, "away_score": 1}
            ]
        }
        odds = {"event_id": 223510, "odds": {"home_win": 1.80, "draw": 3.60, "away_win": 4.50}}
        def fake_get(url_or_path, *args, **kwargs):
            path_text = str(url_or_path)
            if path_text.endswith("/odds/"):
                return Resp(odds)
            if path_text.endswith("/events/"):
                team_id = kwargs.get("params", {}).get("team_id")
                return Resp(history_home if str(team_id) == "1" else history_away)
            return Resp(detail)
        mock_get.side_effect = fake_get
        p = BSDProvider("key", cache_ttl_seconds=0)
        fx = p.fixture_by_id("bsd-223510")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.home_form.wins, 1)
        self.assertEqual(fx.away_form.wins, 1)
        self.assertEqual(fx.odds, {"home": 1.80, "draw": 3.60, "away": 4.50})

class TestTheSportsDBProvider(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_normalizes_event_and_attaches_api_football_id(self, mock_get):
        mock_get.return_value = Resp({"events": [{
            "idEvent": "2494047",
            "idAPIfootball": "1557408",
            "strTimestamp": "2026-09-18T19:00:00",
            "strLeague": "English Premier League",
            "strSeason": "2026-2027",
            "strHomeTeam": "Brentford",
            "strAwayTeam": "Chelsea",
            "strStatus": "NS",
            "intHomeScore": None,
            "intAwayScore": None,
        }]})
        p = TheSportsDBProvider(cache_ttl_seconds=0)
        rows = p.fixtures(datetime(2026, 9, 18, 18, tzinfo=timezone.utc),
                          datetime(2026, 9, 18, 20, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fixture_id, "thesportsdb-2494047")
        self.assertEqual(rows[0].stats["api_football_id"], "1557408")
        self.assertEqual(rows[0].status, "scheduled")

    @patch("app.data_providers.httpx.Client.get")
    def test_thesportsdb_accepts_full_finished_status(self, mock_get):
        mock_get.return_value = Resp({"events": [{
            "idEvent": "2494000", "strTimestamp": "2026-09-14T19:00:00",
            "strLeague": "English Premier League", "strSeason": "2026-2027",
            "strHomeTeam": "Arsenal", "strAwayTeam": "Chelsea",
            "strStatus": "Match Finished", "intHomeScore": "2", "intAwayScore": "1",
        }]})
        p = TheSportsDBProvider(cache_ttl_seconds=0)
        fx = p._normalize_event(mock_get.return_value.json()["events"][0])
        self.assertEqual(fx.status, "finished")

    @patch("app.data_providers.httpx.Client.get")
    def test_thesportsdb_fixture_by_id_keeps_recent_form(self, mock_get):
        event = {
            "idEvent": "2494000", "strTimestamp": "2026-09-18T19:00:00",
            "strLeague": "English Premier League", "strSeason": "2026-2027",
            "strHomeTeam": "Arsenal", "strAwayTeam": "Chelsea", "strStatus": "NS",
            "intHomeScore": None, "intAwayScore": None,
        }
        past = [
            {"idEvent": "1", "strTimestamp": "2026-09-10T19:00:00", "strHomeTeam": "Arsenal", "strAwayTeam": "Everton", "strStatus": "FT", "intHomeScore": "2", "intAwayScore": "0"},
        ]
        def fake_get(url_or_path, *args, **kwargs):
            if "lookupevent.php" in str(url_or_path):
                return Resp({"events": [event]})
            if "eventsseason.php" in str(url_or_path):
                return Resp({"events": [event, *past]})
            return Resp({"events": []})
        mock_get.side_effect = fake_get
        p = TheSportsDBProvider(cache_ttl_seconds=0)
        fx = p.fixture_by_id("thesportsdb-2494000")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.home_form.matches, 1)
        self.assertEqual(fx.home_form.wins, 1)


class TestFootballDataOrgProvider(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_normalizes_match(self, mock_get):
        mock_get.return_value = Resp({"matches": [{
            "id": 9001,
            "utcDate": "2026-09-19T14:00:00Z",
            "status": "SCHEDULED",
            "competition": {"code": "PL", "name": "Premier League"},
            "season": {"startDate": "2026-08-14", "endDate": "2027-05-31"},
            "homeTeam": {"name": "Arsenal"},
            "awayTeam": {"name": "Chelsea"},
            "score": {"fullTime": {"home": None, "away": None}},
        }]})
        p = FootballDataOrgProvider("key", cache_ttl_seconds=0)
        rows = p.fixtures(datetime(2026, 9, 19, tzinfo=timezone.utc),
                          datetime(2026, 9, 20, tzinfo=timezone.utc), league="PL")
        self.assertEqual(rows[0].fixture_id, "football-data-9001")
        self.assertEqual(rows[0].league, "Premier League")
        self.assertEqual(rows[0].season, "2026")


class TestOpenFootballProvider(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_normalizes_fixture_and_builds_recent_form(self, mock_get):
        mock_get.return_value = Resp({
            "name": "Premier League 2026/27",
            "matches": [
                {"round": "Matchday 1", "date": "2026-09-10", "time": "15:00",
                 "team1": "Arsenal FC", "team2": "Everton FC",
                 "score": {"ht": [1, 0], "ft": [2, 0]}},
                {"round": "Matchday 2", "date": "2026-09-17", "time": "15:00",
                 "team1": "Arsenal FC", "team2": "Chelsea FC",
                 "score": {"ft": [1, 1]}},
                {"round": "Matchday 3", "date": "2026-09-19", "time": "15:00",
                 "team1": "Arsenal FC", "team2": "Liverpool FC"}
            ]
        })
        p = OpenFootballProvider(cache_ttl_seconds=0)
        rows = p.fixtures(
            datetime(2026, 9, 19, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 20, 0, tzinfo=timezone.utc),
            league="en.1", season="2026-27",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fixture_id, "openfootball-2026_27-en.1-2")
        self.assertEqual(rows[0].home_team, "Arsenal FC")
        self.assertEqual(rows[0].status, "NS")
        self.assertEqual(rows[0].home_form.matches, 2)
        self.assertEqual(rows[0].home_form.wins, 1)
        self.assertEqual(rows[0].home_form.draws, 1)
        self.assertEqual(mock_get.call_count, 1)

    def test_season_resolution(self):
        start = datetime(2027, 1, 10, tzinfo=timezone.utc)
        self.assertEqual(OpenFootballProvider._season_label(start, None), "2026-27")
        self.assertEqual(OpenFootballProvider._season_label(start, 2026), "2026-27")
        self.assertEqual(OpenFootballProvider._season_label(start, "2026-2027"), "2026-27")


class TestProviderRouter(unittest.TestCase):
    def test_thesportsdb_refuses_fake_live_mode(self):
        p = TheSportsDBProvider(cache_ttl_seconds=0)
        with self.assertRaises(ValueError):
            p.fixtures(datetime(2026, 9, 18, tzinfo=timezone.utc),
                       datetime(2026, 9, 18, 19, tzinfo=timezone.utc), live=True)

    def test_auto_build_includes_bsd_when_key_configured(self):
        p = build_provider(
            "auto", "", "", provider_chain="bsd,openfootball",
            bsd_api_key="bsd-key",
        )
        self.assertIsInstance(p, CompositeFootballProvider)
        self.assertEqual(p.provider_names, ["bsd", "openfootball"])

    def test_auto_build_includes_openfootball_without_key(self):
        p = build_provider(
            "auto", "", "", provider_chain="openfootball,api-football",
        )
        self.assertIsInstance(p, CompositeFootballProvider)
        self.assertEqual(p.provider_names, ["openfootball"])

    def test_auto_build_skips_unconfigured_keyed_providers(self):
        p = build_provider(
            "auto", "", "", provider_chain="api-football,football-data,thesportsdb",
            football_data_api_key="", thesportsdb_api_key="123"
        )
        self.assertIsInstance(p, CompositeFootballProvider)
        self.assertEqual(p.provider_names, ["thesportsdb"])



    @patch("app.data_providers.httpx.Client.get")
    def test_api_football_ids_are_prefixed_and_unprefixed_for_upstream(self, mock_get):
        from app.data_providers import ApiFootballProvider
        mock_get.return_value = Resp({"response": [{
            "fixture": {"id": 123, "date": "2026-09-20T15:00:00+00:00", "status": {"short": "NS"}},
            "league": {"name": "Premier League", "season": 2026},
            "teams": {"home": {"name": "Arsenal", "id": 1}, "away": {"name": "Chelsea", "id": 2}},
            "goals": {"home": None, "away": None}, "score": {}
        }]})
        p = ApiFootballProvider("key", cache_ttl_seconds=0)
        p._recent_form = Mock(return_value=TeamForm())
        p.odds = Mock(return_value={})
        fx = p.fixture_by_id("api-football-123")
        self.assertEqual(fx.fixture_id, "api-football-123")
        self.assertTrue(any(c.kwargs.get("params", {}).get("id") == "123" for c in mock_get.call_args_list))

    def test_composite_preserves_structured_lineup_dict(self):
        provider = Mock()
        provider.lineups.return_value = {"home": {"players": []}, "away": {"players": []}}
        composite = CompositeFootballProvider([("sofascore", provider)])
        data = composite.lineups("sofascore-123")
        self.assertEqual(data, [{"provider": "sofascore", "data": {"home": {"players": []}, "away": {"players": []}}}])

    def test_numeric_id_is_not_routed_to_thesportsdb_after_api_prefixing(self):
        primary = Mock()
        api = Mock()
        primary.fixture_by_id.return_value = None
        api.fixture_by_id.return_value = Fixture(
            "api-football-123", datetime(2026, 9, 20, tzinfo=timezone.utc),
            "Premier League", "2026", "Real Home", "Real Away"
        )
        composite = CompositeFootballProvider([("thesportsdb", primary), ("api-football", api)])
        out = composite.fixture_by_id("api-football-123")
        self.assertEqual(out.home_team, "Real Home")
        primary.fixture_by_id.assert_not_called()

    def test_api_football_numeric_selection_falls_back_to_thesportsdb_mapping(self):
        api = Mock()
        api.fixtures.side_effect = RuntimeError(
            "API-Football error: {'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}"
        )
        db = Mock()
        db.fixtures.side_effect = lambda start, end, live=False, league=None, season=None: [
            Fixture(
                f"thesportsdb-{league}",
                start + timedelta(hours=1),
                "Mapped League",
                str(season),
                f"Home {league}",
                f"Away {league}",
            )
        ]
        composite = CompositeFootballProvider([("api-football", api), ("thesportsdb", db)])
        rows = composite.fixtures(
            datetime(2026, 9, 18, tzinfo=timezone.utc),
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            league="39,140",
            season=2026,
        )
        self.assertEqual(len(rows), 2)
        called = [call.kwargs for call in db.fixtures.call_args_list]
        self.assertEqual({x["league"] for x in called}, {"4328", "4335"})
        self.assertEqual({x["season"] for x in called}, {"2026-2027"})

    @patch("app.data_providers.httpx.Client.get")
    def test_allsports_discovery_maps_selected_api_football_league(self, mock_get):
        def response(url, *args, **kwargs):
            met = kwargs.get("params", {}).get("met")
            if met == "Leagues":
                return Resp({"success": 1, "result": [
                    {"league_key": "148", "league_name": "Premier League", "country_name": "England"},
                    {"league_key": "999", "league_name": "Some Other League", "country_name": "England"},
                ]})
            return Resp({"success": 1, "result": [{
                "event_key": "1",
                "event_date": "2026-09-19",
                "event_time": "15:00",
                "event_home_team": "Arsenal",
                "event_away_team": "Chelsea",
                "event_live": "0",
                "event_status": "NS",
                "country_name": "England",
                "league_name": "Premier League",
                "league_key": "148",
            }]})
        mock_get.side_effect = response
        provider = AllSportsAPIProvider("key", cache_ttl_seconds=0)
        composite = CompositeFootballProvider([("allsportsapi", provider)])
        rows = composite.fixtures(
            datetime(2026, 9, 19, tzinfo=timezone.utc),
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            league="39",
        )
        self.assertEqual(len(rows), 1)
        fixture_calls = [c.kwargs["params"] for c in mock_get.call_args_list if c.kwargs.get("params", {}).get("met") == "Fixtures"]
        self.assertEqual(fixture_calls[0]["leagueId"], "148")

    def test_numeric_selection_routes_supported_league_to_football_data(self):
        fd = Mock()
        fd.fixtures.return_value = [
            Fixture(
                "football-data-1",
                datetime(2026, 9, 19, 15, tzinfo=timezone.utc),
                "Premier League",
                "2026",
                "Arsenal",
                "Chelsea",
            )
        ]
        api = Mock()
        api.fixtures.side_effect = RuntimeError("free season unavailable")
        composite = CompositeFootballProvider([("football-data", fd), ("api-football", api)])
        rows = composite.fixtures(
            datetime(2026, 9, 19, tzinfo=timezone.utc),
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            league="39",
            season=2026,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(fd.fixtures.call_args.kwargs["league"], "PL")
        self.assertEqual(fd.fixtures.call_args.kwargs["season"], 2026)
        api.fixtures.assert_not_called()

    def test_fallback_uses_second_provider_when_first_fails(self):
        first = Mock()
        second = Mock()
        fx = Fixture("x", datetime.now(timezone.utc), "L", "2026", "A", "B")
        first.fixtures.side_effect = RuntimeError("upstream down")
        second.fixtures.return_value = [fx]
        p = CompositeFootballProvider([("first", first), ("second", second)])
        rows = p.fixtures(datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(days=1))
        self.assertEqual(rows, [fx])
        self.assertEqual(fx.stats["provider"], "second")

    def test_fixture_by_id_enriches_thesportsdb_fixture_with_api_football_odds(self):
        primary = Mock()
        fx = Fixture("thesportsdb-1", datetime(2026, 9, 20, tzinfo=timezone.utc),
                     "Premier League", "2026", "Arsenal", "Chelsea",
                     stats={"api_football_id": "999"})
        primary.fixture_by_id.return_value = fx

        odds_provider = Mock()
        odds_provider.odds.return_value = {"bookmakers": [{
            "name": "Bet365", "bets": [{"name": "Match Winner", "values": [
                {"value": "Home", "odd": "2.10"},
                {"value": "Draw", "odd": "3.50"},
                {"value": "Away", "odd": "3.20"},
            ]}]
        }]}

        p = CompositeFootballProvider([("thesportsdb", primary), ("api-football", odds_provider)])
        out = p.fixture_by_id("thesportsdb-1")
        self.assertEqual(out.odds, {"home": 2.10, "draw": 3.50, "away": 3.20})
        odds_provider.odds.assert_called_once_with("999")

    def test_merge_deduplicates_same_fixture(self):
        fx1 = Fixture("a", datetime(2026, 9, 20, 15, tzinfo=timezone.utc), "Premier League", "2026", "Arsenal", "Chelsea")
        fx2 = Fixture("b", datetime(2026, 9, 20, 15, tzinfo=timezone.utc), "Premier League", "2026", "Arsenal", "Chelsea")
        one, two = Mock(), Mock()
        one.fixtures.return_value = [fx1]
        two.fixtures.return_value = [fx2]
        p = CompositeFootballProvider([("one", one), ("two", two)], mode="merge")
        rows = p.fixtures(fx1.date, fx1.date + timedelta(hours=1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].stats["provider"], "one")



class TestProviderSettingsWiring(unittest.TestCase):
    @patch("app.data_providers.httpx.Client.get")
    def test_football_data_form_enrichment_uses_only_pre_fixture_results(self, mock_get):
        class Resp2:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"matches": [
                    {"id": 1, "utcDate": "2026-09-10T14:00:00Z", "status": "FINISHED",
                     "competition": {"code": "PL", "name": "Premier League"}, "season": {"startDate": "2026-08-01"},
                     "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Everton"},
                     "score": {"fullTime": {"home": 2, "away": 0}}},
                    {"id": 3, "utcDate": "2026-09-20T15:00:00Z", "status": "SCHEDULED",
                     "competition": {"code": "PL", "name": "Premier League"}, "season": {"startDate": "2026-08-01"},
                     "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
                     "score": {"fullTime": {"home": None, "away": None}}},
                    {"id": 2, "utcDate": "2026-09-25T14:00:00Z", "status": "FINISHED",
                     "competition": {"code": "PL", "name": "Premier League"}, "season": {"startDate": "2026-08-01"},
                     "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
                     "score": {"fullTime": {"home": 0, "away": 3}}},
                ]}
        mock_get.return_value = Resp2()
        p = FootballDataOrgProvider("key", cache_ttl_seconds=0, enrich_form=True)
        rows = p.fixtures(datetime(2026, 9, 20, tzinfo=timezone.utc),
                          datetime(2026, 9, 21, tzinfo=timezone.utc), league="PL")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fixture_id, "football-data-3")
        self.assertEqual(rows[0].home_form.matches, 1)
        self.assertEqual(rows[0].home_form.wins, 1)

    def test_settings_mapping_keeps_chain_and_keys(self):
        class S:
            football_provider = "auto"
            football_api_base_url = ""
            api_football_key = ""
            api_football_leagues = "39,179,144,203,233,119"
            api_football_use_standings_form = True
            football_api_key = ""
            provider_cache_ttl_seconds = 60
            sofascore_browser_path = ""
            livescorefootball_league = "eng.1"
            odds_preferred_bookmaker = ""
            api_football_enrich_lists = False
            api_football_fetch_discipline = False
            football_data_api_key = "fd-key"
            football_data_base_url = "https://api.football-data.org/v4"
            football_data_competition = "PL"
            football_data_enrich_form = False
            thesportsdb_api_key = "123"
            thesportsdb_base_url = "https://www.thesportsdb.com/api/v1/json"
            thesportsdb_league_id = "4328"
            football_provider_chain = "football-data,thesportsdb"
            bsd_api_key = "bsd-key"
            bsd_base_url = "https://sports.bzzoiro.com/api/v2"
            football_provider_mode = "fallback"
        p = build_provider_from_settings(S())
        self.assertEqual(
            p.provider_names,
            ["bsd", "openfootball", "thesportsdb", "livescorefootball", "football-data"],
        )

if __name__ == "__main__":
    unittest.main()
