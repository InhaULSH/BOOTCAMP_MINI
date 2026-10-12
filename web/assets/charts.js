import {number} from './data.js';
const NS = 'http://www.w3.org/2000/svg';
export function svgElement(tag, attributes = {}, content) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  if (content !== undefined) node.textContent = content;
  return node;
}
export function empty(container, text = '연결된 데이터가 없습니다.') {
  const message = document.createElement('p'); message.className = 'empty'; message.textContent = text;
  container.replaceChildren(message);
}
export function lineChart(container, sets, labels, options = {}) {
  const values = sets.flatMap(s => s.values).filter(number);
  if (!labels.length || !values.length) return empty(container);
  const quarterly = options.quarterly;
  const width = Math.max(quarterly ? 360 : 0, container.clientWidth), height = container.clientHeight || 300;
  const padding = {left:56, right:24, top:22, bottom:quarterly ? 62 : 46};
  const minimum = Math.min(0, ...values), maximum = Math.max(0, ...values);
  const mean=values.reduce((a,b)=>a+b,0)/values.length;
  const logarithmic=options.quarterly&&options.unit==='%'&&Math.sqrt(values.reduce((n,v)=>n+(v-mean)**2,0)/values.length)>=300;
  const transform=v=>logarithmic?Math.sign(v)*Math.log1p(Math.abs(v)/10):v;
  const rawStep = (maximum - minimum || 1) / 5;
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const step = (rawStep / power <= 1 ? 1 : rawStep / power <= 2 ? 2 : rawStep / power <= 5 ? 5 : 10) * power;
  const low = Math.floor(minimum / step) * step, high = Math.ceil(maximum / step) * step || step;
  const x = i => padding.left + (labels.length === 1 ? .5 : i / (labels.length - 1)) * (width - padding.left - padding.right);
  const y = v => padding.top + (transform(high) - transform(v)) / (transform(high) - transform(low)) * (height - padding.top - padding.bottom);
  const svg = svgElement('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':options.label || '시계열 그래프'});
  if(logarithmic){svg.setAttribute('data-scale','symlog');svg.append(svgElement('text',{x:width-padding.right,y:12,'text-anchor':'end',fill:'#607968','font-size':10},'부호 보존 로그 눈금'));}
  svg.style.width = width + 'px'; svg.style.height = height + 'px';
  for (let v = low; v <= high + step * .001; v = Number((v + step).toPrecision(12))) {
    svg.append(svgElement('line', {x1:padding.left, y1:y(v), x2:width-padding.right, y2:y(v), stroke:v === 0 ? '#aabbb0' : '#e2e9e4'}));
    svg.append(svgElement('text', {x:padding.left-8, y:y(v)+4, 'text-anchor':'end', fill:'#849187','font-size':12}, v.toLocaleString('ko-KR') + (options.unit === '%' ? '%' : '')));
  }
  if (options.baseline && low <= 100 && high >= 100) {
    svg.append(svgElement('line', {x1:padding.left, x2:width-padding.right, y1:y(100), y2:y(100), stroke:'#738a7d', 'stroke-dasharray':'5 4'}));
  }
  const indices = quarterly ? labels.map((_,i) => i) : [...new Set([0, Math.floor((labels.length-1)/3), Math.floor((labels.length-1)*2/3), labels.length-1])];
  indices.forEach(i => {
    const text = svgElement('text', {x:x(i), y:height-(quarterly?30:14), 'text-anchor':'middle', fill:'#849187', 'font-size':12, class:'x-axis-label'});
    if (quarterly) {
      const [year, quarter] = labels[i].split(' ');
      text.append(svgElement('tspan', {x:x(i), dy:0}, year.slice(-2)), svgElement('tspan', {x:x(i), dy:16}, quarter));
    } else text.textContent = labels[i];
    svg.append(text);
  });
  const tooltip = document.getElementById('chart-tip');
  sets.forEach(series => {
    const group = svgElement('g', {'data-company':series.id, class:'chart-series'}); svg.append(group);
    // Solid lines contain observations only; an optional dashed bridge marks
    // missing periods without adding values to the series or its axis bounds.
    let segment = [];
    const flush = () => {if (segment.length) group.append(svgElement('polyline', {points:segment.join(' '), fill:'none', stroke:series.color, 'stroke-width':2.3,'stroke-linejoin':'round'})); segment = [];};
    series.values.forEach((v,i) => {if (!number(v)) flush(); else segment.push(`${x(i)},${y(v)}`);}); flush();
    if(options.missingDescription){
      const valid=series.values.map((v,i)=>number(v)?i:null).filter(i=>i!==null);
      const notify=(node,description)=>{
        node.setAttribute('tabindex','0');node.setAttribute('aria-label',description);
        const show=event=>{tooltip.textContent=description;tooltip.hidden=false;tooltip.style.left=Math.max(8,Math.min(event.clientX+12,innerWidth-tooltip.offsetWidth-8))+'px';tooltip.style.top=Math.max(8,Math.min(event.clientY+12,innerHeight-tooltip.offsetHeight-8))+'px';};
        node.addEventListener('pointerenter',show);node.addEventListener('pointermove',show);node.addEventListener('pointerleave',()=>tooltip.hidden=true);
        node.addEventListener('focus',()=>{const r=node.getBoundingClientRect();show({clientX:r.x,clientY:r.y});});node.addEventListener('blur',()=>tooltip.hidden=true);
      };
      for(let a=0;a<valid.length-1;a++){
        const left=valid[a],right=valid[a+1];
        if(right-left!==2)continue;
        const missing=Array.from({length:right-left-1},(_,j)=>left+j+1);
        if(!missing.every(i=>options.missingDescription(series,i)))continue;
        group.append(svgElement('line',{x1:x(left),y1:y(series.values[left]),x2:x(right),y2:y(series.values[right]),stroke:series.color,'stroke-width':2.3,'stroke-dasharray':'5 4',class:'chart-gap','pointer-events':'none'}));
        // Wide transparent hit segments keep every missing period reachable.
        const position=i=>y(series.values[left])+(i-left)/(right-left)*(y(series.values[right])-y(series.values[left]));
        missing.forEach(i=>{
          const hit=svgElement('line',{x1:x(i-.5),y1:position(i-.5),x2:x(i+.5),y2:position(i+.5),stroke:'transparent','stroke-width':18,'pointer-events':'stroke',class:'chart-gap-hit','data-period':labels[i]});
          notify(hit,options.missingDescription(series,i));group.append(hit);
        });
      }
    }
    series.values.forEach((v,i) => {
      if (!number(v) || options.showPoints===false) return;
      const dot = svgElement('circle', {cx:x(i), cy:y(v), r:3.1, fill:series.color, stroke:'#fff'});
      // Market charts show trends only, without native titles or popup handlers.
      if(options.interactive===false){dot.setAttribute('pointer-events','none');group.append(dot);return;}
      const description = options.describe ? options.describe(series,i,v) : `${series.name}\n${labels[i]}\n${v.toLocaleString('ko-KR')} ${options.unit || ''}`;
      // aria-label preserves the description without a duplicate native tooltip.
      const show = event => {tooltip.textContent=description;tooltip.hidden=false;tooltip.style.left=Math.max(8,Math.min(event.clientX+12,innerWidth-tooltip.offsetWidth-8))+'px';tooltip.style.top=Math.max(8,Math.min(event.clientY+12,innerHeight-tooltip.offsetHeight-8))+'px';};
      dot.setAttribute('tabindex','0');dot.setAttribute('role','button');dot.setAttribute('aria-label',description+' · 원문 보기');
      dot.addEventListener('focus',()=>{const r=dot.getBoundingClientRect();show({clientX:r.x,clientY:r.y});});dot.addEventListener('blur',()=>tooltip.hidden=true);
      dot.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();options.onSelect?.(series,i);}});
      dot.addEventListener('pointerenter',show);dot.addEventListener('pointermove',show);dot.addEventListener('click',e=>{tooltip.hidden=true;options.onSelect?options.onSelect(series,i):show(e);});dot.addEventListener('pointerleave',()=>tooltip.hidden=true);group.append(dot);
    });
  });
  container.replaceChildren(svg);

}

