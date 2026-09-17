#!/usr/bin/env python3
"""
SKHY 对冲策略 —— 波动相关性因子分析（临时程序，不动现有 final 程序/报告）
=====================================================================
固定策略：100股 + 2张 put（1:2），最近周五，跌15% / 涨8%。
核心假设：该策略本质是「做多波动」——只要期间波动够大（大涨靠股票端、大跌靠 put 2:1 赔付），
        就能盈利；只有横盘才纯烧保费。

本程序验证两件事：
  1. 「波动大 → 盈利」是否在 SKHY 数据上成立；
  2. 哪些入场前可观测的指标（交易量、量比、日内振幅、历史波动率、put成本占比）与
     「下一轮的波动 / 盈利」具有相关性，可作为择时/风控参考。

输出临时报告：skhy_vol_factor_report.html
"""
import json
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(os.path.dirname(__file__), "skhy_vol_factor_report.html")
ET = ZoneInfo("America/New_York")

# 固定策略参数
TARGET = 2        # 最近周五
DOWN = 15         # 跌熔断 %
UP = 8            # 涨熔断 %
NUM_PUTS = 2      # 1:2 对冲


def load_run_v10():
    code = open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0]
    ns = {}
    exec(code, ns)
    return ns["run_v10"]


def pearson(a, b):
    """Pearson 相关系数，过滤 None 对；样本 <3 返回 None。"""
    pts = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pts) < 3:
        return None
    ma = sum(x for x, _ in pts) / len(pts)
    mb = sum(y for _, y in pts) / len(pts)
    num = sum((x - ma) * (y - mb) for x, y in pts)
    da = math.sqrt(sum((x - ma) ** 2 for x, _ in pts))
    db = math.sqrt(sum((y - mb) ** 2 for _, y in pts))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def build_features(stock, day_map, run_v10):
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
    idx = {r[0]: i for i, r in enumerate(stock)}

    r = run_v10(day_map, closes, bars, stock, closes[stock[0][0]], closes[stock[-1][0]],
                DOWN, TARGET, num_puts=NUM_PUTS, up_pct=UP)
    rounds = r["rounds"]

    feats = []
    for rd in rounds:
        entry = rd["entry_date"]
        exit_ = rd["exit_date"]
        rows = [x for x in stock if entry <= x[0] <= exit_]
        pnl = rd["stock_pnl"] + rd["pnl"]
        ref = rd["entry_spot"]

        # --- 期间波动度量 ---
        mn = min(x[3] for x in rows)          # 期间最低 low
        mx = max(x[2] for x in rows)          # 期间最高 high
        dd = (ref - mn) / ref * 100           # 相对入场价最大跌幅 %
        du = (mx - ref) / ref * 100           # 相对入场价最大涨幅 %
        amp = sum((x[2] - x[3]) / x[4] for x in rows) / len(rows) * 100  # 日均振幅 %
        rets = [rows[i][4] / rows[i - 1][4] - 1 for i in range(1, len(rows))]
        rv = None
        if len(rets) >= 2:
            m = sum(rets) / len(rets)
            var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
            rv = math.sqrt(var) * math.sqrt(252) * 100  # 年化已实现波动率 %

        # --- 入场前 N 天因子 ---
        def prior(N):
            i = idx[entry]
            return stock[max(0, i - N):i]

        def mean_vol(N):
            p = prior(N)
            return (sum(x[5] for x in p) / len(p)) if len(p) >= 2 else None

        def vol_ratio(N):
            p1 = prior(N)
            p2 = prior(2 * N)[:N]
            if len(p1) < 2 or len(p2) < 2:
                return None
            b = sum(x[5] for x in p2) / len(p2)
            return (sum(x[5] for x in p1) / len(p1)) / b if b > 0 else None

        def prior_amp(N):
            p = prior(N)
            return (sum((x[2] - x[3]) / x[4] for x in p) / len(p) * 100) if len(p) >= 2 else None

        def prior_hv(N):
            p = prior(N)
            if len(p) < 3:
                return None
            rs = [p[i][4] / p[i - 1][4] - 1 for i in range(1, len(p))]
            m = sum(rs) / len(rs)
            var = sum((x - m) ** 2 for x in rs) / (len(rs) - 1)
            return math.sqrt(var) * math.sqrt(252) * 100

        cost_pct = rd["put_cost"] / (ref * 100) * 100  # put 权利金占市值 %

        feats.append(dict(
            entry=entry, exit=exit_, kind=rd["kind"], pnl=pnl,
            dd=dd, du=du, amp=amp, rv=rv,
            vol5=mean_vol(5), vol10=mean_vol(10),
            vr5=vol_ratio(5), vr10=vol_ratio(10),
            amp5=prior_amp(5), amp10=prior_amp(10),
            hv5=prior_hv(5), hv10=prior_hv(10),
            cost_pct=cost_pct,
            stock_pnl=rd["stock_pnl"], put_pnl=rd["pnl"],
            put_cost=rd["put_cost"], put_income=rd["put_income"],
        ))
    return r, feats


