#!/usr/bin/env python3
"""Incremental data refresh using the existing data_puller account configuration.
Run this, then gen_qqq_biweekly_report.py. --data-dir allows staging/QA first.
Only the cycle-entry chains needed by this report are extended.
"""
import sys,json,math,time,threading,argparse
from zoneinfo import ZoneInfo
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import data_puller as p
ap=argparse.ArgumentParser(description='Refresh QQQ stock and required biweekly cycle-entry option chains')
ap.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[2]/'Data')
ap.add_argument('--as-of',default=(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=1)).strftime('%Y-%m-%d'))
args=ap.parse_args();ROOT=args.data_dir.resolve()
stock=json.load(open(ROOT/'QQQ_stock.json'))
fresh=p.pull_stock('QQQ',stock[-1][0],args.as_of)
if not fresh:raise RuntimeError('No stock bars received; aborting refresh')
merged={r[0]:r for r in stock};merged.update({r[0]:r for r in fresh})
stock=[merged[k] for k in sorted(merged)];prices={r[0]:r[4] for r in stock}
chains=json.load(open(ROOT/'QQQ_options_2wk.json'));mapping={c['date']:c for c in chains}
# Follow the backtest schedule from its first entry, including holiday-adjusted expiries.
def expiry_for(date):
 d=datetime.strptime(date,'%Y-%m-%d');offset=(4-d.weekday())%7 or 7
 expiry=d+timedelta(days=offset+7)
 while expiry.strftime('%Y-%m-%d') in p.US_HOLIDAYS:expiry-=timedelta(days=1)
 return expiry.strftime('%Y-%m-%d')
entries=[];day=chains[0]['date']
while day<=stock[-1][0]:
 if day not in prices:raise RuntimeError('Missing stock entry date '+day)
 c=mapping.get(day)
 if c and c['calls'] and c['puts']:
  day=c['expiry']
 else:
  entries.append(day);day=expiry_for(day)
local=threading.local()
def pull(task):
 date,expiry,cp,k=task;tk=p.make_ticker('QQQ',expiry,cp,k)
 if not hasattr(local,'s'):
  import requests
  local.s=requests.Session()
 for attempt in range(4):
  try:
   r=local.s.get(p.BASE+f'/v2/aggs/ticker/{tk}/range/1/day/{date}/{date}',params={'apiKey':p.API_KEY,'adjusted':'false'},timeout=25)
   if r.status_code==200:
    d=r.json();bars=d.get('results',[])
    return task,({'strike':k,**{key:bars[0].get(key) for key in ['c','vw','v']}} if bars else None),d.get('request_id')
   if r.status_code not in [429,500,502,503,504]:return task,None,'HTTP '+str(r.status_code)
  except Exception:pass
  time.sleep(attempt+1)
 return task,None,'ERROR'
tasks=[]
for date in entries:
 spot=prices[date];expiry=expiry_for(date)
 mapping[date]={'date':date,'spot':spot,'expiry':expiry,'dte':(datetime.strptime(expiry,'%Y-%m-%d')-datetime.strptime(date,'%Y-%m-%d')).days,'calls':[],'puts':[]}
 for k in range(math.floor(spot*.85/5)*5,math.ceil(spot*1.15/5)*5+1,5):
  for cp in ['C','P']:tasks.append((date,expiry,cp,k))
provenance=[];errors=[]
with ThreadPoolExecutor(max_workers=12) as pool:
 for n,(task,bar,reqid) in enumerate(pool.map(pull,tasks),1):
  date,expiry,cp,k=task
  if reqid=='ERROR' or str(reqid).startswith('HTTP'):errors.append((task,reqid))
  if bar:mapping[date]['calls' if cp=='C' else 'puts'].append(bar)
  provenance.append({'date':date,'expiry':expiry,'cp':cp,'strike':k,'has_bar':bar is not None,'request_id':reqid})
  if n%80==0:print(f'{n}/{len(tasks)} contracts',flush=True)
if errors:raise RuntimeError(str(errors[:3]))
for date in entries:
 c=mapping[date]
 for key in ['calls','puts']:c[key].sort(key=lambda x:x['strike'])
 assert c['calls'] and c['puts'],date
 print(date,c['expiry'],len(c['calls']),len(c['puts']),flush=True)
json.dump(stock,open(ROOT/'QQQ_stock.json','w'))
json.dump([mapping[k] for k in sorted(mapping)],open(ROOT/'QQQ_options_2wk.json','w'))
json.dump({'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'provider':'Polygon/Massive','stock_latest':stock[-1][0],'requested_as_of':args.as_of,'option_scope':'Existing history plus required new cycle entry dates; daily full chains are not extended','requests':provenance},open(ROOT/'refresh_data_provenance.json','w'),indent=2)
