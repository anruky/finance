#!/usr/bin/env python3
"""
QQQ Wheel Strategy - REAL option prices backtest
=================================================
Reimplements the Gav wheel strategy state machine, but replaces the
Black-Scholes simulated premiums with REAL historical option prices
(pulled from Polygon/Massive, stored in qqq_real_chains_dte*.json).

State machine is identical to wheel_strategy_gav.py:
  A/B/C/D/E with normalization to A each cycle, Action1 margin trigger.

Usage:
  python3 wheel_strategy_real.py --dte 7 --targets 60,4,10,20
"""

import json
import argparse
from datetime import datetime

DATA = 'qqq_data_2025_2026.json'
MARGIN_RATE = 0.11
CS = 100  # contract size


def load_prices():
    raw = json.load(open(DATA))
    data = [(r[0], r[1], r[2], r[3], r[4]) for r in raw]
    data.sort(key=lambda x: x[0])
    return data


def make_targets(pn, cn, pd, cd):
    return {
        'A': {'put': pn / 100.0, 'call': cn / 100.0},
        'B': {'put': pn / 100.0, 'call': cn / 100.0},
        'C': {'put': pd / 100.0, 'call': cd / 100.0},
        'D': {'put': pn / 100.0, 'call': cn / 100.0},
        'E': {'put': pd / 100.0, 'call': cd / 100.0},
    }


def find_real_put(puts, target, dte, spot):
    """Find OTM put strike (<=spot) whose annualized premium (prem/strike*365/dte) is closest to target."""
    best = None
    for p in puts:
        if p['strike'] > spot:
            continue  # only OTM/ATM puts
        prem = p.get('vw')
        if prem is None:
            prem = p.get('c')
        if prem is None or prem <= 0:
            continue
        ann = prem / p['strike'] * 365.0 / dte
        if best is None or abs(ann - target) < abs(best['ann'] - target):
            best = {'strike': p['strike'], 'prem': prem, 'ann': ann, 'vol': p.get('v', 0)}
    return best


def find_real_call(calls, target, dte, spot):
    """Find OTM call strike (>=spot) whose annualized premium (prem/spot*365/dte) is closest to target."""
    best = None
    for p in calls:
        if p['strike'] < spot:
            continue  # only OTM/ATM calls
        prem = p.get('vw')
        if prem is None:
            prem = p.get('c')
        if prem is None or prem <= 0:
            continue
        ann = prem / spot * 365.0 / dte
        if best is None or abs(ann - target) < abs(best['ann'] - target):
            best = {'strike': p['strike'], 'prem': prem, 'ann': ann, 'vol': p.get('v', 0)}
    return best


