#!/usr/bin/env python3
"""
AI/半导体事件研究表生成器
=========================
基于 AI_semiconductor_history.md 的 29 条事件，产出「事件 × 股价反应」研究表：
  1) 严格按时间排序（单一连续时间线，不分月）
  2) 每条打标签：突发 / 预期
  3) 事件发生时间点的股价（事件日收盘价）
  4) 事件后 1 个交易日、3 个交易日的股价（含相对事件日的涨跌幅）
输出：market/AI_semiconductor_event_study.md
"""
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DATA = "/Users/gavinz/git/finance/data/event_prices.json"
OUT = "/Users/gavinz/git/finance/market/AI_semiconductor_event_study.md"

# (date, id, 标签, 级别, 主观察标的, 事件标题, 关键事实, 来源URL)
EVENTS = [
    ("2026-06-17", "20260617-FED", "预期", "P0", "QQQ", "FOMC 维持 3.50%–3.75%", "12:0 通过，强调通胀仍高于目标", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm"),
    ("2026-06-23", "20260623-MU-MARKET", "突发", "P1", "MU", "美光财报前单日 -13.2%", "Axios 次日报道，事件日 06-23、报道日 06-24", "https://www.axios.com/2026/06/24/micron-earnings-expectations-have-gone-vertical"),
    ("2026-06-24", "20260624-MU", "预期", "P0", "MU", "Micron FY26Q3 财报", "营收 $41.46B，经营现金流 $25.39B", "https://investors.micron.com/node/50671/pdf"),
    ("2026-07-09", "20260709-DRAM-LTA", "预期", "P0", "MU", "Q3 Server DRAM 合约价 +13–18%", "TrendForce；区分长协与非长协客户", "https://www.trendforce.com/presscenter/news/20260709-13140.html"),
    ("2026-07-13", "20260713-TSM-JUN", "预期", "P1", "TSM", "台积电 6 月营收 +67.9%", "NT$442,680 百万；原定 07-10 台风延至 07-13", "https://investor.tsmc.com/english/monthly-revenue/2026"),
    ("2026-07-15", "20260715-ASML", "预期", "P0", "ASML", "ASML Q2 财报", "净销售 €9.326B，全年指引 €43–45B", "https://www.asml.com/en/news/press-releases/2026/q2-2026-financial-results"),
    ("2026-07-16", "20260716-TSM-Q2", "预期", "P0", "TSM", "台积电 Q2 财报", "美元收入 $40.20B +33.7%，毛利率 67.7%", "https://investor.tsmc.com/english/encrypt/files/encrypt_file/qr/phase4_reports/2026-07/887682617ea280c69ee0bbec7665804756464837/2Q26%20EarningsRelease_WoG.pdf"),
    ("2026-07-22", "20260722-GOOGL", "预期", "P0", "GOOGL", "Alphabet Q2 财报", "总收入 $119.8B +24%，GCP $24.8B +82%", "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm"),
    ("2026-07-23", "20260723-AMD-HELIOS", "预期", "P0", "AMD", "AMD 发布 Helios 机柜系统", "Advancing AI，进入生产", "https://ir.amd.com/news-events/press-releases/detail/1294/aai-2026-amd-delivers-full-stack-compute-for-the-agentic-ai-era"),
    ("2026-07-24", "20260724-CLAUDE-OPUS5", "预期", "P1", "AMZN", "Claude Opus 5 发布", "定位长时 Agent、编码、专业工作", "https://www.anthropic.com/news/claude-opus-5"),
    ("2026-07-29", "20260729-SKHYNIX", "预期", "P0", "SKHY", "SK hynix Q2 财报", "营收 KRW79.32 万亿，营业利润 KRW60.54 万亿", "https://news.skhynix.com/en/q2-2026-business-results/"),
    ("2026-07-29", "20260729-MSFT", "预期", "P0", "MSFT", "Microsoft FY26Q4 财报", "收入 $90.0B +18%，营业利润 $40.6B", "https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast"),
    ("2026-07-29", "20260729-META", "预期", "P0", "META", "Meta 2026 Capex 指引上修", "$125–145B → $130–145B", "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Second-Quarter-2026-Results/default.aspx"),
    ("2026-07-29", "20260729-FED", "预期", "P0", "QQQ", "FOMC 维持 3.50%–3.75%", "9:3 通过，分歧扩大", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm"),
    ("2026-07-30", "20260730-SAMSUNG", "预期", "P0", None, "Samsung Q2 财报", "集团营收 KRW171.5 万亿，DS 环比 +56%", "https://news.samsung.com/global/samsung-electronics-announces-second-quarter-2026-results"),
    ("2026-07-30", "20260730-AMZN", "预期", "P0", "AMZN", "Amazon Q2 财报", "AWS 营业利润 $16.6B", "https://www.aboutamazon.com/news/company-news/amazon-earnings-q2-2026-report"),
    ("2026-08-04", "20260804-AMD-Q2", "预期", "P0", "AMD", "AMD Q2 财报", "收入 $11.536B +50%，DC $6.7B +107%", "https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results"),
    ("2026-08-10", "20260810-TSM-JUL", "预期", "P1", "TSM", "台积电 7 月营收 +44.7%", "NT$467,580 百万", "https://investor.tsmc.com/english/monthly-revenue/2026"),
    ("2026-08-12", "20260812-TENCENT", "预期", "P0", "TCEHY", "腾讯 Q2 财报", "营销服务收入 人民币436 亿 +22%", "https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf"),
    ("2026-08-26", "20260826-NVDA", "预期", "P0", "NVDA", "NVIDIA FY27Q2 财报", "收入 $96.2B，DC $89.0B，Q3 指引 $108B", "https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027"),
    ("2026-08-31", "20260831-ANTHROPIC-SECURITY", "突发", "P1", "AMZN", "Anthropic 安全与对齐改进公告", "回应模型未授权系统访问事件", "https://www.anthropic.com/news/improving-alignment-security-efforts"),
    ("2026-09-01", "20260901-CLAUDE51", "预期", "P1", "AMZN", "Claude Fable/Mythos 5.1 发布", "强调编码、知识工作、科研", "https://www.anthropic.com/claude-fable-and-mythos-5-1"),
    ("2026-09-02", "20260902-AVGO", "预期", "P0", "AVGO", "Broadcom FY26Q3 财报", "总收入 $29.6B，AI 半导体 $16.7B +221%", "https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-third-quarter-fiscal-year-2026-financial"),
    ("2026-09-02", "20260902-DRAM-SPOT", "预期", "P0", "MU", "PC DRAM 合约上修 / 现货偏弱", "TrendForce 周报摘要", "https://www.trendforce.com/research/download/RP260902ZP"),
    ("2026-09-03", "20260903-GPT6", "预期", "P1", "MSFT", "GPT-6 Astra 发布", "重点复杂任务与自主执行", "https://openai.com/index/gpt-6-astra/"),
    ("2026-09-07", "20260907-DRAM-Q2", "预期", "P0", "MU", "Q2 DRAM 行业收入 +59.5%", "预测 Q3 传统 DRAM 合约 +13–18%", "https://www.trendforce.com/presscenter/news/20260907-13219.html"),
    ("2026-09-10", "20260910-TSM-AUG", "预期", "P0", "TSM", "台积电 8 月营收 +53.3%", "NT$514.81B，环比 +10.1%", "https://pr.cld.tsmc.com/english/news/3340"),
    ("2026-09-10", "20260910-US-PPI", "预期", "P0", "QQQ", "美国 8 月 PPI +0.4%", "同比 +5.4%，核心 +0.3%", "https://www.bls.gov/news.release/archives/ppi_09102026.htm"),
    ("2026-09-11", "20260911-US-CPI", "预期", "P0", "QQQ", "美国 8 月 CPI +0.4%", "同比 +3.4%，核心同比 2.4%", "https://www.bls.gov/news.release/archives/cpi_09112026.htm"),
]

prices = json.load(open(DATA))


def get_series(ticker):
    rows = prices.get(ticker, [])
    dates = [r[0] for r in rows]
    closes = {r[0]: r[4] for r in rows}
    return dates, closes


def reaction(ticker, event_date):
    """返回 (事件日收盘, T+1收盘, T+1涨跌%, T+3收盘, T+3涨跌%)，缺数据填 None。"""
    if ticker is None:
        return (None, None, None, None, None)
    dates, closes = get_series(ticker)
    if not dates:
        return (None, None, None, None, None)
    # 事件日交易日：>= event_date 的第一个交易日
    i0 = None
    for i, d in enumerate(dates):
        if d >= event_date:
            i0 = i
            break
    if i0 is None:
        i0 = len(dates) - 1  # 事件日晚于数据末尾，取最后一天兜底（不会发生）
    c0 = closes[dates[i0]]

    def get(idx):
        if 0 <= idx < len(dates):
            return closes[dates[idx]]
        return None

    c1 = get(i0 + 1)
    c3 = get(i0 + 3)
    r1 = (c1 / c0 - 1) * 100 if (c1 is not None and c0) else None
    r3 = (c3 / c0 - 1) * 100 if (c3 is not None and c0) else None
    return (c0, c1, r1, c3, r3)


def fmt_px(c):
    return "—" if c is None else f"${c:,.2f}"


def fmt_ret(r):
    if r is None:
        return "—"
    return f"{r:+.1f}%"


# 生成明细行
rows = []
for (date, eid, label, level, ticker, title, fact, src) in EVENTS:
    c0, c1, r1, c3, r3 = reaction(ticker, date)
    ticker_disp = ticker if ticker else "（无数据）"
    src_short = src.split("//")[-1].split("/")[0]
    rows.append(dict(date=date, id=eid, label=label, level=level, ticker=ticker_disp,
                     title=title, fact=fact, src=src, c0=c0, c1=c1, r1=r1, c3=c3, r3=r3))

# ---- 突发 vs 预期 平均反应 ----
def avg(vals):
    v = [x for x in vals if x is not None]
    return (sum(v) / len(v)) if v else None

tushu_r1 = avg([r["r1"] for r in rows if r["label"] == "突发"])
tushu_r3 = avg([r["r3"] for r in rows if r["label"] == "突发"])
yuqi_r1 = avg([r["r1"] for r in rows if r["label"] == "预期"])
yuqi_r3 = avg([r["r3"] for r in rows if r["label"] == "预期"])
n_tushu = sum(1 for r in rows if r["label"] == "突发")
n_yuqi = sum(1 for r in rows if r["label"] == "预期")

# ---- 组装 Markdown ----
def md_ret(r, c):
    if r is None:
        return "—"
    sign = "📈" if r > 0 else ("📉" if r < 0 else "➖")
    return f"{fmt_px(c)}（{fmt_ret(r)} {sign}）"

line = []
line.append("# AI／半导体事件研究表（事件 × 股价反应）\n")
line.append("> 生成：2026-09-14（美东 ET）｜基于 [AI_semiconductor_history.md](AI_semiconductor_history.md) 的 29 条事件回溯。")
line.append("> 本表聚焦「事件 → 股价反应」：每条事件记录**事件日收盘价**、**事件后 1 个交易日**、**事件后 3 个交易日**的收盘价及涨跌幅。\n")

line.append("## 一、标签口径\n")
line.append("- **预期事件**：市场事先知道“会在这一天发生”——财报、FOMC、PPI/CPI、台积电月营收（有固定日历）、产品发布会（提前预告）、TrendForce 定期研究。")
line.append("- **突发事件**：无预告、市场无预期——如财报前闪崩、突发的安全事故。\n")
line.append(f"本区间 29 条事件中：**预期 {n_yuqi} 条**、**突发 {n_tushu} 条**。绝大多数价格波动由「预期事件」（财报/宏观数据）驱动，突发冲击极少。\n")

line.append("## 二、突发 vs 预期 平均反应\n")
line.append("| 事件类型 | 数量 | T+1 平均涨跌 | T+3 平均涨跌 |")
line.append("| --- | --- | --- | --- |")
line.append(f"| 突发 | {n_tushu} | {fmt_ret(tushu_r1)} | {fmt_ret(tushu_r3)} |")
line.append(f"| 预期 | {n_yuqi} | {fmt_ret(yuqi_r1)} | {fmt_ret(yuqi_r3)} |")
line.append("\n> ⚠️ 突发仅 2 条，样本不足以得出统计结论；此对比仅供方向性参考。\n")

line.append("## 三、事件时间线（严格按时间排序）\n")
line.append("| 日期 | 标签 | 级别 | 主观察标的 | 事件与关键事实 | 事件日收盘 | T+1 收盘（涨跌） | T+3 收盘（涨跌） | 来源 |")
line.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |")

for r in rows:
    lbl = "⚡突发" if r["label"] == "突发" else "🗓️预期"
    fact = f"**{r['title']}** — {r['fact']}"
    c0s = fmt_px(r["c0"])
    t1s = md_ret(r["r1"], r["c1"])
    t3s = md_ret(r["r3"], r["c3"])
    src_link = f"[{r['src'].split('//')[-1].split('/')[0]}]({r['src']})"
    line.append(f"| {r['date']} | {lbl} | {r['level']} | {r['ticker']} | {fact} | {c0s} | {t1s} | {t3s} | {src_link} |")

line.append("\n## 四、数据口径与说明\n")
line.append("- **事件日收盘价** = 事件公告日当天（美股）收盘价；财报多为盘后发布，因此事件日收盘价是“发布前”的价格，**T+1 收盘才是首个完整反应日**。FOMC（14:00 ET 盘中）与台积电月营收（美股盘前）的事件日收盘已包含部分反应。")
line.append("- **T+1 / T+3** = 事件日之后第 1、第 3 个**交易日**（美股），涨跌幅以事件日收盘价为基准。")
line.append("- **股价口径**：Polygon 日线，**未复权**收盘价（区间内基本无分红除息影响）；腾讯用 ADR **TCEHY**（OTC），海力士用 ADR **SKHY**（07-13 上市，仅覆盖其后事件）。")
line.append("- **三星（07-30 财报）**：韩国上市（KRX: 005930），当前数据源无覆盖，股价留空待补。")
line.append("- **主观察标的映射**：公司财报/月营收/产品发布 → 本公司股票；存储行业（TrendForce DRAM）→ 美光 MU；宏观（FOMC/PPI/CPI）→ QQQ；模型发布 → 主投资方（Claude→AMZN，GPT-6→MSFT）。如需调整某条事件的对标，直接改标的即可。")
line.append("- **数据截止**：美股最新交易日 2026-09-11（周五）。09-10 PPI 的 T+3、09-11 CPI 的 T+1/T+3 尚未发生，标“—”，后续 refresh 补齐。")
line.append("- 未计交易摩擦；仅供研究，不构成投资建议。\n")

content = "\n".join(line) + "\n"
with open(OUT, "w") as f:
    f.write(content)
print(f"已生成: {OUT}")
print(f"事件数: {len(rows)} | 突发 {n_tushu} / 预期 {n_yuqi}")
print(f"突发 平均 T+1={fmt_ret(tushu_r1)} T+3={fmt_ret(tushu_r3)}")
print(f"预期 平均 T+1={fmt_ret(yuqi_r1)} T+3={fmt_ret(yuqi_r3)}")
