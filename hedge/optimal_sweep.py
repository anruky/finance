#!/usr/bin/env python3
"""
Comprehensive parameter sweep on REAL DRAM data to find optimal hedge parameters.
"""
import json
import urllib.request
import itertools

API = "http://localhost:5567/api/run"

def run_sim(strike_pct, num_puts=2, holding_period=12, risk_free_rate=0.045,
            synth_vol=0.45, vol_override=None, data_source="real",
            num_lots=1, shares_per_lot=100, contract_size=100,
            initial_capital=100000):
    payload = {
        "strike_pct": strike_pct,
        "num_puts": num_puts,
        "holding_period": holding_period,
        "risk_free_rate": risk_free_rate,
        "synth_vol": synth_vol,
        "num_lots": num_lots,
        "shares_per_lot": shares_per_lot,
        "contract_size": contract_size,
        "initial_capital": initial_capital,
        "data_source": data_source,
    }
    if vol_override is not None:
        payload["vol_override"] = vol_override
    data = json.dumps(payload).encode()
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def extract(r):
    s = r.get("summary", {})
    return {
        "pnl": s.get("total_pnl", 0),
        "bh": s.get("buy_hold_pnl", 0),
        "ret_pct": s.get("strategy_return_pct", 0),
        "bh_ret_pct": s.get("buy_hold_return_pct", 0),
        "premium": s.get("total_put_premium", 0),
        "payoff": s.get("total_put_payoff", 0),
        "net_hedge": s.get("net_hedge_benefit", 0),
        "itm": s.get("itm_cycles", 0),
        "cycles": s.get("total_cycles", 0),
        "win": s.get("win_rate_pct", 0),
        "hedge_cost_pct": s.get("hedge_cost_pct", 0),
    }

print("=" * 100)
print("  COMPREHENSIVE PARAMETER SWEEP ON REAL DRAM DATA")
print("  (86 trading days, 2026-04-02 to 2026-08-05, IPO $27.76 -> $53.74)")
print("=" * 100)

# First, get the realized vol from baseline run
baseline = run_sim(strike_pct=0.03, data_source="real")
di = baseline.get("data_info", {})
print(f"\n  Realized Vol: {di.get('realized_vol', 'N/A')}")
print(f"  BS Vol (auto): {di.get('bs_vol', 'N/A')}")
print(f"  Data Source: {di.get('source', 'N/A')}")

# ============================================================
# 1. Strike % sweep (baseline: 2 puts, 12 days, auto vol)
# ============================================================
print("\n" + "=" * 100)
print("  1. STRIKE % SWEEP (2 puts, 12 days, auto vol)")
print("=" * 100)
print(f"{'Strike%':>8} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'HedgeCost%':>11} {'ITM':>6} {'Win%':>6}")
print("-" * 100)

strike_results = []
for sp in [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]:
    r = run_sim(strike_pct=sp, data_source="real")
    e = extract(r)
    strike_results.append((sp, e))
    print(f"{sp*100:>7.0f}% ${e['pnl']:>9,.0f} {e['ret_pct']:>+7.2f}% ${e['bh']:>9,.0f} ${e['premium']:>9,.0f} ${e['payoff']:>9,.0f} ${e['net_hedge']:>9,.0f} {e['hedge_cost_pct']:>10.1f}% {e['itm']:>3}/{e['cycles']:<2} {e['win']:>5.0f}%")

# ============================================================
# 2. Put count sweep (3% strike, 12 days, auto vol)
# ============================================================
print("\n" + "=" * 100)
print("  2. PUT COUNT SWEEP (3% strike, 12 days, auto vol)")
print("=" * 100)
print(f"{'#Puts':>6} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'HedgeCost%':>11} {'ITM':>6} {'Win%':>6}")
print("-" * 100)

put_results = []
for np_ in [0, 1, 2, 3, 4]:
    r = run_sim(strike_pct=0.03, num_puts=np_, data_source="real")
    e = extract(r)
    put_results.append((np_, e))
    print(f"{np_:>5} ${e['pnl']:>9,.0f} {e['ret_pct']:>+7.2f}% ${e['bh']:>9,.0f} ${e['premium']:>9,.0f} ${e['payoff']:>9,.0f} ${e['net_hedge']:>9,.0f} {e['hedge_cost_pct']:>10.1f}% {e['itm']:>3}/{e['cycles']:<2} {e['win']:>5.0f}%")

# ============================================================
# 3. Holding period sweep (3% strike, 2 puts, auto vol)
# ============================================================
print("\n" + "=" * 100)
print("  3. HOLDING PERIOD SWEEP (3% strike, 2 puts, auto vol)")
print("=" * 100)
print(f"{'Days':>6} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'HedgeCost%':>11} {'ITM':>6} {'Win%':>6}")
print("-" * 100)

