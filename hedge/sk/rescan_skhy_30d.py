#!/usr/bin/env python3
"""
SKHY 对冲策略 —— 最近 30 天全参数重扫（临时程序，不动现有 final 程序/报告）
=====================================================================
只用最近 30 个交易日（去掉上市初期 07-13 ~ 07-30 的暴涨暴跌段），重新扫描四维参数空间：
  · 周期 target      : 2(最近周五) / 7 / 14 / 21 天
  · 跌熔断 down       : 5 / 8 / 10 / 12 / 15 / 20 / 25 %
  · 涨熔断 up         : 5 / 8 / 10 / 12 / 15 / 20 / 25 %
  · put 手数 num_puts : 1 / 2 / 3 / 4 手（对应 股票:put = 1:1 / 1:2 / 1:3 / 1:4）

输出临时报告：skhy_rescan_30d_report.html
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# 复用现有回测核心 run_v10（只读加载，不改动源文件）
_code = open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0]
_ns = {}
exec(_code, _ns)
run_v10 = _ns["run_v10"]

DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(os.path.dirname(__file__), "skhy_rescan_30d_report.html")
WINDOW_DAYS = 30  # 只用最近 30 个交易日

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
DOWNS = [5, 8, 10, 12, 15, 20, 25]
UPS = [5, 8, 10, 12, 15, 20, 25]
NUM_PUTS = [1, 2, 3, 4]


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def bg(value, vmin, vmax, kind):
    """热力图单元格背景色：kind='pnl' 红涨绿跌，kind='ratio' 金色深浅"""
    if vmax == vmin:
        a = 0.0
    else:
        a = (value - vmin) / (vmax - vmin)
    a = max(0.0, min(1.0, a))
    if kind == "pnl":
        if value >= 0:
            return f"background:rgba(255,82,82,{0.08 + 0.30 * a});"
        else:
            return f"background:rgba(38,194,129,{0.08 + 0.30 * (1 - a)});"
    else:  # ratio
        return f"background:rgba(245,195,68,{0.06 + 0.30 * a});"


def main():
    data = json.load(open(os.path.join(DATA, "SKHY_options_3fri.json")))
    day_map = {d["date"]: d for d in data}
    stock = json.load(open(os.path.join(DATA, "SKHY_stock.json")))
    stock = stock[-WINDOW_DAYS:]  # 只用最近 30 个交易日
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
    se = closes[stock[0][0]]
    sx = closes[stock[-1][0]]

    # B&H 基准
    bh_pnl = (sx - se) * 100
    peak = 0.0; mdd = 0.0
    for r in stock:
        v = (closes[r[0]] - se) * 100
        peak = max(peak, v); mdd = max(mdd, peak - v)
    bh_mdd_pct = mdd / (se * 100 + peak) * 100 if (se * 100 + peak) > 0 else 0
    bh_ratio = bh_pnl / mdd if mdd > 0 else 0

    print(f"SKHY 数据: {stock[0][0]} ~ {stock[-1][0]} ({len(stock)} 交易日), 首日 ${se:.2f} -> 末日 ${sx:.2f}")
    print(f"B&H 基准: 收益 ${bh_pnl:+,.0f}, 回撤 {bh_mdd_pct:.1f}%, 比 {bh_ratio:.2f}")

    # ============ 全四维扫描 ============
    results = []
    for target in TARGET_LABELS:
        for down in DOWNS:
            for up in UPS:
                for np_ in NUM_PUTS:
                    r = run_v10(day_map, closes, bars, stock, se, sx, down, target, num_puts=np_, up_pct=up)
                    r["target"] = target; r["down"] = down; r["up"] = up; r["num_puts"] = np_
                    r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
                    results.append(r)
    print(f"扫描完成: {len(results)} 组参数组合")

    best = max(results, key=lambda x: x["ratio"])
    best_total = max(results, key=lambda x: x["total"])
    print(f"最优(收益/回撤比): 周期{best['target']} 跌{best['down']}%/涨{best['up']}% put{best['num_puts']}手 "
          f"-> 收益${best['total']:+,.0f} 回撤{best['mdd_pct']:.1f}% 比{best['ratio']:.2f}")
    print(f"最优(总收益): 周期{best_total['target']} 跌{best_total['down']}%/涨{best_total['up']}% put{best_total['num_puts']}手 "
          f"-> 收益${best_total['total']:+,.0f} 回撤{best_total['mdd_pct']:.1f}% 比{best_total['ratio']:.2f}")

    # 旧参数（现有 final 的最优）对比
    old = run_v10(day_map, closes, bars, stock, se, sx, 15, 2, num_puts=2, up_pct=8)
    old["ratio"] = old["total"] / old["mdd"] if old["mdd"] > 0 else 0

    # ============ 各维度切片 ============
    # 1) 对冲比例切片：固定最优 target/down/up，扫 num_puts
    ratio_slice = [next(r for r in results if r["target"] == best["target"] and r["down"] == best["down"]
                        and r["up"] == best["up"] and r["num_puts"] == np_) for np_ in NUM_PUTS]

    # 2) 熔断矩阵：固定最优 target/num_puts，扫 down×up（收益 + 回撤比两个矩阵）
    def cell(r, field):
        return [next(x for x in results if x["target"] == best["target"] and x["num_puts"] == best["num_puts"]
                    and x["down"] == r and x["up"] == u)[field] for u in UPS]

    pnl_mat = {d: cell(d, "total") for d in DOWNS}
    ratio_mat = {d: cell(d, "ratio") for d in DOWNS}
    pnl_vals = [v for d in DOWNS for v in pnl_mat[d]]
    ratio_vals = [v for d in DOWNS for v in ratio_mat[d]]
    pnl_min, pnl_max = min(pnl_vals), max(pnl_vals)
    ratio_min, ratio_max = min(ratio_vals), max(ratio_vals)

    # 3) 周期切片：固定最优 down/up/num_puts，扫 target
    target_slice = [next(r for r in results if r["down"] == best["down"] and r["up"] == best["up"]
                         and r["num_puts"] == best["num_puts"] and r["target"] == t) for t in TARGET_LABELS]

    # ============ 报告渲染 ============
    def kpi(label, value_html, sub=""):
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value_html}</div><div class="sub">{sub}</div></div>')

    # Top 10
    top10 = sorted(results, key=lambda x: x["ratio"], reverse=True)[:10]
    top10_rows = []
    for i, r in enumerate(top10, 1):
        is_best = (r is best)
        mark = ' <span class="c-gold">★最优</span>' if is_best else ""
        top10_rows.append(
            f'<tr><td>{i}</td>'
            f'<td>{TARGET_LABELS[r["target"]]}</td>'
            f'<td>{r["down"]}%</td><td>{r["up"]}%</td>'
            f'<td>1:{r["num_puts"]}</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>{r["mdd_pct"]:.1f}%</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td>'
            f'<td>{r["down_hits"]}</td><td>{r["up_hits"]}</td><td>{r["expiries"]}</td></tr>'
        )
    top10_html = "\n".join(top10_rows)

    # 对冲比例切片表
    ratio_rows = []
    for r in ratio_slice:
        is_best = (r["num_puts"] == best["num_puts"])
        mark = ' <span class="c-gold">★</span>' if is_best else ""
        ratio_rows.append(
            f'<tr><td>1:{r["num_puts"]}</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>{r["mdd_pct"]:.1f}%</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td>'
            f'<td>${r["put_net"]:+,.0f}</td></tr>'
        )
    ratio_rows_html = "\n".join(ratio_rows)

    # 熔断热力图（收益）
    def matrix_html(mat, vals, kind, title):
        head = "".join(f"<th>涨{up}%</th>" for up in UPS)
        rows = []
        for down in DOWNS:
            tds = []
            for i in range(len(UPS)):
                v = mat[down][i]
                txt = f"${v:+,.0f}" if kind == "pnl" else f"{v:.2f}"
                tds.append(f'<td style="{bg(v, min(vals), max(vals), kind)}">{txt}</td>')
            rows.append(f"<tr><td>跌{down}%</td>{''.join(tds)}</tr>")
        return (f'<div style="margin-top:6px;"><h3 style="font-size:15px;color:var(--text);margin:18px 0 8px;">{title}</h3>'
                f'<table><tr><th>跌\\涨</th>{head}</tr>{"".join(rows)}</table></div>')

    pnl_matrix_html = matrix_html(pnl_mat, pnl_vals, "pnl", "熔断矩阵 —— 总收益（固定最优周期 & put 比例）")
    ratio_matrix_html = matrix_html(ratio_mat, ratio_vals, "ratio", "熔断矩阵 —— 收益/回撤比（固定最优周期 & put 比例）")

    # 周期切片
    target_rows = []
    for r in target_slice:
        is_best = (r["target"] == best["target"])
        mark = ' <span class="c-gold">★</span>' if is_best else ""
        target_rows.append(
            f'<tr><td>{TARGET_LABELS[r["target"]]}</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>{r["mdd_pct"]:.1f}%</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td></tr>'
        )
    target_rows_html = "\n".join(target_rows)

    # 旧 vs 新 对比
    cmp_rows = (
        f'<tr><td style="color:var(--muted);">旧参数（final 报告）</td>'
        f'<td>最近周五</td><td>15%</td><td>8%</td><td>1:2</td>'
        f'<td class="{pc(old["total"])}">${old["total"]:+,.0f}</td>'
        f'<td>{old["mdd_pct"]:.1f}%</td><td>{old["ratio"]:.2f}</td><td>{old["n_rounds"]}</td></tr>'
        f'<tr><td style="color:var(--gold);font-weight:700;">新最优（本次重扫）</td>'
        f'<td>{TARGET_LABELS[best["target"]]}</td><td>{best["down"]}%</td><td>{best["up"]}%</td><td>1:{best["num_puts"]}</td>'
        f'<td class="{pc(best["total"])}">${best["total"]:+,.0f}</td>'
        f'<td>{best["mdd_pct"]:.1f}%</td><td class="c-gold">{best["ratio"]:.2f}</td><td>{best["n_rounds"]}</td></tr>'
    )

    # 最优组合逐轮明细
    detail_rows = []
    for rd in reversed(best["rounds"]):
        total_r = rd["stock_pnl"] + rd["pnl"]
        base = rd["entry_spot"] * 100
        cost_ratio = rd["put_cost"] / base * 100 if base else 0
        if rd["kind"] == "持有中":
            exit_cell = f'<td>{rd.get("expiry", rd["exit_date"])} 到期</td>'
        else:
            exit_cell = f'<td>{rd["exit_date"]}</td>'
        detail_rows.append(
            f'<tr><td>{rd["entry_date"]}</td>{exit_cell}<td>{rd["kind"]}</td>'
            f'<td>${rd["entry_spot"]:.1f}</td><td>${rd["exit_spot"]:.1f}</td>'
            f'<td>${rd["strike"]:g}</td>'
            f'<td class="{pc(rd["stock_pnl"])}">${rd["stock_pnl"]:+,.0f}</td>'
            f'<td class="c-green">-${rd["put_cost"]:,.0f}</td>'
            f'<td class="c-red">${rd["put_income"]:+,.0f}</td>'
            f'<td class="{pc(total_r)}">${total_r:+,.0f}</td>'
            f'<td class="c-green">{cost_ratio:.1f}%</td></tr>'
        )
    detail_html = "\n".join(detail_rows)

    css = """
