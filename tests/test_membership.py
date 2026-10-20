"""Membership changes must not erase retained usage or fabricate a reconnect."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import monitor as m


def client(key='a',up=0):
    return dict(id='1:'+key,email=key,inbound='1',up=up,down=0,enabled=True)


class Membership(unittest.TestCase):
    def setUp(self):self.db=m.connect(':memory:')
    def tearDown(self):self.db.close()

    def test_add_remove_and_retained_totals(self):
        m.ingest(self.db,[client()],60)
        m.ingest(self.db,[client(up=120)],120)
        m.ingest(self.db,[client('b')],180)
        result=m.report(self.db,0,240,m.ZoneInfo('UTC'),now=181)
        self.assertEqual([c['email'] for c in result['clients'] if c['present']],['b'])
        self.assertEqual(result['overview']['totals']['up'],120)
        removed=next(c for c in result['clients'] if c['email']=='a')
        self.assertEqual(removed['status'],'unknown')
        self.assertEqual(sum(day['active_seconds'] for day in removed['daily'].values()),60)

    def test_empty_success_and_recreated_identity_gets_new_baseline(self):
        m.ingest(self.db,[client()],60)
        m.ingest(self.db,[client(up=120)],120)
        m.ingest(self.db,[],180)
        self.assertEqual(m.current_clients(self.db),set())
        m.ingest(self.db,[client(up=10000)],240)
        sample=self.db.execute('SELECT * FROM samples WHERE end=240').fetchone()
        self.assertEqual((sample['state'],sample['up'],sample['start']),('unknown',0,240))
        self.assertEqual(self.db.execute('SELECT SUM(up) FROM samples').fetchone()[0],120)

    def test_failed_snapshot_preserves_previous_membership(self):
        m.ingest(self.db,[client()],60)
        with self.assertRaises(KeyError):m.ingest(self.db,[client('b'),dict(id='bad',up=0)],120)
        self.assertEqual(m.current_clients(self.db),{'1:a'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM clients').fetchone()[0],1)

    def test_deleted_counters_and_new_client_without_counters(self):
        rows=m.normalize([dict(id=1,settings={'clients':[{'email':'new'}]},
                               clientStats=[dict(email='deleted',up=999,down=1)])])
        self.assertEqual([r['email'] for r in rows],['new'])
        self.assertIsNone(rows[0]['up'])
        self.assertEqual(m.normalize([dict(id=1,settings={'clients':[]},
                               clientStats=[dict(email='deleted',up=999,down=1)])]),[])

    def test_same_client_in_two_inbounds_retains_each_name_and_usage(self):
        def inbounds(up=0,remark='Primary'):
            return [dict(id=1,remark=remark,settings={'clients':[{'email':'shared'}]},
                         clientStats=[dict(email='shared',up=up,down=0)]),
                    dict(id=2,remark='Secondary',settings={'clients':[{'email':'shared'}]},
                         clientStats=[dict(email='shared',up=up*2,down=0)])]
        m.ingest(self.db,m.normalize(inbounds()),60)
        m.ingest(self.db,m.normalize(inbounds(100,'Renamed')),120)
        report=m.report(self.db,0,180,m.ZoneInfo('UTC'),now=121)
        clients={c['id']:c for c in report['clients']}
        self.assertEqual(clients['1:shared']['inbound_name'],'Renamed')
        self.assertEqual(clients['2:shared']['inbound_name'],'Secondary')
        self.assertEqual(report['overview']['totals']['up'],300)

    def test_inbound_name_fallback_and_missing_counters(self):
        rows=m.normalize([dict(id=3,remark='New inbound',settings={'clients':[{'email':'new'}]},clientStats=[]),
                          dict(id=4,settings={'clients':[{'email':'other'}]},clientStats=[])])
        m.ingest(self.db,rows,60)
        report=m.report(self.db,0,180,m.ZoneInfo('UTC'),now=61)
        self.assertEqual({c['inbound_name'] for c in report['clients']},{'New inbound','4'})

if __name__=='__main__':unittest.main()
