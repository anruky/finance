#!/usr/bin/env python3
"""
QQQ Wheel Strategy Backtest - Configurable Version
===================================================
Strategy (Wheel):
  1. Start with cash. Sell OTM Put (strike = price - put_otm), DTE days to expiry.
  2. At expiry:
     - Put NOT assigned (price >= strike) -> keep premium, sell another Put.
     - Put assigned (price < strike) -> buy 100 shares at strike, switch to selling Calls.
  3. While holding stock, sell OTM Call (strike = price + call_otm), DTE days to expiry.
  4. At expiry:
     - Call NOT assigned (price <= strike) -> keep premium, sell another Call.
     - Call assigned (price > strike) -> sell 100 shares at strike, switch back to Puts.
  5. Loop until end date.

Usage:
  python3 qqq_wheel_v2.py [options]

Options:
  --dte          Days to expiry (default: 10)
  --put-otm      Dollars below price for put strike (default: 15)
  --call-otm     Dollars above price for call strike (default: 10)
  --start        Start date YYYY-MM-DD (default: 2026-01-01)
  --end          End date YYYY-MM-DD (default: 2026-07-14)
  --iv-mode      IV mode: 'fixed' or 'dynamic' (default: fixed)
  --report       HTML report output path (default: qqq_wheel_report_v2.html)
  --data         JSON data file path (default: qqq_data.json)
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


def find_iv(market_price: float, S: float, K: float, T: float, r: float, opt_type: str) -> float:
    """Find implied volatility via bisection."""
    bs_func = bs_put if opt_type == 'put' else bs_call
    lo, hi = 0.005, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        p = bs_func(S, K, T, r, mid)
        if abs(p - market_price) < 0.0005:
            return mid
        if p < market_price:
            lo = mid
        else:
            hi = mid
    return mid


# ============================================================
# Configuration
# ============================================================

@dataclass
class Config:
    dte: int = 10
    put_otm: float = 15.0
    call_otm: float = 10.0
    start_date: str = '2026-01-01'
    end_date: str = '2026-07-14'
    iv_mode: str = 'fixed'        # 'fixed' or 'dynamic'
    r: float = 0.05               # risk-free rate
    contract_size: int = 100      # shares per contract
    data_file: str = 'qqq_data.json'
    report_file: str = 'qqq_wheel_report_v2.html'
    ticker: str = 'QQQ'


# ============================================================
# Data Structures
# ============================================================

@dataclass
class Cycle:
    cycle_num: int
    option_type: str               # 'PUT' or 'CALL'
    entry_date: str
    entry_price: float
    strike: float
    iv_used: float
    premium_per_share: float
    premium_total: float
    expiry_date: str
    expiry_price: float
    assigned: bool
    cycle_pnl: float               # change in portfolio value this cycle
    portfolio_value: float         # portfolio value after this cycle
    buy_hold_value: float          # buy & hold portfolio value at same point
    cash: float                    # cash after this cycle
    shares: int                    # shares held after this cycle
    note: str = ''


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
    num_puts: int
    num_calls: int
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

def load_data(filepath: str, start_date: str, end_date: str) -> List[Tuple[str, float]]:
    """Load QQQ daily data from JSON file, filtered by date range."""
    with open(filepath, 'r') as f:
        raw = json.load(f)
    
    data = []
    for date_str, price in raw:
        if start_date <= date_str <= end_date:
            data.append((date_str, price))
    
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
    
    # If no trading day after target, use last available
    return len(dates) - 1


def realized_vol(prices: List[float], lookback: int, idx: int) -> float:
    """Calculate annualized realized volatility from daily returns."""
    start = max(0, idx - lookback)
    if idx - start < 2:
        return 0.20  # default 20% if not enough data
    
    returns = []
    for i in range(start + 1, idx + 1):
        if prices[i] > 0 and prices[i-1] > 0:
            returns.append(math.log(prices[i] / prices[i-1]))
    
    if len(returns) < 2:
        return 0.20
    
    mean = sum(returns) / len(returns)
    var = sum((r - mean)**2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(252)


# ============================================================
# IV Calibration
# ============================================================

def calibrate_iv(config: Config) -> Tuple[float, float]:
    """
    Calibrate IV from current market quotes:
      QQQ = 714, 10-day Put strike=699, price=7.47
      QQQ = 714, 10-day Call strike=724, price=6.45
    """
    S = 714.0
    T = 10.0 / 365.0
    
    put_iv = find_iv(7.47, S, 699.0, T, config.r, 'put')
    call_iv = find_iv(6.45, S, 724.0, T, config.r, 'call')
    
    return put_iv, call_iv


# ============================================================
# Wheel Strategy Simulation
# ============================================================

def simulate(config: Config) -> BacktestResult:
    """Run the wheel strategy backtest."""
    
    # Load data
    data = load_data(config.data_file, config.start_date, config.end_date)
    if len(data) < 2:
        raise ValueError(f"Not enough data: only {len(data)} days")
    
    dates = [d[0] for d in data]
    prices = [d[1] for d in data]
    
    # Calibrate IV
    base_put_iv, base_call_iv = calibrate_iv(config)
    
    # Base RV at calibration point (last 20 days of data)
    base_rv = realized_vol(prices, 20, len(prices) - 1)
    
    # Initial capital = enough for 1 cash-secured put = 100 * first price
    initial_capital = config.contract_size * prices[0]
    
    # State
    cash = initial_capital
    shares = 0
    position = 'cash'  # 'cash' or 'holding'
    
    cycles: List[Cycle] = []
    portfolio_values: List[float] = []
    
    cycle_num = 0
    idx = 0
    
    while idx < len(dates) - 1:
        entry_idx = idx
        entry_date = dates[entry_idx]
        entry_price = prices[entry_idx]
        
        # Find expiry
        expiry_idx = find_expiry_index(entry_idx, dates, config.dte)
        expiry_date = dates[expiry_idx]
        expiry_price = prices[expiry_idx]
        
        # Actual days to expiry
        actual_dte = (datetime.strptime(expiry_date, '%Y-%m-%d') - 
                      datetime.strptime(entry_date, '%Y-%m-%d')).days
        T = actual_dte / 365.0
        
        if T <= 0:
            idx = expiry_idx + 1 if expiry_idx + 1 < len(dates) else expiry_idx
            if idx <= entry_idx:
                break
            continue
        
        # Determine option type and strike
        if position == 'cash':
            option_type = 'PUT'
            strike = round(entry_price - config.put_otm)
            
            # Determine IV
            if config.iv_mode == 'dynamic':
                rv = realized_vol(prices, 20, entry_idx)
                ratio = rv / base_rv if base_rv > 0 else 1.0
                iv = base_put_iv * ratio
                iv = max(0.08, min(iv, 1.5))
            else:
                iv = base_put_iv
            
            premium = bs_put(entry_price, strike, T, config.r, iv)
        else:
            option_type = 'CALL'
            strike = round(entry_price + config.call_otm)
            
            if config.iv_mode == 'dynamic':
                rv = realized_vol(prices, 20, entry_idx)
                ratio = rv / base_rv if base_rv > 0 else 1.0
                iv = base_call_iv * ratio
                iv = max(0.08, min(iv, 1.5))
            else:
                iv = base_call_iv
            
            premium = bs_call(entry_price, strike, T, config.r, iv)
        
        premium = round(premium, 2)
        premium_total = premium * config.contract_size
        
        # Record portfolio value before this cycle
        portfolio_before = cash + shares * entry_price
        
        # Receive premium
        cash += premium_total
        
        # Check assignment at expiry
        if option_type == 'PUT':
            assigned = expiry_price < strike
            if assigned:
                # Buy 100 shares at strike
                cash -= strike * config.contract_size
                shares = config.contract_size
                position = 'holding'
                note = f'Put assigned: bought {config.contract_size} shares @ ${strike}'
            else:
                note = 'Put expired worthless'
        else:  # CALL
            assigned = expiry_price > strike
            if assigned:
                # Sell 100 shares at strike
                cash += strike * config.contract_size
                shares = 0
                position = 'cash'
                note = f'Call assigned: sold {config.contract_size} shares @ ${strike}'
            else:
                note = 'Call expired worthless'
        
        # Portfolio value after this cycle (at expiry price)
        portfolio_after = cash + shares * expiry_price
        cycle_pnl = portfolio_after - portfolio_before
        portfolio_values.append(portfolio_after)
        
        # Buy & Hold value at same point (buy 100 shares at first price, hold)
        buy_hold_val = initial_capital * (expiry_price / prices[0])
        
        cycle_num += 1
        cycles.append(Cycle(
            cycle_num=cycle_num,
            option_type=option_type,
            entry_date=entry_date,
            entry_price=round(entry_price, 2),
            strike=strike,
            iv_used=round(iv * 100, 2),
            premium_per_share=premium,
            premium_total=round(premium_total, 2),
            expiry_date=expiry_date,
            expiry_price=round(expiry_price, 2),
            assigned=assigned,
            cycle_pnl=round(cycle_pnl, 2),
            portfolio_value=round(portfolio_after, 2),
            buy_hold_value=round(buy_hold_val, 2),
            cash=round(cash, 2),
            shares=shares,
            note=note
        ))
        
        # Move to next cycle starting from expiry day
        idx = expiry_idx
        if idx >= len(dates) - 1:
            break
    
    # Final valuation at last price
    last_price = prices[-1]
    final_value = cash + shares * last_price
    
    # Statistics
    total_premium = sum(c.premium_total for c in cycles)
    total_return = (final_value - initial_capital) / initial_capital
    backtest_days = (datetime.strptime(dates[-1], '%Y-%m-%d') - 
                     datetime.strptime(dates[0], '%Y-%m-%d')).days
    annualized = (1 + total_return) ** (365.0 / backtest_days) - 1 if backtest_days > 0 else 0
    
    # Buy & hold
    buy_hold_return = (prices[-1] - prices[0]) / prices[0]
    buy_hold_annualized = (1 + buy_hold_return) ** (365.0 / backtest_days) - 1 if backtest_days > 0 else 0
    
    # Max drawdown
    max_dd = 0.0
    peak = portfolio_values[0] if portfolio_values else initial_capital
    for pv in portfolio_values:
        if pv > peak:
            peak = pv
        dd = (peak - pv) / peak
        if dd > max_dd:
            max_dd = dd
    
    # Buy & Hold max drawdown (using all daily prices)
    buy_hold_values_daily = [initial_capital * (p / prices[0]) for p in prices]
    bh_max_dd = 0.0
    bh_peak = buy_hold_values_daily[0] if buy_hold_values_daily else initial_capital
    for bv in buy_hold_values_daily:
        if bv > bh_peak:
            bh_peak = bv
        dd = (bh_peak - bv) / bh_peak
        if dd > bh_max_dd:
            bh_max_dd = dd
    
    # Counts
    num_puts = sum(1 for c in cycles if c.option_type == 'PUT')
    num_calls = sum(1 for c in cycles if c.option_type == 'CALL')
    num_put_assigned = sum(1 for c in cycles if c.option_type == 'PUT' and c.assigned)
    num_call_assigned = sum(1 for c in cycles if c.option_type == 'CALL' and c.assigned)
    
    return BacktestResult(
        config=config,
        cycles=cycles,
        initial_capital=round(initial_capital, 2),
        final_value=round(final_value, 2),
        total_premium=round(total_premium, 2),
        total_return_pct=round(total_return * 100, 2),
        annualized_return_pct=round(annualized * 100, 2),
        num_cycles=len(cycles),
        num_puts=num_puts,
        num_calls=num_calls,
        num_put_assigned=num_put_assigned,
        num_call_assigned=num_call_assigned,
        max_drawdown_pct=round(max_dd * 100, 2),
        buy_hold_return_pct=round(buy_hold_return * 100, 2),
        buy_hold_annualized_pct=round(buy_hold_annualized * 100, 2),
        buy_hold_max_drawdown_pct=round(bh_max_dd * 100, 2),
        backtest_days=backtest_days,
        put_iv=round(base_put_iv * 100, 2),
        call_iv=round(base_call_iv * 100, 2)
    )


# ============================================================
# Console Output
# ============================================================

def print_result(result: BacktestResult):
    """Print backtest results to console."""
    cfg = result.config
    
    print("=" * 90)
    print(f"  {result.config.ticker} WHEEL STRATEGY BACKTEST")
    print("=" * 90)
    
    print(f"\n  Configuration:")
    print(f"    DTE (days to expiry)  : {cfg.dte}")
    print(f"    Put OTM               : ${cfg.put_otm}")
    print(f"    Call OTM              : ${cfg.call_otm}")
    print(f"    Period                : {cfg.start_date} -> {cfg.end_date}")
    print(f"    IV mode               : {cfg.iv_mode}")
    print(f"    Risk-free rate        : {cfg.r*100:.1f}%")
    print(f"    Calibrated Put IV     : {result.put_iv}%")
    print(f"    Calibrated Call IV    : {result.call_iv}%")
    
    print(f"\n  Results:")
    print(f"    Initial capital       : ${result.initial_capital:,.2f}")
    print(f"    Final value           : ${result.final_value:,.2f}")
    print(f"    Total premium income  : ${result.total_premium:,.2f}")
    print(f"    Total return          : {result.total_return_pct:.2f}%")
    print(f"    Annualized return     : {result.annualized_return_pct:.2f}%")
    print(f"    Backtest days         : {result.backtest_days}")
    print(f"    Max drawdown          : {result.max_drawdown_pct:.2f}%")
    print(f"    Buy & Hold return     : {result.buy_hold_return_pct:.2f}%")
    print(f"    Buy & Hold annualized : {result.buy_hold_annualized_pct:.2f}%")
    print(f"    Buy & Hold max drawdn : {result.buy_hold_max_drawdown_pct:.2f}%")
    
    print(f"\n  Cycle Summary:")
    print(f"    Total cycles          : {result.num_cycles}")
    print(f"    Put cycles            : {result.num_puts} ({result.num_put_assigned} assigned)")
    print(f"    Call cycles           : {result.num_calls} ({result.num_call_assigned} assigned)")
    
    print(f"\n  {'#' * 86}")
    print(f"  {'#' * 86}")
    print(f"  ANNUALIZED RETURN: {result.annualized_return_pct:.2f}%")
    print(f"  {'#' * 86}")
    print(f"  {'#' * 86}")
    
    # Print cycle table
    print(f"\n  Cycle List:")
    print(f"  {'#':>3} {'Type':>4} {'Entry':>12} {'Price':>8} {'Strike':>7} {'IV%':>6} "
          f"{'Prem':>6} {'Expiry':>12} {'ExpPrice':>8} {'Assign':>6} {'PnL':>10} {'Value':>12} {'B&H':>12} {'Note'}")
    print(f"  {'-'*3} {'-'*4} {'-'*12} {'-'*8} {'-'*7} {'-'*6} {'-'*6} {'-'*12} {'-'*8} {'-'*6} {'-'*10} {'-'*12} {'-'*12} {'-'*30}")
    
    for c in result.cycles:
        assign_str = 'YES' if c.assigned else 'no'
        pnl_str = f"${c.cycle_pnl:+,.2f}"
        val_str = f"${c.portfolio_value:,.2f}"
        bh_str = f"${c.buy_hold_value:,.2f}"
        print(f"  {c.cycle_num:>3} {c.option_type:>4} {c.entry_date:>12} {c.entry_price:>8.2f} "
              f"{c.strike:>7} {c.iv_used:>6.2f} {c.premium_per_share:>6.2f} "
              f"{c.expiry_date:>12} {c.expiry_price:>8.2f} {assign_str:>6} {pnl_str:>10} {val_str:>12} {bh_str:>12} {c.note}")
    
    print()


# ============================================================
# HTML Report
# ============================================================

def generate_html(result: BacktestResult, output_path: str):
    """Generate an HTML report with charts and cycle table."""
    cfg = result.config
    ticker = cfg.ticker
    
    # Prepare data for charts
    labels = [c.entry_date for c in result.cycles]
    portfolio_values = [c.portfolio_value for c in result.cycles]
    buy_hold_values = [c.buy_hold_value for c in result.cycles]
    premiums = [c.premium_total for c in result.cycles]
    pnls = [c.cycle_pnl for c in result.cycles]
    
    # Cycle table rows
    table_rows = []
    for c in result.cycles:
        assign_class = 'assigned' if c.assigned else 'expired'
        assign_text = 'Assigned' if c.assigned else 'Expired'
        pnl_class = 'profit' if c.cycle_pnl >= 0 else 'loss'
        type_class = 'put' if c.option_type == 'PUT' else 'call'
        table_rows.append(f"""
            <tr>
                <td>{c.cycle_num}</td>
                <td class="{type_class}">{c.option_type}</td>
                <td>{c.entry_date}</td>
                <td>${c.entry_price:.2f}</td>
                <td>${c.strike}</td>
                <td>{c.iv_used:.2f}%</td>
                <td>${c.premium_per_share:.2f}</td>
                <td>${c.premium_total:,.2f}</td>
                <td>{c.expiry_date}</td>
                <td>${c.expiry_price:.2f}</td>
                <td class="{assign_class}">{assign_text}</td>
                <td class="{pnl_class}">${c.cycle_pnl:+,.2f}</td>
                <td>${c.portfolio_value:,.2f}</td>
                <td>${c.buy_hold_value:,.2f}</td>
                <td>{c.shares}</td>
                <td class="note">{c.note}</td>
            </tr>""")
    
    table_rows_html = '\n'.join(table_rows)
    
    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QQQ Wheel Strategy Backtest</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #1a1a2e; line-height: 1.6; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
h1 {{ text-align: center; font-size: 28px; margin: 20px 0 5px; color: #1a1a2e; }}
.subtitle {{ text-align: center; color: #666; margin-bottom: 30px; font-size: 14px; }}

.summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
.card {{ background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.card-label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
.card-value {{ font-size: 24px; font-weight: 700; }}
.card-value.profit {{ color: #c0392b; }}
.card-value.loss {{ color: #27ae60; }}
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
.chart-wrapper {{ position: relative; height: 350px; }}

table {{ width: 100%; border-collapse: collapse; font-size: 12px; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
thead {{ background: #2c3e50; color: white; }}
th {{ padding: 12px 8px; text-align: center; font-weight: 600; white-space: nowrap; }}
td {{ padding: 8px; text-align: center; border-bottom: 1px solid #eee; white-space: nowrap; }}
tr:hover {{ background: #f8f9fa; }}
td.put {{ color: #e74c3c; font-weight: 600; }}
td.call {{ color: #2980b9; font-weight: 600; }}
td.assigned {{ color: #e67e22; font-weight: 600; }}
td.expired {{ color: #27ae60; }}
td.profit {{ color: #c0392b; font-weight: 600; }}
td.loss {{ color: #27ae60; font-weight: 600; }}
td.note {{ text-align: left; color: #666; font-size: 11px; }}

.section-title {{ font-size: 20px; font-weight: 700; margin: 30px 0 15px; color: #2c3e50; }}
</style>
</head>
<body>
<div class="container">
    <h1>{ticker} Wheel Strategy Backtest</h1>
    <p class="subtitle">Sell Put (${{cfg.put_otm}} OTM) → if assigned, sell Call (${cfg.call_otm} OTM) → if assigned, back to Put | {cfg.dte}-day DTE</p>

    <div class="highlight-box">
        <div class="label">Annualized Return</div>
        <div class="value">{result.annualized_return_pct:+.2f}%</div>
        <div class="detail">
            Total return: {result.total_return_pct:+.2f}% over {result.backtest_days} days |
            Initial: ${result.initial_capital:,.0f} → Final: ${result.final_value:,.0f} |
            vs Buy&Hold: {result.buy_hold_annualized_pct:+.2f}% annualized
        </div>
    </div>

    <div class="summary-grid">
        <div class="card">
            <div class="card-label">Total Premium Income</div>
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
            <div class="card-sub">Peak to trough</div>
        </div>
        <div class="card">
            <div class="card-label">Buy & Hold Return</div>
            <div class="card-value neutral">{result.buy_hold_return_pct:+.2f}%</div>
            <div class="card-sub">Annualized: {result.buy_hold_annualized_pct:+.2f}%</div>
        </div>
        <div class="card">
            <div class="card-label">B&H Max Drawdown</div>
            <div class="card-value loss">{result.buy_hold_max_drawdown_pct:.2f}%</div>
            <div class="card-sub">vs Wheel: {result.max_drawdown_pct:.2f}%</div>
        </div>
        <div class="card">
            <div class="card-label">Put Cycles</div>
            <div class="card-value neutral">{result.num_puts}</div>
            <div class="card-sub">{result.num_put_assigned} assigned</div>
        </div>
        <div class="card">
            <div class="card-label">Call Cycles</div>
            <div class="card-value neutral">{result.num_calls}</div>
            <div class="card-sub">{result.num_call_assigned} assigned</div>
        </div>
    </div>

    <div class="config-box">
        <h3>Configuration</h3>
        <div class="config-grid">
            <div class="config-item"><span>DTE</span><span>{cfg.dte} days</span></div>
            <div class="config-item"><span>Put OTM</span><span>${{cfg.put_otm}}</span></div>
            <div class="config-item"><span>Call OTM</span><span>${{cfg.call_otm}}</span></div>
            <div class="config-item"><span>Start</span><span>{cfg.start_date}</span></div>
            <div class="config-item"><span>End</span><span>{cfg.end_date}</span></div>
            <div class="config-item"><span>IV Mode</span><span>{cfg.iv_mode}</span></div>
            <div class="config-item"><span>Put IV</span><span>{result.put_iv}%</span></div>
            <div class="config-item"><span>Call IV</span><span>{result.call_iv}%</span></div>
            <div class="config-item"><span>Risk-free Rate</span><span>{cfg.r*100:.1f}%</span></div>
        </div>
    </div>

    <div class="chart-container">
        <h3>Portfolio Value: Wheel Strategy vs Buy &amp; Hold</h3>
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
                <th>Type</th>
                <th>Entry Date</th>
                <th>Entry Price</th>
                <th>Strike</th>
                <th>IV</th>
                <th>Premium/sh</th>
                <th>Premium Total</th>
                <th>Expiry Date</th>
                <th>Expiry Price</th>
                <th>Result</th>
                <th>Cycle PnL</th>
                <th>Wheel Value</th>
                <th>B&H Value</th>
                <th>Shares</th>
                <th>Note</th>
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

// Portfolio value chart - Wheel vs Buy & Hold
new Chart(document.getElementById('portfolioChart'), {{
    type: 'line',
    data: {{
        labels: labels,
        datasets: [
            {{
                label: 'Wheel Strategy',
                data: portfolioValues,
                borderColor: '#667eea',
                backgroundColor: 'rgba(102, 126, 234, 0.1)',
                fill: true,
                tension: 0.1,
                pointRadius: 3,
                pointBackgroundColor: portfolioValues.map((v, i) => {{
                    return i > 0 && v < portfolioValues[i-1] ? '#e74c3c' : '#27ae60';
                }}),
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
                backgroundColor: pnls.map(p => p >= 0 ? 'rgba(192, 57, 43, 0.6)' : 'rgba(39, 174, 96, 0.6)'),
                borderColor: pnls.map(p => p >= 0 ? '#c0392b' : '#27ae60'),
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
    parser = argparse.ArgumentParser(description='Wheel Strategy Backtest')
    parser.add_argument('--dte', type=int, default=10, help='Days to expiry (default: 10)')
    parser.add_argument('--put-otm', type=float, default=15.0, help='Put OTM in dollars (default: 15)')
    parser.add_argument('--call-otm', type=float, default=10.0, help='Call OTM in dollars (default: 10)')
    parser.add_argument('--start', type=str, default='2026-01-01', help='Start date (default: 2026-01-01)')
    parser.add_argument('--end', type=str, default='2026-07-14', help='End date (default: 2026-07-14)')
    parser.add_argument('--iv-mode', type=str, default='fixed', choices=['fixed', 'dynamic'], help='IV mode (default: fixed)')
    parser.add_argument('--report', type=str, default='qqq_wheel_report_v2.html', help='HTML report path')
    parser.add_argument('--data', type=str, default='qqq_data.json', help='Price data JSON file')
    parser.add_argument('--ticker', type=str, default='QQQ', help='Ticker symbol for report title (default: QQQ)')
    
    args = parser.parse_args()
    
    config = Config(
        dte=args.dte,
        put_otm=args.put_otm,
        call_otm=args.call_otm,
        start_date=args.start,
        end_date=args.end,
        iv_mode=args.iv_mode,
        data_file=args.data,
        report_file=args.report,
        ticker=args.ticker
    )
    
    result = simulate(config)
    print_result(result)
    generate_html(result, config.report_file)


if __name__ == '__main__':
    main()
