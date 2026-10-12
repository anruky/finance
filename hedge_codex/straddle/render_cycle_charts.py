import os,json
from pathlib import Path
from datetime import datetime
os.environ.setdefault('MPLCONFIGDIR','/tmp/skhy_weekly_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
root=Path(__file__).resolve().parent;d=json.loads((root/'skhy_weekly_cycles.json').read_text());slots={0:0,3:1,4:2,5:3,6:4,7:5}
for c in d['cycles']:
 def x(t):
  diff=(datetime.fromisoformat(t[:10])-datetime.fromisoformat(c['start'])).days
  return slots[diff]+(int(t[11:13])*60+int(t[14:16])-570)/390*.92
 fig,axes=plt.subplots(2,1,figsize=(15,7),dpi=140,sharex=True);fig.patch.set_facecolor('#f3f6fa')
 for ax,field,title in zip(axes,['pnl','stock'],['Combined P&L (USD, before costs)','Stock price (USD/share)']):
  for r in c['candles']:
   v=r[field]
   if not v:continue
   xx=(x(r['start'])+x(r['end']))/2;color='#079780' if v['c']>=v['o'] else '#d95b6e'
   ax.vlines(xx,v['l'],v['h'],color=color,lw=.7)
   if v['o']==v['c']:ax.hlines(v['c'],xx-.008,xx+.008,color=color,lw=.9)
   else:ax.add_patch(Rectangle((xx-.008,min(v['o'],v['c'])),.016,abs(v['c']-v['o']),color=color))
  ax.set_title(title,loc='left',fontsize=11);ax.grid(axis='y',alpha=.2);ax.set_xlim(0,6)
  if field=='pnl':ax.axhline(0,color='gray',ls='--',lw=.7)
  for i in range(6):ax.axvline(i,color='#c5ced9',lw=.6)
 axes[-1].set_xticks([i+.46 for i in range(6)],['Entry Fri','Mon','Tue','Wed','Thu','Expiry Fri']);axes[-1].set_xlabel('ET 09:30–16:00 each day; holidays / future sessions blank')
 fig.suptitle('SKHY 100 shares + 2 puts | '+c['label']+(' (ongoing)' if not c['completed'] else '')+'\n10-minute candles from synchronized completed-minute close marks',fontsize=14)
 fig.tight_layout(rect=[0,0,1,.92]);fig.savefig(root/('cycle_'+c['id']+'.png'));plt.close(fig)
print('Rendered',len(d['cycles']),'dual charts')
