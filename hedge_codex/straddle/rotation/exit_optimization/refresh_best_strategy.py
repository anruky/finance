# -*- coding: utf-8 -*-
"""Refresh one previously selected rule. Never search or rank exit rules."""
from pathlib import Path
import sys,json,argparse
from datetime import datetime,timedelta,timezone
BASE=Path(__file__).resolve().parent
ROOT=BASE if (BASE/'exit_optimization_results.json').exists() else Path('/Users/gavinz/git/finance/hedge_codex/straddle/rotation/exit_optimization')
sys.path.insert(0,str(ROOT));import optimize_rotation_exits as opt
core=opt.core;core.CACHE=BASE/'market_cache'
class IncrementalMarket(core.Market):
 def __init__(self,offline=False,end=None):
  super().__init__(offline,end)
  if not (core.CACHE/('SKHY_minute_'+self.end+'.json')).exists():core.save(core.CACHE/('SKHY_minute_'+self.end+'.json'),list(self.stock.values()))
  if not (core.CACHE/('stock_day_'+self.end+'.json')).exists():core.save(core.CACHE/('stock_day_'+self.end+'.json'),list(self.days.values()))
 def fetch(self,key,url,params):
  import re
  path=core.CACHE/(key+'.json')
  if path.exists():return super().fetch(key,url,params)
  match=re.match(r'(.+)_minute_(\d{4}-\d{2}-\d{2})$',key)
  if match:
   prefix,end=match.groups();oldfiles=sorted(core.CACHE.glob(prefix+'_minute_*.json'));oldfiles=[f for f in oldfiles if re.match(re.escape(prefix)+r'_minute_\d{4}-\d{2}-\d{2}\.json$',f.name) and f.stem[-10:]<end]
   if oldfiles:
    old=oldfiles[-1];oldend=old.stem[-10:];rows=json.loads(old.read_text())
    covered_end=oldend
    if rows:oldend=min(oldend,max(datetime.fromtimestamp(r['t']/1000,core.ET).date().isoformat() for r in rows))
    if prefix.startswith('O_SKHY') and datetime.strptime(prefix.split('SKHY')[1][:6],'%y%m%d').date().isoformat()<=covered_end:core.save(path,rows);return rows
    start=(datetime.fromisoformat(oldend)+timedelta(days=1)).date().isoformat();tail=super().fetch(key+'_increment_'+start,url.replace('/'+core.START+'/'+end,'/'+start+'/'+end),params)
    merged={r['t']:r for r in rows};merged.update({r['t']:r for r in tail});rows=[merged[t] for t in sorted(merged)];core.save(path,rows);return rows
  return super().fetch(key,url,params)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--end');args=ap.parse_args()
 original=json.loads((ROOT/'exit_optimization_results.json').read_text());best=next(r for r in original['results'] if r['rule']['id']==original['best'])
 from entry_execution import EntryEngine,summarize
 import copy
 m=IncrementalMarket(args.offline,args.end);engine=EntryEngine(m)
 latest_path=BASE/'best_strategy_latest.json'
 data=json.loads(latest_path.read_text()) if latest_path.exists() else dict(selection_end=original['end'],selected_rule_id=original['best'],result=best)
 assert data['selected_rule_id']==original['best'] and data['result']['rule']==best['rule']
 if m.end<data.get('data_end',original['end']):raise RuntimeError('Refusing to replace newer ledger with older market coverage')
 result=copy.deepcopy(data['result']);last=result['trades'][-1] if result['trades'] else None
 def finalize(tr,new):
  tr.update(new);e,x=tr['entry'],tr['exit'];tr.update(gross=x['value']-e['value'],roi=100*(x['value']-e['value'])/e['value'],call_pnl=100*(x['call']-e['call']),put_pnl=100*(x['put']-e['put']))
 if last and last['status']=='仍持仓估值':finalize(last,engine.closing(last['contract'],last['entry'],best['rule']))
 t=m.reentry(datetime.fromisoformat(last['exit']['time'])) if last and last['status']!='仍持仓估值' else None
 if last and t:result['decisions']=[d for d in result['decisions'] if d['time']<=last['exit']['time']]
 while t and t<=m.limit:
  dec,q,e=engine.opening(t,best['rule']);result['decisions'].append(dec)
  if e is None:
   if dec['action']=='数据待验证':raise RuntimeError('Missing same-day candidate data; existing report preserved')
   t=m.nextday(t);continue
  tr=dict(id=len(result['trades'])+1,decision=dec,contract=q,entry=e);finalize(tr,engine.closing(q,e,best['rule']));result['trades'].append(tr)
  t=m.reentry(datetime.fromisoformat(tr['exit']['time'])) if tr['status']!='仍持仓估值' else None
 summarize(result,m.limit)
 data.update(data_end=m.end,requested_end=args.end or __import__('refresh_data').last_completed_date(),checked_at_utc=datetime.now(timezone.utc).isoformat(),result=result,entry_execution_version='latest_same_day_trade_v1')
 core.save(BASE/'best_strategy_latest.json',data);print('UPDATED_FIXED_RULE',original['best'],m.end,result['stats'])
