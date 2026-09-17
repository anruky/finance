"""Capital denominators and whole-pair reinvestment; no external funding."""
from datetime import date
from dataclasses import replace
from backtest_straddle import run_straddle


def annualize(r,start):
    days=(date.fromisoformat(r['curve'][-1]['date'])-date.fromisoformat(start)).days
    r.update(funding_date=start,calendar_days=days,additional_deposits=0,
        ending_equity=r['curve'][-1]['equity'],annualized_pct=100*((r['curve'][-1]['equity']/r['initial'])**(365/days)-1) if days else None)
    return r


def scenarios(data,calls,cfg,legacy):
    unit=run_straddle(data,calls,cfg,initial_capital=legacy['trades'][0]['cost'])
    # Initial premium is a transaction-cost capital illustration; not an optimized future minimum.
    unit['name']='实际首轮保费本金／固定1组'
    annualize(unit,unit['trades'][0]['entry_date'])
    full=run_straddle(data,calls,cfg,all_in=True);full['name']='$22,852.50／每轮尽量满仓'
    annualize(full,full['curve'][0]['date'])
    sensitivity=[]
    for slip in (0,.02,.05):
        r=run_straddle(data,calls,replace(cfg,slip=slip),all_in=True)
        sensitivity.append(dict(slip=slip,pnl=r['pnl'],return_pct=r['return_pct'],mdd_pct=r['mdd_pct']))
    return dict(unit=unit,full=full,full_slippage=sensitivity)


