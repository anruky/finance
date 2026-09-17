# -*- coding: utf-8 -*-
import json,re,math,statistics,argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from report_helpers import money,pct,table,section
from exit_rules import features

def ranks(xs):
 out=[];ordered=sorted(xs)
 for x in xs:
  ii=[i for i,v in enumerate(ordered) if v==x];out.append(sum(ii)/len(ii))
 return out

def corr(x,y):
 if len(x)<3:return None
 a,b=statistics.mean(x),statistics.mean(y);den=math.sqrt(sum((v-a)**2 for v in x)*sum((v-b)**2 for v in y))
 return sum((v-a)*(w-b) for v,w in zip(x,y))/den if den else None

def factor_checks(d):
 f=features(d);out=[]
 for field,label in [('atr_pct','前7日ATR%'),('rvol','开盘半小时成交量／前5日同期均量'),('morning_return','开盘半小时绝对涨跌幅'),('rv_ratio','前5日／前10日实现波动比')]:
  pairs=[]
  for i in range(len(d['stock'])-1):
   dt,nxt=d['stock'][i][0],d['stock'][i+1][0];x=f[dt][field]
   if x is None:continue
   if field=='morning_return':x=abs(x)
   a=d['stock_minutes'][dt].get('09:59');b=d['stock_minutes'][nxt].get('09:59')
   if a and b:pairs.append((i,x,abs(math.log(b['c']/a['c']))))
  row=dict(factor=label)
  for tag,pp in [('full',pairs),('train',[p for p in pairs if p[0]+1<31]),('validation',[p for p in pairs if p[0]>=31])]:
   row[tag]=dict(n=len(pp),spearman=corr(ranks([p[1] for p in pp]),ranks([p[2] for p in pp])))
  out.append(row)
 return out

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--results',type=Path);ap.add_argument('--output',type=Path);args=ap.parse_args();root=args.project_dir
 rp=args.results or root/'skhy_exit_optimization_results.json';r=json.loads(rp.read_text());d=json.loads((root/'data/SKHY_intraday.json').read_text());checks=factor_checks(d);r['factor_checks']=checks;rp.write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
 byid={x['rule']['id']:x for x in r['summaries']};train=byid[r['robust']];best=byid[r['best_full']];base=r['baseline_periods'];n=r['method']['n_rules']
 s2train=max(r['strategy2_scan'],key=lambda x:x['train']['score']);s2best=max(r['strategy2_scan'],key=lambda x:x['full']['pnl'])
 css=re.search(r'<style>(.*?)</style>',(root/'skhy_simulation_report.html').read_text(),re.S).group(1);parts=[]
 parts.append(section('结论：退出规则改善亏损，尚未找到可验证的盈利方案',f'''<div class="callout-gold"><strong>在本次预设的{n}组退出规则中，两策略都没有找到全期盈利的组合。</strong><br>策略1全期最高收益规则是 <strong>{best['rule']['label']}</strong>，净收益 {money(best['full']['pnl'])}，优于原15%／8%的 {money(base['full']['pnl'])}，但这是使用全期结果排序的事后候选。</div>
<p>只用07-13～08-24前31个交易日挑选，训练收益和风险调整分数都选择<strong>{train['rule']['label']}</strong>。它在08-25～09-11的后13个交易日亏损 {money(train['validation']['pnl'])}，与原规则该段 {money(base['validation']['pnl'])} 相同，未获得后段美元收益改善。因此不能把“涨7%”直接认定为通用最优，也不据此替换现有默认交易规则。</p>
<p>策略2独立执行扫描的训练选择为 <strong>{s2train['rule']['label']}</strong>，全期 {money(s2train['full']['pnl'])}，训练期 {money(s2train['train']['pnl'])}、后段 {money(s2train['validation']['pnl'])}。各策略最佳参数不同，说明仓位结构会影响退出规则。</p>''','conclusion'))
 rows=[['原规则：跌15%／涨8%',money(base['train']['pnl']),money(base['validation']['pnl']),money(base['full']['pnl']),pct(base['full']['mdd_pct']),money(r['baseline']['additional_deposits']),len(r['baseline']['trades'])]]
 for title,x in [('前段选择（后段未改善）',train),('全期排名第一（事后）',best)]:
  res=r['details'][x['rule']['id']]['strategy1'];rows.append([title+'：'+x['rule']['label'],money(x['train']['pnl']),money(x['validation']['pnl']),money(x['full']['pnl']),pct(x['full']['mdd_pct']),money(res['additional_deposits']),len(res['trades'])])
 parts.append(section('策略1：固定10组账户的收益与风险',table(['规则','前31日净收益','后13日净收益','全期净收益','全期单位净值回撤','追加资金','轮数'],rows)+'<p>收益为期末净资产减全部入金，追加资金不算收益；回撤使用剔除入金影响的单位净值。同样负收益但回撤百分比不同，可能来自期初净值及资本路径差异，不等于同段多赚了钱。</p>','comparison'))
 parts.append(section('如何搜索与验证','''<p>候选集合在扫描前固定：77组涨跌阈值、16组ATR倍数、6组时间退出、12组组合盈亏止盈止损、6组利润回撤、6组放量反向、6组波动收缩，共129组。策略1账户10组，资金不足按缺口追加；策略2沿用原本金。10:00判断，最晚等待至15:59共同成交分钟；平仓后下一分钟才能重开。</p>
<p>训练选择分数＝前段净收益−0.5×前段累计净收益的最大美元回撤，系数固定不优化；另列训练净收益最高和全期净收益最高，保留全部129组结果。后段净收益从08-24收盘账户资产和累计入金接续，继承持仓，不把整个跨界轮次利润错算到某一段。</p>
<p>这一后段数据在此前报告已被查看，所以这里只能称为“回顾性的按时间划分验证”，不是从未看过的未来样本。44个交易日不足以建立可靠通用最优。全期排名存在多重尝试偏差，未对最优参数作显著性保证。</p>''','method'))
 fams={'threshold':'固定涨跌幅','atr':'ATR动态阈值','time':'持有天数／到期前退出','option_roi':'组合盈亏止盈止损','trailing':'利润回撤退出','volume_reversal':'放量反向','rv_cooldown':'实现波动收缩'}
 famrows=[]
 for fam,label in fams.items():
  x=max((x for x in r['summaries'] if x['rule']['family']==fam),key=lambda x:x['train']['score'])
  famrows.append([label,x['rule']['label'],money(x['train']['pnl']),money(x['validation']['pnl']),money(x['full']['pnl'])])
 parts.append(section('哪些指标可以用于平仓重开',table(['规则族','仅按训练选择的代表','前段收益','后段收益','全期收益'],famrows)+'''<ul>
<li>ATR：使用截至前日的7日真实波幅均值÷前日收盘价，乘动态涨跌倍数，阈值限制在3%–25%；历史不足7日沿用15%／8%。</li>
<li>组合止盈止损：在09:55–09:59最新共同成交分钟估算扣费清仓价值，相对本轮总投入判断；缺新鲜共同价格就不触发此指标，不拿10:00后的成交回填信号。</li>
<li>利润回撤：只跟踪每日10:00可见的最高组合收益，盈利达到激活门槛后回吐一定收益率百分点退出；不使用全天高点。</li>
<li>量比反向：当日开盘半小时成交量÷前5日同时间段均量，且半小时涨跌方向与持仓累计股价方向相反。成交量本身不等于未来波动，也不保证期权盈利。</li>
<li>波动收缩：只用前日及更早收盘收益计算RV5/RV10。持仓至少2或3自然日且短期波动收缩至阈值以下时重开。时间退出按自然日计算。</li>
</ul><p>固定涨跌触发和到期处理优先，其余指标作为额外退出条件。所有方案退出后仍立即尝试重新开仓；因此这里检验的是“何时滚动”，不是空仓择时。若波动已经变小，平仓后立刻买回期权仍可能继续损失时间价值。</p>''','indicators'))
 parts.append(section('指标与下一交易日波动的关联',table(['10:00可见指标','全期Spearman / N','前段Spearman / N','后段Spearman / N'],[[x['factor']]+[(f"{x[tag]['spearman']:+.3f}" if x[tag]['spearman'] is not None else '—')+f" / {x[tag]['n']}" for tag in ('full','train','validation')] for x in checks])+'<p>目标是本日10:00信号价到下一交易日10:00信号价的绝对对数收益；仅描述下一日股价变动大小，不等于期权收益。前段样本的目标也必须在训练段内，跨分界点样本排除。后段数量少，相关系数不作为已验证的买卖信号。</p>','factors'))
 dns=sorted({x['rule']['down'] for x in r['summaries'] if x['rule']['family']=='threshold'});ups=sorted({x['rule']['up'] for x in r['summaries'] if x['rule']['family']=='threshold'})
 matrix=[]
 for dn in dns:
  cells=[f'跌{dn:g}%']
  for up in ups:
   x=next(x for x in r['summaries'] if x['rule'].get('family')=='threshold' and x['rule']['down']==dn and x['rule']['up']==up)
   cells.append(money(x['full']['pnl']))
  matrix.append(cells)
 parts.append(section('固定涨跌阈值：全期净收益矩阵（事后诊断）',table(['策略1／10组']+[f'涨{u:g}%' for u in ups],matrix)+'<p>矩阵包含已查看的后段，不能据此重新选出参数后仍称它通过了独立验证。</p>','matrix'))
 parts.append(section('前段所选参数附近是否稳定',table(['规则','前段收益','后段收益','全期收益'],[[x['rule']['label'],money(x['train']['pnl']),money(x['validation']['pnl']),money(x['full']['pnl'])] for x in r['neighbors']]),'neighbors'))
 folds=r['walkforward']['folds']
 parts.append(section('逐段滚动选参数并实际接续持仓',table(['截至何日训练','随后验证区间','仅用此前数据选择','实际接续账户净收益','原规则同段收益'],[[x['train_end'],x['test_start']+' → '+x['test_end'],x['rule']['label'],money(x['live']['pnl']),money(x['baseline']['pnl'])] for x in folds])+f"<p>首次前20日保持原规则，随后每8日用此前所有数据按固定训练分数重新选择，应用到真实接续账户的现有持仓，而非拼接各候选的最佳净值。后24日合计 {money(r['walkforward']['validation']['pnl'])}；原规则同段 {money(r['walkforward']['baseline_validation']['pnl'])}。这段没有改善，也不属于新的未观察样本。</p>",'walkforward'))
 stress=[]
 for ident in dict.fromkeys([r['robust'],r['best_full']]):
  detail=r['details'][ident]
  for v in detail['sensitivity']:stress.append([detail['summary']['rule']['label'],pct(v['slip']*100),f"{10+v['window']//60:02d}:{v['window']%60:02d}",money(v['full']['pnl']),money(v['validation']['pnl']),v['rounds']])
 parts.append(section('成交窗口与成本压力测试',table(['规则','每边滑点','最晚成交分钟','全期净收益','后段净收益','轮数'],stress)+'<p>改用更短等待窗口或5%滑点时，账户路径、追加资金和交易轮数重新模拟。最优规则也对执行条件敏感；不得把全天能找到交易误认为开盘后即可按该价成交。</p>','stress'))
 for ident in dict.fromkeys([r['robust'],r['best_full']]):
  v=r['details'][ident];rr=[]
  for t in reversed(v['strategy1']['trades']):
   pc=t['put_cost']/5;pi=t['put_income']/5;stock=t['exit_spot']*100*(1 if t['mark_only'] else 1-.0005)-t['entry_spot']*100*(1+.0005)
   rr.append([t['entry_date']+' '+t['entry_time'],t['exit_date']+' '+t['exit_time'],t['reason'],money(t['strike']),money(t['entry_spot']),money(t['exit_spot']),money(t['cost']/10),money(t['income']/10),money(t['pnl']/10),money(pc),money(pi),money(pi-pc+stock)])
  parts.append(section('候选逐轮：'+v['summary']['rule']['label'],table(['入场','退出','原因','行权价','入场股价','退出股价','1C1P成本','1C1P收入','1C1P利润','2Put成本','2Put收入','100股2Put利润'],rr)+'<p>策略1按单组；策略2固定使用策略1的时间和价格重算，股票买卖各5bps。用于结构比较，不是策略2独立执行的账户结果。期末持有行只按日终市值估值。</p>','trades-'+ident))
 parts.append(section('如何使用这个结果','''<p>当前可以优先继续验证上涨7%的较早滚动，但下跌门槛仍不稳定：训练偏向12.5%，全期排序偏向5%。没有依据保证任何一组在未来最优。要寻求盈利，应下一步把“平仓”和“立即重开”拆开，研究期权价格隐含的波动成本、波动收缩时是否暂缓重开，以及减少近到期期权摩擦；这些属于新入场规则，本次没有用它们改变退出测试。</p>
<p>原理参考：<a href="https://prd-web.optionseducation.org/strategies/all-strategies/long-straddle">OIC：跨式的波动与时间损耗</a>；验证方法背景：<a href="https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf">The Probability of Backtest Overfitting</a>。数据只有44个交易日，仍有成交量不足和非同步末价风险。</p>
<p><a href="skhy_exit_optimization_results.json">完整129组两策略扫描与账本</a> · <a href="EXIT_OPTIMIZATION_README.md">复现说明</a> · <a href="skhy_straddle_report.html">当前基准报告</a></p>''','next'))
 now=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
 html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY 退出规则优化与验证</title><style>{css}</style></head><body><div class="wrap"><h1>SKHY 退出策略优化与验证</h1><p class="sub">129组规则 × 两策略 · 分时成交、补资与费用完整重算 · 更新 {now}</p><nav><a href="#conclusion">结论</a><a href="#comparison">收益对比</a><a href="#indicators">指标</a><a href="#matrix">涨跌矩阵</a><a href="#stress">压力测试</a></nav>{''.join(parts)}</div></body></html>'''
 out=args.output or root/'skhy_exit_optimization_report.html';out.write_text(html)
 print('Report:',out);print('Factors:',checks)
if __name__=='__main__':main()
