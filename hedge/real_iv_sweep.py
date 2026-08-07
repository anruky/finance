#!/usr/bin/env python3
"""
Real IV Parameter Sweep for DRAM ETF Hedge Strategy
====================================================
Uses actual market implied volatility (from Barchart/Yahoo Finance) interpolated
per cycle entry date, instead of a fixed vol_override assumption.

Sweeps: strike% x num_puts x holding_period to find the true optimal parameters.
"""
import math
import csv
import json
from datetime import datetime, timedelta
from itertools import product

# ============================================================
# Black-Scholes
# ============================================================

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_put(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return max(K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1), 0.0)

# ============================================================
# Real IV data (from Barchart + Yahoo Finance snapshots)
# ============================================================

IV_DATA_POINTS = {
    '2026-04-02': 0.65,
    '2026-04-07': 0.6552,
    '2026-04-27': 0.8243,
    '2026-05-15': 0.85,
    '2026-06-01': 0.90,
    '2026-06-23': 0.96,
    '2026-07-10': 0.9610,
    '2026-07-20': 1.0981,
    '2026-07-31': 1.00,
    '2026-08-05': 1.0189,
}

def estimate_iv(date_str):
    """Linear interpolate IV from known Barchart data points."""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    sorted_points = sorted(IV_DATA_POINTS.items(), key=lambda x: x[0])
    for i, (dp_date, dp_iv) in enumerate(sorted_points):
        dp = datetime.strptime(dp_date, '%Y-%m-%d')
        if d <= dp:
            if i == 0:
                return dp_iv
            prev_date, prev_iv = sorted_points[i - 1]
            prev_d = datetime.strptime(prev_date, '%Y-%m-%d')
            frac = (d - prev_d).days / (dp - prev_d).days
            return prev_iv + frac * (dp_iv - prev_iv)
    return sorted_points[-1][1]

# ============================================================
# Load real DRAM price data
# ============================================================

