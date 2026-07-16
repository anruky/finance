#!/usr/bin/env python3
"""
Wheel Strategy V3 - Dual Position with Daily Monitoring
========================================================

Total capital = 2 x 100 x S0 (enough for 2 lots of stock)
Initial: Hold 100 shares + cash = 100 x S0

State A (100 shares + cash):
    1. Sell put, DTE days, strike set for ~20% annualized premium on collateral
    2. Sell call, DTE days, strike set for ~5% annualized premium on stock value
    3. Daily monitor: if price hits call strike -> Action 1 (close put, buy 100 shares)
    4. At expiry:
       - Action 1 triggered:
         - Call exercised (price >= call strike) -> sell 100 shares -> State A
         - Call not exercised -> keep 200 shares -> State B
       - No action:
         - Put exercised (price < put strike) -> receive 100 shares -> State B
         - Neither exercised -> State A

State B (200 shares):
    1. Sell call, DTE days, strike set for ~8% annualized premium on stock value
    2. Sell call, DTE days, strike set for ~3% annualized premium on stock value
    3. At expiry:
       - Both exercised -> sell 200 shares -> buy 100 shares -> State A
       - Only lower call exercised -> sell 100 shares -> State A
       - Neither -> State B

Usage:
  python3 wheel_strategy.py [options]

Options:
  --dte              Days to expiry (default: 10)
  --put-target       Put annualized return target (default: 0.20)
  --call-target      State A call annualized premium target (default: 0.05)
  --call-target1     State B call1 annualized premium target (default: 0.08)
  --call-target2     State B call2 annualized premium target (default: 0.03)
  --put-iv           Put implied volatility (default: 0.30)
  --call-iv          Call implied volatility (default: 0.22)
  --start            Start date YYYY-MM-DD (default: 2026-01-01)
  --end              End date YYYY-MM-DD (default: 2026-07-15)
  --ticker           Ticker name for report (default: QQQ)
  --data             JSON data file [date, open, high, low, close] (default: qqq_data.json)
  --report           HTML report output path (default: qqq_wheel_report.html)
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
    """Standard normal CDF using error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes call price."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put price."""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def find_put_strike(S: float, T: float, r: float, sigma: float,
                    annualized_target: float, dte: int) -> Tuple[float, float]:
    """
    Find put strike K such that premium / K * (365 / dte) ~= annualized_target.
    Returns (strike, premium_per_share).
    """
    target_ratio = annualized_target * dte / 365.0  # premium / strike

    # Binary search: f(K) = bs_put(S, K, ...) - K * target_ratio
    # f(small K) < 0 (put worthless, target > 0)
    # f(K=S) > 0 (ATM put is valuable)
    lo, hi = 0.01, S
    for _ in range(200):
        mid = (lo + hi) / 2.0
        put_price = bs_put(S, mid, T, r, sigma)
        target_price = mid * target_ratio
        if put_price < target_price:
            lo = mid  # need higher K to increase put price
        else:
            hi = mid

    strike = round(mid, 2)
    premium = bs_put(S, strike, T, r, sigma)
    return strike, round(premium, 4)


def find_call_strike(S: float, T: float, r: float, sigma: float,
                     annualized_target: float, dte: int) -> Tuple[float, float]:
    """
    Find call strike K such that premium / S * (365 / dte) ~= annualized_target.
    Collateral for covered call is the stock price S.
    Returns (strike, premium_per_share).
    """
    target_premium = S * annualized_target * dte / 365.0

    # Binary search: f(K) = bs_call(S, K, ...) - target_premium
    # f(K=S) > 0 (ATM call is valuable)
    # f(very high K) < 0 (deep OTM call is worthless)
    lo, hi = S, S * 3.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        call_price = bs_call(S, mid, T, r, sigma)
        if call_price > target_premium:
            lo = mid  # need higher strike to reduce call price
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
    dte: int = 10
    put_annualized_target: float = 0.20    # 20% annualized return target for put
    call_annualized_target: float = 0.05   # State A call: 5% annualized premium
    call_annualized_target_1: float = 0.08 # State B call 1: 8% annualized premium
    call_annualized_target_2: float = 0.03 # State B call 2: 3% annualized premium
    put_iv: float = 0.30                   # Put implied volatility
    call_iv: float = 0.22                  # Call implied volatility
    start_date: str = '2026-01-01'
    end_date: str = '2026-07-15'
    r: float = 0.05                        # risk-free rate
    contract_size: int = 100               # shares per contract
    ticker: str = 'QQQ'
    data_file: str = 'qqq_data.json'
    report_file: str = 'qqq_wheel_report.html'


