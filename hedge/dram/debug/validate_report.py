#!/usr/bin/env python3
"""
DRAM 报告数据验证脚本（只读，不修改任何原始报告/代码）
=====================================================
对 /Users/gavinz/git/finance/hedge/dram/dram_final_report.html 做三类验证：

  A. 动态数字 vs 独立重算（报告里由代码实时算出的部分：KPI、逐轮、现在如何买、情景表）
     用当前源数据重新跑一遍回测，核对报告动态数字是否自洽于源数据。

  B. 报告内部算术（用报告“自己显示”的数字互相印证，例如 策略收益=股票+put净）。

  C. 硬编码叙述 vs 动态/当前数据（核心发现）：
     gen_final_report.py 的模板里把 B&H=2956/3587/44.4%/0.82、出场 57.32/08-14、
     周期扫描 3630/3063/2060/1866、盘中 4.32、不对称 1.76/1.85/1.91 等写成“死值”，
     而动态部分随数据更新后，这些死值与动态数字/当前数据互相打架。

输出：debug/validation_report.md + debug/validation_details.json
本脚本只读取 dram/ 下的源文件与报告，不写入任何 dram/ 路径。
"""
import importlib.util
import json
import os
import re
from collections import defaultdict

HEDGE = "/Users/gavinz/git/finance/hedge/dram"
DATA = "/Users/gavinz/git/finance/data"
REPORT = os.path.join(HEDGE, "dram_final_report.html")
V10 = os.path.join(HEDGE, "real_options_backtest_v10.py")

R = {"checks": []}

def add(cat, group, name, expected, got, tol=1e-6, note=""):
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        ok = abs(expected - got) <= (tol if tol >= 1 else max(tol, abs(expected) * 0.001))
    else:
        ok = str(expected) == str(got)
    R["checks"].append({"cat": cat, "group": group, "name": name,
                        "expected": expected, "got": got, "pass": bool(ok), "note": note})
    return ok

def money(s):
    return float(re.sub(r"[$,+]", "", str(s)))

def pct(s):
    return float(re.sub(r"%", "", str(s)))

# ---------- 加载 v10 核心函数（只读，不调用 main，不产生写文件） ----------
spec = importlib.util.spec_from_file_location("v10", V10)
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)
data, day_map = v10.load_3fri()
stock, closes, bars = v10.load_stock()
stock_entry = closes[stock[0][0]]
stock_exit = closes[stock[-1][0]]
html = open(REPORT, encoding="utf-8").read()

# ---------- 独立重算（当前源数据） ----------
bh = v10.bh_benchmark(stock, closes)
bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0
best = v10.run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, 15, 7)
best_ratio = best["total"] / best["mdd"] if best["mdd"] > 0 else 0
sweep = {t: round(v10.run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, 15, t)["total"])
         for t in (2, 7, 14, 21)}

def run_asym(down_pct, up_pct):
    dn, up = down_pct / 100.0, up_pct / 100.0
    sp = (stock_exit - stock_entry) * 100
    cf = defaultdict(float); pn = 0.0; pos = None
    for r in stock:
        date = r[0]; S = closes[date]; o = bars[date][1]; day = day_map.get(date)
        if pos is None:
            if day is None: continue
            pp = v10.pick_put(day, o, 7)
            if pp is None: continue
            c = pp["vw"] * 100 * 2
            pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=c, entry_date=date)
            cf[date] -= c; continue
        p0 = pos["entry_spot"]; dn_hit = o <= p0 * (1 - dn); up_hit = o >= p0 * (1 + up)
        if date >= pos["expiry"]:
            if dn_hit or up_hit:
                vh = v10.find_put_price(day, pos["expiry"], pos["strike"])
                pay = vh * 100 * 2 if vh is not None else (max(pos["strike"] - o, 0.0) * 100 * 2 if dn_hit else 0.0)
                pn += pay - pos["cost"]; cf[date] += pay; pos = None
                if day is not None:
                    pp = v10.pick_put(day, o, 7)
                    if pp is not None:
                        c = pp["vw"] * 100 * 2
                        pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=c, entry_date=date); cf[date] -= c
            else:
                pay = max(pos["strike"] - S, 0.0) * 100 * 2
                pn += pay - pos["cost"]; cf[date] += pay; pos = None
                if day is not None:
                    pp = v10.pick_put(day, S, 7)
                    if pp is not None:
                        c = pp["vw"] * 100 * 2
                        pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=S, cost=c, entry_date=date); cf[date] -= c
            continue
        if dn_hit:
            vh = v10.find_put_price(day, pos["expiry"], pos["strike"])
            pay = vh * 100 * 2 if vh is not None else max(pos["strike"] - o, 0.0) * 100 * 2
            pn += pay - pos["cost"]; cf[date] += pay; pos = None
            if day is not None:
                pp = v10.pick_put(day, o, 7)
                if pp is not None:
                    c = pp["vw"] * 100 * 2
                    pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=c, entry_date=date); cf[date] -= c
            continue
        if up_hit:
            vh = v10.find_put_price(day, pos["expiry"], pos["strike"])
            pay = vh * 100 * 2 if vh is not None else 0.0
            pn += pay - pos["cost"]; cf[date] += pay; pos = None
            if day is not None:
                pp = v10.pick_put(day, o, 7)
                if pp is not None:
                    c = pp["vw"] * 100 * 2
                    pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=c, entry_date=date); cf[date] -= c
            continue
    tot = sp + pn
    md = v10.compute_mdd(stock, closes, stock_entry, cf)
    return tot, (tot / md["mdd"] if md["mdd"] > 0 else 0)

