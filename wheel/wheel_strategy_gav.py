#!/usr/bin/env python3
"""
Wheel Strategy - Gav Version (Google-specific)
================================================
Based on google原始策略-gav.md

Total capital = 2 lots stock value
Initial: 1 lot stock + 1 lot cash, no loan (State A)

Each cycle (18 days, Mon -> 3rd Friday):
1. Sell put + sell call with state-specific annualized targets
2. Daily monitor: if price hits call strike -> buy 100 shares on margin (11% ann.)
   - Put is NOT closed (stays open)
3. At expiry, determine result state (B/C/D/E/A), normalize to A, then
   use the result state's targets for the NEXT cycle.

State-specific put/call annualized targets:
    State A (low volatility):  Put 50%, Call 5%
    State B (big gain):        Put 50%, Call 5%
    State C (volatile, down):  Put 20%, Call 10%
    State D (gain then back):  Put 40%, Call 5%
    State E (big drop):        Put 20%, Call 10%

All states normalize to A position (100 shares + cash, no loan) at start of next cycle.

Usage:
  python3 wheel_strategy_gav.py [options]

Options:
  --dte              Days to expiry (default: 18)
  --margin-rate      Margin financing annualized rate (default: 0.11)
  --put-iv           Put implied volatility (default: 0.30)
  --call-iv          Call implied volatility (default: 0.22)
  --start            Start date YYYY-MM-DD (default: 2026-01-01)
  --end              End date YYYY-MM-DD (default: 2026-07-15)
  --ticker           Ticker name for report (default: GOOGL)
  --data             JSON data file [date, open, high, low, close]
  --report           HTML report output path
"""

import json
import math
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ============================================================
# Black-Scholes Option Pricing
# ============================================================

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def find_put_strike(S: float, T: float, r: float, sigma: float,
                    annualized_target: float, dte: int) -> Tuple[float, float]:
    """Find put strike K such that premium / K * (365 / dte) ~= annualized_target."""
    target_ratio = annualized_target * dte / 365.0
    lo, hi = 0.01, S
    for _ in range(200):
        mid = (lo + hi) / 2.0
        put_price = bs_put(S, mid, T, r, sigma)
        target_price = mid * target_ratio
        if put_price < target_price:
            lo = mid
        else:
            hi = mid
    strike = round(mid, 2)
    premium = bs_put(S, strike, T, r, sigma)
    return strike, round(premium, 4)


def find_call_strike(S: float, T: float, r: float, sigma: float,
                     annualized_target: float, dte: int) -> Tuple[float, float]:
    """Find call strike K such that premium / S * (365 / dte) ~= annualized_target."""
    target_premium = S * annualized_target * dte / 365.0
    lo, hi = S, S * 3.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        call_price = bs_call(S, mid, T, r, sigma)
        if call_price > target_premium:
            lo = mid
        else:
            hi = mid
    strike = round(mid, 2)
    premium = bs_call(S, strike, T, r, sigma)
    return strike, round(premium, 4)


# ============================================================
# Configuration
# ============================================================

@dataclass
class Config:
    dte: int = 18
    # State-specific put/call annualized targets
    state_targets: dict = field(default_factory=lambda: {
        'A': {'put': 0.40, 'call': 0.03},
        'B': {'put': 0.40, 'call': 0.03},
        'C': {'put': 0.10, 'call': 0.10},
        'D': {'put': 0.40, 'call': 0.03},
        'E': {'put': 0.10, 'call': 0.10},
    })
    put_iv: float = 0.30
    call_iv: float = 0.22
    dynamic_iv: bool = False               # True: use realized vol (from real prices) as IV
    iv_rv_window: int = 21                 # rolling window (trading days) for realized vol
    iv_vrp: float = 1.0                    # vol risk premium multiplier on realized vol (IV = RV * vrp)
    margin_rate: float = 0.11              # 11% annualized margin financing cost
    start_date: str = '2026-01-01'
    end_date: str = '2026-07-15'
    r: float = 0.05
    contract_size: int = 100
    ticker: str = 'GOOGL'
    data_file: str = 'googl_data.json'
    report_file: str = 'googl_wheel_report.html'


# ============================================================
# Data Structures
# ============================================================

@dataclass
class Cycle:
    cycle_num: int
    entry_date: str
    entry_price: float
    put_strike: float
    call_strike: float
    put_premium: float
    call_premium: float
    total_premium: float
    # Action 1
    action1_triggered: bool
    action1_date: str
    action1_price: float
    # Margin
    margin_loan: float
    margin_interest: float
    # Expiry
    expiry_date: str
    expiry_price: float
    result_state: str          # A/B/C/D/E (before normalization)
    outcome: str
    normalization: str
    # Results
    cycle_pnl: float
    stock_pnl: float             # cycle_pnl - total_premium + margin_interest
    portfolio_value: float
    buy_hold_value: float
    cash: float
    shares: int
    # State-specific targets used this cycle
    put_target_used: float
    call_target_used: float
    prev_state: str              # state that determined this cycle's targets


@dataclass
class BacktestResult:
    config: Config
    cycles: List[Cycle]
    initial_capital: float
    final_value: float
    total_premium: float
    total_margin_interest: float
    total_stock_gains: float          # sum of positive stock_pnl
    total_stock_losses: float         # sum of negative stock_pnl (absolute)
    total_return_pct: float
    annualized_return_pct: float
    num_cycles: int
    num_action1: int
    state_counts: dict
    max_drawdown_pct: float
    buy_hold_return_pct: float
    buy_hold_annualized_pct: float
    buy_hold_max_drawdown_pct: float
    backtest_days: int
    put_iv: float
    call_iv: float


# ============================================================
# Data Loading
# ============================================================

def load_data(filepath: str, start_date: str, end_date: str) -> List[Tuple]:
    with open(filepath, 'r') as f:
        raw = json.load(f)
    data = []
    for row in raw:
        date_str = row[0]
        if start_date <= date_str <= end_date:
            data.append((row[0], row[1], row[2], row[3], row[4]))
    data.sort(key=lambda x: x[0])
    return data


