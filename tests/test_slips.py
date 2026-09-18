import unittest
from datetime import datetime, timedelta, timezone
from app.schemas import Fixture, TeamForm
from app.engine import FootballProbabilityEngine
from app.slips import SlipGenerator

class SlipTests(unittest.TestCase):
    def fixtures(self, n):
        now=datetime.now(timezone.utc)
        out=[]
        for i in range(n):
            out.append(Fixture(str(i), now+timedelta(hours=i+1), 'League','2026',f'H{i}',f'A{i}',home_elo=1600+i,away_elo=1500,
                               home_form=TeamForm(matches=10,wins=6,draws=2,losses=2,goals_for=18,goals_against=8),
                               away_form=TeamForm(matches=10,wins=4,draws=3,losses=3,goals_for=13,goals_against=12)))
        return out
    def test_weekly_five_slips(self):
        gen=SlipGenerator(FootballProbabilityEngine(),0.5,'x')
        slips=gen.weekly(self.fixtures(40))
        self.assertEqual(len(slips),5)
        self.assertTrue(all(len(s.selections)==20 for s in slips))
        sigs={tuple(sorted(x['fixture_id'] for x in s.selections)) for s in slips}
        self.assertEqual(len(sigs),5)
    def test_daily_uses_eligible_count(self):
        gen=SlipGenerator(FootballProbabilityEngine(),0.5,'x')
        slip=gen.daily(self.fixtures(10))
        self.assertEqual(len(slip.selections),10)

    def test_monthly_five_distinct_slips(self):
        gen=SlipGenerator(FootballProbabilityEngine(),0.5,'x')
        slips=gen.monthly(self.fixtures(60))
        self.assertEqual(len(slips),5)
        self.assertTrue(all(30 <= len(s.selections) <= 50 for s in slips))
        self.assertEqual(len({tuple(sorted(x['fixture_id'] for x in s.selections)) for s in slips}),5)

if __name__ == '__main__': unittest.main()