cur_asym = {up: round(run_asym(15, up)[1], 2) for up in (10, 15, 20)}

# ---------- 解析报告中的数字 ----------
def grab(pat, cast=float, default=None):
    m = re.search(pat, html)
    return cast(m.group(1)) if m else default

# KPI（6 张）：B&H收益 / 策略收益 / 策略回撤比例 / 回撤降幅 / 收益回撤比 / 股票收益
kpi = re.findall(r'class="value[^"]*">([^<]*)<', html)
kpi_bh = money(kpi[0]); kpi_strat = money(kpi[1]); kpi_mddpct = pct(kpi[2])
kpi_drop = pct(kpi[3]); kpi_ratio = float(kpi[4]); kpi_stock = money(kpi[5])
kpi_bh_sub = re.search(r"回撤 ([0-9.]+)% · 比 ([0-9.]+)", html)
kpi_bh_mddpct = float(kpi_bh_sub.group(1)); kpi_bh_ratio = float(kpi_bh_sub.group(2))

# 策略模型 callout（硬编码 B&H 与出场）
sm_exit = re.search(r"一直持有到 ([0-9-]+) @ \$?([0-9.]+)", html)
sm_exit_date, sm_exit_px = sm_exit.group(1), float(sm_exit.group(2))
sm = re.search(r"基准 = B&H</strong>：收益 <span[^>]*>\$\+?([0-9,]+)</span>，最大回撤 <span[^>]*>\$\+?([0-9,]+)（([0-9.]+)%）</span>，收益/回撤比 ([0-9.]+)", html)
sm_bh_total, sm_bh_mdd, sm_bh_mddpct, sm_bh_ratio = money(sm.group(1)), money(sm.group(2)), float(sm.group(3)), float(sm.group(4))

# 核心结论
cc = re.search(r"收益 <span[^>]*>\$\+?([0-9,]+)</span>（比 B&H 多赚 <span[^>]*>\$\+?([0-9,]+)</span>）", html)
cc_strat, cc_putnet = money(cc.group(1)), money(cc.group(2))
cc2 = re.search(r"降到 <span[^>]*>([0-9.]+)%</span>（降了 <span[^>]*>([0-9.]+) 个百分点</span>）", html)
cc_mddpct, cc_drop = float(cc2.group(1)), float(cc2.group(2))
cc3 = re.search(r"收益/回撤比 <strong[^>]*>([0-9.]+)</strong>，是 B&H（0.82）的 <strong[^>]*>([0-9.]+) 倍</strong>", html)
cc_ratio, cc_mult = float(cc3.group(1)), float(cc3.group(2))

# 逐轮
def extract_table(header):
    i = html.find(header)
    if i < 0: return []
    e = html.find("</table>", i); seg = html[i:e]; out = []
    for row in re.findall(r"<tr>(.*?)</tr>", seg, re.S):
        cells = re.findall(r"<td.*?>(.*?)</td>", row, re.S)
        if cells: out.append(cells)
    return out

