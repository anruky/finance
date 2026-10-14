const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path'),p=__dirname;
const html=fs.readFileSync(path.join(p,'skhy_report5_exit_optimization.html'),'utf8'),code=html.match(/<script>([\s\S]*)<\/script>/)[1],elements=new Map();
function el(id){if(!elements.has(id)){let text='',e={value:'',style:{},getBoundingClientRect:()=>({width:1200,left:0}),getContext:()=>new Proxy({},{get:()=>()=>{}})};Object.defineProperty(e,'innerHTML',{get:()=>text,set:v=>{text=v;let m=v.match(/<option value="([^"]*)"/);if(m)e.value=m[1]}});elements.set(id,e)}return elements.get(id)}
const c={document:{getElementById:el},window:{addEventListener:()=>{}},devicePixelRatio:1,console};vm.createContext(c);vm.runInContext(code,c);const D=vm.runInContext('D',c);
assert(D.comparison.length===44);assert(D.latest.selected_rule_id===D.best);assert(!html.includes('id="policy"'));assert((html.match(/<section\b/g)||[]).length===2);
assert(el('ledger').innerHTML.includes('买入ET'));assert(el('comparison').innerHTML.includes('E43'));assert(el('latestDate').textContent.includes(D.latest.data_end));assert(el('selectionDate').textContent.includes(D.selection_end));
for(let i=0;i<D.latest.result.trades.length;i++){el('trade').value=String(i);el('trade').onchange();el('tradechart').onmousemove({clientX:400});assert(el('tradetip').innerHTML.includes('组合毛收益'))}
el('equity').onmousemove({clientX:700});assert(el('equitytip').innerHTML.includes('最优策略累计毛收益'));assert(!D.latest.result.rule.name.includes('OTM'));
console.log('PASS: exactly two report sections; frozen 44-rule comparison; selected strategy only; all round charts and hover handlers');
