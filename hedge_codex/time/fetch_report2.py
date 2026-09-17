import json,ast,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
sys.path.insert(0,'/Users/gavinz/git/finance/hedge_codex/sk')
from refresh_data import Client
root=Path(__file__).parent
base=root/'weekly_market_data.json'
if not base.exists():base=Path('/Users/gavinz/git/finance/hedge_codex/time/weekly_market_data.json')
r=json.loads(base.read_text())
source=Path('/Users/gavinz/git/finance/data/data_puller.py').read_text()
key=next(ast.literal_eval(n.value) for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='API_KEY' for t in n.targets));client=Client(key)
jobs=[]
for day,put in r['metadata']['selected']:
 call=put[:-9]+'C'+put[-8:];expiry=datetime.strptime(call.split('SKHY')[1][:6],'%y%m%d').date().isoformat()
 for scale in ['minute','day']:jobs.append((call,scale,day,min(expiry,r['metadata']['end'])))
def fetch(j):
 t,scale,start,end=j
 return t+'_'+scale,client.pages(f'/v2/aggs/ticker/{t}/range/1/{scale}/{start}/{end}',{'adjusted':'false','sort':'asc','limit':50000})
with ThreadPoolExecutor(max_workers=5) as pool:
 for name,rows in pool.map(fetch,jobs):r[name]=rows;print(name,len(rows),flush=True)
r['metadata']['call_fetched_at_utc']=datetime.now(timezone.utc).isoformat();r['metadata']['report2_selection']='Same strike and expiration as report 1; first common stock/call/put minute at or after Friday 10:00'
(root/'report2_market_data.json').write_text(json.dumps(r,indent=2));print('Done',flush=True)
