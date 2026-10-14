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
 m=IncrementalMarket(args.offline,args.end);result=opt.Engine(m).run(best['rule'])
 data=dict(selection_end=original['end'],data_end=m.end,selected_rule_id=original['best'],requested_end=args.end or __import__('refresh_data').last_completed_date(),checked_at_utc=datetime.now(timezone.utc).isoformat(),result=result)
 core.save(BASE/'best_strategy_latest.json',data);print('UPDATED_FIXED_RULE',original['best'],m.end,result['stats'])