dates = []
prices = []
with open('/Users/gavinz/git/finance/hedge/dram_price_data.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        dates.append(row['date'])
        prices.append(float(row['close']))

date_ts = [datetime.strptime(d, '%Y-%m-%d') for d in dates]
N = len(dates)

print(f"Loaded {N} trading days: {dates[0]} to {dates[-1]}")
print(f"Price range: ${min(prices):.2f} - ${max(prices):.2f}")
print(f"Start: ${prices[0]:.2f}, End: ${prices[-1]:.2f}")

# ============================================================
# Simulation with per-cycle real IV
# ============================================================

def run_sim(strike_pct, num_puts, cal_days, iv_mode='real', fixed_iv=None):
    """
    Run simulation.
    iv_mode='real': use interpolated market IV per cycle
    iv_mode='fixed': use fixed_iv for all cycles
    """
    RISK_FREE = 0.045
    SHARES = 100
    CONTRACT_SIZE = 100

    trades = []
    i = 0
    while i < N:
        entry_date = dates[i]
        entry_price = prices[i]

        if iv_mode == 'real':
            iv = estimate_iv(entry_date)
        else:
            iv = fixed_iv

        # Find exit date
        target_exit = date_ts[i] + timedelta(days=cal_days)
        exit_idx = i
        for j in range(i + 1, N):
            if date_ts[j] <= target_exit:
                exit_idx = j
            else:
                break
        if exit_idx == i:
            exit_idx = min(i + 1, N - 1)
        if exit_idx <= i:
            break

        exit_date = dates[exit_idx]
        exit_price = prices[exit_idx]
        strike = entry_price * (1.0 - strike_pct)

        T = cal_days / 365.0
        bs_price = bs_put(entry_price, strike, T, RISK_FREE, iv)
        premium_per_contract = bs_price * CONTRACT_SIZE
        premium_total = num_puts * premium_per_contract

        stock_pnl = (exit_price - entry_price) * SHARES
        put_shares_covered = num_puts * CONTRACT_SIZE

        if exit_price < strike:
            put_payoff = (strike - exit_price) * put_shares_covered
            scenario = "ITM"
        else:
            put_payoff = 0.0
            scenario = "OTM"

        total_pnl = stock_pnl + put_payoff - premium_total
        return_pct = total_pnl / (entry_price * SHARES) * 100
        actual_cal_days = (date_ts[exit_idx] - date_ts[i]).days

        trades.append({
            'cycle': len(trades),
            'entry_date': entry_date,
            'entry_price': round(entry_price, 2),
            'exit_date': exit_date,
            'exit_price': round(exit_price, 2),
            'cal_days': actual_cal_days,
            'iv': round(iv * 100, 1),
            'strike': round(strike, 2),
            'premium': round(premium_total, 2),
            'stock_pnl': round(stock_pnl, 2),
            'put_payoff': round(put_payoff, 2),
            'total_pnl': round(total_pnl, 2),
            'return_pct': round(return_pct, 2),
            'scenario': scenario,
        })
        i = exit_idx + 1

    # Summary
    total_cycles = len(trades)
    if total_cycles == 0:
        return None

    itm_cycles = sum(1 for t in trades if t['scenario'] == 'ITM')
    otm_cycles = total_cycles - itm_cycles
    total_pnl = sum(t['total_pnl'] for t in trades)
    total_premium = sum(t['premium'] for t in trades)
    total_payoff = sum(t['put_payoff'] for t in trades)
    total_stock_pnl = sum(t['stock_pnl'] for t in trades)
    win_cycles = sum(1 for t in trades if t['total_pnl'] > 0)

    stock_cost = trades[0]['entry_price'] * SHARES
    first_premium = trades[0]['premium']
    initial_capital = stock_cost + first_premium
    strategy_return = total_pnl / initial_capital * 100

    first_price = trades[0]['entry_price']
    last_price = trades[-1]['exit_price']
    bh_pnl = (last_price - first_price) * SHARES
    bh_return = bh_pnl / initial_capital * 100

    first_dt = datetime.strptime(trades[0]['entry_date'], '%Y-%m-%d')
    last_dt = datetime.strptime(trades[-1]['exit_date'], '%Y-%m-%d')
    span_days = max((last_dt - first_dt).days, 1)
    years = span_days / 365.0
    ann_strategy = strategy_return / years if years < 1 else ((1 + strategy_return / 100) ** (1 / years) - 1) * 100
    ann_bh = bh_return / years if years < 1 else ((1 + bh_return / 100) ** (1 / years) - 1) * 100

    return {
        'strike_pct': strike_pct,
        'num_puts': num_puts,
        'cal_days': cal_days,
        'iv_mode': iv_mode,
        'total_pnl': round(total_pnl, 2),
        'strategy_return_pct': round(strategy_return, 2),
        'annualized_return_pct': round(ann_strategy, 2),
        'bh_pnl': round(bh_pnl, 2),
        'bh_return_pct': round(bh_return, 2),
        'bh_annualized_pct': round(ann_bh, 2),
        'win_rate_pct': round(win_cycles / total_cycles * 100, 1),
        'total_cycles': total_cycles,
        'itm_cycles': itm_cycles,
        'otm_cycles': otm_cycles,
        'total_premium': round(total_premium, 2),
        'total_payoff': round(total_payoff, 2),
        'total_stock_pnl': round(total_stock_pnl, 2),
        'net_hedge': round(total_payoff - total_premium, 2),
        'initial_capital': round(initial_capital, 2),
        'final_capital': round(initial_capital + total_pnl, 2),
        'hedge_cost_pct': round(total_premium / initial_capital * 100, 2),
        'vs_bh': round(total_pnl - bh_pnl, 2),
        'trades': trades,
    }

# ============================================================
# SWEEP 1: Real IV - Full grid
# ============================================================

print("\n" + "=" * 110)
print("  REAL IV PARAMETER SWEEP")
print("  Using interpolated market IV (65.5% - 109.8%) from Barchart")
print("=" * 110)

strikes = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
puts_list = [0, 1, 2, 3, 4, 5]
periods = [5, 14, 21]  # 1wk, 2wk, 3wk

all_results = []
total_combos = len(strikes) * len(puts_list) * len(periods)
combo_count = 0

for sp in strikes:
    for np_ in puts_list:
        for pd in periods:
            combo_count += 1
            r = run_sim(sp, np_, pd, iv_mode='real')
            if r:
                all_results.append(r)

print(f"\n  Tested {len(all_results)} combinations with real IV\n")

# ============================================================
# Rankings
# ============================================================

print("=" * 110)
print("  TOP 20 BY TOTAL P&L (Real IV)")
print("=" * 110)
print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'P&L':>10} {'Return%':>9} {'Ann%':>9} {'B&H%':>8} {'vsB&H':>9} {'Win%':>6} {'ITM':>6} {'Premium':>10} {'NetHedge':>10} {'HedgeCost%':>11}")
print("-" * 130)