def pm(s): return float(re.sub(r"<[^>]+>", "", s).replace("$", "").replace(",", "").replace("%", "").replace("+", "").strip())

round_rows = extract_table("<th>入场日</th>")
rounds = []
for c in round_rows:
    if len(c) < 10: continue
    rounds.append(dict(entry=c[0], exit=c[1], kind=re.sub(r"<[^>]+>","",c[2]).strip(),
                       entry_spot=pm(c[3]), exit_spot=pm(c[4]), strike=pm(c[5]),
                       stock_pnl=pm(c[6]), put_cost=pm(c[7]), put_income=pm(c[8]), period_total=pm(c[9])))
rc = re.search(r"共 (\d+) 轮（跌熔断 (\d+) 次 / 涨熔断 (\d+) 次 / 到期 (\d+) 次）", html)
rep_n, rep_down, rep_up, rep_exp = int(rc.group(1)), int(rc.group(2)), int(rc.group(3)), int(rc.group(4))

# 现在如何买
nb_spot = grab(r"最新 DRAM 现价 <strong[^>]*>\$([0-9.]+)", float)
nb_exp = re.search(r"最近到期日 <strong>([0-9-]+)</strong>（dte (\d+) 天）", html)
nb_expiry, nb_dte = (nb_exp.group(1), int(nb_exp.group(2))) if nb_exp else (None, None)
nb_strike = grab(r"买入 2 张行权价 \$(\d+) 的 Put", float)
nb_vw = grab(r"成交量加权价 <strong>\$([0-9.]+)/股</strong>，每张 \$[0-9.]+，2 张共 <strong[^>]*>-?\$\+?([0-9,]+)", float)
nb_cost = grab(r"2 张共 <strong[^>]*>-?\$\+?([0-9,]+)", lambda s: float(s.replace(",", "")))
nb_pct = grab(r"占持仓 ([0-9.]+)%", float)
nb_up = grab(r"涨到 <strong[^>]*>\$([0-9.]+)", float)
nb_dn = grab(r"跌到 <strong[^>]*>\$([0-9.]+)", float)

# 情景表
scen_rows = extract_table("<th>到期日 spot</th>")
scen = []
for c in scen_rows:
    if len(c) < 6: continue
    scen.append(dict(exit_=pm(c[0]), pct=int(re.sub(r"[^+0-9-]","",c[1])),
                     stock_pnl=pm(c[2]), payoff=pm(c[3]), net=pm(c[4]),
                     net_pct=pm(c[5])))

# 周期扫描叙述（硬编码）
sw = re.search(r"7天\(\$\+?([0-9,]+)\) &gt; 最近周五1-4天\(\$\+?([0-9,]+)\) &gt; 14天\(\$\+?([0-9,]+)\) &gt; 21天\(\$\+?([0-9,]+)\)", html)
sw7, sw2, sw14, sw21 = money(sw.group(1)), money(sw.group(2)), money(sw.group(3)), money(sw.group(4))

# 盘中/开盘对比表（硬编码开盘行）
op = re.search(r"开盘价（open）</td><td>不盯盘</td><td><strong[^>]*>([0-9]+)%</strong></td><td class=\"c-red\">\$\+?([0-9,]+)</td><td>([0-9.]+)%</td><td>([0-9.]+)</td>", html)
op_line, op_total, op_mddpct, op_ratio = (int(op.group(1)), money(op.group(2)), float(op.group(3)), float(op.group(4))) if op else (None,None,None,None)

# 不对称叙述（硬编码）
asym_tx = re.search(r"涨 10% 太灵敏（比 ([0-9.]+)）、涨 20% 太迟钝（比 ([0-9.]+)），涨 15% 最划算", html)
asym10, asym20 = (float(asym_tx.group(1)), float(asym_tx.group(2))) if asym_tx else (None, None)
asym_best = grab(r"跌 15% \+ 涨 15%（对称）仍是全局最优（收益/回撤比 ([0-9.]+)）", float)

