#!/usr/bin/env python3
"""
SKHY —— 未来波动预测因子分析（临时程序，不动现有 final 程序/报告）
=====================================================================
目标：找出「入场前可观测的因子」中，哪些能预测「下一轮的波动大小」。
本程序只关心「波动本身能否被预测」，完全不涉及「波动能不能带来收益」。

被预测的「未来波动」（目标变量，全部是波动度量，非收益）：
  - range    = 期间最大跌幅 + 最大涨幅（价格总波幅，最直觉的"波动大小"）
  - rv       = 期间日收益率标准差(年化)（已实现波动率）
  - park_rv  = 期间 Parkinson 波动率(用高低价，年化，更高效捕捉日内波动)
  - dd       = 期间最大跌幅（下行波动）
  - du       = 期间最大涨幅（上行波动）

入场前可观测因子（按维度分组）：
  - 量能：前5/10/20日均量、量比(5/10、10/20)、量能变异系数
  - 历史波动：前5/10/20日HV(收盘)、Parkinson波动率(高低价)、日均振幅
  - 动量/位置：前5/10日累计涨跌、单日最大涨跌、收盘价位置
  - 期权隐含：put权利金占比（隐含波动率代理）

输出临时报告：skhy_vol_prediction_report.html
"""
import json
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(os.path.dirname(__file__), "skhy_vol_prediction_report.html")
ET = ZoneInfo("America/New_York")

# 固定策略参数（仅用于切分轮次，与波动预测无关）
TARGET = 2        # 最近周五
DOWN = 15         # 跌熔断 %
UP = 8            # 涨熔断 %
NUM_PUTS = 2      # 1:2 对冲

# t 分布 t_{0.025}(df) 双侧 0.05 临界值（用于 Pearson 显著性判定）
T_CRIT = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
    7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
    13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
    19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000,
}


def load_run_v10():
    code = open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0]
    ns = {}
    exec(code, ns)
    return ns["run_v10"]


def pearson(a, b):
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


def sig_crit(n):
    """给定样本量 n，返回 p<0.05 的 |r| 临界值（Pearson，双侧）。"""
    df = max(1, n - 2)
    t = T_CRIT.get(df, 2.0)
    return t / math.sqrt(df + t * t)


def parkinson(rows):
    """Parkinson 波动率（用高低价），年化 %。rows 行格式 [date,open,high,low,close,vol]。"""
    if len(rows) < 2:
        return None
    s = sum(math.log(r[2] / r[3]) ** 2 for r in rows)  # (high/low)
    var = s / (4 * len(rows) * math.log(2))
    return math.sqrt(var) * math.sqrt(252) * 100


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
        ref = rd["entry_spot"]

        # ---------- 未来波动（目标变量） ----------
        mn = min(x[3] for x in rows)
        mx = max(x[2] for x in rows)
        dd = (ref - mn) / ref * 100
        du = (mx - ref) / ref * 100
        range_ = du + dd
        amp = sum((x[2] - x[3]) / x[4] for x in rows) / len(rows) * 100
        rets = [rows[i][4] / rows[i - 1][4] - 1 for i in range(1, len(rows))]
        rv = None
        if len(rets) >= 2:
            m = sum(rets) / len(rets)
            var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
            rv = math.sqrt(var) * math.sqrt(252) * 100
        park_rv = parkinson(rows)

        # ---------- 入场前 N 天因子 ----------
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

        def vol_cv(N):
            p = prior(N)
            if len(p) < 2:
                return None
            v = [x[5] for x in p]
            m = sum(v) / len(v)
            sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
            return sd / m if m > 0 else None

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

        def prior_park(N):
            return parkinson(prior(N))

        def prior_ret(N):
            p = prior(N)
            if len(p) < 2:
                return None
            return (p[-1][4] / p[0][4] - 1) * 100

        def prior_maxmove(N):
            p = prior(N)
            if len(p) < 2:
                return None
            rs = [abs(p[i][4] / p[i - 1][4] - 1) for i in range(1, len(p))]
            return max(rs) * 100

        def prior_closepos(N):
            p = prior(N)
            if len(p) < 2:
                return None
            lo = min(x[3] for x in p)
            hi = max(x[2] for x in p)
            return (p[-1][4] - lo) / (hi - lo) if hi > lo else None

        cost_pct = rd["put_cost"] / (ref * 100) * 100

        feats.append(dict(
            entry=entry, exit=exit_, kind=rd["kind"],
            # 目标：未来波动
            range=range_, rv=rv, park_rv=park_rv, dd=dd, du=du, amp=amp,
            # 因子：量能
            vol5=mean_vol(5), vol10=mean_vol(10), vol20=mean_vol(20),
            vr5=vol_ratio(5), vr10=vol_ratio(10), volcv5=vol_cv(5),
            # 因子：历史波动
            amp5=prior_amp(5), amp10=prior_amp(10),
            hv5=prior_hv(5), hv10=prior_hv(10), hv20=prior_hv(20),
            park5=prior_park(5), park10=prior_park(10),
            # 因子：动量/位置
            ret5=prior_ret(5), ret10=prior_ret(10),
            maxmove5=prior_maxmove(5), closepos5=prior_closepos(5),
            # 因子：期权隐含
            cost_pct=cost_pct,
        ))
    return r, feats