# ============================================================
# Data Structures
# ============================================================

@dataclass
class Cycle:
    cycle_num: int
    state: str                      # 'A' or 'B'
    entry_date: str
    entry_price: float
    # Options sold
    put_strike: float               # 0 if no put
    call1_strike: float             # primary call strike
    call2_strike: float             # secondary call strike (State B), 0 if none
    put_premium: float              # per share, 0 if no put
    call1_premium: float            # per share
    call2_premium: float            # per share, 0 if none
    total_premium: float            # total premium received ($)
    # Action 1 (State A only)
    action1_triggered: bool
    action1_date: str               # date of action, '' if not triggered
    action1_price: float            # price at action, 0 if not triggered
    put_buyback_cost: float         # cost to buy back put ($), 0 if not triggered
    # Expiry
    expiry_date: str
    expiry_price: float
    outcome: str                    # description of what happened
    cycle_pnl: float                # change in portfolio value
    portfolio_value: float          # portfolio value after this cycle
    buy_hold_value: float           # buy & hold value at same point
    cash: float
    shares: int
    next_state: str                 # 'A' or 'B'


@dataclass
class BacktestResult:
    config: Config
    cycles: List[Cycle]
    initial_capital: float
    final_value: float
    total_premium: float
    total_return_pct: float
    annualized_return_pct: float
    num_cycles: int
    num_state_a: int
    num_state_b: int
    num_action1: int
    num_put_assigned: int
    num_call_assigned: int
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
    """
    Load daily OHLC data from JSON file.
    Format: [[date, open, high, low, close], ...]
    """
    with open(filepath, 'r') as f:
        raw = json.load(f)

    data = []
    for row in raw:
        date_str = row[0]
        if start_date <= date_str <= end_date:
            # date, open, high, low, close
            data.append((row[0], row[1], row[2], row[3], row[4]))

    data.sort(key=lambda x: x[0])
    return data


# ============================================================
# Trading Day Utilities
# ============================================================

def find_expiry_index(entry_idx: int, dates: List[str], dte: int) -> int:
    """Find the index of the expiry trading day (first trading day >= entry + DTE calendar days)."""
    entry_date = datetime.strptime(dates[entry_idx], '%Y-%m-%d')
    target = entry_date + timedelta(days=dte)
    target_str = target.strftime('%Y-%m-%d')

    for i in range(entry_idx + 1, len(dates)):
        if dates[i] >= target_str:
            return i

    return len(dates) - 1


# ============================================================
# Strategy Simulation
# ============================================================

