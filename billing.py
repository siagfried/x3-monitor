"""Manual monthly allowance, accumulated independently of history retention."""
import calendar
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import time

GB = 1024**3


def save(db, state):
    db.execute("INSERT OR REPLACE INTO preferences VALUES('manual_billing',?)",(json.dumps(state),))


def load(db, tz, now):
    row=db.execute("SELECT value FROM preferences WHERE name='manual_billing'").fetchone()
    if row:
        state=json.loads(row[0])
    else:
        current=dt.datetime.fromtimestamp(now,tz)
        reset=current.replace(day=8,hour=0,minute=0,second=0,microsecond=0)
        if reset.timestamp()<=now:
            year,month=divmod(current.year*12+current.month,12)
            reset=reset.replace(year=year,month=month+1)
        state=dict(used_bytes=0,total_bytes=1000*GB,next_reset_ts=int(reset.timestamp()),
                   reset_day=8,baseline_ts=now,last_sample=0)
    while state['next_reset_ts']<=now:
        previous=dt.datetime.fromtimestamp(state['next_reset_ts'],tz)
        state['cycle_start']=state['next_reset_ts']
        year,month=divmod(previous.year*12+previous.month,12)
        following=previous.replace(year=year,month=month+1,day=min(state['reset_day'],calendar.monthrange(year,month+1)[1]))
        state['next_reset_ts']=int(following.timestamp())
        state['used_bytes']=0
    return state


def account(db, tz, now):
    state=load(db,tz,now)
    if now>state['last_sample']:
        begin=max(state['baseline_ts'],state.get('cycle_start',0))
        row=db.execute('SELECT COALESCE(SUM((up+down)*1.0*(end-MAX(start,?))/(end-start)),0) FROM samples WHERE end=? AND end>start AND end>?', (begin,now,begin)).fetchone()
        state['used_bytes']+=row[0]
        state['last_sample']=now
    save(db,state)


def status(db,tz,now=None):
    now=int(time.time()) if now is None else now
    with db:
        db.execute('BEGIN IMMEDIATE')
        state=load(db,tz,now)
        save(db,state)
    reset=dt.datetime.fromtimestamp(state['next_reset_ts'],tz)
    return dict(mode='manual',fresh=True,ok=True,info=dict(
        used_gb=state['used_bytes']/GB,total_gb=state['total_bytes']/GB,
        remaining_gb=max(0,state['total_bytes']-state['used_bytes'])/GB,
        next_reset_ts=state['next_reset_ts'],next_reset=reset.strftime('%Y-%m-%d'),
        next_reset_time=reset.strftime('%Y-%m-%d %H:%M:%S'),timezone=str(tz),ips=[]))


def configure(db,value,tz,now=None):
    now=int(time.time()) if now is None else now
    def amount(key):
        try:
            number=Decimal(str(value[key]))
            if not number.is_finite() or number<0 or number>Decimal('1000000000'):
                raise ValueError('invalid amount')
            return int(number*GB)
        except (InvalidOperation,TypeError):
            raise ValueError('invalid amount') from None
    used,total=amount('used_gb'),amount('total_gb')
    if total<=0:
        raise ValueError('total must be positive')
    reset=dt.datetime.strptime(value['next_reset'],'%Y-%m-%dT%H:%M').replace(tzinfo=tz)
    timestamp=int(reset.timestamp())
    if not now<timestamp<=now+366*86400 or dt.datetime.fromtimestamp(timestamp,tz).replace(tzinfo=None)!=reset.replace(tzinfo=None):
        raise ValueError('invalid future reset time')
    with db:
        db.execute('BEGIN IMMEDIATE')
        save(db,dict(used_bytes=used,total_bytes=total,next_reset_ts=timestamp,
                     reset_day=reset.day,baseline_ts=now,last_sample=0))
