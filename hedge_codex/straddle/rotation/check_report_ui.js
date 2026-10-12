const fs=require('fs'),vm=require('vm'),assert=require('assert');
const path=require('path'),base=__dirname;
const html=fs.readFileSync(path.join(base,'skhy_report4_rotation.html'),'utf8');
const code=html.match(/<script>([\s\S]*)<\/script>/)[1];
const elements=new Map();
function element(id){if(!elements.has(id)){let text='',el={value:'',style:{},getBoundingClientRect:()=>({width:1100,left:0}),getContext:()=>new Proxy({}, {get:()=>()=>{}})};Object.defineProperty(el,'innerHTML',{get:()=>text,set:v=>{text=v;let m=v.match(/<option value="([^"]*)"/);if(m)el.value=m[1]}});elements.set(id,el)}return elements.get(id)}
const context={document:{getElementById:element},window:{addEventListener:()=>{}},devicePixelRatio:1,console};vm.createContext(context);vm.runInContext(code,context);
const data=JSON.parse(fs.readFileSync(path.join(base,'rotation_report_data.json'),'utf8'));
for(const r of data.results){element('policy').value=r.id;element('policy').onchange();assert(element('ledger').innerHTML.includes('买入时间'));for(let i=0;i<r.trades.length;i++){element('trade').value=String(i);element('trade').onchange();element('tradechart').onmousemove({clientX:300});assert(element('tradetip').innerHTML.includes('组合毛收益'))}}
element('equity').onmousemove({clientX:600});assert(element('equitytip').innerHTML.includes(data.results[0].name));assert(element('comparison').innerHTML.includes('最低现金需求'));
console.log('PASS: all strategy switches, all trade charts, two-axis zero-line chart code and hover tooltip handlers execute');
