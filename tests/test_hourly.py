import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import monitor as m
class Hourly(unittest.TestCase):
 def setUp(self):self.db=m.connect(':memory:')
 def tearDown(self):self.db.close()
 def ingest(self,stamp,up=0,down=0):
  m.ingest(self.db,[dict(id='a',email='Demo',inbound='1',up=up,down=down,enabled=True)],stamp,gap=4000)
 def test_continuous_usage_keeps_real_hourly_totals(self):
  self.ingest(0);self.ingest(3600,100,20);self.ingest(7200,1000,200)
  result=m.report(self.db,0,7200,m.ZoneInfo('UTC'),now=7200)
  client=result['clients'][0]
  self.assertEqual(len(client['timeline']),1)
  self.assertEqual(client['hourly']['0']['up'],100)
  self.assertEqual(client['hourly']['3600']['up'],900)
  self.assertEqual(client['hourly']['3600']['down'],180)
  self.assertEqual(result['overview']['hourly']['3600']['up'],900)
  self.assertEqual(sum(h['up'] for h in client['hourly'].values()),1000)
 def test_sample_crosses_hour_and_splits_proportionally(self):
  self.ingest(3570);self.ingest(3630,120,60)
  client=m.report(self.db,0,7200,m.ZoneInfo('UTC'),now=3630)['clients'][0]
  for hour in ('0','3600'):
   self.assertEqual(client['hourly'][hour]['up'],60)
   self.assertEqual(client['hourly'][hour]['down'],30)
   self.assertEqual(client['hourly'][hour]['active_seconds'],30)
 def test_non_whole_hour_timezone_boundaries(self):
  base=1767225600
  self.ingest(base+870);self.ingest(base+930,120)
  client=m.report(self.db,base,base+3600,m.ZoneInfo('Asia/Kathmandu'),now=base+930)['clients'][0]
  self.assertEqual(sorted(map(int,client['hourly'])),[base-2700,base+900])
  self.assertEqual(client['hourly'][str(base+900)]['up'],60)
 def test_disconnected_spans_keep_separate_traffic_in_same_hour(self):
  self.ingest(600);self.ingest(1200,100,20)
  self.ingest(1800,100,20);self.ingest(2400,1000,200)
  result=m.report(self.db,0,3600,m.ZoneInfo('UTC'),now=2400)
  spans=result['clients'][0]['hourly']['0']['spans']
  self.assertEqual(spans,[dict(start=600,end=1200,up=100,down=20),dict(start=1800,end=2400,up=900,down=180)])
  self.assertEqual(result['overview']['hourly']['0']['spans'],spans)
 def test_continuous_span_crossing_hour_preserves_actual_edges(self):
  self.ingest(600);self.ingest(3600,100,20);self.ingest(7200,1000,200);self.ingest(8100,1500,300)
  hourly=m.report(self.db,0,86400,m.ZoneInfo('UTC'),now=8100)['clients'][0]['hourly']
  self.assertEqual(hourly['0']['spans'],[dict(start=600,end=3600,up=100,down=20)])
  self.assertEqual(hourly['7200']['spans'],[dict(start=7200,end=8100,up=500,down=100)])
if __name__=='__main__':unittest.main()
