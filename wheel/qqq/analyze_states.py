#!/usr/bin/env python3
"""Analyze which wheel states (A/B/C/D/E) beat Buy & Hold."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_local_backtest as m
from collections import defaultdict

r = m.run('QQQ', m.make_targets(50, 6, 15, 15), options_file='QQQ_options_2wk.json')

state_cycles = defaultdict(list)
for c in r['cycle_list']:
    portfolio_before = c['value'] - c['pnl']
    sret = c['pnl'] / portfolio_before * 100 if portfolio_before else 0
    bret = (c['exp_px'] - c['spot']) / c['spot'] * 100
    state_cycles[c['state']].append((sret, bret, c['pnl']))

state_desc = {
    'A': '两者均到期作废（低波动）',
    'B': 'call被行权（大涨）',
    'C': 'put被行权·先涨后崩（剧烈震荡下行）',
    'D': 'Action1后均作废（涨后回调）',
    'E': 'put被行权（大跌）',
}

print('状态  含义                        周期数   策略均收益   B&H均收益   跑赢次数   累计盈亏   结论')
print('-' * 96)
for st in ['A', 'B', 'C', 'D', 'E']:
    cs = state_cycles.get(st, [])
    if not cs:
        print(f'{st:<4} (本期未出现)')
        continue
    n = len(cs)
    avg_s = sum(x[0] for x in cs) / n
    avg_b = sum(x[1] for x in cs) / n
    beat = sum(1 for x in cs if x[0] > x[1])
    tot_pnl = sum(x[2] for x in cs)
    verdict = '★跑赢B&H' if avg_s > avg_b else '跑输B&H'
    print(f"{st:<4} {state_desc[st]:<26} {n:>4}  {avg_s:>8.2f}%  {avg_b:>8.2f}%  {beat:>4}/{n:<3}  ${tot_pnl:>8,.0f}  {verdict}")

print()
print('注：策略周期收益率 = 周期盈亏 / 周期初组合价值；B&H = 同期股票涨跌幅。')
print('C 状态在本期 2 周策略下未触发。')
