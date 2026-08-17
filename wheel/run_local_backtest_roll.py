#!/usr/bin/env python3
"""
QQQ Wheel - with EARLY ROLL of the call leg.
============================================
When the stock rises to hit the call strike mid-cycle, instead of the
original "buy on margin" (Action1), we CLOSE the call and ROLL it up
to a higher strike (~3% OTM), so the stock keeps running instead of
being called away at a low strike.

Compares against the baseline (no roll) and Buy & Hold.
"""

import json
import argparse
from datetime import datetime

DATA_DIR = "/Users/gavinz/git/finance/data"
MARGIN_RATE = 0.11
CS = 100


def make_targets(pn, cn, pd, cd):
    return {
        'A': {'put': pn / 100.0, 'call': cn / 100.0},
        'B': {'put': pn / 100.0, 'call': cn / 100.0},
        'C': {'put': pd / 100.0, 'call': cd / 100.0},
        'D': {'put': pn / 100.0, 'call': cn / 100.0},
        'E': {'put': pd / 100.0, 'call': cd / 100.0},
    }


def find_put(puts, target, dte, spot):
    best = None
    for p in puts:
        if p['strike'] > spot:
            continue
        prem = p.get('vw') or p.get('c')
        if prem is None or prem <= 0:
            continue
        ann = prem / p['strike'] * 365.0 / dte
        if best is None or abs(ann - target) < abs(best['ann'] - target):
            best = {'strike': p['strike'], 'prem': prem, 'ann': ann}
    return best


def find_call(calls, target, dte, spot):
    best = None
    for p in calls:
        if p['strike'] < spot:
            continue
        prem = p.get('vw') or p.get('c')
        if prem is None or prem <= 0:
            continue
        ann = prem / spot * 365.0 / dte
        if best is None or abs(ann - target) < abs(best['ann'] - target):
            best = {'strike': p['strike'], 'prem': prem, 'ann': ann}
    return best


def call_price_at(calls, strike):
    """Find the call price (vwap) at a specific strike. Returns None if not found."""
    for p in calls:
        if abs(p['strike'] - strike) < 1e-6:
            prem = p.get('vw') or p.get('c')
            if prem is not None:
                return prem
    return None


def roll_new_strike(calls, spot, buffer_pct):
    """Smallest call strike >= spot*(1+buffer)."""
    target = spot * (1 + buffer_pct / 100.0)
    candidates = [p['strike'] for p in calls if p['strike'] >= target]
    return min(candidates) if candidates else None