export function wordCloud(container, keywords, select) {
  const words=(keywords||[]).map(k=>({...k,label:k.keyword||k.label}))
    .filter(k=>k.label&&number(k.display_weight)&&k.display_weight>0);
  if (!words.length) return empty(container, '공시 키워드 데이터가 없습니다.');
  const width=Math.max(160,container.clientWidth),height=Math.max(180,container.clientHeight || 310);
  const canvas=document.createElement('canvas').getContext('2d');
  const modern=document.documentElement?.dataset?.uiVersion==='new';
  const font=modern?'Pretendard, BIGIN, sans-serif':'Arial, BIGIN, sans-serif';
  const palette=modern?['#396BA3','#79539C','#287F73','#A9573F','#4B70A1','#A04D76','#8D702F','#357665','#6253A0','#446F89','#9B672E','#414F61']:['#29103b','#191126','#6b1d25','#7a421f','#9a7625'];
  // A mild power curve increases contrast while preserving score order.
  // Fit long labels using a shared coefficient, never shrinking one word alone.
  const sizeWeight=word=>(word.display_weight/100)**1.15;
  // Measure once at a common reference size; scaling preserves every ratio.
  const dimensions=words.map(word=>{
    const size=sizeWeight(word)*100;
    canvas.font=`700 ${size}px ${font}`;
    return {size,w:canvas.measureText(word.label).width+10,h:size*1.25+8};
  });
  const layout=scale=>{
    if(dimensions.reduce((sum,d)=>sum+d.w*d.h*scale*scale,0)>(width-12)*(height-16))return null;
    const placed=[];
    for(let i=0;i<words.length;i++){
      const word=words[i],base=dimensions[i];
      const d={size:base.size*scale,w:base.w*scale,h:base.h*scale};
      let point=null,best=Infinity;
      // Search the full area without allocating and sorting a large grid.
      for(let y=8+d.h/2;y<=height-8-d.h/2;y+=4){
        for(let x=6+d.w/2;x<=width-6-d.w/2;x+=4){
          const distance=((x-width/2)/(width*.5))**2+((y-height/2)/(height*.5))**2;
          if(distance>=best)continue;
          if(placed.some(p=>x-d.w/2<p.box.x+p.box.w&&x+d.w/2>p.box.x&&
            y-d.h/2<p.box.y+p.box.h&&y+d.h/2>p.box.y))continue;
          point={x,y};best=distance;
        }
      }
      if(!point)return null;
      placed.push({word,size:d.size,cx:point.x,cy:point.y,
        box:{x:point.x-d.w/2,y:point.y-d.h/2,w:d.w,h:d.h}});
    }
    return placed;
  };
  // Grow as well as shrink: find a large feasible common scale for this area.
  let upper=Math.min(...dimensions.map(d=>Math.min((width-12)/d.w,(height-16)/d.h)));
  let scale=upper,placed=layout(scale);
  while(!placed){upper=scale;scale*=.8;placed=layout(scale);}
  for(let attempt=0;attempt<8;attempt++){
    const candidate=(scale+upper)/2,result=layout(candidate);
    if(result){scale=candidate;placed=result;}else upper=candidate;
  }
  // Centre the completed group, rather than leaving unused space on one side.
  const left=Math.min(...placed.map(p=>p.box.x)),right=Math.max(...placed.map(p=>p.box.x+p.box.w));
  const top=Math.min(...placed.map(p=>p.box.y)),bottom=Math.max(...placed.map(p=>p.box.y+p.box.h));
  const dx=(width-left-right)/2,dy=(height-top-bottom)/2;
  placed.forEach(p=>{p.cx+=dx;p.cy+=dy;p.box.x+=dx;p.box.y+=dy;});
  const svg=svgElement('svg',{viewBox:`0 0 ${width} ${height}`,style:`width:100%;height:${height}px;display:block`,role:'group','aria-label':`공시 키워드 ${placed.length}개. 선택하면 용어 해설과 공시 내용을 확인할 수 있습니다.`});
  // Paint every flame before every label so neighbouring text stays in front.
  placed.filter(p=>p.word.is_hot===true).forEach(({size,cx,cy})=>{
    svg.append(svgElement('text',{x:cx,y:cy,'font-size':size*1.15,
      'text-anchor':'middle','dominant-baseline':'central',opacity:.5,
      'font-family':'"Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif',
      'aria-hidden':'true','pointer-events':'none',class:'hot-background'},'🔥'));
  });
  placed.forEach(({word,size,cx,cy},i)=>{
    // Labels remain fully opaque and retain their click and keyboard handlers.
    const label=word.label,hot=word.is_hot===true;
    const node=svgElement('text',{x:cx,y:cy,'text-anchor':'middle','dominant-baseline':'central','font-size':size,'font-family':font,'font-weight':700,fill:palette[i%palette.length],role:'button',tabindex:0,'aria-label':label+(hot?(modern?' 최근 공시 언급 증가':' 최근 상승 신호'):'')+' 공시 설명 보기','aria-haspopup':'dialog'},label);
    node.addEventListener('click',()=>select(word));node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(word);}});svg.append(node);
  });
  container.replaceChildren(svg);
  // The packing rectangles reserve font ascenders and generous spacing. Fit
  // the actual rendered glyphs (including flame markers) to the viewport too.
  if(typeof svg.getBBox==='function'){
    const bounds=svg.getBBox();
    if(bounds.width>0&&bounds.height>0){
      const zoom=Math.min((width-16)/bounds.width,(height-16)/bounds.height);
      const centerX=bounds.x+bounds.width/2,centerY=bounds.y+bounds.height/2;
      [...svg.children].forEach(node=>{
        const x=Number(node.getAttribute('x')),y=Number(node.getAttribute('y'));
        const size=Number(node.getAttribute('font-size'));
        node.setAttribute('x',width/2+(x-centerX)*zoom);
        node.setAttribute('y',height/2+(y-centerY)*zoom);
        node.setAttribute('font-size',size*zoom);
      });
    }
  }
}
