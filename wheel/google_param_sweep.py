#!/usr/bin/env python3
"""
Google parameter optimization sweep.
Goal: find parameter combinations that beat Buy & Hold.
Tests state targets, DTE, IV, and margin rate combinations.
"""
import json
import sys
import itertools

sys.path.insert(0, '/Users/gavinz/git/finance/wheel')
from wheel_strategy_gav import Config, simulate

def run_one(state_targets, dte=18, put_iv=0.30, call_iv=0.22, margin_rate=0.11):
    config = Config()
    config.state_targets = state_targets
    config.ticker = "GOOGL"
    config.data_file = "/Users/gavinz/git/finance/wheel/googl_data.json"
    config.dte = dte
    config.put_iv = put_iv
    config.call_iv = call_iv
    config.margin_rate = margin_rate
    result = simulate(config)
    return result


def main():
    # ===== Baseline: B&H =====
    base = run_one({'A': {'put': 0.40, 'call': 0.03}, 'B': {'put': 0.40, 'call': 0.03},
                     'C': {'put': 0.10, 'call': 0.10}, 'D': {'put': 0.40, 'call': 0.03},
                     'E': {'put': 0.10, 'call': 0.10}})
    bh_ann = base.buy_hold_annualized_pct
    bh_ret = base.buy_hold_return_pct
    bh_dd = base.buy_hold_max_drawdown_pct
    print("=" * 130)
    print("GOOGLE PARAMETER SWEEP - TARGET: BEAT B&H")
    print("=" * 130)
    print(f"\n  B&H Baseline: Annualized {bh_ann:.2f}% | Total {bh_ret:.2f}% | MaxDD {bh_dd:.2f}%")
    print(f"  Current strategy: Annualized {base.annualized_return_pct:.2f}% | MaxDD {base.max_drawdown_pct:.2f}%")
    print(f"  Gap to B&H: {bh_ann - base.annualized_return_pct:.2f}%\n")

    results = []

    # ===== Phase 1: Vary state targets with default DTE=18, IV=30/22 =====
    # Key insight: to beat B&H on a strong uptrend stock like Google:
    # - Need HIGH put targets (more premium, but deeper OTM = less likely assigned)
    # - Need LOW call targets (call strike far OTM = less upside capping)
    # - States C/E (down states): low put to avoid buying on dips, higher call to recover
    
    put_high = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]  # States A/B/D
    call_low = [0.01, 0.02, 0.03, 0.05, 0.08]         # States A/B/D  
    put_low = [0.05, 0.10, 0.15, 0.20, 0.30]          # States C/E
    call_high = [0.05, 0.10, 0.15, 0.20, 0.30]        # States C/E

    count = 0
    for pa in put_high:
        for ca in call_low:
            for pe in put_low:
                for ce in call_high:
                    targets = {
                        'A': {'put': pa, 'call': ca},
                        'B': {'put': pa, 'call': ca},
                        'C': {'put': pe, 'call': ce},
                        'D': {'put': pa, 'call': ca},
                        'E': {'put': pe, 'call': ce},
                    }
                    r = run_one(targets)
                    count += 1
                    if count % 200 == 0:
                        print(f"  ... tested {count} combinations")
                    results.append({
                        'targets': targets,
                        'dte': 18,
                        'put_iv': 30,
                        'call_iv': 22,
                        'margin': 11,
                        'annualized': r.annualized_return_pct,
                        'total_return': r.total_return_pct,
                        'max_dd': r.max_drawdown_pct,
                        'bh_annualized': r.buy_hold_annualized_pct,
                        'premium': r.total_premium,
                        'stock_gains': r.total_stock_gains,
                        'stock_losses': r.total_stock_losses,
                        'financing': r.total_margin_interest,
                        'net_pnl': r.final_value - r.initial_capital,
                        'num_cycles': r.num_cycles,
                        'num_action1': r.num_action1,
                        'state_counts': r.state_counts.copy(),
                        'final_value': r.final_value,
                        'initial_capital': r.initial_capital,
                    })

    print(f"\n  Phase 1 complete: {count} combinations tested (DTE=18, IV=30/22)")

    # ===== Phase 2: Vary DTE for top configs =====
    # Take top 5 from phase 1 and try different DTE/IV
    phase1_sorted = sorted(results, key=lambda x: x['annualized'], reverse=True)
    for base_r in phase1_sorted[:5]:
        for dte in [10, 14, 21, 28, 35]:
            if dte == 18:
                continue
            for piv, civ in [(0.25, 0.18), (0.35, 0.26), (0.40, 0.30)]:
                r = run_one(base_r['targets'], dte=dte, put_iv=piv, call_iv=civ)
                results.append({
                    'targets': base_r['targets'],
                    'dte': dte,
                    'put_iv': int(piv*100),
                    'call_iv': int(civ*100),
                    'margin': 11,
                    'annualized': r.annualized_return_pct,
                    'total_return': r.total_return_pct,
                    'max_dd': r.max_drawdown_pct,
                    'bh_annualized': r.buy_hold_annualized_pct,
                    'premium': r.total_premium,
                    'stock_gains': r.total_stock_gains,
                    'stock_losses': r.total_stock_losses,
                    'financing': r.total_margin_interest,
                    'net_pnl': r.final_value - r.initial_capital,
                    'num_cycles': r.num_cycles,
                    'num_action1': r.num_action1,
                    'state_counts': r.state_counts.copy(),
                    'final_value': r.final_value,
                    'initial_capital': r.initial_capital,
                })

    print(f"  Phase 2 complete: {len(results)} total combinations")

    # ===== Phase 3: Try lower margin rate (negotiated rate) =====
    for base_r in phase1_sorted[:3]:
        for mr in [0.05, 0.08, 0.15]:
            r = run_one(base_r['targets'], margin_rate=mr)
            results.append({
                'targets': base_r['targets'],
                'dte': 18,
                'put_iv': 30,
                'call_iv': 22,
                'margin': int(mr*100),
                'annualized': r.annualized_return_pct,
                'total_return': r.total_return_pct,
                'max_dd': r.max_drawdown_pct,
                'bh_annualized': r.buy_hold_annualized_pct,
                'premium': r.total_premium,
                'stock_gains': r.total_stock_gains,
                'stock_losses': r.total_stock_losses,
                'financing': r.total_margin_interest,
                'net_pnl': r.final_value - r.initial_capital,
                'num_cycles': r.num_cycles,
                'num_action1': r.num_action1,
                'state_counts': r.state_counts.copy(),
                'final_value': r.final_value,
                'initial_capital': r.initial_capital,
            })

    print(f"  Phase 3 complete: {len(results)} total combinations")

    # ===== Results =====
    # Filter: beat B&H
    beaters = [r for r in results if r['annualized'] > r['bh_annualized']]
    beaters.sort(key=lambda x: x['annualized'], reverse=True)

    print(f"\n  Total combinations: {len(results)}")
    print(f"  Combinations beating B&H ({bh_ann:.2f}%): {len(beaters)}")

    # Top 30 by annualized return
    print("\n" + "=" * 130)
    print("TOP 30 BY ANNUALIZED RETURN (all combinations)")
    print("=" * 130)
    all_sorted = sorted(results, key=lambda x: x['annualized'], reverse=True)
    
    print(f"\n  {'#':>3} {'Ann%':>7} {'B&H%':>7} {'Diff':>7} {'DD%':>6} {'DTE':>4} {'IV':>6} {'Marg':>4} {'Premium':>9} {'StGain':>9} {'StLoss':>8} {'Fin':>7} {'NetPnL':>10} {'Cyc':>4} {'A1':>4} {'States':<20} {'Params (A/B/D P/C, C/E P/C)':<35}")
    print(f"  {'-'*3} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*9} {'-'*9} {'-'*8} {'-'*7} {'-'*10} {'-'*4} {'-'*4} {'-'*20} {'-'*35}")
    
    for i, r in enumerate(all_sorted[:30]):
        t = r['targets']
        beat = "<<" if r['annualized'] > r['bh_annualized'] else "  "
        states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r['state_counts'].items()))
        params_str = f"A/B/D:{int(t['A']['put']*100)}/{int(t['A']['call']*100)} C/E:{int(t['C']['put']*100)}/{int(t['C']['call']*100)}"
        diff = r['annualized'] - r['bh_annualized']
        iv_str = f"{r['put_iv']}/{r['call_iv']}"
        print(f"  {i+1:>3} {r['annualized']:>6.2f}% {r['bh_annualized']:>6.2f}% {diff:>+6.2f}% {r['max_dd']:>5.2f}% {r['dte']:>4} {iv_str:>6} {r['margin']:>4}% ${r['premium']:>8,.0f} ${r['stock_gains']:>8,.0f} ${r['stock_losses']:>7,.0f} ${r['financing']:>6,.0f} ${r['net_pnl']:>9,.0f} {r['num_cycles']:>4} {r['num_action1']:>4} {states_str:<20} {params_str:<35} {beat}")

    # If any beaters, show detail
    if beaters:
        print("\n" + "=" * 130)
        print(f"COMBINATIONS THAT BEAT B&H ({bh_ann:.2f}%): {len(beaters)} found")
        print("=" * 130)
        print(f"\n  {'#':>3} {'Ann%':>7} {'B&H%':>7} {'Diff':>7} {'DD%':>6} {'DTE':>4} {'IV':>6} {'Marg':>4} {'Premium':>9} {'NetPnL':>10} {'RiskAdj':>7} {'States':<20} {'Params':<35}")
        print(f"  {'-'*3} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*9} {'-'*10} {'-'*7} {'-'*20} {'-'*35}")
        
        for i, r in enumerate(beaters[:30]):
            t = r['targets']
            states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r['state_counts'].items()))
            params_str = f"A/B/D:{int(t['A']['put']*100)}/{int(t['A']['call']*100)} C/E:{int(t['C']['put']*100)}/{int(t['C']['call']*100)}"
            diff = r['annualized'] - r['bh_annualized']
            risk_adj = r['annualized'] / max(r['max_dd'], 0.01)
            iv_str = f"{r['put_iv']}/{r['call_iv']}"
            print(f"  {i+1:>3} {r['annualized']:>6.2f}% {r['bh_annualized']:>6.2f}% {diff:>+6.2f}% {r['max_dd']:>5.2f}% {r['dte']:>4} {iv_str:>6} {r['margin']:>4}% ${r['premium']:>8,.0f} ${r['net_pnl']:>9,.0f} {risk_adj:>6.2f} {states_str:<20} {params_str:<35}")
    else:
        print("\n  *** No combinations beat B&H ***")
        print("  Closest results:")
        closest = sorted(results, key=lambda x: x['bh_annualized'] - x['annualized'])[:10]
        for i, r in enumerate(closest):
            t = r['targets']
            states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r['state_counts'].items()))
            params_str = f"A/B/D:{int(t['A']['put']*100)}/{int(t['A']['call']*100)} C/E:{int(t['C']['put']*100)}/{int(t['C']['call']*100)}"
            diff = r['annualized'] - r['bh_annualized']
            iv_str = f"{r['put_iv']}/{r['call_iv']}"
            print(f"  {i+1:>3} Ann:{r['annualized']:>6.2f}% B&H:{r['bh_annualized']:>6.2f}% Gap:{diff:>+6.2f}% DD:{r['max_dd']:>5.2f}% DTE:{r['dte']:>3} IV:{iv_str:>6} ${r['net_pnl']:>9,.0f} {states_str:<20} {params_str}")

    # ===== Best risk-adjusted =====
    print("\n" + "=" * 130)
    print("TOP 15 BY RISK-ADJUSTED RETURN (Annualized / Max DD)")
    print("=" * 130)
    risk_sorted = sorted(results, key=lambda x: x['annualized'] / max(x['max_dd'], 0.01), reverse=True)
    print(f"\n  {'#':>3} {'Ann%':>7} {'B&H%':>7} {'DD%':>6} {'Ratio':>7} {'DTE':>4} {'IV':>6} {'NetPnL':>10} {'Premium':>9} {'States':<20} {'Params':<35}")
    print(f"  {'-'*3} {'-'*7} {'-'*7} {'-'*6} {'-'*7} {'-'*4} {'-'*6} {'-'*10} {'-'*9} {'-'*20} {'-'*35}")
    for i, r in enumerate(risk_sorted[:15]):
        t = r['targets']
        ratio = r['annualized'] / max(r['max_dd'], 0.01)
        states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r['state_counts'].items()))
        params_str = f"A/B/D:{int(t['A']['put']*100)}/{int(t['A']['call']*100)} C/E:{int(t['C']['put']*100)}/{int(t['C']['call']*100)}"
        iv_str = f"{r['put_iv']}/{r['call_iv']}"
        beat = "<<" if r['annualized'] > r['bh_annualized'] else ""
        print(f"  {i+1:>3} {r['annualized']:>6.2f}% {r['bh_annualized']:>6.2f}% {r['max_dd']:>5.2f}% {ratio:>6.2f} {r['dte']:>4} {iv_str:>6} ${r['net_pnl']:>9,.0f} ${r['premium']:>8,.0f} {states_str:<20} {params_str:<35} {beat}")

    # ===== Analysis: what drives performance =====
    print("\n" + "=" * 130)
    print("PARAMETER SENSITIVITY ANALYSIS")
    print("=" * 130)
    
    # Vary A/B/D put target (holding call=0.03, C/E=0.10/0.10)
    print(f"\n  Vary A/B/D Put Target (call=3%, C/E=10/10, DTE=18, IV=30/22):")
    print(f"  {'Put%':>6} {'Ann%':>7} {'B&H%':>7} {'DD%':>6} {'Premium':>9} {'StLoss':>8} {'NetPnL':>10} {'States':<20}")
    for pa in [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
        targets = {'A': {'put': pa, 'call': 0.03}, 'B': {'put': pa, 'call': 0.03},
                   'C': {'put': 0.10, 'call': 0.10}, 'D': {'put': pa, 'call': 0.03},
                   'E': {'put': 0.10, 'call': 0.10}}
        r = run_one(targets)
        states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r.state_counts.items()))
        print(f"  {int(pa*100):>5}% {r.annualized_return_pct:>6.2f}% {r.buy_hold_annualized_pct:>6.2f}% {r.max_drawdown_pct:>5.2f}% ${r.total_premium:>8,.0f} ${r.total_stock_losses:>7,.0f} ${r.final_value-r.initial_capital:>9,.0f} {states_str:<20}")

    # Vary A/B/D call target (holding put=0.50, C/E=0.10/0.10)
    print(f"\n  Vary A/B/D Call Target (put=50%, C/E=10/10, DTE=18, IV=30/22):")
    print(f"  {'Call%':>6} {'Ann%':>7} {'B&H%':>7} {'DD%':>6} {'Premium':>9} {'A1':>4} {'NetPnL':>10} {'States':<20}")
    for ca in [0.01, 0.02, 0.03, 0.05, 0.08, 0.10]:
        targets = {'A': {'put': 0.50, 'call': ca}, 'B': {'put': 0.50, 'call': ca},
                   'C': {'put': 0.10, 'call': 0.10}, 'D': {'put': 0.50, 'call': ca},
                   'E': {'put': 0.10, 'call': 0.10}}
        r = run_one(targets)
        states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r.state_counts.items()))
        print(f"  {int(ca*100):>5}% {r.annualized_return_pct:>6.2f}% {r.buy_hold_annualized_pct:>6.2f}% {r.max_drawdown_pct:>5.2f}% ${r.total_premium:>8,.0f} {r.num_action1:>4} ${r.final_value-r.initial_capital:>9,.0f} {states_str:<20}")

    # Vary DTE (with best params so far)
    best = all_sorted[0]
    print(f"\n  Vary DTE (best params: A/B/D:{int(best['targets']['A']['put']*100)}/{int(best['targets']['A']['call']*100)}, C/E:{int(best['targets']['C']['put']*100)}/{int(best['targets']['C']['call']*100)}):")
    print(f"  {'DTE':>5} {'Ann%':>7} {'B&H%':>7} {'DD%':>6} {'Premium':>9} {'Cyc':>4} {'NetPnL':>10} {'States':<20}")
    for dte in [7, 10, 14, 18, 21, 28, 35]:
        r = run_one(best['targets'], dte=dte)
        states_str = ' / '.join(f"{k}:{v}" for k, v in sorted(r.state_counts.items()))
        print(f"  {dte:>5} {r.annualized_return_pct:>6.2f}% {r.buy_hold_annualized_pct:>6.2f}% {r.max_drawdown_pct:>5.2f}% ${r.total_premium:>8,.0f} {r.num_cycles:>4} ${r.final_value-r.initial_capital:>9,.0f} {states_str:<20}")

    # Vary IV
    print(f"\n  Vary IV (best params, DTE=18):")
    print(f"  {'PutIV':>6} {'CallIV':>7} {'Ann%':>7} {'B&H%':>7} {'DD%':>6} {'Premium':>9} {'NetPnL':>10}")
    for piv in [0.20, 0.25, 0.30, 0.35, 0.40, 0.50]:
        for civ in [0.15, 0.18, 0.22, 0.26, 0.30]:
            r = run_one(best['targets'], put_iv=piv, call_iv=civ)
            print(f"  {int(piv*100):>5}% {int(civ*100):>6}% {r.annualized_return_pct:>6.2f}% {r.buy_hold_annualized_pct:>6.2f}% {r.max_drawdown_pct:>5.2f}% ${r.total_premium:>8,.0f} ${r.final_value-r.initial_capital:>9,.0f}")


if __name__ == '__main__':
    main()
