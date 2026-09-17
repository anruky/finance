#!/usr/bin/env python3
"""
DRAM / SK海力士(SKHY) / SanDisk(SNDK) 三标的对冲策略汇总报告
============================================================
① 行情与技术指标：三标的归一化收盘价同图（K线风格折线）
② 最优策略逐轮明细：按周对齐，三标的 成本占比 / 最终收益 / 收益比 并排对比
"""
import json
import importlib.util
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# 复用 sandisk 的 backtest 核心逻辑（三份 run_v10 逻辑一致）
spec = importlib.util.spec_from_file_location("bt", "sandisk/real_options_backtest_v10.py")
bt = importlib.util.module_from_spec(spec)
sys.modules["bt"] = bt
spec.loader.exec_module(bt)

DATA = "/Users/gavinz/git/finance/data"
OUT = "/Users/gavinz/git/finance/hedge/summary_report.html"

CONFIGS = [
    dict(key="DRAM", label="DRAM",  color="#4da3ff", target=7, down=15, up=15, desc="7天 + 15%对称"),
    dict(key="SKHY", label="海力士", color="#f5a05a", target=2, down=15, up=8,  desc="最近周五 + 跌15%/涨8%"),
    dict(key="SNDK", label="闪迪",   color="#26c281", target=2, down=20, up=15, desc="最近周五 + 跌20%/涨15%"),
]


def load(ticker):
    opt = json.load(open(f"{DATA}/{ticker}_options_3fri.json"))
    day_map = {d["date"]: d for d in opt}
    stock = json.load(open(f"{DATA}/{ticker}_stock.json"))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
    return day_map, stock, closes, bars


def load_realtime():
    try:
        return json.load(open(f"{DATA}/realtime_snapshot.json"))
    except Exception:
        return None


RT = load_realtime()


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


# ============ 运行三标的最优策略 ============
results = {}
for c in CONFIGS:
    day_map, stock, closes, bars = load(c["key"])
    se = closes[stock[0][0]]
    sx = closes[stock[-1][0]]
    r = bt.run_v10(day_map, closes, bars, stock, se, sx, c["down"], c["target"], up_pct=c["up"])
    bh = bt.bh_benchmark(stock, closes)
    results[c["key"]] = dict(stock=stock, closes=closes, bars=bars, day_map=day_map, r=r, bh=bh, cfg=c)

# ============ 1. 归一化图（共同窗口 07-13 起） ============
anchor = "2026-07-13"
all_dates = set()
for key in results:
    all_dates |= set(results[key]["closes"].keys())
common = sorted(d for d in all_dates if d >= anchor)

date_idx = {d: i for i, d in enumerate(common)}
chart_series = {}
for key, res in results.items():
    closes = res["closes"]
    base = closes[anchor]
    # 只取该标的实际有的日期（缺失日期自动跳过，线到数据末就停）
    chart_series[key] = [(date_idx[d], round(closes[d] / base * 100, 1))
                         for d in common if d in closes and d >= anchor]

# ============ 2. 逐轮明细（三标的独立表格） ============
# 每只股票的资金基数（用各自首日收盘价 × 100，供"总收益率"参考）
cap = {key: results[key]["closes"][results[key]["stock"][0][0]] * 100 for key in results}

# ============ 3. 生成 HTML ============
# --- 归一化折线图 SVG ---
W, L, R, p_t, p_b = 680, 60, 662, 16, 200
n = len(common)
vmin = min(v for s in chart_series.values() for (_, v) in s)
vmax = max(v for s in chart_series.values() for (_, v) in s)
pad = (vmax - vmin) * 0.08
vmin -= pad; vmax += pad


def px(i):
    return L + (R - L) * (i + 0.5) / n


def py(v):
    return p_t + (p_b - p_t) * (vmax - v) / (vmax - vmin)


def seg(points, color, w=2.0):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"/>'


GRID = "rgba(154,163,178,0.10)"; MUTED = "#9aa3b2"; TEXT = "#e6e8ec"
s = []
for k in range(5):
    v = vmin + (vmax - vmin) * k / 4
    y = py(v)
    s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{R}" y2="{y:.1f}" stroke="{GRID}"/>')
    s.append(f'<text x="{L-8}" y="{y+4:.1f}" fill="{MUTED}" font-size="10" text-anchor="end">{v:.0f}</text>')
for key, res in results.items():
    pts = [(px(i), py(v)) for i, v in chart_series[key]]
    s.append(seg(pts, res["cfg"]["color"], 2.2))
