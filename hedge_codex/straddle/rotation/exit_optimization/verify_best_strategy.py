# -*- coding: utf-8 -*-
import json,sys,math
from pathlib import Path
from datetime import datetime,timedelta
p=Path(__file__).parent;sys.path.insert(0,str(p));import refresh_best_strategy as refresh
old=json.loads((p/'exit_optimization_results.json').read_text());latest=json.loads((p/'best_strategy_latest.json').read_text());assert latest['selection_end']==old['end'] and latest['selected_rule_id']==old['best']
selected=next(r for r in old['results'] if r['rule']['id']==old['best']);r=latest['result'];assert selected['rule']==r['rule'];market=refresh.IncrementalMarket(True,latest['data_end']);prev=None
def source_bars(ticker):
 import re
 files=[f for f in (p/'market_cache').glob(ticker.replace(':','_')+'_minute_*.json') if re.search(r'_minute_\d{4}-\d{2}-\d{2}\.json$',f.name)]
 assert files,ticker
 rows=json.loads(sorted(files)[-1].read_text());return {datetime.fromtimestamp(b['t']/1000,refresh.core.ET):b for b in rows if b.get('v',0)>0 and datetime.fromtimestamp(b['t']/1000,refresh.core.ET).hour>=9 and datetime.fromtimestamp(b['t']/1000,refresh.core.ET).hour<16}
for tr in r['trades']:
 e,x,q=tr['entry'],tr['exit'],tr['contract'];et=datetime.fromisoformat(e['time']);xt=datetime.fromisoformat(x['time']);assert prev is None or et>prev;prev=xt;assert xt<=market.limit
 assert abs(tr['gross']-x['value']+e['value'])<1e-7 and abs(tr['gross']-tr['call_pnl']-tr['put_pnl'])<1e-7
 assert e['value']/(100*e['stock'])<=.12+1e-12
 for leg in ['call','put']:
  b=source_bars(q[leg+'_ticker'])
  if e.get('price_basis')=='latest_same_day_trade_proxy':
   k=max(k for k in b if k.date()==et.date() and k<=et-timedelta(minutes=1));assert b[k]['c']==e[leg] and k.isoformat()==e['quote_times'][leg] and (et-k).total_seconds()/60==e['ages'][leg]
  else:assert b[et]['o']==e[leg]
  if tr['status']=='模拟平仓':assert b[xt]['o']==x[leg]
  if tr['status']=='仍持仓估值':
   assert xt.date().isoformat()==latest['data_end']
   k=max(t for t in b if t.date()==xt.date() and t<xt);assert b[k]['c']==x[leg] and (xt-k).total_seconds()/60==x['ages'][leg]
 assert market.stock[et]['o']==e['stock']
 if tr['status']=='模拟平仓':assert market.stock[xt]['o']==x['stock'] and xt>=datetime.fromisoformat(tr['signal']['time'])+timedelta(minutes=1)
for a,b in zip(selected['trades'],r['trades']):
 if a['status']!='仍持仓估值':assert a==b
 assert a['entry']==b['entry']
assert abs(sum(t['gross'] for t in r['trades'])-r['stats']['total'])<1e-7
assert abs(r['stats']['realized']+r['stats']['floating']-r['stats']['total'])<1e-7
print('PASS: fixed selected rule, historical closed trades unchanged, source prices, latest mark ages, chronological positions and profit totals')