def simulate(config: Config) -> BacktestResult:
    """Run the dual-position wheel strategy backtest."""

    # Load data
    data = load_data(config.data_file, config.start_date, config.end_date)
    if len(data) < 2:
        raise ValueError(f"Not enough data: only {len(data)} days")

    dates = [d[0] for d in data]
    opens = [d[1] for d in data]
    highs = [d[2] for d in data]
    lows = [d[3] for d in data]
    closes = [d[4] for d in data]

    CS = config.contract_size  # 100

    # Initial capital = 2 * 100 * S0 (enough for 2 lots)
    S0 = closes[0]
    initial_capital = 2 * CS * S0

    # Initial state: 100 shares + cash = 100 * S0
    shares = CS
    cash = CS * S0
    state = 'A'  # start in State A

    cycles: List[Cycle] = []
    portfolio_values: List[float] = []

    cycle_num = 0
    idx = 0

    while idx < len(dates) - 1:
        entry_idx = idx
        entry_date = dates[entry_idx]
        entry_price = closes[entry_idx]

        # Find expiry
        expiry_idx = find_expiry_index(entry_idx, dates, config.dte)
        expiry_date = dates[expiry_idx]
        expiry_price = closes[expiry_idx]

        # Actual days to expiry
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

        # ---- State A: 100 shares + cash ----
        if state == 'A':
            # 1. Sell put: find strike for ~20% annualized
            put_strike, put_prem = find_put_strike(
                entry_price, T, config.r, config.put_iv,
                config.put_annualized_target, actual_dte
            )

            # 2. Sell call: find strike for ~5% annualized premium
            call1_strike, call1_prem = find_call_strike(
                entry_price, T, config.r, config.call_iv,
                config.call_annualized_target, actual_dte
            )

            put_prem = round(put_prem, 4)
            call1_prem = round(call1_prem, 4)
            call2_strike = 0
            call2_prem = 0

            total_prem = (put_prem + call1_prem) * CS
            cash += total_prem

            # 3. Daily monitoring: check if high reaches call strike
            action1_triggered = False
            action1_date = ''
            action1_price = 0.0
            put_buyback_cost = 0.0

            for day_idx in range(entry_idx + 1, expiry_idx + 1):
                if highs[day_idx] >= call1_strike:
                    action1_triggered = True
                    action1_date = dates[day_idx]
                    action1_price = call1_strike  # approximate execution price

                    # Calculate remaining time from action day to expiry
                    remaining_days = (datetime.strptime(expiry_date, '%Y-%m-%d') -
                                      datetime.strptime(action1_date, '%Y-%m-%d')).days
                    remaining_T = max(remaining_days / 365.0, 1.0 / 365.0)

                    # Buy back put (it's deep OTM now since price went up)
                    put_buyback = bs_put(action1_price, put_strike, remaining_T,
                                         config.r, config.put_iv)
                    put_buyback = round(put_buyback, 4)
                    put_buyback_cost = put_buyback * CS
                    cash -= put_buyback_cost  # pay to buy back

                    # Buy 100 shares at action price
                    cash -= action1_price * CS
                    shares += CS  # now 200 shares

                    break

            # 4. Determine outcome at expiry
            if action1_triggered:
                # Call is still open; check if exercised
                if expiry_price >= call1_strike:
                    # Call exercised: sell 100 shares at call strike
                    cash += call1_strike * CS
                    shares -= CS  # back to 100 shares
                    outcome = f'Action1 on {action1_date} @ ${action1_price:.2f}; Call assigned: sold {CS} shares @ ${call1_strike}'
                    next_state = 'A'
                else:
                    # Call not exercised: keep 200 shares
                    outcome = f'Action1 on {action1_date} @ ${action1_price:.2f}; Call expired: keep {shares} shares'
                    next_state = 'B'
            else:
                # No action; check put and call at expiry
                put_assigned = expiry_price < put_strike
                call_assigned = expiry_price > call1_strike

                if put_assigned and not call_assigned:
                    # Put exercised: buy 100 shares at put strike
                    cash -= put_strike * CS
                    shares += CS  # now 200 shares
                    outcome = f'Put assigned: bought {CS} shares @ ${put_strike}; Call expired'
                    next_state = 'B'
                elif call_assigned and not put_assigned:
                    # Call exercised: sell 100 shares at call strike
                    cash += call1_strike * CS
                    shares -= CS  # back to 0 shares... but we started with 100
                    # Wait: we have 100 shares, sell 100 -> 0 shares + cash
                    # Need to buy back 100 shares to enter State A
                    cash -= expiry_price * CS
                    shares += CS  # back to 100 shares
                    outcome = f'Call assigned: sold {CS} @ ${call1_strike}, rebought @ ${expiry_price:.2f}; Put expired'
                    next_state = 'A'
                elif not put_assigned and not call_assigned:
                    outcome = 'Both put and call expired worthless'
                    next_state = 'A'
                else:
                    # Both assigned (price < put strike AND price > call strike - impossible)
                    # This can't happen since put_strike < S < call_strike
                    outcome = 'Unexpected: both assigned'
                    next_state = 'A'

        # ---- State B: 200 shares ----
        else:
            # Sell 2 calls: ~8% and ~3% annualized premium
            call1_strike, call1_prem = find_call_strike(
                entry_price, T, config.r, config.call_iv,
                config.call_annualized_target_1, actual_dte
            )
            call2_strike, call2_prem = find_call_strike(
                entry_price, T, config.r, config.call_iv,
                config.call_annualized_target_2, actual_dte
            )

            call1_prem = round(call1_prem, 4)
            call2_prem = round(call2_prem, 4)
            put_strike = 0
            put_prem = 0

            total_prem = (call1_prem + call2_prem) * CS
            cash += total_prem

            action1_triggered = False
            action1_date = ''
            action1_price = 0.0
            put_buyback_cost = 0.0

            # No Action 1 in State B; determine outcome at expiry
            call1_assigned = expiry_price > call1_strike
            call2_assigned = expiry_price > call2_strike

            if call1_assigned and call2_assigned:
                # Both exercised: sell 200 shares
                cash += call1_strike * CS  # sell 100 at higher strike
                cash += call2_strike * CS  # sell 100 at lower strike
                shares -= 2 * CS  # 0 shares
                # Buy back 100 shares to enter State A
                cash -= expiry_price * CS
                shares += CS  # 100 shares
                outcome = f'Both calls assigned: sold 2x{CS} @ ${call1_strike}/${call2_strike}, rebought @ ${expiry_price:.2f}'
                next_state = 'A'
            elif call2_assigned and not call1_assigned:
                # Only lower call exercised: sell 100 shares at call2 strike
                cash += call2_strike * CS
                shares -= CS  # 100 shares
                outcome = f'Call2 (~{config.call_annualized_target_2*100:.0f}% ann.) assigned: sold {CS} @ ${call2_strike}; Call1 expired'
                next_state = 'A'
            else:
                outcome = 'Both calls expired worthless'
                next_state = 'B'

        # Portfolio value after this cycle (at expiry price)
        portfolio_after = cash + shares * expiry_price
        cycle_pnl = portfolio_after - portfolio_before
        portfolio_values.append(portfolio_after)

        # Buy & Hold: invest all initial capital in stock, hold 200 shares
        buy_hold_val = initial_capital * (expiry_price / S0)

        cycle_num += 1
        cycles.append(Cycle(
            cycle_num=cycle_num,
            state=state,
            entry_date=entry_date,
            entry_price=round(entry_price, 2),
            put_strike=put_strike,
            call1_strike=call1_strike,
            call2_strike=call2_strike,
            put_premium=put_prem,
            call1_premium=call1_prem,
            call2_premium=call2_prem,
            total_premium=round(total_prem, 2),
            action1_triggered=action1_triggered,
            action1_date=action1_date,
            action1_price=round(action1_price, 2),
            put_buyback_cost=round(put_buyback_cost, 2),
            expiry_date=expiry_date,
            expiry_price=round(expiry_price, 2),
            outcome=outcome,
            cycle_pnl=round(cycle_pnl, 2),
            portfolio_value=round(portfolio_after, 2),
            buy_hold_value=round(buy_hold_val, 2),
            cash=round(cash, 2),
            shares=shares,
            next_state=next_state
        ))

        state = next_state
        idx = expiry_idx
        if idx >= len(dates) - 1:
            break

    # Final valuation at last price
    last_price = closes[-1]
    final_value = cash + shares * last_price

    # Statistics
    total_premium = sum(c.total_premium for c in cycles)
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

    # Counts
    num_state_a = sum(1 for c in cycles if c.state == 'A')
    num_state_b = sum(1 for c in cycles if c.state == 'B')
    num_action1 = sum(1 for c in cycles if c.action1_triggered)
    num_put_assigned = sum(1 for c in cycles if c.state == 'A' and not c.action1_triggered
                           and c.put_strike > 0 and c.expiry_price < c.put_strike)
    num_call_assigned = sum(1 for c in cycles if c.expiry_price > c.call1_strike)

    return BacktestResult(
        config=config,
        cycles=cycles,
        initial_capital=round(initial_capital, 2),
        final_value=round(final_value, 2),
        total_premium=round(total_premium, 2),
        total_return_pct=round(total_return * 100, 2),
        annualized_return_pct=round(annualized * 100, 2),
        num_cycles=len(cycles),
        num_state_a=num_state_a,
        num_state_b=num_state_b,
        num_action1=num_action1,
        num_put_assigned=num_put_assigned,
        num_call_assigned=num_call_assigned,
        max_drawdown_pct=round(max_dd * 100, 2),
        buy_hold_return_pct=round(buy_hold_return * 100, 2),
        buy_hold_annualized_pct=round(buy_hold_annualized * 100, 2),
        buy_hold_max_drawdown_pct=round(bh_max_dd * 100, 2),
        backtest_days=backtest_days,
        put_iv=round(config.put_iv * 100, 2),
        call_iv=round(config.call_iv * 100, 2)
    )


