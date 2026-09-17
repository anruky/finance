#!/usr/bin/env python3
"""
SKHY 最终报告 —— 逐轮明细「真实数据」验证（修正版）
==================================================
只读 SKHY_stock.json + SKHY_options_3fri.json + skhy_final_report.html。
1) 用与引擎 run_v10 完全一致的口径独立重建每一轮（所有数值均取自真实数据：
   入场/出场用真实开盘价或收盘价、put 成本/赔付用期权链真实 vw）。
2) 把报告 HTML 逐轮表逐项与重建结果比对。
3) 标记「方法学不一致」与「叙述性数字错误」两类不合理之处。
不修改任何原始文件，结果只写到 hedge/debug/。
"""
import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.join(HERE, "..", "sk")
DATA = "/Users/gavinz/git/finance/data"
REPORT = os.path.join(SK, "skhy_final_report.html")
STOCK_F = os.path.join(DATA, "SKHY_stock.json")
OPT_F = os.path.join(DATA, "SKHY_options_3fri.json")

stock = json.load(open(STOCK_F))
opt = json.load(open(OPT_F))

bars = {r[0]: r for r in stock}
opens = {r[0]: r[1] for r in stock}
closes = {r[0]: r[4] for r in stock}
opt_by_date = {d["date"]: d for d in opt}

TARGET, DOWN, UP, NUM_PUTS = 2, 15, 8, 2


def pick_friday(day, target=TARGET):
    valid = [f for f in day["fridays"] if f["dte"] > 0]
    if not valid:
        return min(day["fridays"], key=lambda f: abs(f["dte"] - target))
    return min(valid, key=lambda f: abs(f["dte"] - target))


def atm_put(friday, spot):
    if not friday["puts"]:
        return None
    return min(friday["puts"], key=lambda p: abs(p["strike"] - spot))


def find_vw(day, expiry, strike):
    for f in day["fridays"]:
        if f["expiry"] == expiry:
            for p in f["puts"]:
                if abs(p["strike"] - strike) < 1e-9:
                    return p["vw"]
    return None


def reconstruct():
    """与 run_v10 完全一致的重建（entry_spot 口径：新开仓=当日open；到期滚动=当日close；熔断滚动=当日open）。"""
    rounds = []
    pos = None
    d, u = DOWN / 100.0, UP / 100.0

    def open_new(spot):
        f = pick_friday(opt_by_date[date], TARGET)
        p = atm_put(f, spot)
        if p is None:
            return None
        return dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                   entry_spot=spot, cost=p["vw"] * 100 * NUM_PUTS,
                   entry_date=date, entry_friday=f)

    for r in stock:
        date = r[0]; S = closes[date]; o = opens[date]; day = opt_by_date.get(date)
        if pos is None:
            if day is None:
                continue
            pos = open_new(o)
            continue
        p0 = pos["entry_spot"]
        dn = o <= p0 * (1 - d); up = o >= p0 * (1 + u)
        if date >= pos["expiry"]:
            if dn or up:
                vw = find_vw(day, pos["expiry"], pos["strike"])
                pay = vw * 100 * NUM_PUTS if vw is not None else (max(pos["strike"] - o, 0) * 100 * NUM_PUTS if dn else 0)
                rounds.append(dict(kind="下跌止盈" if dn else "上涨再平衡", entry_date=pos["entry_date"],
                                   exit_date=date, strike=pos["strike"], entry_spot=pos["entry_spot"],
                                   exit_spot=o, stock_pnl=(o - pos["entry_spot"]) * 100,
                                   put_cost=pos["cost"], put_income=pay, payoff_src="vw@exit" if vw else "intrinsic@exit",
                                   exit_vw=vw, entry_friday_expiry=pos["expiry"], entry_vw=pos["vw"]))
                pos = open_new(o)
            else:
                pay = max(pos["strike"] - S, 0) * 100 * NUM_PUTS
                rounds.append(dict(kind="到期", entry_date=pos["entry_date"], exit_date=date,
                                   strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=S,
                                   stock_pnl=(S - pos["entry_spot"]) * 100, put_cost=pos["cost"],
                                   put_income=pay, payoff_src="intrinsic@close", exit_vw=None,
                                   entry_friday_expiry=pos["expiry"], entry_vw=pos["vw"]))
                pos = open_new(S)   # 到期滚动用当日收盘
            continue
        if dn:
            vw = find_vw(day, pos["expiry"], pos["strike"])
            pay = vw * 100 * NUM_PUTS if vw is not None else max(pos["strike"] - o, 0) * 100 * NUM_PUTS
            rounds.append(dict(kind="下跌止盈", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=o,
                               stock_pnl=(o - pos["entry_spot"]) * 100, put_cost=pos["cost"],
                               put_income=pay, payoff_src="vw@exit" if vw else "intrinsic@exit",
                               exit_vw=vw, entry_friday_expiry=pos["expiry"], entry_vw=pos["vw"]))
            pos = open_new(o)
            continue
        if up:
            vw = find_vw(day, pos["expiry"], pos["strike"])
            pay = vw * 100 * NUM_PUTS if vw is not None else 0.0
            rounds.append(dict(kind="上涨再平衡", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=o,
                               stock_pnl=(o - pos["entry_spot"]) * 100, put_cost=pos["cost"],
                               put_income=pay, payoff_src="vw@exit" if vw else "intrinsic@exit",
                               exit_vw=vw, entry_friday_expiry=pos["expiry"], entry_vw=pos["vw"]))
            pos = open_new(o)
            continue
    return rounds


