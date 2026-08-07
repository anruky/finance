#!/usr/bin/env python3
"""
Parameter sensitivity analysis for DRAM hedge strategy.
Tests different strike %, put counts, and holding periods,
then generates a comparison report.
"""

import json
import urllib.request

API = "http://localhost:5567/api/run"

def run_sim(strike_pct, num_puts=2, holding_period=12, risk_free_rate=0.045,
            synth_vol=0.45, num_lots=1, shares_per_lot=100, contract_size=100,
            initial_capital=100000, synth_price=55, synth_drift=0.15, seed=42,
            start_date="2026-01-05", end_date="2026-08-05"):
    payload = json.dumps({
        "strike_pct": strike_pct,
        "num_puts": num_puts,
        "holding_period": holding_period,
        "risk_free_rate": risk_free_rate,
        "synth_vol": synth_vol,
        "num_lots": num_lots,
        "shares_per_lot": shares_per_lot,
        "contract_size": contract_size,
        "initial_capital": initial_capital,
        "synth_price": synth_price,
        "synth_drift": synth_drift,
        "seed": seed,
        "start_date": start_date,
        "end_date": end_date,
    }).encode()
    req = urllib.request.Request(API, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fmt(s):
    """Format summary into compact string."""
    return {
        "pnl": s["total_pnl"],
        "bh": s["buy_hold_pnl"],
        "premium": s["total_put_premium"],
        "payoff": s["total_put_payoff"],
        "itm": s["itm_cycles"],
        "cycles": s["total_cycles"],
        "win": s["win_rate_pct"],
        "net_hedge": s["net_hedge_benefit"],
        "ret_pct": s["strategy_return_pct"],
        "bh_ret_pct": s["buy_hold_return_pct"],
        "avg_prem": s["total_put_premium"] / s["total_cycles"] if s["total_cycles"] else 0,
    }


# ============================================================
# 1. Strike % sweep
# ============================================================
print("=" * 80)
print("  STRIKE % SWEEP (num_puts=2, period=12, vol=45%, r=4.5%)")
print("=" * 80)
print(f"{'Strike%':>8} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'ITM':>6} {'Win%':>6} {'AvgPrem':>8}")
print("-" * 80)

strike_results = []
for sp in [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]:
    d = run_sim(strike_pct=sp)
    r = fmt(d["summary"])
    strike_results.append((sp, r))
    print(f"{sp*100:>7.0f}% ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% ${r['bh']:>9,.0f} ${r['premium']:>9,.0f} ${r['payoff']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['itm']:>3}/{r['cycles']:<2} {r['win']:>5.0f}% ${r['avg_prem']:>7,.0f}")

# ============================================================
# 2. Put count sweep (at best strike %)
# ============================================================
print()
print("=" * 80)
print("  PUT COUNT SWEEP (strike=3%, period=12, vol=45%, r=4.5%)")
print("=" * 80)
print(f"{'#Puts':>6} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'ITM':>6} {'Win%':>6} {'AvgPrem':>8}")
print("-" * 80)

put_results = []
for np_ in [1, 2, 3, 4, 5]:
    d = run_sim(strike_pct=0.03, num_puts=np_)
    r = fmt(d["summary"])
    put_results.append((np_, r))
    print(f"{np_:>5} ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% ${r['bh']:>9,.0f} ${r['premium']:>9,.0f} ${r['payoff']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['itm']:>3}/{r['cycles']:<2} {r['win']:>5.0f}% ${r['avg_prem']:>7,.0f}")

# ============================================================
# 3. Holding period sweep (at 3% strike)
# ============================================================
print()
print("=" * 80)
print("  HOLDING PERIOD SWEEP (strike=3%, num_puts=2, vol=45%, r=4.5%)")
print("=" * 80)
print(f"{'Days':>6} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'ITM':>6} {'Win%':>6} {'AvgPrem':>8}")
print("-" * 80)

period_results = []
for pd in [5, 8, 10, 12, 15, 20, 25]:
    d = run_sim(strike_pct=0.03, num_puts=2, holding_period=pd)
    r = fmt(d["summary"])
    period_results.append((pd, r))
    print(f"{pd:>5} ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% ${r['bh']:>9,.0f} ${r['premium']:>9,.0f} ${r['payoff']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['itm']:>3}/{r['cycles']:<2} {r['win']:>5.0f}% ${r['avg_prem']:>7,.0f}")

# ============================================================
# 4. Combined scenarios
# ============================================================
print()
print("=" * 80)
print("  COMBINED SCENARIOS")
print("=" * 80)
print(f"{'Scenario':>30} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'vs B&H':>10} {'ITM':>6}")
print("-" * 80)

scenarios = [
    ("Baseline",          0.03, 2, 12),
    ("Wider Strike 5%",   0.05, 2, 12),
    ("Wider Strike 7%",   0.07, 2, 12),
    ("More Puts (3)",     0.03, 3, 12),
    ("More Puts (4)",     0.03, 4, 12),
    ("Shorter Period 5d", 0.03, 2, 5),
    ("Longer Period 20d", 0.03, 2, 20),
    ("5%+3puts+5d",       0.05, 3, 5),
    ("5%+2puts+20d",      0.05, 2, 20),
    ("7%+3puts+12d",      0.07, 3, 12),
    ("5%+3puts+12d",      0.05, 3, 12),
    ("2%+2puts+12d",      0.02, 2, 12),
    ("10%+2puts+12d",     0.10, 2, 12),
    ("5%+4puts+12d",      0.05, 4, 12),
    ("15%+1put+12d",      0.15, 1, 12),
]

combo_results = []
for name, sp, np_, pd in scenarios:
    d = run_sim(strike_pct=sp, num_puts=np_, holding_period=pd)
    r = fmt(d["summary"])
    vs_bh = r["pnl"] - r["bh"]
    combo_results.append((name, sp, np_, pd, r, vs_bh))
    print(f"{name:>30} {sp*100:>7.0f}% {np_:>5} {pd:>5} ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% ${r['bh']:>9,.0f} {vs_bh:>+9,.0f} {r['itm']:>3}/{r['cycles']}")

# ============================================================
# 5. Volatility sweep (market regime analysis)
# ============================================================
print()
print("=" * 80)
print("  VOLATILITY REGIME SWEEP (strike=3%, num_puts=2, period=12, r=4.5%)")
print("=" * 80)
print(f"{'Vol':>6} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'ITM':>6} {'Win%':>6} {'AvgPrem':>8}")
print("-" * 80)

vol_results = []
for v in [0.20, 0.30, 0.40, 0.45, 0.50, 0.60, 0.80, 1.00]:
    d = run_sim(strike_pct=0.03, num_puts=2, holding_period=12, synth_vol=v)
    r = fmt(d["summary"])
    vol_results.append((v, r))
    print(f"{v*100:>5.0f}% ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% ${r['bh']:>9,.0f} ${r['premium']:>9,.0f} ${r['payoff']:>9,.0f} ${r['net_hedge']:>9,.0f} {r['itm']:>3}/{r['cycles']:<2} {r['win']:>5.0f}% ${r['avg_prem']:>7,.0f}")

# ============================================================
# 6. Find optimal combos
# ============================================================
print()
print("=" * 80)
print("  TOP 5 BEST STRATEGIES (by P&L)")
print("=" * 80)
sorted_combos = sorted(combo_results, key=lambda x: x[4]["pnl"], reverse=True)
for i, (name, sp, np_, pd, r, vs_bh) in enumerate(sorted_combos[:5]):
    print(f"  #{i+1}: {name:>30} | P&L=${r['pnl']:,.0f} | Return={r['ret_pct']:+.2f}% | vs B&H={vs_bh:+,.0f} | ITM={r['itm']}/{r['cycles']} | Premium=${r['premium']:,.0f}")

print()
print("=" * 80)
print("  TOP 5 BEST vs BUY & HOLD (by outperformance)")
print("=" * 80)
sorted_vs = sorted(combo_results, key=lambda x: x[5], reverse=True)
for i, (name, sp, np_, pd, r, vs_bh) in enumerate(sorted_vs[:5]):
    print(f"  #{i+1}: {name:>30} | P&L=${r['pnl']:,.0f} | vs B&H={vs_bh:+,.0f} | Net Hedge=${r['net_hedge']:,.0f} | Win={r['win']:.0f}%")

print()
print("=" * 80)
print("  TOP 5 BY WIN RATE")
print("=" * 80)
sorted_win = sorted(combo_results, key=lambda x: x[4]["win"], reverse=True)
for i, (name, sp, np_, pd, r, vs_bh) in enumerate(sorted_win[:5]):
    print(f"  #{i+1}: {name:>30} | Win={r['win']:.0f}% | P&L=${r['pnl']:,.0f} | ITM={r['itm']}/{r['cycles']}")

print("\n✅ Analysis complete.")