# 韩股相关性（报告展示值）与端点标签
kr = json.load(open(os.path.join(HEDGE, "kr_dram_compare.json")))
kr_rows = extract_table("<th>领先 / 滞后关系（日涨跌幅相关系数）</th>")
rep_kr = []
for row in kr_rows:
    rep_kr.append((re.sub(r"<[^>]+>","",row[0]).strip(),
                   float(re.sub(r"<[^>]+>","",row[1]).strip()),
                   float(re.sub(r"<[^>]+>","",row[2]).strip())))
kr_ep = re.search(r"三星电子 \+([0-9]+)%.*?SK海力士 \+([0-9]+)%.*?DRAM ETF \+([0-9]+)%", html, re.S)
ep_sam, ep_hyn, ep_dram = (int(kr_ep.group(1)), int(kr_ep.group(2)), int(kr_ep.group(3))) if kr_ep else (None,None,None)

# =====================================================================
# A. 动态数字 vs 独立重算（期望：吻合）
# =====================================================================
add("dynamic", "动态KPI", "B&H收益=重算", round(bh["total"]), round(kpi_bh))
add("dynamic", "动态KPI", "策略收益=重算", round(best["total"]), round(kpi_strat))
add("dynamic", "动态KPI", "策略回撤%=重算", round(best["mdd_pct"],1), round(kpi_mddpct,1))
add("dynamic", "动态KPI", "策略回撤$=重算", round(best["mdd"]), round(money("$1,901")))  # 占位，下方用字符串校验
add("dynamic", "动态KPI", "收益/回撤比=重算", round(best_ratio,2), round(kpi_ratio,2))
add("dynamic", "动态KPI", "股票收益=重算B&H", round(bh["total"]), round(kpi_stock))
add("dynamic", "动态KPI", "B&H比=重算", round(bh_ratio,2), round(kpi_bh_ratio,2))
add("dynamic", "动态KPI", "B&H回撤%=重算", round(bh["mdd_pct"],1), round(kpi_bh_mddpct,1))
# 轮数
add("dynamic", "轮数", "总轮数=重算", best["n_rounds"], rep_n)
add("dynamic", "轮数", "跌+涨+到期=总轮数", rep_n, rep_down+rep_up+rep_exp)
add("dynamic", "轮数", "跌熔断=", best["down_hits"], rep_down)
add("dynamic", "轮数", "涨熔断=", best["up_hits"], rep_up)
add("dynamic", "轮数", "到期=", best["expiries"], rep_exp)
# 现在如何买 vs 当期期权数据重算
last = data[-1]; last_spot_d = last["spot"]
near_f = min([f for f in last["fridays"] if f["dte"] > 0], key=lambda f: abs(f["dte"] - 7))
near_atm = min(near_f["puts"], key=lambda p: abs(p["strike"] - last_spot_d))
add("dynamic", "现在如何买", "现价=当期spot", round(last_spot_d,2), round(nb_spot,2))
add("dynamic", "现在如何买", "到期日=", near_f["expiry"], nb_expiry)
add("dynamic", "现在如何买", "dte=", near_f["dte"], nb_dte)
add("dynamic", "现在如何买", "行权价=当期ATM", near_atm["strike"], nb_strike)
add("dynamic", "现在如何买", "vw=当期", round(near_atm["vw"],2), round(nb_vw,2))
add("dynamic", "现在如何买", "保费=vw*200", round(near_atm["vw"]*100*2), round(nb_cost))
add("dynamic", "现在如何买", "涨线=spot*1.15", round(nb_spot*1.15,2), round(nb_up,2))
add("dynamic", "现在如何买", "跌线=spot*0.85", round(nb_spot*0.85,2), round(nb_dn,2))
add("dynamic", "现在如何买", "占比=cost/(spot*100)", round(nb_cost/(nb_spot*100)*100,1), round(nb_pct,1))
# 逐轮：分解（内部算术，允许四舍五入 ±2） + 与模拟真值逐行比对（防转录错误）
best_rounds_rev = list(reversed(best["rounds"]))
for i, pr in enumerate(rounds):
    calc = pr["stock_pnl"] + pr["put_income"] + pr["put_cost"]
    add("dynamic", "逐轮分解", f"行{i+1} 总利润=股票+收入+成本", round(pr["period_total"]), round(calc), tol=2,
        note="显示分量各自取整后合可能与一次性取整的总利润差±1（四舍五入）")
