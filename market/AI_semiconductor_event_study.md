# AI／半导体事件研究：对 SKHY 美股的影响

> 更新：2026-09-15（北京时间）｜保留原 history 的 29 条事件｜股价覆盖：2026-07-13 至 2026-09-14 美东收盘。
> 核心问题：事件前 SKHY 是否已提前反应？事件公开时的基准价是多少？之后股价如何变化？所有美元股价均为 SKHY。

## 一、阅读口径

- **观察标的统一为 SK hynix 美股 ADR：NASDAQ: SKHY**。MU、NVDA、AMD、云厂商等仅作为事件来源；不再混用其他公司的涨跌幅。原始事实和事件 ID 保留，事件范围仍参照 [历史清单](AI_semiconductor_history.md)。
- **标的历史边界**：7 月 10 日上市初期使用临时代码 SKHYV，7 月 13 日起常规代码为 SKHY；当前 SKHY 行情自 7 月 13 日开始，不拼接 SKHYV 或韩国 000660。因此此前事件不能计算 SKHY 反应，也不能用上市后的首条价格回填。[公司上市公告](https://news.skhynix.com/en/skhynix-lists-adrs-on-nasdaq/)；[代码切换说明](https://www.tomshardware.com/tech-industry/semiconductors/sk-hynix-raises-a-record-usd26-5-billion-in-historic-u-s-ipo-south-korean-memory-giant-to-fund-massive-hbm-manufacturing-expansions)。
- **时间**：下表统一列美东 ET，附北京时间和来源原始时区。此区间 ET 为 EDT（UTC−4），北京时间比 ET 快 12 小时。仅精确到分钟的来源，显示的秒数 :00 为占位，不代表秒级核验。官方新闻稿时间、网页元数据、媒体时间代理分别标注；没有证据不补写 09:00 或 16:00。
- **事件基准价 B**：常规时段 09:30–16:00 ET 内，应取事件公开时或之前最近一笔有效成交；本次已复用 Data/data_puller.py 的相同 key、requests.Session 和 User-Agent 实测：日线/分钟线 HTTP 200；逐笔接口 /v3/trades/SKHY 返回 HTTP 403、NOT_AUTHORIZED（You are not entitled to this data），属于该接口的数据权限问题，非 API key 过期，暂用事件前最后一根完整分钟线收盘代理，绝不取事件所在分钟的收盘。非开盘时段按你的要求，使用最近一次常规收盘，包括盘后用当日收盘、盘前用前一交易日收盘、休市用上一个交易日收盘。
- **前三天 D−3 / D−2 / D−1**：事件美东日历日期之前的三个交易日收盘，从远到近列出，排除事件当日。盘后事件的 B 可为事件当日收盘，故 B 不一定等于 D−1。时间未核实的条目暂按原记录日期展示，并标 †，跨时区日期确认后需重算。上市初期不足三天的部分保留缺失。
- **事后 C1 / C3**：事件时间之后的第 1 / 第 3 次常规收盘；盘前或盘中事件的 C1 是当日收盘，盘后事件的 C1 是下一交易日收盘。涨跌幅 =（C/B − 1）×100%。这比旧版“事件日收盘基准”更贴近事件前后比较，列名也改为 C1/C3，避免混淆。
- **分类**：“预期”表示财报/宏观数据/公司日历或预告发布会，不代表内容已被市场充分定价；产品突然上线、研究报告若缺少事前预告证据，改为“预告未核实”。单日跌幅属于市场观察，不作为独立新闻冲击。

## 二、事件时间与 SKHY 股价反应

“代理”表示观测窗口，不等于已核实的首次披露窗口。时间未知时，B 和收益留空；缺少 B 时也不提供看似可比较的事后收益。日内先后未知的事件按原日期归档，不声称严格的分钟排序。

| 事件 ID / 事件 | 分类 | 时间 ET（24 小时制） | 时间证据类型 | SKHY 基准 B / 取价时点 ET | C1：日期 / 收盘 / 相对 B | C3：日期 / 收盘 / 相对 B |
| --- | --- | --- | --- | --- | --- | --- |
| 20260617-FED<br>**FOMC 维持 3.50%–3.75%** | 预期 | 2026-06-17 14:00:00 | 官方发布时间 | —<br>SKHY 数据覆盖之外 | —（无有效基准） | —（无有效基准） |
| 20260623-MU-MARKET<br>**美光财报前单日 -13.2%** | 市场观察 | 2026-06-23 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260624-MU<br>**Micron FY26Q3 财报** | 预期 | 2026-06-24 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260709-DRAM-LTA<br>**Q3 Server DRAM 合约价 +13–18%** | 预告未核实 | 2026-07-09 01:52:53 | 官方网页元数据 | —<br>SKHY 数据覆盖之外 | —（无有效基准） | —（无有效基准） |
| 20260713-TSM-JUN<br>**台积电 6 月营收 +67.9%** | 预期 | 2026-07-13 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260715-ASML<br>**ASML Q2 财报** | 预期 | 2026-07-15 01:00:00 | 官方发布时间 | $193.92<br>07-14 16:00 收盘 | 07-15 / $176.46 / -9.00% | 07-17 / $154.03 / -20.57% |
| 20260716-TSM-Q2<br>**台积电 Q2 财报** | 预期 | 2026-07-16 02:28:00 | 媒体时间代理 | $176.46<br>07-15 16:00 收盘 | 07-16 / $152.31 / -13.69% | 07-20 / $151.16 / -14.34% |
| 20260722-GOOGL<br>**Alphabet Q2 财报** | 预期 | 2026-07-22 16:01:36 | SEC 接收时间代理 | $165.27<br>07-22 16:00 收盘 | 07-23 / $169.50 / +2.56% | 07-27 / $143.02 / -13.46% |
| 20260723-AMD-HELIOS<br>**AMD 发布 Helios 机柜系统** | 预期 | 2026-07-23 14:30:00 | 官方新闻稿时间 | $172.7400<br>07-23 14:29–14:30 分钟收盘代理 | 07-23 / $169.50 / -1.88% | 07-27 / $143.02 / -17.21% |
| 20260724-CLAUDE-OPUS5<br>**Claude Opus 5 发布** | 预告未核实 | 2026-07-24 13:00:00 | 媒体时间代理 | $157.3950<br>07-24 12:59–13:00 分钟收盘代理 | 07-24 / $154.57 / -1.79% | 07-28 / $130.17 / -17.30% |
| 20260729-SKHYNIX<br>**SK hynix Q2 财报** | 预期 | 2026-07-28 19:45:00 | 媒体时间代理 | $130.17<br>07-28 16:00 收盘 | 07-29 / $126.79 / -2.60% | 07-31 / $143.73 / +10.42% |
| 20260729-FED<br>**FOMC 维持 3.50%–3.75%** | 预期 | 2026-07-29 14:00:00 | 官方发布时间 | $128.4450<br>07-29 13:59–14:00 分钟收盘代理 | 07-29 / $126.79 / -1.29% | 07-31 / $143.73 / +11.90% |
| 20260729-META<br>**Meta 2026 Capex 指引上修** | 预期 | 2026-07-29 16:01:00 | 公司通讯社发布时间 | $126.79<br>07-29 16:00 收盘 | 07-30 / $149.00 / +17.52% | 08-03 / $142.72 / +12.56% |
| 20260729-MSFT<br>**Microsoft FY26Q4 财报** | 预期 | 2026-07-29 16:05:00 | 文件转载时间代理 | $126.79<br>07-29 16:00 收盘 | 07-30 / $149.00 / +17.52% | 08-03 / $142.72 / +12.56% |
| 20260730-SAMSUNG<br>**Samsung Q2 财报** | 预期 | 2026-07-29 19:56:00 | 官方网页元数据 | $126.79<br>07-29 16:00 收盘 | 07-30 / $149.00 / +17.52% | 08-03 / $142.72 / +12.56% |
| 20260730-AMZN<br>**Amazon Q2 财报** | 预期 | 2026-07-30 16:01:00 | 公司通讯社转载时间 | $149.00<br>07-30 16:00 收盘 | 07-31 / $143.73 / -3.54% | 08-04 / $154.38 / +3.61% |
| 20260804-AMD-Q2<br>**AMD Q2 财报** | 预期 | 2026-08-04 16:15:00 | 官方发布时间 | $154.38<br>08-04 16:00 收盘 | 08-05 / $151.03 / -2.17% | 08-07 / $137.91 / -10.67% |
| 20260810-TSM-JUL<br>**台积电 7 月营收 +44.7%** | 预期 | 2026-08-10 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260812-TENCENT<br>**腾讯 Q2 财报** | 预期 | 2026-08-12 06:29:00 | 公司通讯社发布时间 | $141.65<br>08-11 16:00 收盘 | 08-12 / $154.41 / +9.01% | 08-14 / $166.33 / +17.42% |
| 20260826-NVDA<br>**NVIDIA FY27Q2 财报** | 预期 | 2026-08-26 16:20:00 | 公司通讯社发布时间 | $158.02<br>08-26 16:00 收盘 | 08-27 / $161.61 / +2.27% | 08-31 / $164.58 / +4.15% |
| 20260831-ANTHROPIC-SECURITY<br>**Anthropic 安全与对齐改进公告** | 突发（沿用原分类） | 2026-08-31 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260901-CLAUDE51<br>**Claude Fable/Mythos 5.1 发布** | 预告未核实 | 2026-09-01 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260902-AVGO<br>**Broadcom FY26Q3 财报** | 预期 | 2026-09-02 16:15:00 | 公司通讯社发布时间 | $164.98<br>09-02 16:00 收盘 | 09-03 / $163.68 / -0.79% | 09-08 / $185.55 / +12.47% |
| 20260902-DRAM-SPOT<br>**PC DRAM 合约上修 / 现货偏弱** | 预告未核实 | 2026-09-02 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260903-GPT6<br>**GPT-6 Astra 发布** | 预告未核实 | 2026-09-03 † 时分待核实 | 待核实 | —<br>首发时分或时区待核实 | —（无有效基准） | —（无有效基准） |
| 20260907-DRAM-Q2<br>**Q2 DRAM 行业收入 +59.5%** | 预告未核实 | 2026-09-07 03:02:56 | 官方网页元数据 | $177.00<br>09-04 16:00 收盘 | 09-08 / $185.55 / +4.83% | 09-10 / $188.30 / +6.38% |
| 20260910-TSM-AUG<br>**台积电 8 月营收 +53.3%** | 预期 | 2026-09-10 03:55:00 | 媒体时间代理 | $198.63<br>09-09 16:00 收盘 | 09-10 / $188.30 / -5.20% | 09-14 / $175.63 / -11.58% |
| 20260910-US-PPI<br>**美国 8 月 PPI +0.4%** | 预期 | 2026-09-10 08:30:00 | 官方发布时间 | $198.63<br>09-09 16:00 收盘 | 09-10 / $188.30 / -5.20% | 09-14 / $175.63 / -11.58% |
| 20260911-US-CPI<br>**美国 8 月 CPI +0.4%** | 预期 | 2026-09-11 08:30:00 | 官方发布时间 | $188.30<br>09-10 16:00 收盘 | 09-11 / $190.07 / +0.94% | —（观察窗口未完成） |

## 三、事件前三个交易日：预期是否已经反映

为便于比较，所有事件都提供事前价格；重点查看“预期”行。D−3→D−1 仅描述事前走势，不能证明资金提前获得消息。† 表示日期仍按原记录参照，不能当作已核实的美东事件日期。

| 事件 ID | 事件 / 分类 | 参考事件日 ET | D−3 收盘 | D−2 收盘 | D−1 收盘 | D−3→D−1 |
| --- | --- | --- | --- | --- | --- | --- |
| 20260617-FED | FOMC 维持 3.50%–3.75% / 预期 | 2026-06-17 | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | — |
| 20260623-MU-MARKET | 美光财报前单日 -13.2% / 市场观察 | 2026-06-23 † | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | — |
| 20260624-MU | Micron FY26Q3 财报 / 预期 | 2026-06-24 † | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | — |
| 20260709-DRAM-LTA | Q3 Server DRAM 合约价 +13–18% / 预告未核实 | 2026-07-09 | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | — |
| 20260713-TSM-JUN | 台积电 6 月营收 +67.9% / 预期 | 2026-07-13 † | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | —（无更早 SKHY 数据） | — |
| 20260715-ASML | ASML Q2 财报 / 预期 | 2026-07-15 | —（无更早 SKHY 数据） | 07-13 / $152.35 | 07-14 / $193.92 | — |
| 20260716-TSM-Q2 | 台积电 Q2 财报 / 预期 | 2026-07-16 | 07-13 / $152.35 | 07-14 / $193.92 | 07-15 / $176.46 | +15.83% |
| 20260722-GOOGL | Alphabet Q2 财报 / 预期 | 2026-07-22 | 07-17 / $154.03 | 07-20 / $151.16 | 07-21 / $171.94 | +11.63% |
| 20260723-AMD-HELIOS | AMD 发布 Helios 机柜系统 / 预期 | 2026-07-23 | 07-20 / $151.16 | 07-21 / $171.94 | 07-22 / $165.27 | +9.33% |
| 20260724-CLAUDE-OPUS5 | Claude Opus 5 发布 / 预告未核实 | 2026-07-24 | 07-21 / $171.94 | 07-22 / $165.27 | 07-23 / $169.50 | -1.42% |
| 20260729-SKHYNIX | SK hynix Q2 财报 / 预期 | 2026-07-28 | 07-23 / $169.50 | 07-24 / $154.57 | 07-27 / $143.02 | -15.62% |
| 20260729-FED | FOMC 维持 3.50%–3.75% / 预期 | 2026-07-29 | 07-24 / $154.57 | 07-27 / $143.02 | 07-28 / $130.17 | -15.79% |
| 20260729-META | Meta 2026 Capex 指引上修 / 预期 | 2026-07-29 | 07-24 / $154.57 | 07-27 / $143.02 | 07-28 / $130.17 | -15.79% |
| 20260729-MSFT | Microsoft FY26Q4 财报 / 预期 | 2026-07-29 | 07-24 / $154.57 | 07-27 / $143.02 | 07-28 / $130.17 | -15.79% |
| 20260730-SAMSUNG | Samsung Q2 财报 / 预期 | 2026-07-29 | 07-24 / $154.57 | 07-27 / $143.02 | 07-28 / $130.17 | -15.79% |
| 20260730-AMZN | Amazon Q2 财报 / 预期 | 2026-07-30 | 07-27 / $143.02 | 07-28 / $130.17 | 07-29 / $126.79 | -11.35% |
| 20260804-AMD-Q2 | AMD Q2 财报 / 预期 | 2026-08-04 | 07-30 / $149.00 | 07-31 / $143.73 | 08-03 / $142.72 | -4.21% |
| 20260810-TSM-JUL | 台积电 7 月营收 +44.7% / 预期 | 2026-08-10 † | 08-05 / $151.03 | 08-06 / $143.53 | 08-07 / $137.91 | -8.69% |
| 20260812-TENCENT | 腾讯 Q2 财报 / 预期 | 2026-08-12 | 08-07 / $137.91 | 08-10 / $135.29 | 08-11 / $141.65 | +2.71% |
| 20260826-NVDA | NVIDIA FY27Q2 财报 / 预期 | 2026-08-26 | 08-21 / $163.41 | 08-24 / $155.37 | 08-25 / $159.53 | -2.37% |
| 20260831-ANTHROPIC-SECURITY | Anthropic 安全与对齐改进公告 / 突发（沿用原分类） | 2026-08-31 † | 08-26 / $158.02 | 08-27 / $161.61 | 08-28 / $161.04 | +1.91% |
| 20260901-CLAUDE51 | Claude Fable/Mythos 5.1 发布 / 预告未核实 | 2026-09-01 † | 08-27 / $161.61 | 08-28 / $161.04 | 08-31 / $164.58 | +1.84% |
| 20260902-AVGO | Broadcom FY26Q3 财报 / 预期 | 2026-09-02 | 08-28 / $161.04 | 08-31 / $164.58 | 09-01 / $160.78 | -0.16% |
| 20260902-DRAM-SPOT | PC DRAM 合约上修 / 现货偏弱 / 预告未核实 | 2026-09-02 † | 08-28 / $161.04 | 08-31 / $164.58 | 09-01 / $160.78 | -0.16% |
| 20260903-GPT6 | GPT-6 Astra 发布 / 预告未核实 | 2026-09-03 † | 08-31 / $164.58 | 09-01 / $160.78 | 09-02 / $164.98 | +0.24% |
| 20260907-DRAM-Q2 | Q2 DRAM 行业收入 +59.5% / 预告未核实 | 2026-09-07 | 09-02 / $164.98 | 09-03 / $163.68 | 09-04 / $177.00 | +7.29% |
| 20260910-TSM-AUG | 台积电 8 月营收 +53.3% / 预期 | 2026-09-10 | 09-04 / $177.00 | 09-08 / $185.55 | 09-09 / $198.63 | +12.22% |
| 20260910-US-PPI | 美国 8 月 PPI +0.4% / 预期 | 2026-09-10 | 09-04 / $177.00 | 09-08 / $185.55 | 09-09 / $198.63 | +12.22% |
| 20260911-US-CPI | 美国 8 月 CPI +0.4% / 预期 | 2026-09-11 | 09-08 / $185.55 | 09-09 / $198.63 | 09-10 / $188.30 | +1.48% |

## 四、逐条证据、原始时间及对 SKHY 的传导

以下“传导”是研究假设，不是收益归因。事件事实沿用原文，时间证据另行补充。优先关注海力士自身盈利、HBM/DRAM 供需；云端/模型变化需进一步确认是否转化为订单。

| 事件 ID | 原记录事实 / 来源 | 原始时间 → 北京时间 | 时间证据与待核实项 | SKHY 关注点（分析） |
| --- | --- | --- | --- | --- |
| 20260617-FED | 12:0 通过，强调通胀仍高于目标 [原始来源](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm) | 2026-06-17T14:00:00-04:00<br>北京：2026-06-18 02:00:00 | 公告正文：2:00 p.m. EDT [时间来源](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm) | 利率、美元与成长股风险偏好；同时受宏观和存储基本面影响。 |
| 20260623-MU-MARKET | Axios 次日报道，事件日 06-23、报道日 06-24 [原始来源](https://www.axios.com/2026/06/24/micron-earnings-expectations-have-gone-vertical) | 待核实<br>北京：待核实 | 全天跌幅是市场结果，不是单一新闻冲击；不设置虚构分钟。 [时间来源](https://www.axios.com/2026/06/24/micron-earnings-expectations-have-gone-vertical) | 存储板块情绪背景；不能用已经发生的跌幅定义一个精确新闻冲击。 |
| 20260624-MU | 营收 $41.46B，经营现金流 $25.39B [原始来源](https://investors.micron.com/node/50671/pdf) | 待核实<br>北京：待核实 | 财报日期已知，首发时分待补；SKHY 序列尚未开始。 [时间来源](https://investors.micron.com/node/50671/pdf) | 存储价格、库存与供给纪律；区分 HBM、传统 DRAM、现货与长协。 |
| 20260709-DRAM-LTA | TrendForce；区分长协与非长协客户 [原始来源](https://www.trendforce.com/presscenter/news/20260709-13140.html) | 2026-07-09T13:52:53+08:00<br>北京：2026-07-09 13:52:53 | datePublished，含 +08:00 时区；不保证最早新闻渠道 [时间来源](https://www.trendforce.com/presscenter/news/20260709-13140.html) | 存储价格、库存与供给纪律；区分 HBM、传统 DRAM、现货与长协。 |
| 20260713-TSM-JUN | NT$442,680 百万；原定 07-10 台风延至 07-13 [原始来源](https://investor.tsmc.com/english/monthly-revenue/2026) | 待核实<br>北京：待核实 | 官方日历确认台风延期至 07-13，历史页未给首发时分。 [时间来源](https://investor.tsmc.com/english/monthly-revenue/2026) | AI 算力产能与先进封装约束的侧面信号；不是 SKHY 已确认订单。 |
| 20260715-ASML | 净销售 €9.326B，全年指引 €43–45B [原始来源](https://www.asml.com/en/news/press-releases/2026/q2-2026-financial-results) | 2026-07-15T05:00:00+00:00<br>北京：2026-07-15 13:00:00 | article:published_time 与 sc:publication_date 均为 05:00 UTC，即 07:00 CEST [时间来源](https://www.asml.com/en/news/press-releases/2026/q2-2026-financial-results) | AI 算力产能与先进封装约束的侧面信号；不是 SKHY 已确认订单。 |
| 20260716-TSM-Q2 | 美元收入 $40.20B +33.7%，毛利率 67.7% [原始来源](https://investor.tsmc.com/english/encrypt/files/encrypt_file/qr/phase4_reports/2026-07/887682617ea280c69ee0bbec7665804756464837/2Q26%20EarningsRelease_WoG.pdf) | 2026-07-16T14:28:00+08:00<br>北京：2026-07-16 14:28:00 | Bloomberg / The Edge 发布记录为 14:28 GMT+08；非财报首发、非电话会开始时间 [时间来源](https://www.theedgesingapore.com/news/tech/tsmc-beats-lofty-estimates-latest-sign-sustained-ai-demand) | AI 算力产能与先进封装约束的侧面信号；不是 SKHY 已确认订单。 |
| 20260722-GOOGL | 总收入 $119.8B +24%，GCP $24.8B +82% [原始来源](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm) | 2026-07-22T16:01:36-04:00<br>北京：2026-07-23 04:01:36 | SEC 8-K Accepted=16:01:36 ET；是监管文件接收时间，非新闻稿首次发布时间 [时间来源](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/0001652044-26-000066-index.html) | 云厂商 Capex、AI 收入及算力扩张，向 HBM/服务器 DRAM 需求传导。 |
| 20260723-AMD-HELIOS | Advancing AI，进入生产 [原始来源](https://ir.amd.com/news-events/press-releases/detail/1294/aai-2026-amd-delivers-full-stack-compute-for-the-agentic-ai-era) | 2026-07-23T14:30:00-04:00<br>北京：2026-07-24 02:30:00 | 官方 IR time 标签；发布会台上首次披露可能更早 [时间来源](https://ir.amd.com/news-events/press-releases/detail/1294/aai-2026-amd-delivers-full-stack-compute-for-the-agentic-ai-era) | GPU/ASIC 交付及每系统 HBM 容量；订单、供应商份额及认证比发布口号更关键。 |
| 20260724-CLAUDE-OPUS5 | 定位长时 Agent、编码、专业工作 [原始来源](https://www.anthropic.com/news/claude-opus-5) | 2026-07-24T10:00:00-07:00<br>北京：2026-07-25 01:00:00 | VentureBeat 10:00am PT；非官方首发时间，收益仅作代理窗口观察 [时间来源](https://venturebeat.com/orchestration/anthropic-launches-claude-opus-5-a-cheaper-ai-model-for-coding-agents-and-enterprise-workflows) | 模型能力和推理效率对总 token 用量、内存容量需求的净影响；短期关联较弱。 |
| 20260729-SKHYNIX | 营收 KRW79.32 万亿，营业利润 KRW60.54 万亿 [原始来源](https://news.skhynix.com/en/q2-2026-business-results/) | 2026-07-29T08:45:00+09:00<br>北京：2026-07-29 07:45:00 | 韩联社 LEAD 稿显示 08:45 KST，较此前 09:00 版本早；仍非官方首发时间 [时间来源](https://en.yna.co.kr/view/AEN20260729001051320?section=economy-finance%2Feconomy) | 自身 HBM/DRAM 销量、ASP、毛利率与资本开支；应对照财报前市场一致预期。 |
| 20260729-FED | 9:3 通过，分歧扩大 [原始来源](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm) | 2026-07-29T14:00:00-04:00<br>北京：2026-07-30 02:00:00 | 公告正文：2:00 p.m. EDT；14:30 新闻发布会是另一个事件 [时间来源](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm) | 利率、美元与成长股风险偏好；同时受宏观和存储基本面影响。 |
| 20260729-META | $125–145B → $130–145B [原始来源](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Second-Quarter-2026-Results/default.aspx) | 2026-07-29T16:01:00-04:00<br>北京：2026-07-30 04:01:00 | Meta 通过 PR Newswire 发布，16:01 ET [时间来源](https://www.prnewswire.com/news-releases/meta-reports-second-quarter-2026-results-302838214.html) | 云厂商 Capex、AI 收入及算力扩张，向 HBM/服务器 DRAM 需求传导。 |
| 20260729-MSFT | 收入 $90.0B +18%，营业利润 $40.6B [原始来源](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast) | 2026-07-29T16:05:00-04:00<br>北京：2026-07-30 04:05:00 | 8-K 转载显示 4:05 PM EDT；非首发时间，盘后基准使用当日收盘 [时间来源](https://www.streetinsider.com/SEC%2BFilings/Form%2B8-K%2BMICROSOFT%2BCORP%2BFor%3A%2BJul%2B29/26834854.html?classic=1) | 云厂商 Capex、AI 收入及算力扩张，向 HBM/服务器 DRAM 需求传导。 |
| 20260730-SAMSUNG | 集团营收 KRW171.5 万亿，DS 环比 +56% [原始来源](https://news.samsung.com/global/samsung-electronics-announces-second-quarter-2026-results) | 2026-07-30T08:56:00+09:00<br>北京：2026-07-30 07:56:00 | datePublished=08:56 KST；不是 dateModified [时间来源](https://news.samsung.com/global/samsung-electronics-announces-second-quarter-2026-results) | 竞争对手 HBM 认证与产能爬坡，可能改变 SKHY 份额和议价能力。 |
| 20260730-AMZN | AWS 营业利润 $16.6B [原始来源](https://www.aboutamazon.com/news/company-news/amazon-earnings-q2-2026-report) | 2026-07-30T16:01:00-04:00<br>北京：2026-07-31 04:01:00 | Amazon 通过 BusinessWire 发布的稿件，转载标记 16:01 EDT [时间来源](https://markets.financialcontent.com/wss/article/bizwire-2026-7-30-amazoncom-announces-second-quarter-results) | 云厂商 Capex、AI 收入及算力扩张，向 HBM/服务器 DRAM 需求传导。 |
| 20260804-AMD-Q2 | 收入 $11.536B +50%，DC $6.7B +107% [原始来源](https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results) | 2026-08-04T16:15:00-04:00<br>北京：2026-08-05 04:15:00 | 官方 IR time 标签：4:15pm EDT；17:00 电话会不作财报首发 [时间来源](https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results) | GPU/ASIC 交付及每系统 HBM 容量；订单、供应商份额及认证比发布口号更关键。 |
| 20260810-TSM-JUL | NT$467,580 百万 [原始来源](https://investor.tsmc.com/english/monthly-revenue/2026) | 待核实<br>北京：待核实 | 官方历史日历只有日期；不把其他月份的 13:30 套用。 [时间来源](https://investor.tsmc.com/english/monthly-revenue/2026) | AI 算力产能与先进封装约束的侧面信号；不是 SKHY 已确认订单。 |
| 20260812-TENCENT | 营销服务收入 人民币436 亿 +22% [原始来源](https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf) | 2026-08-12T18:29:00+08:00<br>北京：2026-08-12 18:29:00 | PR Newswire APAC：18:29 CST（中国标准时间）；可能晚于港交所首次披露 [时间来源](https://www.prnewswire.com/apac/news-releases/tencent-announces-2026-second-quarter-results-302849608.html) | 云厂商 Capex、AI 收入及算力扩张，向 HBM/服务器 DRAM 需求传导。 |
| 20260826-NVDA | 收入 $96.2B，DC $89.0B，Q3 指引 $108B [原始来源](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027) | 2026-08-26T16:20:00-04:00<br>北京：2026-08-27 04:20:00 | NVIDIA 通过 GlobeNewswire 发布：16:20 ET [时间来源](https://www.globenewswire.com/news-release/2026/8/26/3351702/0/en/nvidia-announces-financial-results-for-second-quarter-fiscal-2027.html) | GPU/ASIC 交付及每系统 HBM 容量；订单、供应商份额及认证比发布口号更关键。 |
| 20260831-ANTHROPIC-SECURITY | 回应模型未授权系统访问事件 [原始来源](https://www.anthropic.com/news/improving-alignment-security-efforts) | 待核实<br>北京：待核实 | 官方页面未提供可验证首发时分；网站整体更新时间不可用。 [时间来源](https://www.anthropic.com/news/improving-alignment-security-efforts) | 模型能力和推理效率对总 token 用量、内存容量需求的净影响；短期关联较弱。 |
| 20260901-CLAUDE51 | 强调编码、知识工作、科研 [原始来源](https://www.anthropic.com/claude-fable-and-mythos-5-1) | 待核实<br>北京：待核实 | 官方页面首发时分、事前预告均待核实。 [时间来源](https://www.anthropic.com/claude-fable-and-mythos-5-1) | 模型能力和推理效率对总 token 用量、内存容量需求的净影响；短期关联较弱。 |
| 20260902-AVGO | 总收入 $29.6B，AI 半导体 $16.7B +221% [原始来源](https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-third-quarter-fiscal-year-2026-financial) | 2026-09-02T16:15:00-04:00<br>北京：2026-09-03 04:15:00 | Broadcom 通过 PR Newswire 发布：16:15 ET [时间来源](https://www.prnewswire.com/news-releases/broadcom-inc-announces-third-quarter-fiscal-year-2026-financial-results-and-quarterly-dividend-302868129.html) | GPU/ASIC 交付及每系统 HBM 容量；订单、供应商份额及认证比发布口号更关键。 |
| 20260902-DRAM-SPOT | TrendForce 周报摘要 [原始来源](https://www.trendforce.com/research/download/RP260902ZP) | 待核实<br>北京：待核实 | 页面 datePublished 为 2026-09-02 09:58:00，但未附时区，暂不换算 ET。 [时间来源](https://www.trendforce.com/research/download/RP260902ZP) | 存储价格、库存与供给纪律；区分 HBM、传统 DRAM、现货与长协。 |
| 20260903-GPT6 | 重点复杂任务与自主执行 [原始来源](https://openai.com/index/gpt-6-astra/) | 待核实<br>北京：待核实 | 官方首发时分和事前预告待核实；不默认 10:00 PT。 [时间来源](https://openai.com/index/gpt-6-astra/) | 模型能力和推理效率对总 token 用量、内存容量需求的净影响；短期关联较弱。 |
| 20260907-DRAM-Q2 | 预测 Q3 传统 DRAM 合约 +13–18% [原始来源](https://www.trendforce.com/presscenter/news/20260907-13219.html) | 2026-09-07T15:02:56+08:00<br>北京：2026-09-07 15:02:56 | datePublished，含 +08:00 时区；美国劳动节休市 [时间来源](https://www.trendforce.com/presscenter/news/20260907-13219.html) | 存储价格、库存与供给纪律；区分 HBM、传统 DRAM、现货与长协。 |
| 20260910-TSM-AUG | NT$514.81B，环比 +10.1% [原始来源](https://pr.cld.tsmc.com/english/news/3340) | 2026-09-10T15:55:00+08:00<br>北京：2026-09-10 15:55:00 | Bloomberg / The Edge 发布记录为 15:55 GMT+08；实际首发分钟待补，13:30 计划时间不当作实际时间 [时间来源](https://www.theedgesingapore.com/amp/news/tech/tsmc-revenue-rises-53-ai-chip-demand-outstrips-supply) | AI 算力产能与先进封装约束的侧面信号；不是 SKHY 已确认订单。 |
| 20260910-US-PPI | 同比 +5.4%，核心 +0.3% [原始来源](https://www.bls.gov/news.release/archives/ppi_09102026.htm) | 2026-09-10T08:30:00-04:00<br>北京：2026-09-10 20:30:00 | BLS 正文解禁时间：8:30 a.m. ET [时间来源](https://www.bls.gov/news.release/archives/ppi_09102026.htm) | 利率、美元与成长股风险偏好；同时受宏观和存储基本面影响。 |
| 20260911-US-CPI | 同比 +3.4%，核心同比 2.4% [原始来源](https://www.bls.gov/news.release/archives/cpi_09112026.htm) | 2026-09-11T08:30:00-04:00<br>北京：2026-09-11 20:30:00 | BLS 正文解禁时间：8:30 a.m. ET [时间来源](https://www.bls.gov/news.release/archives/cpi_09112026.htm) | 利率、美元与成长股风险偏好；同时受宏观和存储基本面影响。 |

## 五、目前能读出的信号与不能归因的部分

- **先看海力士自身财报，再看 HBM/DRAM 价格与客户需求。** 同一家公司股价是统一观察对象，但不同事件对利润的距离不同，模型发布不能直接等同于新增 HBM 订单。
- **7 月 29 日属于重叠事件窗口**：海力士韩国早间财报对应美东 7 月 28 日晚间；7 月 29 日盘中 FOMC，盘后 Meta、Microsoft，随后 Samsung 韩国早间财报。这些事件共享后续收盘价，不能把整个窗口的 SKHY 涨跌分别归因给每一条新闻。
- **9 月 7 日是美国劳动节**：TrendForce 公告对应 ET 03:02:56，B 应取 9 月 4 日收盘，C1 为 9 月 8 日。不能取未来的 9 月 8 日收盘作为事件基准。
- **9 月 10 日存在台积电月营收与 PPI 双重信息，随后还有 CPI**；C3 横跨这些事件，属于综合市场反应。CPI 的 C3 在本次截止时尚未完成。
- **删除旧版“预期 vs 突发平均涨跌”及驱动结论**：原表混用了多只股票、上市前缺数据、事件时间与收盘错位；本版也存在重叠窗口和选择偏差，尚不能给出因果影响。未计算市场调整超额收益，原始涨跌还包含市场/行业共振。

## 六、数据来源与持续更新规则

- 行情：Polygon REST，`/v2/aggs/ticker/SKHY/range/1/day/...` 与 `/range/1/minute/...`；本地抓取时间 `2026-09-15T02:47:14.186397+00:00`，覆盖截至 `2026-09-14`。日线使用供应商日聚合 `c` 作为收盘口径，分钟线与日线的成交筛选可能不同，不强求 15:59 分钟收盘等于日线收盘。金额为 USD，未复权、非总回报；尚未完成区间公司行动核验，不再声称‘没有除息影响’。
- API 响应为延迟行情快照，表内记录历史日期，不代表实时可成交报价。收盘按该期常规交易日 16:00 ET 标记；缺失行情不是零，不以前值填补未知事件或未到期观察窗口。
- 可审计输入：[事件及时间证据](skhy_event_study_events.json)、[SKHY 日线及取价用分钟线](skhy_event_study_prices.json)。仅保存生成表格所需分钟样本，不含 API key。
- 复现：运行 `python3 gen_event_study.py`，仅从同目录快照生成本文件，不联网拉取行情。更新时先补事件及时间来源，再刷新价格快照和截止日期，最后运行生成器；不要直接覆盖 Markdown 中生成的表格。
- **时间补全优先级**：海力士首份 IR/DART 披露、Microsoft 原始公告/SEC 接收时间、台积电月营收与季度财报实际首发、Alphabet 财报首发；模型公告和 TrendForce 周报补公开时间及原始时区。新闻稿、电话会、媒体转载分别建事件，只有确认同一信息才合并。
- 预期事件增加事前预告链接、一致预期和实际值；之后研究的是“超预期幅度”，而非仅判断数字好坏。
- 若逐笔权限可用，保存事件时点之前最近有效成交的价格、SIP 时间戳及成交条件，替换分钟代理，并注明逐笔口径。若只是分钟级公告时间，无法辨识同一秒内消息与成交先后，应保留这一精度限制。
- 本生成器的交易日来自已取得的行情，当前区间没有半日交易；扩展到感恩节等半日市或未来事件时，应先接入交易所日历和实际收市时间。新事件不得早于行情覆盖却被回填未来价；未完成的 C1/C3 保留待更新。
- 本轮优化前的原始文档和生成器保存在 `archive/event_study_before_skhy_2026-09-15/`，便于对照用户原有修改。
