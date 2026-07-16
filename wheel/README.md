# Wheel Strategy V3 - Dual Position with Daily Monitoring

期权轮动策略回测程序，支持多标的、可配置参数，输出年化收益和完整周期列表。

## 策略逻辑

### 总资金

总资金 = 两手股票价值（2 × 100 × 入场价），初始持有一手股票 + 等值现金。

### 状态定义

| 状态 | 持仓 | 操作 |
|------|------|------|
| **State A** | 100 股 + 现金 | 卖 Put（权利金年化≈20%）+ 卖 Call（权利金年化≈5%）|
| **State B** | 200 股 | 卖 2 张 Call（权利金年化≈8% 和 ≈3%）|

> Call 行权价通过 Black-Scholes 模型搜索，使 `权利金 / 股价 × (365 / DTE) ≈ 年化目标`。

### 每日监控（仅 State A）

如果股价涨到 Call 行权价 → **Action 1**：平仓 Put 合同，按现价买入一手股票。

### 到期结算

**State A 到期：**

| 情况 | 条件 | 结果 |
|------|------|------|
| Action 1 触发 + Call 行权 | 价格 ≥ Call strike | 卖出 100 股 → State A |
| Action 1 触发 + Call 未行权 | 价格 < Call strike | 持有 200 股 → State B |
| 无 Action + Put 行权 | 价格 < Put strike | 收到 100 股 → State B |
| 无 Action + 均未行权 | Put strike ≤ 价格 < Call strike | 保持原状 → State A |

**State B 到期：**

| 情况 | 条件 | 结果 |
|------|------|------|
| 两张 Call 均行权 | 价格 ≥ 高行权价 | 卖出 200 股，买回 100 股 → State A |
| 仅低行权价 Call 行权 | 低行权价 ≤ 价格 < 高行权价 | 卖出 100 股 → State A |
| 均未行权 | 价格 < 低行权价 | 持有 200 股 → State B |

### 策略循环图

```
                    ┌──────────────────────────────────────┐
                    │          State A                      │
                    │  100 shares + cash                    │
                    │  Sell Put (20% ann.) + Call (5% ann.) │
                    └──────────┬───────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Daily Monitoring   │
                    │  Price ≥ Call K?    │
                    └──┬─────────────┬────┘
                      YES           NO
                       │             │
              ┌────────▼───┐  ┌─────▼──────┐
              │  Action 1  │  │  Wait to   │
              │  Close Put │  │  Expiry    │
              │  Buy 100sh │  └─────┬──────┘
              └────────┬───┘        │
                       │     ┌──────┼──────┐
              ┌────────▼──┐  │      │      │
              │ Expiry    │ Put   Neither  Call
              │ Call ITM? │ asign  expire  (impossible
              └──┬────┬───┘  │      │      w/o Act1)
              YES  NO       │      │
               │    │       │      │
          ┌────▼┐ ┌─▼───┐  ┌─▼──┐ ┌▼───┐
          │ St A│ │ St B│  │St B│ │St A│
          └─────┘ └────┘  └────┘ └────┘

                    ┌──────────────────────────────────────┐
                    │          State B                      │
                    │  200 shares                            │
                    │  Sell Call (8% ann.) + Call (3% ann.) │
                    └──────────┬───────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │    At Expiry        │
                    └──┬──────┬──────┬────┘
                  Both   Only   Neither
                 ITM    low ITM
                   │      │      │
              ┌────▼┐ ┌──▼──┐ ┌─▼──┐
              │ St A│ │St A │ │St B│
              └─────┘ └─────┘ └────┘
```

## 使用方法

### 基本用法

```bash
# QQQ（默认参数）
python3 wheel_strategy.py --ticker "QQQ" --data qqq_data.json --report qqq_wheel_report.html

# 腾讯
python3 wheel_strategy.py --ticker "Tencent (0700.HK)" --data tencent_data.json --report tencent_wheel_report.html

# Google
python3 wheel_strategy.py --ticker "Google (GOOGL)" --data googl_data.json --report googl_wheel_report.html
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dte` | 10 | 天数到期 |
| `--put-target` | 0.20 | Put 权利金年化收益目标（0.20 = 20%）|
| `--call-target` | 0.05 | State A Call 权利金年化目标（0.05 = 5%）|
| `--call-target1` | 0.08 | State B 第一张 Call 权利金年化目标（0.08 = 8%）|
| `--call-target2` | 0.03 | State B 第二张 Call 权利金年化目标（0.03 = 3%）|
| `--put-iv` | 0.30 | Put 隐含波动率 |
| `--call-iv` | 0.22 | Call 隐含波动率 |
| `--start` | 2026-01-01 | 回测开始日期 |
| `--end` | 2026-07-15 | 回测结束日期 |
| `--ticker` | QQQ | 标的名称（用于报告标题）|
| `--data` | qqq_data.json | 价格数据 JSON 文件 |
| `--report` | qqq_wheel_report.html | HTML 报告输出路径 |

