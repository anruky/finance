#!/usr/bin/env python3
"""
SKHY 早盘快照拉取：报告「现在如何买」改用早盘价（替代全天 vw）
=============================================================
背景：SKHY 是次新股 ADR，全天成交量加权价（vw）会被盘中暴涨暴跌污染，
用户实际在早盘（美东 ~10:00）下单，报告应展示早盘价。

Polygon 数据可得性：
- 股票 SKHY：分钟级 aggs 可用 -> 能精确取 10:00 ET 分钟价
- 期权 O:SKHY...：只有日级 aggs（分钟级/小时级 resultsCount=0，无分时数据）
  -> 最接近「早盘」的期权价 = 日级 open 价（9:30 ET 开盘价）

输出: data/SKHY_intraday_snapshot.json
结构:
{
  "date": "2026-09-21",
  "spot_close": 188.86,      # 收盘价（仅参考）
  "spot_open": 188.31,       # 开盘价 9:30（parity 用这个口径）
  "spot_1000": 188.28,       # 10:00 ET 分钟价（用户下单时点）
  "expiry": "2026-09-25",
  "dte": 4,
  "puts":  {strike: open价},
  "calls": {strike: open价}
}
"""
import json
import os
import time
import requests
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = timezone(timedelta(hours=-4))  # 夏令时兜底

API_KEY = "8MCOdzsVgnUaFCzn4yqZHckAvTJKbh6D"
BASE = "https://api.polygon.io"
DATA_DIR = "/Users/gavinz/git/finance/data"
TICKER = "SKHY"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def make_ticker(expiry_date, cp, strike):
    yy, mm, dd = expiry_date[2:4], expiry_date[5:7], expiry_date[8:10]
    s = int(round(strike * 1000))
    return f"O:{TICKER}{yy}{mm}{dd}{cp}{s:08d}"


def get(url, params):
    for _ in range(6):
        try:
            r = SESSION.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(4)
            else:
                return None
        except Exception:
            time.sleep(2)
    return None


def main():
    # 1. 最新交易日 + 收盘价
    stock = json.load(open(f"{DATA_DIR}/{TICKER}_stock.json"))
    last_date = stock[-1][0]
    last_close = stock[-1][4]

    # 2. 股票日级 -> 官方开盘价 open（9:30 集合竞价，parity 用这个口径）
    spot_open = None
    dd = get(f"{BASE}/v2/aggs/ticker/{TICKER}/range/1/day/{last_date}/{last_date}", {'apiKey': API_KEY})
    if dd and dd.get('results'):
        spot_open = dd['results'][0].get('o')

    # 3. 股票分钟级 -> 取 10:00 ET 分钟价（用户下单时点）
    spot_1000 = None
    d = get(f"{BASE}/v2/aggs/ticker/{TICKER}/range/1/minute/{last_date}/{last_date}",
            {'apiKey': API_KEY, 'adjusted': 'false', 'sort': 'asc'})
    if d and d.get('results'):
        for x in d['results']:
            hm = datetime.fromtimestamp(x['t'] / 1000, ET).strftime('%H:%M')
            if hm == '10:00':
                spot_1000 = x.get('c')
                break
    if spot_1000 is None:
        spot_1000 = spot_open

    # 3. 期权：最新交易日里 dte 最接近 4（最近周五）的到期日，拉所有有成交档的 open 价
    options = json.load(open(f"{DATA_DIR}/{TICKER}_options_3fri.json"))
    last_day = options[-1]
    cand_f = [f for f in last_day['fridays'] if f['dte'] > 0 and (f.get('puts') or f.get('calls'))]
    if not cand_f:
        cand_f = [f for f in last_day['fridays'] if f['dte'] > 0]
    near_f = min(cand_f, key=lambda f: abs(f['dte'] - 4))
    expiry = near_f['expiry']

    puts = {}
    calls = {}
    # 只拉本地已有成交的档（没成交的档 open 也是空）
    for p in near_f.get('puts', []):
        time.sleep(0.6)
        tk = make_ticker(expiry, 'P', p['strike'])
        d = get(f"{BASE}/v2/aggs/ticker/{tk}/range/1/day/{last_date}/{last_date}", {'apiKey': API_KEY})
        if d and d.get('results'):
            puts[p['strike']] = d['results'][0].get('o')
    for c in near_f.get('calls', []):
        time.sleep(0.6)
        tk = make_ticker(expiry, 'C', c['strike'])
        d = get(f"{BASE}/v2/aggs/ticker/{tk}/range/1/day/{last_date}/{last_date}", {'apiKey': API_KEY})
        if d and d.get('results'):
            calls[c['strike']] = d['results'][0].get('o')

    snap = {
        'date': last_date,
        'spot_close': last_close,
        'spot_open': spot_open,
        'spot_1000': spot_1000,
        'expiry': expiry,
        'dte': near_f['dte'],
        'puts': puts,
        'calls': calls,
    }
    out = f"{DATA_DIR}/{TICKER}_intraday_snapshot.json"
    json.dump(snap, open(out, 'w'), indent=2)
    print(f"完成: {out}")
    print(f"  {last_date} spot_open={spot_open} spot_1000={spot_1000} spot_close={last_close}")
    print(f"  expiry={expiry} dte={near_f['dte']}  puts={len(puts)}档  calls={len(calls)}档")
    for k in sorted(puts):
        print(f"    PUT K={k:g} open={puts[k]}")
    for k in sorted(calls):
        print(f"    CALL K={k:g} open={calls[k]}")


if __name__ == '__main__':
    main()
