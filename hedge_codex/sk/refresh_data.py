#!/usr/bin/env python3
"""Fetch actual listed SKHY puts and their complete histories; atomic writes.
Credentials: POLYGON_API_KEY or MASSIVE_API_KEY environment variable.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASE = 'https://api.polygon.io'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    temp.replace(path)


def last_completed_date(now=None):
    now = now or datetime.now(ZoneInfo('America/New_York'))
    d = now.date() if (now.hour, now.minute) >= (16, 30) else now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()  # Stock API resolves exchange holidays.


class Client:
    def __init__(self, key):
        self.key = key

    def get(self, endpoint, params=None):
        import requests
        url = endpoint if endpoint.startswith('https://') else BASE + endpoint
        if urlsplit(url).hostname not in ('api.polygon.io', 'api.massive.com'):
            raise RuntimeError('Unexpected pagination host')
        for attempt in range(5):
            try:
                r = requests.get(url, params=dict(params or {}, apiKey=self.key), timeout=35)
            except requests.RequestException:
                if attempt == 4:
                    raise RuntimeError('Market-data network request failed') from None
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                body = r.json()
                if body.get('status') in ('ERROR', 'NOT_AUTHORIZED'):
                    raise RuntimeError('Market-data response rejected')
                return body
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError('Market-data HTTP %s' % r.status_code)
            time.sleep(2 ** attempt)
        raise RuntimeError('Market-data retries exhausted')

    def pages(self, endpoint, params):
        rows = []
        while endpoint:
            body = self.get(endpoint, params)
            rows.extend(body.get('results') or [])
            endpoint, params = body.get('next_url'), {}
        return rows


def refresh(start, end, out, workers=8):
    key = os.environ.get('POLYGON_API_KEY') or os.environ.get('MASSIVE_API_KEY')
    if not key:
        raise RuntimeError('Set POLYGON_API_KEY or MASSIVE_API_KEY')
    client = Client(key)
    raw = client.pages('/v2/aggs/ticker/SKHY/range/1/day/%s/%s' % (start, end),
                       {'adjusted': 'false', 'sort': 'asc', 'limit': 50000})
    stock = [[datetime.fromtimestamp(b['t']/1000, ZoneInfo('America/New_York')).date().isoformat(),
              b['o'], b['h'], b['l'], b['c'], b['v']] for b in raw]
    stock = sorted([r for r in stock if start <= r[0] <= end])
    if not stock:
        raise RuntimeError('No stock bars returned; existing files preserved')
    print('Stock: %s .. %s, %s sessions' % (stock[0][0], stock[-1][0], len(stock)), flush=True)
    listed, contracts = {}, {}

    def discover(row):
        date, spot = row[0], row[4]
        horizon = (datetime.fromisoformat(date) + timedelta(days=35)).date().isoformat()
        rows = client.pages('/v3/reference/options/contracts', {
            'underlying_ticker': 'SKHY', 'as_of': date, 'contract_type': 'put',
            'expiration_date.gt': date, 'expiration_date.lte': horizon,
            'strike_price.gte': round(spot * .75, 2),
            'strike_price.lte': round(spot * 1.25, 2), 'limit': 1000})
        return date, [r for r in rows if r.get('shares_per_contract') == 100]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(discover, r) for r in stock]):
            date, rows = future.result()
            listed[date] = sorted(r['ticker'] for r in rows)
            for r in rows:
                contracts[r['ticker']] = {k:r.get(k) for k in
                    ('ticker', 'expiration_date', 'strike_price', 'shares_per_contract', 'exercise_style')}
    print('Discovered %s real put contracts' % len(contracts), flush=True)
    history = {}

    def fetch(ticker):
        rows = client.pages('/v2/aggs/ticker/%s/range/1/day/%s/%s' % (ticker, start, stock[-1][0]),
                            {'adjusted': 'false', 'sort': 'asc', 'limit': 50000})
        bars = {datetime.fromtimestamp(b['t']/1000, ZoneInfo('America/New_York')).date().isoformat():
                {k:b.get(k) for k in ('o', 'h', 'l', 'c', 'vw', 'v', 't', 'n')} for b in rows}
        return ticker, bars

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, future in enumerate(as_completed([pool.submit(fetch, t) for t in contracts]), 1):
            ticker, bars = future.result()
            history[ticker] = bars
            if i % 100 == 0:
                print('Fetched %s/%s contract histories' % (i, len(contracts)), flush=True)
    manifest = {
        'schema': 1, 'ticker': 'SKHY', 'source': BASE, 'adjusted': False,
        'fetched_at_utc': datetime.now(ZoneInfo('UTC')).isoformat(),
        'requested_end': end, 'stock_end': stock[-1][0], 'stock_start': stock[0][0],
        'n_sessions': len(stock), 'n_contracts': len(contracts),
        'selection_strike_range': [.75, 1.25], 'selection_horizon_days': 35,
        'price_basis': 'daily trade aggregates; not executable NBBO or synchronised closing quotes',
        'stock_sha256': hashlib.sha256(json.dumps(stock).encode()).hexdigest(),
    }
    atomic_json(out/'SKHY_put_history.json', dict(manifest=manifest, stock=stock,
                listed=listed, contracts=contracts, history=history))
    atomic_json(out/'SKHY_stock.json', stock)
    chains = []
    for row in stock:
        date = row[0]
        expiries = sorted({contracts[t]['expiration_date'] for t in listed[date]})[:3]
        fridays = []
        for expiry in expiries:
            puts = []
            for ticker in listed[date]:
                c, b = contracts[ticker], history[ticker].get(date)
                if c['expiration_date'] == expiry and b and b.get('v', 0) > 0:
                    puts.append(dict(strike=c['strike_price'], **b))
            fridays.append(dict(expiry=expiry, dte=(datetime.fromisoformat(expiry)-datetime.fromisoformat(date)).days,
                                calls=[], puts=sorted(puts, key=lambda p:p['strike'])))
        chains.append(dict(date=date, spot=row[4], fridays=fridays))
    atomic_json(out/'SKHY_options_3fri.json', chains)
    atomic_json(out/'refresh_manifest.json', manifest)
    print('Refresh complete: %s' % (out/'SKHY_put_history.json'), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--start', default='2026-07-13')
    ap.add_argument('--end', default=last_completed_date())
    ap.add_argument('--data-dir', type=Path, default=ROOT/'data')
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()
    if args.end > last_completed_date():
        ap.error('--end must be a completed US session date')
    refresh(args.start, args.end, args.data_dir, args.workers)


if __name__ == '__main__':
    main()
