"""Illustrate a fresh decision after report3's latest simulated exit; not an extra backtest trade."""
from pathlib import Path
import json,argparse
from datetime import datetime,timedelta,time
from rotation_backtest import Market,select,POLS,save,iso
p=Path(__file__).parent
ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,default=p.parent/'best_exit_cycle_details.json');ap.add_argument('--offline',action='store_true');args=ap.parse_args()
d=json.loads((p/'rotation_results.json').read_text());ledger=json.loads(args.source.read_text());sold=[r for r in ledger['cycles'] if r['sell_time']];last=max(sold,key=lambda r:r['sell_time']);m=Market(args.offline,d['end']);t=m.reentry(datetime.fromisoformat(last['sell_time']));initial=t;contracts=m.candidates(t);quotes={}
while t.date()==initial.date() and t.time()<=time(15,30):
 quotes={k:q for k,c in contracts.items() if (q:=m.quote(c,t)) is not None}
 if len(quotes)==len(contracts):break
 t+=timedelta(minutes=10)
if t.time()>time(15,30):t=initial;quotes={k:q for k,c in contracts.items() if (q:=m.quote(c,t)) is not None}
choices=[]
for policy,name,ratio in POLS:
 q=select(quotes,policy,ratio,t.weekday()==4);choices.append(dict(policy=policy,name=name,expiry=q['expiry'] if q else None,cost=q['cost'] if q else None))
d['example']=dict(previous_exit=last['sell_time'],previous_gross=last['gross'],decision_time=iso(t),strike_selection_time=iso(initial),candidates=quotes,choices=choices,source='报告3最后一次模拟平仓后独立观察；不重复计入轮动总收益')
save(p/'rotation_results.json',d);print(json.dumps(d['example'],ensure_ascii=False,indent=2))