period_results = []
for pd in [5, 8, 10, 12, 15, 20]:
    r = run_sim(strike_pct=0.03, num_puts=2, holding_period=pd, data_source="real")
    e = extract(r)
    period_results.append((pd, e))
    print(f"{pd:>5} ${e['pnl']:>9,.0f} {e['ret_pct']:>+7.2f}% ${e['bh']:>9,.0f} ${e['premium']:>9,.0f} ${e['payoff']:>9,.0f} ${e['net_hedge']:>9,.0f} {e['hedge_cost_pct']:>10.1f}% {e['itm']:>3}/{e['cycles']:<2} {e['win']:>5.0f}%")

# ============================================================
# 4. Vol override sweep (3% strike, 2 puts, 12 days)
# ============================================================
print("\n" + "=" * 100)
print("  4. VOL OVERRIDE SWEEP (3% strike, 2 puts, 12 days)")
print("  (Auto vol = realized vol from real data; override adjusts BS pricing input)")
print("=" * 100)
print(f"{'Vol':>6} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'Premium':>10} {'Payoff':>10} {'NetHedge':>10} {'HedgeCost%':>11} {'ITM':>6} {'Win%':>6}")
print("-" * 100)

vol_results = []
for v in [None, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]:
    r = run_sim(strike_pct=0.03, num_puts=2, holding_period=12, vol_override=v, data_source="real")
    e = extract(r)
    label = "auto" if v is None else f"{v*100:.0f}%"
    vol_results.append((v, e))
    print(f"{label:>5} ${e['pnl']:>9,.0f} {e['ret_pct']:>+7.2f}% ${e['bh']:>9,.0f} ${e['premium']:>9,.0f} ${e['payoff']:>9,.0f} ${e['net_hedge']:>9,.0f} {e['hedge_cost_pct']:>10.1f}% {e['itm']:>3}/{e['cycles']:<2} {e['win']:>5.0f}%")

# ============================================================
# 5. Full grid sweep: strike x puts x period x vol_override
# ============================================================
print("\n" + "=" * 100)
print("  5. FULL GRID SWEEP")
print("=" * 100)

all_results = []
strikes = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10]
puts_list = [0, 1, 2, 3]
periods = [5, 8, 10, 12, 15, 20]
vols = [None, 0.50, 0.60, 0.70, 0.80]

total_combos = len(strikes) * len(puts_list) * len(periods) * len(vols)
print(f"  Testing {total_combos} combinations...\n")

for sp in strikes:
    for np_ in puts_list:
        for pd in periods:
            for v in vols:
                r = run_sim(strike_pct=sp, num_puts=np_, holding_period=pd, vol_override=v, data_source="real")
                e = extract(r)
                vs_bh = e["pnl"] - e["bh"]
                all_results.append({
                    "strike_pct": sp, "num_puts": np_, "holding_period": pd,
                    "vol_override": v, **e, "vs_bh": vs_bh
                })

print(f"  Total combinations tested: {len(all_results)}")

# ============================================================
# 6. Rankings
# ============================================================
print("\n" + "=" * 100)
print("  TOP 10 BY TOTAL P&L")
print("=" * 100)
print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'Vol':>5} {'P&L':>10} {'Return%':>8} {'B&H':>10} {'vsB&H':>10} {'NetHedge':>10} {'Win%':>6} {'ITM':>6}")
print("-" * 100)

sorted_pnl = sorted(all_results, key=lambda x: x["pnl"], reverse=True)
for i, r in enumerate(sorted_pnl[:10]):
    vol_str = "auto" if r["vol_override"] is None else f"{r['vol_override']*100:.0f}%"
    print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['holding_period']:>5} {vol_str:>5} ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% ${r['bh']:>9,.0f} ${r['vs_bh']:>+9,.0f} ${r['net_hedge']:>9,.0f} {r['win']:>5.0f}% {r['itm']:>3}/{r['cycles']}")

print("\n" + "=" * 100)
print("  TOP 10 BY OUTPERFORMANCE vs BUY & HOLD")
print("=" * 100)
print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'Vol':>5} {'P&L':>10} {'B&H':>10} {'vsB&H':>10} {'NetHedge':>10} {'Win%':>6} {'HedgeCost%':>11}")
print("-" * 100)

