#!/usr/bin/env python3
"""
QQQ Wheel Strategy - Full Parameter Grid Search (Dynamic IV / Realized Vol)
===========================================================================
Sweeps the state-target space with REALISTIC dynamic IV (realized vol from
real prices, VRP=1.10) to find the best config for weekly (DTE=7) and
biweekly (DTE=14) separately.

Grid:
  put_normal  = A/B/D put target  (higher = closer to ATM, more premium)
  call_normal = A/B/D call target (lower = closer to ATM, more premium)
  put_down    = C/E put target
  call_down   = C/E call target
"""

import json
from wheel_strategy_gav import Config, simulate

DATA = 'qqq_data_2025_2026.json'
START = '2025-01-02'
END = '2026-08-13'
TICKER = 'QQQ'
VRP = 1.10          # volatility risk premium: IV ~= RV * 1.10
RV_WINDOW = 21      # 1-month realized vol window

PUT_NORMAL = [30, 40, 50, 60, 70, 80]
CALL_NORMAL = [2, 3, 4, 5, 6, 7, 8]
PUT_DOWN = [5, 10, 15, 20, 25]
CALL_DOWN = [8, 10, 12, 15, 20]

DTES = [7, 14]


def make_targets(pn, cn, pd, cd):
    return {
        'A': {'put': pn / 100.0, 'call': cn / 100.0},
        'B': {'put': pn / 100.0, 'call': cn / 100.0},
        'C': {'put': pd / 100.0, 'call': cd / 100.0},
        'D': {'put': pn / 100.0, 'call': cn / 100.0},
        'E': {'put': pd / 100.0, 'call': cd / 100.0},
    }


def run_sweep(dte):
    results = []
    total = len(PUT_NORMAL) * len(CALL_NORMAL) * len(PUT_DOWN) * len(CALL_DOWN)
    n = 0
    for pn in PUT_NORMAL:
        for cn in CALL_NORMAL:
            for pd in PUT_DOWN:
                for cd in CALL_DOWN:
                    cfg = Config(
                        dte=dte,
                        state_targets=make_targets(pn, cn, pd, cd),
                        put_iv=0.30, call_iv=0.22,
                        dynamic_iv=True, iv_rv_window=RV_WINDOW, iv_vrp=VRP,
                        margin_rate=0.11,
                        start_date=START, end_date=END,
                        ticker=TICKER, data_file=DATA,
                    )
                    r = simulate(cfg)
                    results.append({
                        'dte': dte, 'pn': pn, 'cn': cn, 'pd': pd, 'cd': cd,
                        'ann': r.annualized_return_pct,
                        'total': r.total_return_pct,
                        'dd': r.max_drawdown_pct,
                        'avg_iv': r.put_iv,
                        'premium': r.total_premium,
                        'cycles': r.num_cycles,
                        'action1': r.num_action1,
                        'states': r.state_counts,
                        'sharpe_like': r.annualized_return_pct / r.max_drawdown_pct if r.max_drawdown_pct > 0 else 0,
                    })
                    n += 1
    return results


def main():
    all_results = {}
    for dte in DTES:
        print(f"\n=== Sweeping DTE={dte} ({len(PUT_NORMAL)*len(CALL_NORMAL)*len(PUT_DOWN)*len(CALL_DOWN)} combos) ===")
        results = run_sweep(dte)
        all_results[str(dte)] = results
        # Rank by annualized return
        ranked = sorted(results, key=lambda x: x['ann'], reverse=True)
        print(f"\n--- DTE={dte} TOP 15 (by annualized return) ---")
        print(f"{'rank':>4} {'ann':>7} {'total':>6} {'dd':>6} {'pn':>4} {'cn':>4} {'pd':>4} {'cd':>4} {'avgIV':>6} {'ret/dd':>7}")
        for i, r in enumerate(ranked[:15]):
            print(f"{i+1:>4} {r['ann']:>7.2f} {r['total']:>6.2f} {r['dd']:>6.2f} "
                  f"{r['pn']:>4} {r['cn']:>4} {r['pd']:>4} {r['cd']:>4} "
                  f"{r['avg_iv']:>6.1f} {r['sharpe_like']:>7.2f}")

    # Save full results
    json.dump(all_results, open('qqq_sweep_dynamic_iv_results.json', 'w'))
    print("\n\nSaved full results to qqq_sweep_dynamic_iv_results.json")

    # Also show best by risk-adjusted (ret/dd)
    for dte in DTES:
        results = all_results[str(dte)]
        ranked_risk = sorted(results, key=lambda x: x['sharpe_like'], reverse=True)
        print(f"\n--- DTE={dte} TOP 5 by return/drawdown ---")
        for r in ranked_risk[:5]:
            print(f"  ann={r['ann']:.2f}% dd={r['dd']:.2f}% ret/dd={r['sharpe_like']:.2f} "
                  f"pn={r['pn']} cn={r['cn']} pd={r['pd']} cd={r['cd']}")


if __name__ == '__main__':
    main()