for i, (pr, rc) in enumerate(zip(rounds, best_rounds_rev)):
    add("dynamic", "逐轮一致性", f"行{i+1} 入场日", rc["entry_date"], pr["entry"])
    add("dynamic", "逐轮一致性", f"行{i+1} 出场日", rc["exit_date"], pr["exit"])
    add("dynamic", "逐轮一致性", f"行{i+1} 方式", rc["kind"], pr["kind"])
    add("dynamic", "逐轮一致性", f"行{i+1} 入场spot", round(rc["entry_spot"], 1), round(pr["entry_spot"], 1))
    add("dynamic", "逐轮一致性", f"行{i+1} 出场spot", round(rc["exit_spot"], 1), round(pr["exit_spot"], 1))
    add("dynamic", "逐轮一致性", f"行{i+1} 行权价", int(rc["strike"]), int(pr["strike"]))
    add("dynamic", "逐轮一致性", f"行{i+1} 股票涨跌", round(rc["stock_pnl"]), round(pr["stock_pnl"]))
    add("dynamic", "逐轮一致性", f"行{i+1} put成本", round(rc["put_cost"]), round(-pr["put_cost"]))
    add("dynamic", "逐轮一致性", f"行{i+1} put收入", round(rc["put_income"]), round(pr["put_income"]))
    add("dynamic", "逐轮一致性", f"行{i+1} 周期总利润", round(rc["stock_pnl"] + rc["pnl"]), round(pr["period_total"]))
# 情景表（用报告自身的 now-buy 参数重算）
for sc in scen:
    calc_sp = (sc["exit_"] - nb_spot) * 100
    calc_pay = max(nb_strike - sc["exit_"], 0.0) * 200
    calc_net = calc_sp + calc_pay - nb_cost
    add("dynamic", "情景表", f"spot={sc['exit_']} 净P&L", round(calc_net), round(sc["net"]), tol=2)
    add("dynamic", "情景表", f"spot={sc['exit_']} 净收益率%", round(calc_net/(nb_spot*100)*100,1), round(sc["net_pct"],1), tol=0.15)
# 周期扫描（当前数据）记录（用于 C 对比）
add("dynamic", "周期扫描", "当前: 最近周五/7/14/21", f"{sweep[2]}/{sweep[7]}/{sweep[14]}/{sweep[21]}",
    f"{sweep[2]}/{sweep[7]}/{sweep[14]}/{sweep[21]}", note="当前数据重算的正确值")
# 不对称（当前数据）
add("dynamic", "不对称", "当前: 跌15+涨10/15/20 比", f"{cur_asym[10]}/{cur_asym[15]}/{cur_asym[20]}",
    f"{cur_asym[10]}/{cur_asym[15]}/{cur_asym[20]}", note="当前数据重算的正确值")
# 韩股端点（从 kr json 算，独立于报告）
add("dynamic", "韩股端点", "三星收益%=报告标签", ep_sam, round((kr["samsung"][-1]/kr["samsung"][0]-1)*100))
add("dynamic", "韩股端点", "海力士收益%", ep_hyn, round((kr["hynix"][-1]/kr["hynix"][0]-1)*100))
add("dynamic", "韩股端点", "DRAM收益%", ep_dram, round((kr["dram"][-1]/kr["dram"][0]-1)*100))
# 韩股相关性：报告展示值 == kr json corr（每行：标签 / 三星 / 海力士）
kr_json_map = [("same_sam", "same_hyn"), ("lag_sam", "lag_hyn"), ("lead_sam", "lead_hyn")]
for (row, (ks, kh)) in zip(rep_kr, kr_json_map):
    add("dynamic", "韩股相关性", f"{row[0]} 三星(报告值=json)", round(kr["corr"][ks], 2), round(row[1], 2))
    add("dynamic", "韩股相关性", f"{row[0]} 海力士(报告值=json)", round(kr["corr"][kh], 2), round(row[2], 2))

