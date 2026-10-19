import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor as m
from push_support import preferences, deliver_once, valid_subscription
import unittest
import json
import base64
import threading
import urllib.request
import urllib.error
import tempfile


def row(n):
    return dict(id='1:a', email='a', inbound='1', up=n, down=0, enabled=True)


class Push(unittest.TestCase):
    def setUp(self):
        self.db = m.connect(':memory:')
        with self.db:
            self.db.execute("INSERT INTO preferences VALUES('layout',?)", (json.dumps({'order': [], 'favorites': ['1:a']}),))
            self.db.execute('INSERT INTO push_subscriptions VALUES(?,?,0)', ('https://fcm.googleapis.com/e', '{}'))

    def tearDown(self):
        self.db.close()

    def test_only_idle_to_active_and_no_duplicate(self):
        for ts,n in [(60,0),(120,5),(180,5),(240,10),(300,15)]:
            m.ingest(self.db,[row(n)],ts)
        self.assertEqual(self.db.execute('select count(*) from push_outbox').fetchone()[0],1)
        self.assertEqual(self.db.execute('select ts from activity_events').fetchone()[0],240)
        m.ingest(self.db,[row(15)],300)
        self.assertEqual(self.db.execute('select count(*) from push_outbox').fetchone()[0],1)

    def test_gap_and_recovery_do_not_notify(self):
        m.ingest(self.db,[row(0)],60);m.ingest(self.db,[row(0)],120)
        with self.db:self.db.execute("insert into health values(150,0,'failure')")
        m.ingest(self.db,[row(5)],180);m.ingest(self.db,[row(10)],240)
        self.assertEqual(self.db.execute('select count(*) from push_outbox').fetchone()[0],0)

    def test_delivery_retry_and_expired_subscription(self):
        for ts,n in [(60,0),(120,0),(180,10)]:m.ingest(self.db,[row(n)],ts)
        def fail(**kw):raise TimeoutError()
        self.assertTrue(deliver_once(self.db,{'private_key':'unused','subject':'https://example.com'},fail,now=180))
        self.assertEqual(self.db.execute('select attempts,next_attempt from push_outbox').fetchone()[:],(1,210))
        class Gone(Exception):status_code=410
        def gone(**kw):raise Gone()
        deliver_once(self.db,{'private_key':'unused','subject':'https://example.com'},gone,now=210)
        self.assertEqual(self.db.execute('select count(*) from push_subscriptions').fetchone()[0],0)

    def test_endpoints_cannot_target_local_services(self):
        value={'endpoint':'https://fcm.googleapis.com/e','keys':{'auth':base64.urlsafe_b64encode(b'x'*16).decode(),'p256dh':base64.urlsafe_b64encode(b'\x04'+b'x'*64).decode()}}
        self.assertTrue(valid_subscription(value))
        for endpoint in ['https://127.0.0.1/a','http://fcm.googleapis.com/e','https://fcm.googleapis.com.evil.test/e','https://fcm.googleapis.com:8098/e']:
            with self.assertRaises(ValueError):valid_subscription(dict(value,endpoint=endpoint))

    def test_timeline_includes_proportional_traffic(self):
        m.ingest(self.db,[row(0)],60);m.ingest(self.db,[row(100)],120)
        result=m.report(self.db,90,120,m.ZoneInfo('UTC'),now=120)
        self.assertEqual(result['clients'][0]['timeline'][0]['up'],50)


class OverviewRetention(unittest.TestCase):
    def test_overlapping_clients_sum_duration_and_traffic(self):
        db=m.connect(':memory:')
        try:
            rows=[row(0),dict(row(0),id='1:b',email='b')]
            m.ingest(db,rows,60)
            m.ingest(db,[row(100),dict(row(50),id='1:b',email='b')],120)
            value=m.report(db,0,180,m.ZoneInfo('UTC'),now=120)['overview']
            self.assertEqual(value['totals']['active_seconds'],120)
            self.assertEqual(value['totals']['up'],150)
            self.assertEqual(sum(p['up'] for p in value['timeline']),150)
            self.assertEqual(value['timeline'][0]['end']-value['timeline'][0]['start'],60)
        finally:db.close()

    def test_retention_deletes_old_and_clips_boundary(self):
        db=m.connect(':memory:')
        try:
            m.ingest(db,[row(0)],60);m.ingest(db,[row(100)],120)
            cutoff=90;m.prune_history(db,365,now=cutoff+365*86400)
            record=db.execute('select start,end,up from samples').fetchone()
            self.assertEqual(tuple(record),(90,120,50))
            self.assertEqual(db.execute('select count(*) from samples where start<?',(cutoff,)).fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from health where ts<?',(cutoff,)).fetchone()[0],0)
        finally:db.close()


class Web(unittest.TestCase):
    def test_no_auth_reads_origin_checked_writes_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'db');db=m.connect(path);m.ingest(db,[row(0)],60);db.close()
            server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
            origin=f'http://127.0.0.1:{server.server_port}'
            server.cfg={'database':path,'timezone':'UTC','max_gap_seconds':150,'web':{'auth':False,'public_origin':origin},'panel_link':'https://panel.example.test/'}
            worker=threading.Thread(target=server.serve_forever);worker.start()
            try:
                with urllib.request.urlopen(origin+'/api/config') as r:self.assertEqual(json.load(r)['preferences']['favorites'],[])
                payload=json.dumps({'order':['1:a'],'favorites':['1:a'],'icons':{'1:a':'router'}}).encode()
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(urllib.request.Request(origin+'/api/preferences',data=payload,headers={'Origin':'https://evil.test'}))
                self.assertEqual(ctx.exception.code,403)
                with urllib.request.urlopen(urllib.request.Request(origin+'/api/preferences',data=payload,headers={'Origin':origin})) as r:self.assertEqual(r.status,200)
                with urllib.request.urlopen(origin+'/api/config') as r:self.assertEqual(json.load(r)['preferences']['icons'],{'1:a':'router'})
                legacy=json.dumps({'order':['1:a'],'favorites':['1:a']}).encode()
                with urllib.request.urlopen(urllib.request.Request(origin+'/api/preferences',data=legacy,headers={'Origin':origin})) as r:self.assertEqual(r.status,200)
                with urllib.request.urlopen(origin+'/api/config') as r:self.assertEqual(json.load(r)['preferences']['icons'],{'1:a':'router'})
                for endpoint in ['/','/sw.js','/api/report']:
                    with urllib.request.urlopen(origin+endpoint) as r:self.assertEqual(r.status,200)
            finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
