#!/usr/bin/env python3
"""Deprecated entry point: v10 cash-flow-only NAV is no longer used.
Use backtest_audited.run for the corrected ledger and report_builder for scans.
The old v10 implementation is retained only in the dated backup directory.
"""
from backtest_audited import Config, run, metrics, window_metrics
from report_builder import main
if __name__ == '__main__':
    main()
