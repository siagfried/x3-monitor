"""KiwiVM read-only polling. The API key is never included in returned state."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import re
import datetime as dt
from decimal import Decimal
import json
import os
import shutil
from pathlib import Path
import time
import urllib.parse
import urllib.request

ENDPOINT = 'https://api.64clouds.com/v1/getServiceInfo'
READ_CALLS = frozenset(('getServiceInfo', 'getAuditLog', 'backup/list', 'snapshot/list', 'getSuspensionDetails', 'getPolicyViolations'))
DETAIL_CALLS = {'audit':'getAuditLog', 'backups':'backup/list', 'snapshots':'snapshot/list', 'suspensions':'getSuspensionDetails', 'violations':'getPolicyViolations'}
GB = 1024 ** 3  # KiwiVM labels binary gigabytes as GB.


def normalize(raw):
    if raw.get('error') != 0:
        raise ValueError('provider rejected query')
    multiplier = Decimal(str(raw.get('monthly_data_multiplier', 1)))
    total = Decimal(str(raw['plan_monthly_data'])) * multiplier
    used = Decimal(str(raw['data_counter'])) * multiplier
    if not all(x.is_finite() and x >= 0 for x in (multiplier, total, used)) or multiplier == 0:
        raise ValueError('invalid provider traffic counters')
    reset = int(raw['data_next_reset'])
    if reset <= 0:
        raise ValueError('invalid reset timestamp')
    suspended = raw.get('suspended', False)
    if isinstance(suspended, str):
        suspended = suspended.lower() in ('1', 'true', 'yes')
    clean = lambda value: str(value or '')[:180]
    places = []
    for key in ('node_location', 'node_datacenter', 'node_location_id'):
        value = clean(raw.get(key))
        if value and value not in places:
            places.append(value)
    ips = raw.get('ip_addresses', [])
    if not isinstance(ips, list):
        raise ValueError('invalid IP list')
    return dict(plan=clean(raw.get('plan')), location=' · '.join(places),
                ips=[clean(x) for x in ips[:16]], suspended=bool(suspended),
                policy_violation=raw.get('policy_violation') in (True,1,'1','true'),
                used_gb=float(used/GB), total_gb=float(total/GB), remaining_gb=float(max(Decimal(0),total-used)/GB),
                next_reset_ts=reset, multiplier=float(multiplier))


def query(cfg, name, opener=None):
    if name not in READ_CALLS:
        raise ValueError('unsupported provider query')
    if opener is None:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    body = urllib.parse.urlencode({'veid': cfg['veid'], 'api_key': cfg['api_key']}).encode()
    request = urllib.request.Request('https://api.64clouds.com/v1/'+name, data=body,
        headers={'Accept':'application/json', 'User-Agent':'X3Monitor/2.0'})
    with opener.open(request, timeout=20) as response:
        raw = response.read(1024*1024 + 1)
    if len(raw) > 1024*1024:
        raise ValueError('provider response too large')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('error') != 0:
        raise ValueError('provider rejected query')
    return value


def fetch(cfg, opener=None):
    return normalize(query(cfg, 'getServiceInfo', opener))


def poll(db, cfg, now=None, fetcher=None):
    now = int(time.time()) if now is None else now
    row = db.execute("SELECT value FROM preferences WHERE name='provider_cache'").fetchone()
    cache = json.loads(row[0]) if row else {}
    try:
        info = (fetcher or fetch)(cfg)
        cache = dict(ok=True, last_attempt=now, last_success=now, info=info)
    except Exception as exc:
        # Exception text and raw responses may contain account information.
        cache.update(ok=False, last_attempt=now, error=type(exc).__name__)
    with db:
        db.execute("INSERT OR REPLACE INTO preferences VALUES('provider_cache',?)", (json.dumps(cache),))
    return cache['ok']


def system_metrics():
    result = dict(cpu_cores=os.cpu_count(), load=None, memory_available_bytes=None, memory_total_bytes=None,
                  disk_used_bytes=None, disk_total_bytes=None)
    try:
        result['load'] = list(os.getloadavg())
    except (AttributeError, OSError):
        pass
    try:
        memory = {line.split(':')[0]: int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
        result.update(memory_available_bytes=memory.get('MemAvailable'), memory_total_bytes=memory.get('MemTotal'))
    except (OSError, ValueError, IndexError):
        pass
    try:
        disk = shutil.disk_usage('/')
        result.update(disk_used_bytes=disk.used, disk_total_bytes=disk.total)
    except OSError:
        pass
    return result


def status(db, tz, now=None, uptime_reader=None):
    now = int(time.time()) if now is None else now
    row = db.execute("SELECT value FROM preferences WHERE name='provider_cache'").fetchone()
    value = json.loads(row[0]) if row else dict(ok=False)
    value['fresh'] = bool(value.get('ok') and now-value.get('last_success',0) <= 180)
    info = value.get('info')
    if info:
        reset = dt.datetime.fromtimestamp(info['next_reset_ts'], tz)
        value = dict(value, info=dict(info, next_reset=reset.strftime('%Y-%m-%d'),
                                     next_reset_time=reset.strftime('%Y-%m-%d %H:%M:%S'), timezone=str(tz)))
    try:
        value['uptime_seconds'] = int(float((uptime_reader or (lambda: Path('/proc/uptime').read_text()))().split()[0]))
    except (OSError, ValueError, IndexError):
        value['uptime_seconds'] = None
    row = db.execute("SELECT value FROM preferences WHERE name='provider_details'").fetchone()
    value['details'] = json.loads(row[0]) if row else {}
    for section in value['details'].values():
        section['fresh'] = bool(section.get('ok') and now-section.get('last_success',0) <= 180)
    value['system'] = system_metrics()
    return value


def detail_text(value, cfg, limit=1000):
    text = str(value or '')
    for secret in (cfg.get('api_key'),):
        if secret:
            text = text.replace(str(secret), '[已隐藏]')
    text = re.sub(r'https?://[^\s<>]+', '[链接已隐藏]', text, flags=re.I)
    text = re.sub(r'private_[A-Za-z0-9_]+', '[已隐藏]', text)
    return text[:limit]


def normalize_details(kind, raw, cfg, now):
    if not isinstance(raw, dict) or raw.get('error') != 0:
        raise ValueError('provider rejected query')
    def number(v):
        try:
            return max(0, int(v))
        except (ValueError, TypeError, OverflowError):
            return 0
    def records(value):
        if isinstance(value, dict):
            return list(value.values())
        if isinstance(value, list):
            return value
        raise ValueError('invalid provider records')
    def recent(items):
        return [x for x in items if not x.get('timestamp') or x['timestamp'] >= now-365*86400]
    if kind == 'audit':
        items = []
        for item in records(raw.get('log_entries', [])):
            if not isinstance(item, dict):
                continue
            try:
                ip = str(ipaddress.IPv4Address(item.get('requestor_ipv4', 0)))
            except (ValueError, TypeError):
                ip = ''
            items.append(dict(timestamp=number(item.get('timestamp')), summary=detail_text(item.get('summary'),cfg), ip=ip))
        return dict(items=sorted(recent(items),key=lambda x:x['timestamp'],reverse=True)[:50])
    if kind in ('backups', 'snapshots'):
        items = []
        for item in records(raw.get(kind, [])):
            if not isinstance(item, dict):
                continue
            timestamp = number(item.get('timestamp'))
            items.append(dict(timestamp=timestamp,size_bytes=number(item.get('size')),
                              description=detail_text(item.get('description'),cfg,180),os=detail_text(item.get('os'),cfg,80),
                              permanent=item.get('sticky') in (True,1,'1'),purges_in=number(item.get('purgesIn'))))
        return dict(items=sorted(recent(items),key=lambda x:x['timestamp'],reverse=True)[:20])
    if kind in ('suspensions', 'violations'):
        items = []
        evidence = raw.get('evidence', {})
        for item in records(raw.get('suspensions' if kind=='suspensions' else 'policy_violations', [])):
            if not isinstance(item, dict):
                continue
            record_id = number(item.get('record_id'))
            text = item.get('evidence_data')
            if not text and isinstance(evidence, dict):
                text = evidence.get(str(item.get('evidence_record_id')), '')
            items.append(dict(record_id=record_id,timestamp=number(item.get('timestamp')),suspend_at=number(item.get('suspend_at')),
                              reason=detail_text(item.get('flag'),cfg,180),evidence=detail_text(text,cfg,2048),
                              abuse_points=number(item.get('abuse_points'))))
        return dict(items=sorted(recent(items),key=lambda x:x['timestamp'],reverse=True)[:20],
                    suspension_count=number(raw.get('suspension_count')),total_abuse_points=number(raw.get('total_abuse_points')),
                    max_abuse_points=number(raw.get('max_abuse_points')))
    raise ValueError('unsupported provider section')


def poll_details(db, cfg, now=None, query_fn=None):
    now = int(time.time()) if now is None else now
    row = db.execute("SELECT value FROM preferences WHERE name='provider_details'").fetchone()
    cache = json.loads(row[0]) if row else {}
    def load(pair):
        kind, name = pair
        previous = cache.get(kind, {})
        try:
            data = normalize_details(kind,(query_fn or query)(cfg,name),cfg,now)
            return kind,dict(ok=True,last_attempt=now,last_success=now,data=data)
        except Exception:
            # Keep sanitized prior results; never expose raw errors or API responses.
            data = previous.get('data')
            if data:
                data = dict(data,items=[x for x in data.get('items',[]) if not x.get('timestamp') or x['timestamp'] >= now-365*86400])
            return kind,dict(previous,ok=False,last_attempt=now,**({'data':data} if data else {}))
    with ThreadPoolExecutor(max_workers=5) as pool:
        result = dict(pool.map(load,DETAIL_CALLS.items()))
    with db:
        db.execute("INSERT OR REPLACE INTO preferences VALUES('provider_details',?)",(json.dumps(result),))
    return all(section['ok'] for section in result.values())
