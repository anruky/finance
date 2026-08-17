#!/usr/bin/env python3
"""
Pull REAL historical QQQ option chains from Polygon/Massive.
============================================================
Since the reference endpoint doesn't return expired contracts, we CONSTRUCT
tickers ourselves (O:QQQ{YYMMDD}{C/P}{strike*1000}) and pull daily aggregates.

For each (entry_date, expiry_date) in the wheel schedule, we pull the real
option chain (strikes +/- 15% around spot, $5 increments) and save close/vwap.

Usage:
  python3 qqq_pull_real_options.py [--dte 7|14] [--limit N] [--out file]
"""

import json
import time
import math
import argparse
import requests
from datetime import datetime, timedelta

API_KEY = "8MCOdzsVgnUaFCzn4yqZHckAvTJKbh6D"
BASE = "https://api.polygon.io"
DATA_FILE = "qqq_data_2025_2026.json"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def load_prices():
    raw = json.load(open(DATA_FILE))
    data = [(r[0], r[1], r[2], r[3], r[4]) for r in raw]  # date, o, h, l, c
    data.sort(key=lambda x: x[0])
    return data


def find_expiry_index(entry_idx, dates, dte):
    entry_date = datetime.strptime(dates[entry_idx], '%Y-%m-%d')
    target = entry_date + timedelta(days=dte)
    target_str = target.strftime('%Y-%m-%d')
    for i in range(entry_idx + 1, len(dates)):
        if dates[i] >= target_str:
            return i
    return len(dates) - 1


def nearest_friday(date_str):
    """Snap a date to the nearest Friday (QQQ weekly expiry)."""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    # weekday(): Mon=0 ... Sun=6, Friday=4
    offset = 4 - d.weekday()
    if offset > 3:
        offset -= 7
    elif offset < -3:
        offset += 7
    return (d + timedelta(days=offset)).strftime('%Y-%m-%d')


def build_schedule(data, dte):
    """Generate cycle schedule: list of (entry_date, entry_price, expiry_date)."""
    dates = [d[0] for d in data]
    closes = [d[4] for d in data]
    schedule = []
    idx = 0
    seen = set()
    while idx < len(dates) - 1:
        entry_idx = idx
        entry_date = dates[entry_idx]
        entry_price = closes[entry_idx]
        expiry_idx = find_expiry_index(entry_idx, dates, dte)
        if expiry_idx <= entry_idx:
            break
        expiry_date = dates[expiry_idx]
        # snap to nearest real Friday (QQQ weekly expiry)
        real_expiry = nearest_friday(expiry_date)
        key = (entry_date, real_expiry)
        if key not in seen:
            seen.add(key)
            schedule.append({
                'entry_date': entry_date,
                'entry_price': entry_price,
                'expiry_date': real_expiry,
            })
        idx = expiry_idx
    return schedule


def option_ticker(expiry_date, cp, strike):
    """Construct QQQ option ticker: O:QQQ{YYMMDD}{C|P}{strike*1000:08d}"""
    yy = expiry_date[2:4]
    mm = expiry_date[5:7]
    dd = expiry_date[8:10]
    s = int(round(strike * 1000))
    return f"O:QQQ{yy}{mm}{dd}{cp}{s:08d}"


def pull_day(ticker, date_str, retries=3):
    """Pull daily aggregate for a ticker on a specific date. Returns (close, vwap, vol) or None."""
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{date_str}/{date_str}"
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params={'apiKey': API_KEY}, timeout=20)
            if r.status_code == 200:
                d = r.json()
                results = d.get('results') or []
                if results:
                    res = results[0]
                    return {
                        'c': res.get('c'),
                        'vw': res.get('vw'),
                        'v': res.get('v'),
                        'o': res.get('o'),
                    }
                return None  # no data (contract didn't trade / didn't exist)
            elif r.status_code == 429:
                time.sleep(1.5)
                continue
            else:
                return None
        except Exception as e:
            time.sleep(1.0)
    return None


def pull_chain(entry_date, entry_price, expiry_date):
    """Pull the real option chain around spot for a given entry date + expiry."""
    spot = entry_price
    lo = math.floor(spot * 0.85 / 5.0) * 5
    hi = math.ceil(spot * 1.15 / 5.0) * 5
    strikes = [lo + 5 * i for i in range(int((hi - lo) / 5) + 1)]

    chain = {'entry_date': entry_date, 'entry_price': spot,
             'expiry_date': expiry_date, 'calls': [], 'puts': []}
    dte_days = (datetime.strptime(expiry_date, '%Y-%m-%d') -
                datetime.strptime(entry_date, '%Y-%m-%d')).days
    chain['dte'] = dte_days

    for strike in strikes:
        # Call
        tk_c = option_ticker(expiry_date, 'C', strike)
        dc = pull_day(tk_c, entry_date)
        if dc:
            chain['calls'].append({'strike': strike, 'ticker': tk_c, **dc})
        # Put
        tk_p = option_ticker(expiry_date, 'P', strike)
        dp = pull_day(tk_p, entry_date)
        if dp:
            chain['puts'].append({'strike': strike, 'ticker': tk_p, **dp})
        time.sleep(0.05)  # gentle rate limit

    return chain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dte', type=int, default=7)
    ap.add_argument('--limit', type=int, default=0, help='only first N cycles (0=all)')
    ap.add_argument('--out', type=str, default='')
    args = ap.parse_args()

    data = load_prices()
    schedule = build_schedule(data, args.dte)
    if args.limit > 0:
        schedule = schedule[:args.limit]

    out_file = args.out or f'qqq_real_chains_dte{args.dte}.json'
    print(f"DTE={args.dte}: {len(schedule)} 个周期待拉取 → {out_file}")

    results = []
    for i, cyc in enumerate(schedule):
        chain = pull_chain(cyc['entry_date'], cyc['entry_price'], cyc['expiry_date'])
        results.append(chain)
        n_c = len(chain['calls'])
        n_p = len(chain['puts'])
        print(f"  [{i+1}/{len(schedule)}] {cyc['entry_date']} -> {cyc['expiry_date']} "
              f"(spot={cyc['entry_price']:.0f}) calls={n_c} puts={n_p}")
        # incremental save every 10 cycles
        if (i + 1) % 10 == 0:
            json.dump(results, open(out_file, 'w'))
            print(f"    ...已保存 {len(results)} 个周期")

    json.dump(results, open(out_file, 'w'))
    print(f"\n完成：{len(results)} 个周期已保存到 {out_file}")


if __name__ == '__main__':
    main()
