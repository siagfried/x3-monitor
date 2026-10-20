"""Persistent browser push subscriptions and bounded delivery queue."""
import base64
import json
import time
from urllib.parse import urlsplit


def preferences(db):
    row = db.execute("SELECT value FROM preferences WHERE name='layout'").fetchone()
    value = json.loads(row[0]) if row else {'order': [], 'favorites': []}
    value.setdefault('icons', {})
    value.setdefault('groups', [])
    value.setdefault('group_members', {})
    value.setdefault('ungrouped_view', 2)
    return value


def validate_groups(groups, members, known):
    if not isinstance(groups, list) or len(groups)>64 or not isinstance(members, dict):
        raise ValueError('invalid groups')
    clean=[]
    ids=set()
    for group in groups:
        if not isinstance(group, dict):raise ValueError('invalid group')
        key, name=group.get('id'),group.get('name')
        if (not isinstance(key,str) or not 1<=len(key)<=64 or
            not all(c.isascii() and (c.isalnum() or c in '-_') for c in key) or key in ids or
            not isinstance(name,str) or not 1<=len(name.strip())<=40 or
            not isinstance(group.get('hidden',False),bool)):
            raise ValueError('invalid group')
        ids.add(key)
        view=group.get('view',0 if group.get('hidden',False) else 2)
        if type(view) is not int or view not in (0,1,2):raise ValueError('invalid group view')
        clean.append(dict(id=key,name=name.strip(),hidden=view!=2,view=view))
    if not set(members)<=known or any(not isinstance(value,str) or value not in ids for value in members.values()):
        raise ValueError('invalid group membership')
    return clean,dict(members)


def valid_subscription(value):
    endpoint = value.get('endpoint', '')
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ''
    allowed = host == 'fcm.googleapis.com' or any(host.endswith('.' + suffix) or host == suffix
        for suffix in ('push.services.mozilla.com', 'push.apple.com', 'notify.windows.com'))
    if parsed.scheme != 'https' or not allowed or parsed.username or parsed.port not in (None, 443) or len(endpoint) > 4096:
        raise ValueError('invalid push endpoint')
    keys = value.get('keys', {})
    for name, length in [('auth', 16), ('p256dh', 65)]:
        raw = base64.urlsafe_b64decode(keys.get(name, '') + '===')
        if len(raw) != length:
            raise ValueError('invalid push key')
    return endpoint


def enqueue(db, payload, now, endpoint=None):
    if endpoint:
        subscriptions = db.execute('SELECT endpoint,subscription FROM push_subscriptions WHERE endpoint=?', (endpoint,))
    else:
        subscriptions = db.execute('SELECT endpoint,subscription FROM push_subscriptions')
    for sub in subscriptions.fetchall():
        db.execute('INSERT INTO push_outbox(endpoint,subscription,payload,attempts,next_attempt) VALUES(?,?,?,0,?)',
                   (sub['endpoint'], sub['subscription'], json.dumps(payload), now))


def activity_events(db, now):
    favorite = set(preferences(db)['favorites'])
    if not favorite:
        return
    for row in db.execute("SELECT s.client,c.email,s.start FROM samples s JOIN clients c ON c.id=s.client WHERE s.end=? AND s.state='active'", (now,)).fetchall():
        if row['client'] not in favorite:
            continue
        previous = db.execute('SELECT state,end FROM samples WHERE client=? AND end<? ORDER BY end DESC LIMIT 1', (row['client'], now)).fetchone()
        if previous and previous['state'] == 'idle' and previous['end'] == row['start']:
            inserted = db.execute('INSERT OR IGNORE INTO activity_events(client,ts) VALUES(?,?)', (row['client'], now))
            if inserted.rowcount:
                enqueue(db, {'title': '关注客户端开始活跃', 'body': row['email'] + ' 刚刚出现流量活动',
                             'tag': 'activity-' + row['client'], 'url': '/', 'ts': now}, now)


def deliver_once(db, cfg, sender=None, now=None):
    now = int(time.time()) if now is None else now
    row = db.execute('SELECT * FROM push_outbox WHERE next_attempt<=? ORDER BY id LIMIT 1', (now,)).fetchone()
    if not row:
        return False
    if sender is None:
        from pywebpush import webpush
        sender = webpush
    try:
        sender(subscription_info=json.loads(row['subscription']), data=row['payload'],
               vapid_private_key=cfg['private_key'], vapid_claims={'sub': cfg['subject']},
               ttl=300, timeout=10)
        with db:
            db.execute('DELETE FROM push_outbox WHERE id=?', (row['id'],))
            db.execute("INSERT OR REPLACE INTO preferences VALUES('push_delivery',?)", (json.dumps({'ok': True, 'ts': now}),))
    except Exception as exc:
        code = getattr(exc, 'status_code', None)
        if code is None and getattr(exc, 'response', None) is not None:
            code = exc.response.status_code
        with db:
            if code in (404, 410):
                db.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (row['endpoint'],))
                db.execute('DELETE FROM push_outbox WHERE endpoint=?', (row['endpoint'],))
            elif row['attempts'] >= 2:
                db.execute('DELETE FROM push_outbox WHERE id=?', (row['id'],))
            else:
                db.execute('UPDATE push_outbox SET attempts=attempts+1,next_attempt=? WHERE id=?', (now + 30 * 2**row['attempts'], row['id']))
            db.execute("INSERT OR REPLACE INTO preferences VALUES('push_delivery',?)", (json.dumps({'ok': False, 'ts': now, 'code': code or type(exc).__name__}),))
    return True
