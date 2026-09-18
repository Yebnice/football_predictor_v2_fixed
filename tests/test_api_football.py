import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.data_providers import ApiFootballProvider, build_provider


class TestApiFootballProvider(unittest.TestCase):
    def test_provider_selection(self):
        p = build_provider("api-football", "https://v3.football.api-sports.io", "key")
        self.assertIsInstance(p, ApiFootballProvider)

    @patch("app.data_providers.httpx.Client.get")
    def test_fixture_normalization(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"errors": {}, "response": [{
                    "fixture": {"id": 123, "date": "2026-09-10T18:00:00+00:00", "status": {"short": "NS"}},
                    "league": {"name": "Premier League", "season": 2026},
                    "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
                    "goals": {"home": None, "away": None},
                    "score": {"periods": {"first": {"home": None, "away": None}}},
                }]}
        mock_get.return_value = R()
        p = ApiFootballProvider("key")
        start = datetime(2026, 9, 10, tzinfo=timezone.utc)
        end = datetime(2026, 9, 10, 23, 59, tzinfo=timezone.utc)
        rows = p.fixtures(start, end, league=39)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fixture_id, "api-football-123")
        self.assertEqual(rows[0].home_team, "Arsenal")
        self.assertEqual(rows[0].stats["source"], "api-football")

    @patch("app.data_providers.httpx.Client.get")
    def test_fixture_details_makes_a_single_request(self, mock_get):
        # Regression test: fixture_details previously issued the same request twice.
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"errors": {}, "response": [{
                    "fixture": {"id": 123, "date": "2026-09-10T18:00:00+00:00", "status": {"short": "NS"}},
                    "league": {"name": "Premier League", "season": 2026},
                    "teams": {"home": {"name": "Arsenal", "id": 1}, "away": {"name": "Chelsea", "id": 2}},
                    "goals": {"home": None, "away": None},
                    "score": {"periods": {}},
                }]}
        mock_get.return_value = R()
        p = ApiFootballProvider("key")
        detail = p.fixture_details("123")
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(detail["fixture"]["id"], 123)

    @patch("app.data_providers.httpx.Client.get")
    def test_fixture_by_id_returns_none_when_not_found(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"errors": {}, "response": []}
        mock_get.return_value = R()
        p = ApiFootballProvider("key")
        self.assertIsNone(p.fixture_by_id("does-not-exist"))

    @patch("app.data_providers.httpx.Client.get")
    def test_repeated_fixtures_call_is_served_from_cache(self, mock_get):
        # Regression/feature test: identical calls within the TTL window should
        # not spend additional daily quota against the free plan's 100/day cap.
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"errors": {}, "response": []}
        mock_get.return_value = R()
        p = ApiFootballProvider("key", cache_ttl_seconds=60.0)
        now = datetime.now(timezone.utc)
        p.fixtures(now, now, league=39)
        p.fixtures(now, now, league=39)
        self.assertEqual(mock_get.call_count, 1)

    @patch("app.data_providers.httpx.Client.get")
    def test_fixtures_passes_league_and_season_through(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"errors": {}, "response": []}
        mock_get.return_value = R()
        p = ApiFootballProvider("key", cache_ttl_seconds=0)
        now = datetime.now(timezone.utc)
        p.fixtures(now, now, league=39, season=2021)
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["league"], 39)
        self.assertEqual(kwargs["params"]["season"], 2021)

    @patch("app.data_providers.httpx.Client.get")
    def test_historical_form_excludes_results_after_target_fixture(self, mock_get):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"errors": {}, "response": [
                    {"fixture": {"id": 20, "date": "2026-09-10T15:00:00Z", "status": {"short": "FT"}},
                     "league": {"name": "Premier League", "season": 2026},
                     "teams": {"home": {"id": 1, "name": "Arsenal"}, "away": {"id": 2, "name": "Everton"}},
                     "goals": {"home": 2, "away": 0}, "score": {"periods": {}}},
                    {"fixture": {"id": 19, "date": "2026-09-05T15:00:00Z", "status": {"short": "FT"}},
                     "league": {"name": "Premier League", "season": 2026},
                     "teams": {"home": {"id": 3, "name": "Chelsea"}, "away": {"id": 1, "name": "Arsenal"}},
                     "goals": {"home": 1, "away": 0}, "score": {"periods": {}}},
                    {"fixture": {"id": 21, "date": "2026-09-15T15:00:00Z", "status": {"short": "FT"}},
                     "league": {"name": "Premier League", "season": 2026},
                     "teams": {"home": {"id": 1, "name": "Arsenal"}, "away": {"id": 4, "name": "Leicester"}},
                     "goals": {"home": 3, "away": 0}, "score": {"periods": {}}},
                ]}
        mock_get.return_value = R()
        p = ApiFootballProvider("key", cache_ttl_seconds=60)
        form = p._recent_form(1, before=datetime(2026, 9, 12, tzinfo=timezone.utc), n=5)
        self.assertEqual(form.matches, 2)
        self.assertEqual(form.wins, 1)
        self.assertEqual(form.losses, 1)
        self.assertEqual(form.goals_for, 2.0)
        self.assertEqual(form.goals_against, 1.0)


if __name__ == "__main__":
    unittest.main()