sorted_pnl = sorted(all_results, key=lambda x: x['total_pnl'], reverse=True)
for i, r in enumerate(sorted_pnl[:20]):
    print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['cal_days']:>5} ${r['total_pnl']:>9,.0f} {r['strategy_return_pct']:>+8.2f}% {r['annualized_return_pct']:>+8.2f}% {r['bh_return_pct']:>+7.2f}% ${r['vs_bh']:>+8,.0f} {r['win_rate_pct']:>5.0f}% {r['itm_cycles']:>3}/{r['total_cycles']:<2} ${r['total_premium']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['hedge_cost_pct']:>10.1f}%")

# ============================================================
# Best that beats B&H
# ============================================================
print("\n" + "=" * 110)
print("  COMBINATIONS THAT BEAT BUY & HOLD (Real IV)")
print("=" * 110)
beat_bh = [r for r in all_results if r['vs_bh'] > 0]
beat_bh.sort(key=lambda x: x['vs_bh'], reverse=True)
print(f"  Found {len(beat_bh)} combinations that beat B&H\n")
if beat_bh:
    print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'P&L':>10} {'Return%':>9} {'B&H%':>8} {'vsB&H':>9} {'Win%':>6} {'ITM':>6} {'Premium':>10} {'NetHedge':>10}")
    print("-" * 110)
    for i, r in enumerate(beat_bh[:20]):
        print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['cal_days']:>5} ${r['total_pnl']:>9,.0f} {r['strategy_return_pct']:>+8.2f}% {r['bh_return_pct']:>+7.2f}% ${r['vs_bh']:>+8,.0f} {r['win_rate_pct']:>5.0f}% {r['itm_cycles']:>3}/{r['total_cycles']:<2} ${r['total_premium']:>9,.0f} ${r['net_hedge']:>9,.0f}")

# ============================================================
# Best profitable with decent win rate
# ============================================================
print("\n" + "=" * 110)
print("  BEST BALANCED (P&L > 0, Win >= 40%, sorted by P&L)")
print("=" * 110)
balanced = [r for r in all_results if r['total_pnl'] > 0 and r['win_rate_pct'] >= 40]
balanced.sort(key=lambda x: x['total_pnl'], reverse=True)
print(f"  Found {len(balanced)} balanced combinations\n")
if balanced:
    print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'P&L':>10} {'Return%':>9} {'Win%':>6} {'vsB&H':>9} {'ITM':>6} {'Premium':>10} {'NetHedge':>10} {'HedgeCost%':>11}")
    print("-" * 120)
    for i, r in enumerate(balanced[:20]):
        print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['cal_days']:>5} ${r['total_pnl']:>9,.0f} {r['strategy_return_pct']:>+8.2f}% {r['win_rate_pct']:>5.0f}% ${r['vs_bh']:>+8,.0f} {r['itm_cycles']:>3}/{r['total_cycles']:<2} ${r['total_premium']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['hedge_cost_pct']:>10.1f}%")
else:
    print("  (No combinations met both P&L > 0 and Win >= 40%)")