def run(dte, chains_file, state_targets):
    prices = load_prices()
    dates = [d[0] for d in prices]
    closes = [d[4] for d in prices]
    highs = [d[2] for d in prices]
    date_to_idx = {d: i for i, d in enumerate(dates)}

    chains = json.load(open(chains_file))

    S0 = closes[0]
    initial_capital = 2 * CS * S0
    shares = CS
    cash = CS * S0

    cycles = []
    portfolio_values = []
    total_prem_sum = 0.0
    total_margin_interest = 0.0
    stock_gains = 0.0
    stock_losses = 0.0
    state_counts = {}
    num_action1 = 0

    prev_state = 'A'

    for cyc in chains:
        entry_date = cyc['entry_date']
        entry_price = cyc['entry_price']
        expiry_date = cyc['expiry_date']
        dte_real = cyc['dte']
        if dte_real <= 0:
            dte_real = 1

        # Map to price indices
        if entry_date not in date_to_idx:
            continue
        entry_idx = date_to_idx[entry_date]
        # expiry: real Friday might not be a trading day (holiday) -> nearest trading day
        if expiry_date in date_to_idx:
            expiry_idx = date_to_idx[expiry_date]
        else:
            # find nearest trading day >= expiry_date
            expiry_idx = None
            for i in range(entry_idx + 1, len(dates)):
                if dates[i] >= expiry_date:
                    expiry_idx = i
                    break
            if expiry_idx is None:
                expiry_idx = len(dates) - 1
        expiry_price = closes[expiry_idx]

        portfolio_before = cash + shares * entry_price

        targets = state_targets[prev_state]
        put_target = targets['put']
        call_target = targets['call']

        put_sel = find_real_put(cyc['puts'], put_target, dte_real, entry_price)
        call_sel = find_real_call(cyc['calls'], call_target, dte_real, entry_price)

        if put_sel is None or call_sel is None:
            # skip cycle if we can't find valid strikes (shouldn't happen)
            continue

        put_strike = put_sel['strike']
        put_prem = put_sel['prem']
        call_strike = call_sel['strike']
        call_prem = call_sel['prem']

        total_prem = (put_prem + call_prem) * CS
        cash += total_prem
        total_prem_sum += total_prem

        # Action 1: daily monitor
        action1_triggered = False
        action1_date = ''
        margin_loan = 0.0
        margin_interest = 0.0
        for day_idx in range(entry_idx + 1, expiry_idx + 1):
            if highs[day_idx] >= call_strike:
                action1_triggered = True
                action1_date = dates[day_idx]
                margin_loan = call_strike * CS
                shares += CS
                break

        if action1_triggered:
            days_holding = (datetime.strptime(expiry_date, '%Y-%m-%d') -
                            datetime.strptime(action1_date, '%Y-%m-%d')).days
            margin_interest = margin_loan * MARGIN_RATE * (max(days_holding, 1) / 365.0)
            total_margin_interest += margin_interest
            num_action1 += 1

        call_exercised = expiry_price >= call_strike
        put_exercised = expiry_price < put_strike

        if action1_triggered:
            if call_exercised:
                cash += call_strike * CS
                shares -= CS
                result_state = 'B'
                cash -= margin_loan + margin_interest
            elif put_exercised:
                cash -= put_strike * CS
                shares += CS
                result_state = 'C'
                cash += 2 * expiry_price * CS - margin_loan - margin_interest
                shares -= 2 * CS
            else:
                result_state = 'D'
                cash += expiry_price * CS - margin_loan - margin_interest
                shares -= CS
        else:
            if put_exercised:
                cash -= put_strike * CS
                shares += CS
                result_state = 'E'
                cash += expiry_price * CS
                shares -= CS
            elif call_exercised:
                cash += call_strike * CS
                shares -= CS
                cash -= expiry_price * CS
                shares += CS
                result_state = 'A'
            else:
                result_state = 'A'

        portfolio_after = cash + shares * expiry_price
        cycle_pnl = portfolio_after - portfolio_before
        stock_pnl = cycle_pnl - total_prem + margin_interest
        portfolio_values.append(portfolio_after)

        if stock_pnl >= 0:
            stock_gains += stock_pnl
        else:
            stock_losses += abs(stock_pnl)

        state_counts[result_state] = state_counts.get(result_state, 0) + 1

        cycles.append({
            'entry_date': entry_date, 'expiry_date': expiry_date, 'dte': dte_real,
            'entry_price': entry_price, 'expiry_price': expiry_price,
            'put_strike': put_strike, 'put_prem': put_prem, 'put_ann': put_sel['ann'],
            'call_strike': call_strike, 'call_prem': call_prem, 'call_ann': call_sel['ann'],
            'total_prem': round(total_prem, 2), 'action1': action1_triggered,
            'result_state': result_state, 'pnl': round(cycle_pnl, 2),
            'portfolio': round(portfolio_after, 2),
        })

        prev_state = result_state

    # Final stats
    last_price = closes[-1]
    final_value = cash + shares * last_price
    total_return = (final_value - initial_capital) / initial_capital
    backtest_days = (datetime.strptime(dates[-1], '%Y-%m-%d') -
                     datetime.strptime(dates[0], '%Y-%m-%d')).days
    annualized = (1 + total_return) ** (365.0 / backtest_days) - 1 if backtest_days > 0 else 0

    buy_hold_return = (closes[-1] - S0) / S0
    buy_hold_ann = (1 + buy_hold_return) ** (365.0 / backtest_days) - 1 if backtest_days > 0 else 0

    max_dd = 0.0
    peak = portfolio_values[0] if portfolio_values else initial_capital
    for pv in portfolio_values:
        if pv > peak:
            peak = pv
        dd = (peak - pv) / peak
        if dd > max_dd:
            max_dd = dd

    return {
        'initial_capital': round(initial_capital, 2),
        'final_value': round(final_value, 2),
        'total_return_pct': round(total_return * 100, 2),
        'annualized_pct': round(annualized * 100, 2),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'buy_hold_return_pct': round(buy_hold_return * 100, 2),
        'buy_hold_annualized_pct': round(buy_hold_ann * 100, 2),
        'num_cycles': len(cycles),
        'num_action1': num_action1,
        'total_premium': round(total_prem_sum, 2),
        'total_margin_interest': round(total_margin_interest, 2),
        'stock_gains': round(stock_gains, 2),
        'stock_losses': round(stock_losses, 2),
        'state_counts': state_counts,
        'cycles': cycles,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dte', type=int, default=7)
    ap.add_argument('--targets', type=str, default='60,4,10,20',
                    help='pn,cn,pd,cd (A/B/D put, A/B/D call, C/E put, C/E call)')
    ap.add_argument('--chains', type=str, default='')
    args = ap.parse_args()

    pn, cn, pd, cd = [int(x) for x in args.targets.split(',')]
    chains_file = args.chains or f'qqq_real_chains_dte{args.dte}.json'

    r = run(args.dte, chains_file, make_targets(pn, cn, pd, cd))

    print("=" * 70)
    print(f"  QQQ WHEEL - REAL OPTION PRICES (DTE={args.dte})")
    print("=" * 70)
    print(f"  Targets: A/B/D put {pn}% call {cn}% | C/E put {pd}% call {cd}%")
    print(f"  Initial capital : ${r['initial_capital']:,.0f}")
    print(f"  Final value     : ${r['final_value']:,.0f}")
    print(f"  Total return    : {r['total_return_pct']}%")
    print(f"  Annualized      : {r['annualized_pct']}%")
    print(f"  Max drawdown    : {r['max_drawdown_pct']}%")
    print(f"  Buy & Hold      : {r['buy_hold_return_pct']}% ({r['buy_hold_annualized_pct']}% ann)")
    print(f"  Cycles          : {r['num_cycles']}  (Action1: {r['num_action1']})")
    print(f"  Premium income  : ${r['total_premium']:,.0f}")
    print(f"  Margin interest : ${r['total_margin_interest']:,.0f}")
    print(f"  Stock gains     : ${r['stock_gains']:,.0f}")
    print(f"  Stock losses    : ${r['stock_losses']:,.0f}")
    print(f"  States          : {r['state_counts']}")


if __name__ == '__main__':
    main()
