#!/usr/bin/env python3
"""
DRAM 双到期日期权拉取 (周一到期 + 周五到期)
============================================
基于 data_puller.py 改造: 原来只拉"下一个周五"到期的期权链,
现在对每个交易日同时拉"下一个周一"和"下一个周五"两个到期日的 near-ATM 链,
用于"7天轮动"回测(选更接近7天的到期日)。

数据源: Polygon.io
输出: /Users/gavinz/git/finance/data/DRAM_options_2exp.json

结构:
  [
    {
      "date": "2026-04-02",
      "spot": 27.76,
      "mon": {"expiry": "2026-04-06", "dte": 4, "calls": [...], "puts": [...]},
      "fri": {"expiry": "2026-04-10", "dte": 8, "calls": [...], "puts": [...]}
    },
    ...
  ]
"""
import json
import math
import time
import argparse
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = "8MCOdzsVgnUaFCzn4yqZHckAvTJKbh6D"
BASE = "https://api.polygon.io"
DATA_DIR = "/Users/gavinz/git/finance/data"
TICKER = "DRAM"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

US_HOLIDAYS = {
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
    '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25',
}


def next_weekday(date_str, weekday_target):
    """下一个指定星期几(不含当天)。weekday_target: 0=周一 ... 4=周五"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    offset = (weekday_target - d.weekday()) % 7
    if offset == 0:
        offset = 7
    result = d + timedelta(days=offset)
    if result.strftime('%Y-%m-%d') in US_HOLIDAYS:
        result -= timedelta(days=1)
    return result.strftime('%Y-%m-%d')


def make_ticker(expiry_date, cp, strike):
    yy, mm, dd = expiry_date[2:4], expiry_date[5:7], expiry_date[8:10]
    s = int(round(strike * 1000))
    return f"O:{TICKER}{yy}{mm}{dd}{cp}{s:08d}"


def strike_step(spot):
    return 1.0 if spot < 100 else (2.5 if spot < 400 else 5.0)


def pull_contract(ticker, date_str):
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{date_str}/{date_str}"
    for _ in range(3):
        try:
            r = SESSION.get(url, params={'apiKey': API_KEY}, timeout=15)
            if r.status_code == 200:
                results = r.json().get('results') or []
                if results:
                    res = results[0]
                    return {'c': res.get('c'), 'vw': res.get('vw'), 'v': res.get('v')}
                return None
            elif r.status_code == 429:
                time.sleep(2)
        except Exception:
            time.sleep(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2026-04-02')
    ap.add_argument('--end', default='2026-08-14')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    stock_file = f"{DATA_DIR}/{TICKER}_stock.json"
    out_file = f"{DATA_DIR}/{TICKER}_options_2exp.json"
    rows = json.load(open(stock_file))
    rows = [r for r in rows if args.start <= r[0] <= args.end]
    if args.limit > 0:
        rows = rows[:args.limit]
    print(f"交易日: {len(rows)} 天 ({rows[0][0]} ~ {rows[-1][0]})")

    # 构建任务
    tasks = []  # (date_str, expiry, cp, strike, which)
    day_meta = {}
    for r in rows:
        date_str, spot = r[0], r[4]
        step = strike_step(spot)
        lo = math.floor(spot * 0.85 / step) * step
        hi = math.ceil(spot * 1.15 / step) * step
        strikes = []
        s = lo
        while s <= hi + 1e-9:
            strikes.append(round(s, 2))
            s += step
        mon_exp = next_weekday(date_str, 0)
        fri_exp = next_weekday(date_str, 4)
        day_meta[date_str] = {'spot': spot,
                              'mon': {'expiry': mon_exp, 'dte': (datetime.strptime(mon_exp, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days},
                              'fri': {'expiry': fri_exp, 'dte': (datetime.strptime(fri_exp, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days}}
        for k in strikes:
            for cp in ('C', 'P'):
                tasks.append((date_str, mon_exp, cp, k, 'mon'))
                tasks.append((date_str, fri_exp, cp, k, 'fri'))

    print(f"共 {len(tasks)} 个合约任务，并发拉取中...")

    # date -> which -> cp -> [records]
    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = {}
        for date_str, expiry, cp, strike, which in tasks:
            tk = make_ticker(expiry, cp, strike)
            futs[ex.submit(pull_contract, tk, date_str)] = (date_str, cp, strike, which)
        for fut in as_completed(futs):
            date_str, cp, strike, which = futs[fut]
            res = fut.result()
            done += 1
            if res is not None:
                rec = {'strike': strike, 'c': res['c'], 'vw': res['vw'], 'v': res['v']}
                results.setdefault(date_str, {}).setdefault(which, {}).setdefault(cp, []).append(rec)
            if done % 5000 == 0:
                print(f"    ...{done}/{len(tasks)}")

    # 组装
    chains = []
    for date_str, meta in day_meta.items():
        day = {'date': date_str, 'spot': meta['spot'],
               'mon': {'expiry': meta['mon']['expiry'], 'dte': meta['mon']['dte'], 'calls': [], 'puts': []},
               'fri': {'expiry': meta['fri']['expiry'], 'dte': meta['fri']['dte'], 'calls': [], 'puts': []}}
        for which in ('mon', 'fri'):
            by_cp = results.get(date_str, {}).get(which, {})
            calls = sorted(by_cp.get('C', []), key=lambda x: x['strike'])
            puts = sorted(by_cp.get('P', []), key=lambda x: x['strike'])
            day[which]['calls'] = calls
            day[which]['puts'] = puts
        chains.append(day)

    json.dump(chains, open(out_file, 'w'))
    n_mon = sum(len(c['mon']['puts']) for c in chains)
    n_fri = sum(len(c['fri']['puts']) for c in chains)
    n_mon_c = sum(len(c['mon']['calls']) for c in chains)
    n_fri_c = sum(len(c['fri']['calls']) for c in chains)
    print(f"完成: {len(chains)} 天 -> {out_file}")
    print(f"  周一到期: put {n_mon} / call {n_mon_c}")
    print(f"  周五到期: put {n_fri} / call {n_fri_c}")


if __name__ == '__main__':
    main()
