#!/usr/bin/env python3
"""
SNDK（SanDisk，NAND 闪存/存储公司）对冲策略最终报告生成器
===============================================
涨熔断 × 跌熔断 不对称扫描，找真正最优参数（不沿用 DRAM 的对称 15%）。
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/sandisk/sndk_final_report.html"

# 复用 v10 的核心逻辑
exec(open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0])
OUT_HTML = "/Users/gavinz/git/finance/hedge/sandisk/sndk_final_report.html"  # 覆盖 exec 引入的 v10 输出路径

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
SYM_MOVES = [8, 10, 15, 20]              # 对称参考（周期 × 熔断线）
ASYM_MOVES = [8, 10, 12, 15, 18, 20, 25]  # 不对称扫描（涨/跌独立）


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
    """计算 SNDK 常用技术指标，返回 {svg, latest} 供报告嵌入。"""
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

    # ---- 绘制 SVG（仅主图：K线 + MA20）----
    UP = "#E24B4A"; DOWN = "#26c281"; TEXT = "#e6e8ec"; MUTED = "#9aa3b2"; GRID = "rgba(154,163,178,0.10)"
    C20 = "#c792ea"
    W = 680; L = 54; R = 668
    def px(i): return L + (R - L) * (i + 0.5) / n
    p_t, p_b = 18, 210
    # 动态价格范围（按实际最高/最低价留 6% 余量，适配任意价位股票）
    _lo = min(lows); _hi = max(highs)
    _pad = (_hi - _lo) * 0.06
    _vmin = _lo - _pad; _vmax = _hi + _pad
    def py(v):
        return p_t + (p_b - p_t) * (_vmax - v) / (_vmax - _vmin)
    def seg(pts, c, w=1.4):
        return f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{c}" stroke-width="{w}"/>'
    s = []
    # y 轴 5 档刻度
    for k in range(5):
        v = _vmin + (_vmax - _vmin) * k / 4
        y = py(v)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{R}" y2="{y:.1f}" stroke="{GRID}"/>')
        s.append(f'<text x="{L-7}" y="{y+4:.1f}" fill="{MUTED}" font-size="10" text-anchor="end">${v:,.0f}</text>')
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        col = UP if c >= o else DOWN
        x = px(i); yc, yo, yh, yl = py(c), py(o), py(h), py(l)
        bt = min(yc, yo); bh = max(abs(yc - yo), 1.2)
        s.append(f'<line x1="{x:.1f}" y1="{yh:.1f}" x2="{x:.1f}" y2="{yl:.1f}" stroke="{col}" stroke-width="1"/>')
        s.append(f'<rect x="{x-5:.1f}" y="{bt:.1f}" width="10" height="{bh:.1f}" fill="{col}"/>')
    s.append(seg([(px(i), py(v)) for i, v in enumerate(ma20) if v is not None], C20, 1.6))
    s.append(f'<text x="{L}" y="{p_t+14}" fill="{TEXT}" font-size="12" font-weight="600">SNDK · K线 + 均线(MA20)</text>')
    s.append(f'<circle cx="{R}" cy="{p_t+10}" r="3" fill="{C20}"/><text x="{R+6}" y="{p_t+14}" fill="{MUTED}" font-size="10">MA20</text>')
    for j in range(0, n, max(1, n // 6)):
        s.append(f'<text x="{px(j):.1f}" y="{p_b+18}" fill="{MUTED}" font-size="10" text-anchor="middle">{dates[j][5:]}</text>')
    svg = '<svg viewBox="0 0 680 240" xmlns="http://www.w3.org/2000/svg" role="img">\n' + "\n".join(s) + '\n</svg>'
    series = {}
    for i in range(n):
        series[dates[i]] = dict(
            rsi=rsi14[i],
            atr_pct=(atr[i] / closes[i] * 100 if atr[i] else None),
            vs_m20=((closes[i] / ma20[i] - 1) * 100 if ma20[i] else None),
        )
    return dict(svg=svg, latest=latest, series=series)


def main():
    data, day_map = load_3fri()
    stock, closes, bars = load_stock()
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]

    bh = bh_benchmark(stock, closes)
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0

    # 1. 对称扫描，先确定最优周期
    sym_results = []
    for target in TARGET_LABELS:
        for m in SYM_MOVES:
            r = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, m, target)
            r["target"] = target
            r["move"] = m
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            sym_results.append(r)
    best_sym = max(sym_results, key=lambda x: x["ratio"])
    best_target = best_sym["target"]

    # 2. 不对称扫描（原来的熔断，不带轮空）
    asym_results = []
    for down in ASYM_MOVES:
        for up in ASYM_MOVES:
            r = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, down, best_target, up_pct=up)
            r["down"] = down
            r["up"] = up
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            # 轮空策略总收益 = 普通总收益 - 被跳过轮次（成本>11%）的周期总利润
            _skip_sum = 0.0
            for _rd in r["rounds"]:
                _cp = _rd["put_cost"] / (_rd["entry_spot"] * 100) * 100
                if _cp > 11:
                    _skip_sum += (_rd["stock_pnl"] + _rd["pnl"])
            r["skip_total"] = r["total"] - _skip_sum
            asym_results.append(r)
    best = max(asym_results, key=lambda x: x["ratio"])

    # 最新期权数据(用于"现在如何买")
    last = data[-1]
    last_spot = last["spot"]
    latest_date = last["date"]
    near_f = min([f for f in last["fridays"] if f["dte"] > 0], key=lambda f: abs(f["dte"] - best_target))
    near_atm = min(near_f["puts"], key=lambda p: abs(p["strike"] - last_spot))
    near_expiry = near_f["expiry"]
    near_dte = near_f["dte"]
    near_strike = near_atm["strike"]
    near_vw = near_atm["vw"]
    cost_2 = near_vw * 100 * 2
    up_line = last_spot * (1 + best["up"] / 100.0)
    dn_line = last_spot * (1 - best["down"] / 100.0)

    # 股票端点（供模板动态化）
    meta = dict(
        entry_date=stock[0][0], entry_price=stock_entry,
        exit_date=stock[-1][0], exit_price=stock_exit,
        n_days=len(stock),
    )
    all_closes = [closes[r[0]] for r in stock]
    meta["max_price"] = max(all_closes)
    meta["min_price"] = min(all_closes)

    # DRAM 同期对比：用 DRAM 原策略（7天+15%对称），完整数据延续滚动，算 07-13 后净值变化
    dram_data = json.load(open(os.path.join(DATA, "DRAM_options_3fri.json")))
    dram_day_map = {d["date"]: d for d in dram_data}
    dram_stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    dram_closes = {r[0]: r[4] for r in dram_stock}
    dram_bars = {r[0]: r for r in dram_stock}
    dram_se = dram_closes[dram_stock[0][0]]
    dram_sx = dram_closes[dram_stock[-1][0]]

    def _dram_cf(move_pct, target, num_puts=2):
        cashflow = defaultdict(float)
        pos = None
        d = move_pct / 100.0
        for r in dram_stock:
            date = r[0]; S = dram_closes[date]; o = dram_bars[date][1]
            day = dram_day_map.get(date)
            if pos is None:
                if day is None: continue
                pp = pick_put(day, o, target)
                if pp is None: continue
                cost = pp["vw"] * 100 * num_puts
                pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost)
                cashflow[date] -= cost; continue
            p0 = pos["entry_spot"]
            dn = o <= p0 * (1 - d); up = o >= p0 * (1 + d)
            if date >= pos["expiry"]:
                if dn or up:
                    vw_h = find_put_price(day, pos["expiry"], pos["strike"])
                    payoff = vw_h * 100 * num_puts if vw_h is not None else (max(pos["strike"]-o, 0)*100*num_puts if dn else 0.0)
                    cashflow[date] += payoff; pos = None
                    if day is not None:
                        pp = pick_put(day, o, target)
                        if pp is not None:
                            cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost); cashflow[date] -= cost
                else:
                    payoff = max(pos["strike"]-S, 0)*100*num_puts
                    cashflow[date] += payoff; pos = None
                    if day is not None:
                        pp = pick_put(day, S, target)
                        if pp is not None:
                            cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=S, cost=cost); cashflow[date] -= cost
                continue
            if dn:
                vw_h = find_put_price(day, pos["expiry"], pos["strike"])
                payoff = vw_h * 100 * num_puts if vw_h is not None else max(pos["strike"]-o, 0)*100*num_puts
                cashflow[date] += payoff; pos = None
                if day is not None:
                    pp = pick_put(day, o, target)
                    if pp is not None:
                        cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost); cashflow[date] -= cost
                continue
            if up:
                vw_h = find_put_price(day, pos["expiry"], pos["strike"])
                payoff = vw_h * 100 * num_puts if vw_h is not None else 0.0
                cashflow[date] += payoff; pos = None
                if day is not None:
                    pp = pick_put(day, o, target)
                    if pp is not None:
                        cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost); cashflow[date] -= cost
                continue
        return cashflow

    dram_cf = _dram_cf(15, 7)
    cum = 0.0
    dram_eq = {}
    for r in dram_stock:
        cum += dram_cf.get(r[0], 0.0)
        dram_eq[r[0]] = (dram_closes[r[0]] - dram_se) * 100 + cum

    base_dt = meta["entry_date"]
    if base_dt not in dram_eq:
        base_dt = min(d for d in dram_eq if d >= base_dt)
    base_eq = dram_eq[base_dt]
    end_eq = dram_eq[dram_stock[-1][0]]
    dram_net = end_eq - base_eq
    dram_cap = dram_closes[base_dt] * 100

    peak = base_eq; dram_mdd = 0.0
    for r in dram_stock:
        if r[0] >= base_dt:
            v = dram_eq[r[0]]; peak = max(peak, v); dram_mdd = max(dram_mdd, peak - v)
    dram_peak_actual = dram_se * 100 + peak
    dram_st_mdd_pct = dram_mdd / dram_peak_actual * 100 if dram_peak_actual > 0 else 0

    b13 = dram_closes[base_dt]
    dram_bh_ret = (dram_sx / b13 - 1) * 100
    bpeak = (b13 - dram_se) * 100; bmdd = 0.0
    for r in dram_stock:
        if r[0] >= base_dt:
            v = (dram_closes[r[0]] - dram_se) * 100; bpeak = max(bpeak, v); bmdd = max(bmdd, bpeak - v)
    bpeak_actual = dram_se * 100 + bpeak
    dram_bh_mdd_pct = bmdd / bpeak_actual * 100 if bpeak_actual > 0 else 0

    dram_cmp = dict(
        days=sum(1 for r in dram_stock if r[0] >= base_dt),
        bh_ret=dram_bh_ret, bh_mdd=dram_bh_mdd_pct,
        st_ret=dram_net / dram_cap * 100, st_mdd=dram_st_mdd_pct,
        st_ratio=dram_net / dram_mdd if dram_mdd > 0 else 0,
        down=15, up=15, target=7,
    )

    indic = build_indicator_board(stock)

    generate_html(best, asym_results, best_sym, best_target, bh, bh_ratio,
                  last_spot, latest_date, near_expiry, near_dte, near_strike, near_vw,
                  cost_2, up_line, dn_line, meta, dram_cmp, indic)


def generate_html(best, asym_results, best_sym, best_target, bh, bh_ratio,
                  last_spot, latest_date, near_expiry, near_dte, near_strike, near_vw,
                  cost_2, up_line, dn_line, meta, dram_cmp, indic):
    best_label = TARGET_LABELS[best_target]
    ind = indic["latest"]

    # 指标信号解读
    _price_vs_ma20 = "站上" if ind["close"] > ind["ma20"] else "跌破"
    _trend = "多头" if ind["close"] > ind["ma20"] else "空头"

    # 不对称矩阵（收益）
    matrix_rows = []
    for down in ASYM_MOVES:
        cells = []
        for up in ASYM_MOVES:
            r = next(x for x in asym_results if x["down"] == down and x["up"] == up)
            is_best = (down == best["down"] and up == best["up"])
            cls = "c-gold" if is_best else ("c-red" if r["total"] > 0 else "c-green")
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">${r["total"]:+,.0f}{mark}</td>')
        matrix_rows.append(f"<tr><td>{down}%</td>{''.join(cells)}</tr>")

    # 比率矩阵
    ratio_rows = []
    for down in ASYM_MOVES:
        cells = []
        for up in ASYM_MOVES:
            r = next(x for x in asym_results if x["down"] == down and x["up"] == up)
            is_best = (down == best["down"] and up == best["up"])
            cls = "c-gold" if is_best else ""
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">{r["ratio"]:.2f}{mark}</td>')
        ratio_rows.append(f"<tr><td>{down}%</td>{''.join(cells)}</tr>")

    # 轮空策略矩阵（成本>11%跳过该轮，总收益）
    best_skip = max(asym_results, key=lambda x: x["skip_total"])
    skip_rows = []
    for down in ASYM_MOVES:
        cells = []
        for up in ASYM_MOVES:
            r = next(x for x in asym_results if x["down"] == down and x["up"] == up)
            is_best = (down == best_skip["down"] and up == best_skip["up"])
            cls = "c-gold" if is_best else ("c-red" if r["skip_total"] > 0 else "c-green")
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">${r["skip_total"]:+,.0f}{mark}</td>')
        skip_rows.append(f"<tr><td>{down}%</td>{''.join(cells)}</tr>")

    # 最优策略明细（原来的熔断轮次，周期总利润拆两列）
    best_rounds = []
    for rd in reversed(best["rounds"]):
        si = indic["series"].get(rd["entry_date"], {})
        m20_v = si.get("vs_m20")
        m20_s = "-" if m20_v is None else f"{m20_v:+.1f}%"
        period_all = rd['stock_pnl'] + rd['pnl']
        cost_pct = rd['put_cost'] / (rd['entry_spot'] * 100) * 100
        period_lt11 = 0.0 if cost_pct > 11 else period_all
        best_rounds.append(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['kind']}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td class="{pc(rd['exit_spot']-rd['entry_spot'])}">{(rd['exit_spot']/rd['entry_spot']-1)*100:+.1f}%</td>
<td>${rd['strike']:.0f}</td>
<td class="{pc(m20_v) if m20_v is not None else 'c-gray'}">{m20_s}</td>
<td class="{pc(rd['stock_pnl'])}">${rd['stock_pnl']:+,.0f}</td>
<td class="c-green">-${rd['put_cost']:,.0f}</td>
<td class="c-green">{cost_pct:.1f}%</td>
<td class="c-red">${rd['put_income']:+,.0f}</td>
<td class="{pc(period_lt11)}">${period_lt11:+,.0f}</td>
<td class="{pc(period_all)}">${period_all:+,.0f}</td>
</tr>""")
    best_rounds = "\n".join(best_rounds)

    # 两列总和 + 空档期对账
    _all_sum = 0.0
    _lt11_sum = 0.0
    _skip_rounds = []
    for rd in best["rounds"]:
        cost_pct = rd['put_cost'] / (rd['entry_spot'] * 100) * 100
        period = rd['stock_pnl'] + rd['pnl']
        _all_sum += period
        if cost_pct > 11:
            _skip_rounds.append(period)
        else:
            _lt11_sum += period
    _skip_diff = _lt11_sum - _all_sum  # 正 = 轮空更赚

    # 空档期对账：股票全程持有，但 put 周期滚动，轮次之间裸持期的股票涨跌只计入"股票全程涨跌"、不计入任何一轮
    _first_entry_spot = best["rounds"][0]["entry_spot"]
    _last_exit_spot = best["rounds"][-1]["exit_spot"]
    _gap_head = (_first_entry_spot - meta["entry_price"]) * 100   # 首日 close → 第一轮 entry(open)
    _gap_tail = (meta["exit_price"] - _last_exit_spot) * 100      # 最后一轮 exit → 末日 close
    _gap_total = _gap_head + _gap_tail
    _sum_stock_rounds = sum(rd["stock_pnl"] for rd in best["rounds"])

    # 情景损益表(假设持有到期的微笑曲线)
    scenario_rows = []
    for pct in [-25, -20, -15, -10, -5, 0, 5, 10, 15, 20]:
        exit_ = last_spot * (1 + pct / 100)
        stock_pnl = (exit_ - last_spot) * 100
        payoff = max(near_strike - exit_, 0) * 200
        net = stock_pnl + payoff - cost_2
        scenario_rows.append(f"""<tr>
<td>{exit_:.2f}</td>
<td>{pct:+d}%</td>
<td class="{pc(stock_pnl)}">{stock_pnl:+,.0f}</td>
<td class="{pc(payoff)}">{payoff:+,.0f}</td>
<td class="{pc(net)}">{net:+,.0f}</td>
<td class="{pc(net)}">{net/(last_spot*100)*100:+.1f}%</td>
</tr>""")
    scenario_html = "\n".join(scenario_rows)

    mdd_reduce = bh["mdd_pct"] - best["mdd_pct"]
    if mdd_reduce >= 0:
        mdd_desc = f'回撤从 {bh["mdd_pct"]:.1f}% 降到 <span class="c-green">{best["mdd_pct"]:.1f}%</span>（降了 <span class="c-red">{mdd_reduce:.1f} 个百分点</span>）'
        mdd_kpi_label = "回撤比例降幅"
        mdd_kpi_val_cls = "c-red"
    else:
        mdd_desc = f'回撤从 {bh["mdd_pct"]:.1f}% 升到 <span class="c-red">{best["mdd_pct"]:.1f}%</span>（升了 <span class="c-green">{abs(mdd_reduce):.1f} 个百分点</span>）'
        mdd_kpi_label = "回撤比例升幅"
        mdd_kpi_val_cls = "c-green"

    sndk_ret = best["total"] / (meta["entry_price"] * 100) * 100

    # 收益/回撤比对比（B&H 比值为负时，"倍"无意义，改用定性表述）
    if bh_ratio > 0:
        ratio_cmp = f'，是 B&H（{bh_ratio:.2f}）的 <strong class="c-gold">{best["ratio"]/bh_ratio:.1f} 倍</strong>'
    else:
        ratio_cmp = f'（B&H 为负值 {bh_ratio:.2f}，策略显著更优）'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SNDK 对冲策略最终报告（涨/跌熔断不对称优化）</title>