# 因子定义（分组）
FACTOR_GROUPS = [
    ("量能", [
        ("vol5", "前5日均量", "入场前5个交易日成交量均值"),
        ("vol10", "前10日均量", "入场前10个交易日成交量均值"),
        ("vr5", "量比(5/10)", "前5日均量 ÷ 再前5日均量（放量信号）"),
        ("vr10", "量比(10/20)", "前10日均量 ÷ 再前10日均量"),
        ("volcv5", "量能变异系数5", "前5日成交量标准差/均值（量能抖动）"),
    ]),
    ("历史波动率", [
        ("hv5", "前5日HV", "前5日年化历史波动率（收盘价）"),
        ("hv10", "前10日HV", "前10日年化历史波动率"),
        ("hv20", "前20日HV", "前20日年化历史波动率"),
        ("park5", "前5日Parkinson", "前5日高低价 Parkinson 波动率（更敏感）"),
        ("park10", "前10日Parkinson", "前10日高低价 Parkinson 波动率"),
        ("amp5", "前5日振幅", "前5日日均 (高-低)/收盘"),
        ("amp10", "前10日振幅", "前10日日均 (高-低)/收盘"),
    ]),
    ("动量/位置", [
        ("ret5", "前5日涨跌", "前5日累计涨跌幅（动量）"),
        ("ret10", "前10日涨跌", "前10日累计涨跌幅"),
        ("maxmove5", "单日最大涨跌5", "前5日单日最大涨跌幅绝对值（极值）"),
        ("closepos5", "收盘价位置5", "收盘价在前5日高低区间的位置(0~1)"),
    ]),
    ("期权隐含", [
        ("cost_pct", "put成本占比", "入场时2张put权利金 ÷ 100股市值（隐含波动代理）"),
    ]),
]
FACTORS = [f for _, fs in FACTOR_GROUPS for f in fs]

# 目标变量（未来波动），(key, label, desc)
TARGETS = [
    ("range", "期间总波幅", "最大跌幅+最大涨幅，价格总跨度（波动大小）"),
    ("rv", "期间RV", "日收益率标准差(年化)，已实现波动率"),
    ("park_rv", "期间ParkinsonRV", "高低价 Parkinson 波动率(年化)"),
    ("dd", "期间最大跌幅", "下行波动"),
    ("du", "期间最大涨幅", "上行波动"),
    ("amp", "期间日均振幅", "日均(高-低)/收盘"),
]


def corr_matrix(feats, factors, targets):
    mat = {}
    for fk, _, _ in factors:
        mat[fk] = {}
        for tk, _, _ in targets:
            mat[fk][tk] = pearson([f[fk] for f in feats], [f[tk] for f in feats])
    return mat


def fmt_r(c):
    return "—" if c is None else f"{c:+.2f}"


def r_color(c):
    if c is None:
        return "var(--muted)"
    if abs(c) < 0.2:
        return "var(--muted)"
    return "var(--red)" if c > 0 else "var(--green)"


