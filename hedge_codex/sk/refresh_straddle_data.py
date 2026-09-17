#!/usr/bin/env python3
"""Fetch same-strike Calls for the existing SKHY Put comparison window."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
import hashlib,json,os
from pathlib import Path
from zoneinfo import ZoneInfo
from refresh_data import Client,atomic_json
from backtest_audited import Config,pick


def call_ticker(put):
    assert put[-9]=='P'
    return put[:-9]+'C'+put[-8:]


def refresh(project,out):
    key=os.environ.get('POLYGON_API_KEY')or os.environ.get('MASSIVE_API_KEY')
    if not key:raise RuntimeError('Set POLYGON_API_KEY or MASSIVE_API_KEY')
    d=json.loads((project/'data/SKHY_put_history.json').read_text());stock=d['stock'];client=Client(key)
    wanted=set()
    for prev,current in zip(stock,stock[1:]):
        for target in (2,7,14,21):
            result=pick(d,prev[0],current[0],prev[4],Config(target=target))
            if result:wanted.add(call_ticker(result[0]))
    listed={};contracts={}
    def reference(row):
        dt,spot=row[0],row[4];end=(datetime.fromisoformat(dt)+timedelta(days=35)).date().isoformat()
        rows=client.pages('/v3/reference/options/contracts',dict(underlying_ticker='SKHY',as_of=dt,
             contract_type='call',limit=1000,**{'expiration_date.gt':dt,'expiration_date.lte':end,
             'strike_price.gte':round(spot*.969,2),'strike_price.lte':round(spot*1.031,2)}))
        return dt,[r for r in rows if r.get('shares_per_contract')==100 and r['ticker']in wanted]
    with ThreadPoolExecutor(max_workers=8)as ex:
        for future in as_completed([ex.submit(reference,r)for r in stock]):
            dt,rows=future.result();listed[dt]=sorted(r['ticker']for r in rows)
            for r in rows:contracts[r['ticker']]={k:r.get(k)for k in ['ticker','strike_price','expiration_date','shares_per_contract','exercise_style']}
    print('Reference verified:',len(contracts),'matching Calls',flush=True)
    def fetch(t):
        rows=client.pages(f'/v2/aggs/ticker/{t}/range/1/day/{stock[0][0]}/{stock[-1][0]}',{'adjusted':'false','sort':'asc','limit':50000})
        return t,{datetime.fromtimestamp(r['t']/1000,ZoneInfo('America/New_York')).date().isoformat():
                 {k:r.get(k)for k in ['o','h','l','c','vw','v','t','n']}for r in rows}
    history={}
    with ThreadPoolExecutor(max_workers=8)as ex:
        for i,future in enumerate(as_completed([ex.submit(fetch,t)for t in contracts]),1):
            t,bars=future.result();history[t]=bars
            if i%25==0:print('Calls fetched',i,'/',len(contracts),flush=True)
    manifest=dict(start=stock[0][0],end=stock[-1][0],source='Polygon/Massive',adjusted=False,
        fetched_at_utc=datetime.now(ZoneInfo('UTC')).isoformat(),n_contracts=len(contracts),
        put_dataset_sha256=hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest(),
        scope='Calls matching prior-close ATM Put candidates for 2/7/14/21 day targets; comparison window frozen to existing Put data')
    atomic_json(out,dict(manifest=manifest,listed=listed,contracts=contracts,history=history))
    print('Saved',out,flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent)
    ap.add_argument('--output',type=Path);args=ap.parse_args()
    refresh(args.project_dir,args.output or args.project_dir/'data/SKHY_call_history.json')


if __name__=='__main__':main()
