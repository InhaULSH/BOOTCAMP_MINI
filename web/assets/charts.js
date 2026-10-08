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
    // Missing observations form gaps; never replace them with zero or join across them.
    let segment = [];
    const flush = () => {if (segment.length) group.append(svgElement('polyline', {points:segment.join(' '), fill:'none', stroke:series.color, 'stroke-width':2.3,'stroke-linejoin':'round'})); segment = [];};
    series.values.forEach((v,i) => {if (!number(v)) flush(); else segment.push(`${x(i)},${y(v)}`);}); flush();
    series.values.forEach((v,i) => {
      if (!number(v)) return;
      const dot = svgElement('circle', {cx:x(i), cy:y(v), r:3.1, fill:series.color, stroke:'#fff'});
      const description = options.describe ? options.describe(series,i,v) : `${series.name}\n${labels[i]}\n${v.toLocaleString('ko-KR')} ${options.unit || ''}`;
      dot.append(svgElement('title', {}, description));
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
  const font='Arial, BIGIN, sans-serif',palette=['#29103b','#191126','#6b1d25','#7a421f','#9a7625'];
  // A mild power curve increases contrast while preserving score order.
  // Fit long labels using a shared coefficient, never shrinking one word alone.
  const sizeWeight=word=>(word.display_weight/100)**1.15;
  let fontUnit=Math.min(70,width*.15);
  for(const word of words){
    const size=sizeWeight(word)*fontUnit;
    canvas.font=`700 ${size}px ${font}`;
    const measured=canvas.measureText(word.label).width;
    if(measured>width*.86)fontUnit*=width*.86/measured;
  }
  const dimensions=(word,scale=1)=>{
    const size=sizeWeight(word)*fontUnit;
    canvas.font=`700 ${size}px ${font}`;
    const measured=canvas.measureText(word.label).width;
    return {size:size*scale,w:(measured+10)*scale,h:(size*1.25+8)*scale};
  };
  const layout=(layoutHeight,scale)=>{
    const placed=[];
    for(const word of words){
      const d=dimensions(word,scale), candidates=[];
      // Search the entire canvas, nearest the elliptical centre first.
      // The former spiral had a fixed radius even when the canvas grew.
      for(let y=8+d.h/2;y<=layoutHeight-8-d.h/2;y+=4){
        for(let x=6+d.w/2;x<=width-6-d.w/2;x+=4){
          candidates.push({x,y,distance:((x-width/2)/(width*.5))**2+((y-layoutHeight/2)/(layoutHeight*.5))**2});
        }
      }
      candidates.sort((a,b)=>a.distance-b.distance);
      const point=candidates.find(({x,y})=>!placed.some(p=>
        x-d.w/2<p.box.x+p.box.w&&x+d.w/2>p.box.x&&
        y-d.h/2<p.box.y+p.box.h&&y+d.h/2>p.box.y));
      if(!point)return null;
      placed.push({word,size:d.size,cx:point.x,cy:point.y,
        box:{x:point.x-d.w/2,y:point.y-d.h/2,w:d.w,h:d.h}});
    }
    return placed;
  };
  // Use one common scale for all words, preserving their computed size ratios.
  let placed=null,scale=1;
  while(!placed){
    placed=layout(height,scale);
    if(!placed)scale*=.95;
  }
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
    const node=svgElement('text',{x:cx,y:cy,'text-anchor':'middle','dominant-baseline':'central','font-size':size,'font-family':font,'font-weight':700,fill:palette[i%palette.length],role:'button',tabindex:0,'aria-label':label+(hot?' 최근 상승 신호':'')+' 공시 설명 보기','aria-haspopup':'dialog'},label);
    node.addEventListener('click',()=>select(word));node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(word);}});svg.append(node);
  });
  container.replaceChildren(svg);
}