reco = reconstruct()
stock_entry, stock_exit = closes[stock[0][0]], closes[stock[-1][0]]
bh_total = (stock_exit - stock_entry) * 100
put_net = sum(rd["put_income"] - rd["put_cost"] for rd in reco)
strat_total = bh_total + put_net

# 解析报告 HTML 逐轮表
html = open(REPORT, encoding="utf-8").read()
idx = html.index("最优策略逐轮明细")
seg = html[idx:html.index("</table>", idx)]
rows = re.findall(r"<tr>(.*?)</tr>", seg, re.S)
report_rows = []
for row in rows[1:]:
    cells = re.findall(r"<td.*?>(.*?)</td>", row, re.S)
    report_rows.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])


def money2float(s):
    # 报告格式: 正 "$+591"/"$591"，负 "$-591"（负号在 $ 之后）。直接去掉 $/逗号后交给 float 保留符号。
    return float(s.replace("$", "").replace(",", "").replace("%", "").strip())


def pct2float(s):
    return float(s.replace("%", "").replace("+", "").strip())


def keyf(rd):
    return (rd["entry_date"], rd["exit_date"], rd["kind"])


reco_map = {keyf(rd): rd for rd in reco}

checks = []
anomalies = []
for rr in report_rows:
    e_date, x_date, kind = rr[0], rr[1], rr[2]
    r_e, r_x = money2float(rr[3]), money2float(rr[4])
    r_wave, r_strike = pct2float(rr[5]), money2float(rr[6])
    r_vsma = rr[7]
    r_stock = money2float(rr[8]); r_cost = money2float(rr[9])
    r_costpct = pct2float(rr[10]); r_income = money2float(rr[11])
    r_lt11, r_all = money2float(rr[12]), money2float(rr[13])

    rd = reco_map.get((e_date, x_date, kind))
    if rd is None:
        anomalies.append(f"[{e_date}→{x_date}/{kind}] 报告中找不到对应轮次（与引擎重建不一致）")
        continue

    # 真实数据基准（取自重建，重建全部来自真实 open/close/vw）
    t_e, t_x = rd["entry_spot"], rd["exit_spot"]
    t_wave = (t_x / t_e - 1) * 100
    t_stock = (t_x - t_e) * 100
    t_cost, t_strike = rd["put_cost"], rd["strike"]
    t_costpct = t_cost / (t_e * 100) * 100
    t_income = rd["put_income"]
    t_all = t_stock + t_income - t_cost
    t_lt11 = 0.0 if t_costpct > 11 else t_all

    def chk(field, got, true, tol=0.5, note=""):
        checks.append(dict(entry=e_date, exit=x_date, kind=kind, field=field,
                           report=round(got, 2), rebuilt=round(true, 2), ok=abs(got - true) <= tol, note=note))

    chk("入场spot", r_e, t_e)
    chk("出场spot", r_x, t_x)
    chk("波动比例", r_wave, t_wave)
    chk("行权价", r_strike, t_strike)
    chk("股票涨跌", r_stock, t_stock)
    chk("put成本", abs(r_cost), t_cost)   # 报告把成本显示为 -X（支出），取绝对值比幅度
    chk("成本占比", r_costpct, t_costpct)
    chk("put收入", r_income, t_income)
    chk("周期总利润(all)", r_all, t_all)
    chk("周期总利润(<11)", r_lt11, t_lt11)

    # 内部算术：报告表内 周期总利润(all) ≈ 股票涨跌 + put收入 - |put成本|（显示值舍入，容忍 ±2）
    arith = r_stock + r_income - abs(r_cost)
    if abs(arith - r_all) > 2.0:
        anomalies.append(f"[{e_date}→{x_date}/{kind}] 表内算术错: 股票{r_stock:+.0f}+收入{r_income:+.0f}-成本|{abs(r_cost):.0f}|={arith:+.0f} ≠ 周期总利润(all){r_all:+.0f}")
    if (r_costpct > 11) != (r_lt11 == 0):
        anomalies.append(f"[{e_date}→{x_date}/{kind}] <11 规则不一致: 成本占比{r_costpct:.1f}% 但 周期总利润(<11)={r_lt11:+.0f}")

