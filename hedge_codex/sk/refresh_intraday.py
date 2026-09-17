# -*- coding: utf-8 -*-
"""Cache same-minute execution data. No price fallback for executions."""
import json,sys,os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor,as_completed
from refresh_data import Client,atomic_json
from refresh_straddle_data import call_ticker
TZ=ZoneInfo('America/New_York')
def refresh(root,out):
 d=json.loads((root/'data/SKHY_put_history.json').read_text());client=Client(os.environ['POLYGON_API_KEY'])
 first,last=d['stock'][0][0],d['stock'][-1][0]
 def fetch(t):
  cache=out/'raw'/ (t.replace(':','_')+'.json');cache.parent.mkdir(parents=True,exist_ok=True)
  if cache.exists():return t,json.loads(cache.read_text())
  rows=client.pages(f'/v2/aggs/ticker/{t}/range/1/minute/{first}/{last}',{'adjusted':'false','sort':'asc','limit':50000})
  hist={}
  for x in rows:
   tm=datetime.fromtimestamp(x['t']/1000,TZ);dt=tm.date().isoformat();hm=tm.strftime('%H:%M')
   if '09:30'<=hm<='15:59':hist.setdefault(dt,{})[hm]=x
  atomic_json(cache,hist);return t,hist
 _,stock=fetch('SKHY');atomic_json(out/'stock_minutes.json',stock)
 # Candidate ranking uses stock through 09:59, known at 10:00, and previous session volume.
 chosen={};wanted=set();daily_calls=json.loads((root/'data/SKHY_call_history.json').read_text())['history']
 for idx,row in enumerate(d['stock']):
  dt=row[0];bar=stock.get(dt,{}).get('09:59')
  if not bar:continue
  spot=bar['c'];choices=[]
  for pt in d['listed'].get(dt,[]):
   con=d['contracts'][pt];days=(datetime.fromisoformat(con['expiration_date'])-datetime.fromisoformat(dt)).days
   if not 1<=days<=7 or abs(con['strike_price']/spot-1)>.03:continue
   choices.append((abs(days-2),abs(con['strike_price']-spot),pt))
  # Collect all nearby candidates to permit causal selection based on morning liquidity.
  pts=[v[2] for v in sorted(choices)]
  chosen[dt]=pts
  for pt in pts:wanted.update([pt,call_ticker(pt)])
 print('Stock sessions',len(stock),'candidate contracts',len(wanted),flush=True)
 hist={}
 with ThreadPoolExecutor(max_workers=6) as ex:
  for i,f in enumerate(as_completed([ex.submit(fetch,t) for t in sorted(wanted)]),1):
   t,h=f.result();hist[t]=h
   if i%20==0:print('Minutes downloaded',i,'/',len(wanted),flush=True)
 # Daily bars for end-of-day valuation only. Never enter/exit using these.
 daily={}
 def endofday(t):
  cache=out/'daily'/ (t.replace(':','_')+'.json');cache.parent.mkdir(parents=True,exist_ok=True)
  if cache.exists():return t,json.loads(cache.read_text())
  if t in d['history']:h=d['history'][t]
  elif t in daily_calls:h=daily_calls[t]
  else:
   rows=client.pages(f'/v2/aggs/ticker/{t}/range/1/day/{first}/{last}',{'adjusted':'false','sort':'asc','limit':50000})
   h={datetime.fromtimestamp(x['t']/1000,TZ).date().isoformat():x for x in rows}
  atomic_json(cache,h);return t,h
 with ThreadPoolExecutor(max_workers=6) as ex:
  for f in as_completed([ex.submit(endofday,t) for t in sorted(wanted)]):
   t,h=f.result();daily[t]=h
 result=dict(manifest=dict(start=first,end=last,source='Polygon/Massive minute aggregates',fetched_at=datetime.now(TZ).isoformat(),timezone=str(TZ),execution_minute='10:00',signal_cutoff='09:59',n_contracts=len(wanted)),stock=d['stock'],stock_minutes=stock,contracts=d['contracts'],candidates=chosen,minutes=hist,daily=daily)
 atomic_json(out/'SKHY_intraday.json',result);print('Saved',out/'SKHY_intraday.json',flush=True)
if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output-dir',type=Path)
 args=ap.parse_args()
 if not os.environ.get('POLYGON_API_KEY'):raise RuntimeError('Set POLYGON_API_KEY in environment')
 refresh(args.project_dir,args.output_dir or args.project_dir/'data/intraday_cache')