# ============================================================
# Best profitable regardless of win rate
# ============================================================
print("\n" + "=" * 110)
print("  ALL PROFITABLE COMBINATIONS (P&L > 0, sorted by P&L)")
print("=" * 110)
profitable = [r for r in all_results if r['total_pnl'] > 0]
profitable.sort(key=lambda x: x['total_pnl'], reverse=True)
print(f"  Found {len(profitable)} profitable combinations\n")
if profitable:
    print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'P&L':>10} {'Return%':>9} {'Win%':>6} {'vsB&H':>9} {'ITM':>6} {'Premium':>10} {'NetHedge':>10}")
    print("-" * 115)
    for i, r in enumerate(profitable[:20]):
        print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['cal_days']:>5} ${r['total_pnl']:>9,.0f} {r['strategy_return_pct']:>+8.2f}% {r['win_rate_pct']:>5.0f}% ${r['vs_bh']:>+8,.0f} {r['itm_cycles']:>3}/{r['total_cycles']:<2} ${r['total_premium']:>9,.0f} ${r['net_hedge']:>9,.0f}")

# ============================================================
# SWEEP 2: Sensitivity - what IV level makes the strategy viable?
# ============================================================
print("\n\n" + "=" * 110)
print("  IV SENSITIVITY ANALYSIS")
print("  Using best structural params (3% strike, 3 puts, 5d) with different fixed IV levels")
print("=" * 110)
print(f"{'IV':>8} {'P&L':>10} {'Return%':>9} {'B&H%':>8} {'vsB&H':>9} {'Win%':>6} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'HedgeCost%':>11}")
print("-" * 110)

for iv in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10]:
    r = run_sim(0.03, 3, 5, iv_mode='fixed', fixed_iv=iv)
    if r:
        print(f"{iv*100:>7.0f}% ${r['total_pnl']:>9,.0f} {r['strategy_return_pct']:>+8.2f}% {r['bh_return_pct']:>+7.2f}% ${r['vs_bh']:>+8,.0f} {r['win_rate_pct']:>5.0f}% ${r['total_premium']:>9,.0f} ${r['total_payoff']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['hedge_cost_pct']:>10.1f}%")

# Also test with real IV
r_real = run_sim(0.03, 3, 5, iv_mode='real')
if r_real:
    print(f"{'real':>7} ${r_real['total_pnl']:>9,.0f} {r_real['strategy_return_pct']:>+8.2f}% {r_real['bh_return_pct']:>+7.2f}% ${r_real['vs_bh']:>+8,.0f} {r_real['win_rate_pct']:>5.0f}% ${r_real['total_premium']:>9,.0f} ${r_real['total_payoff']:>9,.0f} ${r_real['net_hedge']:>9,.0f} {r_real['hedge_cost_pct']:>10.1f}%")

# ============================================================
# SWEEP 3: For each fixed IV level, find best params
# ============================================================
print("\n" + "=" * 110)
print("  BEST PARAMS AT EACH IV LEVEL")
print("=" * 110)

for iv in [0.50, 0.60, 0.65, 0.70, 0.80, 0.90, 1.00, 'real']:
    if iv == 'real':
        results_iv = [r for r in all_results]
        label = 'Real IV (65-110%)'
    else:
        results_iv = []
        for sp in strikes:
            for np_ in puts_list:
                for pd in periods:
                    r = run_sim(sp, np_, pd, iv_mode='fixed', fixed_iv=iv)
                    if r:
                        results_iv.append(r)
        label = f'{iv*100:.0f}% IV'

    best = max(results_iv, key=lambda x: x['total_pnl'])
    print(f"\n  {label}:")
    print(f"    Best: Strike={best['strike_pct']*100:.0f}% Puts={best['num_puts']} Days={best['cal_days']}")
    print(f"    P&L=${best['total_pnl']:,.0f} Return={best['strategy_return_pct']:+.2f}% Win={best['win_rate_pct']:.0f}% vsB&H=${best['vs_bh']:+,.0f} Premium=${best['total_premium']:,.0f} NetHedge=${best['net_hedge']:,.0f}")

# ============================================================
# Save results to JSON
# ============================================================

output = {
    'real_iv_sweep': sorted_pnl[:20],
    'beat_bh': beat_bh[:20],
    'balanced': balanced[:20],
    'profitable': profitable[:20],
    'all_results_count': len(all_results),
}

with open('/tmp/real_iv_sweep_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("\n\n" + "=" * 110)
print("  SWEEP COMPLETE")
print(f"  Results saved to /tmp/real_iv_sweep_results.json")
print("=" * 110)
