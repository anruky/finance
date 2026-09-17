#!/usr/bin/env python3
"""
拉取 DRAM / SKHY / SNDK 三标的的"现在"实时技术指标快照
========================================================
用途: 更新 summary_report.html 里"技术指标 & Put 报价"表 + "现价"列。

数据源: Polygon.io
  - 股票实时快照: /v2/snapshot/locale/us/markets/stocks/tickers/{T}
  - 日线聚合(算 MA20): /v2/aggs/ticker/{T}/range/1/day/...
  - 期权合约列表(找 ATM 行权价): /v3/reference/options/contracts
  - 期权当日聚合(取实时 vw): /v2/aggs/ticker/{O:...}/range/1/day/...

输出: /Users/gavinz/git/finance/data/realtime_snapshot.json
结构:
  {
    "asof": "2026-08-31 09:57 ET",
    "note": "Polygon 标准行情, 约 15 分钟延迟",
    "DRAM": {"spot":56.13, "prev_close":55.83, "chg_pct":0.64,
             "ma20":55.9, "vs_ma20":0.4,
             "atm_strike":56.0, "expiry":"2026-09-04",
             "put_vw":1.36, "put_last":1.37, "cost_ratio":4.8}, ...
  }
"""
import json
import time
import requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

API_KEY = "8MCOdzsVgnUaFCzn4yqZHckAvTJKbh6D"
BASE = "https://api.polygon.io"
DATA = "/Users/gavinz/git/finance/data"

TICKERS = ["DRAM", "SKHY", "SNDK"]

# 美股统一用美国东部时间（ET，含夏令时 EDT / 冬令时 EST 自动切换）
ET = ZoneInfo("America/New_York")


def et_now():
    """美国东部时间当前时刻（aware datetime）"""
    return datetime.now(ET)


def et_today():
    """美国东部时间「今天」的日期（美股交易日口径）"""
    return et_now().date()

# 美股休市日（周五休市时周度期权到期顺延到周四）
US_HOLIDAYS = {
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
    '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25',
}


def next_friday(d=None):
    """下一个周五（不含今天）；周五若休市则顺延到周四。返回 date 对象。"""
    d = d or et_today()
    offset = (4 - d.weekday()) % 7
    if offset == 0:
        offset = 7
    friday = d + timedelta(days=offset)
    while friday.strftime('%Y-%m-%d') in US_HOLIDAYS:
        friday -= timedelta(days=1)
    return friday

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def get(url, params=None):
    for _ in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def fetch_stock_snapshot(ticker):
    d = get(f"{BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            {'apiKey': API_KEY})
    if not d or 'ticker' not in d:
        return None
    t = d['ticker']
    spot = t.get('min', {}).get('c') or t.get('day', {}).get('c')
    return dict(spot=spot,
                prev_close=t['prevDay']['c'],
                chg_pct=t['todaysChangePerc'],
                chg=t['todaysChange'])


def fetch_daily_closes(ticker, start='2026-06-15', end=None):
    if end is None:
        end = et_today().strftime('%Y-%m-%d')
    d = get(f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
            {'apiKey': API_KEY, 'limit': 50000})
    if not d:
        return []
    bars = d.get('results') or []
    out = []
    for b in bars:
        dt = datetime.utcfromtimestamp(b['t'] / 1000).strftime('%Y-%m-%d')
        out.append((dt, b['c']))
    return sorted(out)


def fetch_atm_strike(ticker, spot):
    d = get(f"{BASE}/v3/reference/options/contracts", {
        'underlying_ticker': ticker, 'contract_type': 'put',
        'expiration_date': EXPIRY, 'limit': 1000, 'apiKey': API_KEY})
    if not d:
        return None
    strikes = [r['strike_price'] for r in d.get('results', [])]
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s - spot))


def fetch_option_price(ticker, strike):
    yy, mm, dd = EXPIRY[2:4], EXPIRY[5:7], EXPIRY[8:10]
    s = int(round(strike * 1000))
    ct = f"O:{ticker}{yy}{mm}{dd}P{s:08d}"
    # 美东时间是"今天"的基准; 期权当日价格取最近一个已收盘交易日(往回查 7 天)
    today = et_today()
    start = today - timedelta(days=7)
    d = get(f"{BASE}/v2/aggs/ticker/{ct}/range/1/day/{start.strftime('%Y-%m-%d')}/{today.strftime('%Y-%m-%d')}",
            {'apiKey': API_KEY})
    bars = d.get('results') if d else []
    if bars:
        b = bars[-1]
        return dict(vw=b.get('vw'), last=b.get('c'), volume=b.get('v'), contract=ct)
    return dict(vw=None, last=None, volume=0, contract=ct)


def main():
    global EXPIRY
    EXPIRY = next_friday().strftime('%Y-%m-%d')
    today = et_today().strftime('%Y-%m-%d')
    snap = {"asof": et_now().strftime('%Y-%m-%d %H:%M') + " (美东 ET)",
            "note": "Polygon 标准行情，约 15 分钟延迟",
            "today": today, "expiry": EXPIRY}

    for tk in TICKERS:
        st = fetch_stock_snapshot(tk)
        if st is None:
            print(f"{tk}: 股票快照失败")
            continue
        spot = st['spot']
        closes = fetch_daily_closes(tk)
        # 排除美东「今天」尚未收盘的 partial bar，只取已完成的收盘价算 MA20
        completed = [(d, c) for d, c in closes if d < today]
        last20 = [c for _, c in completed[-20:]]
        ma20 = sum(last20) / len(last20) if last20 else spot
        vs_ma20 = (spot / ma20 - 1) * 100
        atm = fetch_atm_strike(tk, spot)
        opt = fetch_option_price(tk, atm) if atm is not None else None
        cost_ratio = None
        if opt and opt['vw'] is not None and spot:
            cost_ratio = opt['vw'] * 200 / (spot * 100) * 100
        snap[tk] = dict(
            spot=round(spot, 2), prev_close=st['prev_close'],
            chg_pct=round(st['chg_pct'], 2), chg=round(st['chg'], 3),
            ma20=round(ma20, 2), vs_ma20=round(vs_ma20, 2),
            last_close=completed[-1][1] if completed else None,
            last_close_date=completed[-1][0] if completed else None,
            atm_strike=atm, expiry=EXPIRY,
            put_vw=round(opt['vw'], 2) if opt and opt['vw'] is not None else None,
            put_last=round(opt['last'], 2) if opt and opt['last'] is not None else None,
            put_volume=opt['volume'] if opt else 0,
            cost_ratio=round(cost_ratio, 2) if cost_ratio is not None else None,
        )
        print(f"{tk}: spot={snap[tk]['spot']} prev_close={st['prev_close']} "
              f"chg%={snap[tk]['chg_pct']} ma20={snap[tk]['ma20']} "
              f"vs_ma20={snap[tk]['vs_ma20']}% atm_strike={atm} "
              f"put_vw={snap[tk]['put_vw']} cost_ratio={snap[tk]['cost_ratio']}%")

    out = f"{DATA}/realtime_snapshot.json"
    json.dump(snap, open(out, 'w'), ensure_ascii=False, indent=2)
    print(f"\n已写入: {out}")


if __name__ == '__main__':
    main()
