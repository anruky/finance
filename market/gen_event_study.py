#!/usr/bin/env python3
"""Offline, reproducible SKHY event study. Inputs live beside this script; no API secrets."""
import json
from pathlib import Path
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
ET=ZoneInfo('America/New_York')
BJ=ZoneInfo('Asia/Shanghai')

def instant(s):
    return datetime.fromisoformat(s).astimezone(ET)

def close_time(day):
    # This snapshot covers Jul–Sep 2026 with no early-close sessions.
    return datetime.combine(day,time(16),ET)

def prepare(data):
    return sorted([(datetime.fromtimestamp(r['t']/1000,ET).date(),r['c']) for r in data['daily']])

def baseline(t,daily,bars):
    if t.date()<daily[0][0] or t.date()>daily[-1][0]:
        return None,'SKHY 数据覆盖之外'
    session=t.date() in {d for d,c in daily}
    if session and time(9,30)<=t.time().replace(tzinfo=None)<time(16):
        valid=[r for r in bars if datetime.fromtimestamp(r['t']/1000,ET).date()==t.date()
               and datetime.fromtimestamp(r['t']/1000,ET).time().replace(tzinfo=None)>=time(9,30)
               and r['t']+60000<=t.timestamp()*1000]
        if not valid:return None,'盘中逐笔/完整分钟线缺失'
        r=max(valid,key=lambda r:r['t']); start=datetime.fromtimestamp(r['t']/1000,ET)
        if t-(start+timedelta(minutes=1))>timedelta(minutes=2):return None,'分钟线过旧'
        return r['c'],start.strftime('%m-%d %H:%M')+'–'+(start+timedelta(minutes=1)).strftime('%H:%M')+' 分钟收盘代理'
    previous=[(d,c) for d,c in daily if close_time(d)<=t]
    if not previous:return None,'此前无 SKHY 收盘价'
    d,c=previous[-1]
    return c,f'{d:%m-%d} 16:00 收盘'