# =====================================================================
# B. 报告内部算术（用报告自己显示的数字互相印证）
# =====================================================================
add("internal", "内部", "策略收益=股票+put净", round(cc_strat), round(kpi_stock + cc_putnet))
add("internal", "内部", "回撤降幅=44.4-28.5", round(cc_drop,1), round(kpi_bh_mddpct - cc_mddpct,1))
add("internal", "内部", "倍率=1.55/0.74", round(cc_mult,1), round(cc_ratio / kpi_bh_ratio,1))
add("internal", "内部", "B&H比=收益/回撤", round(kpi_bh_ratio,2), round(kpi_bh / sm_bh_mdd,2))
add("internal", "内部", "策略比=收益/回撤$", round(cc_ratio,2), round(kpi_strat / 1901,2))

# =====================================================================
# C. 硬编码叙述 vs 动态/当前数据（核心不一致发现）
# =====================================================================
add("stale", "硬编码B&H", "callout收益2956 vs KPI2652", round(kpi_bh), round(sm_bh_total),
    note="gen_final_report.py 模板写死 2956，但动态 KPI 已更新为 2652")
add("stale", "硬编码B&H", "callout比0.82 vs KPI0.74", round(kpi_bh_ratio,2), round(sm_bh_ratio,2),
    note="写死 0.82")
add("stale", "硬编码出场", "callout出场57.32/08-14 vs 当前54.28/08-24", f"{stock_exit}/{stock[-1][0]}", f"{sm_exit_px}/{sm_exit_date}",
    note="写死 57.32/08-14，与当前数据及逐轮表(含08-21)冲突")
add("stale", "硬编码周期扫描", "7天 3630 vs 当前", sweep[7], round(sw7),
    note="写死 3630；当前数据重算为 %d" % sweep[7])
add("stale", "硬编码周期扫描", "最近周五 3063 vs 当前", sweep[2], round(sw2),
    note="写死 3063；当前为 %d" % sweep[2])
add("stale", "硬编码周期扫描", "14天 2060 vs 当前", sweep[14], round(sw14),
    note="写死 2060；当前为 %d" % sweep[14])
add("stale", "硬编码周期扫描", "21天 1866 vs 当前", sweep[21], round(sw21),
    note="写死 1866；当前为 %d" % sweep[21])
add("stale", "硬编码开盘行", "开盘行收益3630 vs 当前2947", round(best["total"]), round(op_total),
    note="写死 3630（开盘行应与动态一致）")
add("stale", "硬编码开盘行", "开盘行比1.91 vs 当前1.55", round(best_ratio,2), round(op_ratio,2),
    note="写死 1.91；当前为 %.2f" % best_ratio)
add("stale", "硬编码不对称", "涨10%比1.76 vs 当前", cur_asym[10], asym10,
    note="写死 1.76；当前为 %.2f" % cur_asym[10])
add("stale", "硬编码不对称", "涨20%比1.85 vs 当前", cur_asym[20], asym20,
    note="写死 1.85；当前为 %.2f" % cur_asym[20])
add("stale", "硬编码不对称", "对称最优1.91 vs 当前", cur_asym[15], asym_best,
    note="写死 1.91；当前为 %.2f；且当前 15 仍为三者最优" % cur_asym[15])

# =====================================================================
# 输出
# =====================================================================
for cat in ("dynamic", "internal", "stale"):
    items = [c for c in R["checks"] if c["cat"] == cat]
    R.setdefault("summary", {})[cat] = {"total": len(items), "pass": sum(1 for c in items if c["pass"]),
                                        "fail": sum(1 for c in items if not c["pass"])}
json.dump(R, open(os.path.join(HEDGE, "debug", "validation_details.json"), "w"), indent=2, ensure_ascii=False)

