# -*- coding: utf-8 -*-
from pathlib import Path
import json,math
from datetime import datetime,timedelta
import optimize_rotation_exits as opt
p=Path(__file__).parent
# Boundary tests: a Friday expiry means Tuesday / Wednesday deadlines; entry is disallowed at the cutoff.
engine=opt.Engine(None);r={'days':3,'clock':'10:00'}
assert engine.deadline('2026-10-09',r).isoformat()=='2026-10-06T10:00:00-04:00'
r={'days':2,'clock':'15:30'};assert engine.deadline('2026-10-09',r).isoformat()=='2026-10-07T15:30:00-04:00'
# A scheduled deadline fires even when neither leg has a fresh mark; a true fill is still required.
class FakeMarket:
 limit=datetime(2026,10,6,16,tzinfo=opt.ET)
 days={'2026-10-06':{'c':100}}
 def fill(self,q,t,entry=False):return dict(time=(t+timedelta(minutes=1)).isoformat(),call=1,put=1,stock=100,value=200)
fake=FakeMarket();en=opt.Engine(fake);en.quote=lambda c,t:None
q={'call_ticker':'C','put_ticker':'P','expiry':'2026-10-09','strike':100}
e={'time':'2026-10-06T09:50:00-04:00','stock':100,'value':300}
r={'days':3,'clock':'10:00','up':150,'down':10,'stop':35}
out=en.closing(q,e,r);assert out['signal']['time']=='2026-10-06T10:00:00-04:00' and out['signal']['reason']=='到期前强制平仓'
en.quote=lambda c,t:{'stock':99,'cost':100}
out=en.closing(q,e,r);assert out['signal']['reason']=='到期前强制平仓' # priority over simultaneous loss trigger
print('PASS: scheduled exit without a fresh quote and priority over stop/target')
if not (p/'exit_optimization_results.json').exists():print('PASS: deadline boundaries');raise SystemExit()
d=json.loads((p/'exit_optimization_results.json').read_text());market=opt.core.Market(True,d['end']);engine=opt.Engine(market)
for result in d['results']:
 prev=None;r=result['rule'];total=0
 for tr in result['trades']:
  e,x,q=tr['entry'],tr['exit'],tr['contract'];et=datetime.fromisoformat(e['time']);xt=datetime.fromisoformat(x['time']);deadline=engine.deadline(q['expiry'],r)
  assert prev is None or et>prev;prev=xt
  assert et>datetime.fromisoformat(tr['decision']['time']);assert xt<=market.limit
  assert e['value']/(e['stock']*100)<=.12+1e-12 and q['pct']<=12
  if deadline:assert et<deadline
  decision_time=datetime.fromisoformat(tr['decision']['time'])
  eligible=[c for c in tr['decision']['candidates'].values() if c['pct']<=12 and (engine.deadline(c['expiry'],r) is None or decision_time<engine.deadline(c['expiry'],r))]
  choice=min(eligible,key=lambda c:(c['score'],c['cost']));assert (choice['expiry'],choice['strike'])==(q['expiry'],q['strike'])
  assert abs(tr['gross']-x['value']+e['value'])<1e-7
  assert abs(tr['gross']-tr['call_pnl']-tr['put_pnl'])<1e-7;total+=tr['gross']
  for leg in ['call','put']:
   b=market.bars(q[leg+'_ticker']);assert b[et]['o']==e[leg]
   if tr['status']=='模拟平仓':assert b[xt]['o']==x[leg]
  assert market.stock[et]['o']==e['stock']
  if tr['status']=='模拟平仓':
   assert market.stock[xt]['o']==x['stock'];sig=tr['signal'];st=datetime.fromisoformat(sig['time']);assert xt>=st+timedelta(minutes=1)
   if sig['reason']=='到期前强制平仓':assert deadline is not None and st>=deadline
   elif sig['reason']=='组合止损':assert r['stop'] is not None and sig['roi']<=-r['stop']
   else:assert sig['roi']>=sig['target']
  for c in tr['decision']['candidates'].values():
   for k in c['quote_times'].values():assert datetime.fromisoformat(k)+timedelta(minutes=1)<=datetime.fromisoformat(tr['decision']['time'])
 assert result['stats']['forced']==sum(t['status']=='模拟平仓' and bool(t['signal']) and t['signal']['reason']=='到期前强制平仓' for t in result['trades'])
 assert abs(total-result['stats']['total'])<1e-7
 assert abs(result['stats']['total']-result['stats']['realized']-result['stats']['floating'])<1e-7
base=next(r for r in d['results'] if r['rule']['id']=='E00');assert abs(base['stats']['total']-2373)<1e-6
assert d['best']==max(d['results'],key=lambda r:(r['stats']['total'],-r['stats']['drawdown']))['rule']['id']
print('PASS:',len(d['results']),'rules; baseline reproduction, causal data, no overlap, raw buy/sell prices, forced-exit eligibility, targets/stops and P&L reconciliation')
