import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

try:
    import esd
    from esd.sofascore.types.event import Event
    from esd.sofascore.types.team import Team
    from esd.sofascore.types.team_score import TeamScore
    from esd.sofascore.types.tournament import Tournament
    from esd.sofascore.types.status import Status, StatusType
    from esd.sofascore.types.event import RoundInfo
    ESD_AVAILABLE = True
except ImportError:
    ESD_AVAILABLE = False


def make_event(event_id=1, home="Arsenal", away="Chelsea", home_id=10, away_id=20,
                status=StatusType.NOT_STARTED if ESD_AVAILABLE else None,
                home_goals=None, away_goals=None, start_timestamp=1_800_000_000,
                tournament_name="Premier League", tournament_id=17):
    return Event(
        id=event_id,
        status=Status(type=status, description=status.value if status else ""),
        home_team=Team(name=home, id=home_id),
        away_team=Team(name=away, id=away_id),
        home_score=TeamScore(current=home_goals or 0),
        away_score=TeamScore(current=away_goals or 0),
        tournament=Tournament(id=tournament_id, name=tournament_name, slug=tournament_name.lower()),
        start_timestamp=start_timestamp,
        slug=f"{home}-{away}".lower(),
        round_info=RoundInfo(round=1, name="Round 1", cup_round_type=0),
    )


@unittest.skipUnless(ESD_AVAILABLE, "EasySoccerData (esd) not installed — SofascoreProvider is an optional extra")
class SofascoreProviderTests(unittest.TestCase):
    def _provider(self):
        # Patch SofascoreClient so no real browser/Playwright is launched.
        with patch("esd.SofascoreClient") as MockClient:
            MockClient.return_value = MagicMock()
            from app.data_providers import SofascoreProvider
            return SofascoreProvider(cache_ttl_seconds=0), MockClient.return_value

    def test_normalize_maps_core_fields(self):
        from app.data_providers import _normalize_sofascore_event
        event = make_event(event_id=42, home="Arsenal", away="Chelsea",
                            status=StatusType.NOT_STARTED, start_timestamp=1_800_000_000)
        fx = _normalize_sofascore_event(event)
        self.assertEqual(fx.fixture_id, "sofascore-42")
        self.assertEqual(fx.home_team, "Arsenal")
        self.assertEqual(fx.away_team, "Chelsea")
        self.assertEqual(fx.league, "Premier League")
        self.assertEqual(fx.status, "notstarted")
        self.assertIsNone(fx.home_score)  # not started -> no score yet
        self.assertEqual(fx.stats["source"], "sofascore")
        self.assertEqual(fx.date, datetime.fromtimestamp(1_800_000_000, tz=timezone.utc))

    def test_normalize_includes_score_when_finished(self):
        from app.data_providers import _normalize_sofascore_event
        event = make_event(status=StatusType.FINISHED, home_goals=2, away_goals=1)
        fx = _normalize_sofascore_event(event)
        self.assertEqual(fx.status, "finished")
        self.assertEqual(fx.home_score, 2)
        self.assertEqual(fx.away_score, 1)

    def test_fixtures_dedupes_across_days_and_filters_to_range(self):
        provider, mock_client = self._provider()
        early = make_event(event_id=1, start_timestamp=1_700_000_000)  # outside range
        in_range = make_event(event_id=2, start_timestamp=1_800_000_000)
        mock_client.get_events.side_effect = lambda date=None, live=False: [early, in_range]
        start = datetime.fromtimestamp(1_800_000_000 - 3600, tz=timezone.utc)
        end = datetime.fromtimestamp(1_800_000_000 + 3600, tz=timezone.utc)
        fixtures = provider.fixtures(start, end)
        self.assertEqual([f.fixture_id for f in fixtures], ["sofascore-2"])

    def test_fixtures_rejects_overly_wide_range(self):
        provider, _ = self._provider()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            provider.fixtures(start, end)

    def test_fixture_by_id_returns_none_on_lookup_failure(self):
        provider, mock_client = self._provider()
        mock_client.get_event.side_effect = RuntimeError("not found")
        self.assertIsNone(provider.fixture_by_id("sofascore-999"))

    def test_fixture_by_id_enriches_with_recent_form(self):
        provider, mock_client = self._provider()
        target = make_event(event_id=5, home_id=10, away_id=20)
        mock_client.get_event.return_value = target
        history = [
            make_event(event_id=100, home_id=10, away_id=99, status=StatusType.FINISHED, home_goals=2, away_goals=0),
            make_event(event_id=101, home_id=55, away_id=10, status=StatusType.FINISHED, home_goals=1, away_goals=1),
        ]
        mock_client.get_team_events.return_value = history
        fx = provider.fixture_by_id("sofascore-5")
        self.assertEqual(fx.home_form.matches, 2)
        self.assertEqual(fx.home_form.wins, 1)
        self.assertEqual(fx.home_form.draws, 1)

    def test_odds_defaults_to_empty_dict(self):
        provider, _ = self._provider()
        self.assertEqual(provider.odds("sofascore-1"), {})

    def test_missing_esd_raises_actionable_import_error(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "esd":
                raise ImportError("no module named esd")
            return real_import(name, *args, **kwargs)

        from app import data_providers
        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(ImportError) as ctx:
                data_providers.SofascoreProvider()
        self.assertIn("requirements-optional.txt", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
