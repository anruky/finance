import os,json
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/skhy_exit3_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path(__file__).parent;d=json.loads((p/'exit_optimization.json').read_text())
fig,ax=plt.subplots(figsize=(13,4.5),dpi=140);fig.patch.set_facecolor('#171e2c');ax.set_facecolor('#171e2c')
for key,color,label in [('baseline','#ffd166','Hold to expiration'),('train_selected','#43caaa','Training-selected rule'),('full_sample_best','#b794f4','Full-sample best (hindsight)')]:ax.plot(range(6),[r['pnl'] for r in d['selected_results'][key][:6]],color=color,marker='o',lw=2,label=label)
ax.axhline(0,color='#738398',ls='--',lw=1);ax.axvspan(3.5,5.4,color='#38bdf8',alpha=.07);ax.set_xticks(range(6),[c['start'][5:] for c in d['cycles'][:6]],color='#e7edf7');ax.tick_params(colors='#9cabbe');ax.set_ylabel('Net P&L per cycle (USD)',color='#9cabbe');ax.set_xlabel('Entry Friday | final two cycles are retrospective validation',color='#9cabbe');ax.set_title('SKHY 1 Call + 1 Put | 2% entry/exit friction + $0.65 per contract per side',color='#e7edf7',pad=15);ax.grid(axis='y',alpha=.12);ax.legend(facecolor='#202a3b',edgecolor='#2b3546',labelcolor='#e7edf7',fontsize=9,loc='upper left')
for spine in ax.spines.values():spine.set_color('#2b3546')
fig.tight_layout();fig.savefig(p/'exit_strategy_comparison.png');plt.close(fig)