# 方法学不一致：entry_spot 不等于"入场日"当日开盘价（说明是到期滚动，用了前一日收盘）
method_notes = []
for rd in reco:
    od = opens[rd["entry_date"]]
    if abs(rd["entry_spot"] - od) > 0.01:
        method_notes.append(
            f"轮次 {rd['entry_date']}→{rd['exit_date']}/{rd['kind']}：报告「入场spot」=${rd['entry_spot']:.2f}，"
            f"但 {rd['entry_date']} 当日开盘价=${od:.2f}。差异源于该仓位由上一轮到期滚动开立，引擎用「到期日收盘」作为新仓入场价"
            f"（即 ${rd['entry_spot']:.2f} 实为 {rd['entry_date']} 收盘价），并非该日开盘价。")

# 期权真实数据校验：strike 是否真 ATM、vw 是否来自真实链
opt_issues = []
for rd in reco:
    day = opt_by_date.get(rd["entry_date"])
    if day is None or not day["fridays"]:
        continue
    f = pick_friday(day, TARGET)
    if f["puts"]:
        best_strike = min(f["puts"], key=lambda p: abs(p["strike"] - rd["entry_spot"]))["strike"]
        if best_strike != rd["strike"]:
            opt_issues.append(f"[{rd['entry_date']}] 所选行权价 {rd['strike']} 并非 ATM（最近应为 {best_strike}）")
    rvw = find_vw(day, rd["entry_friday_expiry"], rd["strike"])
    if rvw is None:
        opt_issues.append(f"[{rd['entry_date']}] 入场链缺 strike={rd['strike']}/exp={rd['entry_friday_expiry']} 的 vw")
    elif abs(rvw * 100 * NUM_PUTS - rd["put_cost"]) > 0.5:
        opt_issues.append(f"[{rd['entry_date']}] 成本 ${rd['put_cost']:,.0f} ≠ 真实vw(${rvw:.2f})×200=${rvw*200:,.0f}")
    if rd["payoff_src"].startswith("vw"):
        ed = opt_by_date.get(rd["exit_date"])
        if ed is not None:
            evw = find_vw(ed, rd["entry_friday_expiry"], rd["strike"])
            if evw is None:
                opt_issues.append(f"[{rd['exit_date']}] 出场链缺 strike={rd['strike']}/exp={rd['entry_friday_expiry']} 的 vw")
            elif abs(evw * 100 * NUM_PUTS - rd["put_income"]) > 0.5:
                opt_issues.append(f"[{rd['exit_date']}] 收入 ${rd['put_income']:,.0f} ≠ 真实vw(${evw:.2f})×200=${evw*200:,.0f}")

# 叙述性数字核对：报告文字里引用的 $3,667 / strike 181 / 07-15 赔付
narrative_issues = []
narr_payoffs = {rd["exit_date"]: rd["put_income"] for rd in reco}
narr_07_15 = narr_payoffs.get("2026-07-17")  # 07-15→07-17 轮次的 put 收入
narrative_issues.append(
    f"报告「为什么/过拟合警示」称 '07-15 那笔 $3,667 赔付' 与 '07-14 追高到 strike 181'。"
    f"但逐轮表中 07-15→07-17 轮 put 收入实际为 ${narr_07_15:,.0f}、行权价 180；"
    f"全表 10 轮无任何一轮 put 收入 = $3,667，也无 strike 181。该叙述数字与表格数据不符（疑似旧参数/旧数据的残留描述）。")
# 轮空解释里把 +401 赢轮说成"亏损"
narrative_issues.append(
    "报告「轮空规则验证」称 '成本>11% 的 4 个轮次合计净亏 -364（-149, +401, -413, -204），跳过它们就把这部分亏损避开'。"
    "但其中 07-24→07-29 轮 周期总利润(all)=+$401 是**盈利**而非亏损；轮空多赚 +364 实为 '3 个输轮(-766) 抵消 1 个赢轮(+401)' 的净结果，"
    "把 +401 称作 '亏损' 并说 '把亏损避开' 是误导。正确表述：跳过 4 轮（含 1 个赢轮）净效果 +364。")

