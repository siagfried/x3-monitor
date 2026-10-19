import base64
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import billing as b
import configure as c
import monitor as m

TZ=m.ZoneInfo('UTC')
def stamp(text):return int(dt.datetime.fromisoformat(text).replace(tzinfo=TZ).timestamp())
def row(n):return dict(id='1:a',email='Demo',inbound='1',up=n,down=0,enabled=True)


class Manual(unittest.TestCase):
    def setUp(self):self.db=m.connect(':memory:')
    def tearDown(self):self.db.close()
    def setup(self,now,reset,used='10',total='1000'):
        b.configure(self.db,dict(used_gb=used,total_gb=total,next_reset=reset),TZ,now)

    def test_baseline_adds_samples_without_duplicates_and_survives_retention(self):
        now=stamp('2026-01-01T00:00');self.setup(now,'2026-02-01T00:00')
        m.ingest(self.db,[row(0)],now,billing_tz=TZ)
        m.ingest(self.db,[row(b.GB)],now+60,billing_tz=TZ)
        m.ingest(self.db,[row(b.GB)],now+60,billing_tz=TZ)
        self.assertEqual(b.status(self.db,TZ,now+60)['info']['used_gb'],11)
        with self.db:self.db.execute('DELETE FROM samples')
        self.assertEqual(b.status(self.db,TZ,now+60)['info']['used_gb'],11)

    def test_mid_sample_edit_only_adds_traffic_after_edit(self):
        now=stamp('2026-01-01T00:00')
        m.ingest(self.db,[row(0)],now)
        self.setup(now+30,'2026-02-01T00:00')
        m.ingest(self.db,[row(b.GB)],now+60,billing_tz=TZ)
        self.assertEqual(b.status(self.db,TZ,now+60)['info']['used_gb'],10.5)

    def test_reset_crossing_and_short_month_restore_original_day(self):
        reset=stamp('2026-01-31T12:30');self.setup(reset-30,'2026-01-31T12:30')
        m.ingest(self.db,[row(0)],reset-30,billing_tz=TZ)
        # Status may reset before a sample arrives; the overlap must still count.
        b.status(self.db,TZ,reset)
        m.ingest(self.db,[row(b.GB)],reset+30,billing_tz=TZ)
        info=b.status(self.db,TZ,reset+30)['info']
        self.assertEqual(info['used_gb'],0.5)
        self.assertEqual(info['next_reset_time'],'2026-02-28 12:30:00')
        info=b.status(self.db,TZ,stamp('2026-02-28T12:30'))['info']
        self.assertEqual(info['next_reset_time'],'2026-03-31 12:30:00')
        self.assertEqual(info['used_gb'],0)

    def test_invalid_amounts_and_past_time_do_not_overwrite(self):
        now=stamp('2026-01-01T00:00');self.setup(now,'2026-02-01T00:00')
        for amount in ('NaN','Infinity','-1','1000000001'):
            with self.assertRaises(ValueError):self.setup(now,'2026-02-01T00:00',used=amount)
        with self.assertRaises(ValueError):self.setup(now,'2025-01-01T00:00')
        self.assertEqual(b.status(self.db,TZ,now)['info']['used_gb'],10)

    def test_non_tailnet_manual_config_and_authentication_guards(self):
        cfg=c.make_config('','','','http://127.0.0.1:2053/','admin','panelpass',network='proxy',origin='https://monitor.example.test',web_username='admin',web_password='x'*20)
        self.assertFalse(cfg['installer']['manage_serve'])
        self.assertFalse(cfg['provider']['api_key'])
        with self.assertRaises(ValueError):
            c.make_config('','','','http://127.0.0.1/','admin','p',network='proxy',origin='https://monitor.example.test')
        with unittest.mock.patch.object(c,'tailnet',side_effect=AssertionError('not required')):
            self.assertIsNone(c.preflight(cfg))

    def test_public_post_requires_auth_and_api_mode_rejects_manual_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'db');db=m.connect(path);db.close()
            server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
            origin=f'http://127.0.0.1:{server.server_port}'
            server.cfg=dict(database=path,timezone='UTC',max_gap_seconds=150,web=dict(auth=True,username='admin',password='x'*20,public_origin=origin))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            payload=json.dumps(dict(used_gb=12,total_gb=100,next_reset=(dt.datetime.now(TZ)+dt.timedelta(days=20)).strftime('%Y-%m-%dT%H:%M'))).encode()
            try:
                request=urllib.request.Request(origin+'/api/billing',data=payload,headers={'Origin':origin})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,401)
                request.add_header('Authorization','Basic '+base64.b64encode(b'admin:'+b'x'*20).decode())
                with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
                server.cfg['provider']={'api_key':'TEST'}
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,409)
            finally:server.shutdown();thread.join();server.server_close()


if __name__=='__main__':unittest.main()
