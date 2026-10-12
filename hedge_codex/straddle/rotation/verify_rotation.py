"""Regression checks for expiry selection, non-overlap and the downloaded execution records."""
import importlib.util,json,math
from pathlib import Path
from datetime import datetime,timedelta
p=Path(__file__).parent
spec=importlib.util.spec_from_file_location('rotation',p/'rotation_backtest.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def q(premium,days,pct=8):return dict(premium=premium,pct=pct,score=premium/math.sqrt(days),cost=100*premium)
a=q(10,3);b=q(12.5,10)
assert mod.select({'near':a,'far':b},'ratio25',1.25) is b
assert mod.select({'near':a,'far':b},'ratio10',1.1) is a
assert mod.select({'near':a,'far':b},'sqrt',None) is b
expensive=q(12,10,13);assert mod.select({'near':a,'far':expensive},'ratio50',1.5) is a
assert mod.select({'far':b},'near',None) is None
assert mod.select({'far':b},'near',None,True) is b
assert mod.select({'near':q(11,3,13),'far':expensive},'sqrt',None) is None
if (p/'rotation_results.json').exists():
 d=json.loads((p/'rotation_results.json').read_text());mod.validate(d)
 for r in d['results']:
  for tr in r['trades']:
   for dec in [tr['decision']]:
    t=datetime.fromisoformat(dec['time'])
    for c in dec['candidates'].values():
     for leg,k in c['quote_times'].items():
      qt=datetime.fromisoformat(k);assert qt+timedelta(minutes=1)<=t and qt.date()==t.date();assert (t-qt).total_seconds()/60<=10
   assert tr['contract']['pct']<=12
 print('PASS: source timestamps for all entry comparisons and 12% selection limits')
print('PASS: near/far policy, Friday exclusion, ratio boundaries, time score and all-expensive skips')
if (p/'rotation_results.json').exists():
 from zoneinfo import ZoneInfo
 end=d['end'];ET=ZoneInfo('America/New_York');memo={}
 def bars(ticker):
  if ticker not in memo:
   rows=json.loads((p/'rotation_cache'/(ticker.replace(':','_')+'_minute_'+end+'.json')).read_text());memo[ticker]={datetime.fromtimestamp(x['t']/1000,ET).isoformat():x for x in rows if x.get('v',0)>0}
  return memo[ticker]
 stock=bars('SKHY')
 for result in d['results']:
  for tr in result['trades']:
   cm=bars(tr['contract']['call_ticker']);pm=bars(tr['contract']['put_ticker'])
   for leg,b in [('call',cm),('put',pm)]:
    assert tr['entry'][leg]==b[tr['entry']['time']]['o']
    if tr['status']=='模拟平仓':assert tr['exit'][leg]==b[tr['exit']['time']]['o']
   assert tr['entry']['stock']==stock[tr['entry']['time']]['o']
   if tr['status']=='模拟平仓':assert tr['exit']['stock']==stock[tr['exit']['time']]['o']
   chosen=mod.select(tr['decision']['candidates'],result['id'],result['ratio'],datetime.fromisoformat(tr['decision']['time']).weekday()==4)
   assert chosen['expiry']==tr['contract']['expiry'] and chosen['strike']==tr['contract']['strike']
   sig=tr['signal']
   if sig:
    assert sig['roi']+1e-9>=sig['target']
    rem=(datetime.fromisoformat(tr['contract']['expiry']).date()-datetime.fromisoformat(sig['time']).date()).days
    factor={0:.25,1:.5,2:.75}.get(rem,1)
    assert abs(sig['target']-(150 if sig['side']=='涨侧' else 10)*factor)<1e-9
 print('PASS: every entry/exit stock and option price matches raw minute bars; every tenor choice and expiry-relative target reconciles')
