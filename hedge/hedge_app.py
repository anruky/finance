#!/usr/bin/env python3
"""
DRAM ETF Hedge Strategy - Interactive Web App
=============================================
Interactive web UI for running DRAM hedge strategy simulations with
adjustable parameters. Shows per-cycle results and charts in real-time.

Usage:
  python3 hedge_app.py
  Then open http://localhost:5567 in your browser.
"""

import os
import sys
import json
import math
import random
import sqlite3
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'hedge_history.db')


# ============================================================
# Simulation Engine (inlined for self-contained execution)
# ============================================================

@dataclass
class StrategyConfig:
    shares_per_lot: int = 100
    num_lots: int = 1
    num_put_contracts: int = 2
    contract_size: int = 100
    strike_pct_below: float = 0.03
    holding_period_calendar_days: int = 14  # 1wk=5, 2wk=14, 3wk=21
    risk_free_rate: float = 0.045  # 10Y Treasury yield approximation
    start_date: str = "2026-01-05"
    end_date: str = "2026-08-05"
    synth_start_price: float = 55.0
    synth_annual_vol: float = 0.45
    synth_annual_drift: float = 0.15
    synth_seed: int = 42


# ============================================================
# Black-Scholes Option Pricing
# ============================================================

def _norm_cdf(x):
    """Cumulative distribution function of standard normal."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_put(S, K, T, r, sigma):
    """
    Black-Scholes put option price.

    S: spot price
    K: strike price
    T: time to expiry (in years)
    r: risk-free rate (annualized)
    sigma: volatility (annualized)
    """
    if T <= 0 or sigma <= 0:
        # Intrinsic value at expiry
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    put_price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    return max(put_price, 0.0)


def load_real_data():
    """Load real DRAM ETF price data from CSV."""
    csv_path = os.path.join(BASE_DIR, 'dram_price_data.csv')
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path)
    df['date'] = df['date'].astype(str)
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['volume'] = df['volume'].astype(int)
    return df


def calc_realized_vol(df, window=None):
    """Calculate annualized realized volatility from price data."""
    if df is None or len(df) < 2:
        return 0.45  # fallback
    closes = df['close'].values
    log_returns = np.diff(np.log(closes))
    if window and len(log_returns) > window:
        log_returns = log_returns[-window:]
    daily_vol = np.std(log_returns, ddof=1)
    annual_vol = daily_vol * np.sqrt(252)
    return float(annual_vol)


def generate_synthetic_data(cfg, extra_days_before=0):
    """Generate synthetic data for pre-launch period or what-if scenarios."""
    np.random.seed(cfg.synth_seed)
    random.seed(cfg.synth_seed)
    start = pd.Timestamp(cfg.start_date)
    end = pd.Timestamp(cfg.end_date)
    # If extra_days_before > 0, start earlier to splice with real data
    if extra_days_before > 0:
        start = start - pd.Timedelta(days=extra_days_before)
    dates = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            dates.append(d)
        d += pd.Timedelta(days=1)
    n = len(dates)
    if n == 0:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    dt = 1.0 / 252.0
    drift = cfg.synth_annual_drift
    vol = cfg.synth_annual_vol
    S0 = cfg.synth_start_price
    returns = np.zeros(n)
    for i in range(n):
        r = (drift - 0.5 * vol**2) * dt + vol * np.sqrt(dt) * np.random.standard_normal()
        returns[i] = r
    prices = np.zeros(n)
    prices[0] = S0
    for i in range(1, n):
        prices[i] = prices[i-1] * np.exp(returns[i])
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


def get_price_data(cfg, use_real=True, synth_vol_override=None):
    """
    Get price data: real DRAM data if available, or synthetic.
    Returns (DataFrame, realized_vol, data_source_info).
    """
    real_df = load_real_data() if use_real else None
    if real_df is not None and len(real_df) > 0:
        # Filter by date range
        mask = (real_df['date'] >= cfg.start_date) & (real_df['date'] <= cfg.end_date)
        filtered = real_df[mask].copy().reset_index(drop=True)
        if len(filtered) > 1:
            realized_vol = calc_realized_vol(filtered)
            # If user overrides vol for Black-Scholes, use that instead
            bs_vol = synth_vol_override if synth_vol_override else realized_vol
            info = {
                "source": "real",
                "first_date": filtered.iloc[0]['date'],
                "last_date": filtered.iloc[-1]['date'],
                "first_price": float(filtered.iloc[0]['close']),
                "last_price": float(filtered.iloc[-1]['close']),
                "data_points": len(filtered),
                "realized_vol": round(realized_vol, 4),
                "bs_vol": round(bs_vol, 4),
                "ipo_date": str(real_df.iloc[0]['date']),
                "ipo_price": float(real_df.iloc[0]['close']),
            }
            return filtered, bs_vol, info
    # Fallback to synthetic
    synth_df = generate_synthetic_data(cfg)
    bs_vol = synth_vol_override if synth_vol_override else cfg.synth_annual_vol
    info = {
        "source": "synthetic",
        "first_date": synth_df.iloc[0]['date'] if len(synth_df) > 0 else "",
        "last_date": synth_df.iloc[-1]['date'] if len(synth_df) > 0 else "",
        "first_price": float(synth_df.iloc[0]['close']) if len(synth_df) > 0 else 0,
        "last_price": float(synth_df.iloc[-1]['close']) if len(synth_df) > 0 else 0,
        "data_points": len(synth_df),
        "realized_vol": 0.0,
        "bs_vol": round(bs_vol, 4),
        "ipo_date": "",
        "ipo_price": 0,
    }
    return synth_df, bs_vol, info


def run_simulation(price_df, cfg, bs_vol=None):
    """Run hedge simulation. bs_vol overrides volatility for Black-Scholes pricing."""
    if bs_vol is None:
        bs_vol = cfg.synth_annual_vol
    prices = price_df.set_index("date")["close"]
    dates = list(prices.index)
    # Build a list of pd.Timestamp for calendar-day math
    date_ts = [pd.Timestamp(d) for d in dates]
    trades = []
    cycle_id = 0
    i = 0
    while i < len(dates) and dates[i] < cfg.start_date:
        i += 1
    cal_days = cfg.holding_period_calendar_days
    while i < len(dates):
        entry_date = dates[i]
        entry_price = prices[entry_date]
        # Find exit date: target = entry_date + calendar_days
        target_exit = date_ts[i] + pd.Timedelta(days=cal_days)
        # Find the trading day closest to target_exit (on or before; if weekend, use previous trading day)
        exit_idx = i
        for j in range(i + 1, len(dates)):
            if date_ts[j] <= target_exit:
                exit_idx = j
            else:
                break
        # If target is before the next trading day (e.g. 5-day option lands on a weekend),
        # exit_idx stays at the closest prior trading day
        if exit_idx == i:
            exit_idx = min(i + 1, len(dates) - 1)
        # Skip if not enough data for a full cycle (entry and exit must differ)
        if exit_idx <= i:
            break
        exit_date = dates[exit_idx]
        exit_price = prices[exit_date]
        strike = entry_price * (1.0 - cfg.strike_pct_below)
        shares = cfg.shares_per_lot * cfg.num_lots
        num_puts = cfg.num_put_contracts
        put_shares_covered = num_puts * cfg.contract_size
        # ── Dynamic premium via Black-Scholes ──
        # T = calendar days / 365 (not trading days / 252)
        T = cal_days / 365.0  # time to expiry in years
        bs_price_per_share = black_scholes_put(
            S=entry_price,
            K=strike,
            T=T,
            r=cfg.risk_free_rate,
            sigma=bs_vol,
        )
        premium_per_contract = bs_price_per_share * cfg.contract_size
        premium_total = num_puts * premium_per_contract
        stock_value = entry_price * shares
        stock_pnl = (exit_price - entry_price) * shares
        stock_return_pct = (exit_price - entry_price) / entry_price * 100
        if exit_price < strike:
            put_payoff = (strike - exit_price) * put_shares_covered
            put_expired = False
            scenario = "A: Put ITM"
        else:
            put_payoff = 0.0
            put_expired = True
            scenario = "B: Put OTM"
        put_cost = premium_total
        total_pnl = stock_pnl + put_payoff - put_cost
        return_pct = total_pnl / stock_value * 100 if stock_value > 0 else 0
        put_notional = strike * put_shares_covered
        hedge_ratio = put_notional / stock_value
        # Calendar days between entry and exit
        actual_cal_days = (date_ts[exit_idx] - date_ts[i]).days
        trades.append({
            "cycle_id": cycle_id,
            "entry_date": entry_date,
            "entry_price": round(float(entry_price), 2),
            "exit_date": exit_date,
            "exit_price": round(float(exit_price), 2),
            "trading_days": exit_idx - i,
            "calendar_days": actual_cal_days,
            "strike_price": round(float(strike), 2),
            "put_expired": put_expired,
            "shares_held": shares,
            "num_puts": num_puts,
            "premium_per_contract": round(float(premium_per_contract), 2),
            "put_premium_total": round(premium_total, 2),
            "stock_pnl": round(stock_pnl, 2),
            "put_payoff": round(put_payoff, 2),
            "put_cost": round(put_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(return_pct, 2),
            "price_change_pct": round(stock_return_pct, 2),
            "hedge_ratio": round(hedge_ratio, 2),
            "scenario": scenario,
        })
        cycle_id += 1
        i = exit_idx + 1

    total_cycles = len(trades)
    itm_cycles = sum(1 for t in trades if not t["put_expired"])
    otm_cycles = sum(1 for t in trades if t["put_expired"])
    total_pnl = sum(t["total_pnl"] for t in trades)
    total_stock_pnl = sum(t["stock_pnl"] for t in trades)
    total_put_premium = sum(t["put_cost"] for t in trades)
    total_put_payoff = sum(t["put_payoff"] for t in trades)
    first_price = trades[0]["entry_price"] if trades else 0
    last_price = trades[-1]["exit_price"] if trades else 0
    bh_shares = cfg.shares_per_lot * cfg.num_lots
    bh_pnl = (last_price - first_price) * bh_shares
    bh_stock_return = (last_price - first_price) / first_price * 100 if first_price > 0 else 0
    # ── Dynamic initial capital: first cycle stock cost + first cycle put premium ──
    if trades:
        stock_cost = trades[0]["entry_price"] * bh_shares
        first_put_premium = trades[0]["put_cost"]
        initial_capital = stock_cost + first_put_premium
    else:
        initial_capital = 0
    bh_return = bh_pnl / initial_capital * 100 if initial_capital > 0 else 0
    strategy_return = total_pnl / initial_capital * 100 if initial_capital > 0 else 0
    avg_cycle_return = float(np.mean([t["return_pct"] for t in trades])) if trades else 0
    best_cycle = max(trades, key=lambda t: t["return_pct"]) if trades else None
    worst_cycle = min(trades, key=lambda t: t["return_pct"]) if trades else None
    win_cycles = sum(1 for t in trades if t["total_pnl"] > 0)
    win_rate = win_cycles / total_cycles * 100 if total_cycles > 0 else 0
    avg_price_change = float(np.mean([t["price_change_pct"] for t in trades])) if trades else 0

    # Annualized returns — use actual data span (first entry → last exit)
    if trades:
        from datetime import datetime as _dt
        first_dt = _dt.strptime(trades[0]["entry_date"], "%Y-%m-%d")
        last_dt = _dt.strptime(trades[-1]["exit_date"], "%Y-%m-%d")
        total_span_days = max((last_dt - first_dt).days, 1)
    else:
        total_span_days = 1
    years = total_span_days / 365.0
    if years >= 1.0:
        # CAGR for periods >= 1 year
        ann_strategy = ((1 + strategy_return / 100) ** (1 / years) - 1) * 100
        ann_bh = ((1 + bh_return / 100) ** (1 / years) - 1) * 100
    else:
        # Simple annualization for sub-annual periods
        ann_strategy = strategy_return / years
        ann_bh = bh_return / years

    summary = {
        "total_cycles": total_cycles,
        "itm_cycles": itm_cycles,
        "otm_cycles": otm_cycles,
        "initial_capital": round(initial_capital, 2),
        "final_capital": round(initial_capital + total_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_stock_pnl": round(total_stock_pnl, 2),
        "total_put_premium": round(total_put_premium, 2),
        "total_put_payoff": round(total_put_payoff, 2),
        "strategy_return_pct": round(strategy_return, 2),
        "annualized_return_pct": round(ann_strategy, 2),
        "avg_cycle_return_pct": round(avg_cycle_return, 2),
        "best_cycle_return_pct": round(best_cycle["return_pct"], 2) if best_cycle else 0,
        "best_cycle_date": best_cycle["entry_date"] if best_cycle else "",
        "worst_cycle_return_pct": round(worst_cycle["return_pct"], 2) if worst_cycle else 0,
        "worst_cycle_date": worst_cycle["entry_date"] if worst_cycle else "",
        "win_rate_pct": round(win_rate, 2),
        "buy_hold_pnl": round(bh_pnl, 2),
        "buy_hold_return_pct": round(bh_return, 2),
        "buy_hold_annualized_pct": round(ann_bh, 2),
        "buy_hold_stock_return_pct": round(bh_stock_return, 2),
        "hedge_cost_pct": round(total_put_premium / initial_capital * 100, 2) if initial_capital > 0 else 0,
        "avg_price_change_pct": round(avg_price_change, 2),
        "itm_rate_pct": round(itm_cycles / total_cycles * 100, 2) if total_cycles > 0 else 0,
        "net_hedge_benefit": round(total_put_payoff - total_put_premium, 2),
        "first_price": first_price,
        "last_price": last_price,
    }
    return trades, summary


# ============================================================
# Flask Routes
# ============================================================

@app.route('/')
def index():
    return HTML_PAGE


@app.route('/api/run', methods=['POST'])
def api_run():
    try:
        p = request.json
        use_real = p.get('use_real', True)
        # Volatility override: if user sets it, use it; otherwise auto from real data
        vol_override = p.get('vol_override', None)
        cfg = StrategyConfig(
            shares_per_lot=int(p.get('shares_per_lot', 100)),
            num_lots=int(p.get('num_lots', 1)),
            num_put_contracts=int(p.get('num_puts', 2)),
            contract_size=int(p.get('contract_size', 100)),
            strike_pct_below=float(p.get('strike_pct', 0.03)),
            holding_period_calendar_days=int(p.get('holding_period', 14)),
            risk_free_rate=float(p.get('risk_free_rate', 0.045)),
            start_date=p.get('start_date', '2026-04-02'),
            end_date=p.get('end_date', '2026-08-05'),
            synth_start_price=float(p.get('synth_price', 55)),
            synth_annual_vol=float(p.get('synth_vol', 0.45)),
            synth_annual_drift=float(p.get('synth_drift', 0.15)),
            synth_seed=int(p.get('seed', 42)),
        )
        # Get price data (real or synthetic)
        price_df, bs_vol, data_info = get_price_data(cfg, use_real=use_real, synth_vol_override=vol_override)
        trades, summary = run_simulation(price_df, cfg, bs_vol=bs_vol)
        # Save to history
        run_id = save_run({
            'strike_pct': float(p.get('strike_pct', 0.03)),
            'num_puts': int(p.get('num_puts', 2)),
            'holding_period': int(p.get('holding_period', 12)),
            'risk_free_rate': float(p.get('risk_free_rate', 0.045)),
            'shares_per_lot': int(p.get('shares_per_lot', 100)),
            'num_lots': int(p.get('num_lots', 1)),
            'contract_size': int(p.get('contract_size', 100)),
            'start_date': p.get('start_date', '2026-04-02'),
            'end_date': p.get('end_date', '2026-08-05'),
            'use_real': use_real,
            'synth_price': float(p.get('synth_price', 55)),
            'synth_vol': float(p.get('synth_vol', 0.45)),
            'synth_drift': float(p.get('synth_drift', 0.15)),
            'seed': int(p.get('seed', 42)),
            'vol_override': vol_override,
        }, summary)
        # Also return price data for chart
        price_data = []
        for _, row in price_df.iterrows():
            price_data.append({
                "date": row['date'],
                "close": float(row['close']),
            })
        return jsonify({
            "trades": trades,
            "summary": summary,
            "price_data": price_data,
            "config": asdict(cfg),
            "data_info": data_info,
            "bs_vol": round(bs_vol, 4),
            "run_id": run_id,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 400


@app.route('/api/price_data', methods=['POST'])
def api_price_data():
    try:
        p = request.json
        use_real = p.get('use_real', True)
        vol_override = p.get('vol_override', None)
        cfg = StrategyConfig(
            synth_start_price=float(p.get('synth_price', 55)),
            synth_annual_vol=float(p.get('synth_vol', 0.45)),
            synth_annual_drift=float(p.get('synth_drift', 0.15)),
            synth_seed=int(p.get('seed', 42)),
            start_date=p.get('start_date', '2026-04-02'),
            end_date=p.get('end_date', '2026-08-05'),
        )
        price_df, bs_vol, data_info = get_price_data(cfg, use_real=use_real, synth_vol_override=vol_override)
        price_data = []
        for _, row in price_df.iterrows():
            price_data.append({"date": row['date'], "close": float(row['close'])})
        return jsonify({"price_data": price_data, "data_info": data_info, "bs_vol": round(bs_vol, 4)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/history')
def api_history():
    return jsonify(get_history())


@app.route('/api/history/<int:run_id>', methods=['DELETE'])
def api_delete_run(run_id):
    delete_run(run_id)
    return jsonify({'status': 'deleted'})


# ============================================================
# Database (History)
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            params_json TEXT NOT NULL,
            total_pnl REAL,
            strategy_return_pct REAL,
            buy_hold_pnl REAL,
            buy_hold_return_pct REAL,
            win_rate_pct REAL,
            total_cycles INTEGER,
            itm_cycles INTEGER,
            otm_cycles INTEGER,
            total_put_premium REAL,
            total_put_payoff REAL,
            net_hedge_benefit REAL,
            strike_pct REAL,
            num_puts INTEGER,
            holding_period INTEGER,
            risk_free_rate REAL,
            synth_vol REAL
        )
    ''')
    conn.commit()
    conn.close()


def save_run(params, s):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT INTO runs (timestamp, params_json,
                          total_pnl, strategy_return_pct, buy_hold_pnl, buy_hold_return_pct,
                          win_rate_pct, total_cycles, itm_cycles, otm_cycles,
                          total_put_premium, total_put_payoff, net_hedge_benefit,
                          strike_pct, num_puts, holding_period, risk_free_rate, synth_vol)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        json.dumps(params),
        s['total_pnl'], s['strategy_return_pct'], s['buy_hold_pnl'], s['buy_hold_return_pct'],
        s['win_rate_pct'], s['total_cycles'], s['itm_cycles'], s['otm_cycles'],
        s['total_put_premium'], s['total_put_payoff'], s['net_hedge_benefit'],
        params.get('strike_pct', 0.03), params.get('num_puts', 2),
        params.get('holding_period', 12), params.get('risk_free_rate', 0.045),
        params.get('synth_vol', 0.45),
    ))
    conn.commit()
    run_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return run_id


def get_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('''
        SELECT id, timestamp, params_json,
               total_pnl, strategy_return_pct, buy_hold_pnl, buy_hold_return_pct,
               win_rate_pct, total_cycles, itm_cycles, otm_cycles,
               total_put_premium, total_put_payoff, net_hedge_benefit,
               strike_pct, num_puts, holding_period, risk_free_rate, synth_vol
        FROM runs ORDER BY id DESC LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    history = []
    for r in rows:
        history.append({
            'id': r[0], 'timestamp': r[1], 'params': json.loads(r[2]),
            'total_pnl': r[3], 'strategy_return_pct': r[4],
            'buy_hold_pnl': r[5], 'buy_hold_return_pct': r[6],
            'win_rate_pct': r[7], 'total_cycles': r[8],
            'itm_cycles': r[9], 'otm_cycles': r[10],
            'total_put_premium': r[11], 'total_put_payoff': r[12],
            'net_hedge_benefit': r[13],
            'strike_pct': r[14], 'num_puts': r[15], 'holding_period': r[16],
            'risk_free_rate': r[17], 'synth_vol': r[18],
        })
    return history


def delete_run(run_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM runs WHERE id=?', (run_id,))
    conn.commit()
    conn.close()


# ============================================================
# HTML Page
# ============================================================

HTML_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM ETF Hedge Strategy Simulator</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; color: #333; }

.header { background: linear-gradient(135deg, #1a237e 0%, #283593 100%); color: white; padding: 20px 30px; }
.header h1 { font-size: 24px; font-weight: 700; }
.header p { font-size: 13px; opacity: 0.85; margin-top: 4px; }

.container { max-width: 1400px; margin: 0 auto; padding: 20px; display: grid; grid-template-columns: 380px 1fr; gap: 20px; }
.left-panel { display: flex; flex-direction: column; gap: 16px; }
.right-panel { display: flex; flex-direction: column; gap: 16px; }

.card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card h2 { font-size: 15px; font-weight: 700; margin-bottom: 14px; color: #1a1a2e; }

/* Param rows */
.param-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.param-row label { font-size: 12px; color: #666; flex-shrink: 0; }
.param-row input, .param-row select { width: 90px; padding: 5px 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; text-align: right; font-weight: 600; }
.param-row input:focus, .param-row select:focus { border-color: #283593; outline: none; }

/* Slider rows */
.slider-row { margin-bottom: 12px; }
.slider-row .slider-label { display: flex; justify-content: space-between; font-size: 12px; color: #666; margin-bottom: 4px; }
.slider-row .slider-label .val { font-weight: 700; color: #283593; }
.slider-row input[type=range] { width: 100%; -webkit-appearance: none; height: 6px; background: #e0e0e0; border-radius: 3px; outline: none; }
.slider-row input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; background: #283593; border-radius: 50%; cursor: pointer; }

/* Preset buttons */
.preset-row { display: flex; gap: 6px; margin-top: 10px; }
.preset-btn { flex: 1; padding: 8px 4px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; font-size: 11px; font-weight: 600; color: #283593; transition: all 0.15s; }
.preset-btn:hover { background: #e8eaf6; border-color: #283593; }
.preset-btn.active { background: #283593; color: white; border-color: #283593; }

/* Run button */
.run-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #1a237e, #283593); color: white; border: none; border-radius: 10px; font-size: 15px; font-weight: 700; cursor: pointer; transition: all 0.2s; }
.run-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(26,35,126,0.4); }
.run-btn:active { transform: translateY(0); }
.run-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

/* Summary cards */
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.metric-card { background: white; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.metric-label { font-size: 11px; color: #888; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.metric-value { font-size: 22px; font-weight: 800; }
.metric-sub { font-size: 11px; color: #aaa; margin-top: 4px; }
.profit { color: #d32f2f; }
.loss { color: #388e3c; }
.neutral { color: #283593; }

/* Income/Cost */
.ic-section { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.ic-col { background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.ic-col h3 { font-size: 12px; color: #888; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
.ic-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.ic-total { border-top: 1px solid #eee; margin-top: 6px; padding-top: 8px; font-weight: 700; }

/* Charts */
.chart-container { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.chart-container h3 { font-size: 14px; font-weight: 700; margin-bottom: 12px; color: #1a1a2e; }
.chart-wrapper { position: relative; height: 300px; }

/* Trade table */
.trade-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.trade-table th { text-align: center; padding: 8px 6px; background: #283593; color: white; font-weight: 600; white-space: nowrap; position: sticky; top: 0; }
.trade-table td { padding: 7px 6px; text-align: center; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
.trade-table tr:nth-child(even) { background: #fafafa; }
.trade-table tr:hover { background: #e8eaf6; }
.badge-itm { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; background: #ffebee; color: #c62828; }
.badge-otm { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; background: #e3f2fd; color: #1565c0; }

/* Loading */
.loading-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.85); display: none; align-items: center; justify-content: center; z-index: 999; }
.loading-overlay.show { display: flex; }
.spinner { width: 40px; height: 40px; border: 4px solid #e0e0e0; border-top-color: #283593; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { margin-top: 12px; color: #283593; font-weight: 600; }

/* Empty state */
.empty { text-align: center; padding: 60px; color: #aaa; font-size: 15px; }

/* History table */
.history-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.history-table th { text-align: left; padding: 8px 8px; background: #283593; color: white; font-weight: 600; border-bottom: 2px solid #1a237e; white-space: nowrap; }
.history-table td { padding: 7px 8px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
.history-table tr:hover { background: #e8eaf6; cursor: pointer; }
.history-table .del-btn { color: #c62828; cursor: pointer; font-size: 14px; }
.history-table .del-btn:hover { font-weight: 700; }
.history-table .apply-btn { color: #283593; cursor: pointer; font-size: 11px; font-weight: 600; padding: 2px 8px; border: 1px solid #283593; border-radius: 4px; display: inline-block; }
.history-table .apply-btn:hover { background: #283593; color: white; }

/* Tabs */
.tab-row { display: flex; gap: 4px; margin-bottom: 0; }
.tab-btn { padding: 8px 16px; border: none; border-radius: 8px 8px 0 0; background: #e8eaf6; cursor: pointer; font-size: 13px; font-weight: 600; color: #666; }
.tab-btn.active { background: white; color: #1a237e; }
</style>
</head>
<body>

<div class="header">
  <h1>DRAM ETF Hedge Strategy Simulator</h1>
  <p>Roundhill Memory ETF (DRAM) | Hold stock + Buy put options as hedge | Adjust parameters and run simulation</p>
</div>

<div class="container">
  <!-- Left Panel: Controls -->
  <div class="left-panel">
    <!-- Strategy Parameters -->
    <div class="card">
      <h2>1. Strategy Parameters</h2>
      <div class="slider-row">
        <div class="slider-label"><span>Strike % Below Entry</span><span class="val" id="strikePctVal">3%</span></div>
        <input type="range" id="strikePct" min="1" max="15" value="3" step="0.5" oninput="updateSlider('strikePct','strikePctVal','%')">
      </div>
      <div class="param-row">
        <label>Number of Put Contracts</label>
        <input type="number" id="numPuts" value="3" min="1" max="10" style="width:60px">
      </div>
      <div class="param-row">
        <label>Holding Period (calendar days)</label>
        <select id="holdingPeriod" style="width:120px">
          <option value="5" selected>1 week (5d)</option>
          <option value="14">2 weeks (14d)</option>
          <option value="21">3 weeks (21d)</option>
        </select>
        <div style="font-size:10px;color:#999;margin-top:2px;">Mon buy → Fri expire (1wk) or Mon→Mon+2wk (14d)</div>
      </div>
      <div class="preset-row">
        <button class="preset-btn" onclick="applyPreset('aggressive')">Aggressive</button>
        <button class="preset-btn active" onclick="applyPreset('balanced')">Balanced</button>
        <button class="preset-btn" onclick="applyPreset('conservative')">Conservative</button>
      </div>
    </div>

    <!-- Position Parameters -->
    <div class="card">
      <h2>2. Position Parameters</h2>
      <div class="param-row">
        <label>Shares per Lot</label>
        <input type="number" id="sharesPerLot" value="100" min="1" max="1000" style="width:70px">
      </div>
      <div class="param-row">
        <label>Number of Lots</label>
        <input type="number" id="numLots" value="1" min="1" max="20" style="width:60px">
      </div>
      <div class="param-row">
        <label>Contract Size (shares)</label>
        <input type="number" id="contractSize" value="100" min="1" max="1000" style="width:70px">
      </div>
      <div style="font-size:11px;color:#666;margin-top:6px;padding:6px 8px;background:#f5f5f5;border-radius:4px;">
        Initial Capital = auto-calculated<br>(stock cost + put premium for first cycle)
      </div>
    </div>

    <!-- Data Parameters -->
    <div class="card">
      <h2>3. Market Data</h2>
      <div class="param-row" style="flex-direction:column;gap:6px;">
        <label>Data Source</label>
        <div style="display:flex;gap:8px;">
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-weight:400;">
            <input type="radio" name="dataSource" value="real" checked onchange="toggleDataSource()"> Real DRAM Data
          </label>
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-weight:400;">
            <input type="radio" name="dataSource" value="synthetic" onchange="toggleDataSource()"> Synthetic
          </label>
        </div>
      </div>
      <div id="realDataInfo" style="background:#f0f7ff;border:1px solid #c5e0f7;border-radius:6px;padding:8px 10px;font-size:11px;color:#333;margin-bottom:8px;">
        <strong>DRAM ETF (Roundhill Memory ETF)</strong><br>
        IPO: 2026-04-02 @ $27.76 | Latest: 2026-08-05 @ $53.74<br>
        Volatility auto-calculated from real data
      </div>
      <div class="param-row">
        <label>Start Date</label>
        <input type="date" id="startDate" value="2026-04-02" style="width:130px">
      </div>
      <div class="param-row">
        <label>End Date</label>
        <input type="date" id="endDate" value="2026-08-05" style="width:130px">
      </div>
      <div class="slider-row">
        <div class="slider-label"><span>Volatility (for BS pricing)</span><span class="val" id="synthVolVal">50%</span></div>
        <input type="range" id="synthVol" min="0" max="100" value="50" step="1" oninput="updateVolSlider()">
        <div style="font-size:10px;color:#999;margin-top:2px;">0 = Auto from real data; >0 = manual override</div>
      </div>
      <div class="slider-row">
        <div class="slider-label"><span>Risk-Free Rate (10Y Treasury)</span><span class="val" id="riskFreeRateVal">4.5%</span></div>
        <input type="range" id="riskFreeRate" min="0" max="10" value="4.5" step="0.5" oninput="updateSlider('riskFreeRate','riskFreeRateVal','%')">
        <div style="font-size:10px;color:#999;margin-top:2px;">Used in Black-Scholes put pricing</div>
      </div>
      <div id="synthParams" style="display:none;">
        <div class="param-row">
          <label>Starting Price ($)</label>
          <input type="number" id="synthPrice" value="55" min="1" max="500" step="0.5" style="width:70px">
        </div>
        <div class="slider-row">
          <div class="slider-label"><span>Annual Drift (Trend)</span><span class="val" id="synthDriftVal">15%</span></div>
          <input type="range" id="synthDrift" min="-50" max="80" value="15" step="1" oninput="updateSlider('synthDrift','synthDriftVal','%')">
        </div>
        <div class="param-row">
          <label>Random Seed</label>
          <input type="number" id="seed" value="42" min="0" max="9999" style="width:60px">
        </div>
      </div>
      <div style="font-size:11px;color:#999;margin-top:6px;">Put premium dynamically priced via Black-Scholes. Real data: DRAM ETF (Cboe BZX). Synthetic: GBM model for what-if scenarios.</div>
    </div>

    <button class="run-btn" id="runBtn" onclick="runSimulation()">Run Simulation</button>
  </div>

  <!-- Right Panel: Results -->
  <div class="right-panel">
    <div id="emptyState" class="card empty">
      Click "Run Simulation" to see results
    </div>

    <div id="resultsSection" style="display:none;">
      <!-- Summary Cards -->
      <div class="summary-grid" id="summaryGrid"></div>

      <!-- Income/Cost Breakdown -->
      <div class="ic-section" id="icSection"></div>

      <!-- Charts -->
      <div class="chart-container">
        <h3>DRAM ETF Price Path & Trade Entry/Exit Points</h3>
        <div class="chart-wrapper"><canvas id="priceChart"></canvas></div>
      </div>

      <div class="chart-container">
        <h3>Cumulative P&L: Hedge Strategy vs Buy & Hold</h3>
        <div class="chart-wrapper"><canvas id="pnlChart"></canvas></div>
      </div>

      <div class="chart-container">
        <h3>Per-Cycle P&L Breakdown</h3>
        <div class="chart-wrapper" style="height:280px;"><canvas id="cycleChart"></canvas></div>
      </div>

      <!-- Trade Table -->
      <div class="card">
        <h2 style="margin-bottom:10px;">Per-Cycle Trade Detail</h2>
        <div style="overflow-x:auto;max-height:500px;overflow-y:auto;">
          <table class="trade-table" id="tradeTable">
            <thead></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- History -->
    <div class="card">
      <h2>History</h2>
      <div style="overflow-x:auto;">
        <table class="history-table" id="historyTable">
          <thead>
            <tr>
              <th>#</th>
              <th>Time</th>
              <th>Src</th>
              <th>Strike%</th>
              <th>Puts</th>
              <th>Period</th>
              <th>Vol</th>
              <th>RF Rate</th>
              <th>Strat P&L</th>
              <th>Ret%</th>
              <th>Win%</th>
              <th>Cyc</th>
              <th>ITM/OTM</th>
              <th>Premium</th>
              <th>Payoff</th>
              <th>B&H P&L</th>
              <th>Apply</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="historyBody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="loading-overlay" id="loadingOverlay">
  <div style="text-align:center;">
    <div class="spinner"></div>
    <div class="loading-text">Running simulation...</div>
  </div>
</div>

<script>
// ── Slider helpers ──
function updateSlider(sliderId, valId, suffix) {
  const s = document.getElementById(sliderId);
  const v = document.getElementById(valId);
  v.textContent = s.value + suffix;
}

function updateVolSlider() {
  const s = document.getElementById('synthVol');
  const v = document.getElementById('synthVolVal');
  if (parseInt(s.value) === 0) {
    v.textContent = 'Auto';
  } else {
    v.textContent = s.value + '%';
  }
}

function toggleDataSource() {
  const real = document.querySelector('input[name="dataSource"][value="real"]').checked;
  document.getElementById('realDataInfo').style.display = real ? 'block' : 'none';
  document.getElementById('synthParams').style.display = real ? 'none' : 'block';
  // Set default dates
  if (real) {
    document.getElementById('startDate').value = '2026-04-02';
    document.getElementById('synthVol').value = '50';
    document.getElementById('synthVolVal').textContent = '50%';
  } else {
    document.getElementById('synthVol').value = '45';
    document.getElementById('synthVolVal').textContent = '45%';
  }
}

// ── Presets ──
const PRESETS = {
  aggressive:   { strikePct: 5, numPuts: 3, holdingPeriod: '5' },
  balanced:     { strikePct: 3, numPuts: 2, holdingPeriod: '14' },
  conservative: { strikePct: 2, numPuts: 1, holdingPeriod: '21' }
};

function applyPreset(name) {
  const p = PRESETS[name];
  document.getElementById('strikePct').value = p.strikePct;
  document.getElementById('strikePctVal').textContent = p.strikePct + '%';
  document.getElementById('numPuts').value = p.numPuts;
  document.getElementById('holdingPeriod').value = p.holdingPeriod;
  document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
}

// ── Chart instances (destroy before re-create) ──
let priceChart = null, pnlChart = null, cycleChart = null;
let historyCache = [];

function destroyCharts() {
  if (priceChart) { priceChart.destroy(); priceChart = null; }
  if (pnlChart) { pnlChart.destroy(); pnlChart = null; }
  if (cycleChart) { cycleChart.destroy(); cycleChart = null; }
}

// ── Run simulation ──
async function runSimulation() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  document.getElementById('loadingOverlay').classList.add('show');

  const useReal = document.querySelector('input[name="dataSource"][value="real"]').checked;
  const volVal = parseInt(document.getElementById('synthVol').value);
  const payload = {
    strike_pct: parseFloat(document.getElementById('strikePct').value) / 100,
    num_puts: parseInt(document.getElementById('numPuts').value),
    holding_period: parseInt(document.getElementById('holdingPeriod').value),
    risk_free_rate: parseFloat(document.getElementById('riskFreeRate').value) / 100,
    shares_per_lot: parseInt(document.getElementById('sharesPerLot').value),
    num_lots: parseInt(document.getElementById('numLots').value),
    contract_size: parseInt(document.getElementById('contractSize').value),
    start_date: document.getElementById('startDate').value,
    end_date: document.getElementById('endDate').value,
    use_real: useReal,
    vol_override: volVal > 0 ? volVal / 100 : null,
    synth_price: parseFloat(document.getElementById('synthPrice').value),
    synth_vol: parseFloat(document.getElementById('synthVol').value) / 100,
    synth_drift: parseFloat(document.getElementById('synthDrift').value) / 100,
    seed: parseInt(document.getElementById('seed').value),
  };

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.error) {
      alert('Error: ' + data.error);
      return;
    }
    renderResults(data);
    loadHistory();
  } catch(e) {
    alert('Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    document.getElementById('loadingOverlay').classList.remove('show');
  }
}

// ── Render results ──
function renderResults(data) {
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('resultsSection').style.display = 'block';

  const s = data.summary;
  const trades = data.trades;
  const prices = data.price_data;
  const di = data.data_info || {};

  // ── Data source banner ──
  let banner = '';
  if (di.source === 'real') {
    banner = `<div style="background:#e8f5e9;border:1px solid #a5d6a7;border-radius:6px;padding:6px 10px;margin-bottom:8px;font-size:11px;color:#2e7d32;">
      <strong>Real Data:</strong> DRAM ETF | ${di.first_date} to ${di.last_date} | ${di.data_points} trading days |
      $${di.first_price.toFixed(2)} to $${di.last_price.toFixed(2)} |
      Realized Vol: ${(di.realized_vol*100).toFixed(1)}% | BS Vol: ${(di.bs_vol*100).toFixed(1)}%
    </div>`;
  } else {
    banner = `<div style="background:#fff3e0;border:1px solid #ffcc80;border-radius:6px;padding:6px 10px;margin-bottom:8px;font-size:11px;color:#e65100;">
      <strong>Synthetic Data:</strong> GBM model | ${di.first_date} to ${di.last_date} | ${di.data_points} days |
      $${di.first_price.toFixed(2)} to $${di.last_price.toFixed(2)} |
      BS Vol: ${(di.bs_vol*100).toFixed(1)}%
    </div>`;
  }
  // Insert banner at top of resultsSection
  const existingBanner = document.getElementById('dataBanner');
  if (existingBanner) existingBanner.remove();
  const bannerDiv = document.createElement('div');
  bannerDiv.id = 'dataBanner';
  bannerDiv.innerHTML = banner;
  document.getElementById('resultsSection').insertBefore(bannerDiv, document.getElementById('summaryGrid'));

  // ── Summary cards ──
  const pnlCls = s.total_pnl >= 0 ? 'profit' : 'loss';
  const bhCls = s.buy_hold_pnl >= 0 ? 'profit' : 'loss';
  const winCls = s.win_rate_pct >= 50 ? 'profit' : 'neutral';

  document.getElementById('summaryGrid').innerHTML = `
    <div class="metric-card">
      <div class="metric-label">Strategy P&L</div>
      <div class="metric-value ${pnlCls}">${s.total_pnl >= 0 ? '+' : ''}$${s.total_pnl.toLocaleString()}</div>
      <div class="metric-sub">Return: ${s.strategy_return_pct >= 0 ? '+' : ''}${s.strategy_return_pct}% | Annualized: ${s.annualized_return_pct >= 0 ? '+' : ''}${s.annualized_return_pct}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Buy & Hold P&L</div>
      <div class="metric-value ${bhCls}">${s.buy_hold_pnl >= 0 ? '+' : ''}$${s.buy_hold_pnl.toLocaleString()}</div>
      <div class="metric-sub">Return: ${s.buy_hold_return_pct >= 0 ? '+' : ''}${s.buy_hold_return_pct}% | Annualized: ${s.buy_hold_annualized_pct >= 0 ? '+' : ''}${s.buy_hold_annualized_pct}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Win Rate</div>
      <div class="metric-value ${winCls}">${s.win_rate_pct}%</div>
      <div class="metric-sub">${s.total_cycles} cycles | ITM: ${s.itm_cycles} | OTM: ${s.otm_cycles}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Hedge Cost vs Benefit</div>
      <div class="metric-value ${s.net_hedge_benefit >= 0 ? 'profit' : 'loss'}">${s.net_hedge_benefit >= 0 ? '+' : ''}$${s.net_hedge_benefit.toLocaleString()}</div>
      <div class="metric-sub">Premium: $${s.total_put_premium.toLocaleString()} | Payoff: $${s.total_put_payoff.toLocaleString()}</div>
    </div>
  `;

  // ── Income/Cost breakdown ──
  document.getElementById('icSection').innerHTML = `
    <div class="ic-col">
      <h3>Income</h3>
      <div class="ic-row"><span>Put Payoff (ITM)</span><span class="profit">$${s.total_put_payoff.toLocaleString()}</span></div>
      <div class="ic-row"><span>Stock Gains</span><span class="profit">$${Math.round(s.total_stock_pnl > 0 ? s.total_stock_pnl : 0).toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Total Income</span><span class="profit">$${Math.round((s.total_put_payoff + (s.total_stock_pnl > 0 ? s.total_stock_pnl : 0))).toLocaleString()}</span></div>
    </div>
    <div class="ic-col">
      <h3>Cost</h3>
      <div class="ic-row"><span>Put Premium</span><span class="loss">$${s.total_put_premium.toLocaleString()}</span></div>
      <div class="ic-row"><span>Stock Losses</span><span class="loss">$${Math.round(s.total_stock_pnl < 0 ? -s.total_stock_pnl : 0).toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Total Cost</span><span class="loss">$${Math.round((s.total_put_premium + (s.total_stock_pnl < 0 ? -s.total_stock_pnl : 0))).toLocaleString()}</span></div>
    </div>
    <div class="ic-col">
      <h3>Net</h3>
      <div class="ic-row"><span>Strategy P&L</span><span class="${pnlCls}">${s.total_pnl >= 0 ? '+' : ''}$${s.total_pnl.toLocaleString()}</span></div>
      <div class="ic-row"><span>vs Buy & Hold</span><span class="${s.total_pnl > s.buy_hold_pnl ? 'profit' : 'loss'}">${s.total_pnl > s.buy_hold_pnl ? '+' : ''}$${Math.abs(s.total_pnl - s.buy_hold_pnl).toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Initial Capital (stock + puts)</span><span class="neutral">$${s.initial_capital.toLocaleString()}</span></div>
      <div class="ic-row ic-total"><span>Final Capital (Initial + P&L)</span><span class="neutral">$${s.final_capital.toLocaleString()}</span></div>
    </div>
  `;

  // ── Charts ──
  destroyCharts();

  // Chart 1: Price path with trade markers
  const priceLabels = prices.map(p => p.date);
  const priceData = prices.map(p => p.close);

  const entryPoints = trades.map(t => ({ x: t.entry_date, y: t.entry_price }));
  const exitPoints = trades.map(t => ({ x: t.exit_date, y: t.exit_price }));

  priceChart = new Chart(document.getElementById('priceChart'), {
    type: 'line',
    data: {
      labels: priceLabels,
      datasets: [{
        label: 'DRAM ETF Price',
        data: priceData,
        borderColor: '#5c6bc0',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.1,
        yAxisID: 'y',
      }, {
        label: 'Entry (Buy)',
        data: entryPoints,
        borderColor: '#1976d2',
        backgroundColor: '#1976d2',
        showLine: false,
        pointStyle: 'triangle',
        pointRadius: 6,
        yAxisID: 'y',
      }, {
        label: 'Exit (Sell)',
        data: exitPoints,
        borderColor: '#757575',
        backgroundColor: ctx => {
          const t = trades[ctx.dataIndex];
          return t && t.total_pnl > 0 ? '#d32f2f' : '#388e3c'; // Red=profit, Green=loss
        },
        showLine: false,
        pointStyle: 'triangle',
        pointRadius: 6,
        pointRotation: 180,
        yAxisID: 'y',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { maxTicksLimit: 12, font: { size: 10 } } },
        y: { title: { display: true, text: 'Price ($)' } }
      },
      plugins: { tooltip: { mode: 'index', intersect: false } }
    }
  });

  // Chart 2: Cumulative P&L
  let cumPnl = 0;
  const cumPnlData = trades.map(t => { cumPnl += t.total_pnl; return cumPnl; });
  let cumBh = 0;
  const firstPrice = trades.length > 0 ? trades[0].entry_price : 0;
  const cumBhData = trades.map(t => {
    cumBh = (t.exit_price - firstPrice) * t.shares_held;
    return cumBh;
  });
  const cycleLabels = trades.map((t, i) => `C${i}`);

  pnlChart = new Chart(document.getElementById('pnlChart'), {
    type: 'line',
    data: {
      labels: cycleLabels,
      datasets: [{
        label: 'Hedge Strategy P&L',
        data: cumPnlData,
        borderColor: '#d32f2f',
        backgroundColor: 'rgba(211,47,47,0.1)',
        borderWidth: 2,
        tension: 0.2,
        fill: true,
      }, {
        label: 'Buy & Hold P&L',
        data: cumBhData,
        borderColor: '#1976d2',
        borderWidth: 2,
        tension: 0.2,
        borderDash: [5, 3],
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: 'Cycle' } },
        y: { title: { display: true, text: 'Cumulative P&L ($)' } }
      },
      plugins: { tooltip: { mode: 'index', intersect: false } }
    }
  });

  // Chart 3: Per-cycle breakdown
  cycleChart = new Chart(document.getElementById('cycleChart'), {
    type: 'bar',
    data: {
      labels: cycleLabels,
      datasets: [{
        label: 'Stock P&L',
        data: trades.map(t => t.stock_pnl),
        backgroundColor: '#1976d2',
      }, {
        label: 'Put Payoff',
        data: trades.map(t => t.put_payoff),
        backgroundColor: '#d32f2f',
      }, {
        label: 'Put Premium',
        data: trades.map(t => -t.put_cost),
        backgroundColor: '#f57c00',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: 'Cycle' } },
        y: { title: { display: true, text: 'P&L ($)' } }
      },
      plugins: { tooltip: { mode: 'index', intersect: false } }
    }
  });

  // ── Trade table ──
  const thead = document.querySelector('#tradeTable thead');
  const tbody = document.querySelector('#tradeTable tbody');
  thead.innerHTML = `<tr>
    <th>#</th><th>Entry Date</th><th>Entry $</th><th>Exit Date</th><th>Exit $</th>
    <th>Days</th><th>Strike $</th><th>Prem/Contract</th><th>Scenario</th><th>Stock P&L</th><th>Put Payoff</th>
    <th>Premium</th><th>Total P&L</th><th>Return %</th><th>Price Δ%</th>
  </tr>`;
  tbody.innerHTML = trades.map(t => {
    const pnlCls = t.total_pnl > 0 ? 'profit' : 'loss';
    const stockCls = t.stock_pnl > 0 ? 'profit' : 'loss';
    const badge = t.put_expired ? '<span class="badge-otm">OTM</span>' : '<span class="badge-itm">ITM</span>';
    return `<tr>
      <td>${t.cycle_id}</td>
      <td>${t.entry_date}</td>
      <td>$${t.entry_price.toFixed(2)}</td>
      <td>${t.exit_date}</td>
      <td>$${t.exit_price.toFixed(2)}</td>
      <td>${t.calendar_days}d</td>
      <td>$${t.strike_price.toFixed(2)}</td>
      <td>$${t.premium_per_contract.toFixed(2)}</td>
      <td>${badge}</td>
      <td class="${stockCls}">${t.stock_pnl >= 0 ? '+' : ''}$${t.stock_pnl.toFixed(2)}</td>
      <td class="profit">${t.put_payoff >= 0 ? '+' : ''}$${t.put_payoff.toFixed(2)}</td>
      <td class="loss">-$${t.put_cost.toFixed(2)}</td>
      <td class="${pnlCls}" style="font-weight:700;">${t.total_pnl >= 0 ? '+' : ''}$${t.total_pnl.toFixed(2)}</td>
      <td class="${pnlCls}">${t.return_pct >= 0 ? '+' : ''}${t.return_pct.toFixed(2)}%</td>
      <td class="${t.price_change_pct > 0 ? 'profit' : 'loss'}">${t.price_change_pct >= 0 ? '+' : ''}${t.price_change_pct.toFixed(2)}%</td>
    </tr>`;
  }).join('');
}

// ── History ──
async function loadHistory() {
  const resp = await fetch('/api/history');
  const history = await resp.json();
  historyCache = history;
  const tbody = document.getElementById('historyBody');
  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="18" style="text-align:center;color:#aaa;padding:20px;">No runs yet</td></tr>';
    return;
  }
  tbody.innerHTML = history.map(h => {
    const pnlCls = h.total_pnl >= 0 ? 'profit' : 'loss';
    const retCls = h.strategy_return_pct >= 0 ? 'profit' : 'loss';
    const bhCls = h.buy_hold_pnl >= 0 ? 'profit' : 'loss';
    const winCls = h.win_rate_pct >= 50 ? 'profit' : 'neutral';
    const strikePct = (h.strike_pct * 100).toFixed(1);
    const volPct = (h.params && h.params.vol_override != null && h.params.vol_override > 0) ? (h.params.vol_override * 100).toFixed(0) : (h.synth_vol * 100).toFixed(0);
    const rfPct = (h.risk_free_rate * 100).toFixed(1);
    const src = h.params && h.params.use_real === false ? 'Synth' : 'Real';
    const srcCls = src === 'Real' ? 'profit' : 'neutral';
    const hpLabel = h.holding_period == 5 ? '1wk' : h.holding_period == 14 ? '2wk' : h.holding_period == 21 ? '3wk' : h.holding_period + 'd';
    return `<tr>
      <td>${h.id}</td>
      <td>${h.timestamp}</td>
      <td class="${srcCls}" style="font-weight:600;">${src}</td>
      <td>${strikePct}%</td>
      <td>${h.num_puts}</td>
      <td>${hpLabel}</td>
      <td>${volPct}%</td>
      <td>${rfPct}%</td>
      <td class="${pnlCls}" style="font-weight:700;">${h.total_pnl >= 0 ? '+' : ''}$${Math.round(h.total_pnl).toLocaleString()}</td>
      <td class="${retCls}">${h.strategy_return_pct >= 0 ? '+' : ''}${h.strategy_return_pct}%</td>
      <td class="${winCls}">${h.win_rate_pct}%</td>
      <td>${h.total_cycles}</td>
      <td>${h.itm_cycles}/${h.otm_cycles}</td>
      <td>$${Math.round(h.total_put_premium).toLocaleString()}</td>
      <td>$${Math.round(h.total_put_payoff).toLocaleString()}</td>
      <td class="${bhCls}">${h.buy_hold_pnl >= 0 ? '+' : ''}$${Math.round(h.buy_hold_pnl).toLocaleString()}</td>
      <td><span class="apply-btn" onclick="event.stopPropagation();applyHistory(${h.id})">Apply</span></td>
      <td><span class="del-btn" onclick="event.stopPropagation();deleteRun(${h.id})">x</span></td>
    </tr>`;
  }).join('');
}

function applyHistory(id) {
  const h = historyCache.find(r => r.id === id);
  if (!h) return;
  // Apply all parameters from the saved run
  const p = h.params;
  document.getElementById('strikePct').value = (p.strike_pct * 100).toFixed(1);
  document.getElementById('strikePctVal').textContent = (p.strike_pct * 100).toFixed(1) + '%';
  document.getElementById('numPuts').value = p.num_puts;
  document.getElementById('holdingPeriod').value = p.holding_period;
  document.getElementById('sharesPerLot').value = p.shares_per_lot;
  document.getElementById('numLots').value = p.num_lots;
  document.getElementById('contractSize').value = p.contract_size;
  document.getElementById('startDate').value = p.start_date;
  document.getElementById('endDate').value = p.end_date;
  document.getElementById('synthPrice').value = p.synth_price;
  // Data source
  const useReal = p.use_real !== false;
  document.querySelector(`input[name="dataSource"][value="real"]`).checked = useReal;
  document.querySelector(`input[name="dataSource"][value="synthetic"]`).checked = !useReal;
  toggleDataSource();
  if (!useReal) {
    document.getElementById('synthVol').value = (p.synth_vol * 100).toFixed(0);
    document.getElementById('synthVolVal').textContent = (p.synth_vol * 100).toFixed(0) + '%';
  } else if (p.vol_override != null && p.vol_override > 0) {
    document.getElementById('synthVol').value = (p.vol_override * 100).toFixed(0);
    document.getElementById('synthVolVal').textContent = (p.vol_override * 100).toFixed(0) + '%';
  } else {
    document.getElementById('synthVol').value = '0';
    document.getElementById('synthVolVal').textContent = 'Auto';
  }
  document.getElementById('riskFreeRate').value = (p.risk_free_rate * 100).toFixed(1);
  document.getElementById('riskFreeRateVal').textContent = (p.risk_free_rate * 100).toFixed(1) + '%';
  document.getElementById('synthDrift').value = (p.synth_drift * 100).toFixed(0);
  document.getElementById('synthDriftVal').textContent = (p.synth_drift * 100).toFixed(0) + '%';
  document.getElementById('seed').value = p.seed;
  // Update preset highlight - clear all since applied params may not match any preset
  document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
  // Scroll to top and auto-run
  document.querySelector('.left-panel').scrollIntoView({behavior:'smooth', block:'start'});
  runSimulation();
}

async function deleteRun(id) {
  if (!confirm('Delete run #' + id + '?')) return;
  await fetch(`/api/history/${id}`, {method: 'DELETE'});
  loadHistory();
}

// ── Init ──
// Auto-run on page load + load history
window.addEventListener('load', () => {
  loadHistory();
  runSimulation();
});
</script>

</body>
</html>
'''


if __name__ == '__main__':
    init_db()
    print("=" * 50)
    print("  DRAM Hedge Strategy Simulator")
    print("  Open http://localhost:5567")
    print("  Database:", DB_PATH)
    print("=" * 50)
    app.run(host='0.0.0.0', port=5567, debug=False)
