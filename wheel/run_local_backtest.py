#!/usr/bin/env python3
"""
QQQ Wheel Strategy - run with LOCAL real option data (2 years).
=============================================================
Reads /Users/gavinz/git/finance/data/{TICKER}_stock.json and
{TICKER}_options.json, runs the Gav wheel state machine using REAL
option prices, and compares against Buy & Hold.

The daily chains use "next Friday" expiry (standard weekly options).
Weekly wheel = enter on the trading day after each Friday expiry.

Usage:
  python3 run_local_backtest.py --ticker QQQ [--targets 60,4,10,20]
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


def find_real_put(puts, target, dte, spot):
    best = None
    for p in puts:
        if p['strike'] > spot:
            continue
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
    best = None
    for p in calls:
        if p['strike'] < spot:
            continue
        prem = p.get('vw')
        if prem is None:
            prem = p.get('c')
        if prem is None or prem <= 0:
            continue
        ann = prem / spot * 365.0 / dte
        if best is None or abs(ann - target) < abs(best['ann'] - target):
            best = {'strike': p['strike'], 'prem': prem, 'ann': ann, 'vol': p.get('v', 0)}
    return best


def strike_step(spot):
    if spot < 100:
        return 1.0
    elif spot < 400:
        return 2.5
    else:
        return 5.0


def find_call_prem_near(calls, strike):
    """Find the nearest call contract's premium at/near a given strike."""
    best = None
    for p in calls:
        prem = p.get('vw')
        if prem is None:
            prem = p.get('c')
        if prem is None or prem <= 0:
            continue
        if best is None or abs(p['strike'] - strike) < abs(best['strike'] - strike):
            best = {'strike': p['strike'], 'prem': prem}
    return best