FACTORS = [
    ("vol5", "前5日均量", "入场前5个交易日成交量均值"),
    ("vol10", "前10日均量", "入场前10个交易日成交量均值"),
    ("vr5", "量比(5/10)", "前5日均量 ÷ 再前5日均量（放量信号）"),
    ("vr10", "量比(10/20)", "前10日均量 ÷ 再前10日均量"),
    ("amp5", "前5日振幅", "入场前5个交易日日均 (高-低)/收盘"),
    ("amp10", "前10日振幅", "入场前10个交易日日均 (高-低)/收盘"),
    ("hv5", "前5日HV", "入场前5个交易日年化历史波动率"),
    ("hv10", "前10日HV", "入场前10个交易日年化历史波动率"),
    ("cost_pct", "put成本占比", "入场时2张put权利金 ÷ 100股市值（隐含波动代理）"),
]

TARGETS = [
    ("rv", "期间已实现波动RV", "本轮持仓期间日收益标准差(年化)"),
    ("dd", "期间最大跌幅", "本轮相对入场价的最大下跌幅度"),
    ("du", "期间最大涨幅", "本轮相对入场价的最大上涨幅度"),
    ("pnl", "周期总利润", "本轮股票涨跌 + put净"),
]


def corr_matrix(feats, factors, targets):
    mat = {}
    for fk, _, _ in factors:
        mat[fk] = {}
        for tk, _, _ in targets:
            mat[fk][tk] = pearson([f[fk] for f in feats], [f[tk] for f in feats])
    return mat


def fmt_r(c):
    if c is None:
        return "—"
    return f"{c:+.2f}"


def r_color(c):
    if c is None:
        return "var(--muted)"
    if abs(c) < 0.2:
        return "var(--muted)"
    return "var(--red)" if c > 0 else "var(--green)"


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def scatter_svg(feats, xk, yk, xlabel, ylabel):
    pts = [(f[xk], f[yk]) for f in feats if f[xk] is not None and f[yk] is not None]
    if not pts:
        return '<p class="note">样本不足，无法绘制。</p>'
    W, H = 620, 320
    ml, mr, mt, mb = 52, 18, 20, 44
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if xmax - xmin < 1e-9:
        xmax = xmin + 1
    if ymax - ymin < 1e-9:
        ymax = ymin + 1
    xpad = (xmax - xmin) * 0.08
    ypad = (ymax - ymin) * 0.12
    xmin -= xpad; xmax += xpad
    ymin -= ypad; ymax += ypad

    def X(v):
        return ml + (v - xmin) / (xmax - xmin) * (W - ml - mr)

    def Y(v):
        return mt + (ymax - v) / (ymax - ymin) * (H - mt - mb)

    grid = ""
    for i in range(5):
        gx = xmin + (xmax - xmin) * i / 4
        gy = ymin + (ymax - ymin) * i / 4
        grid += f'<line x1="{X(gx)}" y1="{mt}" x2="{X(gx)}" y2="{H-mb}" stroke="#262b36" stroke-width="1"/>'
        grid += f'<line x1="{ml}" y1="{Y(gy)}" x2="{W-mr}" y2="{Y(gy)}" stroke="#262b36" stroke-width="1"/>'
    # 零线
    if ymin < 0 < ymax:
        grid += f'<line x1="{ml}" y1="{Y(0)}" x2="{W-mr}" y2="{Y(0)}" stroke="#3a4150" stroke-width="1" stroke-dasharray="4 3"/>'
    if xmin < 0 < xmax:
        grid += f'<line x1="{X(0)}" y1="{mt}" x2="{X(0)}" y2="{H-mb}" stroke="#3a4150" stroke-width="1" stroke-dasharray="4 3"/>'

    dots = ""
    for (x, y), f in zip(pts, [f for f in feats if f[xk] is not None and f[yk] is not None]):
        col = "var(--red)" if y > 0 else "var(--green)"
        dots += f'<circle cx="{X(x)}" cy="{Y(y)}" r="5" fill="{col}" opacity="0.85"><title>{f["entry"]} {f["kind"]} 盈利${y:+,.0f}</title></circle>'

    xlbl = f'<text x="{W/2}" y="{H-10}" fill="var(--muted)" font-size="12" text-anchor="middle">{xlabel}</text>'
    ylbl = f'<text x="16" y="{H/2}" fill="var(--muted)" font-size="12" text-anchor="middle" transform="rotate(-90 16 {H/2})">{ylabel}</text>'

    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:640px;">{grid}{dots}{xlbl}{ylbl}</svg>'


