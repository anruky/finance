#!/usr/bin/env python3
"""Fix QQQ_options_2wk.json empty chains caused by holiday expiries.

Root cause: the original 2-week puller used "next Friday + 7 days" without
handling US holidays. When that 2-week-Friday landed on a holiday (e.g. 7/4
Independence Day), the option ticker had no data, leaving empty chains.

Fix: recompute expiry with "holiday -> previous trading day (Thursday)" and
re-pull only the empty-chain days, then merge back.
"""
import json
import math
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from data_puller import (make_ticker, pull_contract, strike_step,
                         SESSION, API_KEY, US_HOLIDAYS, OUT_DIR)


def friday_2wk_fixed(date_str):
    """Two-week-out Friday, holiday rolled back to previous trading day."""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    offset = (4 - d.weekday()) % 7
    if offset == 0:
        offset = 7
    next_fri = d + timedelta(days=offset)
    expiry = next_fri + timedelta(days=7)
    while expiry.strftime('%Y-%m-%d') in US_HOLIDAYS:
        expiry -= timedelta(days=1)
    return expiry.strftime('%Y-%m-%d')


def main():
    path = f"{OUT_DIR}/QQQ_options_2wk.json"
    chains = json.load(open(path))
    chain_map = {c['date']: c for c in chains}

    empty_dates = [c['date'] for c in chains
                   if len(c['puts']) == 0 and len(c['calls']) == 0]
    print(f"空链日期 {len(empty_dates)} 天：{empty_dates}")

    tasks = []
    day_meta = {}
    for date_str in empty_dates:
        c = chain_map[date_str]
        spot = c['spot']
        step = strike_step(spot)
        lo = math.floor(spot * 0.85 / step) * step
        hi = math.ceil(spot * 1.15 / step) * step
        strikes = []
        s = lo
        while s <= hi + 1e-9:
            strikes.append(round(s, 2))
            s += step
        expiry = friday_2wk_fixed(date_str)
        day_meta[date_str] = {
            'spot': spot, 'expiry': expiry,
            'dte': (datetime.strptime(expiry, '%Y-%m-%d') -
                    datetime.strptime(date_str, '%Y-%m-%d')).days,
        }
        for k in strikes:
            tasks.append(('QQQ', expiry, 'C', k, date_str))
            tasks.append(('QQQ', expiry, 'P', k, date_str))

    print(f"共 {len(tasks)} 个合约任务，并发拉取...")
    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(pull_contract, *t): t for t in tasks}
        for fut in as_completed(futs):
            t = futs[fut]
            res = fut.result()
            done += 1
            if res is not None:
                results.setdefault(t[4], []).append(res)
            if done % 2000 == 0:
                print(f"  ...{done}/{len(tasks)}")

    # Merge back
    for date_str, meta in day_meta.items():
        recs = results.get(date_str, [])
        calls = [{'strike': r['strike'], 'c': r['c'], 'vw': r['vw'], 'v': r['v']}
                 for r in recs if r['cp'] == 'C' and r['c'] is not None]
        puts = [{'strike': r['strike'], 'c': r['c'], 'vw': r['vw'], 'v': r['v']}
                for r in recs if r['cp'] == 'P' and r['c'] is not None]
        calls.sort(key=lambda x: x['strike'])
        puts.sort(key=lambda x: x['strike'])
        chain_map[date_str] = {
            'date': date_str, 'spot': meta['spot'], 'expiry': meta['expiry'],
            'dte': meta['dte'], 'calls': calls, 'puts': puts,
        }
        print(f"  {date_str}: expiry {meta['expiry']} dte {meta['dte']} "
              f"calls {len(calls)} puts {len(puts)}")

    new_chains = [chain_map[c['date']] for c in chains]
    json.dump(new_chains, open(path, 'w'))
    still_empty = sum(1 for c in new_chains
                      if len(c['puts']) == 0 and len(c['calls']) == 0)
    print(f"完成。剩余空链 {still_empty} 天 -> {path}")


if __name__ == '__main__':
    main()