### 示例

```bash
# 自定义参数：7天周期，25%年化Put目标，7%年化Call目标
python3 wheel_strategy.py --dte 7 --put-target 0.25 --call-target 0.07 \
    --start 2026-03-01 --end 2026-06-30 \
    --ticker "QQQ" --data qqq_data.json --report custom_report.html
```

## 数据格式

JSON 文件包含日线 OHLC 数据，格式为：

```json
[
  ["2026-01-07", 620.5, 625.0, 618.0, 622.52],
  ["2026-01-08", 622.0, 630.0, 621.0, 628.5],
  ...
]
```

每行：`[日期, 开盘价, 最高价, 最低价, 收盘价]`

数据通过 westock-data 技能获取（腾讯自选股数据源）。

## 期权定价

使用 Black-Scholes 模型定价：

- **Put 行权价**：通过二分法找到使 `权利金 / 行权价 × (365 / DTE) ≈ 年化目标` 的行权价
- **Call 行权价**：通过二分法找到使 `权利金 / 股价 × (365 / DTE) ≈ 年化目标` 的行权价
- **IV 校准**：基于 QQQ 市场报价反算（Put IV ≈ 30%，Call IV ≈ 22%），可通过参数覆盖

### Black-Scholes 公式

```
d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T

Call = S·N(d1) - K·e^(-rT)·N(d2)
Put  = K·e^(-rT)·N(-d2) - S·N(-d1)
```

其中 N() 为标准正态分布累积函数。

## 输出

程序输出两部分：

1. **控制台**：配置、结果摘要、年化收益、完整周期列表（含每周期 PnL 和状态转换）
2. **HTML 报告**：包含组合价值曲线（策略 vs Buy & Hold）、每周期权利金和 PnL 柱状图、完整周期明细表

## 回测结果（2026-01-01 ~ 2026-07-15）

| 指标 | QQQ | 腾讯 (0700.HK) | Google (GOOGL) |
|------|-----|---------------|----------------|
| **策略年化** | **+42.41%** | **-36.85%** | **+9.18%** |
| 策略总收益 | +20.09% | -21.68% | +4.65% |
| B&H 年化 | +31.64% | -39.24% | +31.76% |
| 策略最大回撤 | 1.45% | 28.64% | 11.78% |
| B&H 最大回撤 | 11.72% | 34.40% | 20.37% |
| 总权利金 | $7,416 | $3,612 | $3,016 |
| 周期数 | 18 | 19 | 18 |
| State A / B | 15 / 3 | 3 / 16 | 8 / 10 |
| Action 1 触发 | 2 | 0 | 3 |
| Put 被行权 | 0 | 2 | 1 |
| Call 被行权 | 3 | 4 | 4 |

### 结果分析

- **QQQ**：策略年化 42.4%，大幅跑赢 B&H 的 31.6%。期间触发了 2 次 Action 1 和 3 次 State B 周期，Call 行权后在高位卖出股票又买回，有效捕获了上涨趋势。最大回撤仅 1.45%。

- **腾讯**：股价大跌 23%，Put 被行权后进入 State B 长期持有两手股票。策略略跑赢 B&H（-36.9% vs -39.2%），权利金提供了小幅缓冲，但无法抵消股价下跌。最大回撤 28.6% 低于 B&H 的 34.4%。

- **Google**：策略年化 9.2%，低于 B&H 的 31.8%。经历了 3 次 Action 1 和频繁的 A/B 状态切换。State B 期间 covered call 截断了上行收益，但在下跌阶段提供了保护，最大回撤 11.8% 优于 B&H 的 20.4%。

## 文件结构

```
wheel/
├── README.md                      # 本文档
├── wheel_strategy.py              # 回测主程序（纯标准库，无外部依赖）
├── 原始策略.md                     # 策略原始描述
├── qqq_data.json                  # QQQ 日线 OHLC 数据
├── tencent_data.json              # 腾讯日线 OHLC 数据
├── googl_data.json                # Google 日线 OHLC 数据
├── qqq_wheel_report.html          # QQQ 回测报告
├── tencent_wheel_report.html      # 腾讯回测报告
├── googl_wheel_report.html        # Google 回测报告
└── archive/                       # 旧版策略文件归档
    ├── qqq_wheel_v2_old.py        # 旧版回测程序
    ├── qqq_wheel_report.html      # 旧版报告
    ├── qqq_wheel_report_dynamic.html
    ├── tencent_wheel_report.html
    └── googl_wheel_report.html
```

## 局限性

- IV 使用固定值，实际中波动率会随市场变化
- 未计入交易佣金和买卖价差（bid-ask spread）
- 每日监控使用日最高价判断是否触及行权价，实际中可能需要更精细的盘中数据
- Put/Call 行权价基于 BS 模型计算，实际市场中行权价是离散的（通常 $5 间隔）
- 历史回测不代表未来收益
