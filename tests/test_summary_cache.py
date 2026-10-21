import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor as m


class SummaryCacheTests(unittest.TestCase):
    def test_expiration_and_bounded_history(self):
        now = [0]
        cache = m.SummaryCache(ttl=60, limit=2, clock=lambda: now[0])
        self.assertEqual(cache.get('a', lambda: b'first'), b'first')
        self.assertEqual(cache.get('a', lambda: b'unused'), b'first')
        now[0] = 60
        self.assertEqual(cache.get('a', lambda: b'fresh'), b'fresh')
        cache.get('b', lambda: b'b')
        cache.get('c', lambda: b'c')
        self.assertEqual(cache.get('a', lambda: b'rebuilt'), b'rebuilt')

    def test_failed_query_can_be_retried(self):
        cache = m.SummaryCache()
        with self.assertRaises(ValueError):
            cache.get('a', lambda: int('failure'))
        self.assertEqual(cache.get('a', lambda: b'ok'), b'ok')

    def test_concurrent_requests_share_one_calculation(self):
        cache = m.SummaryCache()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def compute():
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(5))
            return b'report'
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(cache.get, 'a', compute)
            self.assertTrue(entered.wait(5))
            rest = [pool.submit(cache.get, 'a', compute) for _ in range(3)]
            release.set()
            self.assertEqual([f.result(5) for f in [first, *rest]], [b'report']*4)
        self.assertEqual(len(calls), 1)

    def test_http_cache_invalidates_when_sampling_or_layout_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp)/'db')
            db = m.connect(path)
            def ingest(stamp, up):
                m.ingest(db, [dict(id='a', email='Demo', inbound='1', up=up, down=0, enabled=True)], stamp)
            ingest(60, 0)
            ingest(120, 10)
            server = m.ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
            server.cfg = dict(database=path, timezone='UTC', max_gap_seconds=150, web=dict(auth=False))
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}/api/report?from=1970-01-01&to=1970-01-01'
            def get():
                with urllib.request.urlopen(url) as response:
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    return json.load(response)
            try:
                with patch.object(m, 'report', wraps=m.report) as calculation:
                    self.assertEqual(get(), get())
                    self.assertEqual(calculation.call_count, 1)
                    ingest(180, 30)
                    self.assertEqual(get()['clients'][0]['daily']['1970-01-01']['up'], 30)
                    self.assertEqual(calculation.call_count, 2)
                    with db:
                        db.execute("INSERT OR REPLACE INTO preferences VALUES('layout',?)", ('{"group_members":{"a":"work"}}',))
                    get()
                    self.assertEqual(calculation.call_count, 3)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
                db.close()


if __name__ == '__main__':
    unittest.main()