:root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }
.wrap { max-width:1180px; margin:0 auto; }
h1 { font-size:24px; margin-bottom:6px; }
h2 { font-size:18px; margin:30px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }
h3 { font-size:15px; margin:18px 0 8px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin-bottom:18px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }
.kpi .label { color:var(--muted); font-size:13px; font-weight:600; }
.kpi .value { font-size:24px; font-weight:700; margin-top:4px; }
.kpi .sub { color:var(--muted); font-size:12px; margin-top:3px; margin-bottom:0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }
th { background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }
th:first-child, td:first-child { text-align:left; }
.c-red { color:var(--red); font-weight:600; }
.c-green { color:var(--green); font-weight:600; }
.c-gray { color:var(--muted); }
.c-gold { color:var(--gold); font-weight:700; }
.callout { background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:12px 16px; margin:12px 0; font-size:13px; }
.note { color:var(--muted); font-size:12px; margin-top:8px; }
code { background:#20242d; border:1px solid var(--border); border-radius:4px; padding:1px 6px;
  font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; color:var(--gold); }
.tbl-scroll { overflow-x:auto; }
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SKHY 全参数重扫报告</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>SKHY（SK海力士 ADR）对冲策略 —— 最近 30 天全参数重扫</h1>
<p class="sub">临时报告 · 最近 30 个交易日 {stock[0][0]} ~ {stock[-1][0]}（已去掉上市初期 07-13 ~ 07-30 暴涨暴跌段） · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="kpis">
{kpi('数据跨度', f'{len(stock)} 天', f'{stock[0][0]} ~ {stock[-1][0]}')}
{kpi('B&H 基准收益', money(bh_pnl), f'回撤 {bh_mdd_pct:.1f}% · 比 {bh_ratio:.2f}')}
{kpi('新最优总收益', money(best['total']), f'{TARGET_LABELS[best["target"]]} · 跌{best["down"]}%/涨{best["up"]}% · 1:{best["num_puts"]}')}
{kpi('新最优回撤', f'{best["mdd_pct"]:.1f}%', f'收益/回撤比 {best["ratio"]:.2f}')}
{kpi('总收益最高组合', money(best_total['total']), f'跌{best_total["down"]}%/涨{best_total["up"]}% · 1:{best_total["num_puts"]} · 回撤{best_total["mdd_pct"]:.1f}%')}
</div>