# ============================================================
# Console Output
# ============================================================

def print_result(result: BacktestResult):
    """Print backtest results to console."""
    cfg = result.config

    print("=" * 100)
    print(f"  {cfg.ticker} DUAL-POSITION WHEEL STRATEGY (V3)")
    print("=" * 100)

    print(f"\n  Configuration:")
    print(f"    DTE                    : {cfg.dte} days")
    print(f"    Put annualized target  : {cfg.put_annualized_target*100:.0f}%")
    print(f"    Call ann. target (A)   : {cfg.call_annualized_target*100:.0f}%")
    print(f"    Call ann. target 1 (B) : {cfg.call_annualized_target_1*100:.0f}%")
    print(f"    Call ann. target 2 (B) : {cfg.call_annualized_target_2*100:.0f}%")
    print(f"    Period                 : {cfg.start_date} -> {cfg.end_date}")
    print(f"    Put IV                 : {result.put_iv}%")
    print(f"    Call IV                : {result.call_iv}%")
    print(f"    Risk-free rate         : {cfg.r*100:.1f}%")

    print(f"\n  Results:")
    print(f"    Initial capital        : ${result.initial_capital:,.2f}")
    print(f"    Final value            : ${result.final_value:,.2f}")
    print(f"    Total premium income   : ${result.total_premium:,.2f}")
    print(f"    Total return           : {result.total_return_pct:.2f}%")
    print(f"    Annualized return      : {result.annualized_return_pct:.2f}%")
    print(f"    Backtest days          : {result.backtest_days}")
    print(f"    Max drawdown           : {result.max_drawdown_pct:.2f}%")
    print(f"    Buy & Hold return      : {result.buy_hold_return_pct:.2f}%")
    print(f"    Buy & Hold annualized  : {result.buy_hold_annualized_pct:.2f}%")
    print(f"    B&H max drawdown       : {result.buy_hold_max_drawdown_pct:.2f}%")

    print(f"\n  Cycle Summary:")
    print(f"    Total cycles           : {result.num_cycles}")
    print(f"    State A cycles         : {result.num_state_a}")
    print(f"    State B cycles         : {result.num_state_b}")
    print(f"    Action 1 triggered     : {result.num_action1}")
    print(f"    Put assigned           : {result.num_put_assigned}")
    print(f"    Call assigned          : {result.num_call_assigned}")

    print(f"\n  {'#' * 96}")
    print(f"  ANNUALIZED RETURN: {result.annualized_return_pct:.2f}%")
    print(f"  {'#' * 96}")

    # Print cycle table
    print(f"\n  Cycle List:")
    hdr = (f"  {'#':>3} {'St':>2} {'Entry':>12} {'Price':>8} {'PutK':>7} {'CallK':>7} "
           f"{'CallK2':>7} {'Prem':>7} {'Act1':>4} {'Expiry':>12} {'ExpPx':>8} "
           f"{'PnL':>10} {'Value':>12} {'B&H':>12}")
    print(hdr)
    print(f"  {'-'*3} {'-'*2} {'-'*12} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*12} {'-'*8} {'-'*10} {'-'*12} {'-'*12}")

    for c in result.cycles:
        act1 = 'YES' if c.action1_triggered else ''
        pnl_str = f"${c.cycle_pnl:+,.0f}"
        val_str = f"${c.portfolio_value:,.0f}"
        bh_str = f"${c.buy_hold_value:,.0f}"
        putk = f"{c.put_strike}" if c.put_strike > 0 else '-'
        callk2 = f"{c.call2_strike}" if c.call2_strike > 0 else '-'
        print(f"  {c.cycle_num:>3} {c.state:>2} {c.entry_date:>12} {c.entry_price:>8.2f} "
              f"{putk:>7} {c.call1_strike:>7} {callk2:>7} {c.total_premium:>7.0f} "
              f"{act1:>4} {c.expiry_date:>12} {c.expiry_price:>8.2f} "
              f"{pnl_str:>10} {val_str:>12} {bh_str:>12}")

    # Print outcomes
    print(f"\n  Outcomes:")
    for c in result.cycles:
        print(f"  #{c.cycle_num:>3} [{c.state}] {c.outcome}")

    print()


