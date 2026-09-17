import math
def money(x):return f'${x:,.2f}'
def pct(x):return f'{x:.2f}%'
def table(headers,rows):
 return '<div class="tbl-scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def section(title,body,ident):return f'<section class="card" id="{ident}"><h2>{title}</h2>{body}</section>'
def chart(a,b):
 vals=[[r['equity']/x['initial']*100 for r in x['curve']] for x in (a,b)]
 lo=math.floor(min(map(min,vals))/10)*10-10;hi=math.ceil(max(map(max,vals))/10)*10+10
 y=lambda v:270-(v-lo)/(hi-lo)*245
 out=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 320" role="img" aria-label="两个策略同本金净值"><title>策略1与策略2净值</title>']
 for j in range(6):
  v=lo+(hi-lo)*j/5
  out.append(f'<line x1="60" x2="970" y1="{y(v):.2f}" y2="{y(v):.2f}" stroke="#303645"/><text x="50" y="{y(v)+4:.2f}" fill="#aaa" text-anchor="end" font-size="12">{v:.0f}</text>')
 for vv,col in zip(vals,['#f5c344','#4da3ff']):
  pts=' '.join(f'{60+i*910/(len(vv)-1):.2f},{y(v):.2f}' for i,v in enumerate(vv))
  out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5"/>')
 for i in (0,10,20,30,len(vals[0])-1):
  out.append(f'<text x="{60+i*910/(len(vals[0])-1):.2f}" y="300" fill="#aaa" text-anchor="middle" font-size="12">{a["curve"][i]["date"][5:]}</text>')
 return ''.join(out)+'</svg><p>金：策略1（10 Call＋10 Put）；蓝：策略2（100股＋2 Put）。同初始本金归一化为100，包含现金及未平仓资产市值。</p>'
