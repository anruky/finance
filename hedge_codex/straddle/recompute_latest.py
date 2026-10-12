from pathlib import Path
import subprocess,sys,shutil,json
p=Path(__file__).parent
subprocess.run([sys.executable,'-B',str(p/'generate_report2.py')],check=True)
inp=p/'report3_inputs';inp.mkdir(exist_ok=True)
for n in ['report2_market_data.json','skhy_report2_cycles.json']:shutil.copy2(p/n,inp/n)
subprocess.run([sys.executable,'-B',str(p/'analyze_all6.py')],check=True)
subprocess.run([sys.executable,'-B',str(p/'verify_all6.py')],check=True)
subprocess.run([sys.executable,'-B',str(p/'build_all6.py')],check=True)
d=json.loads((p/'all6_optimization.json').read_text());N=len(d['training_ids']);end=d['metadata']['end']
(p/'README_all6.md').write_text(f'''# 最新周期策略研究

数据截至美东{end}，{len(d['cycles'])}轮中{N}轮已到期，全部参与训练；未到期轮仅展示。沿用19,977条候选、毛收益与原执行口径。

刷新与复现：
```sh
python3 -B refresh_latest.py
python3 -B recompute_latest.py
```

refresh_latest.py复用已确认的旧合约和旧已到期数据，只增量下载新周期及未完整周期；download_cache保存下载缓存。API密钥读取现有数据程序，不写入报告。recompute_latest.py先生成报告2账本，再更新report3_inputs快照，重算排名、验证、生成报告3。

无需网络的重算：analyze_all6.py → verify_all6.py → build_all6.py。

全部已到期周期均用于选参，不保留验证集。策略结果是样本内最优，不保证未来最优。期权价已包含时间价值，不额外重复扣Theta。
''')
(p/'README_report3.md').write_text('# 当前报告3\n\n已更新到最新完整交易日，全部已到期周期训练。参见[复现说明](README_all6.md)与[当前报告](skhy_report3_all6_time_decay.html)。\n')
print('UPDATE_READY',end,N,len(d['cycles']),flush=True)
