#!/usr/bin/env python3
"""
DRAM ETF Hedge Strategy Simulation
==================================
Strategy: Hold DRAM ETF stock + Buy put options as hedge.

Each cycle:
  1. Buy 1 lot (100 shares) of DRAM ETF at current price
  2. Buy N put contracts at strike = entry_price * (1 - strike_pct)
  3. Hold for `holding_period` trading days
  4. At expiration (Friday):
     A. If price < strike: put is ITM, exercise/sell put for gain
     B. If price >= strike: put expires worthless
  5. Roll to next cycle

All parameters are configurable via the StrategyConfig dataclass.

Usage:
  python3 hedge_simulation.py                  # Run with defaults
  python3 hedge_simulation.py --strike-pct 5   # Adjust parameters
  python3 hedge_simulation.py --help             # See all options
"""

import argparse
import json
import os
import sys
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

# ─── Configuration ──────────────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    """All adjustable parameters for the hedge strategy."""
    # ── Capital ──
    initial_capital: float = 100_000.0        # Starting capital (USD)

    # ── Stock position ──
    shares_per_lot: int = 100                 # Shares per lot (US: 100)
    num_lots: int = 1                         # Number of lots to buy each cycle

    # ── Put option parameters ──
    num_put_contracts: int = 2                # Number of put contracts to buy
    contract_size: int = 100                  # Shares per option contract (US: 100)
    put_premium_per_contract: float = 130.0   # Premium per contract (USD)
    strike_pct_below: float = 0.03            # Strike = entry_price * (1 - this)

    # ── Cycle parameters ──
    holding_period_days: int = 12             # Trading days per cycle (5 or 12)
    roll_on_expiry: bool = True               # Immediately start next cycle on expiry

    # ── Simulation dates ──
    start_date: str = "2026-01-05"            # First Monday
    end_date: str = "2026-08-05"              # End of simulation

    # ── Synthetic data parameters (used when real data unavailable) ──
    synth_start_price: float = 55.0           # Starting price for synthetic data
    synth_annual_vol: float = 0.45            # Annual volatility (45%)
    synth_annual_drift: float = 0.15          # Annual drift/trend (15%)
    synth_seed: int = 42                      # Random seed for reproducibility

    # ── Output ──
    output_dir: str = "/Users/gavinz/git/finance/hedge"


# ─── Data Module ─────────────────────────────────────────────────────────────

def fetch_real_data(ticker: str = "DRAM", start: str = "2026-01-01", end: str = "2026-08-06") -> Optional[pd.DataFrame]:
    """Try to fetch real DRAM ETF data via yfinance."""
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df is not None and len(df) > 0:
            df = df.reset_index()
            df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                                    "Low": "low", "Close": "close", "Volume": "volume"})
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"  [Data] yfinance fetch failed: {e}")
    return None


def generate_synthetic_data(cfg: StrategyConfig) -> pd.DataFrame:
    """Generate synthetic OHLC data calibrated to DRAM ETF characteristics."""
    np.random.seed(cfg.synth_seed)
    random.seed(cfg.synth_seed)

    start = pd.Timestamp(cfg.start_date)
    end = pd.Timestamp(cfg.end_date)

    # Generate trading days (skip weekends)
    dates = []
    d = start - pd.Timedelta(days=7)  # Start a week earlier for warmup
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            dates.append(d)
        d += pd.Timedelta(days=1)

    n = len(dates)
    dt = 1.0 / 252.0

    # GBM parameters
    drift = cfg.synth_annual_drift
    vol = cfg.synth_annual_vol
    S0 = cfg.synth_start_price

    # Generate price path with some regime changes for realism
    returns = np.zeros(n)
    for i in range(n):
        # Base GBM return
        r = (drift - 0.5 * vol**2) * dt + vol * np.sqrt(dt) * np.random.standard_normal()

        # Add some regime changes
        if i > n * 0.3 and i < n * 0.4:  # Mid-period correction
            r += -0.008
        if i > n * 0.55 and i < n * 0.65:  # Rally
            r += 0.006
        if i > n * 0.8 and i < n * 0.85:  # Late period dip
            r += -0.005

        returns[i] = r

    prices = np.zeros(n)
    prices[0] = S0
    for i in range(1, n):
        prices[i] = prices[i-1] * np.exp(returns[i])

    # Generate OHLC
    rows = []
    for i in range(n):
        close = prices[i]
        intraday_vol = vol * 0.6 / np.sqrt(252)
        open_p = close * (1 + np.random.normal(0, intraday_vol * 0.5))
        high = max(open_p, close) * (1 + abs(np.random.normal(0, intraday_vol)))
        low = min(open_p, close) * (1 - abs(np.random.normal(0, intraday_vol)))
        volume = int(np.random.lognormal(mean=15, sigma=0.5))

        rows.append({
            "date": dates[i].strftime("%Y-%m-%d"),
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": volume,
        })

    return pd.DataFrame(rows)


def get_price_data(cfg: StrategyConfig) -> pd.DataFrame:
    """Get price data: try real first, fall back to synthetic."""
    print("[1/4] Fetching price data...")

    # Try real data first
    df = fetch_real_data("DRAM", cfg.start_date, cfg.end_date)
    if df is not None and len(df) > 10:
        print(f"  Using real DRAM ETF data: {len(df)} trading days")
        data_source = "real (yfinance)"
    else:
        print(f"  Real data unavailable, generating synthetic data")
        df = generate_synthetic_data(cfg)
        data_source = "synthetic (GBM calibrated to DRAM characteristics)"
        print(f"  Generated {len(df)} trading days of synthetic data")

    return df, data_source


