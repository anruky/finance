#!/usr/bin/env python3
"""
Runner script - called as subprocess by backtest_app.py
Reads JSON config from stdin, runs backtest, outputs summary JSON to stdout.
"""

import sys, os, json, io, contextlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wheel_strategy_gav import Config, simulate, generate_html

def main():
    params = json.loads(sys.stdin.read())

    config = Config()
    config.ticker = params['ticker']
    config.data_file = params['data_file']
    config.state_targets = {
        s: {'put': params['targets'][s]['put'] / 100.0,
            'call': params['targets'][s]['call'] / 100.0}
        for s in ['A', 'B', 'C', 'D', 'E']
    }
    if 'dte' in params:
        config.dte = params['dte']
    if 'put_iv' in params:
        config.put_iv = params['put_iv'] / 100.0
    if 'call_iv' in params:
        config.call_iv = params['call_iv'] / 100.0
    if 'margin_rate' in params:
        config.margin_rate = params['margin_rate'] / 100.0

    report_path = params['report_path']

    # Suppress all stdout from strategy module
    with contextlib.redirect_stdout(io.StringIO()):
        result = simulate(config)
        generate_html(result, report_path)

    # Output summary as JSON
    summary = {
        'initial_capital': round(result.initial_capital, 2),
        'final_value': round(result.final_value, 2),
        'total_premium': round(result.total_premium, 2),
        'total_margin_interest': round(result.total_margin_interest, 2),
        'total_stock_gains': round(result.total_stock_gains, 2),
        'total_stock_losses': round(result.total_stock_losses, 2),
        'total_return_pct': round(result.total_return_pct, 2),
        'annualized_return_pct': round(result.annualized_return_pct, 2),
        'num_cycles': result.num_cycles,
        'num_action1': result.num_action1,
        'state_counts': result.state_counts,
        'max_drawdown_pct': round(result.max_drawdown_pct, 2),
        'buy_hold_return_pct': round(result.buy_hold_return_pct, 2),
        'buy_hold_annualized_pct': round(result.buy_hold_annualized_pct, 2),
        'buy_hold_max_drawdown_pct': round(result.buy_hold_max_drawdown_pct, 2),
        'backtest_days': result.backtest_days,
    }
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
