import json,ast,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
sys.path.insert(0,'/Users/gavinz/git/finance/hedge_codex/sk')
from refresh_data import Client,last_completed_date
source=Path('/Users/gavinz/git/finance/data/data_puller.py').read_text()
key=next(ast.literal_eval(n.value) for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='API_KEY' for t in n.targets))
c=Client(key);start='2026-07-31';end=last_completed_date();out=Path(__file__).resolve().parent
selected=[('2026-08-07','O:SKHY260814P00137000'),('2026-08-14','O:SKHY260821P00167500'),('2026-08-21','O:SKHY260828P00167500'),('2026-08-28','O:SKHY260904P00160000'),('2026-09-04','O:SKHY260911P00170000'),('2026-09-11','O:SKHY260918P00190000')]
bars=c.pages('/v2/aggs/ticker/SKHY/range/1/minute/2026-07-31/2026-07-31',{'adjusted':'false','sort':'asc','limit':50000})
from zoneinfo import ZoneInfo
spot=next(b['c'] for b in bars if datetime.fromtimestamp(b['t']/1000,ZoneInfo('America/New_York')).strftime('%H:%M')=='09:59')
contracts=c.pages('/v3/reference/options/contracts',{'underlying_ticker':'SKHY','as_of':start,'contract_type':'put','expiration_date':'2026-08-07','limit':1000})
contract=min([x for x in contracts if x.get('shares_per_contract')==100],key=lambda x:(abs(x['strike_price']-spot),x['strike_price']))
selected.insert(0,(start,contract['ticker']))
print('July31 ATM',spot,contract['ticker'],flush=True)
jobs=[('SKHY',scale,start,end) for scale in ['minute','day']]
for dt,ticker in selected:
 expiry=(datetime.fromisoformat(dt)+timedelta(days=7)).date().isoformat()
 for scale in ['minute','day']:jobs.append((ticker,scale,dt,min(expiry,end)))
def fetch(job):
 t,scale,lo,hi=job;rows=c.pages(f'/v2/aggs/ticker/{t}/range/1/{scale}/{lo}/{hi}',{'adjusted':'false','sort':'asc','limit':50000})
 return t+'_'+scale,rows
r={}
with ThreadPoolExecutor(max_workers=5) as ex:
 for k,rows in ex.map(fetch,jobs):r[k]=rows;print(k,len(rows),flush=True)
r['metadata']=dict(start=start,end=end,selected=selected,fetched_at_utc=datetime.now(timezone.utc).isoformat(),selection='nearest listed next-Friday Put strike to Friday 09:59 stock close; wait for first common minute >=10:00')
(out/'weekly_market_data.json').write_text(json.dumps(r,indent=2));print('Complete through',end,flush=True)
