#!/usr/bin/env python3
"""
General data puller: 2 years of stock + options data from Polygon/Massive.
===========================================================================
Pulls for a given ticker:
  1. Stock: 2 years of daily OHLCV  ->  {TICKER}_stock.json
  2. Options: 2 years of daily near-ATM chains  ->  {TICKER}_options.json

Data saved to /Users/gavinz/git/finance/data/

Usage:
  python3 data_puller.py --ticker QQQ
  python3 data_puller.py --ticker QQQ --stock-only
  python3 data_puller.py --ticker QQQ --options-only --start 2024-08-17
"""

import json
import math
import argparse
import time
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = "8MCOdzsVgnUaFCzn4yqZHckAvTJKbh6D"
BASE = "https://api.polygon.io"
OUT_DIR = "/Users/gavinz/git/finance/data"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


# ---- Stock data ----

def pull_stock(ticker, start, end):
    """Pull 2 years of daily OHLCV. Returns list of [date, o, h, l, c, v]."""
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    rows = []
    for attempt in range(3):
        try:
            r = SESSION.get(url, params={'apiKey': API_KEY, 'adjusted': 'false',
                                         'sort': 'asc', 'limit': 50000}, timeout=30)
            if r.status_code == 200:
                d = r.json()
                for res in d.get('results', []):
                    ts = datetime.fromtimestamp(res['t'] / 1000, tz=timezone.utc)
                    date_str = ts.strftime('%Y-%m-%d')
                    rows.append([date_str, res['o'], res['h'], res['l'], res['c'], res['v']])
                return rows
            elif r.status_code == 429:
                time.sleep(2)
        except Exception:
            time.sleep(1)
    return rows


# ---- Options data ----

def make_ticker(ticker, expiry_date, cp, strike):
    yy = expiry_date[2:4]
    mm = expiry_date[5:7]
    dd = expiry_date[8:10]
    s = int(round(strike * 1000))
    return f"O:{ticker}{yy}{mm}{dd}{cp}{s:08d}"


# 美股休市日（落在工作日的节日）。若周五休市，周度期权到期日顺延至周四。
US_HOLIDAYS = {
    # 2024
    '2024-01-01', '2024-01-15', '2024-02-19', '2024-03-29',
    '2024-05-27', '2024-06-19', '2024-07-04', '2024-09-02',
    '2024-11-28', '2024-12-25',
    # 2025
    '2025-01-01', '2025-01-20', '2025-02-17', '2025-04-18',
    '2025-05-26', '2025-06-19', '2025-07-04', '2025-09-01',
    '2025-11-27', '2025-12-25',
    # 2026
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
    '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25',
}


def next_friday(date_str):
    d = datetime.strptime(date_str, '%Y-%m-%d')
    offset = (4 - d.weekday()) % 7
    if offset == 0:
        offset = 7  # next Friday, not same day
    friday = d + timedelta(days=offset)
    # 周五休市时，周度期权实际到期日为周四
    if friday.strftime('%Y-%m-%d') in US_HOLIDAYS:
        friday -= timedelta(days=1)
    return friday.strftime('%Y-%m-%d')


def strike_step(spot):
    if spot < 100:
        return 1.0
    elif spot < 400:
        return 2.5
    else:
        return 5.0


def pull_contract(ticker, expiry_date, cp, strike, date_str):
    tk = make_ticker(ticker, expiry_date, cp, strike)
    url = f"{BASE}/v2/aggs/ticker/{tk}/range/1/day/{date_str}/{date_str}"
    try:
        r = SESSION.get(url, params={'apiKey': API_KEY}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            results = d.get('results') or []
            if results:
                res = results[0]
                return {'strike': strike, 'cp': cp,
                        'c': res.get('c'), 'vw': res.get('vw'), 'v': res.get('v')}
    except Exception:
        pass
    return None


def pull_options(ticker, stock_rows):
    """Pull daily near-ATM option chains. Returns list of daily chains."""
    # Build all (date, strike, cp) tasks
    tasks = []
    day_meta = {}
    for row in stock_rows:
        date_str = row[0]
        spot = row[4]
        step = strike_step(spot)
        lo = math.floor(spot * 0.85 / step) * step
        hi = math.ceil(spot * 1.15 / step) * step
        strikes = []
        s = lo
        while s <= hi + 1e-9:
            strikes.append(round(s, 2))
            s += step
        expiry = next_friday(date_str)
        day_meta[date_str] = {'spot': spot, 'expiry': expiry,
                              'dte': (datetime.strptime(expiry, '%Y-%m-%d') -
                                      datetime.strptime(date_str, '%Y-%m-%d')).days}
        for k in strikes:
            tasks.append((ticker, expiry, 'C', k, date_str))
            tasks.append((ticker, expiry, 'P', k, date_str))

    print(f"  共 {len(tasks)} 个合约任务，并发拉取中...")

    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(pull_contract, *t): t for t in tasks}
        for fut in as_completed(futs):
            t = futs[fut]
            date_str = t[4]
            res = fut.result()
            done += 1
            if res is not None:
                results.setdefault(date_str, []).append(res)
            if done % 5000 == 0:
                print(f"    ...{done}/{len(tasks)}")

    # Group into daily chains
    chains = []
    for date_str, meta in day_meta.items():
        recs = results.get(date_str, [])
        calls = [{'strike': r['strike'], 'c': r['c'], 'vw': r['vw'], 'v': r['v']}
                 for r in recs if r['cp'] == 'C' and r['c'] is not None]
        puts = [{'strike': r['strike'], 'c': r['c'], 'vw': r['vw'], 'v': r['v']}
                for r in recs if r['cp'] == 'P' and r['c'] is not None]
        calls.sort(key=lambda x: x['strike'])
        puts.sort(key=lambda x: x['strike'])
        chains.append({
            'date': date_str, 'spot': meta['spot'], 'expiry': meta['expiry'],
            'dte': meta['dte'], 'calls': calls, 'puts': puts,
        })
    chains.sort(key=lambda x: x['date'])
    return chains


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', required=True)
    ap.add_argument('--start', default='2024-08-17')
    ap.add_argument('--end', default='2026-08-17')
    ap.add_argument('--stock-only', action='store_true')
    ap.add_argument('--options-only', action='store_true')
    args = ap.parse_args()

    ticker = args.ticker.upper()
    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    stock_file = f"{OUT_DIR}/{ticker}_stock.json"
    options_file = f"{OUT_DIR}/{ticker}_options.json"

    do_stock = not args.options_only
    do_options = not args.stock_only

    if do_stock:
        print(f"[{ticker}] 拉取股票日线 {args.start} ~ {args.end} ...")
        rows = pull_stock(ticker, args.start, args.end)
        if rows:
            json.dump(rows, open(stock_file, 'w'))
            print(f"  股票数据: {len(rows)} 天 -> {stock_file}")
        else:
            print("  股票数据拉取失败！")
            return
    else:
        rows = json.load(open(stock_file))

    if do_options:
        print(f"[{ticker}] 拉取期权日频近月链 ...")
        chains = pull_options(ticker, rows)
        json.dump(chains, open(options_file, 'w'))
        n_contracts = sum(len(c['calls']) + len(c['puts']) for c in chains)
        print(f"  期权数据: {len(chains)} 天, {n_contracts} 个合约记录 -> {options_file}")

    print(f"[{ticker}] 完成")


if __name__ == '__main__':
    main()