<div class="callout">
<strong>结论：</strong>在最新 {len(stock)} 个交易日数据上，重新扫描 {len(results)} 组参数后，<strong class="c-gold">最优（收益/回撤比）组合</strong>为：
周期 <strong>{TARGET_LABELS[best["target"]]}</strong>、跌熔断 <strong>{best["down"]}%</strong>、涨熔断 <strong>{best["up"]}%</strong>、对冲比例 <strong>1:{best["num_puts"]}</strong>，
总收益 <strong class="{pc(best['total'])}">${best['total']:+,.0f}</strong>、回撤 <strong>{best['mdd_pct']:.1f}%</strong>、收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>。
</div>

<div class="card">
<h2 style="margin-top:0;">旧参数 vs 新最优</h2>
<div class="tbl-scroll">
<table>
<tr><th>参数集</th><th>周期</th><th>跌熔断</th><th>涨熔断</th><th>对冲比例</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th></tr>
{cmp_rows}
</table>
</div>
<p class="note">旧参数 = 现有 final 报告（<code>skhy_final_report.html</code>）里的最优：最近周五 + 跌15%/涨8% + 1:2。</p>
</div>

<div class="card">
<h2 style="margin-top:0;">Top 10 参数组合（按收益/回撤比排序）</h2>
<div class="tbl-scroll">
<table>
<tr><th>#</th><th>周期</th><th>跌熔断</th><th>涨熔断</th><th>对冲比例</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th><th>跌触发</th><th>涨触发</th><th>到期</th></tr>
{top10_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">对冲比例（股票:put）敏感性</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">固定最优周期 {TARGET_LABELS[best["target"]]} + 跌{best["down"]}%/涨{best["up"]}%，只改 put 手数。put 净 = put 收入 − put 成本（对冲部分的净贡献）。</p>
<div class="tbl-scroll">
<table>
<tr><th>股票:put</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th><th>put 净</th></tr>
{ratio_rows_html}
</table>
</div>
<p class="note">1:1 = 100 股配 1 手 put（完全对冲）；1:2 = 配 2 手（2 倍过度对冲，旧默认）；1:3 / 1:4 为更高倍数过度对冲。比例越高，下行保护越强但保费成本也越贵。</p>
</div>

<div class="card">
<h2 style="margin-top:0;">熔断比例扫描（不对称矩阵）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">固定最优周期 {TARGET_LABELS[best["target"]]} + 最优对冲比例 1:{best["num_puts"]}，扫描跌熔断 × 涨熔断。★ 单元格为全局最优（回撤比口径）。</p>
{pnl_matrix_html}
{ratio_matrix_html}
</div>

<div class="card">
<h2 style="margin-top:0;">周期敏感性</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">固定最优熔断跌{best["down"]}%/涨{best["up"]}% + 最优对冲比例 1:{best["num_puts"]}，只改周期。</p>
<div class="tbl-scroll">
<table>
<tr><th>周期</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th></tr>
{target_rows_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">新最优组合逐轮明细</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">周期 {TARGET_LABELS[best["target"]]} + 跌{best["down"]}%/涨{best["up"]}% + 1:{best["num_puts"]}。方式：到期 / 上涨再平衡 / 下跌止盈 / 持有中（数据截止未平仓，按现价估值）。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th><th>行权价</th><th>股票涨跌</th><th>put成本</th><th>put收入</th><th>周期总利润</th><th>成本占比</th></tr>
{detail_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>股票:put 比例</strong>：股票固定 100 股，put 手数可调。1:N 表示配 N 手 put（N×100 股名义）。</li>
<li><strong>口径</strong>：开盘价熔断（盘中不触发）；put 成本/收入用每日期权链成交量加权价 vw，非 BS 理论价。</li>
<li><strong>最优标准</strong>：默认用「收益/回撤比」最大（与现有 final 报告一致）；报告另附「总收益最高」组合供参考。</li>
<li><strong>本程序为临时重扫</strong>（<code>rescan_skhy.py</code>），不改动现有 <code>gen_final_report.py</code> / <code>real_options_backtest_v10.py</code> / <code>skhy_final_report.html</code>。</li>
<li><strong>过拟合警示</strong>：SKHY 仅 {len(stock)} 个交易日，样本短、波动大，参数稳定性低，仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""

    with open(OUT, "w") as f:
        f.write(html)
    print(f"\n临时报告已生成: {OUT}")
    print(f"  扫描 {len(results)} 组参数 → 最优比 {best['ratio']:.2f} (旧 {old['ratio']:.2f})")


if __name__ == "__main__":
    main()