# ============================================================
# HTML Report
# ============================================================

def generate_html(result: BacktestResult, output_path: str):
    """Generate an HTML report with charts and cycle table."""
    cfg = result.config
    ticker = cfg.ticker

    # Prepare data for charts (use expiry dates so values align with actual dates)
    labels = [c.expiry_date for c in result.cycles]
    portfolio_values = [c.portfolio_value for c in result.cycles]
    buy_hold_values = [c.buy_hold_value for c in result.cycles]
    premiums = [c.total_premium for c in result.cycles]
    pnls = [c.cycle_pnl for c in result.cycles]
    states = [c.state for c in result.cycles]

    # State colors for portfolio chart points
    point_colors = []
    for i, s in enumerate(states):
        if s == 'A':
            point_colors.append('#667eea')
        else:
            point_colors.append('#e67e22')

    # Cycle table rows
    table_rows = []
    for c in result.cycles:
        pnl_class = 'profit' if c.cycle_pnl >= 0 else 'loss'
        state_class = 'state-a' if c.state == 'A' else 'state-b'
        act1_html = '<span class="badge badge-action">ACT1</span>' if c.action1_triggered else ''
        putk_html = f'${c.put_strike}' if c.put_strike > 0 else '-'
        callk2_html = f'${c.call2_strike}' if c.call2_strike > 0 else '-'

        # Premium breakdown
        prem_parts = []
        if c.put_premium > 0:
            prem_parts.append(f'P:{c.put_premium:.2f}')
        prem_parts.append(f'C1:{c.call1_premium:.2f}')
        if c.call2_premium > 0:
            prem_parts.append(f'C2:{c.call2_premium:.2f}')
        prem_detail = ' / '.join(prem_parts)

        table_rows.append(f"""
            <tr>
                <td>{c.cycle_num}</td>
                <td class="{state_class}">{c.state}</td>
                <td>{c.entry_date}</td>
                <td>${c.entry_price:.2f}</td>
                <td>{putk_html}</td>
                <td>${c.call1_strike}</td>
                <td>{callk2_html}</td>
                <td>${c.total_premium:,.0f}<br><span class="prem-detail">{prem_detail}</span></td>
                <td>{act1_html}</td>
                <td>{c.expiry_date}</td>
                <td>${c.expiry_price:.2f}</td>
                <td class="{pnl_class}">${c.cycle_pnl:+,.0f}</td>
                <td>${c.portfolio_value:,.0f}</td>
                <td>${c.buy_hold_value:,.0f}</td>
                <td>{c.shares}</td>
                <td class="note">{c.outcome}</td>
            </tr>""")

    table_rows_html = '\n'.join(table_rows)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} Wheel Strategy V3 Backtest</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
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
td.state-b {{ color: #e67e22; font-weight: 700; }}
td.profit {{ color: #27ae60; font-weight: 600; }}
td.loss {{ color: #c0392b; font-weight: 600; }}
td.note {{ text-align: left; color: #666; font-size: 11px; max-width: 350px; }}
.prem-detail {{ font-size: 10px; color: #999; }}
.badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }}
.badge-action {{ background: #e74c3c; color: white; }}

.section-title {{ font-size: 20px; font-weight: 700; margin: 30px 0 15px; color: #2c3e50; }}

.strategy-box {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.strategy-box h3 {{ font-size: 16px; margin-bottom: 12px; color: #555; }}
.strategy-box ul {{ margin-left: 20px; font-size: 13px; color: #444; }}
.strategy-box li {{ margin-bottom: 6px; }}
</style>
</head>
<body>
<div class="container">
    <h1>{ticker} Wheel Strategy V3 - Dual Position</h1>
    <p class="subtitle">Initial: 1 lot stock + cash | Sell Put (20% ann.) + Call (5% ann.) | Daily monitor | State A/B cycling | {cfg.dte}-day DTE</p>

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
            <div class="card-label">Total Premium</div>
            <div class="card-value profit">${{result.total_premium:,.0f}}</div>
            <div class="card-sub">{result.num_cycles} cycles</div>
        </div>
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
            <div class="card-label">State A / B</div>
            <div class="card-value neutral">{result.num_state_a} / {result.num_state_b}</div>
            <div class="card-sub">cycles in each state</div>
        </div>
        <div class="card">
            <div class="card-label">Action 1 Triggered</div>
            <div class="card-value neutral">{result.num_action1}</div>
            <div class="card-sub">put closed early</div>
        </div>
    </div>

    <div class="strategy-box">
        <h3>Strategy Logic</h3>
        <ul>
            <li><b>State A</b> (100 shares + cash): Sell Put (~{cfg.put_annualized_target*100:.0f}% ann.) + Sell Call (~{cfg.call_annualized_target*100:.0f}% ann.)</li>
            <li><b>Daily Monitor</b>: If price hits call strike -> Action 1: close put, buy 100 shares</li>
            <li><b>State B</b> (200 shares): Sell 2 Calls (~{cfg.call_annualized_target_1*100:.0f}% and ~{cfg.call_annualized_target_2*100:.0f}% ann.)</li>
            <li><b>Cycle</b>: {cfg.dte} days to expiry, then reassess state</li>
        </ul>
    </div>

    <div class="config-box">
        <h3>Configuration</h3>
        <div class="config-grid">
            <div class="config-item"><span>DTE</span><span>{cfg.dte} days</span></div>
            <div class="config-item"><span>Put Ann. Target</span><span>{cfg.put_annualized_target*100:.0f}%</span></div>
            <div class="config-item"><span>Call Ann. (A)</span><span>{cfg.call_annualized_target*100:.0f}%</span></div>
            <div class="config-item"><span>Call Ann. 1 (B)</span><span>{cfg.call_annualized_target_1*100:.0f}%</span></div>
            <div class="config-item"><span>Call Ann. 2 (B)</span><span>{cfg.call_annualized_target_2*100:.0f}%</span></div>
            <div class="config-item"><span>Start</span><span>{cfg.start_date}</span></div>
            <div class="config-item"><span>End</span><span>{cfg.end_date}</span></div>
            <div class="config-item"><span>Put IV</span><span>{result.put_iv}%</span></div>
            <div class="config-item"><span>Call IV</span><span>{result.call_iv}%</span></div>
            <div class="config-item"><span>Risk-free Rate</span><span>{cfg.r*100:.1f}%</span></div>
        </div>
    </div>

    <div class="chart-container">
        <h3>Portfolio Value: Strategy vs Buy &amp; Hold</h3>
        <div class="chart-wrapper">
            <canvas id="portfolioChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h3>Per-Cycle Premium Income & PnL</h3>
        <div class="chart-wrapper">
            <canvas id="premiumChart"></canvas>
        </div>
    </div>

    <div class="section-title">Cycle List ({result.num_cycles} cycles)</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>State</th>
                <th>Entry Date</th>
                <th>Entry Price</th>
                <th>Put Strike</th>
                <th>Call1 Strike</th>
                <th>Call2 Strike</th>
                <th>Total Premium</th>
                <th>Act1</th>
                <th>Expiry Date</th>
                <th>Expiry Price</th>
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
const labels = {json.dumps(labels)};
const portfolioValues = {json.dumps(portfolio_values)};
const buyHoldValues = {json.dumps(buy_hold_values)};
const premiums = {json.dumps(premiums)};
const pnls = {json.dumps(pnls)};
const pointColors = {json.dumps(point_colors)};

// Portfolio value chart
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
                pointRadius: 5,
                pointBackgroundColor: pointColors,
                pointBorderColor: pointColors,
                borderWidth: 2
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
                borderWidth: 2
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            tooltip: {{
                callbacks: {{
                    label: function(ctx) {{ return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString(undefined, {{minimumFractionDigits: 0, maximumFractionDigits: 0}}); }}
                }}
            }}
        }},
        scales: {{
            y: {{ ticks: {{ callback: function(v) {{ return '$' + v.toLocaleString(); }} }} }}
        }}
    }}
}});

// Premium & PnL chart
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
                yAxisID: 'y'
            }},
            {{
                label: 'Cycle PnL',
                data: pnls,
                backgroundColor: pnls.map(p => p >= 0 ? 'rgba(39, 174, 96, 0.6)' : 'rgba(192, 57, 43, 0.6)'),
                borderColor: pnls.map(p => p >= 0 ? '#27ae60' : '#c0392b'),
                borderWidth: 1,
                yAxisID: 'y1'
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
            y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'Premium ($)' }} }},
            y1: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'PnL ($)' }} }}
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
    parser = argparse.ArgumentParser(description='Wheel Strategy V3 - Dual Position Backtest')
    parser.add_argument('--dte', type=int, default=10, help='Days to expiry (default: 10)')
    parser.add_argument('--put-target', type=float, default=0.20, help='Put annualized return target (default: 0.20)')
    parser.add_argument('--call-target', type=float, default=0.05, help='State A call annualized premium target (default: 0.05)')
    parser.add_argument('--call-target1', type=float, default=0.08, help='State B call1 annualized premium target (default: 0.08)')
    parser.add_argument('--call-target2', type=float, default=0.03, help='State B call2 annualized premium target (default: 0.03)')
    parser.add_argument('--put-iv', type=float, default=0.30, help='Put implied volatility (default: 0.30)')
    parser.add_argument('--call-iv', type=float, default=0.22, help='Call implied volatility (default: 0.22)')
    parser.add_argument('--start', type=str, default='2026-01-01', help='Start date (default: 2026-01-01)')
    parser.add_argument('--end', type=str, default='2026-07-15', help='End date (default: 2026-07-15)')
    parser.add_argument('--ticker', type=str, default='QQQ', help='Ticker name (default: QQQ)')
    parser.add_argument('--data', type=str, default='qqq_data.json', help='Price data JSON file')
    parser.add_argument('--report', type=str, default='qqq_wheel_report.html', help='HTML report path')

    args = parser.parse_args()

    config = Config(
        dte=args.dte,
        put_annualized_target=args.put_target,
        call_annualized_target=args.call_target,
        call_annualized_target_1=args.call_target1,
        call_annualized_target_2=args.call_target2,
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
