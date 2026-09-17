#!/usr/bin/env python3
"""Download comparison stock histories using the existing paid Polygon account.
Set POLYGON_API_KEY or MASSIVE_API_KEY; never embeds credentials.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from refresh_data import Client,atomic_json,last_completed_date


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--start',default='2024-09-01')
    ap.add_argument('--end',default=last_completed_date())
    ap.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'data/factor_market_data.json')
    args=ap.parse_args()
    key=os.environ.get('POLYGON_API_KEY')or os.environ.get('MASSIVE_API_KEY')
    if not key:ap.error('Set POLYGON_API_KEY or MASSIVE_API_KEY')
    if args.end>last_completed_date():ap.error('Use only completed sessions')
    c=Client(key)
    def fetch(ticker):
        b=c.pages(f'/v2/aggs/ticker/{ticker}/range/1/day/{args.start}/{args.end}',{'adjusted':'true','sort':'asc','limit':50000})
        rows=[[datetime.fromtimestamp(r['t']/1000,ZoneInfo('America/New_York')).date().isoformat(),r['o'],r['h'],r['l'],r['c'],r['v']]for r in b]
        if not rows:raise RuntimeError('No data: '+ticker)
        return ticker,rows
    stocks={}
    with ThreadPoolExecutor(max_workers=5)as ex:
        for future in as_completed([ex.submit(fetch,t)for t in ('QQQ','SMH','MU','SNDK','DRAM')]):
            ticker,rows=future.result();stocks[ticker]=rows
            print(ticker,len(rows),rows[0][0],rows[-1][0])
    atomic_json(args.output,{'manifest':{'source':'Polygon/Massive aggregates','fetched_at_utc':datetime.now(ZoneInfo('UTC')).isoformat(),
                 'end':args.end,'adjusted':True,'purpose':'volatility predictors, not SKHY option valuation'},'stocks':stocks})


if __name__=='__main__':main()