# x 轴日期
for j in range(0, n, max(1, n // 7)):
    s.append(f'<text x="{px(j):.1f}" y="{p_b+18}" fill="{MUTED}" font-size="10" text-anchor="middle">{common[j][5:]}</text>')
chart_svg = f'<svg viewBox="0 0 {W} 260" xmlns="http://www.w3.org/2000/svg" role="img">\n' + "\n".join(s) + '\n</svg>'

legend = "".join(
    f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:18px;">'
    f'<span style="width:16px;height:3px;border-radius:2px;background:{res["cfg"]["color"]};"></span>'
    f'{res["cfg"]["label"]}</span>'
    for res in results.values()
)

# --- 逐轮明细表（三标的各自独立表格，每轮一行） ---
ROUND_HEAD = ("<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th>"
              "<th>行权价</th><th>股票涨跌</th><th>put成本</th><th>put收入</th><th>周期总利润</th>"
              "<th>成本占比</th><th>收益比</th></tr>")


def _round_rows(key):
    rows = []
    for rd in reversed(results[key]["r"]["rounds"]):
        total = rd["stock_pnl"] + rd["pnl"]
        base = rd["entry_spot"] * 100
        cost_ratio = rd["put_cost"] / base * 100 if base else 0
        ret_ratio = total / base * 100 if base else 0
        if rd["kind"] == "持有中":
            exit_cell = f'<td>{rd.get("expiry", rd["exit_date"])} 到期</td>'
        else:
            exit_cell = f'<td>{rd["exit_date"]}</td>'
        rows.append(
            f'<tr><td>{rd["entry_date"]}</td>'
            f'{exit_cell}'
            f'<td>{rd["kind"]}</td>'
            f'<td>${rd["entry_spot"]:.1f}</td>'
            f'<td>${rd["exit_spot"]:.1f}</td>'
            f'<td>${rd["strike"]:g}</td>'
            f'<td class="{pc(rd["stock_pnl"])}">${rd["stock_pnl"]:+,.0f}</td>'
            f'<td class="c-green">-${rd["put_cost"]:,.0f}</td>'
            f'<td class="c-red">${rd["put_income"]:+,.0f}</td>'
            f'<td class="{pc(total)}">${total:+,.0f}</td>'
            f'<td class="c-green">{cost_ratio:.1f}%</td>'
            f'<td class="{pc(total)}">{ret_ratio:+.1f}%</td>'
            f'</tr>'
        )
    return "\n".join(rows)


round_tables = []
for key in ["DRAM", "SKHY", "SNDK"]:
    cfg = results[key]["cfg"]
    r = results[key]["r"]
    round_tables.append(
        f'<h2 style="color:{cfg["color"]};margin-top:26px;font-size:16px;border-left-color:{cfg["color"]};">{cfg["label"]}（{cfg["desc"]}）'
        f'<span style="color:var(--muted);font-size:13px;font-weight:400;"> · {r["n_rounds"]} 轮'
        f' · 总收益 <span style="color:{pc(r["total"])};">${r["total"]:+,.0f}</span></span></h2>'
        f'<div class="tbl-scroll"><table>{ROUND_HEAD}{_round_rows(key)}</table></div>'
    )
round_tables_html = "\n".join(round_tables)

# --- 汇总 KPI ---
def _annualize(dec, days):
    """总收益率(小数) + 持有自然天数 -> 年化收益率(%)"""
    if days <= 0:
        return 0.0
    base = 1 + dec
    if base <= 0:
        return -100.0  # 本金亏光或更糟
    return (base ** (365.0 / days) - 1) * 100

kpi_rows = []
for key in ["DRAM", "SKHY", "SNDK"]:
    res = results[key]
    r, bh, cfg = res["r"], res["bh"], res["cfg"]
    stock = res["stock"]
    days = (datetime.strptime(stock[-1][0], "%Y-%m-%d") - datetime.strptime(stock[0][0], "%Y-%m-%d")).days
    r_dec = r["total"] / cap[key]
    bh_dec = bh["total"] / cap[key]
    r_ann = _annualize(r_dec, days)
    bh_ann = _annualize(bh_dec, days)
    kpi_rows.append(f"""
<div class="kpi">
<div class="label" style="color:{cfg['color']};">{cfg['label']} <span style="color:var(--muted);font-size:10px;">{cfg['desc']}</span></div>
<div class="value c-red">${r['total']:+,.0f}</div>
<div class="sub">策略年化 <span class="{pc(r_ann)}">{r_ann:+.1f}%</span> · 回撤 {r['mdd_pct']:.1f}% · {r['n_rounds']}轮</div>
<div class="sub">B&H年化 <span class="{pc(bh_ann)}">{bh_ann:+.1f}%</span> · 回撤 {bh['mdd_pct']:.1f}% · {days}天</div>
</div>""")
kpi_html = "\n".join(kpi_rows)

# --- 行情指标快照表 ---
snap_rows = []
for key in ["DRAM", "SKHY", "SNDK"]:
    res = results[key]
    stock, closes, cfg = res["stock"], res["closes"], res["cfg"]
    last_date = stock[-1][0]
    last_close = closes[last_date]
    first_close = closes[stock[0][0]]
    chg = (last_close / first_close - 1) * 100
    # 区间最高/最低（收盘）
    all_c = [closes[r[0]] for r in stock]
    hi = max(all_c); lo = min(all_c)
    # 实时现价（如快照存在）
    if RT and key in RT:
        live = RT[key]["spot"]
        live_chg = RT[key]["chg_pct"]
        price_cell = (f'<td class="c-red">${live:.2f}'
                      f'<div style="font-size:11px;color:var(--muted);">实时 · 当日 <span class="{pc(live_chg)}">{live_chg:+.2f}%</span></div></td>')
    else:
        price_cell = f'<td class="c-red">${last_close:.2f}</td>'
    snap_rows.append(f"""
<tr>
<td style="color:{cfg['color']};font-weight:600;">{cfg['label']}（{key}）</td>
{price_cell}
<td class="{pc(chg)}">{chg:+.1f}%</td>
<td>${lo:.2f} ~ ${hi:.2f}</td>
<td>{stock[0][0]} ~ {stock[-1][0]}（{len(stock)}天）</td>
</tr>""")
snap_html = "\n".join(snap_rows)

# --- 技术指标 + Put 报价（参考 sandisk 报告口径） ---
def _ma(arr, k):
    if len(arr) < k:
        return sum(arr) / len(arr)
    return sum(arr[-k:]) / k

ind = {}
rt_mode = RT is not None
if rt_mode:
    # 用实时快照数据（现在这个时点）
    for key in ["DRAM", "SKHY", "SNDK"]:
        d = RT.get(key)
        if not d:
            continue
        spot = d["spot"]
        put_px = d["put_vw"] if d.get("put_vw") is not None else d.get("put_last")
        ind[key] = dict(last_close=spot, ma20=d["ma20"], vs_ma20=d["vs_ma20"],
                        near_vw=put_px, near_strike=d["atm_strike"], near_expiry=d["expiry"],
                        cost_ratio=(put_px * 2 / spot * 100) if put_px is not None and spot else None,
                        spot=spot, chg_pct=d["chg_pct"])
else:
    for key in ["DRAM", "SKHY", "SNDK"]:
        res = results[key]
        stock, closes, day_map, cfg = res["stock"], res["closes"], res["day_map"], res["cfg"]
        all_c = [closes[r[0]] for r in stock]
        last_close = all_c[-1]
        ma20 = _ma(all_c, 20)
        vs_ma20 = (last_close / ma20 - 1) * 100
        # 最新 ATM put（用该标的自己的最优周期 target）
        last_opt_date = max(day_map.keys())
        last_day = day_map[last_opt_date]
        spot = last_day["spot"]
        near_f = bt.pick_friday(last_day, cfg["target"])
        near_atm = bt.atm_put(near_f, spot) if near_f else None
        if near_atm is not None:
            near_vw = near_atm["vw"]
            near_strike = near_atm["strike"]
            near_expiry = near_f["expiry"]
            cost_ratio = near_vw * 200 / (spot * 100) * 100  # 2张成本 / 100股市值
        else:
            near_vw = near_strike = near_expiry = None
            cost_ratio = None
        ind[key] = dict(last_close=last_close, ma20=ma20, vs_ma20=vs_ma20,
                        near_vw=near_vw, near_strike=near_strike, near_expiry=near_expiry,
                        cost_ratio=cost_ratio, spot=spot)

def _ind_cell(key, row):
    d = ind[key]
    cfg = results[key]["cfg"]
    if row == "spot":
        return f'<td class="c-red">${d["spot"]:.2f}</td>'
    if row == "chg_pct":
        v = d.get("chg_pct", 0)
        return f'<td class="{pc(v)}">{v:+.2f}%</td>'
    if row == "ma20":
        return f'<td class="c-red">${d["ma20"]:.2f}</td>'
    if row == "vs_ma20":
        v = d["vs_ma20"]
        s = "站上" if v >= 0 else "跌破"
        return f'<td class="{pc(v)}">{v:+.1f}%（{s}）</td>'
    if row == "atm_put":
        if d["near_vw"] is None:
            return '<td class="c-gray">—</td>'
        return f'<td class="c-red">${d["near_vw"]:.2f}/股</td>'
    if row == "atm_strike":
        if d["near_strike"] is None:
            return '<td class="c-gray">—</td>'
        return f'<td>${d["near_strike"]:g} · {d["near_expiry"]}</td>'
    if row == "cost_ratio":
        if d["cost_ratio"] is None:
            return '<td class="c-gray">—</td>'
        return f'<td class="c-green">{d["cost_ratio"]:.1f}%</td>'
    return "<td></td>"

ind_rows = []
if rt_mode:
    cells = "".join(_ind_cell(key, "spot") for key in ["DRAM", "SKHY", "SNDK"])
    ind_rows.append(f'<tr><td style="color:var(--muted);font-weight:600;">现价（实时）</td>{cells}</tr>')
    cells = "".join(_ind_cell(key, "chg_pct") for key in ["DRAM", "SKHY", "SNDK"])
    ind_rows.append(f'<tr><td style="color:var(--muted);font-weight:600;">当日涨跌</td>{cells}</tr>')
put_label = "买入 ATM Put（成交量加权 vw）" if rt_mode else "买入 ATM Put（现价档）"
for row, name in [("ma20", "均线 MA20"), ("vs_ma20", "现价 vs MA20"),
                  ("atm_put", put_label), ("atm_strike", "行权价 · 到期"),
                  ("cost_ratio", "Put 成本比例（2张）")]:
    cells = "".join(_ind_cell(key, row) for key in ["DRAM", "SKHY", "SNDK"])
    ind_rows.append(f'<tr><td style="color:var(--muted);font-weight:600;">{name}</td>{cells}</tr>')
ind_html = "\n".join(ind_rows)

rt_badge = ""
rt_note_extra = ""
if rt_mode:
    rt_badge = (f'<span style="font-size:12px;color:var(--gold);font-weight:600;margin-left:10px;">'
                f'● 实时快照 @ {RT.get("asof", "")} · {RT.get("note", "")}</span>')
    rt_note_extra = ("下面「技术指标 & Put 报价」和「现价」列已替换为当前时点的实时数据"
                     f"（快照时间 {RT.get('asof', '')}）。Put 价格 = 最近交易日成交量加权价 vw，"
                     "与历史逐轮明细口径一致。")

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM / 海力士 / 闪迪 对冲策略汇总报告</title>
<style>
:root {{ --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }}
.wrap {{ max-width:1120px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:6px; }}
h2 {{ font-size:18px; margin:30px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }}
.kpi .label {{ color:var(--muted); font-size:13px; font-weight:600; }}
.kpi .value {{ font-size:24px; font-weight:700; margin-top:4px; }}
.kpi .sub {{ color:var(--muted); font-size:12px; margin-top:3px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }}
th {{ background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }}
th:first-child, td:first-child {{ text-align:left; }}
.c-red {{ color:var(--red); font-weight:600; }}
.c-green {{ color:var(--green); font-weight:600; }}
.c-gray {{ color:var(--muted); }}
.c-gold {{ color:var(--gold); font-weight:700; }}
.callout {{ background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:12px 16px; margin:12px 0; font-size:13px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
code {{ background:#20242d; border:1px solid var(--border); border-radius:4px; padding:1px 6px;
  font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; color:var(--gold); }}
.tbl-scroll {{ overflow-x:auto; }}
</style>
</head>
<body>
<div class="wrap">
<h1>DRAM / 海力士 / 闪迪 对冲策略汇总报告</h1>
<p class="sub">三标的归一化对比 + 逐轮明细并排 · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="card">
<h2 style="margin-top:0;">行情与技术指标{rt_badge}</h2>
<div style="margin-bottom:12px;">{legend}</div>
<div style="margin-bottom:8px;">{chart_svg}</div>
<p class="note">三条曲线 = 收盘价归一化（{anchor} 起 = 100）。三标的价格量级差异大（DRAM ~$54、海力士 ~$155、闪迪 ~$1500），归一化后才能同图对比。</p>
<div class="tbl-scroll" style="margin-top:14px;">
<table>
<tr><th>标的</th><th>现价</th><th>区间涨跌</th><th>区间最低~最高（收盘）</th><th>数据范围</th></tr>
{snap_html}
</table>
</div>
<div class="tbl-scroll" style="margin-top:14px;">
<table>
<tr><th>技术指标 &amp; Put 报价{'（实时）' if rt_mode else ''}</th><th>DRAM</th><th>海力士</th><th>闪迪</th></tr>
{ind_html}
</table>
</div>
<p class="note">均线 MA20 = 最近 20 个交易日收盘价均值；现价 vs MA20 为正 = 站上均线（短期偏强），为负 = 跌破均线（短期偏弱）。买入 ATM Put = 最新期权链里最接近现价的平值档 put。Put 成本比例（2张）= 2 张 put 总成本 ÷ 100 股市值。海力士/闪迪用各自最优周期选到期日，DRAM 用 7 天。{rt_note_extra}</p>
</div>

<div class="card">
<h2 style="margin-top:0;">三标的策略概览（各自最优参数）</h2>
<div class="kpis">{kpi_html}</div>
<p class="note">年化收益 = (1 + 总收益率)^(365/持有天数) − 1，总收益率 = 总收益 ÷ 期初市值（100 股 × 首日收盘价）。注意：短周期的年化会被放大（尤其海力士仅 42 天），跨标的对比年化时需结合持有天数。三标的分别用各自扫描出的最优参数（DRAM 7天+15%对称、海力士最近周五+跌15%/涨8%、闪迪最近周五+跌20%/涨15%），2:1 过度对冲。</p>
</div>

<div class="card">
<h2>最优策略逐轮明细（三标的独立表格，每轮一行，最新在前）</h2>
<p class="note" style="margin-bottom:10px;">每行 = 一笔 put 持仓轮（入场 → 出场）。周期总利润 = 股票涨跌 + put收入 − put成本；成本占比 = put成本 ÷ 入场市值（100 股 × 入场spot）；收益比 = 周期总利润 ÷ 入场市值。方式：到期 = 持有到期滚动、上涨再平衡 = 涨到熔断线平仓重开、下跌止盈 = 跌到熔断线平仓重开、持有中 = 数据截止时未平仓（mark-to-market 估值）。</p>
{round_tables_html}
</div>

<div class="card">
<h2>说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>如何刷新数据</strong>：在 <code>hedge/</code> 目录执行 <code>./refresh_summary.sh</code>，一次刷齐全量数据（股票日线 + 期权增量 + 实时指标 + 逐轮明细回测），通常几十秒；<code>./refresh_summary.sh --full</code> 会强制期权全量重拉（慢，修复历史数据用）。</li>
<li><strong>策略框架通用</strong>：买 put 对冲 + 开盘价涨跌熔断 + 2:1 过度对冲。三标的各自扫描出的最优涨/跌熔断和周期不同（DRAM 7天+15%对称、海力士最近周五+跌15%/涨8%、闪迪最近周五+跌20%/涨15%）。</li>
<li><strong>收益比</strong> = 周期总利润 ÷ 入场市值（100 股 × 入场spot），是资金收益率口径。</li>
<li><strong>三标的可对比窗口为 07-13 之后</strong>：海力士(SKHY) 07-13 才在 Nasdaq 上市，DRAM 数据 04-02 起、闪迪 05-26 起，故归一化图在各自数据起点前为空；逐轮明细表为三标的独立表格，各列自身完整轮次。</li>
<li><strong>真实成交价</strong>：Put 成本用每日期权链成交量加权价 vw，非 BS 理论价。</li>
<li><strong>仅供研究，不构成投资建议</strong>。三标的样本量有限（DRAM 99天/海力士31天/闪迪65天），参数含过拟合风险。</li>
</ul>
</div>

</div>
</body>
</html>"""

with open(OUT, "w") as f:
    f.write(html)
print(f"汇总报告已生成: {OUT}")
for key in ["DRAM", "SKHY", "SNDK"]:
    r = results[key]["r"]
    print(f"  {key}: {r['n_rounds']}轮, 收益 ${r['total']:+,.0f}, 回撤 {r['mdd_pct']:.1f}%")
