const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path'),p=__dirname;
const html=fs.readFileSync(path.join(p,'skhy_report5_exit_optimization.html'),'utf8'),code=html.match(/<script>([\s\S]*)<\/script>/)[1];
const elements=new Map();function el(id){if(!elements.has(id)){let text='',e={value:'',style:{},getBoundingClientRect:()=>({width:1200,left:0}),getContext:()=>new Proxy({},{get:()=>()=>{}})};Object.defineProperty(e,'innerHTML',{get:()=>text,set:v=>{text=v;let m=v.match(/<option value="([^"]*)"/);if(m)e.value=m[1]}});elements.set(id,e)}return elements.get(id)}
const c={document:{getElementById:el},window:{addEventListener:()=>{}},devicePixelRatio:1,console};vm.createContext(c);vm.runInContext(code,c);const data=vm.runInContext('D',c);
for(const r of data.results){el('policy').value=r.id;el('policy').onchange();assert(el('ledger').innerHTML.includes('买入时间'));for(let i=0;i<r.trades.length;i++){el('trade').value=String(i);el('trade').onchange();el('tradechart').onmousemove({clientX:400});assert(el('tradetip').innerHTML.includes('组合毛收益'))}}
el('equity').onmousemove({clientX:700});assert(el('equitytip').innerHTML.includes('E00'));assert(el('ranking').innerHTML.includes('强平时间'));assert(data.results.length===44);
console.log('PASS: all 44 strategy selectors, trade plots, equity hover, forced-exit tables and two-axis charts execute');
