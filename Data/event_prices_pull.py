#!/usr/bin/env python3
"""批量拉取事件研究所需标的的日线数据（Polygon），保存为 data/event_prices.json"""
import json, time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

API_KEY = "8MCOdzsVgnUaFCzn4yqZHckAvTJKbh6D"
BASE = "https://api.polygon.io"
ET = ZoneInfo("America/New_York")
START, END = "2026-06-01", "2026-09-14"

# 事件研究涉及的标的（美股 + ADR）。三星(韩)、海力士韩股 Polygon 无覆盖，另行处理。
TICKERS = ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "GOOGL", "MSFT",
           "AMZN", "META", "QQQ", "TCEHY", "SKHY"]

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0"})


def pull(ticker):
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{START}/{END}"
    rows = []
    for attempt in range(3):
        try:
            r = s.get(url, params={"apiKey": API_KEY, "adjusted": "false",
                                   "sort": "asc", "limit": 50000}, timeout=30)
            if r.status_code == 200:
                for res in r.json().get("results", []):
                    ts = datetime.fromtimestamp(res["t"] / 1000, tz=ET)
                    rows.append([ts.strftime("%Y-%m-%d"), res["o"], res["h"],
                                 res["l"], res["c"], res["v"]])
                return rows
            elif r.status_code == 429:
                time.sleep(2)
        except Exception:
            time.sleep(1)
    return rows


out = {}
for tk in TICKERS:
    rows = pull(tk)
    out[tk] = rows
    print(f"{tk}: {len(rows)} 行  {rows[0][0] if rows else '-'} ~ {rows[-1][0] if rows else '-'}")
    time.sleep(0.3)

json.dump(out, open("/Users/gavinz/git/finance/data/event_prices.json", "w"), indent=1)
print("已保存 -> /Users/gavinz/git/finance/data/event_prices.json")