# ─── Strategy Engine ─────────────────────────────────────────────────────────

@dataclass
class Trade:
    """Represents one hedge cycle."""
    cycle_id: int
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    strike_price: float
    put_expired: bool
    shares_held: int
    num_puts: int
    put_premium_total: float
    stock_pnl: float
    put_payoff: float
    put_cost: float
    total_pnl: float
    return_pct: float
    stock_return_pct: float
    put_hedge_ratio: float  # put notional / stock notional
    price_change_pct: float
    scenario: str  # "A: Put ITM (exercised)" or "B: Put OTM (expired)"


def run_simulation(price_df: pd.DataFrame, cfg: StrategyConfig) -> Tuple[List[Trade], Dict]:
    """Run the hedge strategy simulation."""
    print("[2/4] Running hedge strategy simulation...")

    prices = price_df.set_index("date")["close"]
    dates = list(prices.index)

    trades = []
    capital = cfg.initial_capital
    cycle_id = 0

    i = 0
    # Find the starting date
    while i < len(dates) and dates[i] < cfg.start_date:
        i += 1

    while i < len(dates):
        entry_date = dates[i]
        entry_price = prices[entry_date]

        # Calculate exit index
        exit_idx = min(i + cfg.holding_period_days, len(dates) - 1)
        exit_date = dates[exit_idx]
        exit_price = prices[exit_date]

        # Calculate strike price
        strike = entry_price * (1.0 - cfg.strike_pct_below)

        # Position sizes
        shares = cfg.shares_per_lot * cfg.num_lots
        num_puts = cfg.num_put_contracts
        put_shares_covered = num_puts * cfg.contract_size
        premium_total = num_puts * cfg.put_premium_per_contract

        # Stock P&L
        stock_value = entry_price * shares
        stock_pnl = (exit_price - entry_price) * shares
        stock_return_pct = (exit_price - entry_price) / entry_price * 100

        # Put payoff
        if exit_price < strike:
            # Put is ITM
            put_payoff = (strike - exit_price) * put_shares_covered
            put_expired = False
            scenario = "A: Put ITM (exercised)"
        else:
            # Put expires worthless
            put_payoff = 0.0
            put_expired = True
            scenario = "B: Put OTM (expired)"

        # Total P&L
        put_cost = premium_total
        total_pnl = stock_pnl + put_payoff - put_cost

        # Return percentages
        return_pct = total_pnl / stock_value * 100 if stock_value > 0 else 0

        # Hedge ratio (put notional / stock notional)
        put_notional = strike * put_shares_covered
        hedge_ratio = put_notional / stock_value

        trade = Trade(
            cycle_id=cycle_id,
            entry_date=entry_date,
            entry_price=round(entry_price, 2),
            exit_date=exit_date,
            exit_price=round(exit_price, 2),
            strike_price=round(strike, 2),
            put_expired=put_expired,
            shares_held=shares,
            num_puts=num_puts,
            put_premium_total=round(premium_total, 2),
            stock_pnl=round(stock_pnl, 2),
            put_payoff=round(put_payoff, 2),
            put_cost=round(put_cost, 2),
            total_pnl=round(total_pnl, 2),
            return_pct=round(return_pct, 2),
            stock_return_pct=round(stock_return_pct, 2),
            put_hedge_ratio=round(hedge_ratio, 2),
            price_change_pct=round(stock_return_pct, 2),
            scenario=scenario,
        )
        trades.append(trade)

        # Update capital
        capital += total_pnl

        cycle_id += 1
        i = exit_idx + 1  # Start next cycle on the next trading day after expiry

    # Summary statistics
    total_cycles = len(trades)
    itm_cycles = sum(1 for t in trades if not t.put_expired)
    otm_cycles = sum(1 for t in trades if t.put_expired)

    total_pnl = sum(t.total_pnl for t in trades)
    total_stock_pnl = sum(t.stock_pnl for t in trades)
    total_put_premium = sum(t.put_cost for t in trades)
    total_put_payoff = sum(t.put_payoff for t in trades)

    # Buy-and-hold comparison
    first_price = trades[0].entry_price if trades else 0
    last_price = trades[-1].exit_price if trades else 0
    bh_shares = cfg.shares_per_lot * cfg.num_lots
    bh_pnl = (last_price - first_price) * bh_shares
    bh_stock_return = (last_price - first_price) / first_price * 100 if first_price > 0 else 0
    # Return on capital basis (same as strategy, for fair comparison)
    bh_return = bh_pnl / cfg.initial_capital * 100

    # Strategy return
    total_invested = sum(t.entry_price * t.shares_held for t in trades)
    strategy_return = total_pnl / cfg.initial_capital * 100

    # Per-cycle stats
    avg_cycle_return = np.mean([t.return_pct for t in trades]) if trades else 0
    best_cycle = max(trades, key=lambda t: t.return_pct) if trades else None
    worst_cycle = min(trades, key=lambda t: t.return_pct) if trades else None
    win_cycles = sum(1 for t in trades if t.total_pnl > 0)
    win_rate = win_cycles / total_cycles * 100 if total_cycles > 0 else 0

    # Avg price change per cycle
    avg_price_change = np.mean([t.price_change_pct for t in trades]) if trades else 0

    summary = {
        "config": asdict(cfg),
        "data_source": None,  # Set by caller
        "total_cycles": total_cycles,
        "itm_cycles": itm_cycles,
        "otm_cycles": otm_cycles,
        "initial_capital": cfg.initial_capital,
        "final_capital": round(cfg.initial_capital + total_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_stock_pnl": round(total_stock_pnl, 2),
        "total_put_premium": round(total_put_premium, 2),
        "total_put_payoff": round(total_put_payoff, 2),
        "strategy_return_pct": round(strategy_return, 2),
        "avg_cycle_return_pct": round(avg_cycle_return, 2),
        "best_cycle_return_pct": round(best_cycle.return_pct, 2) if best_cycle else 0,
        "best_cycle_date": best_cycle.entry_date if best_cycle else "",
        "worst_cycle_return_pct": round(worst_cycle.return_pct, 2) if worst_cycle else 0,
        "worst_cycle_date": worst_cycle.entry_date if worst_cycle else "",
        "win_rate_pct": round(win_rate, 2),
        "buy_hold_pnl": round(bh_pnl, 2),
        "buy_hold_return_pct": round(bh_return, 2),
        "buy_hold_stock_return_pct": round(bh_stock_return, 2),
        "hedge_cost_pct": round(total_put_premium / cfg.initial_capital * 100, 2),
        "avg_price_change_pct": round(avg_price_change, 2),
        "itm_rate_pct": round(itm_cycles / total_cycles * 100, 2) if total_cycles > 0 else 0,
        "put_hedge_ratio": round(cfg.num_put_contracts * cfg.contract_size /
                                 (cfg.shares_per_lot * cfg.num_lots), 2),
        "net_hedge_benefit": round(total_put_payoff - total_put_premium, 2),
    }

    print(f"  Completed {total_cycles} cycles")
    print(f"  Total P&L: ${total_pnl:,.2f} | Buy & Hold: ${bh_pnl:,.2f}")
    print(f"  ITM cycles: {itm_cycles} | OTM cycles: {otm_cycles}")
    print(f"  Win rate: {win_rate:.1f}%")

    return trades, summary


# ─── Report Generator ────────────────────────────────────────────────────────

def generate_report(trades: List[Trade], summary: Dict, price_df: pd.DataFrame,
                    cfg: StrategyConfig, data_source: str, output_path: str):
    """Generate comprehensive HTML report with charts."""
    print("[3/4] Generating HTML report...")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import base64
    from io import BytesIO

    # Chinese stock market convention: red = up, green = down
    plt.rcParams["axes.unicode_minus"] = False

    def fig_to_base64(fig):
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode()

    # ── Chart 1: Price path with trade markers ──
    fig, ax = plt.subplots(figsize=(12, 5))
    dates = pd.to_datetime(price_df["date"])
    closes = price_df["close"]
    ax.plot(dates, closes, color="#333333", linewidth=1.2, label="DRAM ETF Price", zorder=1)

    # Mark entry/exit points
    for t in trades:
        entry_dt = pd.Timestamp(t.entry_date)
        exit_dt = pd.Timestamp(t.exit_date)
        if t.total_pnl > 0:
            color = "#d32f2f"  # Red = profit (Chinese convention)
        else:
            color = "#388e3c"  # Green = loss (Chinese convention)

        ax.scatter(entry_dt, t.entry_price, color="#1976d2", s=30, zorder=3, marker="^")
        ax.scatter(exit_dt, t.exit_price, color=color, s=30, zorder=3, marker="v")

    ax.set_title("DRAM ETF Price Path & Trade Cycle Markers", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price (USD)")
    ax.legend(["Price", "Entry (buy)", "Exit (sell)"], loc="best")
    ax.grid(True, alpha=0.3)
    chart1 = fig_to_base64(fig)

    # ── Chart 2: Cumulative P&L vs Buy & Hold ──
    fig, ax = plt.subplots(figsize=(12, 5))

    cum_pnl = []
    running = 0
    for t in trades:
        running += t.total_pnl
        cum_pnl.append(running)

    cum_bh = []
    bh_running = 0
    first_price = trades[0].entry_price if trades else 0
    for t in trades:
        bh_running = (t.exit_price - first_price) * t.shares_held
        cum_bh.append(bh_running)

    x = range(len(trades))
    ax.plot(x, cum_pnl, color="#d32f2f", linewidth=2, label="Hedge Strategy P&L", marker="o", markersize=5)
    ax.plot(x, cum_bh, color="#1976d2", linewidth=2, label="Buy & Hold P&L", marker="s", markersize=5)
    ax.axhline(y=0, color="#666666", linestyle="--", alpha=0.5)
    ax.set_title("Cumulative P&L: Hedge Strategy vs Buy & Hold", fontsize=14, fontweight="bold")
    ax.set_xlabel("Cycle Number")
    ax.set_ylabel("P&L (USD)")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    chart2 = fig_to_base64(fig)

    # ── Chart 3: Per-cycle P&L breakdown ──
    fig, ax = plt.subplots(figsize=(12, 5))
    cycle_labels = [f"C{i}" for i in range(len(trades))]
    stock_pnls = [t.stock_pnl for t in trades]
    put_payoffs = [t.put_payoff for t in trades]
    put_costs = [-t.put_cost for t in trades]

    x_pos = np.arange(len(trades))
    width = 0.25

    bars1 = ax.bar(x_pos - width, stock_pnls, width, label="Stock P&L", color="#1976d2", alpha=0.8)
    bars2 = ax.bar(x_pos, put_payoffs, width, label="Put Payoff", color="#d32f2f", alpha=0.8)
    bars3 = ax.bar(x_pos + width, put_costs, width, label="Put Premium Cost", color="#f57c00", alpha=0.8)

    ax.axhline(y=0, color="#333333", linewidth=0.8)
    ax.set_title("Per-Cycle P&L Breakdown", fontsize=14, fontweight="bold")
    ax.set_xlabel("Cycle")
    ax.set_ylabel("P&L (USD)")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(cycle_labels, fontsize=8)
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3, axis="y")
    chart3 = fig_to_base64(fig)

    # ── Chart 4: Return % per cycle ──
    fig, ax = plt.subplots(figsize=(12, 4))
    returns = [t.return_pct for t in trades]
    colors = ["#d32f2f" if r > 0 else "#388e3c" for r in returns]  # Red=up, Green=down
    ax.bar(range(len(returns)), returns, color=colors, alpha=0.8)
    ax.axhline(y=0, color="#333333", linewidth=0.8)
    ax.set_title("Return % per Cycle", fontsize=14, fontweight="bold")
    ax.set_xlabel("Cycle")
    ax.set_ylabel("Return (%)")
    ax.set_xticks(range(len(returns)))
    ax.set_xticklabels(cycle_labels, fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")
    chart4 = fig_to_base64(fig)

    # ── Chart 5: Price change distribution ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    price_changes = [t.price_change_pct for t in trades]
    ax1.hist(price_changes, bins=15, color="#7b1fa2", alpha=0.7, edgecolor="white")
    ax1.axvline(x=0, color="#333333", linestyle="--", linewidth=1)
    ax1.axvline(x=-cfg.strike_pct_below*100, color="#d32f2f", linestyle="--", linewidth=1.5,
                label=f"Strike (-{cfg.strike_pct_below*100:.0f}%)")
    ax1.set_title("Distribution of Price Changes per Cycle", fontsize=12, fontweight="bold")
    ax1.set_xlabel("Price Change (%)")
    ax1.set_ylabel("Frequency")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # ITM vs OTM pie
    sizes = [summary["itm_cycles"], summary["otm_cycles"]]
    labels = [f"Put ITM\n({summary['itm_cycles']})", f"Put OTM\n({summary['otm_cycles']})"]
    colors_pie = ["#d32f2f", "#90caf9"]
    ax2.pie(sizes, labels=labels, colors=colors_pie, autopct="%1.0f%%", startangle=90)
    ax2.set_title("Put Outcome Distribution", fontsize=12, fontweight="bold")
    chart5 = fig_to_base64(fig)

    # ── Generate HTML ──
    trade_rows = ""
    for t in trades:
        pnl_color = "#d32f2f" if t.total_pnl > 0 else "#388e3c"
        scenario_color = "#d32f2f" if not t.put_expired else "#666666"
        trade_rows += f"""
        <tr>
            <td>{t.cycle_id}</td>
            <td>{t.entry_date}</td>
            <td>${t.entry_price:.2f}</td>
            <td>{t.exit_date}</td>
            <td>${t.exit_price:.2f}</td>
            <td>${t.strike_price:.2f}</td>
            <td style="color:{scenario_color}">{t.scenario}</td>
            <td style="color:{'#388e3c' if t.stock_pnl < 0 else '#d32f2f'}">${t.stock_pnl:+.2f}</td>
            <td>${t.put_payoff:+.2f}</td>
            <td style="color:#f57c00">-${t.put_cost:.2f}</td>
            <td style="color:{pnl_color};font-weight:bold">${t.total_pnl:+.2f}</td>
            <td style="color:{pnl_color}">{t.return_pct:+.2f}%</td>
        </tr>"""

    # Determine if strategy outperformed buy & hold
    strategy_beats_bh = summary["total_pnl"] > summary["buy_hold_pnl"]
    outperform_text = "优于" if strategy_beats_bh else "劣于"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DRAM ETF Hedge Strategy Simulation Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
               background: #f5f5f5; color: #333; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #1a237e, #283593); color: white;
                   padding: 40px 30px; border-radius: 12px; margin-bottom: 30px;
                   box-shadow: 0 4px 20px rgba(0,0,0,0.15); }}
        .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
        .header .subtitle {{ font-size: 14px; opacity: 0.85; }}
        .header .meta {{ margin-top: 15px; font-size: 13px; opacity: 0.75; }}
        .section {{ background: white; border-radius: 10px; padding: 25px 30px;
                    margin-bottom: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.06); }}
        .section h2 {{ font-size: 20px; color: #1a237e; margin-bottom: 15px;
                       border-bottom: 2px solid #e8eaf6; padding-bottom: 8px; }}
        .section h3 {{ font-size: 16px; color: #283593; margin: 15px 0 10px; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                     gap: 15px; margin-bottom: 20px; }}
        .kpi-card {{ background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 8px;
                     padding: 18px; text-align: center; }}
        .kpi-card .label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
        .kpi-card .value {{ font-size: 24px; font-weight: 700; margin-top: 5px; }}
        .kpi-card .sub {{ font-size: 11px; color: #999; margin-top: 3px; }}
        .kpi-profit {{ color: #d32f2f; }}
        .kpi-loss {{ color: #388e3c; }}
        .kpi-neutral {{ color: #1976d2; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ background: #283593; color: white; padding: 10px 8px; text-align: center;
              font-weight: 600; }}
        td {{ padding: 8px; text-align: center; border-bottom: 1px solid #eee; }}
        tr:nth-child(even) {{ background: #fafafa; }}
        tr:hover {{ background: #e8eaf6; }}
        .chart {{ text-align: center; margin: 20px 0; }}
        .chart img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .strategy-desc {{ background: #e8eaf6; border-radius: 8px; padding: 20px; margin-bottom: 15px; }}
        .strategy-desc ul {{ margin-left: 20px; }}
        .strategy-desc li {{ margin-bottom: 6px; }}
        .highlight-box {{ display: inline-block; padding: 3px 12px; border-radius: 20px;
                          font-size: 13px; font-weight: 600; }}
        .badge-profit {{ background: #ffebee; color: #c62828; }}
        .badge-loss {{ background: #e8f5e9; color: #2e7d32; }}
        .config-table {{ width: 100%; }}
        .config-table td {{ text-align: left; padding: 6px 10px; }}
        .config-table td:first-child {{ font-weight: 600; color: #555; width: 40%; }}
        .footer {{ text-align: center; padding: 20px; color: #999; font-size: 12px;
                   margin-top: 20px; }}
        .warning {{ background: #fff3e0; border-left: 4px solid #ff9800; padding: 12px 16px;
                    border-radius: 4px; margin: 15px 0; font-size: 13px; color: #e65100; }}
    </style>
</head>
<body>
<div class="container">

    <!-- Header -->
    <div class="header">
        <h1>DRAM ETF Hedge Strategy Simulation Report</h1>
        <div class="subtitle">Roundhill Memory ETF (DRAM) | Protective Put Hedging Strategy</div>
        <div class="meta">
            Simulation Period: {cfg.start_date} to {cfg.end_date} |
            Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")} |
            Data Source: {data_source}
        </div>
    </div>

    <!-- Strategy Description -->
    <div class="section">
        <h2>Strategy Overview</h2>
        <div class="strategy-desc">
            <ul>
                <li><strong>Underlying:</strong> Roundhill Memory ETF (ticker: DRAM), tracking global memory chip companies (Micron, SK Hynix, Samsung, etc.)</li>
                <li><strong>Core Idea:</strong> Hold DRAM ETF stock while buying put options as downside protection. The puts act as insurance against price drops beyond a threshold.</li>
                <li><strong>Cycle:</strong> Every {cfg.holding_period_days} trading days, buy {cfg.num_lots} lot(s) ({cfg.shares_per_lot * cfg.num_lots} shares) of DRAM and {cfg.num_put_contracts} put contract(s) at strike = entry_price x (1 - {cfg.strike_pct_below*100:.0f}%)</li>
                <li><strong>Put Premium:</strong> ~${cfg.put_premium_per_contract:.0f} per contract (assumed)</li>
                <li><strong>Hedge Ratio:</strong> {cfg.num_put_contracts} put contracts x {cfg.contract_size} shares = {cfg.num_put_contracts * cfg.contract_size} shares covered, vs {cfg.shares_per_lot * cfg.num_lots} shares held (ratio: {cfg.num_put_contracts * cfg.contract_size / (cfg.shares_per_lot * cfg.num_lots):.1f}:1)</li>
            </ul>
        </div>
        <div class="warning">
            Note: This is a simulation using {data_source}. Option premiums are assumed at ${cfg.put_premium_per_contract:.0f}/contract and do not reflect actual market prices. Results are for educational purposes only.
        </div>
    </div>

    <!-- KPI Summary -->
    <div class="section">
        <h2>Performance Summary</h2>
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="label">Total Cycles</div>
                <div class="value kpi-neutral">{summary['total_cycles']}</div>
                <div class="sub">{summary['itm_cycles']} ITM / {summary['otm_cycles']} OTM</div>
            </div>
            <div class="kpi-card">
                <div class="label">Strategy Total P&L</div>
                <div class="value {'kpi-profit' if summary['total_pnl'] > 0 else 'kpi-loss'}">${summary['total_pnl']:,.2f}</div>
                <div class="sub">Return: {summary['strategy_return_pct']:+.2f}%</div>
            </div>
            <div class="kpi-card">
                <div class="label">Buy & Hold P&L</div>
                <div class="value {'kpi-profit' if summary['buy_hold_pnl'] > 0 else 'kpi-loss'}">${summary['buy_hold_pnl']:,.2f}</div>
                <div class="sub">Return on capital: {summary['buy_hold_return_pct']:+.2f}% | Stock: {summary.get('buy_hold_stock_return_pct', 0):+.2f}%</div>
            </div>
            <div class="kpi-card">
                <div class="label">Win Rate</div>
                <div class="value kpi-neutral">{summary['win_rate_pct']:.1f}%</div>
                <div class="sub">Win/Total: {sum(1 for t in trades if t.total_pnl > 0)}/{summary['total_cycles']}</div>
            </div>
            <div class="kpi-card">
                <div class="label">Total Put Premium</div>
                <div class="value kpi-loss">-${summary['total_put_premium']:,.2f}</div>
                <div class="sub">Hedge cost: {summary['hedge_cost_pct']:.2f}% of capital</div>
            </div>
            <div class="kpi-card">
                <div class="label">Total Put Payoff</div>
                <div class="value kpi-profit">${summary['total_put_payoff']:,.2f}</div>
                <div class="sub">Net: {summary['net_hedge_benefit']:+,.2f}</div>
            </div>
            <div class="kpi-card">
                <div class="label">Best Cycle</div>
                <div class="value kpi-profit">{summary['best_cycle_return_pct']:+.2f}%</div>
                <div class="sub">{summary['best_cycle_date']}</div>
            </div>
            <div class="kpi-card">
                <div class="label">Worst Cycle</div>
                <div class="value kpi-loss">{summary['worst_cycle_return_pct']:+.2f}%</div>
                <div class="sub">{summary['worst_cycle_date']}</div>
            </div>
        </div>

        <h3>Strategy vs Buy & Hold Comparison</h3>
        <table>
            <tr><th>Metric</th><th>Hedge Strategy</th><th>Buy & Hold</th><th>Difference</th></tr>
            <tr>
                <td>Total P&L</td>
                <td>${summary['total_pnl']:,.2f}</td>
                <td>${summary['buy_hold_pnl']:,.2f}</td>
                <td>${summary['total_pnl'] - summary['buy_hold_pnl']:,.2f}</td>
            </tr>
            <tr>
                <td>Return %</td>
                <td>{summary['strategy_return_pct']:+.2f}%<br><span style="font-size:11px;color:#999;">on capital</span></td>
                <td>{summary['buy_hold_return_pct']:+.2f}%<br><span style="font-size:11px;color:#999;">on capital | stock: {summary.get('buy_hold_stock_return_pct', 0):+.2f}%</span></td>
                <td>{summary['strategy_return_pct'] - summary['buy_hold_return_pct']:+.2f}%</td>
            </tr>
            <tr>
                <td>Max Drawdown Protection</td>
                <td>Put limits downside to ~strike level</td>
                <td>Full downside exposure</td>
                <td>Insurance value</td>
            </tr>
            <tr>
                <td>Cost of Hedging</td>
                <td>${summary['total_put_premium']:,.2f} ({summary['hedge_cost_pct']:.2f}%)</td>
                <td>$0</td>
                <td>-${summary['total_put_premium']:,.2f}</td>
            </tr>
        </table>

        <p style="margin-top:15px;">
            <span class="highlight-box {'badge-profit' if strategy_beats_bh else 'badge-loss'}">
                Strategy {outperform_text} Buy & Hold by ${abs(summary['total_pnl'] - summary['buy_hold_pnl']):,.2f}
            </span>
        </p>
    </div>

    <!-- Charts -->
    <div class="section">
        <h2>Visual Analysis</h2>
        <div class="chart"><img src="data:image/png;base64,{chart1}" alt="Price Path"></div>
        <p style="text-align:center;color:#666;font-size:13px;margin-top:-10px;margin-bottom:20px;">
            Blue triangles (^) = entry points; Red/Green triangles (v) = exit points (red=profit, green=loss per Chinese convention)
        </p>
        <div class="chart"><img src="data:image/png;base64,{chart2}" alt="Cumulative P&L"></div>
        <div class="chart"><img src="data:image/png;base64,{chart3}" alt="Per-Cycle Breakdown"></div>
        <div class="chart"><img src="data:image/png;base64,{chart4}" alt="Return per Cycle"></div>
        <div class="chart"><img src="data:image/png;base64,{chart5}" alt="Distribution"></div>
    </div>

    <!-- Trade Detail -->
    <div class="section">
        <h2>Trade-by-Trade Detail</h2>
        <table>
            <tr>
                <th>#</th><th>Entry Date</th><th>Entry Price</th><th>Exit Date</th><th>Exit Price</th>
                <th>Strike</th><th>Scenario</th><th>Stock P&L</th><th>Put Payoff</th>
                <th>Put Cost</th><th>Total P&L</th><th>Return %</th>
            </tr>
            {trade_rows}
        </table>
    </div>

    <!-- Configuration -->
    <div class="section">
        <h2>Simulation Configuration</h2>
        <table class="config-table">
            <tr><td>Initial Capital</td><td>${cfg.initial_capital:,.2f}</td></tr>
            <tr><td>Shares per Lot</td><td>{cfg.shares_per_lot}</td></tr>
            <tr><td>Number of Lots</td><td>{cfg.num_lots}</td></tr>
            <tr><td>Number of Put Contracts</td><td>{cfg.num_put_contracts}</td></tr>
            <tr><td>Contract Size (shares)</td><td>{cfg.contract_size}</td></tr>
            <tr><td>Put Premium per Contract</td><td>${cfg.put_premium_per_contract:.2f}</td></tr>
            <tr><td>Strike % Below Entry</td><td>{cfg.strike_pct_below*100:.1f}%</td></tr>
            <tr><td>Holding Period (trading days)</td><td>{cfg.holding_period_days}</td></tr>
            <tr><td>Start Date</td><td>{cfg.start_date}</td></tr>
            <tr><td>End Date</td><td>{cfg.end_date}</td></tr>
            <tr><td>Data Source</td><td>{data_source}</td></tr>
        </table>
    </div>

    <div class="footer">
        DRAM ETF Hedge Strategy Simulation | Generated by hedge_simulation.py |
        For educational purposes only - not investment advice
    </div>
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Report saved to: {output_path}")


# ─── Parameter Sweeper ───────────────────────────────────────────────────────

def run_parameter_sweep(price_df: pd.DataFrame, cfg: StrategyConfig) -> List[Dict]:
    """Run simulations with different parameter combinations for comparison."""
    print("[4/4] Running parameter sensitivity analysis...")

    sweep_results = []

    # Vary strike percentage
    for strike_pct in [0.01, 0.02, 0.03, 0.05, 0.07, 0.10]:
        test_cfg = StrategyConfig(
            initial_capital=cfg.initial_capital,
            shares_per_lot=cfg.shares_per_lot,
            num_lots=cfg.num_lots,
            num_put_contracts=cfg.num_put_contracts,
            contract_size=cfg.contract_size,
            put_premium_per_contract=cfg.put_premium_per_contract,
            strike_pct_below=strike_pct,
            holding_period_days=cfg.holding_period_days,
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            synth_start_price=cfg.synth_start_price,
            synth_annual_vol=cfg.synth_annual_vol,
            synth_annual_drift=cfg.synth_annual_drift,
            synth_seed=cfg.synth_seed,
        )
        _, sweep_summary = run_simulation(price_df, test_cfg)
        sweep_results.append({
            "param": "strike_pct",
            "value": f"{strike_pct*100:.0f}%",
            "total_pnl": sweep_summary["total_pnl"],
            "strategy_return": sweep_summary["strategy_return_pct"],
            "win_rate": sweep_summary["win_rate_pct"],
            "itm_cycles": sweep_summary["itm_cycles"],
            "total_cycles": sweep_summary["total_cycles"],
            "buy_hold_return": sweep_summary["buy_hold_return_pct"],
        })

    # Vary number of put contracts
    for num_puts in [1, 2, 3, 4]:
        test_cfg = StrategyConfig(
            initial_capital=cfg.initial_capital,
            shares_per_lot=cfg.shares_per_lot,
            num_lots=cfg.num_lots,
            num_put_contracts=num_puts,
            contract_size=cfg.contract_size,
            put_premium_per_contract=cfg.put_premium_per_contract,
            strike_pct_below=cfg.strike_pct_below,
            holding_period_days=cfg.holding_period_days,
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            synth_start_price=cfg.synth_start_price,
            synth_annual_vol=cfg.synth_annual_vol,
            synth_annual_drift=cfg.synth_annual_drift,
            synth_seed=cfg.synth_seed,
        )
        _, sweep_summary = run_simulation(price_df, test_cfg)
        sweep_results.append({
            "param": "num_puts",
            "value": str(num_puts),
            "total_pnl": sweep_summary["total_pnl"],
            "strategy_return": sweep_summary["strategy_return_pct"],
            "win_rate": sweep_summary["win_rate_pct"],
            "itm_cycles": sweep_summary["itm_cycles"],
            "total_cycles": sweep_summary["total_cycles"],
            "buy_hold_return": sweep_summary["buy_hold_return_pct"],
        })

    # Vary holding period
    for period in [5, 8, 12, 15]:
        test_cfg = StrategyConfig(
            initial_capital=cfg.initial_capital,
            shares_per_lot=cfg.shares_per_lot,
            num_lots=cfg.num_lots,
            num_put_contracts=cfg.num_put_contracts,
            contract_size=cfg.contract_size,
            put_premium_per_contract=cfg.put_premium_per_contract,
            strike_pct_below=cfg.strike_pct_below,
            holding_period_days=period,
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            synth_start_price=cfg.synth_start_price,
            synth_annual_vol=cfg.synth_annual_vol,
            synth_annual_drift=cfg.synth_annual_drift,
            synth_seed=cfg.synth_seed,
        )
        _, sweep_summary = run_simulation(price_df, test_cfg)
        sweep_results.append({
            "param": "holding_period",
            "value": f"{period}d",
            "total_pnl": sweep_summary["total_pnl"],
            "strategy_return": sweep_summary["strategy_return_pct"],
            "win_rate": sweep_summary["win_rate_pct"],
            "itm_cycles": sweep_summary["itm_cycles"],
            "total_cycles": sweep_summary["total_cycles"],
            "buy_hold_return": sweep_summary["buy_hold_return_pct"],
        })

    # Vary premium
    for premium in [50, 80, 100, 130, 180, 250]:
        test_cfg = StrategyConfig(
            initial_capital=cfg.initial_capital,
            shares_per_lot=cfg.shares_per_lot,
            num_lots=cfg.num_lots,
            num_put_contracts=cfg.num_put_contracts,
            contract_size=cfg.contract_size,
            put_premium_per_contract=premium,
            strike_pct_below=cfg.strike_pct_below,
            holding_period_days=cfg.holding_period_days,
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            synth_start_price=cfg.synth_start_price,
            synth_annual_vol=cfg.synth_annual_vol,
            synth_annual_drift=cfg.synth_annual_drift,
            synth_seed=cfg.synth_seed,
        )
        _, sweep_summary = run_simulation(price_df, test_cfg)
        sweep_results.append({
            "param": "put_premium",
            "value": f"${premium}",
            "total_pnl": sweep_summary["total_pnl"],
            "strategy_return": sweep_summary["strategy_return_pct"],
            "win_rate": sweep_summary["win_rate_pct"],
            "itm_cycles": sweep_summary["itm_cycles"],
            "total_cycles": sweep_summary["total_cycles"],
            "buy_hold_return": sweep_summary["buy_hold_return_pct"],
        })

    return sweep_results


def generate_sweep_report(sweep_results: List[Dict], output_path: str, cfg: StrategyConfig):
    """Generate parameter sensitivity report (appended to main report as separate file)."""
    # Group by parameter
    params = {}
    for r in sweep_results:
        p = r["param"]
        if p not in params:
            params[p] = []
        params[p].append(r)

    param_names = {
        "strike_pct": "Strike Price % Below Entry",
        "num_puts": "Number of Put Contracts",
        "holding_period": "Holding Period (Trading Days)",
        "put_premium": "Put Premium per Contract",
    }

    tables_html = ""
    for param, name in param_names.items():
        if param not in params:
            continue
        rows = params[param]
        rows_html = ""
        for r in rows:
            pnl_color = "#d32f2f" if r["total_pnl"] > 0 else "#388e3c"
            rows_html += f"""
            <tr>
                <td>{r['value']}</td>
                <td style="color:{pnl_color};font-weight:bold">${r['total_pnl']:,.2f}</td>
                <td style="color:{pnl_color}">{r['strategy_return']:+.2f}%</td>
                <td>{r['win_rate']:.1f}%</td>
                <td>{r['itm_cycles']}/{r['total_cycles']}</td>
            </tr>"""
        tables_html += f"""
        <h3>{name}</h3>
        <table>
            <tr><th>Value</th><th>Total P&L</th><th>Strategy Return</th><th>Win Rate</th><th>ITM/Total</th></tr>
            {rows_html}
        </table>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Parameter Sensitivity Analysis</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background: #f5f5f5; color: #333; }}
        .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #4a148c, #7b1fa2); color: white; padding: 30px; border-radius: 12px; margin-bottom: 25px; }}
        .header h1 {{ font-size: 24px; }}
        .section {{ background: white; border-radius: 10px; padding: 25px 30px; margin-bottom: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.06); }}
        .section h2 {{ color: #4a148c; margin-bottom: 15px; border-bottom: 2px solid #e1bee7; padding-bottom: 8px; }}
        .section h3 {{ color: #6a1b9a; margin: 20px 0 10px; font-size: 16px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 15px; }}
        th {{ background: #7b1fa2; color: white; padding: 10px; text-align: center; }}
        td {{ padding: 8px; text-align: center; border-bottom: 1px solid #eee; }}
        tr:nth-child(even) {{ background: #fafafa; }}
        .footer {{ text-align: center; padding: 20px; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Parameter Sensitivity Analysis</h1>
        <p style="opacity:0.85;margin-top:5px;">How different parameters affect the hedge strategy performance</p>
    </div>
    <div class="section">
        <h2>Sensitivity Tables</h2>
        <p style="margin-bottom:15px;color:#666;">
            Each table shows strategy performance when varying one parameter while keeping others at default.
            Buy & Hold return for reference: all simulations use the same price data.
        </p>
        {tables_html}
    </div>
    <div class="footer">
        Parameter Sensitivity Analysis | hedge_simulation.py | For educational purposes only
    </div>
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Sensitivity report saved to: {output_path}")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DRAM ETF Hedge Strategy Simulation")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital (USD)")
    parser.add_argument("--shares-per-lot", type=int, default=100, help="Shares per lot")
    parser.add_argument("--num-lots", type=int, default=1, help="Number of lots")
    parser.add_argument("--num-puts", type=int, default=2, help="Number of put contracts")
    parser.add_argument("--contract-size", type=int, default=100, help="Shares per option contract")
    parser.add_argument("--premium", type=float, default=130.0, help="Put premium per contract (USD)")
    parser.add_argument("--strike-pct", type=float, default=0.03, help="Strike % below entry (e.g. 0.03 = 3%)")
    parser.add_argument("--period", type=int, default=12, help="Holding period in trading days")
    parser.add_argument("--start", type=str, default="2026-01-05", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default="2026-08-05", help="End date YYYY-MM-DD")
    parser.add_argument("--synth-price", type=float, default=55.0, help="Synthetic data starting price")
    parser.add_argument("--synth-vol", type=float, default=0.45, help="Synthetic data annual volatility")
    parser.add_argument("--synth-drift", type=float, default=0.15, help="Synthetic data annual drift")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-dir", type=str, default="/Users/gavinz/git/finance/hedge", help="Output directory")
    parser.add_argument("--no-sweep", action="store_true", help="Skip parameter sensitivity analysis")
    args = parser.parse_args()

    cfg = StrategyConfig(
        initial_capital=args.capital,
        shares_per_lot=args.shares_per_lot,
        num_lots=args.num_lots,
        num_put_contracts=args.num_puts,
        contract_size=args.contract_size,
        put_premium_per_contract=args.premium,
        strike_pct_below=args.strike_pct,
        holding_period_days=args.period,
        start_date=args.start,
        end_date=args.end,
        synth_start_price=args.synth_price,
        synth_annual_vol=args.synth_vol,
        synth_annual_drift=args.synth_drift,
        synth_seed=args.seed,
        output_dir=args.output_dir,
    )

    print("=" * 60)
    print("  DRAM ETF Hedge Strategy Simulation")
    print("=" * 60)

    # Step 1: Get price data
    price_df, data_source = get_price_data(cfg)

    # Step 2: Run simulation
    trades, summary = run_simulation(price_df, cfg)
    summary["data_source"] = data_source

    # Step 3: Generate report
    report_path = os.path.join(cfg.output_dir, "hedge_report.html")
    generate_report(trades, summary, price_df, cfg, data_source, report_path)

    # Step 4: Parameter sweep (optional)
    if not args.no_sweep:
        sweep_results = run_parameter_sweep(price_df, cfg)
        sweep_path = os.path.join(cfg.output_dir, "hedge_sensitivity.html")
        generate_sweep_report(sweep_results, sweep_path, cfg)

    # Save trade data as JSON
    json_path = os.path.join(cfg.output_dir, "hedge_trades.json")
    trade_data = [asdict(t) for t in trades]
    with open(json_path, "w") as f:
        json.dump({"trades": trade_data, "summary": summary}, f, indent=2, default=str)
    print(f"  Trade data saved to: {json_path}")

    # Save price data
    csv_path = os.path.join(cfg.output_dir, "dram_price_data.csv")
    price_df.to_csv(csv_path, index=False)
    print(f"  Price data saved to: {csv_path}")

    print()
    print("=" * 60)
    print("  SIMULATION COMPLETE")
    print(f"  Strategy P&L:   ${summary['total_pnl']:,.2f} ({summary['strategy_return_pct']:+.2f}%)")
    print(f"  Buy & Hold:     ${summary['buy_hold_pnl']:,.2f} ({summary['buy_hold_return_pct']:+.2f}%)")
    print(f"  Cycles:         {summary['total_cycles']}")
    print(f"  Win Rate:       {summary['win_rate_pct']:.1f}%")
    print(f"  Reports:        {cfg.output_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
