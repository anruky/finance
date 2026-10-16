# -*- coding: utf-8 -*-
"""Regression: stale prints remain candidates, no future/previous-day prices, causal proxy fill."""
import sys,json,copy
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).parent));import refresh_best_strategy as refresh
from entry_execution import EntryEngine,core
core.CACHE=Path(__file__).parent/'market_cache';m=refresh.IncrementalMarket(True,'2026-10-14');eng=EntryEngine(m)
r=json.loads((Path(__file__).parent/'best_strategy_latest.json').read_text())['result']['rule'];t=datetime(2026,10,14,14,10,tzinfo=core.ET)
qs,q,missing=eng.snapshot(t,r);assert not missing and set(qs)=={'near','far'} and q['expiry']=='2026-10-23';assert qs['far']['ages']['put']==15
assert qs['far']['score']<qs['near']['score']
dec,q,e=eng.opening(t,r);assert e['time']==(t+timedelta(minutes=1)).isoformat() and q['expiry']=='2026-10-23';assert e['ages']['put']==16 and abs(e['value']-1130)<.001
# Reject unavailable candidate data instead of silently buying the other expiry.
c=m.candidates(t)['far'];saved=m.maps[c['put']];m.maps[c['put']]={}
assert eng.snapshot(t,r)[1] is None and 'far' in eng.snapshot(t,r)[2]
# Neither a future bar nor yesterday's trade can stand in for an observed same-day price.
b=next(iter(saved.values()));m.maps[c['put']]={t+timedelta(minutes=1):dict(b,c=999),t-timedelta(days=1):dict(b,c=888)}
assert eng.snapshot(t,r)[1] is None
m.maps[c['put']]=saved
# A huge future trade cannot change the decision or fill at 14:11.
saved2=copy.deepcopy(saved);m.maps[c['put']][t+timedelta(minutes=2)]=dict(b,c=999)
assert eng.opening(t,r)[2]==e
m.maps[c['put']]=saved2
print('PASS: 15-minute and older print accepted; both expiry candidates compared; no same-minute trade requirement; no future/previous-day leakage; missing candidate never silently excluded')
