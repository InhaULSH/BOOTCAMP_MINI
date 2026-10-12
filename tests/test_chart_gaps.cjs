const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
class Element{
 constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.style={};this.events={};this.clientWidth=900;this.clientHeight=290;this.offsetWidth=100;this.offsetHeight=40;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 append(...n){this.children.push(...n);}
 replaceChildren(...n){this.children=n;}
 addEventListener(k,f){this.events[k]=f;}
 getBoundingClientRect(){return {x:100,y:100};}
}
(async()=>{
 const tip=new Element('tip');global.innerWidth=1200;global.innerHeight=800;
 global.document={createElementNS:(_,tag)=>new Element(tag),getElementById:()=>tip};
 const {lineChart}=await import(pathToFileURL(path.resolve('web/assets/charts.js')).href);
 const labels=['2025 Q1','2025 Q2','2025 Q3','2025 Q4','2026 Q1'];
 const series={id:'one',name:'기업',color:'#123456',values:[10,null,30,null,null]};
 const description=(s,i)=>`${s.name} ${labels[i]}: 지표 계산에 오류가 있어 표시하지 않습니다.`;
 const box=new Element('div');lineChart(box,[series],labels,{quarterly:true,unit:'%',missingDescription:description});
 const group=box.children[0].children.find(n=>n.attrs.class==='chart-series');
 const bridge=group.children.filter(n=>n.attrs.class==='chart-gap');
 assert.equal(bridge.length,1);assert.equal(bridge[0].attrs.stroke,series.color);assert.equal(bridge[0].attrs['stroke-dasharray'],'5 4');
 const hits=group.children.filter(n=>n.attrs.class==='chart-gap-hit');assert.equal(hits.length,1);
 for(const hit of hits){assert(!hit.children.some(n=>n.tag==='title'));assert(hit.attrs['aria-label']);hit.events.pointerenter({clientX:100,clientY:100});assert.equal(tip.hidden,false);assert(tip.textContent.includes(hit.attrs['data-period']));assert(tip.textContent.includes('오류'));hit.events.pointerleave();assert.equal(tip.hidden,true);}
 assert.equal(group.children.filter(n=>n.tag==='circle').length,2);
 for(const dot of group.children.filter(n=>n.tag==='circle')){assert(!dot.children.some(n=>n.tag==='title'));assert(dot.attrs['aria-label']);dot.events.pointerenter({clientX:100,clientY:100});assert.equal(tip.hidden,false);dot.events.pointerleave();assert.equal(tip.hidden,true);}
 assert.equal(group.children.filter(n=>n.attrs.class==='chart-missing-end').length,0);
 assert.deepEqual(series.values,[10,null,30,null,null]);
 lineChart(box,[series],labels,{quarterly:true,unit:'%'});
 assert(!box.children[0].children.some(g=>g.children?.some(n=>n.attrs.class==='chart-gap')));
 lineChart(box,[{...series,values:[null,20,30,40,50]}],labels,{quarterly:true,unit:'%',missingDescription:description});
 const leading=box.children[0].children.find(n=>n.attrs.class==='chart-series');
 assert(!leading.children.some(n=>n.attrs.class==='chart-gap'));
 lineChart(box,[{...series,values:[10,null,null,40,50]}],labels,{quarterly:true,unit:'%',missingDescription:description});
 assert(!box.children[0].children.find(n=>n.attrs.class==='chart-series').children.some(n=>n.attrs.class==='chart-gap'));
 lineChart(box,[{...series,values:[-10,null,0,40,50]}],labels,{quarterly:true,unit:'%',missingDescription:description});
 assert.equal(box.children[0].children.find(n=>n.attrs.class==='chart-series').children.filter(n=>n.attrs.class==='chart-gap').length,1);
 console.log('All core metrics: single missing period only, company-color dashed bridge and hover; consecutive/edge gaps remain disconnected, no fabricated values.');
})().catch(e=>{console.error(e);process.exit(1)});
