'use strict';
let data;
const sectorQuery=()=>`sector=${encodeURIComponent(data.sector_id)}`;
const industryHref=()=>data.sector_id===data.sectors?.[0]?.id?'industry':'sector:'+encodeURIComponent(data.sector_id);
const companyHref=code=>`company:${encodeURIComponent(data.sector_id)}:${code}`;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const valid = v => typeof v === 'number' && Number.isFinite(v);
const pct = v => valid(v) ? `${v.toFixed(1)}%` : '—';
const money = v => valid(v) ? `${(v/1e8).toLocaleString('ko-KR',{maximumFractionDigits:0})}` : '—';
const tips = {
 '매출 성장률':'직전 사업연도 대비 매출 증가율입니다. 이전 매출이 양수이고 재무제표 기준이 같은 경우에만 계산합니다. 매출 증가는 판매량·가격·제품 구성 변화가 함께 작용한 결과입니다.',
 '영업이익률':'매출에서 영업이익이 차지하는 비율입니다. 높을수록 본업의 수익성이 높지만 서로 다른 사업모델 간 단순 우열 판단에는 주의가 필요합니다.',
 'CAPEX / 매출':'현금흐름표의 유형자산 취득액을 매출액으로 나눈 값입니다. 무형자산 취득과 비현금 취득은 제외한 간소화 지표이며 기업이 발표하는 설비투자액과 다를 수 있습니다.',
 '단순 FCF':'영업활동현금흐름에서 유형자산 취득액을 차감한 값입니다. 무형자산 투자 등을 모두 반영한 기업가치평가용 잉여현금흐름과는 다릅니다.',
 '상대 위치':'실증 표본 내에서 해당 값보다 작은 기업 수에 동일 값 기업 수의 절반을 더하고, 유효 기업 수로 나눈 백분위입니다. 5개 기업의 서로 다른 사업을 비교하므로 투자 매력도 순위가 아닙니다. CAPEX 비율이나 재고 증가율은 높다고 좋은 값이 아닙니다.',
 '공시 표현':'사업보고서의 사업의 내용에서 주제 관련 문장을 찾습니다. 해당 문장 검출 여부를 세는 간단한 방식이며, 실제 투자 실행 여부나 표현 부재의 의미를 판정하지 않습니다.',
 '중앙값':'유효한 기업별 수치를 정렬했을 때 가운데 값입니다. 기업 규모 차이에 따른 쏠림을 줄이지만 실제 산업 전체의 통계는 아닙니다. 누락된 값은 0으로 채우지 않습니다.',
 'AI 분석':'기본 화면은 처리된 공시 문단 발췌와 Python 계산 수치를 사용합니다. LLM을 명시적으로 실행한 경우 입력 근거를 바탕으로 생성·검증한 분석으로 교체합니다. 공시에서 확인되는 내용과 AI 해석을 구분하며, 해석은 원인이나 미래 성과를 확정하지 않습니다.',
 '공시 서술 단계':'연도별 핵심 변화에 관한 공시 표현을 AI가 기대·전망, 투자·개발 계획, 실행·공급, 매출·수익 기여로 구분한 보조 해석입니다. 회사 전체의 성장 등급이 아닙니다. 여러 단계가 섞이거나 근거가 부족하면 판단을 유보합니다.',
 '재무 영향':'사업 변화가 매출, 수익성, 설비 지출, 재고 등에 영향을 주고 현금흐름으로 이어질 수 있는 경로입니다. 추정 현금흐름이나 기업가치의 계산 결과가 아니며 조건부 해석입니다.'
};
const help = title => `<button class="help" data-help="${esc(title)}" aria-label="${esc(title)} 설명">?</button>`;
function metric(label,value,note,tip=label){return `<div class="metric"><div class="metric-label">${label}${help(tip)}</div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></div>`;}
function heading(title,small=''){return `<div class="section-head"><h2>${title}</h2><small>${small}</small></div>`;}
function cards(items){return `<div class="insights">${items.map(x=>`<article class="insight"><span class="tag">${esc(x.signal)}</span><h3>${esc(x.title)}</h3><span class="label">확인된 내용</span><p class="fact">${esc(x.fact)}</p><span class="label">해석 · 가능성</span><p>${esc(x.interpretation)}</p>${x.financial_impact?`<span class="label">재무·현금흐름 영향 ${help('재무 영향')}</span><p>${esc(x.financial_impact)}</p><span class="label">조건과 불확실성</span><p>${esc(x.uncertainty)}</p>`:''}</article>`).join('') || '<p class="empty">분석에 필요한 재무정보가 부족합니다.</p>'}</div>`;}
function narrativeIntro(n){return `<section class="panel ai-overview"><div class="eyebrow">공시 기반 분석 ${help('AI 분석')}</div><h2>사업 흐름을 읽는 핵심</h2><p class="lead">${esc(n.summary)}</p><div class="narrative-pair"><div><h3>기회 요인</h3><p>${esc(n.opportunity)}</p></div><div><h3>위험과 불확실성</h3><p>${esc(n.risk)}</p></div></div></section>`;}
function narrativeDetails(n,company){return heading('3년간 사업은 어떻게 달라졌나',`공시 발췌 또는 AI 보조 해석 ${help('공시 서술 단계')}`)+`<section class="panel timeline">${n.timeline.map(t=>`<article class="year-row"><strong>${t.year}</strong><div><span class="badge">${esc(t.stage)}</span><p>${esc(t.summary)}</p></div></article>`).join('')}</section>`+heading('앞으로 확인할 변화')+`<section class="panel"><ul class="watch-list">${n.checks.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></section>`;}
function chart(series,key,benchmark=null,relative=false){
 const values=[...series,...(benchmark||[])].map(x=>x[key]).filter(valid);
 if(!values.length)return '<div class="empty">표시할 수 있는 수치가 없습니다.</div>';
 let lo=Math.min(0,...values),hi=Math.max(0,...values); if(hi===lo)hi=lo+1;
 const span=hi-lo; if(relative){lo=0;hi=100;}else{lo-=span*.12;hi+=span*.12;}
 const x=i=>60+i*460/Math.max(series.length-1,1), y=v=>175-(v-lo)/(hi-lo)*145;
 const lines=Array.from({length:4},(_,i)=>{const v=lo+(hi-lo)*i/3;return `<line class="gridline" x1="60" x2="520" y1="${y(v)}" y2="${y(v)}"/><text x="48" y="${y(v)+4}" text-anchor="end">${key==='fcf'?money(v):v.toFixed(0)+'%'}</text>`}).join('');
 function path(rows,color){let d='',connected=false;rows.forEach((r,i)=>{if(valid(r[key])){d+=`${connected?'L':'M'}${x(i)},${y(r[key])} `;connected=true;}else connected=false;});return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5"/>`+rows.map((r,i)=>valid(r[key])?`<circle cx="${x(i)}" cy="${y(r[key])}" r="4" fill="${color}"><title>${r.year}: ${pct(r[key])}</title></circle>`:'').join('');}
 return `<svg class="chart" viewBox="0 0 560 210" role="img" aria-label="연도별 지표 추이">${lines}${benchmark?path(benchmark,'#b2bdcf'):''}${path(series,'#315ddd')}${series.map((r,i)=>`<text x="${x(i)}" y="202" text-anchor="middle">${r.year}</text>`).join('')}</svg>`;
}
let selectedYear=null;
const signed=v=>valid(v)?`${v>0?'+':''}${v.toFixed(2)}%`:'—';
const tone=v=>!valid(v)||v===0?'neutral':v>0?'rise':'fall';
const latest=c=>c.history.at(-1)||{};
const specs=[['revenue_growth','매출 성장률','성장하고 있나요?'],['margin','영업이익률','팔아서 얼마나 남기나요?'],['capex_ratio','CAPEX / 매출','설비에 얼마나 투자하나요?'],['fcf_margin','투자 후 현금 비중','투자하고 현금이 남나요?']];
tips['투자 후 현금 비중']='영업활동현금흐름에서 현금 유형자산 취득액을 뺀 단순 FCF를 매출로 나눈 값입니다. 무형자산 투자는 제외합니다. 현금 비중 하락만으로 본업의 현금창출력이 나빠졌다고 단정할 수 없습니다.';
tips['지수 가중평균']='현재 표본 기업의 시가총액 비중으로 기업별 재무 비율을 가중평균합니다. 같은 비중을 과거 연도에도 적용하므로 당시 시장 구성을 재현한 값이 아닙니다. 공식 KRX 비중이 아니며 지표가 누락된 기업이 있으면 평균을 계산하지 않습니다.';
function spark(rows,label,percent=false){
 if(!rows?.length)return '<p class="empty">시세를 불러오지 못했습니다.</p>';
 const vals=rows.map(r=>r.value).filter(valid);if(!vals.length)return '<p class="empty">자료 없음</p>';
 let lo=Math.min(...vals),hi=Math.max(...vals);let span=hi-lo||1;lo-=span*.1;hi+=span*.1;
 const x=i=>12+i*416/Math.max(rows.length-1,1),y=v=>120-(v-lo)/(hi-lo)*105;
 let d='',connected=false;rows.forEach((r,i)=>{if(valid(r.value)){const window=rows.slice(Math.max(0,i-2),i+1);const value=label==='최근 주가지수 추이'&&window.every(r=>valid(r.value))?window.reduce((sum,r)=>sum+r.value,0)/window.length:r.value;d+=`${connected?'L':'M'}${x(i)},${y(value)} `;connected=true;}else connected=false;});
 return `<svg viewBox="0 0 440 150" class="spark" role="img" aria-label="${esc(label)}"><line x1="12" x2="428" y1="120" y2="120" stroke="#dce7e2"/><path d="${d}" fill="none" stroke="currentColor" stroke-width="2.6"/>${rows.map((r,i)=>valid(r.value)?`<circle cx="${x(i)}" cy="${y(r.value)}" r="1.8" fill="currentColor" opacity=".45"><title>${esc(r.date)}: ${r.value.toLocaleString('ko-KR',{maximumFractionDigits:2})}${percent?'%':''}</title></circle>`:'').join('')}<text x="12" y="145">${esc(rows[0].date)}</text><text x="428" y="145" text-anchor="end">${esc(rows.at(-1).date)}</text></svg>`;
}
function bindHelp(){document.querySelectorAll('[data-help]').forEach(b=>b.onclick=()=>{$('#help-title').textContent=b.dataset.help;$('#help-body').textContent=tips[b.dataset.help]||'제공된 공시와 계산 수치를 바탕으로 해석합니다.';$('#help').showModal();});}
function nav(company){
 document.body.classList.toggle('company-view',Boolean(company));
 
}
const yearRow=c=>c.history.find(r=>r.year===selectedYear)||{};
function changeLabel(rows,key){
 const current=rows.find(r=>r.year===selectedYear), previous=rows.find(r=>r.year===selectedYear-1);
 if(!current||!previous||!valid(current[key])||!valid(previous[key]))return '전년 비교 자료 없음';
 if(current.basis!==previous.basis)return '재무 기준 변경 · 비교 제외';
 const delta=current[key]-previous[key];
 return `전년 대비 ${delta>0?'+':''}${delta.toFixed(1)}%p`;
}
function home(){
 const idx=data.market.index||{};
 $('#content').innerHTML=`<div class="eyebrow">DISCOVER INDUSTRIES</div><h1>어떤 산업이 궁금한가요?</h1><p class="subtitle">숫자 너머의 사업 변화. 관심 있는 산업에서 시작하세요.</p><section class="universe" aria-label="산업 노드 히트맵"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><button class="sector-node ${tone(idx.change)}" id="semiconductor"><span class="node-kicker">SECTOR</span><strong>${esc(data.sector_name)}</strong><b>${signed(idx.change)}</b><span>KRX ${esc(data.sector_name)} 지수 · 직전 거래일 대비</span><small>공시로 읽는 성장·투자·현금흐름</small><em>산업 살펴보기 ↗</em></button><button class="soon bio" disabled>바이오<small>준비 중</small></button><button class="soon car" disabled>자동차<small>준비 중</small></button><button class="soon battery" disabled>2차전지<small>준비 중</small></button><button class="soon finance" disabled>금융<small>준비 중</small></button><div class="map-legend"><span class="rise">● 상승</span><span class="fall">● 하락</span><span>● 자료 없음 / 준비 중</span></div></section><div class="home-bottom"><div><span class="eyebrow">01 / DISCOVER</span><h3>산업을 발견하고</h3><p>대표 기업의 움직임을 함께 살펴봅니다.</p></div><div><span class="eyebrow">02 / UNDERSTAND</span><h3>변화를 이해하고</h3><p>성장·수익·투자·현금의 흐름을 읽습니다.</p></div><div><span class="eyebrow">03 / EXPLORE</span><h3>기업으로 깊이 들어갑니다</h3><p>서로 다른 사업과 공시 내용을 비교합니다.</p></div></div>`;
 if(data.sectors?.length>1){
  $('.universe').classList.add('multi-sector-map');
  $('.universe').innerHTML=data.sectors.map((s,i)=>`<button class="sector-node extra-sector" data-sector="${esc(s.id)}" style="left:${25+(i%3)*25}%;top:${32+Math.floor(i/3)*30}%;transform:translate(-50%,-50%);width:180px;height:180px"><strong>${esc(s.name)}</strong><small>산업 살펴보기 ↗</small></button>`).join('');
  document.querySelectorAll('[data-sector]').forEach(b=>b.onclick=()=>{location.hash='sector:'+encodeURIComponent(b.dataset.sector)});return;
 }
 $('#semiconductor').onclick=()=>{const node=$('#semiconductor');node.classList.add('expanding');setTimeout(()=>{location.hash='industry'},matchMedia('(prefers-reduced-motion: reduce)').matches?0:360)};
}
function quotePanel(company){
 const idx=data.market.index||{},q=company?data.market.quotes?.[company.code]:idx;
 const hist=q?.history||[],v=company?q?.price:hist.at(-1)?.value;
 const stale=q?.stale;
 return `<section class="panel market-panel ${company?'':'sector-market'}"><div class="eyebrow">${company?'STOCK SNAPSHOT':'SECTOR PULSE'}</div><h2>${company?esc(company.name)+' 주가':'KRX '+data.sector_name+' 지수'}</h2><div class="quote-line"><strong>${valid(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:2}):'—'}<small>${company?' 원':' pt'}</small></strong><span class="${tone(q?.change)}">${signed(q?.change)}</span></div><p class="small">${esc(q?.traded_at||'기준일 미수집')} 종가 · 직전 거래일 대비</p>${spark(hist,company?'최근 주가 추이':'최근 주가지수 추이')}<p class="small">${company?'':'KRX 섹터 지수 · 3거래일 이동평균선, 원 종가 점 표시'}</p></section>`;
}
function comparisonBars(key,company){
 const rows=data.companies.map(c=>({code:c.code,name:c.name,value:yearRow(c)[key],history:c.history})).sort((a,b)=>valid(a.value)&&valid(b.value)?a.value-b.value:valid(a.value)?-1:valid(b.value)?1:a.name.localeCompare(b.name,'ko'));
 const max=Math.max(1,...rows.map(r=>valid(r.value)?Math.abs(r.value):0));
 return `<div class="bars" aria-label="기업별 ${esc(key)} 낮은 값부터 비교">${rows.map(r=>`<div class="bar-col ${company?.code===r.code?'chosen':''}" data-value="${valid(r.value)?r.value:''}"><div class="bar-space"><span class="bar ${tone(r.value)}" style="height:${valid(r.value)?Math.abs(r.value)/max*62:0}px;${r.value<0?'top:50%':'bottom:50%'}"></span><span class="zero"></span></div><b class="${tone(r.value)}">${pct(r.value)}</b><small>${esc(r.name)}</small><small class="bar-change">${changeLabel(r.history,key)}</small></div>`).join('')}</div>`;
}
const trendSpecs=[['revenue','매출','전사 매출 규모'],['operating_income','영업이익','본업에서 남긴 이익'],['capex','설비투자','현금 유형자산 취득액'],['operating_cashflow','영업활동현금흐름','영업에서 들어온 현금']];
tips['매출']='전사 연간 매출입니다. 삼성전자 전사 실적은 반도체 부문 실적과 다릅니다.';
tips['영업이익']='연간 본업의 이익입니다. 음수는 영업손실을 뜻합니다.';
tips['설비투자']=tips['CAPEX / 매출'];
tips['영업활동현금흐름']='현금흐름표의 영업활동으로 인한 순현금흐름입니다. 영업이익과는 다릅니다.';
// Display-only parameters: original financial amounts and YoY formulas stay unchanged.
const TREND_LOG_STD_THRESHOLD=300; // percentage points, population standard deviation
const TREND_SYMLOG_CONSTANT=10;
function trendScale(input){
 const values=input.filter(valid);
 const mean=values.length?values.reduce((sum,v)=>sum+v,0)/values.length:0;
 const std=values.length?Math.sqrt(values.reduce((sum,v)=>sum+(v-mean)**2,0)/values.length):0;
 const logarithmic=std>=TREND_LOG_STD_THRESHOLD;
 const transform=v=>logarithmic?Math.sign(v)*Math.log1p(Math.abs(v)/TREND_SYMLOG_CONSTANT):v;
 const inverse=v=>logarithmic?Math.sign(v)*TREND_SYMLOG_CONSTANT*Math.expm1(Math.abs(v)):v;
 const low=Math.min(0,...values),high=Math.max(0,...values);
 const span=transform(high)-transform(low)||1,padding=span*.09;
 const lo=transform(low)-padding,hi=transform(high)+padding;
 const y=v=>213-(transform(v)-lo)/(hi-lo)*176;
 const ticks=Array.from({length:5},(_,i)=>inverse(lo+(hi-lo)*i/4)).filter(v=>Math.abs(y(v)-y(0))>15);
 ticks.push(0);ticks.sort((a,b)=>a-b);
 return {std,logarithmic,y,ticks};
}
function clearChartHighlight(){
 document.querySelectorAll('.chart-series').forEach(g=>g.classList.remove('hover-muted','hover-selected'));
 document.querySelectorAll('.chart-legend').forEach(g=>{g.classList.remove('hover-active');g.setAttribute('aria-pressed','false')});
}
function trendLines(key,company){
 const colors=['#2563b5','#d65358','#168b78','#b77a16','#8062b5'];
 const series=data.companies.map((c,i)=>({code:c.code,name:c.name,color:colors[i]||`hsl(${i*137.5},60%,44%)`,rows:c.history}));
 const values=series.flatMap(s=>s.rows.map(r=>r.yoy?.[key])).filter(valid);
 if(!values.length)return '<p class="empty">전년 대비 비교 자료가 없습니다.</p>';
 const scale=trendScale(values),x=i=>75+i*360/Math.max(data.years.length-1,1),y=scale.y;
 const grid=scale.ticks.map(v=>`<line class="${v===0?'zero-line':'gridline'}" x1="75" x2="440" y1="${y(v)}" y2="${y(v)}"/><text x="65" y="${y(v)+4}" text-anchor="end">${v.toLocaleString('ko-KR',{maximumFractionDigits:Math.abs(v)<10?1:0})}%</text>`).join('');
 const paths=series.map(s=>{let d='',last=null;const points=[];data.years.forEach((year,i)=>{const r=s.rows.find(r=>r.year===year)||{},v=r.yoy?.[key];if(!valid(v)){last=null;return;}d+=`${last&&last.basis===r.basis?'L':'M'}${x(i)},${y(v)} `;last=r;points.push(`<g class="chart-point" tabindex="0" role="button" data-chart-company="${s.code}" data-chart-key="${key}" data-chart-year="${year}" aria-label="${esc(s.name)} ${year}년 금액과 변동률"><circle class="point-halo" cx="${x(i)}" cy="${y(v)}" r="11" fill="${s.color}"/><circle class="point-dot" cx="${x(i)}" cy="${y(v)}" r="4.5" fill="${s.color}"/></g>`)});return `<g class="chart-series" data-series="${s.code}" opacity="${company&&company.code!==s.code?'.25':'1'}"><path class="series-underlay" d="${d}"/><path class="series-line" d="${d}" stroke="${s.color}"/>${points.join('')}</g>`}).join('');
 const legend=series.map((s,i)=>`<g class="chart-legend" tabindex="0" role="button" data-chart-company="${s.code}" data-chart-key="${key}" aria-label="${esc(s.name)} 3개년 ${esc(trendSpecs.find(t=>t[0]===key)[1])}과 공시 보기"><rect x="459" y="${39+i*29}" width="152" height="27" rx="6"/><line x1="469" x2="486" y1="${53+i*29}" y2="${53+i*29}" stroke="${s.color}" stroke-width="3"/><circle cx="478" cy="${53+i*29}" r="3" fill="${s.color}"/><text x="495" y="${57+i*29}">${esc(s.name)}</text></g>`).join('');
 return `<div class="chart-scale-note"><span class="scale-badge ${scale.logarithmic?'is-log':''}" title="유효한 기업·연도별 변동률의 표준편차가 ${TREND_LOG_STD_THRESHOLD}%p 이상이면 대칭 로그 눈금을 사용합니다. 0과 음수도 표시하며 수치는 원래 변동률입니다.">${scale.logarithmic?'대칭 로그 눈금':'일반 눈금'}</span><small>변동률 표준편차 ${scale.std.toLocaleString('ko-KR',{maximumFractionDigits:1})}%p</small></div><svg class="trend-chart" data-scale="${scale.logarithmic?'symlog':'linear'}" data-std="${scale.std}" viewBox="0 0 620 ${Math.max(250,series.length*29+70)}" role="img" aria-label="${esc(key)} 전년 대비 변동률"><title>${scale.logarithmic?'대칭 로그 눈금. 눈금 간 간격은 비례하지 않습니다. ' : ''}0% 기준 전년 대비 변동률. 전년 값이 0 이하이거나 비교 불가하면 표시하지 않습니다.</title><rect class="plot-surface" x="70" y="29" width="374" height="193" rx="10"/>${grid}${paths}${legend}${data.years.map((year,i)=>`<text x="${x(i)}" y="240" text-anchor="middle">${year}</text>`).join('')}</svg>`;
}
function keyMetrics(company){
 return `<div class="section-head metric-heading"><h2>대표기업으로 보는 사업의 흐름</h2></div><div class="trend-grid">`+trendSpecs.map(([key,label,note])=>{
 const rows=data.companies.map(c=>({code:c.code,value:c.history.find(r=>r.year===selectedYear)?.yoy?.[key]})),weights=data.market.representative_weights||{};
 const included=rows.filter(r=>valid(r.value)&&valid(weights[r.code])&&weights[r.code]>0);
 const omitted=data.companies.filter(c=>!included.some(r=>r.code===c.code));
 const value=company?company.history.find(r=>r.year===selectedYear)?.yoy?.[key]:included.length?included.reduce((s,r)=>s+r.value*weights[r.code],0)/included.reduce((s,r)=>s+weights[r.code],0):null;
 return `<section class="panel trend-card"><h3>${label}${help(label)}</h3><p class="small">${note} · 전년 대비 변동률</p><strong class="trend-value ${tone(value)}">${signed(value)}</strong><p class="small">${selectedYear}년 · ${company?esc(company.name):`대표 ${data.companies.length}사 변동률의 시가총액 비중 가중평균`}</p>${!company&&omitted.length?`<p class="coverage-note">${omitted.map(c=>esc(c.name)).join(' · ')} 비교 수치 또는 비중 누락 · 유효 ${included.length}사 비중을 재조정했습니다.</p>`:''}${trendLines(key,company)}</section>`}).join('')+'</div>';
}
function bindChartHover(){
 let panel=document.createElement('div');panel.className='chart-tooltip';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label','기업 재무 정보');document.body.append(panel);
 let timer,switchTimer,active;const hide=()=>{clearTimeout(timer);timer=setTimeout(()=>{panel.hidden=true;clearChartHighlight();},550)};
 const keep=()=>{clearTimeout(timer);clearTimeout(switchTimer)};
 panel.onmouseenter=keep;panel.onmouseleave=hide;panel.onfocusin=keep;panel.onfocusout=hide;
 const show=target=>{
  keep();clearChartHighlight();active=target;const c=data.companies.find(c=>c.code===target.dataset.chartCompany),key=target.dataset.chartKey,year=Number(target.dataset.chartYear),label=trendSpecs.find(s=>s[0]===key)[1];
  const rows=year?c.history.filter(r=>r.year===year):c.history;
  panel.innerHTML=`<strong>${esc(c.name)} · ${esc(label)}${year?' · '+year+'년':''}</strong><p class="small">${year?'해당 시점 금액과 전년 대비 변동률':'최근 3개년 금액 · 단위: 억 원'}</p>${rows.map(r=>`<div class="hover-row"><span>${r.year}</span><b>${money(r[key])}</b>${valid(r[key])?`<button class="revenue-origin" data-code="${c.code}" data-key="${key}" data-year="${r.year}" aria-label="${r.year}년 ${esc(label)} 공시 위치">공시 ↗</button>`:''}</div><p class="hover-change">전년 대비 <b>${signed(r.yoy?.[key])}</b></p>`).join('')}<p class="small">${c.history.at(-1)?.basis==='CFS'?'연결':'별도'} 재무 · 단위: 억 원</p>`;
  const comparable=c.history.filter(r=>valid(r.yoy?.[key])).length;
  if(!year)panel.insertAdjacentHTML('beforeend',`<p class="hover-availability">${esc(label)} 변동률 · ${comparable?`${comparable}개 연도 표시`:'전년 비교 자료 없음 · 그래프 미표시'}</p>`);
  const rect=target.getBoundingClientRect(),chartRect=target.closest('svg').getBoundingClientRect();panel.hidden=false;
  const width=panel.offsetWidth,isLegend=target.classList.contains('chart-legend');
  // Keep legend details outside the plot; the old left-side placement covered the selected line.
  let left=rect.left-width+rect.width,top=rect.bottom+8;
  if(isLegend){
   if(chartRect.right+width+8<=innerWidth){left=chartRect.right+8;top=rect.top-10;}
   else {left=chartRect.right-width;top=chartRect.bottom+8;
    if(top+panel.offsetHeight>innerHeight-8){top=chartRect.top-panel.offsetHeight-8;}
    // When neither side fits vertically, use the right-side legend space plus outer margin.
    if(top<8){left=Math.max(8,innerWidth-width-8);top=8;}
   }
  }
  panel.style.left=Math.max(8,Math.min(innerWidth-width-8,left))+'px';panel.style.top=Math.max(8,Math.min(innerHeight-panel.offsetHeight-8,top))+'px';
  const legend=target.closest('svg').querySelector(`.chart-legend[data-chart-company="${c.code}"]`);
  if(legend){legend.classList.add('hover-active');legend.setAttribute('aria-pressed','true')}
  target.closest('svg').querySelectorAll('.chart-series').forEach(g=>{g.classList.toggle('hover-muted',g.dataset.series!==c.code);g.classList.toggle('hover-selected',g.dataset.series===c.code)});
  const selected=target.closest('svg').querySelector(`[data-series="${c.code}"]`);if(selected)selected.parentNode.append(selected);
  panel.querySelectorAll('.revenue-origin').forEach(button=>button.onclick=()=>showRevenueSource(button.dataset.code,Number(button.dataset.year),button.dataset.key));
 };
 document.querySelectorAll('[data-chart-company]').forEach(target=>{target.onmouseenter=()=>{
  clearTimeout(switchTimer);
  if(!panel.hidden&&active!==target&&active?.classList.contains('chart-legend')&&target.classList.contains('chart-legend')){
   // Crossing a neighbouring row on the way into the popup is not a selection.
   clearTimeout(timer);switchTimer=setTimeout(()=>show(target),420);
  }else show(target);
 };target.onmouseleave=()=>{clearTimeout(switchTimer);hide()};target.onfocus=()=>show(target);target.onblur=hide;target.onclick=()=>show(target);target.onkeydown=e=>{if(e.key==='Escape'){keep();panel.hidden=true;clearChartHighlight();target.blur()}}});
}
async function showRevenueSource(code,year,key="revenue"){
 const label=trendSpecs.find(s=>s[0]===key)?.[1]||"매출";
 document.querySelectorAll('.chart-tooltip').forEach(p=>p.hidden=true);clearChartHighlight();
 const dialog=$('#source-dialog'),body=$('#source-body');body.textContent=label+' 원문 위치를 확인하는 중입니다.';$('#source-title').textContent=label+' 공시 원문';dialog.showModal();
 try{const response=await fetch(`/api/revenue-source?${sectorQuery()}&code=${encodeURIComponent(code)}&year=${year}&key=${encodeURIComponent(key)}`);if(!response.ok)throw new Error('수치와 일치하는 원문 표 위치를 확인하지 못했습니다.');const r=await response.json();
 $('#source-title').textContent=`${r.company} · ${year}년 ${label}`;
 if(!r.table)throw new Error('전체 원본 표를 확인하지 못했습니다.');
 const span=v=>Math.max(1,Math.min(200,Number(v)||1));
 const table=r.table.rows.map(row=>'<tr>'+row.cells.map(c=>{const tag=c.header?'th':'td';return `<${tag} rowspan="${span(c.rowspan)}" colspan="${span(c.colspan)}" class="${c.highlight?'original-target':''}" ${c.primary_highlight?'id="source-highlight"':''}>${esc(c.text)}</${tag}>`}).join('')+'</tr>').join('');
 body.innerHTML=`<p>${esc(r.section)} / ${esc(r.heading)}</p><p class="small">${esc(r.paragraph_id)} · 원문 단위: ${esc(r.unit)} · ${r.basis==='CFS'?'연결':'별도'}</p><div class="original-table-scroll"><table class="original-disclosure-table"><caption>${esc(r.company)} ${year}년 · 공시 원문 전체 표</caption><tbody>${table}</tbody></table></div><p class="small">원문의 모든 행·열과 병합 셀을 유지했으며, 참고한 당기 지표 셀을 강조했습니다. ${r.derived?'CAPEX는 강조한 세부 취득 계정의 합산 값입니다.':''}</p><a href="${esc(r.document_url)}" target="_blank" rel="noopener noreferrer" class="source-original">DART 원문 전체 보기 ↗</a>`;
 $('#source-highlight')?.scrollIntoView({block:'center',inline:'center'});
 }catch(e){body.textContent=e.message;}
}
function insightPanel(company){
 const insight=(company?.ai_insights||data.ai_insights)?.[String(selectedYear)],sentences=insight?.sentences||[];
 let number=0;
 return `<section class="panel ai-insight"><div class="section-head"><h2>AI ${company?'기업':'산업'} 인사이트</h2><small>${selectedYear}년 · ${esc(insight?.method||'생성 전')}</small></div><p class="insight-paragraph">${sentences.map(s=>`${esc(s.text)}${s.source_refs.map(ref=>`<sup><button class="footnote" data-source="${esc(ref)}" aria-label="출처 ${++number} 보기" title="출처 ${number} · 공시 원문 보기">${number}</button></sup>`).join('')}`).join(' ')||'인사이트를 생성할 공시 근거가 없습니다.'}</p></section>`;
}
function bindSources(){
 document.querySelectorAll('[data-source]').forEach(button=>button.onclick=async()=>{
  document.querySelectorAll('.chart-tooltip').forEach(p=>p.hidden=true);clearChartHighlight();
  const dialog=$('#source-dialog'),body=$('#source-body');body.innerHTML='<p>원문을 불러오는 중입니다.</p>';dialog.showModal();
  try{
   const response=await fetch('/api/source?'+sectorQuery()+'&ref='+encodeURIComponent(button.dataset.source));if(!response.ok)throw new Error('원문 위치를 확인하지 못했습니다.');
   const result=await response.json(),c=result.citation;
   $('#source-title').textContent=`${c.company} · ${c.report_name}`;
   body.innerHTML=`<p class="small">${esc(c.section)} / ${esc(c.heading)} · ${esc(c.paragraph_id)}</p>${result.blocks.map(b=>{let text=esc(b.text);if(b.highlight){const [a,z]=b.highlight;text=esc(b.text.slice(0,a))+'<mark id="source-highlight">'+esc(b.text.slice(a,z))+'</mark>'+esc(b.text.slice(z));}return `<p class="source-block ${b.highlight?'target-block':''}">${text}</p>`}).join('')}<a class="source-original" href="${esc(result.document_url)}" target="_blank" rel="noopener noreferrer">DART 원문 전체 보기 ↗</a>`;
   if(result.table){
    const span=v=>Math.max(1,Math.min(200,Number(v)||1));
    const rows=result.table.rows.map(row=>'<tr>'+row.cells.map(cell=>`<td rowspan="${span(cell.rowspan)}" colspan="${span(cell.colspan)}" class="${cell.highlight?'original-target':''}">${esc(cell.text)}</td>`).join('')+'</tr>').join('');
    body.insertAdjacentHTML('beforeend',`<div class="original-table-scroll"><table class="original-disclosure-table"><caption>공시 원문 전체 표 · 매출액 셀 강조</caption><tbody>${rows}</tbody></table></div>`);
   }
   $('#source-highlight')?.scrollIntoView({block:'center'});
  }catch(error){body.textContent=error.message;}
 });
}
function cloudPanel(company){
 const cloud=(company?.wordcloud||data.wordcloud)?.[String(selectedYear)]||[];
 return `<section class="panel signal-cloud"><h2>주요 공시 신호 워드클라우드 ${help('단어 빈도')}</h2><p class="small">${selectedYear}년 사업·반기·분기보고서 · 사업의 내용</p><svg id="word-cloud" viewBox="0 0 560 250" role="img" aria-label="공시 용어 출현 빈도"><title>단어 크기는 실제 출현 횟수만 반영합니다.</title></svg><p class="small cloud-scope">지정 사업 용어의 단순 출현 횟수 · 문서 간 반복 포함 · 색상에 방향성 의미 없음</p>${!cloud.length?'<p class="empty">표시할 공시 용어가 없습니다.</p>':''}</section>`;
}
tips['단어 빈도']='본문 사업의 내용에서 지정된 사업 용어가 나타난 횟수입니다. 제목·첨부·숫자 중심 표는 제외하며, 청킹 전 문단/표 행으로 세어 분할로 인한 중복을 방지합니다. 같은 문장이 여러 보고서에 반복되면 각각 셉니다. 큰 단어가 긍정적 변화나 중요성을 뜻하지는 않습니다.';
function drawCloud(company){
 const svg=$('#word-cloud');if(!svg)return;
 const words=((company?.wordcloud||data.wordcloud)?.[String(selectedYear)]||[]).slice(0,45),canvas=document.createElement('canvas'),ctx=canvas.getContext('2d'),boxes=[];
 const colors=['#087d66','#3478ef','#e85d4b','#8a61b7','#184b43'],max=words[0]?.count||1;
 let output='';
 for(let i=0;i<words.length;i++){
  const word=words[i];let placed=false;
  for(let shrink=0;shrink<3&&!placed;shrink++){
   const size=(14+45*Math.sqrt(word.count/max))*(1-shrink*.16);ctx.font=`700 ${size}px Malgun Gothic, sans-serif`;const width=ctx.measureText(word.text).width+12,height=size*1.22+7;
   for(let step=0;step<1400;step++){
    const angle=step*.37+i*1.8,radius=step*.18,x=280+Math.cos(angle)*radius*1.38-width/2,y=123+Math.sin(angle)*radius*.70-height/2;
    const box={x,y,w:width,h:height};if(x<6||y<5||x+width>554||y+height>245||boxes.some(b=>x<b.x+b.w&&x+width>b.x&&y<b.y+b.h&&y+height>b.y))continue;
    boxes.push(box);output+=`<text x="${x+width/2}" y="${y+height*.76}" text-anchor="middle" font-size="${size}" fill="${colors[i%colors.length]}" font-weight="700"><title>${esc(word.text)}: ${word.count.toLocaleString('ko-KR')}회</title>${esc(word.text)}</text>`;placed=true;break;
   }
  }
 }
 svg.innerHTML='<title>공시 용어의 단순 출현 빈도</title>'+output;
}
function filingSection(company){
 const n=company?company.llm:data.llm;
 const recent=n?.timeline?.at(-1);
 const items=n?.cards||company?.insights||[];
 return heading('최근 DART 공시 동향','공시 본문에서 확인한 변화와 조건부 해석')+`<section class="panel disclosure-intro">${recent?`<p class="small">분석된 정기보고서 중 최근 연도 · ${recent.year}년</p><p class="lead">${esc(recent.summary)}</p>`:''}${n?.comparison?`<p class="comparison">${esc(n.comparison)}</p>`:''}${!n?'<p>저장된 공시 본문 분석이 부족합니다. 공시 제목이나 건수만으로 사업 변화를 추정하지 않습니다.</p>':''}</section>`+cards(items)+`<p class="small disclosure-scope">${data.years[0]}-${data.years.at(-1)}년 사업·반기·분기보고서 기반의 저장된 분석입니다. 새로 수집한 공시 목록만으로 최신 사업 변화를 생성하지 않습니다.</p>`;
}
function matrix(){
 const cols=data.companies;
 const fields=[['주요 사업',c=>esc(c.sector)],['매출 성장',c=>pct(yearRow(c).revenue_growth)],['수익성 · 영업이익률',c=>pct(yearRow(c).margin)],['투자 · 매출 대비',c=>pct(yearRow(c).capex_ratio)],['현금 · 매출 대비',c=>pct(yearRow(c).fcf_margin)],['최근 공시',c=>esc((data.market.filings||[]).find(f=>f.code===c.code&&f.category!=='기타 공시')?.title||'자료 없음')]];
 return heading(`대표기업 ${data.companies.length}사, 나란히 읽기`,`${selectedYear}년 · 사업모델 차이를 함께 살펴봅니다`)+`<section class="panel table-wrap matrix"><table><thead><tr><th>비교 항목</th>${cols.map(c=>`<th><a href="#${companyHref(c.code)}">${esc(c.name)} ↗</a></th>`).join('')}</tr></thead><tbody>${fields.map(([label,get])=>`<tr><th>${label}</th>${cols.map(c=>`<td>${get(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></section>`;
}
function quoteCards(){return heading('기업을 더 깊이 살펴보세요','전일 종가 · 그 직전 거래일 대비')+`<div class="quote-cards">${data.companies.map(c=>{const q=data.market.quotes?.[c.code];return `<a class="panel quote-card" href="#${companyHref(c.code)}"><span>${esc(c.name)} ↗</span><strong class="${tone(q?.change)}">${signed(q?.change)}</strong><small>${valid(q?.price)?q.price.toLocaleString('ko-KR')+'원':'시세 미수집'} · ${esc(q?.traded_at||'미수집')}</small></a>`}).join('')}</div>`;}
function companyExtras(company){return heading('표본 내 상대 위치',help('상대 위치'))+`<section class="panel">${specs.slice(0,3).map(([k,label])=>{const v=latest(company).positions?.[k];return `<div class="position"><span>${label}</span><div class="rail">${valid(v)?`<b style="left:${v}%"></b>`:''}</div><em>${pct(v)}</em></div>`}).join('')}</section>`+heading('연도별 재무 요약','단위: 억 원, %')+`<section class="panel table-wrap"><table><thead><tr><th>사업연도</th><th>기준</th><th>매출</th><th>영업이익</th><th>유형자산 취득</th><th>영업현금흐름</th><th>단순 FCF</th></tr></thead><tbody>${company.history.map(r=>`<tr><td>${r.year}</td><td>${r.basis==='CFS'?'연결':r.basis==='OFS'?'별도':'—'}</td><td>${money(r.revenue)}</td><td>${money(r.operating_income)}</td><td>${money(r.capex)}</td><td>${money(r.operating_cashflow)}</td><td>${money(r.fcf)}</td></tr>`).join('')}</tbody></table></section>`;}
function render(){
 document.querySelectorAll(".chart-tooltip").forEach(p=>p.remove());
 const route=location.hash.slice(1),parts=route.split(':'),code=parts[0]==='company'?parts[2]:route,company=data.companies.find(c=>c.code===code);selectedYear??=data.years.at(-1);nav(company);
 if(!route||route==='home'){home();return;}
 if(route!=='industry'&&!route.startsWith('sector:')&&!company){$('#content').innerHTML='<h1>찾을 수 없는 보고서입니다.</h1><a href="#home">산업 지도로 돌아가기</a>';return;}
 const n=company?company.llm:data.llm;
 let html=`<nav class="breadcrumb"><a href="#home">산업 지도</a> / <a href="#${industryHref()}">${esc(data.sector_name)}</a>${company?' / '+esc(company.name):''}</nav><div class="intro"><div><div class="eyebrow">${company?'COMPANY REPORT':'INDUSTRY REPORT'}</div><div class="company-title-row"><h1>${company?esc(company.name):data.sector_name+', 지금 어떤 흐름일까요?'}</h1>${company?`<div class="company-controls"><a href="#home">산업 지도</a><select id="company-switch" aria-label="기업 전환">${data.companies.map(c=>`<option value="${c.code}" ${c.code===company.code?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div>`:''}</div><p class="subtitle">${company?esc(company.description):`대표 ${data.companies.length}개 기업의 공시와 재무로 사업의 변화를 살펴봅니다.`}</p></div></div><div class="overview-grid">${quotePanel(company)}${cloudPanel(company)}</div>`;
 html+=insightPanel(company);
 if(!company)html+=quoteCards();
 html+=keyMetrics(company);
 if(!company)html+=matrix();
 if(company){html+=companyExtras(company);if(!n)html+=`<section class="panel">${Object.entries(company.topics||{}).map(([k,vs])=>`<h3>${esc(k)}</h3>${vs.map(v=>`<p>${esc(v)}</p>`).join('')}`).join('')}</section>`;}
 html+=`<p class="note">${esc(data.mode)} · 연간 재무와 최근 시세의 기간은 다릅니다. 표본 기업의 전사 재무이며 산업 전체 통계가 아닙니다. 미확인 수치는 —로 표시합니다. 시세·공시 수집: ${esc(data.market.fetched_at||'미수집')}${data.market.errors?.length?'<br>'+data.market.errors.map(esc).join(' · '):''}</p>`;
 $('#content').innerHTML=html;bindHelp();bindSources();bindChartHover();drawCloud(company);if($('#company-switch'))$('#company-switch').onchange=e=>location.hash=companyHref(e.target.value);$('.workspace').scrollTo(0,0);
}
$('#close-source').addEventListener('click',()=>$('#source-dialog').close());
$('#close-help').addEventListener('click',()=>$('#help').close());
let routeRequest=0;
async function loadRoute(){
 const request=++routeRequest,parts=location.hash.slice(1).split(':');
 const sectorId=['sector','company'].includes(parts[0])?decodeURIComponent(parts[1]):data?.sector_id;
 try{
  if(!data||sectorId&&sectorId!==data.sector_id){
   const r=await fetch('/api/reports'+(sectorId?'?sector='+encodeURIComponent(sectorId):''));
   if(!r.ok)throw new Error('선택한 섹터 보고서를 읽지 못했습니다.');
   const value=await r.json();if(request!==routeRequest)return;data=value;selectedYear=data.years.at(-1);
  }
  render();
 }catch(error){$('#content').innerHTML=`<h1>보고서를 준비해 주세요</h1><p>${esc(error.message)}</p><p>python -m snapdart.analyze --offline 실행 후 새로고침하세요.</p>`}
}
window.addEventListener('hashchange',loadRoute);
loadRoute();
