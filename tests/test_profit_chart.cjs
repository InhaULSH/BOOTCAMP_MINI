const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
class Element {
 constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.style={};this.clientWidth=900;this.clientHeight=290;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 addEventListener(){}
}
(async()=>{
 const {metricSeries,financialPeriods}=await import(pathToFileURL(path.resolve('web/assets/data.js')).href);
 const {lineChart}=await import(pathToFileURL(path.resolve('web/assets/charts.js')).href);
 global.document={createElementNS:(_,tag)=>new Element(tag),getElementById:()=>new Element('tip')};
 const companies=process.argv[2]?JSON.parse(fs.readFileSync(process.argv[2],'utf8')).companies:
 Array.from({length:5},(_,i)=>({id:String(i),name:'company '+i,financials:Array.from({length:12},(_,q)=>({period:`${2023+Math.floor(q/4)} Q${q%4+1}`,revenue:100+i*10,operatingProfit:q===0?-10-i:10+i+q}))}));
 const periods=financialPeriods(companies);
 assert.equal(companies.length,5);assert.equal(periods.length,12);
 const sets=companies.map(c=>({id:c.id,name:c.name,color:'#367aba',values:metricSeries(c,'operating',periods)}));
 const container=new Element('div');lineChart(container,sets,periods,{quarterly:true,unit:'%'});
 const groups=container.children[0].children.filter(n=>n.attrs.class==='chart-series');
 assert.equal(groups.length,5);
 for(const g of groups){
  assert.equal(g.children.filter(n=>n.tag==='circle').length,12);
  assert(g.children.some(n=>n.tag==='polyline'));
  assert(g.children.filter(n=>n.tag==='circle').every(n=>Number.isFinite(Number(n.attrs.cy))));
 }
 for(const file of ['web/assets/service.css','deploy/web/assets/service.css']){
  const css=fs.readFileSync(file,'utf8');const opacity=Number(css.match(/\.chart-series\.is-muted\{opacity:([.\d]+)\}/)[1]);
  assert.equal(opacity,.16);assert(css.includes('.chart-series.is-highlighted{opacity:1}'));
 }
 console.log('Operating margin: all 5 companies render 12 points; local/deploy unselected opacity is 16%.');
 console.log(sets.map(s=>[s.name,s.values[0],s.values.at(-1)]));
})().catch(e=>{console.error(e);process.exit(1)});