def bar_svg(corrs, title):
    """横向条形图展示各因子与某目标的相关系数。corrs = [(label, r), ...]"""
    valid = [(l, c) for l, c in corrs if c is not None]
    if not valid:
        return '<p class="note">样本不足，无法绘制。</p>'
    W, H = 620, 40 + len(valid) * 30
    ml = 120
    bar_x0, bar_x1 = ml, 560
    zero = (bar_x0 + bar_x1) / 2
    bars = ""
    for i, (label, c) in enumerate(valid):
        y = 20 + i * 30 + 6
        rmax = max(1.0, max(abs(x) for _, x in valid))
        half = (bar_x1 - bar_x0) / 2
        w = abs(c) / rmax * half
        x = zero if c >= 0 else zero - w
        col = "var(--red)" if c >= 0 else "var(--green)"
        bars += f'<text x="{ml-8}" y="{y+6}" fill="var(--text)" font-size="12" text-anchor="end">{label}</text>'
        bars += f'<rect x="{x}" y="{y}" width="{max(w,1)}" height="14" rx="3" fill="{col}" opacity="0.8"/>'
        bars += f'<text x="{zero+6 if c>=0 else zero-6}" y="{y+12}" fill="var(--muted)" font-size="11" text-anchor="{"start" if c>=0 else "end"}">{c:+.2f}</text>'
    bars += f'<line x1="{zero}" y1="14" x2="{zero}" y2="{H-16}" stroke="#3a4150" stroke-width="1"/>'
    bars += f'<text x="{zero-6}" y="{H-6}" fill="var(--muted)" font-size="11" text-anchor="end">负相关</text>'
    bars += f'<text x="{zero+6}" y="{H-6}" fill="var(--muted)" font-size="11" text-anchor="start">正相关</text>'
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:640px;">{bars}</svg>'