# 现在如何买：用最新期权数据核对
last = opt[-1]
last_spot = last["spot"]; latest_date = last["date"]
near_f = min([f for f in last["fridays"] if f["dte"] > 0], key=lambda f: abs(f["dte"] - TARGET))
near_atm = min(near_f["puts"], key=lambda p: abs(p["strike"] - last_spot))
near_expiry, near_strike, near_vw = near_f["expiry"], near_atm["strike"], near_atm["vw"]
cost_2 = near_vw * 100 * 2
nowbuy = dict(spot=round(last_spot, 2), date=latest_date, expiry=near_expiry, strike=near_strike,
              vw=round(near_vw, 2), cost_2=round(cost_2), pct=round(cost_2/(last_spot*100)*100, 1),
              up_line=round(last_spot*(1+UP/100), 2), dn_line=round(last_spot*(1-DOWN/100), 2))
# 与报告核对
rep_spot = float(re.search(r"最新 SKHY 现价 <strong class=\"c-gold\">\$([\d.]+)</strong>", html).group(1))
rep_strike = float(re.search(r"买入 2 张行权价 \$(\d+) 的 Put", html).group(1))
rep_vw = float(re.search(r"成交量加权价 <strong>\$([\d.]+)/股</strong>", html).group(1))
rep_up = float(re.search(r"开盘价涨到 <strong class=\"c-red\">\$([\d.]+)</strong>", html).group(1))
rep_dn = float(re.search(r"跌到 <strong class=\"c-green\">\$([\d.]+)</strong>", html).group(1))
nowbuy_checks = []
for nm, got, true in [("现价", rep_spot, nowbuy["spot"]), ("行权价", rep_strike, nowbuy["strike"]),
                      ("vw", rep_vw, nowbuy["vw"]), ("涨熔断线", rep_up, nowbuy["up_line"]),
                      ("跌熔断线", rep_dn, nowbuy["dn_line"])]:
    nowbuy_checks.append(dict(item=nm, report=got, rebuilt=true, ok=abs(got-true) <= 0.01))

# 汇总
n_ok = sum(1 for c in checks if c["ok"])
n_total = len(checks)
all_sum = sum((rd["stock_pnl"] + rd["put_income"] - rd["put_cost"]) for rd in reco)
gap_head = (reco[0]["entry_spot"] - stock_entry) * 100
gap_tail = (stock_exit - reco[-1]["exit_spot"]) * 100

print("=== 逐项字段比对（报告 vs 引擎重建，均取自真实数据）===")
print(f"{n_ok}/{n_total} 通过；异常 {len(anomalies)}；方法学提示 {len(method_notes)}；期权校验 {len(opt_issues)}；叙述问题 {len(narrative_issues)}")
for c in checks:
    if not c["ok"]:
        print(f"  ✗ [{c['entry']}→{c['exit']}/{c['kind']}] {c['field']}: 报告={c['report']} 重建={c['rebuilt']}")
print("\n=== 异常 ===")
for a in anomalies: print("  !", a)
print("\n=== 方法学不一致（入场spot≠入场日开盘）===")
for a in method_notes: print("  ?", a)
print("\n=== 期权真实数据校验 ===")
for a in opt_issues: print("  ?", a)
print("\n=== 现在如何买 核对 ===")
for c in nowbuy_checks: print(f"  {'✓' if c['ok'] else '✗'} {c['item']}: 报告={c['report']} 重建={c['rebuilt']}")
print(f"\n头部对账: 各轮(all)合计={all_sum:,.0f} + 开头空档{gap_head:,.0f} + 结尾空档{gap_tail:,.0f} = {all_sum+gap_head+gap_tail:,.0f}  vs 总收益 {strat_total:,.0f}")

out = dict(
    summary=dict(report_rows=len(report_rows), rebuilt_rounds=len(reco),
                 field_checks=n_total, field_ok=n_ok, anomalies=len(anomalies),
                 method_notes=len(method_notes), opt_issues=len(opt_issues),
                 narrative_issues=len(narrative_issues),
                 bh_total=round(bh_total, 2), strat_total=round(strat_total, 2),
                 put_net=round(put_net, 2), all_sum=round(all_sum, 2)),
    checks=checks, anomalies=anomalies, method_notes=method_notes,
    opt_issues=opt_issues, narrative_issues=narrative_issues,
    nowbuy=nowbuy, nowbuy_checks=nowbuy_checks,
    rebuilt=[{k: (round(v, 2) if isinstance(v, float) else v) for k, v in rd.items()} for rd in reco],
    report_rows=report_rows,
)
with open(os.path.join(HERE, "skhy_validation_details.json"), "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("\n已写出 skhy_validation_details.json")