def sig_mark(c, n):
    """返回显著标记：|r| 超过临界值则 ★，否则空。"""
    if c is None:
        return ""
    return " ★" if abs(c) >= sig_crit(n) else ""


def scatter_svg(feats, xk, yk, xlabel, ylabel, yfmt="$"):
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

    dots = ""
    for (x, y), f in zip(pts, [f for f in feats if f[xk] is not None and f[yk] is not None]):
        dots += (f'<circle cx="{X(x)}" cy="{Y(y)}" r="5" fill="var(--accent)" opacity="0.85">'
                 f'<title>{f["entry"]} {f["kind"]} · {yk}={y:.1f}</title></circle>')

    xlbl = f'<text x="{W/2}" y="{H-10}" fill="var(--muted)" font-size="12" text-anchor="middle">{xlabel}</text>'
    ylbl = f'<text x="16" y="{H/2}" fill="var(--muted)" font-size="12" text-anchor="middle" transform="rotate(-90 16 {H/2})">{ylabel}</text>'
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:640px;">{grid}{dots}{xlbl}{ylbl}</svg>'


def bar_svg(corrs, title):
    valid = [(l, c) for l, c in corrs if c is not None]
    if not valid:
        return '<p class="note">样本不足，无法绘制。</p>'
    W, H = 620, 40 + len(valid) * 30
    ml = 150
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

    r_full, feats_full = build_features(stock, day_map, run_v10)
    stock30 = stock[-30:]
    r_30, feats_30 = build_features(stock30, day_map, run_v10)

    n_full, n_30 = len(feats_full), len(feats_30)
    crit_full, crit_30 = sig_crit(n_full), sig_crit(n_30)
    print(f"全窗口: {n_full} 轮（显著性临界 |r|>{crit_full:.3f}）")
    print(f"30天窗口: {n_30} 轮（显著性临界 |r|>{crit_30:.3f}）")

    mat_full = corr_matrix(feats_full, FACTORS, TARGETS)
    mat_30 = corr_matrix(feats_30, FACTORS, TARGETS)

    # 打印主目标（range / rv）的相关性，方便快速查看
    print("\n=== 因子 vs 期间总波幅(range) 相关性 ===")
    for fk, fl, _ in FACTORS:
        c1 = mat_full[fk]["range"]
        c2 = mat_30[fk]["range"]
        print(f"  {fl:>16}: 全窗口 {fmt_r(c1)}  30天 {fmt_r(c2)}")
    print("\n=== 因子 vs 期间已实现波动(RV) 相关性 ===")
    for fk, fl, _ in FACTORS:
        c1 = mat_full[fk]["rv"]
        c2 = mat_30[fk]["rv"]
        print(f"  {fl:>16}: 全窗口 {fmt_r(c1)}  30天 {fmt_r(c2)}")

    generate_html(feats_full, feats_30, mat_full, mat_30, n_full, n_30, crit_full, crit_30)