# ============================================================
# Trading Day Utilities
# ============================================================

def find_expiry_index(entry_idx: int, dates: List[str], dte: int) -> int:
    entry_date = datetime.strptime(dates[entry_idx], '%Y-%m-%d')
    target = entry_date + timedelta(days=dte)
    target_str = target.strftime('%Y-%m-%d')
    for i in range(entry_idx + 1, len(dates)):
        if dates[i] >= target_str:
            return i
    return len(dates) - 1


def compute_realized_volatility(closes: List[float], idx: int, window: int = 21) -> Optional[float]:
    """Annualized realized volatility from real log returns over `window` days ending at idx."""
    start = max(0, idx - window + 1)
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(start + 1, idx + 1)]
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    if var <= 0:
        return None
    return math.sqrt(var) * math.sqrt(252.0)  # annualized


# ============================================================
# Strategy Simulation
# ============================================================

def simulate(config: Config) -> BacktestResult:
    """Run the Gav wheel strategy backtest."""

    data = load_data(config.data_file, config.start_date, config.end_date)
    if len(data) < 2:
        raise ValueError(f"Not enough data: only {len(data)} days")

    dates = [d[0] for d in data]
    opens = [d[1] for d in data]
    highs = [d[2] for d in data]
    lows = [d[3] for d in data]
    closes = [d[4] for d in data]

    # Precompute realized volatility series (for dynamic IV mode)
    rv_series: List[Optional[float]] = []
    if config.dynamic_iv:
        for i in range(len(closes)):
            rv_series.append(compute_realized_volatility(closes, i, config.iv_rv_window))

    CS = config.contract_size  # 100

    # Initial: 2 lots capital, hold 1 lot stock + 1 lot cash
    S0 = closes[0]
    initial_capital = 2 * CS * S0
    shares = CS           # 100 shares
    cash = CS * S0        # cash = 100 * S0
    # No margin loan initially

    cycles: List[Cycle] = []
    portfolio_values: List[float] = []
    stock_gains_list: List[float] = []
    stock_losses_list: List[float] = []
    put_ivs_used: List[float] = []
    call_ivs_used: List[float] = []

    cycle_num = 0
    idx = 0
    prev_state = 'A'  # start in State A

    while idx < len(dates) - 1:
        entry_idx = idx
        entry_date = dates[entry_idx]
        entry_price = closes[entry_idx]

        expiry_idx = find_expiry_index(entry_idx, dates, config.dte)
        expiry_date = dates[expiry_idx]
        expiry_price = closes[expiry_idx]

        actual_dte = (datetime.strptime(expiry_date, '%Y-%m-%d') -
                      datetime.strptime(entry_date, '%Y-%m-%d')).days
        T = actual_dte / 365.0

        if T <= 0:
            idx = expiry_idx + 1 if expiry_idx + 1 < len(dates) else expiry_idx
            if idx <= entry_idx:
                break
            continue

        # Portfolio value before this cycle
        portfolio_before = cash + shares * entry_price

        # ---- State-specific targets based on previous cycle's result ----
        targets = config.state_targets[prev_state]
        put_target = targets['put']
        call_target = targets['call']

        # ---- IV: dynamic (realized vol from real prices) or fixed ----
        if config.dynamic_iv and entry_idx < len(rv_series):
            rv = rv_series[entry_idx]
            if rv is not None:
                base_iv = rv * config.iv_vrp
                put_iv = min(base_iv, 2.0)
                call_iv = min(base_iv, 2.0)
            else:
                put_iv, call_iv = config.put_iv, config.call_iv
        else:
            put_iv, call_iv = config.put_iv, config.call_iv
        put_ivs_used.append(put_iv)
        call_ivs_used.append(call_iv)

        put_strike, put_prem = find_put_strike(
            entry_price, T, config.r, put_iv,
            put_target, actual_dte
        )
        call_strike, call_prem = find_call_strike(
            entry_price, T, config.r, call_iv,
            call_target, actual_dte
        )

        put_prem = round(put_prem, 4)
        call_prem = round(call_prem, 4)

        total_prem = (put_prem + call_prem) * CS
        cash += total_prem

        # ---- Daily monitoring: Action 1 ----
        # If price hits call strike -> buy 100 shares on margin
        # Put is NOT closed
        action1_triggered = False
        action1_date = ''
        action1_price = 0.0
        margin_loan = 0.0
        margin_interest = 0.0

        for day_idx in range(entry_idx + 1, expiry_idx + 1):
            if highs[day_idx] >= call_strike:
                action1_triggered = True
                action1_date = dates[day_idx]
                action1_price = call_strike

                # Buy 100 shares on margin (borrow at margin_rate)
                margin_loan = call_strike * CS
                shares += CS  # now 200 shares
                # Put stays open!
                break

        # Calculate margin interest
        if action1_triggered:
            days_holding = (datetime.strptime(expiry_date, '%Y-%m-%d') -
                            datetime.strptime(action1_date, '%Y-%m-%d')).days
            margin_interest = margin_loan * config.margin_rate * (days_holding / 365.0)

        # ---- Determine outcome at expiry ----
        call_exercised = expiry_price >= call_strike
        put_exercised = expiry_price < put_strike

        if action1_triggered:
            if call_exercised:
                # State B: call exercised
                # Sell 100 at call strike
                cash += call_strike * CS
                shares -= CS  # back to 100
                result_state = 'B'
                # Normalize: pay off loan + interest
                cash -= margin_loan + margin_interest
                normalization = f'State B -> A: paid off loan ${margin_loan:,.0f} + interest ${margin_interest:,.0f}'
                outcome = (f'Action1 on {action1_date} @ ${action1_price:.2f}; '
                           f'Call assigned: sold {CS} @ ${call_strike}; '
                           f'Put expired. Normalized: paid off loan')

            elif put_exercised:
                # State C: put exercised (price went up then crashed below put strike)
                # Buy 100 at put strike
                cash -= put_strike * CS
                shares += CS  # now 300
                result_state = 'C'
                # Normalize: sell 200 shares at expiry, pay off loan
                cash += 2 * expiry_price * CS - margin_loan - margin_interest
                shares -= 2 * CS  # back to 100
                normalization = (f'State C -> A: sold 200 @ ${expiry_price:.2f} '
                                 f'(${2*expiry_price*CS:,.0f}), paid off loan ${margin_loan:,.0f} '
                                 f'+ interest ${margin_interest:,.0f}')
                outcome = (f'Action1 on {action1_date} @ ${action1_price:.2f}; '
                           f'Put assigned: bought {CS} @ ${put_strike}; '
                           f'Call expired. Normalized: sold 200, paid off loan')

            else:
                # State D: neither exercised
                result_state = 'D'
                # Normalize: sell 100 shares at expiry, pay off loan
                cash += expiry_price * CS - margin_loan - margin_interest
                shares -= CS  # back to 100
                normalization = (f'State D -> A: sold 100 @ ${expiry_price:.2f} '
                                 f'(${expiry_price*CS:,.0f}), paid off loan ${margin_loan:,.0f} '
                                 f'+ interest ${margin_interest:,.0f}')
                outcome = (f'Action1 on {action1_date} @ ${action1_price:.2f}; '
                           f'Both expired. Normalized: sold 100, paid off loan')

        else:
            # No Action 1 triggered
            if put_exercised:
                # State E: put exercised
                cash -= put_strike * CS
                shares += CS  # now 200
                result_state = 'E'
                # Normalize: sell 100 shares at expiry
                cash += expiry_price * CS
                shares -= CS  # back to 100
                normalization = f'State E -> A: sold 100 @ ${expiry_price:.2f} (${expiry_price*CS:,.0f})'
                outcome = (f'Put assigned: bought {CS} @ ${put_strike}; '
                           f'Call expired. Normalized: sold 100')

            elif call_exercised:
                # Edge case: call ITM at expiry without Action 1 (shouldn't happen)
                # Sell 100 at call strike, rebuy at market -> State A
                cash += call_strike * CS
                shares -= CS  # 0
                cash -= expiry_price * CS
                shares += CS  # back to 100
                result_state = 'A'
                normalization = 'State A (call assigned, rebought)'
                outcome = (f'Call assigned: sold {CS} @ ${call_strike}, '
                           f'rebought @ ${expiry_price:.2f}; Put expired')

            else:
                # State A: neither exercised
                result_state = 'A'
                normalization = 'State A (no change)'
                outcome = 'Both put and call expired worthless'

        # Portfolio value after this cycle (after normalization, no loan)
        portfolio_after = cash + shares * expiry_price
        cycle_pnl = portfolio_after - portfolio_before
        stock_pnl = cycle_pnl - total_prem + margin_interest  # stock-related P&L (excl premium & financing)
        portfolio_values.append(portfolio_after)

        if stock_pnl >= 0:
            stock_gains_list.append(stock_pnl)
            stock_losses_list.append(0.0)
        else:
            stock_gains_list.append(0.0)
            stock_losses_list.append(abs(stock_pnl))

        # Buy & Hold: invest all initial capital in stock, hold 200 shares
        buy_hold_val = initial_capital * (expiry_price / S0)

        cycle_num += 1
        cycles.append(Cycle(
            cycle_num=cycle_num,
            entry_date=entry_date,
            entry_price=round(entry_price, 2),
            put_strike=put_strike,
            call_strike=call_strike,
            put_premium=put_prem,
            call_premium=call_prem,
            total_premium=round(total_prem, 2),
            action1_triggered=action1_triggered,
            action1_date=action1_date,
            action1_price=round(action1_price, 2),
            margin_loan=round(margin_loan, 2),
            margin_interest=round(margin_interest, 2),
            expiry_date=expiry_date,
            expiry_price=round(expiry_price, 2),
            result_state=result_state,
            outcome=outcome,
            normalization=normalization,
            cycle_pnl=round(cycle_pnl, 2),
            stock_pnl=round(stock_pnl, 2),
            portfolio_value=round(portfolio_after, 2),
            buy_hold_value=round(buy_hold_val, 2),
            cash=round(cash, 2),
            shares=shares,
            put_target_used=put_target,
            call_target_used=call_target,
            prev_state=prev_state
        ))

        # Update prev_state for next cycle
        prev_state = result_state

        idx = expiry_idx
        if idx >= len(dates) - 1:
            break

    # Final valuation
    last_price = closes[-1]
    final_value = cash + shares * last_price

    # Statistics
    total_premium = sum(c.total_premium for c in cycles)
    total_margin_interest = sum(c.margin_interest for c in cycles)
    total_stock_gains = sum(stock_gains_list)
    total_stock_losses = sum(stock_losses_list)
    total_return = (final_value - initial_capital) / initial_capital
    backtest_days = (datetime.strptime(dates[-1], '%Y-%m-%d') -
                     datetime.strptime(dates[0], '%Y-%m-%d')).days
    annualized = (1 + total_return) ** (365.0 / backtest_days) - 1 if backtest_days > 0 else 0

    # Buy & hold
    buy_hold_return = (closes[-1] - S0) / S0
    buy_hold_annualized = (1 + buy_hold_return) ** (365.0 / backtest_days) - 1 if backtest_days > 0 else 0

    # Max drawdown (strategy)
    max_dd = 0.0
    peak = portfolio_values[0] if portfolio_values else initial_capital
    for pv in portfolio_values:
        if pv > peak:
            peak = pv
        dd = (peak - pv) / peak
        if dd > max_dd:
            max_dd = dd

    # Buy & Hold max drawdown (daily)
    bh_daily = [initial_capital * (c / S0) for c in closes]
    bh_max_dd = 0.0
    bh_peak = bh_daily[0] if bh_daily else initial_capital
    for bv in bh_daily:
        if bv > bh_peak:
            bh_peak = bv
        dd = (bh_peak - bv) / bh_peak
        if dd > bh_max_dd:
            bh_max_dd = dd

    # State counts
    state_counts = {}
    for c in cycles:
        state_counts[c.result_state] = state_counts.get(c.result_state, 0) + 1

    num_action1 = sum(1 for c in cycles if c.action1_triggered)

    return BacktestResult(
        config=config,
        cycles=cycles,
        initial_capital=round(initial_capital, 2),
        final_value=round(final_value, 2),
        total_premium=round(total_premium, 2),
        total_margin_interest=round(total_margin_interest, 2),
        total_stock_gains=round(total_stock_gains, 2),
        total_stock_losses=round(total_stock_losses, 2),
        total_return_pct=round(total_return * 100, 2),
        annualized_return_pct=round(annualized * 100, 2),
        num_cycles=len(cycles),
        num_action1=num_action1,
        state_counts=state_counts,
        max_drawdown_pct=round(max_dd * 100, 2),
        buy_hold_return_pct=round(buy_hold_return * 100, 2),
        buy_hold_annualized_pct=round(buy_hold_annualized * 100, 2),
        buy_hold_max_drawdown_pct=round(bh_max_dd * 100, 2),
        backtest_days=backtest_days,
        put_iv=round((sum(put_ivs_used) / len(put_ivs_used)) * 100, 2) if put_ivs_used else round(config.put_iv * 100, 2),
        call_iv=round((sum(call_ivs_used) / len(call_ivs_used)) * 100, 2) if call_ivs_used else round(config.call_iv * 100, 2)
    )