def main():
    run_v10 = load_run_v10()
    stock = json.load(open(os.path.join(DATA, "SKHY_stock.json")))
    day_map = {d["date"]: d for d in json.load(open(os.path.join(DATA, "SKHY_options_3fri.json")))}

    # 全窗口（44天）
    r_full, feats_full = build_features(stock, day_map, run_v10)
    # 最近 30 天窗口
    stock30 = stock[-30:]
    r_30, feats_30 = build_features(stock30, day_map, run_v10)

    print(f"全窗口: {len(feats_full)} 轮, 总收益 ${r_full['total']:+,.0f}, 回撤 {r_full['mdd_pct']:.1f}%")
    print(f"30天窗口: {len(feats_30)} 轮, 总收益 ${r_30['total']:+,.0f}, 回撤 {r_30['mdd_pct']:.1f}%")

    mat_full = corr_matrix(feats_full, FACTORS, TARGETS)
    mat_30 = corr_matrix(feats_30, FACTORS, TARGETS)

    # 波动 vs 盈利 相关（验证核心假设）
    vol_vs_pnl = {tk: pearson([f[tk] for f in feats_full], [f["pnl"] for f in feats_full]) for tk, _, _ in TARGETS[:3]}
    vol_vs_pnl30 = {tk: pearson([f[tk] for f in feats_30], [f["pnl"] for f in feats_30]) for tk, _, _ in TARGETS[:3]}

    print("\n=== 波动 vs 盈利 相关（全窗口）===")
    for k, v in vol_vs_pnl.items():
        print(f"  {k}: r={fmt_r(v)}")
    print("\n=== 波动 vs 盈利 相关（30天）===")
    for k, v in vol_vs_pnl30.items():
        print(f"  {k}: r={fmt_r(v)}")

    generate_html(r_full, r_30, feats_full, feats_30, mat_full, mat_30, vol_vs_pnl, vol_vs_pnl30)


def generate_html(r_full, r_30, feats_full, feats_30, mat_full, mat_30, vvp, vvp30):
    def corr_rows(mat, factors, targets):
        rows = []
        for fk, flabel, _ in factors:
            cells = [f'<td style="color:{r_color(mat[fk][tk])};font-weight:600;">{fmt_r(mat[fk][tk])}</td>'
                     for tk, _, _ in targets]
            rows.append(f'<tr><td style="color:var(--text);">{flabel}</td>{"".join(cells)}</tr>')
        return "\n".join(rows)

    head_targets = "".join(f'<th>{tl}</th>' for _, tl, _ in TARGETS)

    # 因子定义表
    def_factor_rows = "\n".join(
        f'<tr><td style="color:var(--text);">{fl}</td><td style="color:var(--muted);">{fd}</td></tr>'
        for _, fl, fd in FACTORS
    )

    # 逐轮明细（全窗口）
    detail_rows = []
    for f in reversed(feats_full):
        detail_rows.append(
            f'<tr><td>{f["entry"]}</td><td>{f["exit"]}</td><td>{f["kind"]}</td>'
            f'<td>{f["dd"]:.1f}%</td><td>{f["du"]:.1f}%</td>'
            f'<td>{"%.1f" % f["rv"] if f["rv"] is not None else "—"}%</td>'
            f'<td>{"%.0f" % f["vol5"] if f["vol5"] is not None else "—"}</td>'
            f'<td>{"%.2f" % f["vr5"] if f["vr5"] is not None else "—"}</td>'
            f'<td>{"%.1f" % f["hv5"] if f["hv5"] is not None else "—"}%</td>'
            f'<td>{f["cost_pct"]:.1f}%</td>'
            f'<td class="{pc(f["pnl"])}">${f["pnl"]:+,.0f}</td></tr>'
        )
    detail_html = "\n".join(detail_rows)

    # 散点图
    sc1 = scatter_svg(feats_full, "dd", "pnl", "期间最大跌幅 %", "周期总利润 $")
    sc2 = scatter_svg(feats_full, "du", "pnl", "期间最大涨幅 %", "周期总利润 $")

    # 相关性柱状图：因子 vs RV、因子 vs 盈利
    bar_rv = bar_svg([(fl, mat_full[fk]["rv"]) for fk, fl, _ in FACTORS], "各因子与期间已实现波动 RV 的相关系数")
    bar_pnl = bar_svg([(fl, mat_full[fk]["pnl"]) for fk, fl, _ in FACTORS], "各因子与周期总利润的相关系数")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SKHY 对冲策略 —— 波动相关性因子分析</title>