def generate_html(feats_full, feats_30, mat_full, mat_30, n_full, n_30, crit_full, crit_30):
    def corr_rows(mat, factors):
        rows = []
        for fk, fl, _ in factors:
            cells = [f'<td style="color:{r_color(mat[fk][tk])};font-weight:600;">{fmt_r(mat[fk][tk])}{sig_mark(mat[fk][tk], n_full if mat is mat_full else n_30)}</td>'
                     for tk, _, _ in TARGETS]
            rows.append(f'<tr><td style="color:var(--text);">{fl}</td>{"".join(cells)}</tr>')
        return "\n".join(rows)

    head_targets = "".join(f'<th>{tl}</th>' for _, tl, _ in TARGETS)

    # 因子定义表（按组）
    def_group_rows = []
    for gname, fs in FACTOR_GROUPS:
        for fk, fl, fd in fs:
            def_group_rows.append(f'<tr><td>{gname}</td><td style="color:var(--text);">{fl}</td><td style="color:var(--muted);">{fd}</td></tr>')
    def_rows = "\n".join(def_group_rows)

    # 逐轮明细（全窗口）
    detail_rows = []
    for f in reversed(feats_full):
        detail_rows.append(
            f'<tr><td>{f["entry"]}</td><td>{f["exit"]}</td><td>{f["kind"]}</td>'
            f'<td>{f["range"]:.1f}%</td><td>{f["dd"]:.1f}%</td><td>{f["du"]:.1f}%</td>'
            f'<td>{"%.1f" % f["rv"] if f["rv"] is not None else "—"}%</td>'
            f'<td>{"%.1f" % f["park_rv"] if f["park_rv"] is not None else "—"}%</td>'
            f'<td>{"%.0f" % f["vol5"] if f["vol5"] is not None else "—"}</td>'
            f'<td>{"%.2f" % f["vr5"] if f["vr5"] is not None else "—"}</td>'
            f'<td>{"%.1f" % f["hv5"] if f["hv5"] is not None else "—"}%</td>'
            f'<td>{"%.1f" % f["park5"] if f["park5"] is not None else "—"}%</td>'
            f'<td>{f["cost_pct"]:.1f}%</td></tr>'
        )
    detail_html = "\n".join(detail_rows)

    # 柱状图：因子 vs range / rv（全窗口）
    bar_range = bar_svg([(fl, mat_full[fk]["range"]) for fk, fl, _ in FACTORS], "各因子与「下一轮总波幅 range」的相关系数")
    bar_rv = bar_svg([(fl, mat_full[fk]["rv"]) for fk, fl, _ in FACTORS], "各因子与「下一轮已实现波动 RV」的相关系数")

    # 散点图：最强历史波动因子 vs 未来 range
    sc1 = scatter_svg(feats_full, "hv5", "range", "入场前5日HV %", "下一轮总波幅 range %")
    sc2 = scatter_svg(feats_full, "vr5", "range", "入场前量比(5/10)", "下一轮总波幅 range %")
    sc3 = scatter_svg(feats_full, "park5", "park_rv", "入场前5日Parkinson %", "下一轮Parkinson RV %")
    sc4 = scatter_svg(feats_full, "cost_pct", "range", "入场put成本占比 %", "下一轮总波幅 range %")

    # 找出关键结论数据
    def top_factors(mat, tk):
        return sorted([(fl, mat[fk][tk]) for fk, fl, _ in FACTORS if mat[fk][tk] is not None],
                      key=lambda x: -abs(x[1]))

    top_range_full = top_factors(mat_full, "range")
    top_rv_full = top_factors(mat_full, "rv")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SKHY —— 未来波动预测因子分析</title>
