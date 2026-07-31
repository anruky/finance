#!/usr/bin/env python3
"""
Parameter sensitivity analysis for the Gav wheel strategy.
Tests different put/call target combinations and reports results.
"""
import json
import sys
import itertools

# Import the strategy module
sys.path.insert(0, '/Users/gavinz/git/finance/wheel')
from wheel_strategy_gav import Config, simulate, BacktestResult

def load_data(path):
    with open(path) as f:
        return json.load(f)

def run_backtest(state_targets, label=""):
    config = Config()
    config.state_targets = state_targets
    config.ticker = "GOOGL"
    config.data_file = "/Users/gavinz/git/finance/wheel/googl_data.json"
    
    result = simulate(config)
    
    # PnL by state
    state_pnl = {}
    state_count = {}
    for c in result.cycles:
        state_pnl.setdefault(c.result_state, 0)
        state_count.setdefault(c.result_state, 0)
        state_pnl[c.result_state] += c.cycle_pnl
        state_count[c.result_state] += 1
    
    return {
        'label': label,
        'annualized': result.annualized_return_pct,
        'total_return': result.total_return_pct,
        'max_dd': result.max_drawdown_pct,
        'bh_annualized': result.buy_hold_annualized_pct,
        'premium': result.total_premium,
        'stock_gains': result.total_stock_gains,
        'stock_losses': result.total_stock_losses,
        'financing': result.total_margin_interest,
        'net_pnl': result.final_value - result.initial_capital,
        'num_cycles': result.num_cycles,
        'num_action1': result.num_action1,
        'state_pnl': state_pnl,
        'state_count': state_count,
        'final_value': result.final_value,
    }