def run(ticker, state_targets, roll_buffer=3.0):
    stock = json.load(open(f"{DATA_DIR}/{ticker}_stock.json"))
    options = json.load(open(f"{DATA_DIR}/{ticker}_options.json"))
    dates = [s[0] for s in stock]
    highs = [s[2] for s in stock]
    closes = [s[4] for s in stock]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    chain_map = {c['date']: c for c in options}

    S0 = closes[0]
    initial = 2 * CS * S0
    shares = CS
    cash = CS * S0

    cycles = []
    pvals = []
    total_prem = 0.0
    total_roll_cost = 0.0
    stock_gains = 0.0
    stock_losses = 0.0
    state_counts = {}
    n_rolls = 0

    prev_state = 'A'
    idx = 0

    while idx < len(dates) - 1:
        entry_date = dates[idx]
        chain = chain_map.get(entry_date)
        if chain is None:
            idx += 1
            continue
        spot = chain['spot']
        expiry = chain['expiry']
        dte = max(chain['dte'], 1)
        expiry_idx = date_to_idx.get(expiry)
        if expiry_idx is None:
            for i in range(idx + 1, len(dates)):
                if dates[i] >= expiry:
                    expiry_idx = i
                    break
            if expiry_idx is None:
                expiry_idx = len(dates) - 1
        if expiry_idx <= idx:
            idx += 1
            continue
        expiry_price = closes[expiry_idx]

        portfolio_before = cash + shares * spot

        targets = state_targets[prev_state]
        put_sel = find_put(chain['puts'], targets['put'], dte, spot)
        call_sel = find_call(chain['calls'], targets['call'], dte, spot)
        if put_sel is None or call_sel is None:
            idx = expiry_idx
            continue

        put_strike = put_sel['strike']
        call_strike = call_sel['strike']
        prem = (put_sel['prem'] + call_sel['prem']) * CS
        cash += prem
        total_prem += prem

        # ---- Early roll loop (before expiry) ----
        rolls = 0
        for d in range(idx + 1, expiry_idx):  # strictly before expiry
            if highs[d] < call_strike:
                continue
            chain_d = chain_map.get(dates[d])
            if chain_d is None or chain_d['expiry'] != expiry:
                continue  # can only roll within same expiry
            buyback = call_price_at(chain_d['calls'], call_strike)
            new_strike = roll_new_strike(chain_d['calls'], closes[d], roll_buffer)
            if buyback is None or new_strike is None or new_strike <= call_strike:
                continue
            new_prem = call_price_at(chain_d['calls'], new_strike)
            if new_prem is None:
                continue
            # close old call (buy back) + open new call (sell)
            cash += (new_prem - buyback) * CS
            total_roll_cost += (buyback - new_prem) * CS
            call_strike = new_strike
            rolls += 1

        n_rolls += rolls

        # ---- Expiry ----
        call_ex = expiry_price >= call_strike
        put_ex = expiry_price < put_strike

        if put_ex:
            cash -= put_strike * CS
            shares += CS  # 200
            result_state = 'E'
            cash += expiry_price * CS  # sell 100 to normalize
            shares -= CS
        elif call_ex:
            # call assigned at (rolled) strike, rebuy at market
            cash += call_strike * CS
            shares -= CS
            cash -= expiry_price * CS
            shares += CS
            result_state = 'A'
        else:
            result_state = 'A'

        portfolio_after = cash + shares * expiry_price
        cycle_pnl = portfolio_after - portfolio_before
        stock_pnl = cycle_pnl - prem + 0
        pvals.append(portfolio_after)
        if stock_pnl >= 0:
            stock_gains += stock_pnl
        else:
            stock_losses += abs(stock_pnl)
        state_counts[result_state] = state_counts.get(result_state, 0) + 1

        cycles.append({
            'entry': entry_date, 'expiry': expiry, 'spot': round(spot, 2),
            'exp_px': round(expiry_price, 2), 'put': put_strike,
            'final_call': call_strike, 'rolls': rolls,
            'prem': round(prem, 0), 'pnl': round(cycle_pnl, 0),
            'state': result_state, 'value': round(portfolio_after, 0),
        })

        prev_state = result_state
        idx = expiry_idx

    last_price = closes[-1]
    final_value = cash + shares * last_price
    total_return = (final_value - initial) / initial
    days = (datetime.strptime(dates[-1], '%Y-%m-%d') -
            datetime.strptime(dates[0], '%Y-%m-%d')).days
    ann = (1 + total_return) ** (365.0 / days) - 1 if days > 0 else 0
    bh_ret = (closes[-1] - S0) / S0
    bh_ann = (1 + bh_ret) ** (365.0 / days) - 1 if days > 0 else 0

    max_dd = 0.0
    peak = pvals[0] if pvals else initial
    for pv in pvals:
        peak = max(peak, pv)
        max_dd = max(max_dd, (peak - pv) / peak)

    return {
        'initial': initial, 'final': final_value,
        'total_ret': total_return * 100, 'ann': ann * 100, 'dd': max_dd * 100,
        'bh_ret': bh_ret * 100, 'bh_ann': bh_ann * 100,
        'cycles': len(cycles), 'rolls': n_rolls,
        'premium': total_prem, 'roll_cost': total_roll_cost,
        'gains': stock_gains, 'losses': stock_losses,
        'states': state_counts, 'cycle_list': cycles,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', default='QQQ')
    ap.add_argument('--targets', default='50,3,20,5')
    ap.add_argument('--roll-buffer', type=float, default=3.0)
    args = ap.parse_args()
    pn, cn, pd, cd = [int(x) for x in args.targets.split(',')]
    r = run(args.ticker, make_targets(pn, cn, pd, cd), args.roll_buffer)
    print(f"=== {args.ticker} WHEEL + 提前滚动call (buffer {args.roll_buffer}%) ===")
    print(f"  总收益 {r['total_ret']:.2f}%  年化 {r['ann']:.2f}%  回撤 {r['dd']:.2f}%")
    print(f"  B&H    {r['bh_ret']:.2f}%  年化 {r['bh_ann']:.2f}%")
    print(f"  周期 {r['cycles']}  滚动次数 {r['rolls']}  权利金 \${r['premium']:,.0f}  滚动成本 \${r['roll_cost']:,.0f}")
    print(f"  状态 {r['states']}")


if __name__ == '__main__':
    main()