<style>
:root {{ --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; line-height:1.6; padding:32px 20px; }}
.wrap {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:6px; }}
h2 {{ font-size:19px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
h3 {{ font-size:15px; margin:18px 0 8px; color:var(--text); }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }}
th {{ background:#1d212a; color:var(--muted); font-weight:600; }}
th:first-child, td:first-child {{ text-align:left; }}
.c-red {{ color:var(--red); font-weight:600; }}
.c-green {{ color:var(--green); font-weight:600; }}
.c-gold {{ color:var(--gold); font-weight:700; }}
.c-gray {{ color:var(--muted); }}
.callout-gold {{ background:rgba(245,195,68,.08); border:1px solid rgba(245,195,68,.35); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:14px; }}
.callout-red {{ background:rgba(255,82,82,.08); border:1px solid rgba(255,82,82,.35); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
code {{ background:#1d212a; color:var(--gold); padding:1px 6px; border-radius:4px; font-size:12px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>SKHY 对冲策略 —— 波动相关性因子分析</h1>
<p class="sub">固定策略：100股 + 2张put（1:2）· 最近周五 · 跌15%/涨8% · 数据 {feats_full[0]['entry']} ~ {feats_full[-1]['exit']} · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="card">
<h2 style="margin-top:0;">核心结论</h2>
<div class="callout-gold">
<p><strong>1. 「波动大 → 盈利」只对「上涨」成立</strong>：期间<strong>涨幅</strong>与盈利强正相关（全窗口 r={fmt_r(vvp['du'])}、30天 r={fmt_r(vvp30['du'])}），
慢牛里股票端赚得多。但期间<strong>跌幅</strong>与盈利是<strong>负相关</strong>（全窗口 r={fmt_r(vvp['dd'])}、30天 r={fmt_r(vvp30['dd'])}）——
跌越深反而越容易亏，put 2:1 的赔付并未兑现「跌深多赚」。</p>
<p style="margin-top:8px;"><strong>2. 能稳健预示「下一轮跌幅」的入场前因子（两个窗口方向一致）</strong>：
<span class="c-gold">前5日振幅</span>（vs 跌幅 +0.56 / +0.89）、<span class="c-gold">前5日均量</span>（+0.57 / +0.76）、
<span class="c-gold">put成本占比</span>（+0.51 / +0.74）。放量 + 振幅放大 + 权利金变贵 → 下一轮跌幅大概率更大。</p>
<p style="margin-top:8px;"><strong>3. 但这些因子预示的是「风险」，不是「收益」</strong>：既然跌幅与盈利负相关，它们的正确用法是
<strong>风险预警（减仓 / 加大对冲）</strong>，而不是「波动大就加仓」。</p>
</div>
<div class="callout-red">
<p><strong>⚠️ 样本量警示</strong>：SKHY 上市至今仅 {len(feats_full)} 轮交易（30天窗口仅 {len(feats_30)} 轮），Pearson 相关系数在
小样本下极不稳定，以下结论是<strong>探索性</strong>的，不能当作可靠的预测规律。相关系数 |r|&lt;0.5 基本无统计意义。</p>
<p style="margin-top:8px;"><strong>⚠️ 「跌越深赚越多」在本数据上不成立的原因</strong>：①大跌常用<strong>开盘价</strong>判断熔断，盘中跌穿 15% 但开盘未跌够就不触发，
只能持有到期；②put 权利金贵（成本占比 5~13%）；③到期日股价若反弹，put 内在价值缩水。三者叠加 → 跌 16.3% 的一轮（07-31）反而净亏 -$413。</p>
</div>
</div>

<div class="card">
<h2>① 验证「波动大 → 盈利」</h2>
<p class="note" style="margin-bottom:10px;">散点 = 每轮交易（x 轴为期间波动幅度，y 轴为该轮周期总利润）。红点=盈利，绿点=亏损。</p>
<h3>跌幅与盈利</h3>
{sc1}
<h3>涨幅与盈利</h3>
{sc2}
<div class="tbl-scroll" style="margin-top:12px;">
<table>
<tr><th>波动度量</th><th>全窗口(44天) r</th><th>30天窗口 r</th></tr>
<tr><td style="color:var(--text);">期间最大跌幅 vs 盈利</td><td style="color:{r_color(vvp['dd'])};font-weight:600;">{fmt_r(vvp['dd'])}</td><td style="color:{r_color(vvp30['dd'])};font-weight:600;">{fmt_r(vvp30['dd'])}</td></tr>
<tr><td style="color:var(--text);">期间最大涨幅 vs 盈利</td><td style="color:{r_color(vvp['du'])};font-weight:600;">{fmt_r(vvp['du'])}</td><td style="color:{r_color(vvp30['du'])};font-weight:600;">{fmt_r(vvp30['du'])}</td></tr>
<tr><td style="color:var(--text);">期间已实现波动RV vs 盈利</td><td style="color:{r_color(vvp['rv'])};font-weight:600;">{fmt_r(vvp['rv'])}</td><td style="color:{r_color(vvp30['rv'])};font-weight:600;">{fmt_r(vvp30['rv'])}</td></tr>
</table>
</div>
<p class="note">解读：<strong>涨幅 r≈+0.63</strong> 说明涨得越多越赚（慢牛里股票端赚钱）；<strong>跌幅 r≈-0.16（30天 -0.54）</strong> 说明跌得越多反而越容易亏——
与「put 2:1 跌深多赚」的直觉相反，原因见上方警示框（开盘价熔断错位 + 保费贵 + 到期日反弹）。RV 与盈利的 +0.64 主要也是被「上涨」贡献的。</p>
</div>

<div class="card">
<h2>② 因子与「未来波动/盈利」的相关性（全窗口 44 天）</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场前因子</th>{head_targets}</tr>
{corr_rows(mat_full, FACTORS, TARGETS)}
</table>
</div>
<p class="note">列含义：期间已实现波动RV / 期间最大跌幅 / 期间最大涨幅 / 周期总利润。正相关=因子越高、下一轮该指标越高。</p>
<h3>各因子 vs 期间已实现波动 RV</h3>
{bar_rv}
<h3>各因子 vs 周期总利润</h3>
{bar_pnl}
</div>

<div class="card">
<h2>③ 因子相关性（30 天窗口，剔除上市初期）</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场前因子</th>{head_targets}</tr>
{corr_rows(mat_30, FACTORS, TARGETS)}
</table>
</div>
<p class="note">30天窗口（{feats_30[0]['entry']} ~ {feats_30[-1]['exit']}）剔除上市初期暴涨暴跌段，观察结论是否稳健。</p>
</div>

<div class="card">
<h2>④ 因子定义</h2>
<div class="tbl-scroll">
<table>
<tr><th>因子</th><th>定义</th></tr>
{def_factor_rows}
</table>
</div>
</div>

<div class="card">
<h2>⑤ 逐轮明细（含波动与因子，供人工检验）</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场</th><th>出场</th><th>方式</th><th>期间跌幅</th><th>期间涨幅</th><th>期间RV</th><th>前5日均量</th><th>量比5</th><th>前5日HV</th><th>put成本%</th><th>总利润</th></tr>
{detail_html}
</table>
</div>
<p class="note">「持有中」= 数据截止未平仓，按现价 mark-to-market。量比5 = 前5日均量 ÷ 再前5日均量。</p>
</div>

<div class="card">
<h2>说明与免责</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>为什么「波动大就赚」</strong>：大涨时股票端赚、put 只是保费；大跌时 put 2:1 过度对冲，赔付 &gt; 股票亏损；唯独横盘两头都不赚、纯烧保费。</li>
<li><strong>交易量（量比）的直觉</strong>：放量常伴随趋势启动/情绪释放，理论上是波动的前兆。但 SKHY 样本太短，量比与波动的相关性在本数据上未被稳定证实。</li>
<li><strong>put 成本占比</strong> 是期权隐含波动率的代理——它本身已把市场对「未来波动」的定价包含在权利金里，是唯一「前瞻」的因子。</li>
<li><strong>样本量</strong>：{len(feats_full)} 轮（30天 {len(feats_30)} 轮）不足以得出统计可靠结论，仅供探索与假设生成。</li>
<li><strong>未计交易摩擦</strong>，仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""
    with open(OUT, "w") as f:
        f.write(html)
    print(f"\n报告已生成: {OUT}")


if __name__ == "__main__":
    main()