sorted_vs = sorted(all_results, key=lambda x: x["vs_bh"], reverse=True)
for i, r in enumerate(sorted_vs[:10]):
    vol_str = "auto" if r["vol_override"] is None else f"{r['vol_override']*100:.0f}%"
    print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['holding_period']:>5} {vol_str:>5} ${r['pnl']:>9,.0f} ${r['bh']:>9,.0f} ${r['vs_bh']:>+9,.0f} ${r['net_hedge']:>9,.0f} {r['win']:>5.0f}% {r['hedge_cost_pct']:>10.1f}%")

print("\n" + "=" * 100)
print("  TOP 10 BY WIN RATE (with P&L > 0)")
print("=" * 100)
profitable = [r for r in all_results if r["pnl"] > 0]
sorted_win = sorted(profitable, key=lambda x: x["win"], reverse=True)
print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'Vol':>5} {'P&L':>10} {'Return%':>8} {'Win%':>6} {'vsB&H':>10} {'HedgeCost%':>11}")
print("-" * 100)
for i, r in enumerate(sorted_win[:10]):
    vol_str = "auto" if r["vol_override"] is None else f"{r['vol_override']*100:.0f}%"
    print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['holding_period']:>5} {vol_str:>5} ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% {r['win']:>5.0f}% ${r['vs_bh']:>+9,.0f} {r['hedge_cost_pct']:>10.1f}%")

# ============================================================
# 7. Best balanced (P&L > 0 and Win > 40%)
# ============================================================
print("\n" + "=" * 100)
print("  BEST BALANCED (P&L > 0, sorted by P&L + Win% composite)")
print("=" * 100)
balanced = [r for r in all_results if r["pnl"] > 0 and r["win"] >= 40]
balanced.sort(key=lambda x: x["pnl"] * (1 + x["win"]/100), reverse=True)
print(f"{'#':>3} {'Strike%':>8} {'#Puts':>5} {'Days':>5} {'Vol':>5} {'P&L':>10} {'Return%':>8} {'Win%':>6} {'vsB&H':>10} {'HedgeCost%':>11} {'NetHedge':>10}")
print("-" * 100)
for i, r in enumerate(balanced[:10]):
    vol_str = "auto" if r["vol_override"] is None else f"{r['vol_override']*100:.0f}%"
    print(f"{i+1:>3} {r['strike_pct']*100:>7.0f}% {r['num_puts']:>5} {r['holding_period']:>5} {vol_str:>5} ${r['pnl']:>9,.0f} {r['ret_pct']:>+7.2f}% {r['win']:>5.0f}% ${r['vs_bh']:>+9,.0f} {r['hedge_cost_pct']:>10.1f}% ${r['net_hedge']:>9,.0f}")

if not balanced:
    print("  (No combinations met both P&L > 0 and Win >= 40%)")
    # Show best profitable regardless of win rate
    print("\n  Best profitable regardless of win rate:")
    profitable.sort(key=lambda x: x["pnl"], reverse=True)
    for i, r in enumerate(profitable[:10]):
        vol_str = "auto" if r["vol_override"] is None else f"{r['vol_override']*100:.0f}%"
        print(f"  {i+1}. Strike={r['strike_pct']*100:.0f}% Puts={r['num_puts']} Days={r['holding_period']} Vol={vol_str} | P&L=${r['pnl']:,.0f} Ret={r['ret_pct']:+.2f}% Win={r['win']:.0f}% vsB&H=${r['vs_bh']:+,.0f}")

# Save best result
print("\n" + "=" * 100)
print("  RECOMMENDED OPTIMAL PARAMETERS")
print("=" * 100)
if sorted_pnl:
    best = sorted_pnl[0]
    vol_str = "auto (use realized vol)" if best["vol_override"] is None else f"{best['vol_override']*100:.0f}%"
    print(f"""
  ┌─────────────────────────────────────────────────────────────┐
  │  Strike %:        {best['strike_pct']*100:.0f}% OTM
  │  Put Contracts:   {best['num_puts']}
  │  Holding Period:  {best['holding_period']} days
  │  Vol Override:    {vol_str}
  │  Risk-free Rate:  4.5%
  ├─────────────────────────────────────────────────────────────┤
  │  Total P&L:       ${best['pnl']:,.0f}
  │  Return:          {best['ret_pct']:+.2f}%
  │  Buy & Hold P&L:  ${best['bh']:,.0f}
  │  vs Buy & Hold:   ${best['vs_bh']:+,.0f}
  │  Win Rate:        {best['win']:.0f}%
  │  Hedge Cost:      {best['hedge_cost_pct']:.1f}% of capital
  │  Net Hedge:       ${best['net_hedge']:,.0f}
  │  ITM Cycles:     {best['itm']}/{best['cycles']}
  └─────────────────────────────────────────────────────────────┘
""")

print("\n✅ Comprehensive sweep complete.")
