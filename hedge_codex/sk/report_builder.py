#!/usr/bin/env python3
"""Generate a self-contained Chinese research report and reproducible results."""
import argparse
from dataclasses import replace
from datetime import datetime
from html import escape
import json
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo
from backtest_audited import Config, run, window_metrics, indicators
from refresh_data import atomic_json

ROOT = Path(__file__).resolve().parent
BOUNDARY = '2026-08-24'
MOVES = [8, 10, 12, 15, 18, 20, 25]


def compact(r):
    return {k:v for k,v in r.items() if k not in ('curve', 'trades')}


def money(v):
    return f'<span class="{"pos" if v >= 0 else "neg"}">{v:+,.2f}</span>'


def pct(v):
    return f'{v:+.2f}%'


def ratio(v):
    return '—' if v is None else f'{v:.2f}'


def quality(r):
    return ('<span class="badge ok">未发现两类异常</span>' if r['eligible'] else
            f'<span class="badge warn">估值缺失 {r["missing_marks"]} · 不同步 {r["async_marks"]} · 成交异常 {r["execution_anomalies"]}</span>')


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in headers)+\
           '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+\
           '</tbody></table></div>'


def validate(d):
    stock = d['stock']; dates = [r[0] for r in stock]
    assert dates == sorted(set(dates)), 'Duplicate/unsorted sessions'
    assert len(stock) > 31 and BOUNDARY in dates, 'Need both development and holdout periods'
    for dt, o, h, l, c, volume in stock:
        assert 0 < l <= min(o,c) <= max(o,c) <= h and volume > 0, 'Invalid stock OHLC'
        assert dt in d['listed']
    assert dates[-1] == d['manifest']['stock_end']
    for tickers in d['listed'].values():
        assert all(t in d['contracts'] and t in d['history'] for t in tickers)


def compute(d):
    validate(d)
    base = Config()
    configs = [replace(base, puts=0), base, replace(base, puts=1),
               replace(base, puts=1, moneyness=.95), replace(base, puts=1, moneyness=.90),
               replace(base, cap=11), replace(base, cap=8),
               replace(base, puts=1, cap=5.5), replace(base, target=7),
               replace(base, target=14), replace(base, target=21),
               replace(base, trend=True), replace(base, atr_trigger=True)]
    names = ['持股基准＋同额备用金', '原参数／修正执行', '1 张 ATM Put',
             '1 张 95% 行权价 Put', '1 张 90% 行权价 Put', '2 张 Put／11% 保费上限',
             '2 张 Put／8% 保费上限', '1 张 Put／5.5% 保费上限',
             '2 张 Put／7 天', '2 张 Put／14 天', '2 张 Put／21 天',
             'MA20 弱势才买 Put', 'ATR 自适应滚动']
    results = []
    for cfg, name in zip(configs, names):
        r = run(d, cfg); r['name'] = name
        r['holdout'] = window_metrics(r, BOUNDARY)
        r['development'] = compact(run(d, cfg, end=BOUNDARY))
        results.append(r)
    grid = []
    for target in (2,7,14,21):
        for n in (1,2):
            for down in MOVES:
                for up in MOVES:
                    cfg = replace(base, target=target, puts=n, down=down, up=up)
                    train = run(d, cfg, end=BOUNDARY)
                    full = run(d, cfg)
                    grid.append(dict(config=full['config'], label=full['label'], development=compact(train),
                                     full=compact(full), holdout=window_metrics(full, BOUNDARY)))
    clean = [r for r in grid if r['development']['eligible'] and len(r['development']['actual_dtes']) >= 3]
    key = lambda r: r['development']['pnl_mdd'] if r['development']['pnl_mdd'] is not None else -1e9
    best_clean = max(clean, key=key) if clean else None
    baseline_score = results[0]['development']['pnl_mdd']
    select_hedge = best_clean is not None and key(best_clean) > baseline_score
    selected = best_clean['label'] if select_hedge else '持股基准＋同额备用金'
    sensitivity = []
    for n in (1,2):
        for slip in (0, .02, .05):
            r = run(d, replace(base, puts=n, slip=slip))
            sensitivity.append(dict(puts=n, slip=slip, **compact(r), holdout=window_metrics(r, BOUNDARY)))
    # Rolling chronological folds: freshly funded portfolios at each boundary.
    walk = []
    dates = [r[0] for r in d['stock']]
    for cut in (24, 29, 34, 39):
        if cut+1 >= len(dates):
            continue
        train_end, test_start, test_end = dates[cut], dates[cut+1], dates[min(cut+5, len(dates)-1)]
        options = [replace(base, puts=0)] + [replace(base, puts=n,target=t,down=dn,up=up)
                  for n in (1,2) for t in (2,7,14,21) for dn in (8,15,25) for up in (8,15,25)]
        train = [run(d,c,end=train_end) for c in options]
        usable = [r for r in train if r['eligible'] and (r['config']['puts']==0 or len(r['trades'])>=3)]
        chosen = max(usable,key=lambda r:r['pnl_mdd'] if r['pnl_mdd'] is not None else -1e9)
        test = run(d,Config(**chosen['config']),start=test_start,end=test_end)
        bh = run(d,replace(base,puts=0),start=test_start,end=test_end)
        walk.append(dict(train_end=train_end,test_start=test_start,test_end=test_end,
                         selected='持股基准' if not chosen['config']['puts'] else chosen['label'],
                         test=compact(test),baseline=compact(bh)))
    return dict(results=results, grid=grid, clean_count=len(clean), best_clean=best_clean,
                selected=selected, select_hedge=select_hedge, sensitivity=sensitivity, walk_forward=walk)


