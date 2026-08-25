#!/usr/bin/env python3
"""
SKHY (SK海力士美股 ADR) 多周五到期日期权拉取 (未来 3 个周五)
=============================================================
与 hedge/dram/data_puller_3fri.py 同逻辑，仅 TICKER 改为 SKHY。
SKHY 于 2026-07-13 在 Nasdaq 上市（ADR，1 ADR = 1/10 韩国普通股），历史约 1.5 个月。

对每个交易日拉"未来 3 个周五"到期日的 near-ATM 期权链，
用于"7天轮动"回测(选 dte 最接近 7 天的那个周五到期日)。

数据源: Polygon.io
输出: /Users/gavinz/git/finance/data/SKHY_options_3fri.json
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
TICKER = "SKHY"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

US_HOLIDAYS = {
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
    '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25',
}


def next_n_fridays(date_str, n):
    """未来 n 个周五(不含当天), 周五休市则顺延到周四"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    offset = (4 - d.weekday()) % 7
    if offset == 0:
        offset = 7
    cur = d + timedelta(days=offset)
    fridays = []
    for _ in range(n):
        f = cur
        while f.strftime('%Y-%m-%d') in US_HOLIDAYS:
            f -= timedelta(days=1)
        fridays.append(f.strftime('%Y-%m-%d'))
        cur += timedelta(days=7)
    return fridays


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
    ap.add_argument('--start', default='2026-07-13')
    ap.add_argument('--end', default='2026-08-24')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    stock_file = f"{DATA_DIR}/{TICKER}_stock.json"
    out_file = f"{DATA_DIR}/{TICKER}_options_3fri.json"
    rows = json.load(open(stock_file))
    rows = [r for r in rows if args.start <= r[0] <= args.end]
    if args.limit > 0:
        rows = rows[:args.limit]
    print(f"交易日: {len(rows)} 天 ({rows[0][0]} ~ {rows[-1][0]})")

    # 构建任务
    tasks = []  # (date_str, expiry, cp, strike, fri_idx)
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
        fridays = next_n_fridays(date_str, 3)
        day_meta[date_str] = {'spot': spot, 'fridays': [
            {'expiry': e, 'dte': (datetime.strptime(e, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days}
            for e in fridays]}
        for fi, exp in enumerate(fridays):
            for k in strikes:
                for cp in ('C', 'P'):
                    tasks.append((date_str, exp, cp, k, fi))

    print(f"共 {len(tasks)} 个合约任务，并发拉取中...")

    results = {}  # date -> fi -> cp -> [records]
    done = 0
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = {}
        for date_str, expiry, cp, strike, fi in tasks:
            tk = make_ticker(expiry, cp, strike)
            futs[ex.submit(pull_contract, tk, date_str)] = (date_str, cp, strike, fi)
        for fut in as_completed(futs):
            date_str, cp, strike, fi = futs[fut]
            res = fut.result()
            done += 1
            if res is not None:
                rec = {'strike': strike, 'c': res['c'], 'vw': res['vw'], 'v': res['v']}
                results.setdefault(date_str, {}).setdefault(fi, {}).setdefault(cp, []).append(rec)
            if done % 8000 == 0:
                print(f"    ...{done}/{len(tasks)}")

    # 组装
    chains = []
    for date_str, meta in day_meta.items():
        day = {'date': date_str, 'spot': meta['spot'], 'fridays': []}
        for fi, fm in enumerate(meta['fridays']):
            by_cp = results.get(date_str, {}).get(fi, {})
            calls = sorted(by_cp.get('C', []), key=lambda x: x['strike'])
            puts = sorted(by_cp.get('P', []), key=lambda x: x['strike'])
            day['fridays'].append({'expiry': fm['expiry'], 'dte': fm['dte'], 'calls': calls, 'puts': puts})
        chains.append(day)

    json.dump(chains, open(out_file, 'w'))
    total_puts = sum(len(f['puts']) for c in chains for f in c['fridays'])
    print(f"完成: {len(chains)} 天 -> {out_file}")
    print(f"  3 个周五到期日 put 记录总数: {total_puts}")


if __name__ == '__main__':
    main()