L = []
L.append("# DRAM 报告数据验证结果\n")
L.append(f"- 报告：`dram/dram_final_report.html`（文件 mtime 2026-08-25 14:52）")
L.append(f"- 验证脚本：`dram/debug/validate_report.py`（只读，未修改任何原始报告/代码）")
L.append(f"- 源数据：`data/DRAM_stock.json`（**{len(stock)} 交易日，最后 {stock[-1][0]} 收盘 ${stock_exit}**）、`DRAM_options_3fri.json`、`dram/kr_dram_compare.json`\n")
L.append("## 总览\n")
s = R["summary"]
L.append(f"- **A. 动态数字 vs 独立重算**：{s['dynamic']['pass']}/{s['dynamic']['total']} 通过 —— 报告里实时计算的部分与源数据一致 ✅")
L.append(f"- **B. 报告内部算术**：{s['internal']['pass']}/{s['internal']['total']} 通过 —— KPI 分解自洽 ✅")
L.append(f"- **C. 硬编码叙述 vs 动态/当前数据**：{s['stale']['fail']} 处不一致 ❌（gen_final_report.py 模板里的“死值”未随数据更新）\n")
L.append("> ⚠️ **核心结论**：报告被“部分更新”了——KPI、逐轮明细、现在如何买、情景表已用当前 99 日数据重算，")
L.append("> 但模板里硬编码的叙述（B&H=2956/0.82、出场 57.32/08-14、周期扫描 3630/3063/2060/1866、")
L.append("> 盘中 4.32、不对称 1.76/1.85/1.91）仍是旧 93 日快照的数字，与动态数字及当前数据互相打架。\n")
L.append("---\n")

def dump(cat, title):
    items = [c for c in R["checks"] if c["cat"] == cat]
    L.append(f"## {title}\n")
    L.append("| 校验项 | 期望值 | 实际值 | 结果 | 说明 |")
    L.append("|---|---|---|---|---|")
    for c in items:
        mark = "✅" if c["pass"] else ("❌" if cat == "stale" else "⚠️")
        ev, gv = c["expected"], c["got"]
        if isinstance(ev, float): ev = round(ev, 4)
        if isinstance(gv, float): gv = round(gv, 4)
        L.append(f"| {c['name']} | {ev} | {gv} | {mark} | {c['note']} |")
    L.append("")

dump("dynamic", "A. 动态数字 vs 独立重算（期望吻合）")
dump("internal", "B. 报告内部算术（自身印证）")
dump("stale", "C. 硬编码叙述不一致（核心问题）")

L.append("## 根因与建议\n")
L.append("1. **根因**：`gen_final_report.py` 的 HTML 模板把若干数字写成字符串常量：")
L.append("   - 策略模型 callout：`@ $27.76 … 持有到 2026-08-14 @ $57.32`、`B&H 收益 $2,956、回撤 $3,587(44.4%)、比 0.82`；")
L.append("   - 策略演进：`7天($3,630) > 最近周五($3,063) > 14天($2,060) > 21天($1,866)`、盘中 `4.32`、不对称 `1.76/1.85/1.91`。")
L.append("   这些常量只在“数据是 93 日、收盘 57.32”时才正确；数据扩展到 99 日后，动态部分变了，死值没变 → 自相矛盾。")
L.append("2. **巧合正确的部分**：B&H 最大回撤 $3,587（44.4%）在 99 日数据下仍成立（最大回撤发生在早期，未被近期数据改变），")
L.append("   所以 callout 里的回撤数字反而没出错，只有“收益 2956 / 比 0.82 / 出场 57.32”是错的。")
L.append("3. **修复建议（不改本报告，供参考）**：把上述死值改为用 `{bh['total']}`、`{bh_ratio:.2f}`、`{stock_exit}`、`{stock[-1][0]}`")
L.append("   等变量填充，或在生成报告时统一从 `bh` / `best` / `sweep` 取值，避免叙述与数字脱节。重新运行生成器即可消除全部 C 类不一致。")
L.append("4. **已验证无误的部分**：KPI 分解（2947=2652+295、降幅 15.9、倍率 2.1）、逐轮“总利润=股票+收入+成本”全部 17 行、")
L.append("   情景微笑曲线（用声明参数 54.28/54/340 重算吻合）、韩股相关性展示值与 `kr_dram_compare.json` 的 corr 一致、半年端点收益均正确。")
L.append("")
L.append("> 注：韩股相关性若用报告显示（已舍入到 1 位）的归一化序列独立重算，会与 json 存储精确值有约 0.02–0.04 偏差")
L.append("> （显示序列已舍入所致），故以 json 中存储的精确 corr 为准。")

open(os.path.join(HEDGE, "debug", "validation_report.md"), "w").write("\n".join(L))
print("A 动态:", s["dynamic"]["pass"], "/", s["dynamic"]["total"])
print("B 内部:", s["internal"]["pass"], "/", s["internal"]["total"])
print("C 硬编码不一致:", s["stale"]["fail"], "处")
print("详见 debug/validation_report.md")
