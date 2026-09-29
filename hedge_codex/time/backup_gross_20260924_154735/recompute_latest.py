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
(p/'report3_summary.md').write_text(f'''# 最新报告3：全部已到期周期训练

[查看报告](skhy_report3_all6_time_decay.html)

行情截至美东{end}，共{len(d['cycles'])}个周期，{N}个已到期周期全部训练，未到期周期仅展示。

持有到期总净收益：${d['comparison']['baseline']['pnl']:,.2f}。
固定涨跌不同目标最高总净收益：${d['comparison']['asymmetric']['pnl']:,.2f}。
时间递减目标最高总净收益：${d['comparison']['decay_asymmetric']['pnl']:,.2f}。

时间递减候选：{d['selected']['decay_asymmetric']['name']}。

19,977组规则，所有结果均为样本内比较。标准示例摩擦每腿买入+2%、卖出−2%，每张每次$0.65；不能保证实际成交。
''')
(p/'README_all6.md').write_text(f'''# 最新周期策略研究

数据截至美东{end}，{len(d['cycles'])}轮中{N}轮已到期，全部参与训练；未到期轮仅展示。沿用19,977条候选、摩擦与执行口径。

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
