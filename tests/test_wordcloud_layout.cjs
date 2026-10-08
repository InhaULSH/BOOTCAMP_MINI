const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {pathToFileURL}=require('node:url');
class Element{
 constructor(){this.attrs={};this.children=[];this.events={};}
 setAttribute(k,v){this.attrs[k]=v;}
 append(node){this.children.push(node);}
 replaceChildren(node){this.children=[node];}
 addEventListener(k,f){this.events[k]=f;}
}
(async()=>{
 global.document={createElementNS:()=>new Element(),createElement:()=>({getContext:()=>({font:'',measureText(text){return {width:text.length*parseFloat(this.font.match(/[\d.]+px/)[0])*.75};}})})};
 const {wordCloud}=await import(pathToFileURL(path.resolve('web/assets/charts.js')).href);
 const labels=['SSD','수주 상황','데이터 센터','HBM','웨이퍼','OLED','GDDR','PECVD','생산 능력','부가 가치','가동 시간','평균 가동'];
 for(const width of [160,280,440,650]){
  const container=new Element();container.clientWidth=width;container.clientHeight=310;
  let clicked;
  wordCloud(container,labels.map((label,i)=>({label,display_weight:100-i*70/11,final_signal_score:91-i*.7,count:1})),word=>clicked=word.label);
  const texts=container.children[0].children;
  assert.equal(texts.length,12,`width ${width}`);
  assert.equal(new Set(texts.map(n=>n.textContent)).size,12);
  assert(new Set(texts.map(n=>n.attrs.x)).size>3,`cloud must not become a centered vertical list at width ${width}`);
  const boxes=texts.map(n=>{const size=n.attrs['font-size'];return {x:n.attrs.x-n.textContent.length*size*.75/2,y:n.attrs.y-size/2,w:n.textContent.length*size*.75,h:size};});
  boxes.forEach((a,i)=>boxes.slice(i+1).forEach(b=>assert(!(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y),'words must not overlap')));
  assert(texts.every(n=>Number.isFinite(n.attrs['font-size'])&&n.attrs['font-size']>0));
  let commonScale;
  texts.forEach((n,i)=>{
   const expected=((100-i*70/11)/100)**1.15*Math.min(70,width*.15);
   const scale=n.attrs['font-size']/expected;
   if(commonScale===undefined)commonScale=scale;
   assert(Math.abs(scale-commonScale)<1e-10,'all word sizes use one common scale');
   assert(scale<=1);
   assert(n.attrs.y>=0&&n.attrs.y<=310);
   assert(container.children[0].attrs.viewBox.endsWith(' 310'),'height remains fixed');
  });
  texts[0].events.click();assert.equal(clicked,'SSD');
  const hotContainer=new Element();hotContainer.clientWidth=width;hotContainer.clientHeight=310;
  wordCloud(hotContainer,[{label:'HBM',display_weight:100,is_hot:true,count:1}],()=>{});
  const [marker,hot]=hotContainer.children[0].children;
  assert.equal(hot.textContent,'HBM');assert.equal(marker.textContent,'🔥');
  assert.equal(marker.attrs['font-size'],hot.attrs['font-size']*1.15);
  assert.equal(marker.attrs.x,hot.attrs.x);assert.equal(marker.attrs.y,hot.attrs.y);
  assert.equal(marker.attrs.opacity,.5);assert.equal(hot.attrs.opacity,undefined);
  assert.equal(marker.attrs['pointer-events'],'none');
  assert.equal(marker.attrs['aria-hidden'],'true');

 }
 const render=words=>{const c=new Element();c.clientWidth=650;c.clientHeight=310;wordCloud(c,words,()=>{});return c.children[0].children;};
 const a=render([{keyword:'HBM',display_weight:50,final_signal_score:100,count:999,is_hot:false}])[0];
 const b=render([{keyword:'HBM',display_weight:50,final_signal_score:1,count:1,isHot:true}])[0];
 assert.equal(a.attrs['font-size'],b.attrs['font-size'],'size uses display_weight, not count or signal score');
 assert.equal(a.attrs['font-size'],.5**1.15*70,'a single word is not renormalized to maximum weight');
 assert.equal(a.children.length,0);assert.equal(b.children.length,0,'only canonical is_hot controls the marker');
 const ordered=render([{keyword:'SSD',display_weight:40,final_signal_score:1},{keyword:'HBM',display_weight:80,final_signal_score:99}]);
 assert.deepEqual(ordered.map(n=>n.textContent),['SSD','HBM'],'backend selection order is preserved');
 assert.equal(fs.readFileSync('web/assets/charts.js','utf8'),fs.readFileSync('deploy/web/assets/charts.js','utf8'));
 console.log('PASS: all 12 keywords render at desktop/mobile widths; selection and deployment parity preserved.');
})();
