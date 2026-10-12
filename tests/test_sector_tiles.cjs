const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');const path=require('node:path');
(async()=>{
 const {sectorTileLayout,tileTypography}=await import(pathToFileURL(path.resolve('web/assets/sector-tiles.js')).href);
 for(const [w,h] of [[1200,300],[320,228]]){
  const items=[100,50,25,15,10].map((cap,i)=>({id:i,cap}));
  const boxes=sectorTileLayout(items,w,h),total=items.reduce((n,r)=>n+r.cap,0);
  assert.equal(boxes.length,5);
  for(const b of boxes){assert(Math.abs(b.width*b.height/(w*h)-b.item.cap/total)<1e-10);assert(b.x>=0&&b.y>=0&&b.x+b.width<=w+1e-8&&b.y+b.height<=h+1e-8);}
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
   const a=boxes[i],b=boxes[j];assert(!(a.x<b.x+b.width-1e-8&&a.x+a.width>b.x+1e-8&&a.y<b.y+b.height-1e-8&&a.y+a.height>b.y+1e-8));
  }
 }
 assert.equal(sectorTileLayout([{cap:null},{cap:0},{cap:NaN}],300,200).length,0);
 assert.equal(sectorTileLayout([{cap:10}],300,200)[0].width,300);
 const softened=sectorTileLayout([{cap:100},{cap:4}],1000,300,.5);
 assert(Math.abs((softened[0].width*softened[0].height)/(softened[1].width*softened[1].height)-5)<1e-10);
 assert.equal(softened[0].item.cap,100);
 const measure=(text,size)=>text.length*size*.62;
 for(const [w,h] of [[500,300],[200,200],[110,150],[90,130]]){
  const t=tileTypography(w,h,'은행금융지주','-12.34%',measure);
  assert(t.nameSize>=12&&t.nameSize<=26);assert.equal(t.valueSize/t.nameSize,1.5);
 }
 assert.equal(tileTypography(30,30,'은행금융지주','-12.34%',measure).fits,false);
 assert(tileTypography(500,300,'반도체','+2.00%',measure).nameSize>tileTypography(110,150,'반도체','+2.00%',measure).nameSize);
 console.log('PASS: proportional tile areas, bounds, no overlap, single sector and missing market caps.');
})().catch(e=>{console.error(e);process.exit(1)});
