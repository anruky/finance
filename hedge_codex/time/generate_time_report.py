# -*- coding: utf-8 -*-
"""Historical 10-minute replay for the fixed Sep 4 position; not a live poller."""
import json,math,os,hashlib,argparse
from pathlib import Path
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
os.environ.setdefault('MPLCONFIGDIR','/tmp/skhy_time_matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ET=ZoneInfo('America/New_York');CN=ZoneInfo('Asia/Shanghai')
TICKER='O:SKHY260911P00170000'
DEST=Path('/Users/gavinz/git/finance/hedge_codex/sk/time')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--dir',type=Path,default=Path(__file__).resolve().parent);args=ap.parse_args();out=args.dir
 raw=json.loads((out/'market_data.json').read_text())
 def bars(t):return {datetime.fromtimestamp(b['t']/1000,ET):b for b in raw[t+'_minute'] if b.get('v',0)>0}
 stocks,puts=bars('SKHY'),bars(TICKER)
 daily={datetime.fromtimestamp(b['t']/1000,ET).date().isoformat():b for b in raw['SKHY_day']}
 pdaily={datetime.fromtimestamp(b['t']/1000,ET).date().isoformat():b for b in raw[TICKER+'_day']}
 entry=datetime(2026,9,4,10,0,tzinfo=ET);S0=stocks[entry]['o'];P0=puts[entry]['o'];cost=100*S0+200*P0
 def last_completed(mapping,stamp):
  keys=[k for k in mapping if k.date()==stamp.date() and k.time()>=time(9,30) and k+timedelta(minutes=1)<=stamp]
  if not keys:return None,None,None
  k=max(keys);return mapping[k]['c'],k,int((stamp-k).total_seconds()/60)
 rows=[]
 for dt in sorted(daily):
  day=datetime.fromisoformat(dt).replace(tzinfo=ET)
  start=entry if dt=='2026-09-04' else day.replace(hour=9,minute=30)
  stamp=start
  while stamp<=day.replace(hour=16):
   kind='last_completed';age=None;ps=None;ss=None
   if stamp==entry:
    S,P=S0,P0;kind='entry_proxy';ps=ss=entry;age=0
   elif stamp.hour==16:
    S=daily[dt]['c'];P=max(170-S,0) if dt=='2026-09-11' else pdaily[dt]['c'];kind='expiry_review' if dt=='2026-09-11' else 'close_review'
   else:
    S,ss,_=last_completed(stocks,stamp);P,ps,age=last_completed(puts,stamp)
   stock_pnl=100*(S-S0) if S is not None else None
   put_pnl=200*(P-P0) if P is not None else None
   gross=stock_pnl+put_pnl if stock_pnl is not None and put_pnl is not None else None
   # Illustrative friction only, not the user's actual broker charges or a spread model.
   fee=100*S0*.0005+1.3+(100*S*.0005 if S is not None else 0)+(0 if kind=='expiry_review' else 1.3)
   net=gross-fee if gross is not None else None
   status='入场基准（分钟首笔）' if kind=='entry_proxy' else '到期复核／Put内在价值' if kind=='expiry_review' else '日线收盘复核' if kind=='close_review' else '缺当日已完成分钟' if gross is None else ('旧价 '+str(age)+'m' if age>10 else str(age)+'m')
   rows.append(dict(et=stamp.isoformat(),beijing=stamp.astimezone(CN).isoformat(),kind=kind,stock_price=S,put_price=P,stock_return_pct=100*(S/S0-1) if S is not None else None,
    stock_pnl=stock_pnl,put_pnl=put_pnl,gross_pnl=gross,illustrative_net_pnl=net,put_bar_start=ps.isoformat() if ps else None,put_age_upper_minutes=age,status=status))
   stamp+=timedelta(minutes=10)
 # Persist an audit-friendly ledger; no secrets in this file.
 valid=[r for r in rows if r['gross_pnl'] is not None];regular=[r for r in valid if r['kind']=='last_completed'];fresh=[r for r in regular if r['put_age_upper_minutes']<=10]
 peak=max(regular,key=lambda r:r['gross_pnl']);low=min(regular,key=lambda r:r['gross_pnl']);final=rows[-1]
 stale=sum(r['kind']=='last_completed' and r['put_age_upper_minutes'] is not None and r['put_age_upper_minutes']>10 for r in rows)
 audit=dict(entry=dict(et=entry.isoformat(),beijing=entry.astimezone(CN).isoformat(),stock_price=S0,put_price=P0,stock_shares=100,put_contracts=2,multiplier=100,strike=170,expiry='2026-09-11',gross_cost=cost),source_fetched_at=raw['fetched_at_utc'],source_sha256=hashlib.sha256((out/'market_data.json').read_bytes()).hexdigest(),quote_access=raw['quote_access'],rows=rows)
 (out/'skhy_10min_pnl.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False))
 # Continuous trading-time index: overnight periods intentionally omitted.
 fig,ax=plt.subplots(figsize=(14,6.5),dpi=150);fig.patch.set_facecolor('#f7f8fb');ax.set_facecolor('#ffffff')
 xs=list(range(len(rows)))
 val=lambda k:[r[k] if r[k] is not None else float('nan') for r in rows]
 ax.plot(xs,val('stock_pnl'),color='#2874b2',alpha=.6,lw=1.4,label='100 shares P&L')
 ax.plot(xs,val('put_pnl'),color='#8a63b8',alpha=.6,lw=1.4,label='2 puts P&L')
 ax.plot(xs,val('gross_pnl'),color='#13856b',lw=2.3,label='Combined P&L (before costs)')
 aged=[i for i,r in enumerate(rows) if r['kind']=='last_completed' and r['put_age_upper_minutes'] is not None and r['put_age_upper_minutes']>10 and r['gross_pnl'] is not None]
 ax.scatter(aged,[rows[i]['gross_pnl'] for i in aged],facecolors='none',edgecolors='#dc9127',s=24,label='Put last trade >10 min old',zorder=4)
 ticks=[];labels=[]
 for i,r in enumerate(rows):
  dt=r['et'][:10]
  if i==0 or dt!=rows[i-1]['et'][:10]:ticks.append(i);labels.append(dt[5:]);ax.axvline(i,color='#d9dde5',lw=.8)
 ax.axhline(0,color='#777',lw=.9,linestyle='--');ax.set_xticks(ticks,labels);ax.set_ylabel('Unrealized / hypothetical exit P&L (USD)');ax.set_xlabel('2026 US trading dates; 10-minute samples, overnight gaps omitted')
 ax.set_title('SKHY: 100 shares + 2 Sep 11 $170 puts\nEntry Sep 4, 10:00 ET | last-trade estimates, not executable quotes',fontsize=13,pad=16)
 ax.grid(axis='y',alpha=.18);ax.legend(loc='upper left',fontsize=9);fig.tight_layout()
 fig.savefig(out/'skhy_10min_pnl.png');plt.close(fig)
 m=lambda v:'—' if v is None else f'${v:,.2f}'
 signed=lambda v:'—' if v is None else f'${v:+,.2f}'
 stamp_cn=lambda r:datetime.fromisoformat(r['beijing']).strftime('%m-%d %H:%M')
 md=f'''# SKHY 100股＋2张平值Put：每10分钟收益回放

> 按 `brd_gav.md` 生成。日期按当前项目解释为 **2026年9月4日至9月11日**，这是已结束持仓的历史回放，不是当前实时行情，也不是已启动的每10分钟定时监控。

## 持仓与入场假设

| 项目 | 本报告采用值 |
| --- | ---: |
| 入场北京时间 | 2026-09-04 22:00（UTC+8） |
| 入场美东时间 | 2026-09-04 10:00（EDT，UTC−4） |
| 股票 | SKHY，100股 |
| 股票入场估算价 | ${S0:.4f}/股 |
| Put | `{TICKER}` |
| 行权价／到期 | $170／2026-09-11 |
| Put数量与乘数 | 2张，每张100股 |
| Put入场估算价 | ${P0:.2f}/股，即每张${P0*100:,.2f} |
| 股票本金 | {m(100*S0)} |
| 两张Put权利金 | {m(200*P0)} |
| 合计初始投入（未计费用） | **{m(cost)}** |

“0 OTM”按接近平值理解：入场估算股价${S0:.2f}，选$170档。缺少你的实际成交回单，入场用股票与Put各自10:00分钟首笔价，不能保证两笔发生在同一秒或与你的实际成交价一致。本报告持有原股票和原Put至到期，期间不滚动、不追加、不触发前面策略报告中的涨跌熔断。

## 先看结果

| 项目 | 股票损益 | 2张Put损益 | 组合损益（未计费用） |
| --- | ---: | ---: | ---: |
| 到期收盘复核 | {signed(final['stock_pnl'])} | {signed(final['put_pnl'])} | **{signed(final['gross_pnl'])}** |
| 十分钟采样内组合最高点：北京时间 {stamp_cn(peak)} | {signed(peak['stock_pnl'])} | {signed(peak['put_pnl'])} | {signed(peak['gross_pnl'])} |
| 十分钟采样内组合最低点：北京时间 {stamp_cn(low)} | {signed(low['stock_pnl'])} | {signed(low['put_pnl'])} | {signed(low['gross_pnl'])} |

到期收盘复核股票价为{m(final['stock_price'])}，高于$170行权价，Put到期内在价值为0。组合毛收益率为 **{100*final['gross_pnl']/cost:.2f}%**（不年化）。若按下述示例摩擦估算，期末净收益约 **{signed(final['illustrative_net_pnl'])}**。

最高点和最低点只是采样值，不是全天真实极值，更不是事前能够选中的最佳平仓点；陈旧期权成交价也可能影响这些读数。详见每行价格状态。

## 组合收益趋势

![SKHY每10分钟持仓收益趋势]({DEST/'skhy_10min_pnl.png'})

绿色为组合毛收益，蓝色为100股收益，紫色为两张Put收益。横轴压缩了休市时段，橙色空心点表示Put最新已知成交分钟距采样点超过10分钟；缺当日行情处断线。最后一天收盘点用Put到期内在价值，不把最后一笔$0.01成交价当作到期残值。

## 计算方法与价格可信度

- 股票收益＝100×（观察股价−${S0:.4f}）；股票波动＝观察股价÷${S0:.4f}−1。
- 期权收益＝200×（观察Put单价−${P0:.2f}）；“Put单价”是每股报价，“Put损益”是两张合计损益。
- 组合毛收益＝股票收益＋期权收益。这是持仓估值／假设按这些价格平仓的损益，不是已兑现利润。
- 示例净收益＝毛收益−股票买入和卖出各5bps−两张Put每次每张$0.65佣金。到期虚值归零不扣卖Put佣金。未计实际Bid/Ask价差、税费及真实券商收费，因此不是保证可成交的净收益。入场行“示例净收益”表示立即往返的假设摩擦，不表示已经平仓。
- 普通采样点只读取该点之前已结束的当日常规时段分钟K线，取最新一笔成交分钟的收盘价。例如10:10不读取10:10–10:10:59的未来分钟，也不向后找成交。若Put刚好没交易，沿用截至当时的最新已知成交价并显示其陈旧程度；超过10分钟仍展示为估值，不能冒充新报价。
- “价格状态”中的`Nm`为采样时间与Put成交分钟起点的间隔上界，不是逐笔成交的精确秒级年龄。开盘9:30尚无已完成的当日常规分钟时记为缺失，不跨夜填补。
- 每日16:00另列**事后日线收盘复核点**，不声称日线收盘结果在16:00整已可即时获得。9月11日该点按到期内在价值复核Put；此前收盘点仍用日线成交末价。
- 本次重新拉取股票、Put分钟及日线数据；历史Bid/Ask查询结果：`{raw['quote_access']}`。因此无法验证在采样时刻卖股票和两张Put的真实可成交买价及深度。

共 **{len(rows)}个时间点**（含入场和每日收盘复核）；{len(rows)-len(valid)}个点缺当日已完成行情；{stale}个普通采样点使用超过10分钟的Put旧价。9月5、6日为周末，9月7日Labor Day休市，因此交易日期为9月4、8、9、10、11日。美东09:30–16:00对应北京时间当日21:30至次日04:00。

## 每10分钟明细

每行都假设原持仓仍在，展示在该点估值或假设平仓的累计收益，**不是每10分钟实际卖出再买入**。下列时间同时保留北京时间和美东时间，股票价格保留4位以便复核计算。

'''
 for dt in sorted(daily):
  md+=f'### 美东 {dt}\n\n| 北京时间 | 美东时间 | 股票价 | 股价波动 | 股票损益 | Put单价 | 2Put损益 | 组合毛收益 | 示例净收益 | Put价格状态 |\n| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n'
  for r in rows:
   if r['et'][:10]!=dt:continue
   sp='—' if r['stock_price'] is None else f"${r['stock_price']:.4f}"
   ch='—' if r['stock_return_pct'] is None else f"{r['stock_return_pct']:+.2f}%"
   md+='| '+' | '.join([stamp_cn(r),r['et'][11:16],sp,ch,signed(r['stock_pnl']),m(r['put_price']),signed(r['put_pnl']),signed(r['gross_pnl']),signed(r['illustrative_net_pnl']),r['status']])+' |\n'
  md+='\n'
 md+=f'''## 数据与复现

- 数据服务：Polygon/Massive，抓取时间UTC `{raw['fetched_at_utc']}`。股票和期权均为实际历史聚合成交数据，不使用理论期权定价。
- [市场休市日历](https://www.nyse.com/trade/hours-calendars)：2026年9月7日休市。
- [数据服务关于缺失聚合K线的说明](https://massive.com/knowledge-base/article/why-are-there-missing-aggregates-in-massives-data)：无合格成交时可能不生成分钟K线，缺K线不等于当时没有买卖报价。
- [原始行情]({DEST/'market_data.json'})；[完整计算账本]({DEST/'skhy_10min_pnl.json'})；[生成程序]({DEST/'generate_time_report.py'})。
- 复现：在time目录执行 `python3 -B generate_time_report.py`。图片与Markdown同目录保存；未创建任何定时任务。
'''
 (out/'skhy_20260904_0911_10min_report.md').write_text(md)
 assert len(rows)==197
 for r in valid:assert abs(r['gross_pnl']-r['stock_pnl']-r['put_pnl'])<1e-8
 for r in regular:
  assert datetime.fromisoformat(r['put_bar_start'])+timedelta(minutes=1)<=datetime.fromisoformat(r['et'])
 assert final['put_price']==0 and abs(final['gross_pnl']-938)<1e-6
 print(json.dumps(dict(points=len(rows),missing=len(rows)-len(valid),stale=stale,entry_cost=cost,final=final,peak=peak,low=low),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
