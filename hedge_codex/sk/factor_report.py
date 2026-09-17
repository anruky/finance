"""Append measured volatility factors and keep the report at 100 shares / 2 puts."""
from html import escape
import math
import re
import json
import hashlib


def fmt(x,digits=2):
    return '—'if x is None else f'{x:+.{digits}f}'


def plain(x,digits=2):
    return '—'if x is None else f'{x:.{digits}f}'


def table(headers,rows):
    return '<div class="tbl-scroll"><table><thead><tr>'+''.join(f'<th>{x}</th>'for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{x}</td>'for x in row)+'</tr>'for row in rows)+'</tbody></table></div>'


def section(title,body,ident=None):
    return '<section class="card"'+(f' id="{ident}"'if ident else '')+f'><h2>{title}</h2>{body}</section>'


def money(x):
    return f'<span class="{"c-red"if x>=0 else "c-green"}">${x:+,.2f}</span>'


def scatter(stat):
    rows=stat['pairs'];W,H,L,R,T,B=780,285,65,757,18,240
    xs=[r['x']for r in rows];ys=[r['y']for r in rows]
    xmin=min(xs)*.9;xmax=max(xs)*1.06;ymax=max(ys)*1.1
    x=lambda v:L+(v-xmin)/(xmax-xmin)*(R-L);y=lambda v:B-v/ymax*(B-T)
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="RVOL5与未来5日波动散点图"><title>当日RVOL5与未来5日已实现波动</title>']
    for j in range(5):
        v=ymax*j/4;s.append(f'<line x1="{L}" x2="{R}" y1="{y(v):.2f}" y2="{y(v):.2f}" stroke="#262b36"/><text x="{L-7}" y="{y(v)+4:.2f}" fill="#9aa3b2" text-anchor="end" font-size="11">{v:.0f}%</text>')
    for j in range(5):
        v=xmin+(xmax-xmin)*j/4;s.append(f'<text x="{x(v):.2f}" y="{B+21}" fill="#9aa3b2" text-anchor="middle" font-size="11">{v:.2f}×</text>')
    for r in rows:
        col='#4da3ff'if r['date']>'2026-08-24'else '#9aa3b2'
        s.append(f'<circle cx="{x(r["x"]):.2f}" cy="{y(r["y"]):.2f}" r="4" fill="{col}" opacity=".85"><title>{r["date"]} RVOL5 {r["x"]:.2f}×，后5日RV {r["y"]:.2f}%</title></circle>')
    return ''.join(s)+'</svg><p class="note">横轴：当日成交量 / 前5日平均成交量；纵轴：未来5日已实现波动。蓝色为新增区间的有效信号日，灰色为更早日期；点代表重叠观察窗，不是独立交易。</p>'


def two_curve(results):
    W,H,L,R,T,B=1000,280,55,980,18,240
    vv=[[r['equity']/res['initial']*100 for r in res['curve']]for res in results]
    lo=math.floor(min(min(v)for v in vv)/5)*5-5;hi=math.ceil(max(max(v)for v in vv)/5)*5+5
    n=len(vv[0]);x=lambda i:L+i*(R-L)/(n-1);y=lambda v:B-(v-lo)/(hi-lo)*(B-T)
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="持股基准与100股加2张Put净值"><title>100股加2张Put与同资金持股基准</title>']
    for j in range(5):
        v=lo+j*(hi-lo)/4;s.append(f'<line x1="{L}" x2="{R}" y1="{y(v):.2f}" y2="{y(v):.2f}" stroke="#262b36"/><text x="{L-7}" y="{y(v)+4:.2f}" fill="#9aa3b2" font-size="11" text-anchor="end">{v:.0f}</text>')
    for v,col in zip(vv,['#9aa3b2','#4da3ff']):
        pts=' '.join(f'{x(i):.2f},{y(z):.2f}'for i,z in enumerate(v));s.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>')
    for i in list(range(0,n-3,7))+[n-1]:s.append(f'<text x="{x(i):.2f}" y="{B+23}" fill="#9aa3b2" font-size="11" text-anchor="middle">{results[0]["curve"][i]["date"][5:]}</text>')
    return ''.join(s)+'</svg><p class="note">灰：同资金持股基准；蓝：100 股＋2 张 Put。初始资金归一为100。</p>'


def apply_factors(html,a,results,data):
    assert a['manifest']['shares']==100 and a['manifest']['puts']==2
    assert a['manifest']['asof']==data['stock'][-1][0], 'Refresh factor analysis to match report data'
    assert a['manifest']['dataset_sha256']==hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(), 'Underlying data changed: recalculate factors'
    stats={r['key']:r for r in a['stats']};latest={r['key']:r for r in a['latest']}
    base=results['results'][1];bh=results['results'][0];end=a['manifest']['asof']
    stock=data['stock'];S=stock[-1][4]
    snap=a['option_snapshots'].get(end)
    assert snap is not None
    p=snap['price'];K=snap['strike'];upper=S+2*p;lower=2*K-S-2*p
    principle=section('固定 100 股＋2 张 Put：怎样把波动兑现为盈利',f'''<div class="callout-gold"><strong>保留原有仓位比例与滚动框架，本次研究只增加波动观测因素。</strong><br>这个组合在到期时具有 V 形收益：涨得足够多，股票赚钱；跌得足够多，两张 Put 的赔付超过股票亏损。</div>
<p>若该轮入场股票价为 S₀、行权价为 K、每股 Put 权利金为 P，在不提前滚动、忽略成本时：</p>
<div class="callout"><strong>到期盈亏 = 100 × (Sₜ − S₀) + 200 × max(K − Sₜ, 0) − 200 × P</strong><br>若 K = S₀，则简化为 <strong>100 × |Sₜ − S₀| − 200 × P</strong>。到期位移超过两张 Put 的权利金才盈亏平衡；不是只要日内来回波动大就一定赚钱。</div>
<p>用 {end} 的快照举例：股票 ${S:.2f}、{snap['expiry']} 到期、行权价 ${K:g}、Put 末价 ${p:.2f}。100股＋2张Put的裸保费为 ${200*p:,.0f}，无滚动到期盈亏平衡约为 <strong>${lower:.2f} / ${upper:.2f}</strong>；佣金和价差会进一步扩大区间。</p>
<p class="note">这只是到期支付结构的算术示例，不是可成交报价。若盘中大涨大跌后收回原位、没有按规则兑现，仍可能亏保费；实际滚动策略须以逐笔账本计算。下文因此同时检验未来路径波动、收盘最大位移与到期近似位移。</p>''','payoff')
    core=section('核心结论：固定2张Put，优先研究下一轮波动',f'''<p>原参数仍为 <strong>100股＋2张Put、目标2天、跌15% / 涨8%滚动</strong>。已有日线模拟全期盈亏 {money(base['pnl'])}，最大回撤 {base['mdd_pct']:.2f}%；同资金基准盈亏 {money(bh['pnl'])}，最大回撤 {bh['mdd_pct']:.2f}%。本轮因子分析没有改变交易或仓位。</p>
<div class="callout-gold"><strong>现阶段优先跟踪“当日振幅”，成交量用相对量作辅助，最后必须看保费。</strong><br>当日高低振幅与后5日波动的秩相关约 {fmt(stats['range_pct']['rho'])}；RVOL5 仅 {fmt(stats['rvol5']['rho'])}。原始成交量的表观相关为 {fmt(stats['log_volume']['rho'])}，控制样本时间和近期波动后降至 {fmt(stats['log_volume']['partial_age_rv5'])}。</div>
<p class="note">因子与波动相关，并不等于因子能提高本策略净收益。数据截止 {end}，SKHY只有44个交易日；原模拟报价不同步的限制仍然存在。</p>''','conclusion')
    priority=['range_pct','rvol5','volume_change','rv5','atr5','down_return','put_cost7','put_tv7','SMH_rv5','QQQ_rv5','MU_rv5','log_volume']
    rows=[]
    for key in priority:
        r=stats[key];rows.append([r['name'],r['n'],fmt(r['rho']),fmt(r['close_excursion_rho']),fmt(r['endpoint_rho']),fmt(r['train_rho']),fmt(r['test_rho'])+f' / n={r["test_n"]}'])
    factors=section('潜在波动因素：与未来波动究竟有多相关',f'''<p>所有特征仅使用<strong>当日收盘及以前</strong>信息，目标从下一交易日开始。主指标为未来5日RV：<strong>100 × √Σ[ln(Cⱼ/Cⱼ₋₁)]²</strong>，不年化。另列未来5日相对信号日的最大收盘位移，以及第5日收盘净位移的绝对值。</p>
{table(['因子','有效样本','后5日RV ρ','最大收盘位移ρ','第5日净位移ρ','开发期ρ','新增期ρ / 样本'],rows)}
<p class="note">ρ 为 Spearman 秩相关，范围 −1～+1；不是胜率或预测精度。比如当日振幅对未来RV相关为 {fmt(stats['range_pct']['rho'])}，但对第5日净位移仅 {fmt(stats['range_pct']['endpoint_rho'])}，说明“波动路径变大”尚不能推出“到期赚到保费”。</p>
<details><summary>查看全部 {len(stats)} 个因子与 1 / 3 / 5 / 10 日波动</summary>{table(['因子','1日ρ','3日ρ','5日ρ','10日ρ','5日样本'],[[r['name']]+[fmt(r['horizons'][str(h)]['rho'])for h in (1,3,5,10)]+[r['n']]for r in a['stats']])}</details>''','factors')
    volume=section('成交量专题：绝对量、相对量与上市效应',f'''<div class="cols"><div><h3>原始成交量容易混入上市阶段效应</h3><p>与当天高低振幅的相关为 {fmt(a['volume_same_day']['log_volume'])}，与后5日RV为 {fmt(stats['log_volume']['rho'])}。控制检查使用满足暖机的共同样本（n={stats['log_volume']['partial_n']}），其未控制相关为 {fmt(stats['log_volume']['matched_raw_rho'])}，控制样本经过天数及近5日RV后为 {fmt(stats['log_volume']['partial_age_rv5'])}；新增期相关约 {fmt(stats['log_volume']['test_rho'])}。</p><p class="note">这是探索性偏相关，不能证明因果；早期量大和早期波动大可能来自同一上市阶段。</p></div>
<div><h3>RVOL5 更适合日常跟踪，但证据仍弱</h3><p><strong>RVOL5 = 当日量 / 前5日平均量</strong>，分母不含当天。全样本后5日相关 {fmt(stats['rvol5']['rho'])}，排除最初10个信号日后为 {fmt(stats['rvol5']['exclude_first10'])}；5日分块重采样区间为 [{fmt(stats['rvol5']['interval'][0])}, {fmt(stats['rvol5']['interval'][1])}]。</p><p class="note">区间跨零，不能作为独立有效信号；新增期虽有较高相关，但只有 {stats['rvol5']['test_n']} 个重叠观察窗。</p></div></div>{scatter(stats['rvol5'])}
<p>长样本交叉检查也显示，相对量的相关通常弱于价格振幅和已有波动。因此量能适合与振幅、事件和保费联合记录，尚不宜据此跳过或增加任何一轮。</p>''','volume-factors')
    checks=[]
    for key in ['log_volume','rvol5','range_pct','atr5','rv5','put_cost7']:
        r=stats[key];ci=r['interval'];checks.append([r['name'],fmt(r['rho']),f'[{fmt(ci[0])}, {fmt(ci[1])}]'if ci else '—',fmt(r['exclude_first10']),fmt(r['partial_age_rv5']),fmt(r['nonoverlap_rho'])+f' / n={r["nonoverlap_n"]}'])
    peerrows=[]
    for r in a['peers']:
        peerrows.append([r['ticker'],r['start']+' → '+r['end'],r['n_bars']]+[fmt(r['factors'][k]['rho'])+f' / n={r["factors"][k]["n"]}'for k in ('rvol5','range_pct','rv5')])
    robust=section('稳定性检查与更长历史的交叉验证',table(['因子','全样本ρ','5日块重采样95%区间','去最初10日ρ','控制时间与RV5后ρ','不重叠窗ρ / n'],checks)+f'''<p class="note">RV5作为控制变量时自身的偏相关不定义。重采样为5日移动块、800次、固定种子；这是小样本描述区间，未作多重比较校正，也未消除上市阶段的非平稳性，不能据此宣称统计显著。</p>
<h3>长历史：各标的自己的指标 → 自己随后5日RV</h3>{table(['标的','数据区间','交易日','RVOL5 ρ / n','当日振幅ρ / n','近5日RV ρ / n'],peerrows)}
<p>在这五个独立标的中，RVOL5 的相关约为 +0.10～+0.18，日内振幅约为 +0.27～+0.42，近5日RV约为 +0.25～+0.41。这支持先研究波动持续性，再考察量能是否提供额外信息。</p>
<p class="note">这些是各标的内部的描述性检验，不是对 SKHY 的新增样本，也不是经过多标的持仓回测的策略收益。板块指标预测 SKHY 的结果已在上表单列。外部价格为供应商拆股调整日线，SKHY沿用已刷新行情包。</p>
<h3>固定开发期中位数作观察门槛</h3>{table(['因子','开发期门槛','开发期高/低组后5日RV','新增期高/低组后5日RV'],[[stats[k]['name'],plain(stats[k]['threshold'],3),group(stats[k],'train'),group(stats[k],'test')]for k in ['rvol5','volume_change','range_pct','rv5']])}
<p class="note">开发期只使用未来5日窗口结束日≤2026-08-24的标签，避免穿越切分点。新增期信号日>08-24且后5日数据已完整，因此最多只有8个标签。振幅和RV5的新增期高组为空，不能声称固定门槛已通过新增期验证。</p>''','factor-checks')
    roundrows=[]
    for r in a['rounds']:
        roundrows.append([r['signal'],r['entry']+' → '+r['exit'],plain(r['rvol5'])+'×'if r['rvol5']is not None else '暖机不足',plain(r['rv5'])+'%'if r['rv5']is not None else '暖机不足',f'{r["cost_pct"]:.2f}%',money(r['round_pnl']),('期末估值'if r['mark_only']else '已结束')])
    profitability=section('这些因子是否能提高100股＋2张Put净收益',f'''<p>保留原来的实际交易路径，把每轮<strong>入场前一日</strong>的指标与该轮股票＋Put合计盈亏关联，不事后删除亏损轮。</p>
{table(['入场前因子','可用已结束轮数','与轮内组合盈亏的秩相关'],[[{'rvol5':'RVOL5','rv5':'近5日RV','atr5':'ATR5%'}[r['key']],r['n'],fmt(r['rho'])]for r in a['round_associations']])}
<div class="callout-warn"><strong>尚未证明任何成交量/波动因子能提高该固定策略净收益。</strong><br>当前RVOL5与轮内组合盈亏的相关为 {fmt(a['round_associations'][0]['rho'])}；只有11轮可用，而且最早两个已结束轮因暖机不足被排除，包含最大盈利轮。这个小样本结果不能作为反向交易信号。</div>
<details><summary>展开每轮入场前指标与合计盈亏</summary>{table(['信号日','入场 → 退出','RVOL5','近5日RV','实际2张保费占比','轮内组合盈亏','状态'],roundrows)}</details>
<p class="note">期末未平仓轮不参加相关计算；轮内组合盈亏仅归属该轮股票期间和Put，不包括轮次外的股票盈亏。原模拟中的不同步价格仍影响这些金额。</p>''','factor-profit')
    monitorrows=[]
    for k,unit in [('rvol5','×'),('range_pct','%'),('rv5','%'),('atr5','%'),('SMH_rv5','%'),('put_cost7','%')]:
        r=latest[k];monitorrows.append([r['name'],plain(r['value'])+unit,plain(r['percentile'],0)+'%'])
    candidates=[
        ['未来5日内财报/产品发布/宏观事件','有预定时间的消息容易造成跳空；但波动也可能已被期权价格计入','需要历史当时可见的事件日历；本次未回填或计算相关性'],
        ['SK海力士韩国本股波动、ADR溢价、USD/KRW','韩国收盘信息先于美国开盘，可能提供跨市场信息','需韩国股价、汇率、存托凭证比例及明确时区；本次未作因子验证'],
        ['期限结构、IV/RV、Put/Call量比和未平仓量变化','市场预期、对冲需求和期权成本能共同解释买波动是否太贵','当前已测Put价格/时间价值代理；完整Call链、历史OI及同步报价尚未补齐'],
        ['报价价差与盘口深度','决定看见的波动收益能否实际兑现','历史Quotes权限403，现阶段不能可靠估计入场/退出Bid-Ask成本'],
        ['盘中量能、尾盘成交与隔夜波动','可能区分当天放量结束还是信息继续发酵','需分钟量并按同一时刻历史均量归一；日线结果不能直接替代']]
    monitoring=section(f'最新因子看板与后续观察（{end}）',table(['指标','最新值','相对此前SKHY样本的分位'],monitorrows)+f'''<p>最新 RVOL5 为 {plain(latest['rvol5']['value'])}×，当日振幅 {plain(latest['range_pct']['value'])}%；这两项并未处于本样本高位。近5日RV为 {plain(latest['rv5']['value'])}%，与两张Put保费率 {plain(latest['put_cost7']['value'])}% 的口径不同，不能直接相减或据此宣布存在盈利空间。</p>
<div class="callout"><strong>实际记录顺序：</strong>先记当日振幅、RVOL5和近5日RV；再标注已知事件与板块情况；最后把两张Put的实际成本换算为上下盈亏平衡位移，观察随后是否按现有滚动规则兑现。<br>仓位固定100股＋2张Put。现在把因子作为观察列，不依据这44天样本增减张数或自动跳过交易。</div>
<h3>潜在因素：有机制依据，但尚未实证验证</h3>{table(['候选因素','可能机制','需要补充的数据/本次状态'],candidates)}
<p class="note">数据文件：<a href="factor_analysis.json">26项因子、标签、相关性及逐轮关联</a> · <a href="data/factor_market_data.json">新增五个标的行情</a> · <a href="FACTOR_RESEARCH.md">因子定义与复现命令</a>。新增行情拉取时间：{escape(a['manifest']['market_data']['fetched_at_utc'])}。</p>
<p class="note">机制参考：<a href="https://www.nber.org/papers/w4988">Brock 与 LeBaron：成交量、波动及持续性</a>；<a href="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365738">Corsi：多期限波动持续性模型</a>；<a href="https://cdn.cboe.com/resources/education/research_publications/rmoverlaystrategieswp.pdf">Cboe：隐含与已实现波动及风险溢价</a>。文献支持研究动机，SKHY数值均由本地行情计算。</p>''','factor-monitor')
    factor_sections=principle+factors+volume+robust+profitability+monitoring
    replacements={
     '策略模型':section('策略模型',f'''<p><strong>固定100股对应2张Put，捕捉下一轮足以覆盖保费的价格波动。</strong>维持原参数目标2天、跌15% / 涨8%滚动。</p><p>{stock[0][0]} 首日收盘买入100股，保费备用金为股票成本的50%，所有方案及基准初始资金 ${base['initial']:,.2f}。前日收盘形成信号并选择合约，次日日线末价加费用模拟执行。</p><p class="note">每边滑点2%（最低$0.01/股），佣金每张$0.65；股票成本5bps。新因子分析不修改仓位、阈值或交易路径。</p>'''),
     '核心结论':core+factor_sections,
     '组合净值曲线':section('组合净值曲线',two_curve([bh,base])),
     '策略优化方案横向对比':section('固定2张Put：已有规则敏感性对照',table(['规则对照','全期收益','最大回撤','新增期盈亏'],[[r['name'],money(r['pnl']),f'{r["mdd_pct"]:.2f}%',money(r['holdout']['pnl'])]for r in results['results']if r['config']['puts']==2])+'''<p class="note">所有期权仓位都是2张。成本/趋势过滤方案仅保留为既有敏感性对照，过滤期间可能不持有Put；本轮主策略不采用这些过滤规则。因子尚未带来经过验证的收益改进。</p>''','optimization'),
    }
    def sub(m):
        block=m.group(0);heading=re.search(r'<h2>(.*?)</h2>',block).group(1)
        if heading in replacements:return replacements[heading]
        if heading.startswith('新增区间验证'):
            return section(heading,table(['方案','新增期盈亏','新增期收益率','新增期最大回撤'],[[r['name'],money(r['holdout']['pnl']),f'{r["holdout"]["return_pct"]:+.2f}%',f'{r["holdout"]["mdd_pct"]:.2f}%']for r in [bh,base]])+'<p class="note">沿用已有持仓，以08-24各方案实际净值为期初。因子预测另行清除跨越切分点的未来5日标签，两者样本数不同。</p>','validation')
        if heading=='交易摩擦敏感性':
            return section(heading,table(['Put张数','每边比例滑点','全期收益','最大回撤','新增期收益'],[[2,f'{r["slip"]:.0%}',money(r['pnl']),f'{r["mdd_pct"]:.2f}%',money(r['holdout']['pnl'])]for r in results['sensitivity']if r['puts']==2])+'<p class="note">0%仍保留最低一分钱价差与佣金。</p>')
        if heading.startswith('最新期权快照'):
            return section(heading,table(['股票收盘','参考Put','到期日','Put末价','2张裸保费','上下盈亏平衡价'],[[f'${S:.2f}',f'K=${K:g}',snap['expiry'],f'${p:.2f}',f'${p*200:,.2f}',f'${lower:.2f} / ${upper:.2f}']])+'<p class="note">参考为当日7天目标ATM Put，供保费比较。历史末价不是实时可成交盘口；盈亏平衡示例忽略滚动及费用。</p>','snapshot')
        return block
    html=re.sub(r'<section class="card"[^>]*>.*?</section>',sub,html,flags=re.S)
    html=html.replace('（涨 / 跌阈值不对称扫描 · 更新版）','（100股＋2张Put · 波动相关因素研究）')
    html=html.replace('<a href="#matrix">参数矩阵</a>','<a href="#factors">波动因子</a><a href="#volume-factors">成交量</a><a href="#factor-monitor">最新因子</a><a href="#matrix">参数矩阵</a>')
    return html


def group(stat,key):
    g=stat['groups'].get(key)
    if not g:return '样本不足'
    return f'{plain(g["high_mean"])}% / {plain(g["low_mean"])}%（n={g["high_n"]}/{g["low_n"]}）'
