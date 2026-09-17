#!/usr/bin/env python3
"""
SKHY（SK海力士美股 ADR）对冲策略最终报告生成器 —— 自适应策略版
================================================================
策略（2026-09-15 定版）：每轮入场按 put/call 相对贵贱动态切换结构
  · put 比 call 贵        → 1 call + 1 put（跨式，纯做多波动）
  · put 比 call 便宜/相等 → 2 put + 100 股（股票 + 2张put对冲）

扫描：周期 target ∈ {2,7,14,21} × 跌熔断 × 涨熔断，找最优。
结算口径：熔断/到期/持有中一律按内在价值结算（消除前视偏差）。

复用 skhy_adaptive.run_adaptive 作为回测核心。
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SK = os.path.dirname(os.path.abspath(__file__))
DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = os.path.join(SK, "skhy_final_report.html")

import sys
sys.path.insert(0, SK)
import skhy_adaptive as A
import real_options_backtest_v10 as v10mod

run_adaptive = A.run_adaptive
round_mdd = A.round_mdd
load_3fri = v10mod.load_3fri
load_stock = v10mod.load_stock
bh_benchmark = v10mod.bh_benchmark
run_v10 = v10mod.run_v10

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
TARGETS = [2, 7, 14, 21]
DOWNS = [5, 8, 10, 12, 15, 20, 25]
UPS = [5, 8, 10, 12, 15, 20, 25]


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def _ma(arr, k):
    out = [None] * len(arr)
    for i in range(len(arr)):
        if i + 1 >= k:
            out[i] = sum(arr[i - k + 1:i + 1]) / k
    return out


def _ema(arr, k):
    out = [None] * len(arr)
    m = 2 / (k + 1)
    prev = None
    for i, v in enumerate(arr):
        prev = v if prev is None else prev * (1 - m) + v * m
        out[i] = prev
    return out


def build_indicator_board(stock):
    """计算 SKHY 常用技术指标，返回 {svg, latest} 供报告嵌入。"""
    import math
    dates = [r[0] for r in stock]
    opens = [r[1] for r in stock]
    highs = [r[2] for r in stock]
    lows = [r[3] for r in stock]
    closes = [r[4] for r in stock]
    vols = [r[5] for r in stock]
    n = len(stock)

    ma5 = _ma(closes, 5); ma10 = _ma(closes, 10); ma20 = _ma(closes, 20)
    e12 = _ema(closes, 12); e26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    macd_hist = [(d - e) * 2 for d, e in zip(dif, dea)]

    rsi14 = [None] * n
    gains, losses = [], []
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0)); losses.append(max(-ch, 0))
    if n > 14:
        avg_g = sum(gains[:14]) / 14; avg_l = sum(losses[:14]) / 14
        for i in range(14, n):
            rs = avg_g / avg_l if avg_l > 0 else 100
            rsi14[i] = 100 - 100 / (1 + rs)
            avg_g = (avg_g * 13 + gains[i - 1]) / 14
            avg_l = (avg_l * 13 + losses[i - 1]) / 14

    boll_mid = ma20
    boll_up = [None] * n; boll_dn = [None] * n
    for i in range(n):
        if boll_mid[i] is not None:
            w = closes[i - 19:i + 1]
            sd = (sum((x - boll_mid[i]) ** 2 for x in w) / 20) ** 0.5
            boll_up[i] = boll_mid[i] + 2 * sd
            boll_dn[i] = boll_mid[i] - 2 * sd

    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = _ma(trs, 14)
    vma5 = _ma(vols, 5); vma10 = _ma(vols, 10)

    last = n - 1
    latest = dict(
        close=closes[last], ma5=ma5[last], ma10=ma10[last], ma20=ma20[last],
        dif=dif[last], dea=dea[last], macd=macd_hist[last], rsi=rsi14[last],
        boll_up=boll_up[last], boll_mid=boll_mid[last], boll_dn=boll_dn[last],
        atr=atr[last], atr_pct=atr[last] / closes[last] * 100 if atr[last] else 0,
        vma5=vma5[last], vma10=vma10[last],
    )

    UP = "#E24B4A"; DOWN = "#26c281"; TEXT = "#e6e8ec"; MUTED = "#9aa3b2"; GRID = "rgba(154,163,178,0.10)"
    C20 = "#c792ea"
    W = 680; L = 54; R = 668
    def px(i): return L + (R - L) * (i + 0.5) / n
    p_t, p_b = 18, 210
    def py(v):
        return p_t + (p_b - p_t) * (200.0 - v) / (200.0 - 120.0)
    def seg(pts, c, w=1.4):
        return f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{c}" stroke-width="{w}"/>'
    s = []
    for v in [120, 140, 160, 180, 200]:
        y = py(v)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{R}" y2="{y:.1f}" stroke="{GRID}"/>')
        s.append(f'<text x="{L-7}" y="{y+4:.1f}" fill="{MUTED}" font-size="10" text-anchor="end">${v}</text>')
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        col = UP if c >= o else DOWN
        x = px(i); yc, yo, yh, yl = py(c), py(o), py(h), py(l)
        bt = min(yc, yo); bh = max(abs(yc - yo), 1.2)
        s.append(f'<line x1="{x:.1f}" y1="{yh:.1f}" x2="{x:.1f}" y2="{yl:.1f}" stroke="{col}" stroke-width="1"/>')
        s.append(f'<rect x="{x-5:.1f}" y="{bt:.1f}" width="10" height="{bh:.1f}" fill="{col}"/>')
    s.append(seg([(px(i), py(v)) for i, v in enumerate(ma20) if v is not None], C20, 1.6))
    s.append(f'<text x="{L}" y="{p_t+14}" fill="{TEXT}" font-size="12" font-weight="600">SKHY · K线 + 均线(MA20)</text>')
    s.append(f'<circle cx="{R}" cy="{p_t+10}" r="3" fill="{C20}"/><text x="{R+6}" y="{p_t+14}" fill="{MUTED}" font-size="10">MA20</text>')
    for j in range(0, n, max(1, n // 6)):
        s.append(f'<text x="{px(j):.1f}" y="{p_b+18}" fill="{MUTED}" font-size="10" text-anchor="middle">{dates[j][5:]}</text>')
    svg = '<svg viewBox="0 0 680 240" xmlns="http://www.w3.org/2000/svg" role="img">\n' + "\n".join(s) + '\n</svg>'
    return dict(svg=svg, latest=latest)


def main():
    data, day_map = load_3fri()
    stock, closes, bars = load_stock()
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]
    meta = dict(entry_date=stock[0][0], entry_price=stock_entry,
                exit_date=stock[-1][0], exit_price=stock_exit, n_days=len(stock))

    bh = bh_benchmark(stock, closes)
    bh_mdd_abs = bh["mdd"]
    bh_ratio_abs = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0

    # ============ 全空间扫描：周期 × 跌熔断 × 涨熔断 ============
    results = []
    for t in TARGETS:
        for down in DOWNS:
            for up in UPS:
                r = run_adaptive(day_map, closes, bars, stock, down, t, up_pct=up)
                mdd = round_mdd(r["rounds"], lambda rd: rd["pnl"])
                r["down"] = down; r["up"] = up; r["target"] = t
                r["mdd"] = mdd
                r["ratio"] = r["total"] / mdd if mdd > 0 else 0
                results.append(r)
    print(f"扫描完成: {len(results)} 组（周期 {len(TARGETS)} × 跌 {len(DOWNS)} × 涨 {len(UPS)}）")

    best = max(results, key=lambda x: x["ratio"])
    best_total = max(results, key=lambda x: x["total"])
    print(f"最优(收益/回撤比): 周期{best['target']} 跌{best['down']}%/涨{best['up']}% "
          f"-> 收益${best['total']:+,.0f} 回撤${best['mdd']:,.0f} 比{best['ratio']:.2f}")
    print(f"最优(总收益): 周期{best_total['target']} 跌{best_total['down']}%/涨{best_total['up']}% "
          f"-> 收益${best_total['total']:+,.0f}")

    # 固定 2put / 固定跨式 作为对比基准（同参数，逐轮累计回撤口径）
    f2p = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit,
                  best["down"], best["target"], num_puts=2, up_pct=best["up"])
    f2p_rounds = [dict(entry_date=rd["entry_date"], pnl=rd["stock_pnl"] + rd["pnl"]) for rd in f2p["rounds"]]
    f2p_sum = sum(r["pnl"] for r in f2p_rounds)
    f2p_mdd = round_mdd(f2p_rounds, lambda rd: rd["pnl"])
    f2p_ratio = f2p_sum / f2p_mdd if f2p_mdd > 0 else 0

    import rescan_skhy_straddle as st
    fst = st.run_straddle(day_map, closes, bars, stock, best["down"], best["target"], up_pct=best["up"])
    fst_rounds = [dict(entry_date=rd["entry_date"], pnl=rd["pnl"]) for rd in fst["rounds"]]
    fst_sum = sum(r["pnl"] for r in fst_rounds)
    fst_mdd = round_mdd(fst_rounds, lambda rd: rd["pnl"])
    fst_ratio = fst_sum / fst_mdd if fst_mdd > 0 else 0

    # ============ 熔断矩阵（固定最优周期）============
    def mat(field, kind):
        mat_dict = {}
        vals = []
        for down in DOWNS:
            row = []
            for up in UPS:
                r = next(x for x in results if x["target"] == best["target"] and x["down"] == down and x["up"] == up)
                v = r[field]
                row.append(v)
                vals.append(v)
            mat_dict[down] = row
        return mat_dict, vals

    pnl_mat, pnl_vals = mat("total", "pnl")
    ratio_mat, ratio_vals = mat("ratio", "ratio")

    def matrix_html(mat, vals, kind, title, as_money=True):
        head = "".join(f"<th>涨{up}%</th>" for up in UPS)
        rows = []
        for down in DOWNS:
            tds = []
            for i in range(len(UPS)):
                v = mat[down][i]
                is_best = (down == best["down"] and UPS[i] == best["up"])
                txt = f"${v:+,.0f}" if as_money else f"{v:.2f}"
                mark = " ★" if is_best else ""
                if is_best:
                    cls = "c-gold"
                elif kind == "pnl":
                    cls = "c-red" if v > 0 else "c-green"
                else:
                    cls = ""
                tds.append(f'<td class="{cls}">{txt}{mark}</td>')
            rows.append(f"<tr><td>{down}%</td>{''.join(tds)}</tr>")
        return (f'<div style="margin-top:6px;"><h3 style="font-size:15px;color:var(--text);margin:18px 0 8px;">{title}</h3>'
                f'<table><tr><th>跌\\涨</th>{head}</tr>{"".join(rows)}</table></div>')

    pnl_matrix_html = matrix_html(pnl_mat, pnl_vals, "pnl", "熔断矩阵 —— 总收益（周期=最近周五）")
    ratio_matrix_html = matrix_html(ratio_mat, ratio_vals, "ratio", "熔断矩阵 —— 收益/回撤比（周期=最近周五）", as_money=False)

    # ============ 周期敏感性（固定最优熔断）============
    target_rows = []
    for t in TARGETS:
        r = next(x for x in results if x["target"] == t and x["down"] == best["down"] and x["up"] == best["up"])
        is_best = (t == best["target"])
        mark = ' <span class="c-gold">★</span>' if is_best else ""
        target_rows.append(
            f'<tr><td>{TARGET_LABELS[t]}</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>${r["mdd"]:,.0f}</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td>'
            f'<td>跨式{r["n_straddle"]} / 2put{r["n_2put"]}</td></tr>'
        )
    target_rows_html = "\n".join(target_rows)

    # ============ 最优组合逐轮明细 ============
    detail_rows = []
    for rd in reversed(best["rounds"]):
        struct_txt = ("<span class='c-gold'>跨式</span>" if rd["struct"] == "straddle"
                      else "<span class='c-red'>2put</span>")
        if rd["kind"] == "持有中":
            exit_cell = f"<td>{rd.get('expiry', rd['exit_date'])} 到期</td>"
        else:
            exit_cell = f"<td>{rd['exit_date']}</td>"
        chg = (rd["exit_spot"] / rd["entry_spot"] - 1) * 100
        detail_rows.append(
            f'<tr><td>{rd["entry_date"]}</td>{exit_cell}<td>{rd["kind"]}</td>'
            f'<td>{struct_txt}</td>'
            f'<td>${rd["entry_spot"]:.1f}</td><td>${rd["exit_spot"]:.1f}</td>'
            f'<td class="{pc(chg)}">{chg:+.1f}%</td>'
            f'<td>${rd["strike"]:g}</td>'
            f'<td>${rd["put_price"]:.2f}</td><td>${rd["call_price"]:.2f}</td>'
            f'<td class="c-green">${rd["cost"]:,.0f}</td>'
            f'<td class="c-red">${rd["income"]:+,.0f}</td>'
            f'<td class="{pc(rd["pnl"])}">${rd["pnl"]:+,.0f}</td></tr>'
        )
    detail_html = "\n".join(detail_rows)

    # ============ 现在如何买（基于最新数据做 adaptive 决策）============
    last_day = data[-1]
    latest_date = last_day["date"]
    last_spot = closes[stock[-1][0]]  # 用最新收盘价
    near_f = min([f for f in last_day["fridays"] if f["dte"] > 0], key=lambda f: abs(f["dte"] - best["target"]))
    near_atm_put = min(near_f["puts"], key=lambda p: abs(p["strike"] - last_spot))
    near_strike = near_atm_put["strike"]
    near_put_vw = near_atm_put["vw"]
    near_call = next((x for x in near_f.get("calls", []) if abs(x["strike"] - near_strike) < 1e-9), None)
    near_call_vw = near_call["vw"] if near_call else None
    near_expiry = near_f["expiry"]
    near_dte = near_f["dte"]

    if near_call_vw is not None:
        if near_put_vw > near_call_vw:
            now_struct = "跨式（1 call + 1 put）"
            now_cost = (near_put_vw + near_call_vw) * 100
            now_reason = f'put ${near_put_vw:.2f} &gt; call ${near_call_vw:.2f}，put 更贵 → 买便宜 call 抓波动'
        else:
            now_struct = "2 put + 100 股"
            now_cost = near_put_vw * 200
            now_reason = f'put ${near_put_vw:.2f} ≤ call ${near_call_vw:.2f}，put 更便宜 → 用便宜 put 对冲 + 股票吃慢牛'
    else:
        now_struct = "数据缺 call，无法判断"
        now_cost = near_put_vw * 200
        now_reason = "最新期权链缺同档 call 数据"

    up_line = last_spot * (1 + best["up"] / 100.0)
    dn_line = last_spot * (1 - best["down"] / 100.0)

    # 技术指标
    indic = build_indicator_board(stock)
    ind = indic["latest"]
    _price_vs_ma20 = "站上" if ind["close"] > ind["ma20"] else "跌破"
    _trend = "多头" if ind["close"] > ind["ma20"] else "空头"

    # 三策略对比
    def cmp_row(name, total, mdd, ratio, extra, is_best):
        mark = ' <span class="c-gold">★最优</span>' if is_best else ""
        return (f'<tr><td>{name}{mark}</td>'
                f'<td class="{pc(total)}">${total:+,.0f}</td>'
                f'<td>${mdd:,.0f}</td>'
                f'<td class="c-gold">{ratio:.2f}</td>'
                f'<td>{extra}</td></tr>')

    best_name = max([("自适应", best["total"], best["ratio"]),
                     ("固定2put", f2p_sum, f2p_ratio),
                     ("固定跨式", fst_sum, fst_ratio)], key=lambda x: x[2])[0]
    cmp_html = (
        cmp_row("自适应（put贵→跨式，put便宜→2put）", best["total"], best["mdd"], best["ratio"],
                f'{best["n_rounds"]} 轮 · 跨式{best["n_straddle"]} / 2put{best["n_2put"]}', best_name == "自适应") +
        cmp_row("固定 2put（100股+2put）", f2p_sum, f2p_mdd, f2p_ratio, f'{len(f2p_rounds)} 轮', best_name == "固定2put") +
        cmp_row("固定 跨式（1call+1put）", fst_sum, fst_mdd, fst_ratio, f'{len(fst_rounds)} 轮', best_name == "固定跨式") +
        cmp_row("B&H（持有100股）", bh["total"], bh_mdd_abs, bh_ratio_abs, f'{meta["n_days"]} 交易日', best_name == "B&H")
    )

    css = """