# ============================================================
# Console Output
# ============================================================

def print_result(result: BacktestResult):
    cfg = result.config

    print("=" * 100)
    print(f"  {cfg.ticker} WHEEL STRATEGY - GAV VERSION")
    print("=" * 100)

    print(f"\n  Configuration:")
    print(f"    DTE                    : {cfg.dte} days")
    print(f"    Margin rate            : {cfg.margin_rate*100:.0f}%")
    print(f"    Period                 : {cfg.start_date} -> {cfg.end_date}")
    print(f"    Put IV                 : {result.put_iv}%")
    print(f"    Call IV                : {result.call_iv}%")
    print(f"    Risk-free rate         : {cfg.r*100:.1f}%")
    print(f"    State targets (Put/Call ann.):")
    for st in ['A', 'B', 'C', 'D', 'E']:
        t = cfg.state_targets[st]
        print(f"      State {st}              : {t['put']*100:.0f}% / {t['call']*100:.0f}%")

    print(f"\n  Results:")
    print(f"    Initial capital        : ${result.initial_capital:,.2f}")
    print(f"    Final value            : ${result.final_value:,.2f}")
    print(f"    Total return           : {result.total_return_pct:.2f}%")
    print(f"    Annualized return      : {result.annualized_return_pct:.2f}%")
    print(f"    Backtest days          : {result.backtest_days}")
    print(f"    Max drawdown           : {result.max_drawdown_pct:.2f}%")
    print(f"    Buy & Hold return      : {result.buy_hold_return_pct:.2f}%")
    print(f"    Buy & Hold annualized  : {result.buy_hold_annualized_pct:.2f}%")
    print(f"    B&H max drawdown       : {result.buy_hold_max_drawdown_pct:.2f}%")

    print(f"\n  Income & Cost Summary:")
    print(f"    --- Income ---")
    print(f"    Premium income         : ${result.total_premium:,.2f}")
    print(f"    Stock gains            : ${result.total_stock_gains:,.2f}")
    print(f"    Total income           : ${result.total_premium + result.total_stock_gains:,.2f}")
    print(f"    --- Cost ---")
    print(f"    Stock losses           : ${result.total_stock_losses:,.2f}")
    print(f"    Financing cost         : ${result.total_margin_interest:,.2f}")
    print(f"    Total cost             : ${result.total_stock_losses + result.total_margin_interest:,.2f}")
    print(f"    --- Net ---")
    print(f"    Net P&L                : ${result.final_value - result.initial_capital:,.2f}")

    print(f"\n  Cycle Summary:")
    print(f"    Total cycles           : {result.num_cycles}")
    print(f"    Action 1 triggered     : {result.num_action1}")
    state_str = ' / '.join(f'{k}:{v}' for k, v in sorted(result.state_counts.items()))
    print(f"    Result states          : {state_str}")

    print(f"\n  {'#' * 96}")
    print(f"  ANNUALIZED RETURN: {result.annualized_return_pct:.2f}%")
    print(f"  {'#' * 96}")

    # Cycle table
    print(f"\n  Cycle List:")
    hdr = (f"  {'#':>3} {'Entry':>12} {'Price':>8} {'PutK':>7} {'CallK':>7} "
           f"{'Prem':>7} {'Act1':>4} {'Margin':>8} {'Expiry':>12} {'ExpPx':>8} "
           f"{'St':>2} {'PnL':>10} {'Value':>12} {'B&H':>12}")
    print(hdr)
    print(f"  {'-'*3} {'-'*12} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*8} {'-'*12} {'-'*8} {'-'*2} {'-'*10} {'-'*12} {'-'*12}")

    for c in result.cycles:
        act1 = 'YES' if c.action1_triggered else ''
        margin_str = f"${c.margin_loan + c.margin_interest:,.0f}" if c.margin_loan > 0 else '-'
        pnl_str = f"${c.cycle_pnl:+,.0f}"
        val_str = f"${c.portfolio_value:,.0f}"
        bh_str = f"${c.buy_hold_value:,.0f}"
        print(f"  {c.cycle_num:>3} {c.entry_date:>12} {c.entry_price:>8.2f} "
              f"{c.put_strike:>7} {c.call_strike:>7} {c.total_premium:>7.0f} "
              f"{act1:>4} {margin_str:>8} {c.expiry_date:>12} {c.expiry_price:>8.2f} "
              f"{c.result_state:>2} {pnl_str:>10} {val_str:>12} {bh_str:>12}")

    # Outcomes
    print(f"\n  Outcomes:")
    for c in result.cycles:
        print(f"  #{c.cycle_num:>3} [{c.result_state}] {c.outcome}")
        if c.normalization and c.normalization != 'State A (no change)':
            print(f"         {c.normalization}")

    print()