def main():
    events=json.loads((ROOT/'skhy_event_study_events.json').read_text())
    data=json.loads((ROOT/'skhy_event_study_prices.json').read_text())
    assert data['ticker']=='SKHY' and data['adjusted'] is False
    daily=prepare(data); bars=data['minute_bars']
    assert len({d for d,c in daily})==len(daily)
    events.sort(key=lambda e: (instant(e['timestamp']).isoformat() if e['timestamp'] else e['date_original']+'T23:59:59',e['id']))
    lines=['# AI／半导体事件研究：对 SKHY 美股的影响','',
    '> 更新：2026-09-15（北京时间）｜保留原 history 的 29 条事件｜股价覆盖：2026-07-13 至 2026-09-14 美东收盘。',
    '> 核心问题：事件前 SKHY 是否已提前反应？事件公开时的基准价是多少？之后股价如何变化？所有美元股价均为 SKHY。','',
    '## 一、阅读口径','',
    '- **观察标的统一为 SK hynix 美股 ADR：NASDAQ: SKHY**。MU、NVDA、AMD、云厂商等仅作为事件来源；不再混用其他公司的涨跌幅。原始事实和事件 ID 保留，事件范围仍参照 [历史清单](AI_semiconductor_history.md)。',
    '- **标的历史边界**：7 月 10 日上市初期使用临时代码 SKHYV，7 月 13 日起常规代码为 SKHY；当前 SKHY 行情自 7 月 13 日开始，不拼接 SKHYV 或韩国 000660。因此此前事件不能计算 SKHY 反应，也不能用上市后的首条价格回填。[公司上市公告](https://news.skhynix.com/en/skhynix-lists-adrs-on-nasdaq/)；[代码切换说明](https://www.tomshardware.com/tech-industry/semiconductors/sk-hynix-raises-a-record-usd26-5-billion-in-historic-u-s-ipo-south-korean-memory-giant-to-fund-massive-hbm-manufacturing-expansions)。',
    '- **时间**：下表统一列美东 ET，附北京时间和来源原始时区。此区间 ET 为 EDT（UTC−4），北京时间比 ET 快 12 小时。仅精确到分钟的来源，显示的秒数 :00 为占位，不代表秒级核验。官方新闻稿时间、网页元数据、媒体时间代理分别标注；没有证据不补写 09:00 或 16:00。',
    '- **事件基准价 B**：常规时段 09:30–16:00 ET 内，应取事件公开时或之前最近一笔有效成交；本次已复用 Data/data_puller.py 的相同 key、requests.Session 和 User-Agent 实测：日线/分钟线 HTTP 200；逐笔接口 /v3/trades/SKHY 返回 HTTP 403、NOT_AUTHORIZED（You are not entitled to this data），属于该接口的数据权限问题，非 API key 过期，暂用事件前最后一根完整分钟线收盘代理，绝不取事件所在分钟的收盘。非开盘时段按你的要求，使用最近一次常规收盘，包括盘后用当日收盘、盘前用前一交易日收盘、休市用上一个交易日收盘。',
    '- **前三天 D−3 / D−2 / D−1**：事件美东日历日期之前的三个交易日收盘，从远到近列出，排除事件当日。盘后事件的 B 可为事件当日收盘，故 B 不一定等于 D−1。时间未核实的条目暂按原记录日期展示，并标 †，跨时区日期确认后需重算。上市初期不足三天的部分保留缺失。',
    '- **事后 C1 / C3**：事件时间之后的第 1 / 第 3 次常规收盘；盘前或盘中事件的 C1 是当日收盘，盘后事件的 C1 是下一交易日收盘。涨跌幅 =（C/B − 1）×100%。这比旧版“事件日收盘基准”更贴近事件前后比较，列名也改为 C1/C3，避免混淆。',
    '- **分类**：“预期”表示财报/宏观数据/公司日历或预告发布会，不代表内容已被市场充分定价；产品突然上线、研究报告若缺少事前预告证据，改为“预告未核实”。单日跌幅属于市场观察，不作为独立新闻冲击。','',
    '## 二、事件时间与 SKHY 股价反应','',
    '“代理”表示观测窗口，不等于已核实的首次披露窗口。时间未知时，B 和收益留空；缺少 B 时也不提供看似可比较的事后收益。日内先后未知的事件按原日期归档，不声称严格的分钟排序。','',
    '| 事件 ID / 事件 | 分类 | 时间 ET（24 小时制） | 时间证据类型 | SKHY 基准 B / 取价时点 ET | C1：日期 / 收盘 / 相对 B | C3：日期 / 收盘 / 相对 B |',
    '| --- | --- | --- | --- | --- | --- | --- |']
    computed={}
    for e in events:
        t=instant(e['timestamp']) if e['timestamp'] else None
        b,why=baseline(t,daily,bars) if t else (None,'首发时分或时区待核实')
        computed[e['id']]=(t,b,why)
        after=[(d,c) for d,c in daily if t and close_time(d)>t]
        def outcome(n):
            if b is None:return '—（无有效基准）'
            if len(after)<n:return '—（观察窗口未完成）'
            d,c=after[n-1]
            return f'{d:%m-%d} / ${c:.2f} / {c/b-1:+.2%}'
        bc=f'${b:.4f}<br>{why}' if b is not None and '分钟' in why else f'${b:.2f}<br>{why}' if b is not None else '—<br>'+why
        stamp=t.strftime('%Y-%m-%d %H:%M:%S') if t else e['date_original']+' † 时分待核实'
        lines.append(f"| {e['id']}<br>**{e['title']}** | {e['classification']} | {stamp} | {e['time_quality']} | {bc} | {outcome(1)} | {outcome(3)} |")
    lines+=['','## 三、事件前三个交易日：预期是否已经反映','',
    '为便于比较，所有事件都提供事前价格；重点查看“预期”行。D−3→D−1 仅描述事前走势，不能证明资金提前获得消息。† 表示日期仍按原记录参照，不能当作已核实的美东事件日期。','',
    '| 事件 ID | 事件 / 分类 | 参考事件日 ET | D−3 收盘 | D−2 收盘 | D−1 收盘 | D−3→D−1 |',
    '| --- | --- | --- | --- | --- | --- | --- |']
    for e in events:
        t,b,why=computed[e['id']]
        day=t.date() if t else datetime.fromisoformat(e['date_original']).date()
        prior=[(d,c) for d,c in daily if d<day][-3:]
        prior=[None]*(3-len(prior))+prior
        cells=[f'{r[0]:%m-%d} / ${r[1]:.2f}' if r else '—（无更早 SKHY 数据）' for r in prior]
        change=f'{prior[-1][1]/prior[0][1]-1:+.2%}' if prior[0] else '—'
        lines.append('| '+' | '.join([e['id'],e['title']+' / '+e['classification'],str(day)+(' †' if not t else ''),*cells,change])+' |')
    lines+=['','## 四、逐条证据、原始时间及对 SKHY 的传导','',
    '以下“传导”是研究假设，不是收益归因。事件事实沿用原文，时间证据另行补充。优先关注海力士自身盈利、HBM/DRAM 供需；云端/模型变化需进一步确认是否转化为订单。','',
    '| 事件 ID | 原记录事实 / 来源 | 原始时间 → 北京时间 | 时间证据与待核实项 | SKHY 关注点（分析） |',
    '| --- | --- | --- | --- | --- |']
    for e in events:
        t,b,why=computed[e['id']]
        eid=e['id']
        if 'SKHYNIX' in eid:link='自身 HBM/DRAM 销量、ASP、毛利率与资本开支；应对照财报前市场一致预期。'
        elif 'DRAM' in eid or eid=='20260624-MU':link='存储价格、库存与供给纪律；区分 HBM、传统 DRAM、现货与长协。'
        elif 'SAMSUNG' in eid:link='竞争对手 HBM 认证与产能爬坡，可能改变 SKHY 份额和议价能力。'
        elif any(k in eid for k in ['NVDA','AMD','AVGO']):link='GPU/ASIC 交付及每系统 HBM 容量；订单、供应商份额及认证比发布口号更关键。'
        elif any(k in eid for k in ['FED','US-PPI','US-CPI']):link='利率、美元与成长股风险偏好；同时受宏观和存储基本面影响。'
        elif any(k in eid for k in ['TSM','ASML']):link='AI 算力产能与先进封装约束的侧面信号；不是 SKHY 已确认订单。'
        elif any(k in eid for k in ['GOOGL','MSFT','META','AMZN','TENCENT']):link='云厂商 Capex、AI 收入及算力扩张，向 HBM/服务器 DRAM 需求传导。'
        elif 'MU-MARKET' in eid:link='存储板块情绪背景；不能用已经发生的跌幅定义一个精确新闻冲击。'
        else:link='模型能力和推理效率对总 token 用量、内存容量需求的净影响；短期关联较弱。'
        local=e['timestamp'] if t else '待核实'
        bj=t.astimezone(BJ).strftime('%Y-%m-%d %H:%M:%S') if t else '待核实'
        lines.append(f"| {eid} | {e['fact']} [原始来源]({e['source']}) | {local}<br>北京：{bj} | {e['time_note']} [时间来源]({e['time_source']}) | {link} |")
    lines+=['','## 五、目前能读出的信号与不能归因的部分','',
    '- **先看海力士自身财报，再看 HBM/DRAM 价格与客户需求。** 同一家公司股价是统一观察对象，但不同事件对利润的距离不同，模型发布不能直接等同于新增 HBM 订单。',
    '- **7 月 29 日属于重叠事件窗口**：海力士韩国早间财报对应美东 7 月 28 日晚间；7 月 29 日盘中 FOMC，盘后 Meta、Microsoft，随后 Samsung 韩国早间财报。这些事件共享后续收盘价，不能把整个窗口的 SKHY 涨跌分别归因给每一条新闻。',
    '- **9 月 7 日是美国劳动节**：TrendForce 公告对应 ET 03:02:56，B 应取 9 月 4 日收盘，C1 为 9 月 8 日。不能取未来的 9 月 8 日收盘作为事件基准。',
    '- **9 月 10 日存在台积电月营收与 PPI 双重信息，随后还有 CPI**；C3 横跨这些事件，属于综合市场反应。CPI 的 C3 在本次截止时尚未完成。',
    '- **删除旧版“预期 vs 突发平均涨跌”及驱动结论**：原表混用了多只股票、上市前缺数据、事件时间与收盘错位；本版也存在重叠窗口和选择偏差，尚不能给出因果影响。未计算市场调整超额收益，原始涨跌还包含市场/行业共振。','',
    '## 六、数据来源与持续更新规则','',
    f"- 行情：Polygon REST，`/v2/aggs/ticker/SKHY/range/1/day/...` 与 `/range/1/minute/...`；本地抓取时间 `{data['fetched_at']}`，覆盖截至 `{data['through']}`。日线使用供应商日聚合 `c` 作为收盘口径，分钟线与日线的成交筛选可能不同，不强求 15:59 分钟收盘等于日线收盘。金额为 USD，未复权、非总回报；尚未完成区间公司行动核验，不再声称‘没有除息影响’。",
    '- API 响应为延迟行情快照，表内记录历史日期，不代表实时可成交报价。收盘按该期常规交易日 16:00 ET 标记；缺失行情不是零，不以前值填补未知事件或未到期观察窗口。',
    '- 可审计输入：[事件及时间证据](skhy_event_study_events.json)、[SKHY 日线及取价用分钟线](skhy_event_study_prices.json)。仅保存生成表格所需分钟样本，不含 API key。',
    '- 复现：运行 `python3 gen_event_study.py`，仅从同目录快照生成本文件，不联网拉取行情。更新时先补事件及时间来源，再刷新价格快照和截止日期，最后运行生成器；不要直接覆盖 Markdown 中生成的表格。',
    '- **时间补全优先级**：海力士首份 IR/DART 披露、Microsoft 原始公告/SEC 接收时间、台积电月营收与季度财报实际首发、Alphabet 财报首发；模型公告和 TrendForce 周报补公开时间及原始时区。新闻稿、电话会、媒体转载分别建事件，只有确认同一信息才合并。',
    '- 预期事件增加事前预告链接、一致预期和实际值；之后研究的是“超预期幅度”，而非仅判断数字好坏。',
    '- 若逐笔权限可用，保存事件时点之前最近有效成交的价格、SIP 时间戳及成交条件，替换分钟代理，并注明逐笔口径。若只是分钟级公告时间，无法辨识同一秒内消息与成交先后，应保留这一精度限制。',
    '- 本生成器的交易日来自已取得的行情，当前区间没有半日交易；扩展到感恩节等半日市或未来事件时，应先接入交易所日历和实际收市时间。新事件不得早于行情覆盖却被回填未来价；未完成的 C1/C3 保留待更新。',
    '- 本轮优化前的原始文档和生成器保存在 `archive/event_study_before_skhy_2026-09-15/`，便于对照用户原有修改。','']
    (ROOT/'AI_semiconductor_event_study.md').write_text('\n'.join(lines))
    print(f'Generated {len(events)} events; {sum(e[1] is not None for e in computed.values())} price baselines; {len(daily)} daily bars.')

if __name__=='__main__':main()