:root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }
.wrap { max-width:1120px; margin:0 auto; }
h1 { font-size:26px; margin-bottom:6px; }
h2 { font-size:19px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }
h3 { font-size:15px; margin:18px 0 8px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }
.kpi .label { color:var(--muted); font-size:12px; }
.kpi .value { font-size:22px; font-weight:700; margin-top:4px; }
.kpi .sub { color:var(--muted); font-size:12px; margin-top:2px; margin-bottom:0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }
th { background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }
th:first-child, td:first-child { text-align:left; }
.c-red { color:var(--red); font-weight:600; }
.c-green { color:var(--green); font-weight:600; }
.c-gray { color:var(--muted); }
.c-gold { color:var(--gold); font-weight:700; }
.callout { background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }
.callout-gold { background:rgba(245,195,68,.08); border:1px solid rgba(245,195,68,.35); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }
.callout-warn { background:rgba(245,195,68,.06); border:1px solid rgba(245,195,68,.3); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }
.note { color:var(--muted); font-size:12px; margin-top:8px; }
.tbl-scroll { overflow-x:auto; }
code { background:#20242d; border:1px solid var(--border); border-radius:4px; padding:1px 6px;
  font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; color:var(--gold); }
"""

    def kpi(label, value_html, sub=""):
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value_html}</div><div class="sub">{sub}</div></div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SKHY 对冲策略最终报告（自适应结构切换版）</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>SKHY 对冲策略最终报告 <span style="color:var(--muted);font-size:15px;">（自适应结构切换 · put贵→跨式 / put便宜→2put）</span></h1>
<p class="sub">数据源：SKHY_stock.json（{meta['n_days']} 交易日）+ SKHY_options_3fri.json（真实 3 周五到期日期权链，含 call/put） · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="card">
<h2 style="margin-top:0;">行情与技术指标</h2>
<div style="margin-bottom:12px;">{indic['svg']}</div>
<div class="tbl-scroll">
<table>
<tr><th>指标</th><th>最新值</th><th>信号解读</th></tr>
<tr><td>现价</td><td class="c-red">${ind['close']:.2f}</td><td>{_price_vs_ma20} MA20（{ind['ma20']:.2f}）</td></tr>
<tr><td>均线 MA20</td><td class="c-red">{ind['ma20']:.2f}</td><td>{_trend}（现价{_price_vs_ma20}均线）</td></tr>
<tr><td>ATM Put（现价档）</td><td>${near_put_vw:.2f}/股</td><td>行权价 ${near_strike:.0f} · 到期 {near_expiry}（dte {near_dte}）</td></tr>
<tr><td>ATM Call（同档）</td><td>{('$%.2f/股' % near_call_vw) if near_call_vw is not None else '—'}</td><td>put/call 贵贱 → 决定结构</td></tr>
</table>
</div>
<p class="note">说明：SKHY 上市仅 {meta['n_days']} 个交易日，MA20 样本偏短、信号仅供参考。</p>
</div>

<div class="card">
<h2>策略模型（自适应结构切换）</h2>
<div class="callout">
<strong>每轮入场时看 ATM 期权的 put 权利金 vs call 权利金</strong>，动态切换结构：<br>
· <strong>put 比 call 贵</strong>（skew 大、市场担忧下跌）→ 买 <strong>1 call + 1 put（跨式）</strong>，不持股票，纯做多波动；<br>
· <strong>put 比 call 便宜/相等</strong>（慢牛/乐观）→ 买 <strong>2 put + 100 股</strong>，股票吃慢牛上涨、2张便宜 put 对冲。 <br>
本质是把「put skew」这个因子变成每轮的择时开关。
</div>
<div class="callout-gold">
<strong>熔断（不对称）</strong>：开盘价相对入场价 <strong class="c-green">跌 {best['down']}%</strong> 或 <strong class="c-red">涨 {best['up']}%</strong> 就开盘平仓 + 重买；盘中不触发。没触发就持有到期，再滚动下一轮。<br>
<strong>周期</strong>：{TARGET_LABELS[best['target']]}（买入 dte 最接近该值的周五到期期权）。<br>
<strong>结算口径</strong>：熔断/到期/持有中一律按<strong>内在价值</strong>结算（2026-09-15 修正前视偏差，涨熔断时虚值 put 归零）。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
<strong>最优组合：{TARGET_LABELS[best['target']]} + 跌 {best['down']}% / 涨 {best['up']}% 熔断（自适应结构切换）。</strong><br>
总收益 <span class="c-red">${best['total']:+,.0f}</span>（B&H 为 ${bh['total']:+,.0f}，自适应<strong>少赚 ${(best['total']-bh['total']):+,.0f}</strong>，但这是用"放弃部分上涨"换来的），
回撤从 B&H 的 <span class="c-green">${bh['mdd']:,.0f}</span> 降到 <strong>${best['mdd']:,.0f}</strong>，
收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>（B&H 仅 {bh_ratio_abs:.2f}），是 B&H 的 <strong class="c-gold">{best['ratio']/bh_ratio_abs:.1f} 倍</strong>。
</div>
<div class="kpis" style="margin-top:14px;">
{kpi('自适应总收益', money(best['total']), f'共 {best["n_rounds"]} 轮')}
{kpi('回撤(逐轮累计)', f'${best["mdd"]:,.0f}', f'收益/回撤比 {best["ratio"]:.2f}')}
{kpi('结构分布', f'{best["n_straddle"]} : {best["n_2put"]}', f'跨式 {best["n_straddle"]/best["n_rounds"]*100:.0f}% / 2put {best["n_2put"]/best["n_rounds"]*100:.0f}%')}
{kpi('触发统计', f'跌{best["down_hits"]} / 涨{best["up_hits"]} / 到期{best["expiries"]}', '')}
{kpi('B&H 收益', money(bh['total']), f'回撤 ${bh["mdd"]:,.0f} · 比 {bh_ratio_abs:.2f}')}
</div>
<div class="callout-warn">
<strong>⚠️ 但这是一个「孤立的尖峰」</strong>——见下方熔断矩阵，最优点（跌{best['down']}%/涨{best['up']}%）周围一圈参数几乎全是负收益，49 组里只有这 1 个点显著赚钱。
它是 44 个交易日里「某几次 +8%~+9% 上涨 + 两次 -16% 大跌」被刚好框住的产物，<strong>换一段行情这个尖峰就会移动甚至消失</strong>，不能当稳定规律。
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">四策略对比（统一逐轮累计回撤口径）</h2>
<div class="tbl-scroll">
<table>
<tr><th>策略</th><th>总收益</th><th>回撤(绝对金额)</th><th>收益/回撤比</th><th>说明</th></tr>
{cmp_html}
</table>
</div>
<p class="note">回撤 = 累计逐轮盈亏曲线的最大回撤（绝对金额），四种口径统一，可直接对比。B&H 逐轮盈亏 = 每日收盘价相对首日收盘价的涨跌 ×100 股。</p>
</div>

<div class="card">
<h2>熔断比例扫描（不对称矩阵，周期=最近周五）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">★ = 全局最优（回撤比口径）。行 = 跌熔断，列 = 涨熔断。</p>
{pnl_matrix_html}
{ratio_matrix_html}
</div>

<div class="card">
<h2>周期敏感性（固定最优熔断 {best['down']}%/{best['up']}%）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">周期 7/14/21 天全部负收益，只有最近周五（1-4 天）显著为正——SKHY 波动太快，长周期 put 追不上节奏。</p>
<div class="tbl-scroll">
<table>
<tr><th>周期</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th><th>结构分布</th></tr>
{target_rows_html}
</table>
</div>
</div>

<div class="card">
<h2>最优策略逐轮明细：跌 {best['down']}% / 涨 {best['up']}%</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">
「结构」列：<span class="c-gold">跨式</span> = put 比 call 贵时选的 1call+1put；<span class="c-red">2put</span> = put 比 call 便宜时选的 2put+100股。
「成本」列：跨式 = call+put 权利金；2put = 2×put 权利金。「收入」列：跨式 = call/put 结算收入；2put = put 结算收入（股票端已并入利润）。
</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>结构</th><th>入场spot</th><th>出场spot</th><th>波动</th><th>行权价</th><th>put价</th><th>call价</th><th>成本</th><th>收入</th><th>利润</th></tr>
{detail_html}
</table>
</div>
</div>

<div class="card">
<h2>现在如何买（基于最新期权数据 {latest_date}）</h2>
<div class="callout-gold">
最新 SKHY 现价 <strong class="c-gold">${last_spot:.2f}</strong>，最近到期日 <strong>{near_expiry}</strong>（dte {near_dte} 天）。
按自适应策略判断，现在应该选 <strong class="c-gold">{now_struct}</strong>：{now_reason}。
</div>
<ol style="font-size:14px;padding-left:22px;line-height:2.0;">
<li>先看 ATM 期权：put <strong>${near_put_vw:.2f}</strong> vs call <strong>{('$%.2f' % near_call_vw) if near_call_vw is not None else '—'}</strong>（行权价 ${near_strike:.0f}）。</li>
<li>若选<strong>跨式</strong>：买 1 张 call + 1 张 put，成本约 <strong class="c-green">${(near_put_vw+near_call_vw)*100:,.0f}</strong>（{('$%.2f' % near_call_vw) if near_call_vw is not None else '—'} + ${near_put_vw:.2f}）。</li>
<li>若选<strong>2put+100股</strong>：买 100 股（市值 ${last_spot*100:,.0f}）+ 2 张 put，put 成本 <strong class="c-green">${near_put_vw*200:,.0f}</strong>。</li>
<li><strong>熔断线（不对称）</strong>：开盘价涨到 <strong class="c-red">${up_line:.2f}</strong>（涨 {best['up']}%）或跌到 <strong class="c-green">${dn_line:.2f}</strong>（跌 {best['down']}%）就开盘平仓 + 重买（盘中不盯盘）。</li>
<li>没触发熔断就持有到 {near_expiry} 到期，再滚动下一轮。</li>
</ol>
</div>

<div class="card">
<h2>数据与结论说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>⚠️ 数据长度限制</strong>：SKHY 于 2026-07-13 在 Nasdaq 上市（ADR），至今仅 {meta['n_days']} 个交易日（约 6 周）。样本极少，仅 {best['n_rounds']} 轮交易，参数结论可靠性远低于长周期回测。</li>
<li><strong>真实成交价</strong>：call/put 成本用每日期权链的成交量加权价（vw），不是 Black-Scholes 理论价。</li>
<li><strong>多到期日数据</strong>：SKHY_options_3fri.json 每天含 3 个周五到期日 + call/put 双边数据，可真实对比不同周期与结构。</li>
<li><strong>开盘价熔断</strong>：只在美国开盘瞬间判断一次，盘中 low/high 不触发——符合「不盯盘」的实盘操作。</li>
<li><strong>内在价值结算</strong>：熔断/到期/持有中一律按内在价值结算，消除「开盘价触发 + 全天 vw 结算」的前视偏差。</li>
<li><strong>结构切换</strong>：每轮入场用 put_vw 与 call_vw 的比较决定结构，这是把 put skew 当择时信号。</li>
<li><strong>过拟合警示</strong>：最优参数是「孤立尖峰」，高度依赖这段行情节奏，稳定性差，仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""

    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"\n最终报告已生成: {OUT_HTML}")
    print(f"最优: {TARGET_LABELS[best['target']]} + 跌 {best['down']}% / 涨 {best['up']}%, "
          f"收益 ${best['total']:+,.0f}, 回撤 ${best['mdd']:,.0f}, 比 {best['ratio']:.2f}")


if __name__ == "__main__":
    main()