def render(d, out, analysis):
    rr=analysis['results']; bh, original, one = rr[:3]
    stock=d['stock']; start,end=stock[0][0],stock[-1][0]
    ntrain=sum(r[0]<=BOUNDARY for r in stock); ntest=len(stock)-ntrain
    recent=stock[-1][4]; ma,atr=indicators(stock)
    countbars=sum(len(b) for b in d['history'].values())
    rows=[]
    for r in rr:
        h=r['holdout']
        rows.append([escape(r['name']), money(r['pnl']),pct(r['return_pct']),f'{r["mdd_pct"]:.2f}%',
                     money(r['put_pnl']),money(h['pnl']),pct(h['return_pct']),
                     str(len(r['trades'])),f'{r["protected_pct"]:.0f}%',quality(r)])
    comparison=table(['方案','全期盈亏 $','资金收益','最大回撤','Put净损益 $',
                      '新增期盈亏 $','新增期收益','轮数¹','覆盖²','数据检查'],rows)
    sensitivity=table(['张数','每边比例滑点³','全期盈亏 $','最大回撤','新增期盈亏 $'],
        [[r['puts'],f'{r["slip"]:.0%}',money(r['pnl']),f'{r["mdd_pct"]:.2f}%',money(r['holdout']['pnl'])]
         for r in analysis['sensitivity']])
    walk=table(['训练截止','验证期','训练后选择','验证收益','基准收益'],
        [[r['train_end'],r['test_start']+' → '+r['test_end'],r['selected'],
          pct(r['test']['return_pct']),pct(r['baseline']['return_pct'])] for r in analysis['walk_forward']])
    top=sorted(analysis['grid'],key=lambda r:r['development']['pnl_mdd'] if r['development']['pnl_mdd'] is not None else -1e9,reverse=True)[:12]
    scan=table(['训练期排序（含异常）','训练盈亏 $','训练收益/回撤','训练数据检查','新增期盈亏 $'],
        [[r['label'],money(r['development']['pnl']),ratio(r['development']['pnl_mdd']),
          quality(r['development']),money(r['holdout']['pnl'])] for r in top])
    # Full asymmetric grid, no first-stage symmetric pruning.
    matrix=[]
    for dn in MOVES:
        cells=[f'跌 {dn}%']
        for up in MOVES:
            r=next(r for r in analysis['grid'] if r['config']['target']==2 and r['config']['puts']==2
                   and r['config']['down']==dn and r['config']['up']==up)
            cells.append(money(r['full']['pnl'])+(' †' if not r['full']['eligible'] else ''))
        matrix.append(cells)
    matrix=table(['2 张／2D']+[f'涨 {up}%' for up in MOVES],matrix)
    trade_table=table(['信号日','入场 → 退出/估值日','合约','结束方式','支出 $','收入/市值 $','Put净损益 $'],
        [[r['signal_date'],r['entry_date']+' → '+r['exit_date'],escape(r['ticker']),r['reason'],
          f'{r["cost"]:,.2f}',f'{r["income"]:,.2f}',money(r['pnl'])] for r in reversed(original['trades'])])
    ledger=table(['日期','股票市值 $','现金 $','Put市值 $','组合净值 $','持仓'],
        [[r['date']]+[f'{r[k]:,.2f}' for k in ('stock','cash','put_value','equity')]+[r['holding'] or '—']
         for r in reversed(original['curve'])])
    anomaly=[]
    for row in original['curve']:
        t=row['holding']
        if not t:continue
        con=d['contracts'][t]; p=d['history'][t].get(row['date'],{}).get('c')
        intrinsic=max(con['strike_price']-row['stock']/100,0)
        if p is not None and p+.05<intrinsic:
            anomaly.append([row['date'],t,f'{p:.2f}',f'{intrinsic:.2f}',f'{(intrinsic-p)*200:.2f}'])
    anomalies=table(['日期','合约','期权日线末价 $','股票收盘对应内在价值 $','2 张估值差 $'],anomaly)
    near=[]
    expiries=sorted({d['contracts'][t]['expiration_date'] for t in d['listed'][end]})[:3]
    for exp in expiries:
        ts=[t for t in d['listed'][end] if d['contracts'][t]['expiration_date']==exp and d['history'][t].get(end,{}).get('v',0)>0]
        if not ts:continue
        t=min(ts,key=lambda t:abs(d['contracts'][t]['strike_price']-recent)); c=d['contracts'][t]; b=d['history'][t][end]
        near.append([exp,str(c['strike_price']),f'{b["c"]:.2f}',f'{b["vw"]:.4f}',str(b['v']),
                     f'{b["c"]*200:,.2f}',f'{b["c"]*2/recent*100:.2f}%'])
    latest=table(['到期','行权价 $','日线末价 $','全天VWAP $','成交张数','2 张裸保费 $','占100股市值'],near)
    best=analysis['best_clean']
    clean_text=(f'通过两类数据筛选的训练期候选有 {analysis["clean_count"]} 组（至少 3 轮）。其中最高收益/回撤比为 '
                f'{ratio(best["development"]["pnl_mdd"])}，参数 {escape(best["label"])}；'
                f'同口径基准为 {ratio(bh["development"]["pnl_mdd"])}。' if best else '没有通过数据筛选的训练期候选。')
    generated=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M CST')
    html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SKHY 对冲策略｜数据刷新与审计</title><style>
