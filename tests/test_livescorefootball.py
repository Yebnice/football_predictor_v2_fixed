import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.data_providers import LivescoreFootballProvider

# NOTE: worldcup26.ir's exact JSON field names are not independently verified
# (see LivescoreFootballProvider's docstring) — this mock payload is an
# assumed-plausible shape based on the endpoints/fields the project's README
# documents. If the live API's real fields differ, these tests would need
# updating alongside _normalize_livescorefootball_fixture, not just relaxed.
ASSUMED_FIXTURE_ROW = {
    "id": "5001", "date": "2026-09-20T15:00:00Z", "status": "scheduled",
    "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
    "homeScore": None, "awayScore": None, "season": "2026",
}


class LivescoreFootballProviderTests(unittest.TestCase):
    def _provider(self):
        return LivescoreFootballProvider(default_league="eng.1", cache_ttl_seconds=0)

    def test_requires_a_league_slug(self):
        provider = LivescoreFootballProvider(cache_ttl_seconds=0)  # no default_league
        now = datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            provider.fixtures(now, now)

    @patch("httpx.Client.get")
    def test_fixtures_normalizes_assumed_shape(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self): return {"fixtures": [ASSUMED_FIXTURE_ROW]}
        mock_get.return_value = R()
        provider = self._provider()
        now = datetime.now(timezone.utc)
        fixtures = provider.fixtures(now, now)
        self.assertEqual(len(fixtures), 1)
        fx = fixtures[0]
        self.assertEqual(fx.fixture_id, "livescorefootball-eng.1-5001")
        self.assertEqual(fx.home_team, "Arsenal")
        self.assertEqual(fx.away_team, "Chelsea")
        self.assertEqual(fx.league, "eng.1")
        self.assertIsNone(fx.home_score)

    @patch("httpx.Client.get")
    def test_fixtures_follows_documented_page_count(self, mock_get):
        first = ASSUMED_FIXTURE_ROW | {"id": "5001"}
        second = ASSUMED_FIXTURE_ROW | {"id": "5002"}
        class R:
            def __init__(self, payload):
                self.status_code = 200
                self.headers = {}
                self._payload = payload
            def raise_for_status(self): pass
            def json(self): return self._payload
        mock_get.side_effect = [
            R({"events": [first], "pageIndex": 1, "pageCount": 2}),
            R({"events": [second], "pageIndex": 2, "pageCount": 2}),
        ]
        provider = self._provider()
        start = datetime(2026, 9, 20, tzinfo=timezone.utc)
        end = datetime(2026, 9, 21, tzinfo=timezone.utc)
        fixtures = provider.fixtures(start, end)
        self.assertEqual([fx.fixture_id for fx in fixtures], [
            "livescorefootball-eng.1-5001",
            "livescorefootball-eng.1-5002",
        ])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["page"], 2)

    @patch("httpx.Client.get")
    def test_extract_rows_checks_multiple_wrapper_keys(self, mock_get):
        # Response shape is unconfirmed, so the provider tries several
        # plausible envelope keys rather than assuming exactly one.
        class R:
            def raise_for_status(self): pass
            def json(self): return {"data": [ASSUMED_FIXTURE_ROW]}
        mock_get.return_value = R()
        provider = self._provider()
        now = datetime.now(timezone.utc)
        fixtures = provider.fixtures(now, now)
        self.assertEqual(len(fixtures), 1)

    @patch("httpx.Client.get")
    def test_fixtures_handles_a_bare_list_response(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self): return [ASSUMED_FIXTURE_ROW]
        mock_get.return_value = R()
        provider = self._provider()
        now = datetime.now(timezone.utc)
        fixtures = provider.fixtures(now, now)
        self.assertEqual(len(fixtures), 1)

    @patch("httpx.Client.get")
    def test_unrecognized_shape_returns_empty_not_a_crash(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self): return {"totally_unexpected_key": "nope"}
        mock_get.return_value = R()
        provider = self._provider()
        now = datetime.now(timezone.utc)
        fixtures = provider.fixtures(now, now)
        self.assertEqual(fixtures, [])

    @patch("httpx.Client.get")
    def test_fixture_by_id_round_trips_league_and_event(self, mock_get):
        class R:
            def raise_for_status(self): pass
            def json(self): return {"match": ASSUMED_FIXTURE_ROW}
        mock_get.return_value = R()
        provider = self._provider()
        fx = provider.fixture_by_id("livescorefootball-eng.1-5001")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.home_team, "Arsenal")

    def test_fixture_by_id_returns_none_for_malformed_id(self):
        provider = self._provider()
        self.assertIsNone(provider.fixture_by_id("not-a-real-id"))

    def test_odds_and_lineups_are_empty_by_design(self):
        # This upstream source has no bookmaker odds at all.
        provider = self._provider()
        self.assertEqual(provider.odds("livescorefootball-eng.1-5001"), {})
        self.assertEqual(provider.lineups("livescorefootball-eng.1-5001"), [])


if __name__ == "__main__":
    unittest.main()
