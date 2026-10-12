import json,ast,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone,time
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import time as wait_time
sys.path.insert(0,'/Users/gavinz/git/finance/hedge_codex/sk')
from refresh_data import Client,last_completed_date
p=Path(__file__).parent;ET=ZoneInfo('America/New_York');end=last_completed_date();start='2026-07-31'
source=Path('/Users/gavinz/git/finance/data/data_puller.py').read_text();key=next(ast.literal_eval(n.value) for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='API_KEY' for t in n.targets));c=Client(key)
cache=p/'download_cache';cache.mkdir(exist_ok=True)
def agg(t,scale,lo,hi):
 path=cache/(t.replace(':','_')+'_'+scale+'_'+lo+'_'+hi+'.json')
 if path.exists():return json.loads(path.read_text())
 result=c.pages(f'/v2/aggs/ticker/{t}/range/1/{scale}/{lo}/{hi}',{'adjusted':'false','sort':'asc','limit':50000});path.write_text(json.dumps(result));return result
r={}
for scale in ['minute','day']:r['SKHY_'+scale]=agg('SKHY',scale,start,end)
old=json.loads((p/'report2_market_data.json').read_text());known=dict(old['metadata']['selected']);known['2026-09-18']='O:SKHY260925P00185000'
actual=max(datetime.fromtimestamp(b['t']/1000,ET).date().isoformat() for b in r['SKHY_day']);end=min(end,actual);selected=[];signals=[];day=datetime.fromisoformat(start)
while day.date().isoformat()<=end:
 ds=day.date().isoformat();expiry=(day+timedelta(days=7)).date().isoformat();bars=[b for b in r['SKHY_minute'] if datetime.fromtimestamp(b['t']/1000,ET).strftime('%Y-%m-%d %H:%M')==ds+' 09:59']
 if not bars:raise RuntimeError('Missing 09:59 stock signal '+ds)
 spot=bars[0]['c']
 if ds in known:put=known[ds]
 else:
  contracts=c.pages('/v3/reference/options/contracts',{'underlying_ticker':'SKHY','as_of':ds,'contract_type':'put','expiration_date':expiry,'limit':1000})
  put=min([x for x in contracts if x.get('shares_per_contract')==100],key=lambda x:(abs(x['strike_price']-spot),x['strike_price']))['ticker']
 selected.append((ds,put));signals.append(dict(day=ds,spot=spot,put=put));print(ds,put,flush=True);day+=timedelta(days=7)
jobs=[]
for ds,put in selected:
 expiry=datetime.strptime(put.split('SKHY')[1][:6],'%y%m%d').date().isoformat()
 for ticker in [put,put[:-9]+'C'+put[-8:]]:
  for scale in ['minute','day']:
   name=ticker+'_'+scale
   if expiry<=old['metadata']['end'] and name in old:r[name]=old[name]
   else:jobs.append((ticker,scale,ds,min(end,expiry)))
def job(args):
 t,scale,lo,hi=args;return t+'_'+scale,agg(t,scale,lo,hi)
for task in jobs:
 k,v=job(task);r[k]=v;print(k,len(v),flush=True);wait_time.sleep(13)
r['metadata']=dict(start=start,end=end,selected=selected,selection_signals=signals,fetched_at_utc=datetime.now(timezone.utc).isoformat(),call_fetched_at_utc=datetime.now(timezone.utc).isoformat(),historical_reused_fetched_at=old['metadata']['fetched_at_utc'],selection='Nearest next-Friday strike from Friday09:59 stock close; first common stock/call/put minute at or after10:00')
(p/'report2_market_data.json').write_text(json.dumps(r,indent=2));print('Complete through',end,flush=True)
