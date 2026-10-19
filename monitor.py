#!/usr/bin/env python3
"""X3 Monitor: read-only traffic sampling, stdlib only, Python >=3.10."""
import argparse
import base64
import csv
from contextlib import closing
import datetime as dt
import hashlib
import hmac
import http.cookiejar
import http.client
import socket
import io
import json
import logging
import signal
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import provider
from push_support import preferences, valid_subscription, activity_events, enqueue, deliver_once


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY, email TEXT, inbound TEXT,
      seen INTEGER, up INTEGER, down INTEGER, enabled INTEGER);
    CREATE TABLE IF NOT EXISTS samples(client TEXT, start INTEGER, end INTEGER,
      state TEXT, up INTEGER, down INTEGER, note TEXT,
      PRIMARY KEY(client,end));
    CREATE INDEX IF NOT EXISTS samples_time ON samples(end);
    CREATE TABLE IF NOT EXISTS health(ts INTEGER PRIMARY KEY, ok INTEGER, code TEXT);
    CREATE TABLE IF NOT EXISTS preferences(name TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS push_subscriptions(endpoint TEXT PRIMARY KEY,subscription TEXT NOT NULL,created INTEGER);
    CREATE TABLE IF NOT EXISTS activity_events(client TEXT,ts INTEGER,PRIMARY KEY(client,ts));
    CREATE TABLE IF NOT EXISTS push_outbox(id INTEGER PRIMARY KEY,endpoint TEXT,subscription TEXT,payload TEXT,attempts INTEGER,next_attempt INTEGER);

    ''')
    return db


class Panel:
    def __init__(self, cfg):
        self.c = cfg
        self.base = cfg['url'].rstrip('/') + '/'
        self.csrf = ''
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
            raise ValueError('invalid panel URL')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('remote panel requires HTTPS')
        context = ssl.create_default_context(cafile=cfg.get('ca_file') or None)
        connect_host = cfg.get('connect_host')
        if connect_host and (parsed.scheme != 'https' or connect_host not in ('127.0.0.1', '::1')):
            raise ValueError('connect_host requires HTTPS and a loopback address')
        class LocalHTTPSConnection(http.client.HTTPSConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if connect_host:
                    self._create_connection = lambda address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None: socket.create_connection((connect_host, address[1]), timeout, source_address)
        class VerifiedHTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(LocalHTTPSConnection, req, context=self._context)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            VerifiedHTTPSHandler(context=context))

    def request(self, path, data=None):
        origin = urllib.parse.urlsplit(self.base)
        headers = {'Accept': 'application/json', 'Origin': origin.scheme + '://' + origin.netloc,
                   'Referer': self.base}
        if self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        if self.c.get('token'):
            headers['Authorization'] = 'Bearer ' + self.c['token']
        if data is not None:
            data = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(self.base + path.lstrip('/'), data=data, headers=headers)
        with self.opener.open(req, timeout=self.c.get('timeout', 15)) as r:
            raw = r.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('response too large')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('success') is not True:
            raise ValueError('API rejected request')
        return result.get('obj')

    def prepare_login(self):
        class CSRFParser(HTMLParser):
            token = ''
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'meta' and attrs.get('name') == 'csrf-token':
                    self.token = attrs.get('content', '')
        with self.opener.open(self.base, timeout=self.c.get('timeout', 15)) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('login page too large')
        parser = CSRFParser()
        parser.feed(raw.decode('utf-8', errors='replace'))
        self.csrf = parser.token

    def fetch(self):
        try:
            result = self.request(self.c.get('list_path', 'panel/api/inbounds/list'))
        except (urllib.error.HTTPError, ValueError):
            if self.c.get('token'):
                raise
            self.prepare_login()
            self.request('login', {'username': self.c['username'], 'password': self.c['password'],
                                   'twoFactorCode': self.c.get('two_factor_code', '')})
            result = self.request(self.c.get('list_path', 'panel/api/inbounds/list'))
        return normalize(result)


def normalize(inbounds):
    if not isinstance(inbounds, list):
        raise ValueError('inbounds must be a list')
    rows = []
    for inbound in inbounds:
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings or '{}')
        configured = {c['email']: c for c in settings.get('clients', []) if c.get('email')}
        stats = inbound.get('clientStats')
        if stats is None:
            raise ValueError('clientStats missing; incompatible API')
        found = set()
        for stat in stats:
            email = stat.get('email')
            if not email or email in found:
                raise ValueError('missing or duplicate client email')
            found.add(email)
            client = configured.get(email, {})
            key = str(inbound['id']) + ':' + email
            rows.append(dict(id=key, email=email, inbound=str(inbound['id']),
                             up=max(0, int(stat['up'])), down=max(0, int(stat['down'])),
                             enabled=bool(inbound.get('enable', True) and client.get('enable', stat.get('enable', True)))))
        # A configured client without counters is unknown, never fabricated as zero.
        for email in configured.keys() - found:
            rows.append(dict(id=str(inbound['id']) + ':' + email, email=email,
                             inbound=str(inbound['id']), up=None, down=None, enabled=False))
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate identity')
    return rows


def ingest(db, rows, now, interval=60, gap=150):
    with db:
        for row in rows:
            old = db.execute('SELECT * FROM clients WHERE id=?', (row['id'],)).fetchone()
            start, state, up, down, note = now, 'unknown', 0, 0, 'baseline'
            valid = row['up'] is not None and row['down'] is not None
            if old and now > old['seen']:
                start = old['seen']
                if valid and old['up'] is not None:
                    reset = row['up'] < old['up'] or row['down'] < old['down']
                    if not reset:
                        up, down = row['up'] - old['up'], row['down'] - old['down']
                    failure = db.execute('SELECT 1 FROM health WHERE ts>=? AND ts<=? AND ok=0 LIMIT 1', (start, now)).fetchone()
                    if now-start > gap or failure:
                        note = 'gap_reset' if reset else 'gap'
                    elif reset:
                        note = 'counter_reset'
                    elif not row['enabled']:
                        state, note = 'disabled', ''
                    else:
                        state, note = ('active' if up+down > 0 else 'idle'), ''
                else:
                    note = 'missing_counters'
            db.execute('INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?,?)',
                       (row['id'], start, now, state, up, down, note))
            db.execute('INSERT OR REPLACE INTO clients VALUES(?,?,?,?,?,?,?)',
                       (row['id'], row['email'], row['inbound'], now, row['up'], row['down'], row['enabled']))
        activity_events(db, now)
        db.execute('INSERT OR REPLACE INTO health VALUES(?,1,?)', (now, 'ok'))


def date_range(query, tz):
    today = dt.datetime.now(tz).date()
    end_date = dt.date.fromisoformat(query.get('to', [str(today)])[0])
    begin = dt.date.fromisoformat(query.get('from', [str(end_date)])[0])
    if not 0 <= (end_date-begin).days <= 366:
        raise ValueError('date range must be 1..367 days')
    return int(dt.datetime.combine(begin, dt.time(), tz).timestamp()), int(dt.datetime.combine(end_date+dt.timedelta(days=1), dt.time(), tz).timestamp())


def report(db, begin, end, tz, now=None, stale=150):
    now = int(time.time()) if now is None else now
    clients = [dict(r) for r in db.execute('SELECT * FROM clients ORDER BY email')]
    health = db.execute('SELECT * FROM health ORDER BY ts DESC LIMIT 1').fetchone()
    for c in clients:
        latest = db.execute('SELECT state FROM samples WHERE client=? ORDER BY end DESC LIMIT 1', (c['id'],)).fetchone()
        c['status'] = latest['state'] if now-c['seen'] <= stale and health and health['ok'] else 'unknown'
        c['daily'], c['sessions'], c['timeline'] = {}, [], []
        session = None
        for r in db.execute('SELECT * FROM samples WHERE client=? AND end>? AND start<? ORDER BY end', (c['id'], begin, end)):
            a, b = max(begin, r['start']), min(end, r['end'])
            if b <= a:
                continue
            piece = dict(start=a, end=b, state=r['state'], note=r['note'], up=r['up']*(b-a)/(r['end']-r['start']), down=r['down']*(b-a)/(r['end']-r['start']))
            previous_piece = c['timeline'][-1] if c['timeline'] else None
            if previous_piece and previous_piece['end'] == a and previous_piece['state'] == piece['state'] and previous_piece['note'] == piece['note'] and dt.datetime.fromtimestamp(previous_piece['start'],tz).date() == dt.datetime.fromtimestamp(b-1,tz).date():
                previous_piece['end'] = b
                previous_piece['up'] += piece['up']
                previous_piece['down'] += piece['down']
            else:
                c['timeline'].append(piece)
            # Deltas spanning midnight/gaps are estimated proportionally by elapsed seconds.
            t = a
            while t < b:
                local = dt.datetime.fromtimestamp(t, tz)
                midnight = dt.datetime.combine(local.date()+dt.timedelta(days=1), dt.time(), tz)
                stop = min(b, int(midnight.timestamp()))
                day = c['daily'].setdefault(str(local.date()), dict(active_seconds=0, unknown_seconds=0, up=0, down=0))
                seconds = stop-t
                if r['state'] == 'active':
                    day['active_seconds'] += seconds
                if r['state'] == 'unknown':
                    day['unknown_seconds'] += seconds
                for field in ('up', 'down'):
                    day[field] += r[field] * seconds / (r['end']-r['start'])
                t = stop
            if r['state'] == 'active':
                if session and session['end'] == a:
                    session['end'] = b
                else:
                    session = dict(start=a, end=b)
                    c['sessions'].append(session)
            else:
                session = None
        for session in c['sessions']:
            session['seconds'] = session['end']-session['start']
        # Current unobserved tail is not counted as active time.
    days = []
    t = begin
    while t < end:
        local = dt.datetime.fromtimestamp(t, tz)
        stop = min(end, int(dt.datetime.combine(local.date()+dt.timedelta(days=1), dt.time(), tz).timestamp()))
        days.append(dict(date=str(local.date()), start=t, end=stop))
        t = stop
    return dict(now=now, health=dict(health) if health else None, clients=clients,
                timezone=str(tz), begin=begin, end=end, days=days, overview=aggregate_overview(clients))


def aggregate_overview(clients):
    value = dict(id='__overview__', email='总览', inbound='', status='idle', daily={}, timeline=[], sessions=[])
    events = {}
    for client in clients:
        if client['status'] == 'active':
            value['status'] = 'active'
        for date, daily in client['daily'].items():
            target = value['daily'].setdefault(date, dict(active_seconds=0, unknown_seconds=0, up=0, down=0))
            for key in target:
                target[key] += daily[key]
        for piece in client['timeline']:
            seconds = piece['end'] - piece['start']
            if seconds <= 0:
                continue
            delta = [int(piece['state']=='active'), int(piece['state']=='unknown'), piece['up']/seconds, piece['down']/seconds]
            for stamp, sign in [(piece['start'],1),(piece['end'],-1)]:
                acc = events.setdefault(stamp, [0,0,0,0])
                for i in range(4):
                    acc[i] += sign*delta[i]
    active = [0,0,0,0]
    previous = None
    for stamp in sorted(events):
        if previous is not None and stamp > previous:
            state = 'active' if active[0] else ('unknown' if active[1] else 'idle')
            piece = dict(start=previous, end=stamp, state=state, note='', up=max(0,active[2]*(stamp-previous)), down=max(0,active[3]*(stamp-previous)))
            timeline = value['timeline']
            if timeline and timeline[-1]['end'] == previous and timeline[-1]['state'] == state:
                timeline[-1]['end'] = stamp
                timeline[-1]['up'] += piece['up']
                timeline[-1]['down'] += piece['down']
            else:
                timeline.append(piece)
        for i in range(4):
            active[i] += events[stamp][i]
        previous = stamp
    value['totals'] = {key: sum(day[key] for day in value['daily'].values()) for key in ['active_seconds','up','down']}
    return value


def prune_history(db, days, now=None):
    if days <= 0:
        return
    cutoff = (int(time.time()) if now is None else now) - days*86400
    with db:
        db.execute('DELETE FROM samples WHERE end<=?', (cutoff,))
        db.execute('UPDATE samples SET up=up*1.0*(end-?)/(end-start),down=down*1.0*(end-?)/(end-start),start=? WHERE start<? AND end>?', (cutoff,cutoff,cutoff,cutoff,cutoff))
        db.execute('DELETE FROM health WHERE ts<?', (cutoff,))
        db.execute('DELETE FROM activity_events WHERE ts<?', (cutoff,))
        db.execute('DELETE FROM push_outbox WHERE next_attempt<?', (cutoff,))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # No query strings, identities or credentials in access logs.

    def do_GET(self):
        if self.server.cfg['web'].get('auth', True):
            expected = 'Basic ' + base64.b64encode((self.server.cfg['web']['username'] + ':' + self.server.cfg['web']['password']).encode()).decode()
            if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="X3 Monitor", charset="UTF-8"')
                self.end_headers()
                return
        url = urllib.parse.urlsplit(self.path)
        try:
            if url.path == '/':
                return self.reply(200, 'text/html; charset=utf-8', Path(__file__).with_name('dashboard.html').read_bytes())
            if url.path in ('/manifest.webmanifest', '/icon.svg'):
                kind = 'application/manifest+json' if url.path.endswith('webmanifest') else 'image/svg+xml'
                return self.reply(200, kind, Path(__file__).with_name(url.path[1:]).read_bytes())
            if url.path == '/sw.js':
                return self.reply(200, 'application/javascript', Path(__file__).with_name('sw.js').read_bytes())
            if url.path == '/api/config':
                with closing(connect(self.server.cfg['database'])) as db:
                    value = dict(preferences=preferences(db), panel_url=self.server.cfg.get('panel_link', ''),
                                 push_public_key=self.server.cfg.get('push', {}).get('public_key', ''),
                                 oldest_date=str((dt.datetime.now(ZoneInfo(self.server.cfg['timezone']))-dt.timedelta(days=self.server.cfg.get('retention_days',365))).date()))
                    row = db.execute("SELECT value FROM preferences WHERE name='push_delivery'").fetchone()
                    value['push_delivery'] = json.loads(row[0]) if row else None
                    value['provider'] = provider.status(db, ZoneInfo(self.server.cfg['timezone']))
                return self.reply(200, 'application/json', json.dumps(value).encode())
            if url.path not in ('/api/report', '/export.csv'):
                return self.reply(404, 'text/plain', b'Not found')
            tz = ZoneInfo(self.server.cfg['timezone'])
            begin, end = date_range(urllib.parse.parse_qs(url.query), tz)
            with closing(connect(self.server.cfg['database'])) as db:
                result = report(db, begin, end, tz, stale=self.server.cfg['max_gap_seconds'])
            if url.path == '/api/report':
                return self.reply(200, 'application/json', json.dumps(result).encode())
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['client', 'inbound', 'date', 'active_seconds', 'unknown_seconds', 'up_bytes_estimated', 'down_bytes_estimated'])
            for client in result['clients']:
                for day, values in client['daily'].items():
                    email = client['email']
                    if email.startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                        email = "'" + email
                    writer.writerow([email, client['inbound'], day, *[round(values[k]) for k in ('active_seconds','unknown_seconds','up','down')]])
            return self.reply(200, 'text/csv; charset=utf-8', ('\ufeff'+buf.getvalue()).encode())
        except (ValueError, KeyError):
            self.reply(400, 'text/plain', b'Invalid request')
        except Exception:
            self.reply(500, 'text/plain', b'Report unavailable')

    def do_POST(self):
        # Browser writes must originate from this exact Tailnet dashboard.
        if self.headers.get('Origin') != self.server.cfg['web'].get('public_origin'):
            return self.reply(403, 'text/plain', b'Origin rejected')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError('invalid body size')
            value = json.loads(self.rfile.read(size))
            path = urllib.parse.urlsplit(self.path).path
            now = int(time.time())
            with closing(connect(self.server.cfg['database'])) as db, db:
                if path == '/api/preferences':
                    known = {r[0] for r in db.execute('SELECT id FROM clients')}
                    for key in ['order', 'favorites']:
                        if not isinstance(value.get(key), list) or len(value[key]) != len(set(value[key])) or not set(value[key]) <= known:
                            raise ValueError('invalid preferences')
                    icons = value.get('icons', preferences(db).get('icons', {}))
                    if not isinstance(icons, dict) or not set(icons) <= known or any(v not in ('desktop','laptop','phone','router','server','board') for v in icons.values()):
                        raise ValueError('invalid device icons')
                    saved = {k: value[k] for k in ['order', 'favorites']}
                    saved['icons'] = icons
                    db.execute("INSERT OR REPLACE INTO preferences VALUES('layout',?)", (json.dumps(saved),))
                elif path == '/api/push/subscribe':
                    endpoint = valid_subscription(value)
                    if db.execute('SELECT count(*) FROM push_subscriptions').fetchone()[0] >= 32 and not db.execute('SELECT 1 FROM push_subscriptions WHERE endpoint=?', (endpoint,)).fetchone():
                        raise ValueError('subscription limit')
                    db.execute('INSERT OR REPLACE INTO push_subscriptions VALUES(?,?,?)', (endpoint, json.dumps(value), now))
                elif path == '/api/push/unsubscribe':
                    endpoint = value['endpoint']
                    db.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (endpoint,))
                    db.execute('DELETE FROM push_outbox WHERE endpoint=?', (endpoint,))
                elif path == '/api/push/test':
                    previous = db.execute("SELECT value FROM preferences WHERE name='last_push_test'").fetchone()
                    if previous and now-int(previous[0]) < 10:
                        return self.reply(429, 'text/plain', b'Please wait')
                    db.execute("INSERT OR REPLACE INTO preferences VALUES('last_push_test',?)", (str(now),))
                    if not db.execute('SELECT 1 FROM push_subscriptions WHERE endpoint=?', (value['endpoint'],)).fetchone():
                        raise ValueError('subscribe first')
                    enqueue(db, {'title': 'X3 Monitor 通知已就绪', 'body': '关注客户端开始活跃时会在这里提醒你。', 'tag': 'test', 'url': '/'}, now, value['endpoint'])
                else:
                    return self.reply(404, 'text/plain', b'Not found')
            return self.reply(200, 'application/json', b'{"ok":true}')
        except (ValueError, TypeError, KeyError):
            self.reply(400, 'text/plain', b'Invalid request')
        except Exception:
            self.reply(500, 'text/plain', b'Update unavailable')

    def reply(self, status, kind, body):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; worker-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        if kind.startswith('text/csv'):
            self.send_header('Content-Disposition', 'attachment; filename="x3-monitor.csv"')
        self.end_headers()
        self.wfile.write(body)


def validate(cfg):
    if cfg.get('interval_seconds') != 60:
        raise ValueError('interval_seconds must be 60')
    if not 60 < cfg['max_gap_seconds'] <= 300:
        raise ValueError('invalid max_gap_seconds')
    ZoneInfo(cfg['timezone'])
    if cfg['web'].get('auth', True) and (len(cfg['web'].get('password','')) < 16 or cfg['web']['password'].startswith('CHANGE')):
        raise ValueError('set web password, at least 16 characters')
    if cfg['web']['host'] not in ('127.0.0.1', '::1'):
        raise ValueError('web must bind loopback; use SSH tunnel or HTTPS reverse proxy')
    if not cfg['panel'].get('token') and not (cfg['panel'].get('username') and cfg['panel'].get('password')):
        raise ValueError('configure panel credentials')
    Panel(cfg['panel'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/opt/x3-monitor/config.json')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    validate(cfg)
    panel = Panel(cfg['panel'])
    if args.check:
        print('Configuration valid')
        return
    if args.probe:
        print('API compatible; clients:', len(panel.fetch()))
        return
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    stop = threading.Event()
    def collect():
        db = connect(cfg['database'])
        try:
            while not stop.is_set():
                started = time.monotonic()
                try:
                    rows = panel.fetch()
                    ingest(db, rows, int(time.time()), gap=cfg['max_gap_seconds'])
                except Exception as exc:
                    # Class only: remote API messages/URLs may contain secrets.
                    with db:
                        db.execute('INSERT OR REPLACE INTO health VALUES(?,0,?)', (int(time.time()), type(exc).__name__))
                    logging.warning('Collection failed (%s)', type(exc).__name__)
                prune_history(db, cfg.get('retention_days',365))
                stop.wait(max(1, 60-(time.monotonic()-started)))
        finally:
            db.close()
    def push_worker():
        with closing(connect(cfg['database'])) as db:
            while not stop.is_set():
                try:
                    worked = deliver_once(db, cfg['push'])
                except Exception as exc:
                    logging.warning('Push worker failed (%s)', type(exc).__name__)
                    worked = False
                stop.wait(0.2 if worked else 3)
    def provider_worker():
        failures = 0
        with closing(connect(cfg['database'])) as db:
            while not stop.is_set():
                ok = provider.poll(db, cfg['provider'])
                if not stop.is_set():
                    provider.poll_details(db, cfg['provider'])
                failures = 0 if ok else failures + 1
                stop.wait(60 if ok else min(900, 60 * 2**min(failures,4)))
    with closing(connect(cfg['database'])) as db:
        prune_history(db, cfg.get('retention_days',365))
    with closing(connect(cfg['database'])) as db:
        with db:
            db.execute('INSERT OR REPLACE INTO health VALUES(?,0,?)', (int(time.time()), 'starting'))
    server = ThreadingHTTPServer((cfg['web']['host'], cfg['web']['port']), Handler)
    server.cfg = cfg
    worker = threading.Thread(target=collect)
    worker.start()
    provider_thread = None
    if cfg.get('provider', {}).get('api_key'):
        provider_thread = threading.Thread(target=provider_worker)
        provider_thread.start()
    push_thread = None
    if cfg.get('push', {}).get('private_key'):
        push_thread = threading.Thread(target=push_worker)
        push_thread.start()
    def shutdown(*_):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        worker.join()
        if provider_thread:
            provider_thread.join()
        if push_thread:
            push_thread.join()


if __name__ == '__main__':
    main()
