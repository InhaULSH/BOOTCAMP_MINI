'use strict';
let data;
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
 '중앙값':'유효한 기업별 수치를 정렬했을 때 가운데 값입니다. 기업 규모 차이에 따른 쏠림을 줄이지만 실제 반도체 산업 전체의 통계는 아닙니다. 누락된 값은 0으로 채우지 않습니다.',
 'AI 분석':'설정된 분석 모델이 사업·반기·분기보고서에서 선별한 문단과 Python 계산 수치를 함께 읽고 작성했습니다. 공시에서 확인되는 내용과 AI 해석을 구분하며, 해석은 원인이나 미래 성과를 확정하지 않습니다.',
 '공시 서술 단계':'연도별 핵심 변화에 관한 공시 표현을 AI가 기대·전망, 투자·개발 계획, 실행·공급, 매출·수익 기여로 구분한 보조 해석입니다. 회사 전체의 성장 등급이 아닙니다. 여러 단계가 섞이거나 근거가 부족하면 판단을 유보합니다.',
 '재무 영향':'사업 변화가 매출, 수익성, 설비 지출, 재고 등에 영향을 주고 현금흐름으로 이어질 수 있는 경로입니다. 추정 현금흐름이나 기업가치의 계산 결과가 아니며 조건부 해석입니다.'
};
const help = title => `<button class="help" data-help="${esc(title)}" aria-label="${esc(title)} 설명">?</button>`;
function metric(label,value,note,tip=label){return `<div class="metric"><div class="metric-label">${label}${help(tip)}</div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></div>`;}
function heading(title,small=''){return `<div class="section-head"><h2>${title}</h2><small>${small}</small></div>`;}
function cards(items){return `<div class="insights">${items.map(x=>`<article class="insight"><span class="tag">${esc(x.signal)}</span><h3>${esc(x.title)}</h3><span class="label">확인된 내용</span><p class="fact">${esc(x.fact)}</p><span class="label">해석 · 가능성</span><p>${esc(x.interpretation)}</p>${x.financial_impact?`<span class="label">재무·현금흐름 영향 ${help('재무 영향')}</span><p>${esc(x.financial_impact)}</p><span class="label">조건과 불확실성</span><p>${esc(x.uncertainty)}</p>`:''}</article>`).join('') || '<p class="empty">분석에 필요한 재무정보가 부족합니다.</p>'}</div>`;}
function narrativeIntro(n){return `<section class="panel ai-overview"><div class="eyebrow">공시 기반 분석 ${help('AI 분석')}</div><h2>사업 흐름을 읽는 핵심</h2><p class="lead">${esc(n.summary)}</p><div class="narrative-pair"><div><h3>기회 요인</h3><p>${esc(n.opportunity)}</p></div><div><h3>위험과 불확실성</h3><p>${esc(n.risk)}</p></div></div></section>`;}
function narrativeDetails(n,company){return heading('5년간 사업은 어떻게 달라졌나',`공시 서술 단계는 AI의 보조 해석 ${help('공시 서술 단계')}`)+`<section class="panel timeline">${n.timeline.map(t=>`<article class="year-row"><strong>${t.year}</strong><div><span class="badge">${esc(t.stage)}</span><p>${esc(t.summary)}</p></div></article>`).join('')}</section>`+heading('앞으로 확인할 변화')+`<section class="panel"><ul class="watch-list">${n.checks.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></section>`;}
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
tips['지수 가중평균']='대표 5사 실증 지수에 쓰인 현재 시가총액 비중으로 기업별 재무 비율을 가중평균합니다. 같은 비중을 과거 연도에도 적용하므로 당시 시장 구성을 재현한 값이 아닙니다. 공식 KRX 비중이 아니며 지표가 누락된 기업이 있으면 평균을 계산하지 않습니다.';
function spark(rows,label,percent=false){
 if(!rows?.length)return '<p class="empty">시세를 불러오지 못했습니다.</p>';
 const vals=rows.map(r=>r.value).filter(valid);if(!vals.length)return '<p class="empty">자료 없음</p>';
 let lo=Math.min(...vals),hi=Math.max(...vals);let span=hi-lo||1;lo-=span*.1;hi+=span*.1;
 const x=i=>12+i*416/Math.max(rows.length-1,1),y=v=>120-(v-lo)/(hi-lo)*105;
 let d='',connected=false;rows.forEach((r,i)=>{if(valid(r.value)){d+=`${connected?'L':'M'}${x(i)},${y(r.value)} `;connected=true;}else connected=false;});
 return `<svg viewBox="0 0 440 150" class="spark" role="img" aria-label="${esc(label)}"><line x1="12" x2="428" y1="120" y2="120" stroke="#dce7e2"/><path d="${d}" fill="none" stroke="currentColor" stroke-width="2.6"/>${rows.map((r,i)=>valid(r.value)?`<circle cx="${x(i)}" cy="${y(r.value)}" r="2.5" fill="currentColor"><title>${esc(r.date)}: ${r.value.toLocaleString('ko-KR',{maximumFractionDigits:2})}${percent?'%':''}</title></circle>`:'').join('')}<text x="12" y="145">${esc(rows[0].date)}</text><text x="428" y="145" text-anchor="end">${esc(rows.at(-1).date)}</text></svg>`;
}
function bindHelp(){document.querySelectorAll('[data-help]').forEach(b=>b.onclick=()=>{$('#help-title').textContent=b.dataset.help;$('#help-body').textContent=tips[b.dataset.help]||'제공된 공시와 계산 수치를 바탕으로 해석합니다.';$('#help').showModal();});}
function nav(company){
 document.body.classList.toggle('company-view',Boolean(company));
 $('#companies').innerHTML=company?data.companies.map(c=>`<a href="#${c.code}" class="${company.code===c.code?'active':''}">${esc(c.name)}</a>`).join(''):'';
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
 $('#content').innerHTML=`<div class="eyebrow">DISCOVER INDUSTRIES</div><h1>어떤 산업이 궁금한가요?</h1><p class="subtitle">숫자 너머의 사업 변화. 관심 있는 산업에서 시작하세요.</p><section class="universe" aria-label="산업 노드 히트맵"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><button class="sector-node ${tone(idx.change)}" id="semiconductor"><span class="node-kicker">SEMICONDUCTORS</span><strong>반도체</strong><b>${signed(idx.change)}</b><span>대표 5사 지수 · 직전 거래일 대비</span><small>공시로 읽는 성장·투자·현금흐름</small><em>산업 살펴보기 ↗</em></button><button class="soon bio" disabled>바이오<small>준비 중</small></button><button class="soon car" disabled>자동차<small>준비 중</small></button><button class="soon battery" disabled>2차전지<small>준비 중</small></button><button class="soon finance" disabled>금융<small>준비 중</small></button><div class="map-legend"><span class="rise">● 상승</span><span class="fall">● 하락</span><span>● 자료 없음 / 준비 중</span></div></section><div class="home-bottom"><div><span class="eyebrow">01 / DISCOVER</span><h3>산업을 발견하고</h3><p>대표 기업의 움직임을 함께 살펴봅니다.</p></div><div><span class="eyebrow">02 / UNDERSTAND</span><h3>변화를 이해하고</h3><p>성장·수익·투자·현금의 흐름을 읽습니다.</p></div><div><span class="eyebrow">03 / EXPLORE</span><h3>기업으로 깊이 들어갑니다</h3><p>서로 다른 사업과 공시 내용을 비교합니다.</p></div></div>`;
 $('#semiconductor').onclick=()=>{const node=$('#semiconductor');node.classList.add('expanding');setTimeout(()=>{location.hash='industry'},matchMedia('(prefers-reduced-motion: reduce)').matches?0:360)};
}
function quotePanel(company){
 const idx=data.market.index||{},q=company?data.market.quotes?.[company.code]:idx;
 const hist=q?.history||[],v=company?q?.price:hist.at(-1)?.value;
 const stale=company?(q?.stale|| (q?.traded_at && Date.now()-Date.parse(q.traded_at)>86400000)):Object.values(data.market.quotes||{}).some(x=>x.stale);
 return `<section class="panel market-panel"><div class="eyebrow">${company?'STOCK SNAPSHOT':'SECTOR PULSE'}</div><h2>${company?esc(company.name)+' 주가':'대표 5사 주가 지수'}</h2><div class="quote-line"><strong>${valid(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:2}):'—'}<small>${company?' 원':' pt'}</small></strong><span class="${tone(q?.change)}">${signed(q?.change)}</span></div><p class="small">${company?'전일 종가 대비 · 수집 시점 시세':'공통 거래일의 일별 가격 · 첫날=100'}</p>${spark(hist,'최근 주가 추이')}<p class="small">${company?`시세 ${esc(q?.traded_at||'미수집')} · ${stale?'저장된 이전 시세':'자동 실시간 갱신 아님'}`:'현재 시가총액 비중을 고정한 실증 지수 · KRX 공식 지수 아님'}</p></section>`;
}
function comparisonBars(key,company){
 const rows=data.companies.map(c=>({code:c.code,name:c.name,value:yearRow(c)[key],history:c.history})).sort((a,b)=>valid(a.value)&&valid(b.value)?a.value-b.value:valid(a.value)?-1:valid(b.value)?1:a.name.localeCompare(b.name,'ko'));
 const max=Math.max(1,...rows.map(r=>valid(r.value)?Math.abs(r.value):0));
 return `<div class="bars" aria-label="기업별 ${esc(key)} 낮은 값부터 비교">${rows.map(r=>`<div class="bar-col ${company?.code===r.code?'chosen':''}" data-value="${valid(r.value)?r.value:''}"><div class="bar-space"><span class="bar ${tone(r.value)}" style="height:${valid(r.value)?Math.abs(r.value)/max*62:0}px;${r.value<0?'top:50%':'bottom:50%'}"></span><span class="zero"></span></div><b class="${tone(r.value)}">${pct(r.value)}</b><small>${esc(r.name)}</small><small class="bar-change">${changeLabel(r.history,key)}</small></div>`).join('')}</div>`;
}
function keyMetrics(company){
 const rows=company?company.history:data.weighted_history,row=rows.find(r=>r.year===selectedYear)||{};
 return `<div class="section-head metric-heading"><h2>대표기업으로 보는 사업의 흐름</h2><label>기준 연도 <select id="metric-year" aria-label="핵심 지표 기준 연도">${data.years.map(y=>`<option value="${y}" ${y===selectedYear?'selected':''}>${y}년</option>`).join('')}</select></label></div>`+specs.map(([key,label,question])=>`<section class="panel metric-comparison"><div class="metric-summary"><span class="eyebrow">${question}</span><h3>${label}${help(label)}</h3><strong>${pct(row[key])}</strong><p class="small">${company?'해당 기업의 연간 비율':`지수 비중 가중평균 ${help('지수 가중평균')}`}</p><p class="year-change">${changeLabel(rows,key)}</p></div><div class="metric-visual">${comparisonBars(key,company)}<p class="small">${key==='capex_ratio'?'낮은 투자 비중 → 높은 투자 비중 · 높고 낮음으로 좋고 나쁨을 판단하지 않습니다.':'낮은 값 → 높은 값 · 해당 지표 기준 비교이며 종합 투자 순위가 아닙니다.'} 변화는 비율 간 차이(%p)입니다.</p></div></section>`).join('');
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
 return heading('대표기업 5사, 나란히 읽기',`${selectedYear}년 · 사업모델 차이를 함께 살펴봅니다`)+`<section class="panel table-wrap matrix"><table><thead><tr><th>비교 항목</th>${cols.map(c=>`<th><a href="#${c.code}">${esc(c.name)} ↗</a></th>`).join('')}</tr></thead><tbody>${fields.map(([label,get])=>`<tr><th>${label}</th>${cols.map(c=>`<td>${get(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></section>`;
}
function quoteCards(){return heading('기업을 더 깊이 살펴보세요','전일 종가 대비 · 저장된 시세')+`<div class="quote-cards">${data.companies.map(c=>{const q=data.market.quotes?.[c.code];return `<a class="panel quote-card" href="#${c.code}"><span>${esc(c.name)} ↗</span><strong class="${tone(q?.change)}">${signed(q?.change)}</strong><small>${valid(q?.price)?q.price.toLocaleString('ko-KR')+'원':'시세 미수집'}</small></a>`}).join('')}</div>`;}
function companyExtras(company){return heading('표본 내 상대 위치',help('상대 위치'))+`<section class="panel">${specs.slice(0,3).map(([k,label])=>{const v=latest(company).positions?.[k];return `<div class="position"><span>${label}</span><div class="rail">${valid(v)?`<b style="left:${v}%"></b>`:''}</div><em>${pct(v)}</em></div>`}).join('')}</section>`+heading('연도별 재무 요약','단위: 억 원, %')+`<section class="panel table-wrap"><table><thead><tr><th>사업연도</th><th>기준</th><th>매출</th><th>영업이익</th><th>유형자산 취득</th><th>영업현금흐름</th><th>단순 FCF</th></tr></thead><tbody>${company.history.map(r=>`<tr><td>${r.year}</td><td>${r.basis==='CFS'?'연결':r.basis==='OFS'?'별도':'—'}</td><td>${money(r.revenue)}</td><td>${money(r.operating_income)}</td><td>${money(r.capex)}</td><td>${money(r.operating_cashflow)}</td><td>${money(r.fcf)}</td></tr>`).join('')}</tbody></table></section>`;}
function render(){
 const route=location.hash.slice(1),company=data.companies.find(c=>c.code===route);selectedYear??=data.years.at(-1);nav(company);
 if(!route||route==='home'){home();return;}
 if(route!=='industry'&&!company){$('#content').innerHTML='<h1>찾을 수 없는 보고서입니다.</h1><a href="#home">산업 지도로 돌아가기</a>';return;}
 const n=company?company.llm:data.llm;
 let html=`<nav class="breadcrumb"><a href="#home">산업 지도</a> / <a href="#industry">반도체</a>${company?' / '+esc(company.name):''}</nav><div class="intro"><div><div class="eyebrow">${company?'COMPANY REPORT':'INDUSTRY REPORT'}</div><h1>${company?esc(company.name):'반도체, 지금 어떤 흐름일까요?'}</h1><p class="subtitle">${company?esc(company.description):'대표 5개 기업의 공시와 재무로 사업의 변화를 살펴봅니다.'}</p></div></div><div class="overview-grid">${quotePanel(company)}<section class="panel report-summary"><div class="eyebrow">DISCLOSURE REPORT ${help('AI 분석')}</div><h2>${company?'기업':'섹터'} 요약 리포트</h2><p class="lead">${esc(n?.summary||'저장된 AI 요약이 없습니다. 아래 계산 지표와 공시 목록으로 흐름을 확인하세요.')}</p><p class="summary-trend">${esc(company?company.trend_summary:data.trend_summary)}</p></section></div>`;
 html+=keyMetrics(company)+filingSection(company);
 if(!company)html+=matrix()+quoteCards();
 if(n)html+=`<section class="panel narrative-pair"><div><h3>기회 요인</h3><p>${esc(n.opportunity)}</p></div><div><h3>위험과 불확실성</h3><p>${esc(n.risk)}</p></div></section>`+narrativeDetails(n,company);
 if(company){html+=companyExtras(company);if(!n)html+=`<section class="panel">${Object.entries(company.topics||{}).map(([k,vs])=>`<h3>${esc(k)}</h3>${vs.map(v=>`<p>${esc(v)}</p>`).join('')}`).join('')}</section>`;}
 html+=`<p class="note">${esc(data.mode)} · 연간 재무와 최근 시세의 기간은 다릅니다. 대표 5사의 전사 재무이며 산업 전체 통계가 아닙니다. 미확인 수치는 —로 표시합니다. 시세·공시 수집: ${esc(data.market.fetched_at||'미수집')}${data.market.errors?.length?'<br>'+data.market.errors.map(esc).join(' · '):''}</p>`;
 $('#content').innerHTML=html;$('#metric-year').onchange=e=>{selectedYear=Number(e.target.value);const y=window.scrollY;render();window.scrollTo(0,y)};bindHelp();window.scrollTo(0,0);
}
$('#close-help').addEventListener('click',()=>$('#help').close());
window.addEventListener('hashchange',()=>data&&render());
fetch('/api/reports').then(r=>{if(!r.ok)throw new Error('보고서 파일을 먼저 생성해 주세요.');return r.json()}).then(value=>{data=value;render()}).catch(error=>{$('#content').innerHTML=`<h1>보고서를 준비해 주세요</h1><p>${esc(error.message)}</p><p>python -m snapdart.analyze 실행 후 새로고침하세요.</p>`});
