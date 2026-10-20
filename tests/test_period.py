import datetime as dt
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import monitor as m


class Period(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:')
        self.tz=m.ZoneInfo('Asia/Shanghai')
    def tearDown(self):self.db.close()
    def timestamp(self,value):return int(dt.datetime.fromisoformat(value).replace(tzinfo=self.tz).timestamp())
    def ingest(self,when,up,second=0):
        m.ingest(self.db,[dict(id='a',email='Demo A',inbound='1',enabled=True,up=up,down=0),dict(id='b',email='Demo B',inbound='1',enabled=True,up=second,down=0)],self.timestamp(when))

    def test_year_and_month_split_cross_boundary_proportionally(self):
        self.ingest('2026-01-31T23:59:30',0)
        self.ingest('2026-02-01T00:00:30',120,60)
        now=self.timestamp('2026-02-01T00:01:00')
        year=m.period_report(self.db,'year',self.tz,now)
        month=m.period_report(self.db,'month',self.tz,now)
        self.assertEqual(len(year['bins']),12)
        self.assertEqual(len(month['bins']),28)
        self.assertEqual(year['clients']['a']['totals']['active_seconds'],60)
        self.assertEqual(year['clients']['a']['bins'][0]['up'],60)
        self.assertEqual(year['clients']['a']['bins'][1]['up'],60)
        self.assertEqual(month['clients']['a']['totals']['active_seconds'],30)
        self.assertEqual(month['clients']['a']['totals']['up'],60)
        self.assertEqual(month['overview']['totals']['up'],90)
        self.assertEqual(year['overview']['totals']['active_seconds'],120)

    def test_previous_year_excluded_and_matches_daily_report(self):
        self.ingest('2025-12-31T23:59:30',0)
        self.ingest('2026-01-01T00:00:30',120)
        now=self.timestamp('2026-01-01T00:01:00')
        period=m.period_report(self.db,'year',self.tz,now)
        full=m.report(self.db,self.timestamp('2026-01-01T00:00:00'),now,self.tz,now)
        self.assertEqual(period['clients']['a']['totals']['up'],60)
        self.assertEqual(period['overview']['totals']['up'],full['overview']['totals']['up'])
        self.assertTrue(all(x['up']==0 for x in period['overview']['bins'][1:]))

    def test_billing_cycle_hour_slots_and_natural_year_days(self):
        self.ingest('2026-10-08T10:59:30',0)
        self.ingest('2026-10-08T11:00:30',120)
        now=self.timestamp('2026-10-20T12:00:00')
        reset=self.timestamp('2026-11-07T22:42:10')
        month=m.period_report(self.db,'month',self.tz,now,next_reset=reset)
        self.assertEqual(month['begin'],self.timestamp('2026-10-07T22:42:10'))
        self.assertEqual(month['end'],reset)
        slots=[month['slots'][i] for i in month['clients']['a']['active_slots']]
        self.assertEqual(len(slots),2)
        self.assertTrue(all(x['end']-x['start']==3600 for x in slots))
        self.assertEqual(slots[0]['end'],slots[1]['start'])
        self.assertEqual(month['bins'][slots[0]['group']]['label'],'2026-10-08')
        self.assertEqual(month['clients']['b']['active_slots'],[])
        year=m.period_report(self.db,'year',self.tz,now,next_reset=reset)
        self.assertEqual(len(year['slots']),365)
        self.assertEqual(len(year['clients']['a']['active_slots']),1)
        self.assertEqual(year['slots'][year['clients']['a']['active_slots'][0]]['group'],9)
        self.assertEqual(year['begin'],self.timestamp('2026-01-01T00:00:00'))

    def test_invalid_scope_and_zero_data(self):
        with self.assertRaises(ValueError):m.period_report(self.db,'all',self.tz)
        empty=m.period_report(self.db,'month',self.tz,self.timestamp('2026-10-20T00:00:00'))
        self.assertEqual(empty['overview']['totals']['up'],0)
        self.assertEqual(len(empty['bins']),31)


if __name__=='__main__':unittest.main()
