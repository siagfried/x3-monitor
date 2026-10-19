import base64
import sys
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('monitor', Path(__file__).resolve().parents[1]/'monitor.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def row(up=0, down=0, enabled=True):
    return dict(id='1:a', email='a', inbound='1', up=up, down=down, enabled=enabled)


class Sampling(unittest.TestCase):
    def setUp(self):
        self.db = m.connect(':memory:')

    def tearDown(self):
        self.db.close()

    def states(self):
        return [r['state'] for r in self.db.execute('SELECT * FROM samples ORDER BY end')]

    def test_baseline_active_idle_reset(self):
        for t, r in [(60,row(100)),(120,row(200)),(180,row(200)),(240,row(3))]:
            m.ingest(self.db,[r],t)
        self.assertEqual(self.states(),['unknown','active','idle','unknown'])
        self.assertEqual(self.db.execute('SELECT SUM(up) FROM samples').fetchone()[0],100)

    def test_gap_does_not_invent_online(self):
        m.ingest(self.db,[row(10)],60)
        m.ingest(self.db,[row(50)],600)
        r=self.db.execute('SELECT * FROM samples WHERE end=600').fetchone()
        self.assertEqual((r['state'],r['up'],r['note']),('unknown',40,'gap'))

    def test_failed_poll_breaks_activity(self):
        m.ingest(self.db,[row()],60)
        with self.db:
            self.db.execute("INSERT INTO health VALUES(90,0,'timeout')")
        m.ingest(self.db,[row(20)],120)
        self.assertEqual(self.states(),['unknown','unknown'])

    def test_missing_stats_baselines_next(self):
        m.ingest(self.db,[row()],60)
        m.ingest(self.db,[row(None,None)],120)
        m.ingest(self.db,[row(20)],180)
        self.assertEqual(self.states(),['unknown']*3)

    def test_session_and_stale(self):
        for t,u in [(60,0),(120,10),(180,20),(240,20),(300,30)]:
            m.ingest(self.db,[row(u)],t)
        result=m.report(self.db,0,400,ZoneInfo('UTC'),now=301)
        c=result['clients'][0]
        self.assertEqual([s['seconds'] for s in c['sessions']],[120,60])
        self.assertEqual(c['status'],'active')
        self.assertEqual(m.report(self.db,0,400,ZoneInfo('UTC'),now=999)['clients'][0]['status'],'unknown')

    def test_midnight_split(self):
        m.ingest(self.db,[row()],86370)
        m.ingest(self.db,[row(60)],86430)
        c=m.report(self.db,0,172800,ZoneInfo('UTC'),now=86430)['clients'][0]
        self.assertEqual([d['active_seconds'] for d in c['daily'].values()],[30,30])
        self.assertEqual([d['up'] for d in c['daily'].values()],[30,30])

    def test_disabled(self):
        m.ingest(self.db,[row()],60)
        m.ingest(self.db,[row(1,enabled=False)],120)
        self.assertEqual(self.states()[-1],'disabled')


class API(unittest.TestCase):
    def test_shapes_and_identity(self):
        for settings in [{'clients':[{'email':'a'}]},json.dumps({'clients':[{'email':'a'}]})]:
            rows=m.normalize([dict(id=1,settings=settings,clientStats=[dict(email='a',up=1,down=2)]),dict(id=2,settings={},clientStats=[dict(email='a',up=4,down=5)])])
            self.assertEqual([r['id'] for r in rows],['1:a','2:a'])
        with self.assertRaises(ValueError):
            m.normalize([dict(id=1,settings={})])

    def test_cookie_relogin_and_base_path(self):
        class Fake(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                assert self.path=='/secret/login'
                assert self.headers.get('X-CSRF-Token') == 'test-csrf'
                assert self.headers.get('Origin') == f'http://127.0.0.1:{self.server.server_port}'
                self.send_response(200)
                self.send_header('Set-Cookie','session=ok; Path=/secret/')
                self.end_headers()
                self.wfile.write(b'{"success":true}')
            def do_GET(self):
                if self.path == '/secret/':
                    self.send_response(200);self.end_headers()
                    self.wfile.write(b'<meta name="csrf-token" content="test-csrf">');return
                assert self.path=='/secret/panel/api/inbounds/list'
                if self.headers.get('Cookie')!='session=ok':
                    self.send_response(401);self.end_headers();return
                self.send_response(200);self.end_headers()
                self.wfile.write(b'{"success":true,"obj":[]}')
        server=ThreadingHTTPServer(('127.0.0.1',0),Fake)
        worker=threading.Thread(target=server.serve_forever);worker.start()
        try:
            panel=m.Panel(dict(url=f'http://127.0.0.1:{server.server_port}/secret/',username='u',password='p'))
            self.assertEqual(panel.fetch(),[])
            self.assertEqual(panel.fetch(),[])
            for handler in panel.opener.handlers:
                if hasattr(handler, 'cookiejar'): handler.cookiejar.clear()
            self.assertEqual(panel.fetch(),[])
        finally:
            server.shutdown();server.server_close();worker.join()

    def test_remote_plaintext_refused(self):
        with self.assertRaises(ValueError):m.Panel(dict(url='http://example.com/'))

    def test_http_auth_report_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'db')
            db=m.connect(path)
            m.ingest(db,[row()],60);m.ingest(db,[row(10)],120);db.close()
            server=ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
            server.cfg=dict(database=path,timezone='UTC',max_gap_seconds=150,web=dict(username='u',password='testpassword123456'))
            worker=threading.Thread(target=server.serve_forever);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(base+'/api/report')
                self.assertEqual(ctx.exception.code,401)
                auth='Basic '+base64.b64encode(b'u:testpassword123456').decode()
                for endpoint in ['/', '/api/report?from=1970-01-01&to=1970-01-01','/export.csv?from=1970-01-01&to=1970-01-01']:
                    with urllib.request.urlopen(urllib.request.Request(base+endpoint,headers={'Authorization':auth})) as response:
                        self.assertEqual(response.status,200)
                        self.assertEqual(response.headers['Cache-Control'],'no-store')
                        self.assertTrue(response.read())
            finally:
                server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