:root{color-scheme:dark;--bg:#0c1119;--panel:#141d29;--line:#293647;--ink:#e7eef7;--muted:#9fb0c5;--blue:#7fb8ff;--gold:#f5cb80;--up:#f09490;--down:#68cbb3}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1240px;margin:auto;padding:48px 28px 64px}a{color:var(--blue)}header{border-bottom:1px solid var(--line);padding-bottom:26px}.eyebrow{letter-spacing:.16em;color:var(--blue);font-size:12px}h1{font-size:38px;line-height:1.3;margin:12px 0}h2{font-size:23px;margin:0 0 14px}h3{font-size:17px;margin:0 0 8px}p{margin:10px 0}.muted,.note{color:var(--muted)}.note{font-size:12px}.section{margin:38px 0}.lead{font-size:18px;max-width:920px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}.card .label{color:var(--muted);font-size:12px}.value{font-size:27px;font-weight:650;margin:8px 0;line-height:1.3}.callout{border-left:3px solid var(--gold);background:#23231f;padding:17px 20px;border-radius:0 9px 9px 0}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}.badge{font-size:11px;border:1px solid var(--line);padding:3px 7px;border-radius:5px;white-space:nowrap}.warn{color:var(--gold)}.ok{color:var(--muted)}.pos{color:var(--up)}.neg{color:var(--down)}.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:9px}table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums}th,td{padding:11px 12px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);background:#182230}th:first-child,td:first-child{text-align:left}tr:last-child td{border-bottom:0}tbody tr:hover{background:#1c2938}td:first-child{font-weight:550}nav{display:flex;gap:22px;flex-wrap:wrap;margin-top:20px;font-size:13px}nav a{text-decoration:none}details{margin:16px 0}summary{cursor:pointer;color:var(--blue);padding:12px 0}li{margin:7px 0}code{font-size:12px;overflow-wrap:anywhere}select{background:#1b293c;color:var(--ink);padding:9px;border:1px solid var(--line);border-radius:6px;max-width:100%}.chart svg{display:block;width:100%;height:auto}.timeline{display:flex;margin:16px 0;font-size:12px}.timeline span{padding:12px 16px}.timeline span:first-child{background:#213852;flex:31}.timeline span:last-child{background:#383225;flex:13}.chart-legend{font-size:12px;display:flex;gap:20px;flex-wrap:wrap}.chart-legend b{font-weight:500}.status{margin-top:18px}footer{border-top:1px solid var(--line);padding-top:22px;color:var(--muted);font-size:12px}
@media(max-width:760px){main{padding:26px 16px}h1{font-size:29px}.cards{grid-template-columns:1fr 1fr}.grid2{grid-template-columns:1fr}.value{font-size:23px}.lead{font-size:16px}.timeline span{padding:8px}.card{padding:16px}}
@media print{body{background:white;color:#17212e}.card,.callout,th{background:#f3f5f7;color:#17212e}.scroll{overflow:visible}details>*{display:block}nav,select{display:none}main{max-width:none;padding:10px}table{font-size:9px}th,td{padding:5px}.section{break-inside:avoid}.chart{break-inside:avoid}}
</style></head><body><main>'''
    html+=f'''<header><div class="eyebrow">SKHY / HEDGE RESEARCH · AUDITED DAILY MODEL</div>
<h1>更新数据，也重审策略优势</h1><p class="lead">2 张 Put 的收益优势没有在新增区间延续。下一步应优先降低保费消耗、验证真实成交条件，再决定是否调整涨跌阈值。</p>
<p class="muted">SK 海力士 ADR · {start} → {end} · {len(stock)} 个完整交易日 · 生成于 {generated}</p>
<div class="status"><span class="badge warn">日线条件性模拟 · 同步报价权限受限</span> <span class="badge">股票与期权已全量重拉</span></div>
<nav><a href="#findings">研究结论</a><a href="#compare">方案对比</a><a href="#validation">时间验证</a><a href="#audit">口径审计</a><a href="#snapshot">最新快照</a><a href="#details">账本与复现</a></nav></header>
<div class="cards"><div class="card"><div class="label">最新完整收盘 · {end}</div><div class="value">${recent:,.2f}</div><div class="note">{len(stock)} 个交易日；日线非实时价格</div></div>
<div class="card"><div class="label">新增区间 · 同资金持股基准</div><div class="value">{pct(bh['holdout']['return_pct'])}</div><div class="note">{money(bh['holdout']['pnl'])} 美元</div></div>
<div class="card"><div class="label">新增区间 · 原参数 2 张 Put</div><div class="value">{pct(original['holdout']['return_pct'])}</div><div class="note">{money(original['holdout']['pnl'])} 美元 · 条件模拟</div></div>
<div class="card"><div class="label">新增区间 · 改为 1 张 Put</div><div class="value">{pct(one['holdout']['return_pct'])}</div><div class="note">{money(one['holdout']['pnl'])} 美元 · 条件模拟</div></div></div>
<section id="findings" class="section"><h2>01 / 这次值得保留的亮点</h2><div class="grid2">
<div class="card"><h3>1 张 Put 值得继续验证</h3><p>原参数保留跌 15%／涨 8%，仅从 2 张降到 1 张：全期盈亏由 {money(original['pnl'])} 变为 {money(one['pnl'])} 美元；新增期收益从 {pct(original['holdout']['return_pct'])} 变为 {pct(one['holdout']['return_pct'])}。</p><p class="note">上涨区间少付一份保费，代价是减少下跌保护。两方案都存在 {original['async_marks']} 个不同步估值日，不能据此直接选实盘赢家。</p></div>
<div class="card"><h3>“11% 就轮空”不是稳定优势</h3><p>真实重跑跳过规则后，全期盈亏为 {money(rr[5]['pnl'])} 美元，低于未过滤的 {money(original['pnl'])}。高保费过滤也可能跳过后来最有价值的保护。</p><p class="note">被跳过的是该到期周期的 Put；100 股继续持有，到该合约到期日才重新评估。没有事后删除股票利润。</p></div>
<div class="card"><h3>到期周期必须先确认可交易</h3><p>全量发现 {d['manifest']['n_contracts']} 个真实挂牌 Put，保存 {countbars:,} 条日线。最长测试期限定为 18–24 天，缺合约就不成交。</p><p class="note">21 天方案保护覆盖 {rr[10]['protected_pct']:.0f}%，资金不足跳过 {rr[10]['skipped']['cash']} 次；更长周期不一定降低整体保费。</p></div>
<div class="card"><h3>先买得合理，再优化阈值</h3><p>已比较 95%／90% 行权价、MA20 过滤和 ATR 阈值。MA20 方案仅有 {len(rr[11]['trades'])} 轮，不能把长时间不持有 Put 的结果解读为过滤有效。</p><p class="note">下一阶段优先补同步 Bid/Ask 与交易深度；再检验较轻的保护仓位，以及允许封顶收益时的 Collar。</p></div></div></section>
<section id="compare" class="section"><h2>02 / 同资金、同日期的方案对比</h2>
<p>所有方案首日收盘买入 100 股，另备股票成本的 50% 作为保费现金：初始总资金 <strong>${bh['initial']:,.2f}</strong>。基准也保留同额现金，避免把备用金造成的回撤稀释误当对冲效果。</p>
{comparison}<p class="note">¹ 包含期末仍持有的估值轮。² 覆盖 = 收盘持有 Put 的天数 / 总交易日，并非 Delta 覆盖。收益率分母是各期间实际期初净值；跨方案比较同时看美元盈亏。不同步 = Put 日线末价比对应股票收盘内在价值低超过 $0.05；“未发现异常”并不等于成交可实现。</p>
<div class="card chart"><label for="scenario">净值曲线 · 选择研究方案 </label><select id="scenario">{''.join(f'<option value="{i}" '+('selected' if i==1 else '')+f'>{escape(r["name"])}</option>' for i,r in enumerate(rr))}</select>
<div id="chart"></div><div class="chart-legend"><b style="color:#7fb8ff">蓝色：所选方案</b><b style="color:#9fb0c5">灰色：同资金持股基准</b><b style="color:#f5cb80">虚线：旧报告数据截止日</b></div><p id="chart-note" class="note"></p></div></section>
<section id="validation" class="section"><h2>03 / 时间切分：不拿新增区间选参数</h2>
<div class="timeline"><span>开发区间 · {start} → {BOUNDARY}<br>{ntrain} 个交易日</span><span>新增区间 · 2026-08-25 → {end}<br>{ntest} 个交易日</span></div>
<p>全组合扫描 4 个目标期限 × 7 个下跌阈值 × 7 个上涨阈值 × 2 种张数，共 {len(analysis['grid'])} 组；只按开发区间的净收益 / 美元最大回撤选择，新增区间保留已有持仓继续计算。</p>
<div class="callout"><strong>严格数据筛选后的选择：{escape(analysis['selected'])}</strong><p>{clean_text}</p><p>因此，本次研究没有给出经过验证的“最优对冲参数”。下面的高收益参数仍受估值异常影响。</p></div>
<details><summary>查看训练期前 12 名及其数据异常</summary>{scan}</details>
<details><summary>查看完整涨跌阈值矩阵：2 张 Put／目标 2 天</summary>{matrix}<p class="note">美元全期盈亏。† 有估值缺失或不同步，仅供探索；完整 392 组扫描见 results.json。</p></details>
<h3>滚动时间验证</h3>{walk}<p class="note">每个训练截止日重新比较 72 个稀疏参数组合与持股基准，只用当时及以前数据；次日开启一个独立资金账户，在后续最多 5 个交易日验证。各段重新建仓、计入股票交易成本，不拼接为一个连续策略收益。窗口短且可能没有足够交易。</p>
<p class="note">这是今天重建的历史时间切分，不是真正事前登记的样本外实验。新增区间仅 {ntest} 天，参数族和模型设计也可能包含研究者事后选择，尚不足以估计稳定年化收益或统计显著性。</p>
<h3>滑点敏感性</h3>{sensitivity}<p class="note">³ 每次 Put 买卖在日线末价基础上加/减比例滑点，最低 $0.01/股；每张每边佣金 $0.65。0% 行仍保留最低一分钱价差和佣金，故不是零摩擦。表中结果仍受同步价格缺失影响。</p></section>
<section id="audit" class="section"><h2>04 / 为什么不能沿用旧报告的“最优”结论</h2>
<div class="grid2"><div class="card"><h3>修正资金与回撤</h3><p>旧净值只计股票和累计 Put 现金流，买入 Put 后漏计资产价值。新净值逐日等于股票市值＋现金＋Put 市值；百分比回撤按各日当时历史峰值计算。</p><p class="note">备用金可耗尽，资金不足就跳过新仓。股票首日交易摩擦 5 bps；不计现金利息、税费和股息，所以本报告为价格回报而非含分红总回报。</p></div>
<div class="card"><h3>修正信号与执行时间</h3><p>旧程序用开盘触发却按全天 VWAP 成交。新版用前一交易日收盘形成信号和候选合约，在下一交易日用日线末价加交易摩擦模拟成交。</p><p class="note">这改变了策略的执行语义，不能将差异全部归因于行情更新；日线末价也不等于同步收盘可成交报价，故仍属条件模拟。</p></div>
<div class="card"><h3>修正数据完整性与路径</h3><p>按历史 as_of 日期发现合约，不再猜行权价间隔。持仓即使远离平值仍保存完整历史，包括到期日。股票和期权用同一股票行情生成快照。</p><p class="note">旧缓存 09-04 的 spot 为 170.23、股票收盘为 177；09-11 分别为 189.90 和 190.07。新数据独立保存在当前 sk/data，避免覆盖其他策略共享缓存。报告输出回当前 sk 目录。</p></div>
<div class="card"><h3>不再把缺失价格当成可成交</h3><p>缺卖出价时保留仓位、推迟卖出；缺每日估值时，仅用前次价格与内在价值较高者作显式估计，并排除该参数的排名资格。</p><p class="note">到期用内在价值结算作等价现金处理，模拟行权后买回交付股票以维持 100 股；计每张 $1 行权成本及买回股票的 5 bps 摩擦。未模拟提前行权、结算资金等待及借券限制。</p></div></div>
<h3>实际发现的不同步价格</h3>{anomalies}
<p>例如，股票收盘对应的内在价值与 Put 日线末价相差较大，会直接扭曲每日净值。历史收盘报价接口本次请求返回 <strong>HTTP 403</strong>，当前账户无法完成同步 Bid/Ask 复核；没有用理论期权价格冒充真实成交。</p>
<p class="note">日线成交聚合只在发生合格交易时生成，VWAP 是成交量加权均价，详见 <a href="https://massive.com/docs/rest/options/aggregates/custom-bars">Massive 期权日线文档</a>；报价字段见 <a href="https://massive.com/docs/rest/options/quotes">历史 Quotes 文档</a>。</p></section>
<section id="snapshot" class="section"><h2>05 / 最新数据快照，不是下单指令</h2>
<p>截至 {end}，股票收盘 <strong>${recent:.2f}</strong>，MA20 <strong>${ma[end]:.2f}</strong>，14 日简单平均真实波幅 / 收盘价 <strong>{atr[end]:.2f}%</strong>。以下选同日最接近收盘价的挂牌 Put。</p>
{latest}<p class="note">裸保费未含价差和佣金；全天成交量不能保证拟交易时点的深度。所有报价属于 {end}，不是当前盘口。近期长仓参考阈值还取决于实际入场股价，所以不把这张快照当作已经触发的交易信号。</p>
<div class="callout"><strong>优化优先级</strong><ol><li>补 09:30 后和收盘前的同步股票／期权 Bid/Ask，用买 Ask、卖 Bid 重跑原开盘规则与新版规则。</li><li>先比较 1 张 ATM 与 1 张轻度虚值 Put 的保护效果和保费，再调整涨跌滚动阈值；保费预算与最大允许裸露风险一起确定。</li><li>如允许牺牲部分上涨收益，再单独回测 Collar（买 Put＋备兑卖 Call）；本次只刷新 Put，尚未验证 Collar 收益。</li><li>冻结一组规则，积累更多独立滚动周期后再看回撤、保费支出及成交成本；不要用 44 天样本给出稳定最优结论。</li></ol></div>
<p class="note">保护性 Put 的保费会削减上涨收益，行权价决定保护起点，参见 <a href="https://prd-web.optionseducation.org/strategies/all-strategies/protective-put-married-put">OIC 保护性 Put</a>；Collar 用备兑 Call 收入抵付部分 Put 成本并限制上涨空间，参见 <a href="https://prd-web.optionseducation.org/news/july-webinar-key-takeaways-protecting-a-your-stock-position">OIC 股票仓位保护说明</a>。</p></section>
<section id="details" class="section"><h2>06 / 逐笔账本与可复现结果</h2>
<p>原参数／修正执行的全期盈亏 {money(original['pnl'])} 美元 = 股票净损益 {money(original['stock_pnl'])} ＋ Put 净损益 {money(original['put_pnl'])}。账本对账残差 {original['reconciliation']:.8f} 美元。</p>
<details><summary>展开 {len(original['trades'])} 轮 Put 明细</summary>{trade_table}<p class="note">期末持有行的“收入”为市值，没有模拟出售；各轮只列 Put 损益。100 股全程损益另计，避免把轮次之间的股票利润漏掉或重复统计。</p></details>
<details><summary>展开逐日股票、现金与 Put 市值</summary>{ledger}</details>
<p><a href="results.json">完整结果 JSON</a> · <a href="data/refresh_manifest.json">数据刷新清单</a> · <a href="README.md">复现说明</a></p>
<p class="note">Python 3.9+；联网刷新：<code>python3 refresh_data.py</code>（环境变量提供 API Key）；离线生成：<code>python3 gen_final_report.py</code>；验证：<code>python3 -m unittest -v test_backtest.py</code>。报告与 JSON 不依赖外部 JS/CDN。</p></section>
<footer>数据拉取时间：{escape(d['manifest']['fetched_at_utc'])} · {d['manifest']['n_contracts']} 个历史合约 · {countbars:,} 条 Put 日线。<br>
股票正式常规交易起于 2026-07-13；7 月 10 日为 SKHYV when-issued 交易，参见 <a href="https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2026-37">Nasdaq 交易通知</a>。本报告评估回测模型与历史风险收益，不提供即时买卖建议。</footer>'''
    chart_data=json.dumps([dict(name=r['name'],curve=r['curve'],initial=r['initial'],
                               missing=r['missing_marks'],async_days=r['async_marks']) for r in rr],ensure_ascii=False).replace('</','<\\/')
    html+='''<script>
const data=CHART_DATA;
const selector=document.getElementById('scenario');
function draw(){
 const idx=Number(selector.value),a=data[idx],b=data[0],W=1120,H=360,L=64,R=1096,T=28,B=318;
 const series=[a,b].map(x=>x.curve.map(v=>100*v.equity/x.initial));
 let low=Math.floor((Math.min(...series.flat())-3)/5)*5,high=Math.ceil((Math.max(...series.flat())+3)/5)*5;
 const x=i=>L+(R-L)*i/(a.curve.length-1),y=v=>B-(v-low)/(high-low)*(B-T);
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="按初始资金100归一化的逐日净值">`;
 for(let j=0;j<=5;j++){const v=low+(high-low)*j/5;s+=`<line x1="${L}" y1="${y(v)}" x2="${R}" y2="${y(v)}" stroke="#293647"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end" fill="#9fb0c5" font-size="12">${v.toFixed(0)}</text>`;}
 const cut=a.curve.findIndex(v=>v.date==='2026-08-24');
 if(cut>=0)s+=`<line x1="${x(cut)}" y1="${T}" x2="${x(cut)}" y2="${B}" stroke="#f5cb80" stroke-dasharray="4 5"/><text x="${x(cut)+8}" y="${T+12}" fill="#f5cb80" font-size="11">新增区间 →</text>`;
 [1,0].forEach(j=>{const c=j===0?'#7fb8ff':'#9fb0c5';s+=`<polyline points="${series[j].map((v,i)=>`${x(i)},${y(v)}`).join(' ')}" fill="none" stroke="${c}" stroke-width="2.4"/>`;});
 a.curve.forEach((v,i)=>{if(i%7===0||i===a.curve.length-1)s+=`<text x="${x(i)}" y="${B+23}" text-anchor="middle" fill="#9fb0c5" font-size="11">${v.date.slice(5)}</text>`;s+=`<circle cx="${x(i)}" cy="${y(series[0][i])}" r="5" fill="transparent"><title>${v.date} · ${a.name} $${v.equity.toFixed(2)} · 基准 $${b.curve[i].equity.toFixed(2)}</title></circle>`;});
 document.getElementById('chart').innerHTML=s+'</svg>';
 document.getElementById('chart-note').textContent=`初始资金归一为100。${a.name}：缺失估值 ${a.missing} 天，不同步 ${a.async_days} 天。曲线是日线条件模拟。`;
}
selector.addEventListener('change',draw);draw();
</script></main></body></html>'''.replace('CHART_DATA',chart_data)
    tmp=out.with_suffix('.html.tmp');tmp.write_text(html);tmp.replace(out)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-dir',type=Path,default=ROOT/'data')
    ap.add_argument('--output',type=Path,default=ROOT/'skhy_final_report.html')
    args=ap.parse_args()
    d=json.loads((args.data_dir/'SKHY_put_history.json').read_text())
    analysis=compute(d)
    atomic_json(args.output.parent/'results.json',dict(manifest=d['manifest'],boundary=BOUNDARY,**analysis))
    render(d,args.output,analysis)
    print('Report:',args.output)
    print('Strict training selection:',analysis['selected'])
    for r in analysis['results'][:3]:
        print(r['name'], 'pnl=',round(r['pnl'],2),'mdd%=',round(r['mdd_pct'],2),
              'holdout pnl=',round(r['holdout']['pnl'],2))


if __name__=='__main__':
    main()
