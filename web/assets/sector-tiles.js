// Pure geometry: area follows a disclosed market-cap display exponent; raw caps stay unchanged.
export function sectorTileLayout(items, width, height, power=1) {
  const valid=items.filter(item=>Number.isFinite(item.cap)&&item.cap>0);
  const result=[];
  const split=(rows,x,y,w,h)=>{
    if(rows.length===1){result.push({item:rows[0],x,y,width:w,height:h});return;}
    const total=rows.reduce((sum,row)=>sum+row.cap**power,0);
    let sum=0,index=1,best=Infinity;
    for(let i=1;i<rows.length;i++){
      sum+=rows[i-1].cap**power;const distance=Math.abs(total/2-sum);
      if(distance<best){best=distance;index=i;}
    }
    const first=rows.slice(0,index),second=rows.slice(index);
    const fraction=first.reduce((sum,row)=>sum+row.cap**power,0)/total;
    if(w>=h){split(first,x,y,w*fraction,h);split(second,x+w*fraction,y,w*(1-fraction),h);}
    else{split(first,x,y,w,h*fraction);split(second,x,y+h*fraction,w,h*(1-fraction));}
  };
  if(valid.length&&width>0&&height>0)split(valid,0,0,width,height);
  return result;
}

// One typography scale for both labels: return size is always 1.5x name size.
export function tileTypography(width,height,name,value,measure) {
  const padding=Math.max(3.5,Math.min(20,Math.min(width,height)*.055));
  const usable=Math.max(0,width-padding*2-6),available=height-padding*2-6;
  const target=Math.max(14,Math.min(26,14+(Math.sqrt(width*height)-90)*.035));
  const lines=size=>{
    let line='',count=1;
    for(const char of name){
      if(line&&measure(line+char,size)>usable){count++;line=char;}else line+=char;
    }
    return count;
  };
  let size=target;
  const gap=height<100?3:8;
  while(size>12&&(measure(value,size*1.5)>usable||lines(size)>2||lines(size)*size*1.35+size*1.5*1.15+gap>available))size=Math.max(12,size-.5);
  const fits=measure(value,size*1.5)<=usable&&lines(size)<=2&&lines(size)*size*1.35+size*1.5*1.15+gap<=available;
  // Without the return, the name can use every line that fits the tile height.
  const nameFitsAt=fontSize=>[...name].every(char=>measure(char,fontSize)<=usable)&&lines(fontSize)*fontSize*1.35<=available;
  let nameOnlySize=target;
  while(nameOnlySize>12&&!nameFitsAt(nameOnlySize))nameOnlySize=Math.max(12,nameOnlySize-.5);
  return {nameSize:size,valueSize:size*1.5,padding,gap,fits,nameOnlySize,nameFits:nameFitsAt(nameOnlySize)};
}

export function layoutSectorTiles(field,nodes,sectors) {
  field.classList.add('is-tile-map');
  const softened=window.innerWidth>750;
  field.setAttribute('aria-label',softened?'타일 면적은 전체 KRX 구성종목 시가총액의 제곱근 기준으로 크기 차이를 완화하며, 색은 해당 지수 수익률':'타일 면적은 전체 KRX 지수 구성종목 시가총액 합계에 비례하고, 색은 해당 지수 수익률');
  let note=field.querySelector('.tile-size-note');
  if(!note){note=document.createElement('p');note.className='tile-size-note';field.append(note);}
  note.textContent=softened?'시가총액 기준':'전체 KRX 구성종목 시가총액에 비례하는 면적입니다.';
  const width=field.clientWidth-32,height=field.clientHeight-72;
  const placements=sectorTileLayout(sectors,width,height,softened ? .5 : 1);
  const measure=document.createElement('canvas').getContext('2d');
  const textWidth=(text,size)=>{measure.font=`700 ${size}px Pretendard, BIGIN, sans-serif`;return measure.measureText(text).width;};
  sectors.forEach((sector,i)=>{
    const node=nodes.children[i],tile=placements.find(p=>p.item===sector);
    node.hidden=!tile;
    if(!tile)return;
    const x=tile.x+16,y=tile.y+16;
    Object.assign(node.style,{left:x+'px',top:y+'px',width:tile.width+'px',height:tile.height+'px'});
    const name=node.querySelector('.sector-name'),value=node.querySelector('.sector-return');
    const type=tileTypography(tile.width,tile.height,sector.name,value.textContent,textWidth);
    // Small targets remain selectable, without squeezed or clipped lettering.
    const largeEnough=tile.width>=45&&tile.height>=38;
    const showBoth=largeEnough&&type.fits;
    const showName=largeEnough&&(type.fits||type.nameFits);
    node.classList.remove('is-compact','is-tiny');
    node.classList.toggle('needs-readable-label',!showBoth);
    node.style.padding=type.padding+'px';
    node.style.gap=type.gap+'px';
    name.style.fontSize=(showBoth?type.nameSize:type.nameOnlySize)+'px';
    value.style.fontSize=type.valueSize+'px';
    name.style.display=showName?'':'none';
    value.style.display=showBoth?'':'none';
    node.dataset.labelFits=String(showName);
    node.dataset.labelMode=showBoth?'both':showName?'name':'none';
    const tipWidth=Math.min(290,field.clientWidth-24);
    node.style.setProperty('--tip-width',tipWidth+'px');
    node.style.setProperty('--tip-left',(Math.max(12,Math.min(x,field.clientWidth-tipWidth-12))-x)+'px');
    node.classList.toggle('tip-above',y+tile.height>field.clientHeight*.65);
    node.setAttribute('aria-label',sector.name+' '+node.querySelector('.sector-return').textContent);
  });
  let pending=field.nextElementSibling;
  if(!pending?.classList.contains('tile-unavailable')){
    pending=document.createElement('div');pending.className='tile-unavailable';field.after(pending);
  }
  pending.setAttribute('role','group');
  pending.setAttribute('aria-label','전체 섹터 · 마우스를 올리거나 키보드로 초점을 맞추면 해당 타일 강조');
  // Keep controls and keyboard focus intact when only the map size changes.
  if(!pending.children.length)sectors.forEach((sector,i)=>{
    const node=nodes.children[i];
    node.id='sector-tile-'+i;
    const link=document.createElement('a');
    link.href=node.href;
    link.textContent=sector.name+' · '+node.querySelector('.sector-return').textContent;
    if(node.hidden){link.href=node.href;link.setAttribute('aria-label',sector.name+' · 타일 면적 미표시 · 산업 분석 보기');}
    else{
      link.setAttribute('aria-controls',node.id);
      const highlight=()=>{
        [...nodes.children].forEach(n=>n.classList.remove('tile-is-selected'));
        node.classList.toggle('tile-is-selected',link.matches(':hover')||link.matches(':focus-visible'));
      };
      link.addEventListener('mouseenter',highlight);
      link.addEventListener('mouseleave',highlight);
      link.addEventListener('focus',highlight);
      link.addEventListener('blur',highlight);
    }
    pending.append(link);
  });
  pending.hidden=!pending.children.length;
}