def render(cap,legacy,table,section,money):
    unit,full=cap['unit'],cap['full']
    rows=[]
    for r in (unit,full,legacy):
        rows.append([r['name'],f"${r['initial']:,.2f}",f"${r['curve'][-1]['equity']:,.2f}",money(r['pnl']),f"{r['return_pct']:.2f}%",f"{r['mdd_pct']:.2f}%",f"{r['annualized_pct']:,.2f}%" if 'annualized_pct' in r else '旧现金基准'])
    body=f'''<div class="callout-gold"><strong>已按期权实际本金修正：固定一组的本金为 ${unit['initial']:,.2f}，本期收益率 {unit['return_pct']:.2f}%。</strong><br>同样用 $22,852.50 每轮尽量满仓，结果为 {full['return_pct']:.2f}%，最大回撤 {full['mdd_pct']:.2f}%。两种仓位管理不能直接按倍数换算。</div>'''
    body+=table(['资金／仓位方案','初始投入','期末净资产','本期盈亏','本期收益率','最大回撤','年化外推'],rows)
    body+=f'''<p>固定一组：{unit['funding_date']} 首次支付保费与开仓费用，此后保留利润、每轮仍只买1组；截至09-11共 {unit['calendar_days']} 个自然日，无追加资金、无借款、无资金不足跳单。因此本期利润除以首笔实际投入成立。若未来资金不足，模型跳过交易，不默认为追加本金。</p>
<p>年化 = (期末净资产 / 初始投入)<sup>365 / 自然日数</sup> − 1。无中途外部现金流时，与首笔投入和期末净资产两笔现金流的XIRR一致；满仓账户从07-13开始计 {full['calendar_days']} 天。<strong>样本不足一年，年化仅为数学外推，并非可持续年收益预测。</strong>期末含未平仓期权市值；本金不包含股票成本，累计滚动保费也不当作初始本金。<a href="https://support.microsoft.com/zh-cn/excel/functions/xirr-function">XIRR日期及365日口径参考</a>。</p>
<p>一组 = 1张Call＋1张Put，每张乘数100。首轮单组含费 ${unit['initial']:,.2f}，$22,852.50可买 {full['trades'][0]['pairs']} 组，即 {full['trades'][0]['pairs']*2} 张合约；本期最大仓位 {max(t['pairs'] for t in full['trades'])} 组。每次开仓按当时现金÷模拟单组含费成交价向下取整，剩余零钱留现金；退出收入到账后重新计算，不借款、不补资。若买不起一组则继续等待有效信号。涨跌触发和合约筛选仍只用前日信息。</p>
<p class="note">张数是组合预算成交近似：假设成交时可按可用预算调整数量，日线成交末价并非提前已知的限价。所有张数采用相同2%滑点，未验证盘口深度；满仓结果是条件模拟，不能视为这些张数都能实盘成交。每日现金最低 ${full['cash_min']:,.2f}，资金不足跳过 {full['skipped']['cash']} 次。</p>'''
    out=section('更新：实际期权本金与满仓滚动',body,'capital')
    # Log-free common scale, normalized to each scenario's own funding capital.
    rr=[unit,full,legacy];colors=['#f5c344','#ff6b81','#4da3ff'];vals=[[100*x['equity']/r['initial'] for x in r['curve']] for r in rr]
    hi=max(max(v) for v in vals)*1.05;svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 320" role="img" aria-label="各自本金归一化的资金曲线"><title>固定一组、满仓、旧现金基准资金曲线</title>']
    for j in range(6):
        v=hi*j/5;y=270-v/hi*245
        svg.append(f'<line x1="60" x2="970" y1="{y:.2f}" y2="{y:.2f}" stroke="#303645"/><text x="50" y="{y+4:.2f}" fill="#aaa" text-anchor="end" font-size="12">{v:.0f}</text>')
    for v,col in zip(vals,colors):
        pts=' '.join(f'{60+i*910/(len(v)-1):.2f},{270-x/hi*245:.2f}' for i,x in enumerate(v))
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5"/>')
    for i in (0,10,20,30,43):
        svg.append(f'<text x="{60+i*910/43:.2f}" y="300" text-anchor="middle" fill="#aaa" font-size="12">{unit["curve"][i]["date"][5:]}</text>')
    out+=section('不同仓位的净值与风险',''.join(svg)+'</svg><p>金：实际保费本金固定1组；红：$22,852.50满仓滚动；蓝：旧版$22,852.50只买1组。各自本金归一化=100；单组首笔资金在07-15到位，前两天绘为100仅作对齐，不计入年化天数。</p><p>满仓在盈利后扩大仓位，08-14开仓45组，该轮亏损约$54,455；下一轮减至5组，随后降至1组。固定单组保留盈利作现金，承受的风险占净资产比例更低。最大回撤按每日含期权市值的账户净值历史高点计算；图中曲线为日终估值。</p>','capital-chart')
    out+=section('满仓账户：逐轮张数与损益',table(['入场 → 退出','组数／合约张数','单组含费','总投入','期末／退出回收','该轮盈亏','单轮保费收益率','张数/前日较小单腿成交量'],[
        [t['entry_date']+' → '+t['exit_date'],f"{t['pairs']} / {t['pairs']*2}",f"${t['unit_cost']:,.2f}",f"${t['cost']:,.2f}",f"${t['income']:,.2f}",money(t['pnl']),f"{100*t['pnl']/t['cost']:.2f}%",f"{100*t['pairs']/t['previous_volume']:.1f}%"] for t in full['trades']])+f"<p class='note'>最后一轮只按期末市值估值。成交量占比是流动性诊断，没有作为容量限制；成交量不能替代盘口深度。满仓模拟估值异常腿日 {full['async_marks']}，成交异常 {full['execution_anomalies']}，缺失估值 {full['missing_marks']}，不满足可执行报价验证。</p>",'full-trades')
    out+=section('满仓成交摩擦敏感性',table(['每边滑点（另有最低一分钱）','本期盈亏','本期收益率','最大回撤'],[[f"{r['slip']:.0%}",money(r['pnl']),f"{r['return_pct']:.2f}%",f"{r['mdd_pct']:.2f}%"] for r in cap['full_slippage']])+"<p>各档重新计算可买张数和完整账户路径。现金不计息，其他参数不变。大波动需要足以覆盖双边期权支出和摩擦才盈利；满仓多次买入期权可能连续损失大部分保费。</p>")
    return out+section('以下保留旧现金基准与单组结构研究','<p>以下所有原版比较、阈值矩阵、期限和现金利息表，统一为$22,852.50账户只买1组的旧基准；其中9.43%为包含大量闲置现金的账户收益率。实际期权本金收益率及满仓结果以上方更新为准。</p>')