def run(ticker, state_targets, min_vol=0, options_file=None,
        buy_call_otm=0.01, buy_call_num=2):
    stock = json.load(open(f"{DATA_DIR}/{ticker}_stock.json"))
    if options_file is None:
        options_file = f"{ticker}_options.json"
    options = json.load(open(f"{DATA_DIR}/{options_file}"))

    dates = [s[0] for s in stock]
    opens = [s[1] for s in stock]
    highs = [s[2] for s in stock]
    closes = [s[4] for s in stock]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    chain_map = {c['date']: c for c in options}

    # Align stock data with options data: trim stock to start at the first option chain date
    # (so S0 / initial capital match the actual backtest start, not an earlier stock date)
    first_opt_date = options[0]['date']
    if first_opt_date in date_to_idx:
        start_idx = date_to_idx[first_opt_date]
        stock = stock[start_idx:]
        dates = [s[0] for s in stock]
        opens = [s[1] for s in stock]
        highs = [s[2] for s in stock]
        closes = [s[4] for s in stock]
        date_to_idx = {d: i for i, d in enumerate(dates)}

    S0 = closes[0]
    initial_capital = 2 * CS * S0
    shares = CS
    cash = CS * S0

    cycles = []
    portfolio_values = []
    total_prem = 0.0
    total_call_cost = 0.0
    total_call_value = 0.0
    stock_gains = 0.0
    stock_losses = 0.0
    state_counts = {}
    num_action1 = 0

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
        # expiry index (nearest trading day >= expiry)
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
        put_sel = find_real_put(chain['puts'], targets['put'], dte, spot)
        call_sel = find_real_call(chain['calls'], targets['call'], dte, spot)
        if put_sel is None or call_sel is None:
            # 空链（节假日等）：延后到下一个交易日再卖，不跳过整个周期
            idx += 1
            continue

        put_strike = put_sel['strike']
        call_strike = call_sel['strike']
        put_prem = put_sel['prem']
        call_prem = call_sel['prem']
        prem = (put_prem + call_prem) * CS
        cash += prem
        total_prem += prem

        # Action 1：股价触及 call 价 → 买 2 手 1% OTM call（不融资买股票）
        step = strike_step(spot)
        action1 = False
        action1_date = ''
        buy_call_strike = 0.0
        buy_call_cost = 0.0
        for d in range(idx + 1, expiry_idx + 1):
            if highs[d] >= call_strike:
                action1 = True
                action1_date = dates[d]
                # 买 buy_call_num 手 buy_call_otm OTM call（行权价 = call_strike * (1+otm)，取整到档位）
                buy_call_strike = round(call_strike * (1 + buy_call_otm) / step) * step
                sel = find_call_prem_near(chain['calls'], buy_call_strike)
                if sel is not None:
                    buy_call_strike = sel['strike']
                    buy_call_cost = buy_call_num * sel['prem'] * CS
                else:
                    buy_call_cost = 0.0
                cash -= buy_call_cost
                total_call_cost += buy_call_cost
                num_action1 += 1
                break

        call_ex = expiry_price >= call_strike
        put_ex = expiry_price < put_strike

        # 买 call 到期价值（内在价值）
        buy_call_value = 0.0
        if action1 and buy_call_strike > 0:
            buy_call_value = max(expiry_price - buy_call_strike, 0.0) * buy_call_num * CS
        total_call_value += buy_call_value

        if action1:
            if call_ex:
                # 卖 call 被行权，交割 1 手股票 → 0 手股票 + 现金
                cash += call_strike * CS
                shares -= CS
                result_state = 'B'
                cash += buy_call_value
            elif put_ex:
                # 卖 put 被行权，买入 1 手股票 → 2 手股票
                cash -= put_strike * CS
                shares += CS
                result_state = 'C'
            else:
                # 都没行权 → 1 手股票 + 1 手现金
                result_state = 'D'
        else:
            if put_ex:
                # 卖 put 被行权，买入 1 手股票 → 2 手股票
                cash -= put_strike * CS
                shares += CS
                result_state = 'E'
            elif call_ex:
                # 防御分支（股价触及 call_strike 时 action1 必已触发，通常不会到）
                cash += call_strike * CS
                shares -= CS
                cash -= expiry_price * CS
                shares += CS
                result_state = 'A'
            else:
                result_state = 'A'

        # 下一周期开始前归一化持仓到 1 手股票 + 1 手现金
        if result_state == 'B':
            # 0 手股票 → 买回 1 手
            shares += CS
            cash -= expiry_price * CS
        elif result_state in ('C', 'E'):
            # 2 手股票 → 卖出 1 手
            shares -= CS
            cash += expiry_price * CS

        portfolio_after = cash + shares * expiry_price
        cycle_pnl = portfolio_after - portfolio_before
        stock_pnl = cycle_pnl - prem + buy_call_cost - buy_call_value
        portfolio_values.append(portfolio_after)
        if stock_pnl >= 0:
            stock_gains += stock_pnl
        else:
            stock_losses += abs(stock_pnl)
        state_counts[result_state] = state_counts.get(result_state, 0) + 1

        cycles.append({
            'entry': entry_date, 'expiry': expiry, 'dte': dte,
            'spot': round(spot, 2), 'exp_px': round(expiry_price, 2),
            'put': put_strike, 'call': call_strike,
            'prem': round(prem, 0), 'action1': action1, 'state': result_state,
            'buy_call_strike': buy_call_strike,
            'buy_call_cost': round(buy_call_cost, 0),
            'buy_call_value': round(buy_call_value, 0),
            'pnl': round(cycle_pnl, 0), 'value': round(portfolio_after, 0),
        })

        prev_state = result_state
        idx = expiry_idx

    last_price = closes[-1]
    final_value = cash + shares * last_price
    total_return = (final_value - initial_capital) / initial_capital
    days = (datetime.strptime(dates[-1], '%Y-%m-%d') -
            datetime.strptime(dates[0], '%Y-%m-%d')).days
    ann = (1 + total_return) ** (365.0 / days) - 1 if days > 0 else 0
    bh_ret = (closes[-1] - S0) / S0
    bh_ann = (1 + bh_ret) ** (365.0 / days) - 1 if days > 0 else 0

    max_dd = 0.0
    peak = portfolio_values[0] if portfolio_values else initial_capital
    for pv in portfolio_values:
        peak = max(peak, pv)
        max_dd = max(max_dd, (peak - pv) / peak)

    return {
        'initial': initial_capital, 'final': final_value,
        'total_ret': total_return * 100, 'ann': ann * 100, 'dd': max_dd * 100,
        'bh_ret': bh_ret * 100, 'bh_ann': bh_ann * 100,
        'cycles': len(cycles), 'action1': num_action1,
        'premium': total_prem, 'call_cost': total_call_cost, 'call_value': total_call_value,
        'gains': stock_gains, 'losses': stock_losses,
        'states': state_counts, 'cycle_list': cycles,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', default='QQQ')
    ap.add_argument('--targets', default='60,4,10,20')
    args = ap.parse_args()
    pn, cn, pd, cd = [int(x) for x in args.targets.split(',')]
    r = run(args.ticker, make_targets(pn, cn, pd, cd))
    print(f"=== {args.ticker} WHEEL (本地真实期权数据) ===")
    print(f"  参数: A/B/D put{pn}% call{cn}% | C/E put{pd}% call{cd}%")
    print(f"  初始 ${r['initial']:,.0f} -> 终值 ${r['final']:,.0f}")
    print(f"  总收益 {r['total_ret']:.2f}%  年化 {r['ann']:.2f}%  回撤 {r['dd']:.2f}%")
    print(f"  B&H    {r['bh_ret']:.2f}%  年化 {r['bh_ann']:.2f}%")
    print(f"  周期 {r['cycles']} (Action1 {r['action1']})  权利金 ${r['premium']:,.0f}")
    print(f"  状态 {r['states']}")


if __name__ == '__main__':
    main()