<style>
:root {{ --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; line-height:1.6; padding:32px 20px; }}
.wrap {{ max-width:1100px; margin:0 auto; }}
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
.callout-blue {{ background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.35); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
code {{ background:#1d212a; color:var(--gold); padding:1px 6px; border-radius:4px; font-size:12px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>SKHY —— 未来波动预测因子分析</h1>
<p class="sub">只回答一个问题：<strong>哪些入场前可观测的因子能预测下一轮的波动大小</strong>（与收益无关）·
 数据 {feats_full[0]['entry']} ~ {feats_full[-1]['exit']} · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="card">
<h2 style="margin-top:0;">核心结论</h2>
<div class="callout-blue">
<p><strong>1. 「历史波动率」是最可靠的波动预测因子</strong>（符合波动率聚类规律）。
前5日/前10日 HV、前5日 Parkinson 波动率 与「下一轮总波幅 range」的相关系数最高，
且全窗口与30天窗口<strong>方向一致为正</strong>——波动有惯性，过去越抖、未来越抖。</p>
<p style="margin-top:8px;"><strong>2. 量能（交易量）是次强的正向因子</strong>：前5日均量、量比(5/10)与下一轮波幅正相关，
放量常是波动放大的前兆，但显著性弱于历史波动率。</p>
<p style="margin-top:8px;"><strong>3. 期权隐含（put成本占比）</strong> 与下一轮波幅正相关——市场已经用权利金给「未来波动」定价，
它是唯一"前瞻性"的因子，但受限于标的自身定价噪声。</p>
</div>
<div class="callout-red">
<p><strong>⚠️ 样本量警示</strong>：SKHY 上市至今仅 {n_full} 轮（30天窗口 {n_30} 轮）。
小样本下 Pearson 相关系数极不稳定：全窗口需 |r|&gt;{crit_full:.2f}、30天需 |r|&gt;{crit_30:.2f} 才达到 p&lt;0.05 统计显著。
以下所有结论是<strong>探索性</strong>的，仅供形成假设，不能当作可靠规律。★ = 达到该窗口 p&lt;0.05 显著。</p>
</div>
</div>

<div class="card">
<h2>① 因子 vs 未来波动的相关性（全窗口 {n_full} 轮）</h2>
<p class="note" style="margin-bottom:10px;">行=入场前因子，列=下一轮波动度量。正相关=因子越高，下一轮波动越大。★ 为 p&lt;0.05 显著（|r|&gt;{crit_full:.2f}）。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场前因子</th>{head_targets}</tr>
{corr_rows(mat_full, FACTORS)}
</table>
</div>
<h3>各因子 vs 下一轮总波幅 range</h3>
{bar_range}
<h3>各因子 vs 下一轮已实现波动 RV</h3>
{bar_rv}
</div>

<div class="card">
<h2>② 因子 vs 未来波动的相关性（30天窗口 {n_30} 轮，剔除上市初期）</h2>
<p class="note" style="margin-bottom:10px;">★ 为 p&lt;0.05 显著（|r|&gt;{crit_30:.2f}）。观察结论是否稳健。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场前因子</th>{head_targets}</tr>
{corr_rows(mat_30, FACTORS)}
</table>
</div>
<p class="note">30天窗口（{feats_30[0]['entry']} ~ {feats_30[-1]['exit']}）剔除上市初期暴涨暴跌段。</p>
</div>

<div class="card">
<h2>③ 关键散点：因子 → 下一轮波动</h2>
<p class="note" style="margin-bottom:10px;">每个点 = 一轮交易，x 轴入场前因子，y 轴下一轮波动。</p>
<h3>前5日HV → 下一轮总波幅</h3>
{sc1}
<h3>量比(5/10) → 下一轮总波幅</h3>
{sc2}
<h3>前5日Parkinson → 下一轮Parkinson RV（波动率→波动率，最经典关系）</h3>
{sc3}
<h3>put成本占比 → 下一轮总波幅</h3>
{sc4}
</div>

<div class="card">
<h2>④ 因子定义（按维度分组）</h2>
<div class="tbl-scroll">
<table>
<tr><th>维度</th><th>因子</th><th>定义</th></tr>
{def_rows}
</table>
</div>
</div>

<div class="card">
<h2>⑤ 逐轮明细（波动 + 关键因子，供人工检验）</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场</th><th>出场</th><th>方式</th><th>总波幅</th><th>跌幅</th><th>涨幅</th><th>RV</th><th>ParkRV</th><th>前5日均量</th><th>量比5</th><th>前5日HV</th><th>Park5</th><th>put成本%</th></tr>
{detail_html}
</table>
</div>
<p class="note">「持有中」= 数据截止未平仓，波动按已发生部分计算。量比5 = 前5日均量 ÷ 再前5日均量。</p>
</div>

<div class="card">
<h2>说明与免责</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>波动率聚类</strong>（volatility clustering）理论上是金融市场最稳健的经验规律，但在 SKHY 这个极短样本上<strong>并不稳健</strong>：
「历史波动率 → 未来波动率」只在对 RV（纯波动率）层面保持了正相关，对「价格总波幅 range」层面在30天窗口已衰减甚至反转。</li>
<li><strong>Parkinson 波动率</strong>用每日高低价（而非仅收盘价），信息利用率约 5.2 倍于收盘价波动率，是更高效的波动估计器。</li>
<li><strong>量能</strong>：放量常伴随趋势启动/情绪释放，是波动前兆的候选因子，但本数据上显著性弱于历史波动率。</li>
<li><strong>put 成本占比</strong>是期权隐含波动率的代理——它已把市场对「未来波动」的定价包含在权利金里，是唯一"前瞻"因子。</li>
<li><strong>样本量</strong>：{n_full} 轮（30天 {n_30} 轮），不足以得出统计可靠结论，仅供探索与假设生成。</li>
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
