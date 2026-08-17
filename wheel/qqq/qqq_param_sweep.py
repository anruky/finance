#!/usr/bin/env python3
"""
QQQ Wheel Strategy - Parameter Sweep
=====================================
Tests DTE (7 weekly / 14 biweekly / 18 current) x Put/Call target presets
to find the best config vs Buy & Hold.

Imports the core simulate() from wheel_strategy_gav.py.
"""

import sys
from wheel_strategy_gav import Config, simulate

DATA = 'qqq_data_2025_2026.json'
START = '2025-01-02'
END = '2026-08-13'
TICKER = 'QQQ'
PUT_IV = 0.30
CALL_IV = 0.22
MARGIN = 0.11

# State target presets: {state: {'put': pct, 'call': pct}}
PRESETS = {
    'balanced':      {'A': {'put': 40, 'call': 3}, 'B': {'put': 40, 'call': 3}, 'C': {'put': 10, 'call': 10}, 'D': {'put': 40, 'call': 3}, 'E': {'put': 10, 'call': 10}},
    'aggressive':    {'A': {'put': 50, 'call': 3}, 'B': {'put': 50, 'call': 3}, 'C': {'put': 20, 'call': 5}, 'D': {'put': 50, 'call': 3}, 'E': {'put': 20, 'call': 5}},
    'high_put':      {'A': {'put': 70, 'call': 3}, 'B': {'put': 70, 'call': 3}, 'C': {'put': 10, 'call': 10}, 'D': {'put': 70, 'call': 3}, 'E': {'put': 10, 'call': 10}},
    'wide_call':     {'A': {'put': 40, 'call': 6}, 'B': {'put': 40, 'call': 6}, 'C': {'put': 10, 'call': 15}, 'D': {'put': 40, 'call': 6}, 'E': {'put': 10, 'call': 15}},
    'wide_both':     {'A': {'put': 50, 'call': 6}, 'B': {'put': 50, 'call': 6}, 'C': {'put': 15, 'call': 15}, 'D': {'put': 50, 'call': 6}, 'E': {'put': 15, 'call': 15}},
    'conservative':  {'A': {'put': 20, 'call': 5}, 'B': {'put': 20, 'call': 5}, 'C': {'put': 5, 'call': 15}, 'D': {'put': 20, 'call': 5}, 'E': {'put': 5, 'call': 15}},
}

DTES = [7, 14, 18]


def run(dte, preset_name, preset):
    state_targets = {s: {'put': v['put'] / 100.0, 'call': v['call'] / 100.0}
                     for s, v in preset.items()}
    cfg = Config(
        dte=dte,
        state_targets=state_targets,
        put_iv=PUT_IV,
        call_iv=CALL_IV,
        margin_rate=MARGIN,
        start_date=START,
        end_date=END,
        ticker=TICKER,
        data_file=DATA,
    )
    r = simulate(cfg)
    return r


def main():
    results = []
    for dte in DTES:
        for name, preset in PRESETS.items():
            r = run(dte, name, preset)
            results.append((dte, name, r))
            print(f"DTE={dte:>2}  {name:<13}  Ann={r.annualized_return_pct:>6.2f}%  "
                  f"Total={r.total_return_pct:>6.2f}%  DD={r.max_drawdown_pct:>5.2f}%  "
                  f"B&HAnn={r.buy_hold_annualized_pct:>6.2f}%  "
                  f"cycles={r.num_cycles:>3}  Act1={r.num_action1}  "
                  f"prem=${r.total_premium:,.0f}")

    # Summary: sort by annualized return
    print("\n\n=== RANKED BY ANNUALIZED RETURN ===")
    ranked = sorted(results, key=lambda x: x[2].annualized_return_pct, reverse=True)
    for dte, name, r in ranked:
        beat_bh = 'BEAT-BH' if r.annualized_return_pct > r.buy_hold_annualized_pct else ''
        print(f"  {r.annualized_return_pct:>6.2f}%  DTE={dte:>2}  {name:<13}  "
              f"Total={r.total_return_pct:>6.2f}%  DD={r.max_drawdown_pct:>5.2f}%  "
              f"BH_Ann={r.buy_hold_annualized_pct:>6.2f}%  {beat_bh}")


if __name__ == '__main__':
    main()