def main():
    data = load_data('/Users/gavinz/git/finance/wheel/googl_data.json')
    
    # Current params (V3)
    current = {
        'A': {'put': 0.50, 'call': 0.05},
        'B': {'put': 0.50, 'call': 0.05},
        'C': {'put': 0.20, 'call': 0.10},
        'D': {'put': 0.40, 'call': 0.05},
        'E': {'put': 0.20, 'call': 0.10},
    }
    
    # ===== Analysis 1: PnL by state for current params =====
    print("=" * 120)
    print("ANALYSIS 1: Current V3 Parameters - PnL by State")
    print("=" * 120)
    r = run_backtest(current, "Current V3")
    print(f"\n  Annualized: {r['annualized']:.2f}% | Max DD: {r['max_dd']:.2f}% | Net P&L: ${r['net_pnl']:,.0f}")
    print(f"\n  {'State':<8} {'Count':>6} {'Total PnL':>12} {'Avg PnL':>12} {'Description':<30}")
    print(f"  {'-'*8} {'-'*6} {'-'*12} {'-'*12} {'-'*30}")
    desc_map = {
        'A': 'Neither exercised',
        'B': 'Call assigned (Act1)',
        'C': 'Put assigned (Act1)',
        'D': 'Both expired (Act1)',
        'E': 'Put assigned (no Act1)',
    }
    for st in ['A', 'B', 'C', 'D', 'E']:
        if st in r['state_count']:
            cnt = r['state_count'][st]
            total = r['state_pnl'][st]
            avg = total / cnt
            print(f"  {st:<8} {cnt:>6} ${total:>11,.0f} ${avg:>11,.0f} {desc_map[st]:<30}")
    
    # ===== Analysis 2: Vary State A put target (most common entry state) =====
    print("\n" + "=" * 120)
    print("ANALYSIS 2: Vary State A Put Target (Affects initial & steady-state cycles)")
    print("=" * 120)
    print(f"\n  {'Put A%':>8} {'Call A%':>8} {'Annual%':>8} {'MaxDD%':>8} {'Premium':>10} {'StLoss':>10} {'NetPnL':>10} {'A1':>4} {'States':<20}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*4} {'-'*20}")
    
    for put_a in [0.20, 0.30, 0.40, 0.50, 0.60]:
        for call_a in [0.03, 0.05, 0.10, 0.15]:
            test = {k: v.copy() for k, v in current.items()}
            test['A']['put'] = put_a
            test['A']['call'] = call_a
            r = run_backtest(test)
            states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r['state_count'].items()))
            print(f"  {put_a*100:>7.0f}% {call_a*100:>7.0f}% {r['annualized']:>7.2f}% {r['max_dd']:>7.2f}% ${r['premium']:>9,.0f} ${r['stock_losses']:>9,.0f} ${r['net_pnl']:>9,.0f} {r['num_action1']:>4} {states_str:<20}")
    
    # ===== Analysis 3: Vary State E put/call (biggest loser state) =====
    print("\n" + "=" * 120)
    print("ANALYSIS 3: Vary State E Targets (State E = put assigned after drop, currently biggest loser)")
    print("=" * 120)
    print(f"\n  {'Put E%':>8} {'Call E%':>8} {'Annual%':>8} {'MaxDD%':>8} {'Premium':>10} {'NetPnL':>10} {'E_count':>8} {'E_pnl':>10}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8} {'-'*10}")
    
    for put_e in [0.10, 0.15, 0.20, 0.30]:
        for call_e in [0.05, 0.10, 0.15, 0.20]:
            test = {k: v.copy() for k, v in current.items()}
            test['E']['put'] = put_e
            test['E']['call'] = call_e
            r = run_backtest(test)
            e_count = r['state_count'].get('E', 0)
            e_pnl = r['state_pnl'].get('E', 0)
            print(f"  {put_e*100:>7.0f}% {call_e*100:>7.0f}% {r['annualized']:>7.2f}% {r['max_dd']:>7.2f}% ${r['premium']:>9,.0f} ${r['net_pnl']:>9,.0f} {e_count:>8} ${e_pnl:>9,.0f}")
    
    # ===== Analysis 4: Best combinations =====
    print("\n" + "=" * 120)
    print("ANALYSIS 4: Top 10 Parameter Combinations by Annualized Return")
    print("=" * 120)
    
    results = []
    # Test a focused grid: vary A and E put/call, keep B/C/D proportional
    for put_a in [0.30, 0.40, 0.50]:
        for call_a in [0.03, 0.05, 0.08]:
            for put_e in [0.10, 0.15, 0.20]:
                for call_e in [0.05, 0.10, 0.15]:
                    test = {
                        'A': {'put': put_a, 'call': call_a},
                        'B': {'put': put_a, 'call': call_a},  # B similar to A
                        'C': {'put': put_e, 'call': call_e},  # C similar to E
                        'D': {'put': 0.40, 'call': call_a},   # D between A and E
                        'E': {'put': put_e, 'call': call_e},
                    }
                    r = run_backtest(test, f"A:{put_a*100:.0f}/{call_a*100:.0f} E:{put_e*100:.0f}/{call_e*100:.0f}")
                    results.append(r)
    
    # Sort by annualized return
    results.sort(key=lambda x: x['annualized'], reverse=True)
    
    print(f"\n  {'Rank':>4} {'Config':<25} {'Annual%':>8} {'MaxDD%':>8} {'Premium':>10} {'StGains':>10} {'StLoss':>10} {'Fin':>8} {'NetPnL':>10}")
    print(f"  {'-'*4} {'-'*25} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*10}")
    for i, r in enumerate(results[:10]):
        print(f"  {i+1:>4} {r['label']:<25} {r['annualized']:>7.2f}% {r['max_dd']:>7.2f}% ${r['premium']:>9,.0f} ${r['stock_gains']:>9,.0f} ${r['stock_losses']:>9,.0f} ${r['financing']:>7,.0f} ${r['net_pnl']:>9,.0f}")
    
    # ===== Analysis 5: Risk-adjusted (Sharpe-like: annualized / max_dd) =====
    print("\n" + "=" * 120)
    print("ANALYSIS 5: Top 10 by Risk-Adjusted Return (Annualized / Max Drawdown)")
    print("=" * 120)
    
    results_with_ratio = [(r, r['annualized'] / max(r['max_dd'], 0.01)) for r in results]
    results_with_ratio.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\n  {'Rank':>4} {'Config':<25} {'Annual%':>8} {'MaxDD%':>8} {'Ratio':>8} {'NetPnL':>10}")
    print(f"  {'-'*4} {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    for i, (r, ratio) in enumerate(results_with_ratio[:10]):
        print(f"  {i+1:>4} {r['label']:<25} {r['annualized']:>7.2f}% {r['max_dd']:>7.2f}% {ratio:>7.2f} ${r['net_pnl']:>9,.0f}")

    # ===== Summary =====
    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    best_ret = results[0]
    best_risk = results_with_ratio[0][0]
    print(f"\n  Current V3:          Annualized 15.08%, Max DD 9.29%, Net P&L $4,853")
    print(f"  Best by return:      {best_ret['label']} -> Annualized {best_ret['annualized']:.2f}%, Max DD {best_ret['max_dd']:.2f}%, Net P&L ${best_ret['net_pnl']:,.0f}")
    print(f"  Best risk-adjusted:  {best_risk['label']} -> Annualized {best_risk['annualized']:.2f}%, Max DD {best_risk['max_dd']:.2f}%, Net P&L ${best_risk['net_pnl']:,.0f}")

if __name__ == '__main__':
    main()
