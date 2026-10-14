# 最终报告5：策略选优与最优策略逐笔操作

[打开报告5](skhy_report5_exit_optimization.html)。报告分为两部分：

1. **策略对比与选优**：保留2026-07-31至2026-10-08的44组比较与排名，最优规则固定为E00。
2. **最优策略最新细节**：只展示E00的累计毛收益、逐笔交易、每轮选约与买卖原因、股票价格、两腿费用及盈亏。

当前交易数据更新至美东2026-10-12收盘。10月9日前沿用Massive历史；10月12日补充Yahoo Finance公开股票、Call和Put分钟行情，并与Investing.com/Barchart收盘期权链核对。明细的报价来源和原始公开数据记录见 oct12_market_provenance.json 与 public_market_data/。交易明细与原选优结果的截止日分别显示。

E00：每次1 Call＋1 Put，费用／√剩余天数选约，费用比上限12%。初始涨侧盈利150%、跌侧10%；到期周三、周四、周五分别乘75%、50%、25%。不增加强平或35%止损。平仓后继续按原规则重开；每次仅一组持仓。

## 日常刷新：不重新选参

```sh
python3 -B refresh_best_strategy.py
python3 -B verify_best_strategy.py
python3 -B build_exit_report.py
```

常规刷新程序使用Massive。当前免费权限若拒绝最近交易日，需要补齐相应公开行情后再刷新；不能将旧数据当作最新。只更新既有最优规则，结果写入 `best_strategy_latest.json`；不修改 `exit_optimization_results.json` 的原始排名。缓存位于 `market_cache/`；股票和未结束合约增量补下载，已到期历史复用。实际返回的覆盖日期会影响数据截止日。

离线复现已有最新数据：

```sh
python3 -B refresh_best_strategy.py --offline --end 2026-10-12
```

## 原始选优研究

44组＝4种涨跌止盈目标×2种止损设置×5种强平时点，加4种纯时间强平。原区间的完整结果保存在 `exit_optimization_results.json`，后续行情不参与本次选优。

只有用户明确要求重新比较参数时才运行 `optimize_rotation_exits.py`；它会覆盖原始比较结果，不属于上述日常刷新流程。历史核验程序是 `verify_exit_optimization.py`。计算及图表基础程序依赖父目录的 `rotation_backtest.py` 和 `build_rotation_report.py`。

收益统一为毛收益，含期末浮盈亏；不扣交易费用、不年化。价格采用历史成交分钟数据，不能保证实盘成交。期末估值保留两腿价格年龄。仍持仓估值不等于卖出；到期结算单独标注。原始选优为样本内比较，不保证未来最优。
