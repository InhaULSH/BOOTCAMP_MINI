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
  const rawStep = (maximum - minimum || 1) / 5;
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const step = (rawStep / power <= 1 ? 1 : rawStep / power <= 2 ? 2 : rawStep / power <= 5 ? 5 : 10) * power;
  const low = Math.floor(minimum / step) * step, high = Math.ceil(maximum / step) * step || step;
  const x = i => padding.left + (labels.length === 1 ? .5 : i / (labels.length - 1)) * (width - padding.left - padding.right);
  const y = v => padding.top + (high - v) / (high - low) * (height - padding.top - padding.bottom);
  const svg = svgElement('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':options.label || '시계열 그래프'});
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
      dot.addEventListener('pointerenter',show);dot.addEventListener('pointermove',show);dot.addEventListener('click',show);dot.addEventListener('pointerleave',()=>tooltip.hidden=true);group.append(dot);
    });
  });
  container.replaceChildren(svg);
}

export function wordCloud(container, keywords, select) {
  const words = (keywords || []).map(k => ({...k, label:k.keyword || k.label}))
    .filter(k => k.label && number(k.display_weight) && k.display_weight > 0);
  if (!words.length) return empty(container, '공시 키워드 데이터가 없습니다.');
  const width=container.clientWidth,height=container.clientHeight || 310;
  const svg=svgElement('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':'공시 키워드. 선택하면 공시 맥락과 중요도 선정 이유를 볼 수 있습니다.'});
  const canvas=document.createElement('canvas').getContext('2d'),boxes=[],palette=['#29103b','#191126','#6b1d25','#7a421f','#9a7625'];
  words.forEach((word,index)=>{
    // Fixed pixel scale: the Python display_weight is already normalized for display.
    let size=Math.round(14+(word.display_weight/100)*Math.min(56,width*.12));
    canvas.font=`700 ${size}px Arial, BIGIN, sans-serif`;
    let measured=canvas.measureText(word.label).width;
    if(measured>width*.86){size=Math.floor(size*width*.86/measured);canvas.font=`700 ${size}px Arial, BIGIN, sans-serif`;measured=canvas.measureText(word.label).width;}
    const boxWidth=measured+6,boxHeight=size+6;
    for(let j=0;j<8000;j++){
      const a=j*.38,r=1.4*Math.sqrt(j),cx=width/2+Math.cos(a)*r*2.5,cy=height/2+Math.sin(a)*r*1.45,box={x:cx-boxWidth/2,y:cy-boxHeight/2,w:boxWidth,h:boxHeight};
      if(box.x<6||box.y<8||box.x+box.w>width-6||box.y+box.h>height-8||boxes.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))continue;
      boxes.push(box);
      const keywordBox=svgElement('g',{class:'keyword-box',transform:`translate(${box.x} ${box.y})`});
      const node=svgElement('text',{x:box.w/2,y:box.h/2,'text-anchor':'middle','dominant-baseline':'central','font-size':size,'font-weight':700,fill:palette[index%palette.length],role:'button',tabindex:0,'aria-label':word.label+' 공시 설명 보기','aria-haspopup':'dialog'},word.label);
      node.addEventListener('click',()=>select(word));node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(word);}});keywordBox.append(node);
      if(word.is_hot===true)keywordBox.append(svgElement('text',{class:'hot-badge',x:0,y:0,'dominant-baseline':'hanging','font-size':12,'aria-hidden':'true'},'🔥'));
      svg.append(keywordBox);break;
    }
  });
  container.replaceChildren(svg);
}