# ============================================================
# HTML Report
# ============================================================

def generate_html(result: BacktestResult, output_path: str):
    cfg = result.config
    ticker = cfg.ticker

    labels = [c.expiry_date for c in result.cycles]
    portfolio_values = [c.portfolio_value for c in result.cycles]
    buy_hold_values = [c.buy_hold_value for c in result.cycles]
    stock_prices = [c.expiry_price for c in result.cycles]
    premiums = [c.total_premium for c in result.cycles]
    pnls = [c.cycle_pnl for c in result.cycles]
    margin_interests = [c.margin_interest for c in result.cycles]
    result_states = [c.result_state for c in result.cycles]

    # State colors for portfolio chart points
    state_colors_map = {'A': '#667eea', 'B': '#27ae60', 'C': '#e74c3c', 'D': '#f39c12', 'E': '#e67e22'}
    state_desc_map = {
        'A': 'Neither exercised',
        'B': 'Call assigned (after Act1)',
        'C': 'Put assigned (after Act1)',
        'D': 'Both expired (after Act1)',
        'E': 'Put assigned (no Act1)'
    }
    point_colors = [state_colors_map.get(s, '#667eea') for s in result_states]

    # Cycle table rows
    table_rows = []
    for c in result.cycles:
        pnl_class = 'profit' if c.cycle_pnl >= 0 else 'loss'
        state_class = f'state-{c.result_state.lower()}'
        prev_class = f'state-{c.prev_state.lower()}'
        act1_html = '<span class="badge badge-action">ACT1</span>' if c.action1_triggered else ''

        # Financing cost = margin interest only (not loan principal)
        if c.margin_interest > 0:
            financing_str = f'${c.margin_interest:,.0f}<br><span class="prem-detail">loan: ${c.margin_loan:,.0f}</span>'
        else:
            financing_str = '-'

        prem_detail = f'P:{c.put_premium:.2f} / C:{c.call_premium:.2f}'
        tgt_detail = f'P:{c.put_target_used*100:.0f}% / C:{c.call_target_used*100:.0f}%'

        # State badge with description
        state_desc_map = {
            'A': 'Neither exercised',
            'B': 'Call assigned (Act1)',
            'C': 'Put assigned (Act1)',
            'D': 'Both expired (Act1)',
            'E': 'Put assigned (no Act1)'
        }
        state_badge = (f'<span class="badge-state {c.result_state.lower()}" '
                        f'title="{state_desc_map.get(c.result_state, "")}">{c.result_state}</span>'
                        f'<br><span class="prem-detail">{state_desc_map.get(c.result_state, "")}</span>')

        prev_badge = (f'<span class="badge-state {c.prev_state.lower()}" '
                      f'title="Targets: {tgt_detail}">{c.prev_state}</span>'
                      f'<br><span class="prem-detail">{tgt_detail}</span>')

        table_rows.append(f"""
            <tr>
                <td>{c.cycle_num}</td>
                <td>{c.entry_date}</td>
                <td>${c.entry_price:.2f}</td>
                <td>${c.put_strike}<br><span class="prem-detail">{c.put_target_used*100:.0f}% tgt</span></td>
                <td>${c.call_strike}<br><span class="prem-detail">{c.call_target_used*100:.0f}% tgt</span></td>
                <td>${c.total_premium:,.0f}<br><span class="prem-detail">{prem_detail}</span></td>
                <td>{act1_html}</td>
                <td>{financing_str}</td>
                <td>{c.expiry_date}</td>
                <td>${c.expiry_price:.2f}</td>
                <td class="{prev_class}">{prev_badge}</td>
                <td class="{state_class}">{state_badge}</td>
                <td class="{pnl_class}">${c.cycle_pnl:+,.0f}</td>
                <td>${c.portfolio_value:,.0f}</td>
                <td>${c.buy_hold_value:,.0f}</td>
                <td>{c.shares}</td>
                <td class="note">{c.outcome}</td>
            </tr>""")

    table_rows_html = '\n'.join(table_rows)

    # State distribution string
    state_dist = ' / '.join(f'{k}:{v}' for k, v in sorted(result.state_counts.items()))

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} Wheel Strategy - Gav Version</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #1a1a2e; line-height: 1.6; }}
.container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}
h1 {{ text-align: center; font-size: 28px; margin: 20px 0 5px; color: #1a1a2e; }}
.subtitle {{ text-align: center; color: #666; margin-bottom: 30px; font-size: 14px; }}

.summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
.card {{ background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.card-label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
.card-value {{ font-size: 24px; font-weight: 700; }}
.card-value.profit {{ color: #27ae60; }}
.card-value.loss {{ color: #c0392b; }}
.card-value.neutral {{ color: #2c3e50; }}
.card-sub {{ font-size: 12px; color: #aaa; margin-top: 4px; }}

.highlight-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 16px; padding: 30px; text-align: center; margin-bottom: 30px; color: white; }}
.highlight-box .label {{ font-size: 14px; opacity: 0.9; text-transform: uppercase; letter-spacing: 1px; }}
.highlight-box .value {{ font-size: 48px; font-weight: 800; margin: 10px 0; }}
.highlight-box .detail {{ font-size: 14px; opacity: 0.8; }}

.config-box {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.config-box h3 {{ font-size: 16px; margin-bottom: 12px; color: #555; }}
.config-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
.config-item {{ display: flex; justify-content: space-between; padding: 6px 12px; background: #f8f9fa; border-radius: 6px; font-size: 13px; }}
.config-item span:first-child {{ color: #888; }}
.config-item span:last-child {{ font-weight: 600; }}

.chart-container {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.chart-container h3 {{ font-size: 16px; margin-bottom: 16px; color: #333; }}
.chart-wrapper {{ position: relative; height: 400px; }}

table {{ width: 100%; border-collapse: collapse; font-size: 12px; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
thead {{ background: #2c3e50; color: white; }}
th {{ padding: 12px 6px; text-align: center; font-weight: 600; white-space: nowrap; }}
td {{ padding: 8px 6px; text-align: center; border-bottom: 1px solid #eee; white-space: nowrap; }}
tr:hover {{ background: #f8f9fa; }}
td.state-a {{ color: #667eea; font-weight: 700; }}
td.state-b {{ color: #27ae60; font-weight: 700; }}
td.state-c {{ color: #e74c3c; font-weight: 700; }}
td.state-d {{ color: #f39c12; font-weight: 700; }}
td.state-e {{ color: #e67e22; font-weight: 700; }}
td.profit {{ color: #27ae60; font-weight: 600; }}
td.loss {{ color: #c0392b; font-weight: 600; }}
td.note {{ text-align: left; color: #666; font-size: 11px; max-width: 350px; }}
.prem-detail {{ font-size: 10px; color: #999; }}
.badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }}
.badge-action {{ background: #e74c3c; color: white; }}
.badge-state {{ display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; color: white; }}
.badge-state.a {{ background: #667eea; }}
.badge-state.b {{ background: #27ae60; }}
.badge-state.c {{ background: #e74c3c; }}
.badge-state.d {{ background: #f39c12; }}
.badge-state.e {{ background: #e67e22; }}

.state-legend {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }}
.state-legend-item {{ display: flex; align-items: center; gap: 4px; font-size: 12px; color: #666; }}
.state-legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

.chart-wrapper-dual {{ position: relative; height: 480px; }}

.section-title {{ font-size: 20px; font-weight: 700; margin: 30px 0 15px; color: #2c3e50; }}

.strategy-box {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.strategy-box h3 {{ font-size: 16px; margin-bottom: 12px; color: #555; }}
.strategy-box ul {{ margin-left: 20px; font-size: 13px; color: #444; }}
.strategy-box li {{ margin-bottom: 6px; }}

.income-cost-section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.income-cost-section h3 {{ font-size: 16px; margin-bottom: 16px; color: #333; }}
.income-cost-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }}
.ic-column {{ border-radius: 8px; padding: 16px; }}
.ic-column.income {{ background: #eafaf1; }}
.ic-column.cost {{ background: #fdedec; }}
.ic-column.net {{ background: #f4f6f9; }}
.ic-header {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #555; }}
.ic-row {{ display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid rgba(0,0,0,0.05); }}
.ic-row:last-child {{ border-bottom: none; }}
.ic-row.ic-total {{ font-weight: 700; border-top: 2px solid rgba(0,0,0,0.1); padding-top: 10px; margin-top: 4px; }}
.ic-value {{ font-weight: 600; }}
.ic-value.profit {{ color: #27ae60; }}
.ic-value.loss {{ color: #c0392b; }}

.state-targets-table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }}
.state-targets-table th {{ padding: 6px 10px; text-align: center; background: #f8f9fa; color: #555; font-weight: 600; }}
.state-targets-table td {{ padding: 6px 10px; text-align: center; border-bottom: 1px solid #eee; }}
.state-targets-table td.state-label {{ font-weight: 700; }}
</style>
</head>
<body>
<div class="container">
    <h1>{ticker} Wheel Strategy - Gav Version</h1>
    <p class="subtitle">1 lot stock + cash | State-specific Put/Call targets | Margin {cfg.margin_rate*100:.0f}% | All states normalize to A | {cfg.dte}-day DTE</p>

    <div class="highlight-box">
        <div class="label">Annualized Return</div>
        <div class="value">{result.annualized_return_pct:+.2f}%</div>
        <div class="detail">
            Total: {result.total_return_pct:+.2f}% over {result.backtest_days} days |
            ${result.initial_capital:,.0f} -> ${result.final_value:,.0f} |
            vs B&H: {result.buy_hold_annualized_pct:+.2f}% annualized
        </div>
    </div>

    <div class="summary-grid">
        <div class="card">
            <div class="card-label">Total Return</div>
            <div class="card-value {('profit' if result.total_return_pct >= 0 else 'loss')}">{result.total_return_pct:+.2f}%</div>
            <div class="card-sub">${result.final_value - result.initial_capital:+,.0f} P&L</div>
        </div>
        <div class="card">
            <div class="card-label">Max Drawdown</div>
            <div class="card-value loss">{result.max_drawdown_pct:.2f}%</div>
            <div class="card-sub">B&H: {result.buy_hold_max_drawdown_pct:.2f}%</div>
        </div>
        <div class="card">
            <div class="card-label">B&H Return</div>
            <div class="card-value neutral">{result.buy_hold_return_pct:+.2f}%</div>
            <div class="card-sub">Ann: {result.buy_hold_annualized_pct:+.2f}%</div>
        </div>
        <div class="card">
            <div class="card-label">Action 1 / States</div>
            <div class="card-value neutral">{result.num_action1}</div>
            <div class="card-sub">{state_dist}</div>
        </div>
    </div>

    <div class="income-cost-section">
        <h3>Income &amp; Cost Summary</h3>
        <div class="income-cost-grid">
            <div class="ic-column income">
                <div class="ic-header">Income</div>
                <div class="ic-row"><span>Premium income</span><span class="ic-value profit">${result.total_premium:,.0f}</span></div>
                <div class="ic-row"><span>Stock gains</span><span class="ic-value profit">${result.total_stock_gains:,.0f}</span></div>
                <div class="ic-row ic-total"><span>Total income</span><span class="ic-value profit">${result.total_premium + result.total_stock_gains:,.0f}</span></div>
            </div>
            <div class="ic-column cost">
                <div class="ic-header">Cost</div>
                <div class="ic-row"><span>Stock losses</span><span class="ic-value loss">${result.total_stock_losses:,.0f}</span></div>
                <div class="ic-row"><span>Financing cost</span><span class="ic-value loss">${result.total_margin_interest:,.0f}</span></div>
                <div class="ic-row ic-total"><span>Total cost</span><span class="ic-value loss">${result.total_stock_losses + result.total_margin_interest:,.0f}</span></div>
            </div>
            <div class="ic-column net">
                <div class="ic-header">Net P&amp;L</div>
                <div class="ic-row ic-total"><span>Net</span><span class="ic-value {('profit' if result.final_value >= result.initial_capital else 'loss')}">${result.final_value - result.initial_capital:+,.0f}</span></div>
                <div class="ic-row"><span>Return</span><span class="ic-value {('profit' if result.total_return_pct >= 0 else 'loss')}">{result.total_return_pct:+.2f}%</span></div>
            </div>
        </div>
    </div>

    <div class="strategy-box">
        <h3>Strategy Logic (Gav Version)</h3>
        <ul>
            <li><b>Initial</b>: 100 shares + cash (State A), 2 lots total capital</li>
            <li><b>Daily Monitor</b>: If price hits call strike -> buy 100 shares on margin ({cfg.margin_rate*100:.0f}% ann.). Put stays open.</li>
            <li><b>State B</b> (call exercised after Act1): pay off loan -> A. Next: Put {cfg.state_targets['B']['put']*100:.0f}% / Call {cfg.state_targets['B']['call']*100:.0f}%</li>
            <li><b>State C</b> (put exercised after Act1): sell 200, pay off loan -> A. Next: Put {cfg.state_targets['C']['put']*100:.0f}% / Call {cfg.state_targets['C']['call']*100:.0f}%</li>
            <li><b>State D</b> (neither after Act1): sell 100, pay off loan -> A. Next: Put {cfg.state_targets['D']['put']*100:.0f}% / Call {cfg.state_targets['D']['call']*100:.0f}%</li>
            <li><b>State E</b> (put exercised, no Act1): sell 100 -> A. Next: Put {cfg.state_targets['E']['put']*100:.0f}% / Call {cfg.state_targets['E']['call']*100:.0f}%</li>
            <li><b>State A</b> (neither exercised): stays A. Next: Put {cfg.state_targets['A']['put']*100:.0f}% / Call {cfg.state_targets['A']['call']*100:.0f}%</li>
            <li><b>Cycle</b>: {cfg.dte} days to expiry, all states normalize to A position</li>
        </ul>
    </div>

    <div class="config-box">
        <h3>State-Specific Targets (Annualized)</h3>
        <table class="state-targets-table">
            <thead>
                <tr>
                    <th>State</th>
                    <th>Description</th>
                    <th>Put Target</th>
                    <th>Call Target</th>
                </tr>
            </thead>
            <tbody>
                <tr><td class="state-label state-a">A</td><td>Low volatility</td><td>{cfg.state_targets['A']['put']*100:.0f}%</td><td>{cfg.state_targets['A']['call']*100:.0f}%</td></tr>
                <tr><td class="state-label state-b">B</td><td>Big gain (call assigned)</td><td>{cfg.state_targets['B']['put']*100:.0f}%</td><td>{cfg.state_targets['B']['call']*100:.0f}%</td></tr>
                <tr><td class="state-label state-c">C</td><td>Volatile, ended down</td><td>{cfg.state_targets['C']['put']*100:.0f}%</td><td>{cfg.state_targets['C']['call']*100:.0f}%</td></tr>
                <tr><td class="state-label state-d">D</td><td>Gain then pullback</td><td>{cfg.state_targets['D']['put']*100:.0f}%</td><td>{cfg.state_targets['D']['call']*100:.0f}%</td></tr>
                <tr><td class="state-label state-e">E</td><td>Big drop</td><td>{cfg.state_targets['E']['put']*100:.0f}%</td><td>{cfg.state_targets['E']['call']*100:.0f}%</td></tr>
            </tbody>
        </table>
    </div>

    <div class="config-box">
        <h3>Configuration</h3>
        <div class="config-grid">
            <div class="config-item"><span>DTE</span><span>{cfg.dte} days</span></div>
            <div class="config-item"><span>Margin Rate</span><span>{cfg.margin_rate*100:.0f}%</span></div>
            <div class="config-item"><span>Start</span><span>{cfg.start_date}</span></div>
            <div class="config-item"><span>End</span><span>{cfg.end_date}</span></div>
            <div class="config-item"><span>Put IV</span><span>{result.put_iv}%</span></div>
            <div class="config-item"><span>Call IV</span><span>{result.call_iv}%</span></div>
            <div class="config-item"><span>Risk-free Rate</span><span>{cfg.r*100:.1f}%</span></div>
            <div class="config-item"><span>Cycles</span><span>{result.num_cycles}</span></div>
        </div>
    </div>

    <div class="chart-container">
        <h3>Portfolio Value: Strategy vs Buy &amp; Hold vs Stock Price</h3>
        <div class="state-legend">
            <div class="state-legend-item"><div class="state-legend-dot" style="background:#667eea"></div>A - Neither exercised</div>
            <div class="state-legend-item"><div class="state-legend-dot" style="background:#27ae60"></div>B - Call assigned (Act1)</div>
            <div class="state-legend-item"><div class="state-legend-dot" style="background:#e74c3c"></div>C - Put assigned (Act1)</div>
            <div class="state-legend-item"><div class="state-legend-dot" style="background:#f39c12"></div>D - Both expired (Act1)</div>
            <div class="state-legend-item"><div class="state-legend-dot" style="background:#e67e22"></div>E - Put assigned (no Act1)</div>
        </div>
        <div class="chart-wrapper-dual">
            <canvas id="portfolioChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h3>Per-Cycle Premium, PnL & Financing Cost</h3>
        <div class="chart-wrapper">
            <canvas id="premiumChart"></canvas>
        </div>
    </div>

    <div class="section-title">Cycle List ({result.num_cycles} cycles)</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Entry Date</th>
                <th>Entry Price</th>
                <th>Put Strike</th>
                <th>Call Strike</th>
                <th>Premium</th>
                <th>Act1</th>
                <th>Financing</th>
                <th>Expiry Date</th>
                <th>Expiry Price</th>
                <th>From</th>
                <th>End State</th>
                <th>Cycle PnL</th>
                <th>Strategy Value</th>
                <th>B&H Value</th>
                <th>Shares</th>
                <th>Outcome</th>
            </tr>
        </thead>
        <tbody>
            {table_rows_html}
        </tbody>
    </table>
</div>

<script>
Chart.register(ChartDataLabels);

const labels = {json.dumps(labels)};
const portfolioValues = {json.dumps(portfolio_values)};
const buyHoldValues = {json.dumps(buy_hold_values)};
const stockPrices = {json.dumps(stock_prices)};
const premiums = {json.dumps(premiums)};
const pnls = {json.dumps(pnls)};
const marginInterests = {json.dumps(margin_interests)};
const resultStates = {json.dumps(result_states)};
const pointColors = {json.dumps(point_colors)};

// Portfolio chart with stock price trend and state labels
new Chart(document.getElementById('portfolioChart'), {{
    type: 'line',
    data: {{
        labels: labels,
        datasets: [
            {{
                label: 'Strategy',
                data: portfolioValues,
                borderColor: '#667eea',
                backgroundColor: 'rgba(102, 126, 234, 0.1)',
                fill: true,
                tension: 0.1,
                pointRadius: 6,
                pointBackgroundColor: pointColors,
                pointBorderColor: pointColors,
                borderWidth: 2,
                yAxisID: 'y',
                datalabels: {{
                    align: 'top',
                    offset: 8,
                    color: function(ctx) {{
                        return pointColors[ctx.dataIndex];
                    }},
                    font: {{ size: 11, weight: 'bold' }},
                    formatter: function(value, ctx) {{
                        return resultStates[ctx.dataIndex];
                    }}
                }}
            }},
            {{
                label: 'Buy & Hold',
                data: buyHoldValues,
                borderColor: '#f39c12',
                backgroundColor: 'rgba(243, 156, 18, 0.05)',
                fill: false,
                tension: 0.1,
                pointRadius: 3,
                pointBackgroundColor: '#f39c12',
                borderDash: [6, 3],
                borderWidth: 2,
                yAxisID: 'y',
                datalabels: {{ display: false }}
            }},
            {{
                label: 'Stock Price',
                data: stockPrices,
                borderColor: '#2ecc71',
                backgroundColor: 'rgba(46, 204, 113, 0.05)',
                fill: false,
                tension: 0.1,
                pointRadius: 3,
                pointBackgroundColor: '#2ecc71',
                borderWidth: 1.5,
                yAxisID: 'y2',
                datalabels: {{ display: false }}
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            datalabels: {{}},
            tooltip: {{
                callbacks: {{
                    afterLabel: function(ctx) {{
                        if (ctx.datasetIndex === 0) {{
                            const stateDescs = {{'A':'Neither exercised','B':'Call assigned (after Act1)','C':'Put assigned (after Act1)','D':'Both expired (after Act1)','E':'Put assigned (no Act1)'}};
                            return 'State: ' + resultStates[ctx.dataIndex] + ' - ' + stateDescs[resultStates[ctx.dataIndex]];
                        }}
                        return '';
                    }},
                    label: function(ctx) {{
                        return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
                    }}
                }}
            }},
            legend: {{ position: 'top' }}
        }},
        scales: {{
            y: {{
                type: 'linear',
                position: 'left',
                title: {{ display: true, text: 'Portfolio Value ($)' }},
                ticks: {{ callback: function(v) {{ return '$' + v.toLocaleString(); }} }}
            }},
            y2: {{
                type: 'linear',
                position: 'right',
                title: {{ display: true, text: 'Stock Price ($)' }},
                grid: {{ drawOnChartArea: false }},
                ticks: {{ callback: function(v) {{ return '$' + v.toFixed(0); }} }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('premiumChart'), {{
    type: 'bar',
    data: {{
        labels: labels,
        datasets: [
            {{
                label: 'Premium',
                data: premiums,
                backgroundColor: 'rgba(102, 126, 234, 0.6)',
                borderColor: '#667eea',
                borderWidth: 1,
                yAxisID: 'y',
                datalabels: {{ display: false }}
            }},
            {{
                label: 'Cycle PnL',
                data: pnls,
                backgroundColor: pnls.map(p => p >= 0 ? 'rgba(39, 174, 96, 0.6)' : 'rgba(192, 57, 43, 0.6)'),
                borderColor: pnls.map(p => p >= 0 ? '#27ae60' : '#c0392b'),
                borderWidth: 1,
                yAxisID: 'y1',
                datalabels: {{ display: false }}
            }},
            {{
                label: 'Financing Cost',
                data: marginInterests,
                backgroundColor: 'rgba(231, 76, 60, 0.4)',
                borderColor: '#c0392b',
                borderWidth: 1,
                yAxisID: 'y1',
                datalabels: {{ display: false }}
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            datalabels: {{ display: false }},
            legend: {{ position: 'top' }}
        }},
        scales: {{
            y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'Premium ($)' }} }},
            y1: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'PnL / Financing ($)' }} }}
        }}
    }}
}});
</script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n  HTML report saved to: {output_path}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Wheel Strategy - Gav Version (Google)')
    parser.add_argument('--dte', type=int, default=18, help='Days to expiry (default: 18)')
    parser.add_argument('--margin-rate', type=float, default=0.11, help='Margin financing annualized rate (default: 0.11)')
    parser.add_argument('--put-iv', type=float, default=0.30, help='Put implied volatility (default: 0.30)')
    parser.add_argument('--call-iv', type=float, default=0.22, help='Call implied volatility (default: 0.22)')
    parser.add_argument('--start', type=str, default='2026-01-01', help='Start date (default: 2026-01-01)')
    parser.add_argument('--end', type=str, default='2026-07-15', help='End date (default: 2026-07-15)')
    parser.add_argument('--ticker', type=str, default='GOOGL', help='Ticker name (default: GOOGL)')
    parser.add_argument('--data', type=str, default='googl_data.json', help='Price data JSON file')
    parser.add_argument('--report', type=str, default='googl_wheel_report.html', help='HTML report path')

    args = parser.parse_args()

    config = Config(
        dte=args.dte,
        margin_rate=args.margin_rate,
        put_iv=args.put_iv,
        call_iv=args.call_iv,
        start_date=args.start,
        end_date=args.end,
        ticker=args.ticker,
        data_file=args.data,
        report_file=args.report
    )

    result = simulate(config)
    print_result(result)
    generate_html(result, config.report_file)


if __name__ == '__main__':
    main()