<style>
:root {{ --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }}
.wrap {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:26px; margin-bottom:6px; }}
h2 {{ font-size:19px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }}
.kpi .label {{ color:var(--muted); font-size:12px; }}
.kpi .value {{ font-size:22px; font-weight:700; margin-top:4px; }}
.kpi .sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }}
th {{ background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }}
th:first-child, td:first-child {{ text-align:left; }}
.c-red {{ color:var(--red); font-weight:600; }}
.c-green {{ color:var(--green); font-weight:600; }}
.c-gray {{ color:var(--muted); }}
.c-gold {{ color:var(--gold); font-weight:700; }}
.callout {{ background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }}
.callout-gold {{ background:rgba(245,195,68,.08); border:1px solid rgba(245,195,68,.35); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }}
.callout-warn {{ background:rgba(245,195,68,.06); border:1px solid rgba(245,195,68,.3); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
</style>
</head>
<body>
<div class="wrap">
<h1>SNDK 对冲策略最终报告 <span style="color:var(--muted);font-size:15px;">（涨熔断 × 跌熔断 不对称优化 · 开盘价熔断）</span></h1>
<p class="sub">数据源：SNDK_stock.json（{meta['n_days']} 交易日）+ SNDK_options_3fri.json（真实 3 周五到期日期权链） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2 style="margin-top:0;">行情与技术指标</h2>
<div style="margin-bottom:12px;">{indic['svg']}</div>
<div class="tbl-scroll">
<table>
<tr><th>指标</th><th>最新值</th><th>信号解读</th></tr>
<tr><td>现价</td><td class="c-red">${ind['close']:.2f}</td><td>{_price_vs_ma20} MA20（{ind['ma20']:.2f}）</td></tr>
<tr><td>均线 MA20</td><td class="c-red">{ind['ma20']:.2f}</td><td>{_trend}（现价{_price_vs_ma20}均线）</td></tr>
<tr><td>买入 ATM Put（现价档）</td><td>${near_vw:.2f}/股</td><td>行权价 ${near_strike:.0f} · 到期 {near_expiry}</td></tr>
<tr><td>Put 成本比例（2张）</td><td class="c-green">{cost_2/(last_spot*100)*100:.1f}%</td><td>2 张共 ${cost_2:,.0f}，占 100 股市值 ${last_spot*100:,.0f}</td></tr>
</table>
</div>
<p class="note">说明：SNDK 回测仅覆盖近 3 个月 {meta['n_days']} 个交易日，MA20 样本偏短、信号仅供参考。现价跌破 MA20 说明短期偏弱。</p>
</div>

<div class="card">
<h2>策略模型</h2>
<div class="callout">
<strong>股票：{meta['entry_date']} 买入 100 股 @ ${meta['entry_price']:.2f}，持有到 {meta['exit_date']} @ ${meta['exit_price']:.2f}，中间不卖出。</strong><br>
<strong>Put：每次买入「{best_label}」的 ATM put 2 张，真实成交价 vw。</strong><br>
<strong>熔断（不对称）</strong>：开盘价相对入场价 <strong class="c-green">跌 {best['down']}%</strong> 或 <strong class="c-red">涨 {best['up']}%</strong> 就开盘平仓 + 重买；盘中不触发。没触发就持有到期，再滚动下一轮。<br>
<strong>2:1 过度对冲</strong>：2 张 put 覆盖 200 股 vs 持有 100 股，下跌时 put 赔付是股票亏损的 2 倍。<br>
<strong>基准 = B&H</strong>：收益 <span class="c-red">${bh['total']:+,.0f}</span>，最大回撤 <span class="c-green">${bh['mdd']:,.0f}（{bh['mdd_pct']:.1f}%）</span>，收益/回撤比 {bh_ratio:.2f}。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
<strong>最优组合：{best_label} put + 跌 {best['down']}% / 涨 {best['up']}% 熔断（不对称）——「不盯盘」前提下的最优策略。</strong><br>
收益 <span class="c-red">${best['total']:+,.0f}</span>（比 B&H 多赚 <span class="c-red">${best['total']-bh['total']:+,.0f}</span>），
{mdd_desc}。
收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>{ratio_cmp}。
</div>
<div class="kpis">
<div class="kpi"><div class="label">B&H 收益</div><div class="value c-red">${bh['total']:+,.0f}</div><div class="sub">回撤 {bh['mdd_pct']:.1f}% · 比 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">策略收益</div><div class="value c-red">${best['total']:+,.0f}</div><div class="sub">{best_label} · 跌{best['down']}%/涨{best['up']}%</div></div>
<div class="kpi"><div class="label">策略回撤比例</div><div class="value c-red">{best['mdd_pct']:.1f}%</div><div class="sub">回撤 ${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">{mdd_kpi_label}</div><div class="value {mdd_kpi_val_cls}">{mdd_reduce:+.1f}%</div><div class="sub">{bh['mdd_pct']:.1f}% → {best['mdd_pct']:.1f}%</div></div>
<div class="kpi"><div class="label">收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">B&H 为 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">股票收益</div><div class="value c-red">${best['stock_pnl']:+,.0f}</div><div class="sub">put 净 {money(best['put_net'])}</div></div>
</div>
<p class="note">回撤比例 = 最大回撤 ÷ 峰值净值。收益/回撤比 = 总收益 ÷ 最大回撤，越高越好。</p>
</div>

<div class="card">
<h2>涨熔断 × 跌熔断 不对称扫描（总收益）</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:8px;">周期 = {best_label}（先由对称扫描确定）。★ = 全局最优（收益/回撤比）。行 = 跌熔断，列 = 涨熔断。</p>
<div class="tbl-scroll">
<table>
<tr><th>跌\涨</th>{''.join(f'<th>{m}%</th>' for m in ASYM_MOVES)}</tr>
{''.join(matrix_rows)}
</table>
</div>
</div>

<div class="card">
<h2>收益/回撤比 矩阵</h2>
<div class="tbl-scroll">
<table>
<tr><th>跌\涨</th>{''.join(f'<th>{m}%</th>' for m in ASYM_MOVES)}</tr>
{''.join(ratio_rows)}
</table>
</div>
</div>

<div class="card">
<h2>轮空策略 不对称扫描（总收益，成本 &gt;11% 跳过该轮）</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:8px;">口径 = 普通总收益 − 被跳过轮次（成本占比 &gt;11%）的周期总利润。★ = 轮空策略下的最优（总收益最高）。行 = 跌熔断，列 = 涨熔断。</p>
<div class="tbl-scroll">
<table>
<tr><th>跌\涨</th>{''.join(f'<th>{m}%</th>' for m in ASYM_MOVES)}</tr>
{''.join(skip_rows)}
</table>
</div>
<p class="note">轮空策略最优 = <strong class="c-gold">跌 {best_skip['down']}% / 涨 {best_skip['up']}%</strong>，收益 <strong class="c-gold">${best_skip['skip_total']:+,.0f}</strong>（普通策略同参数收益 ${best_skip['total']:+,.0f}，轮空多赚 ${best_skip['skip_total']-best_skip['total']:+,.0f}）。轮空不改变最优熔断线，但普遍提升收益。</p>
</div>

<div class="card">
<h2>为什么是「跌 {best['down']}% + 涨 {best['up']}%」</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>涨熔断 {best['up']}%、跌熔断 {best['down']}% 是这段数据下独立扫描出来的最优组合</strong>，不是对称的固定值。涨跌分开扫，是因为标的的上涨节奏和下跌节奏往往不对称。</li>
<li><strong>涨熔断</strong>：涨到 {best['up']}% 就追高重新对齐行权价，捕捉「涨了又回调」的波动。太灵敏会在单边慢涨里反复亏权利金；太迟钝会让 put 停留在旧行权价、回调时保护不足。</li>
<li><strong>跌熔断</strong>：跌到 {best['down']}% 才止盈落袋，只捕捉真正的趋势下跌，避免小波动反复付权利金。</li>
<li><strong>不能跨标的通用</strong>：DRAM、SKHY、SNDK 各自扫描出的最优涨/跌熔断都不同，因为它们的波动节奏不一样。这个「涨跌分开扫」的框架是通用的，但具体数值要每个标的自己扫。</li>
</ul>
<div class="callout-warn">
<strong>⚠️ 过拟合警示</strong>：SNDK 仅 {meta['n_days']} 个交易日、{best['n_rounds']} 轮交易。最优参数高度依赖这段行情的具体节奏，若未来波动节奏改变（如变成单边慢涨），追高会频繁亏权利金。这个参数是短数据下的拟合结果，稳定性有限，仅供研究。
</div>
</div>

<div class="card">
<h2>最优策略逐轮明细：跌 {best['down']}% / 涨 {best['up']}% 熔断</h2>
<p style="font-size:14px;margin-bottom:10px;">共 {best['n_rounds']} 轮（跌熔断 {best['down_hits']} 次 / 涨熔断 {best['up_hits']} 次 / 到期 {best['expiries']} 次）。股票 {money(best['stock_pnl'])}；put 净 {money(best['put_net'])}；<strong>总收益 {money(best['total'])}</strong>。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th><th>波动比例</th><th>行权价</th><th>入场vsMA20</th><th>股票涨跌</th><th>put成本</th><th>成本占比</th><th>put收入</th><th>周期总利润(&lt;11)</th><th>周期总利润(all)</th></tr>
{best_rounds}
</table>
</div>
<p class="note">周期总利润 = 股票涨跌 + put收入 − put成本。倒序排列（最近的交易在最上）。<strong>「周期总利润(all)」= 原本的周期总利润；「周期总利润(&lt;11)」= 若采用"成本占比 &gt;11% 轮空"规则，该轮收益记 0（成本 ≤11% 的轮次两列相同）</strong>。「入场vsMA20」是每轮入场当日现价相对 MA20 的偏离，"-"表示数据不足。</p>
<div class="callout" style="margin-top:10px;">
<strong>对账说明</strong>：各轮「周期总利润(all)」加总 = <span class="c-red">${_all_sum:+,.0f}</span>，而顶部总收益是 <span class="c-red">${best['total']:+,.0f}</span>，差 <span class="c-red">${_gap_total:+,.0f}</span>。<br>
差额是<strong>空档期股票涨跌</strong>——股票全程持有（首日 {meta['entry_date']} 买入、末日 {meta['exit_date']} 卖出），但 put 是周期滚动的，轮次之间裸持期的股票涨跌只计入"股票全程涨跌"、不计入任何一轮：<br>
① 开头空档：数据首日 {meta['entry_date']} 无期权数据，股票从 ${meta['entry_price']:.2f} 裸涨到第一轮入场 ${_first_entry_spot:.2f}，计 <span class="{pc(_gap_head)}">${_gap_head:+,.0f}</span>；<br>
② 结尾空档：最后一轮 {best['rounds'][-1]['exit_date']} 到期后，股票从 ${_last_exit_spot:.2f} 持有到末日 ${meta['exit_price']:.2f}，计 <span class="{pc(_gap_tail)}">${_gap_tail:+,.0f}</span>。<br>
合计：{money(_all_sum)} + {money(_gap_head)} + {money(_gap_tail)} = {money(best['total'])} ✓
</div>
</div>

<div class="card">
<h2>轮空规则验证（成本 &gt;11% 跳过该轮）</h2>
<div class="callout-gold">
<strong>✅ 结论：轮空（跳过成本 &gt;11% 的轮次）收益更高。</strong>对比明细表两列总和：不轮空的「周期总利润(all)」合计 <span class="c-red">${_all_sum:+,.0f}</span>，轮空的「周期总利润(&lt;11)」合计 <span class="c-red">${_lt11_sum:+,.0f}</span>，轮空<strong class="c-gold">多赚 {money(_skip_diff)}</strong>。
</div>
<p style="font-size:13px;color:var(--text);line-height:1.9;">原因：成本 &gt;11% 的 {len(_skip_rounds)} 个轮次合计净亏 {money(sum(_skip_rounds))}（{', '.join(f'{v:+,.0f}' for v in _skip_rounds)}），跳过它们就把这部分亏损避开了。注意：这里是"事后跳过"的对比口径（其他轮次不受影响），实盘若轮空导致重新进场的时点错位，收益会有差异。SNDK 仅 {meta['n_days']} 个交易日，样本小，仅供参考。</p>
</div>

<div class="card">
<h2>亏损轮的特征分析</h2>
<div class="callout-warn">
<strong>结论：亏损 / 小赚的轮次，几乎全是「波动不够大」的轮次。</strong>买 put 赚的是"波动"的钱——只有实际涨跌幅超过权利金成本，put 的赔付才能覆盖保费。波动小的轮次（无论涨还是跌），权利金白付，就是亏损轮。
</div>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>亏损轮只有两类</strong>：①「上涨再平衡」轮（涨了触发追高，但追高后没继续涨，put 变虚值 + 重新付保费）；②「到期」小跌轮（跌了但跌得不够狠，put 赔付 &lt; 保费，股票又小亏）。</li>
<li><strong>大赚轮只有两类</strong>：①「下跌止盈」轮（跌穿熔断线 {best['down']}%，2:1 对冲下 put 赔付是股票亏损的 2 倍）；②「极端大涨」轮（股票涨 + 追高前 put 也涨，双击）。</li>
<li><strong>关键变量是 put 成本占比</strong>：成本占比越高的轮次越难回本——高成本意味着市场 IV 高、权利金贵，后续需要更大的波动才能覆盖保费。对应报告里的「成本 &gt;11% 轮空」规则。</li>
</ul>
<p class="note">注意：SNDK 仅 {meta['n_days']} 个交易日、共 {best['n_rounds']} 轮，样本量很小，上述特征是"这一段行情"的观察，统计意义有限，仅供参考，不可外推为普适规律。</p>
</div>

<div class="card">
<h2>现在如何买（基于最新期权数据 {latest_date}）</h2>
<div class="callout-gold">
最新 SNDK 现价 <strong class="c-gold">${last_spot:.2f}</strong>，最近到期日 <strong>{near_expiry}</strong>（dte {near_dte} 天）。
按最优策略 <strong class="c-gold">{best_label} + 跌 {best['down']}% / 涨 {best['up']}%</strong>，现在应这样操作：
</div>
<ol style="font-size:14px;padding-left:22px;line-height:2.0;">
<li><strong>持有 100 股 SNDK</strong>（市值 ${last_spot*100:,.0f}），一直持有不动。</li>
<li><strong>买入 2 张行权价 ${near_strike:.0f} 的 Put</strong>（现价 ${last_spot:.2f} 最接近的平值档），到期日 {near_expiry}。</li>
<li>该档 Put 成交量加权价 <strong>${near_vw:.2f}/股</strong>，每张 ${near_vw*100:,.2f}，2 张共 <strong class="c-green">-${cost_2:,.0f}</strong>（占持仓 {cost_2/(last_spot*100)*100:.1f}%）。</li>
<li><strong>熔断线（不对称）</strong>：开盘价涨到 <strong class="c-red">${up_line:.2f}</strong>（涨 {best['up']}%）或跌到 <strong class="c-green">${dn_line:.2f}</strong>（跌 {best['down']}%）就开盘平仓 put + 重买（盘中不盯盘）。</li>
<li>没触发熔断就持有到 {near_expiry} 到期，再滚动下一轮 {best_label} put。</li>
</ol>
<div class="tbl-scroll">
<table>
<tr><th>到期日 spot</th><th>涨跌</th><th>股票 P&L</th><th>Put 赔付</th><th>净 P&L</th><th>净收益率</th></tr>
{scenario_html}
</table>
</div>
<p class="note">净 P&L = 股票 P&L + Put 赔付 − 保费（2 张 ${cost_2:,.0f}）。这是「微笑曲线」：<strong>大涨赚（股票）、大跌也赚（2:1 过度对冲）、只有横盘小波动亏保费</strong>。注意：实际涨跌 {best['up']}%/{best['down']}% 会触发熔断提前平仓，不会真的持有到期。</p>
</div>

<div class="card">
<h2>与 DRAM 同期对比（{meta['entry_date']} ~ {meta['exit_date']}，{dram_cmp['days']} 交易日）</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:10px;">同一时间窗口（SNDK 近 3 个月数据期）。SNDK 用其最优参数；DRAM 用原报告策略（7天+15% 对称）<strong>延续滚动</strong>（从 4 月建仓滚到现在，不重新建仓）。资金收益率 = 策略净值变化 ÷ 期初市值（100 股 × 首日收盘价）。</p>
<div class="tbl-scroll">
<table>
<tr><th>指标</th><th>SNDK（最优：{best_label} 跌{best['down']}%/涨{best['up']}%）</th><th>DRAM（7天+15% 对称，延续滚动）</th></tr>
<tr><td>B&H 资金收益率</td><td class="{pc(bh['total'])}">{bh['total']/(meta['entry_price']*100)*100:+.1f}%</td><td class="{pc(dram_cmp['bh_ret'])}">{dram_cmp['bh_ret']:+.1f}%</td></tr>
<tr><td>B&H 回撤比例</td><td class="c-green">{bh['mdd_pct']:.1f}%</td><td class="c-green">{dram_cmp['bh_mdd']:.1f}%</td></tr>
<tr><td><strong>策略资金收益率</strong></td><td class="{pc(sndk_ret)}"><strong>{sndk_ret:+.1f}%</strong></td><td class="{pc(dram_cmp['st_ret'])}">{dram_cmp['st_ret']:+.1f}%</td></tr>
<tr><td><strong>策略回撤比例</strong></td><td class="c-green"><strong>{best['mdd_pct']:.1f}%</strong></td><td class="c-green">{dram_cmp['st_mdd']:.1f}%</td></tr>
<tr><td><strong>收益/回撤比</strong></td><td class="{pc(best['ratio'])}"><strong>{best['ratio']:.2f}</strong></td><td class="{pc(dram_cmp['st_ratio'])}">{dram_cmp['st_ratio']:.2f}</td></tr>
</table>
</div>
<div class="callout">
<strong>同期对比结论</strong>：同样这 {dram_cmp['days']} 个交易日里，<strong>DRAM 涨跌 {dram_cmp['bh_ret']:+.1f}%，SNDK 涨跌 {bh['total']/(meta['entry_price']*100)*100:+.1f}%</strong>。买 put 对冲在两者身上的效果：
<ul style="font-size:13px;padding-left:20px;line-height:1.9;">
<li><strong>SNDK 买 put</strong>：策略收益率 {sndk_ret:+.1f}%（B&H {bh['total']/(meta['entry_price']*100)*100:+.1f}%），回撤从 {bh['mdd_pct']:.1f}% 变到 {best['mdd_pct']:.1f}%。</li>
<li><strong>DRAM 同期买 put</strong>：策略收益率 {dram_cmp['st_ret']:+.1f}%（B&H {dram_cmp['bh_ret']:+.1f}%），回撤从 {dram_cmp['bh_mdd']:.1f}% 变到 {dram_cmp['st_mdd']:.1f}%。</li>
<li><strong>核心规律</strong>：买 put 对冲的收益，取决于「实际波动 vs 隐含波动」的差。实际波动越远超 IV 定价，买 put 越正期望；波动温和则 put 赔付勉强覆盖保费，只起"保险"作用。</li>
</ul>
</div>
</div>

<div class="card">
<h2>数据与结论说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>⚠️ 数据长度限制</strong>：本回测用 SNDK（SanDisk，NAND 闪存/存储公司，Nasdaq 上市）近 3 个月数据，仅 {meta['n_days']} 个交易日、{best['n_rounds']} 轮交易。样本偏少，参数结论可靠性低于更长周期的回测，仅供研究参考。</li>
<li><strong>真实成交价</strong>：Put 成本用每日期权链的成交量加权价（vw），不是 Black-Scholes 理论价 + 假设 IV。</li>
<li><strong>多到期日数据</strong>：SNDK_options_3fri.json 每天含 3 个周五到期日（dte 1-4 / 6-11 / 13-21 天），可真实对比不同周期，无需 BS 外推。</li>
<li><strong>开盘价熔断</strong>：只在美国开盘瞬间判断一次，盘中 low/high 不触发——符合「不盯盘」的实盘操作。</li>
<li><strong>回撤口径</strong>：逐日净值 = 股票市值 + 累计 Put 现金流，MDD = 峰值到谷底最大回撤。</li>
<li><strong>不对称扫描</strong>：涨熔断与跌熔断独立扫描（{len(ASYM_MOVES)}×{len(ASYM_MOVES)} 组合），发现 SNDK 最优是「跌 {best['down']}% + 涨 {best['up']}%」，与 DRAM 的对称 15% 不同——两标的最优参数不能通用。</li>
<li><strong>未计交易摩擦</strong>：实盘佣金 + bid-ask 价差会吃掉部分优势，周期越短越明显。</li>
<li><strong>结果依赖这段行情</strong>：SNDK 这 3 个月从 ${meta['entry_price']:.2f} 波动到最高 ~${meta['max_price']:.0f}、最低 ~${meta['min_price']:.2f}，高波动是策略赚钱的前提。仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"最终报告已生成: {OUT_HTML}")
    print(f"最优: {best_label} + 跌 {best['down']}% / 涨 {best['up']}%, 收益 ${best['total']:+,.0f}, 回撤 {best['mdd_pct']:.1f}%, 比 {best['ratio']:.2f}")


if __name__ == "__main__":
    main()
