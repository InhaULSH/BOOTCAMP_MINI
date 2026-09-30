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
function narrativeIntro(n){return `<section class="panel ai-overview"><div class="eyebrow">GEMINI 3.5 FLASH-LITE ${help('AI 분석')}</div><h2>사업 흐름을 읽는 핵심</h2><p class="lead">${esc(n.summary)}</p><div class="narrative-pair"><div><h3>기회 요인</h3><p>${esc(n.opportunity)}</p></div><div><h3>위험과 불확실성</h3><p>${esc(n.risk)}</p></div></div></section>`;}
function narrativeDetails(n,company){return heading(company?'표본과 비교해 읽기':'공통 흐름과 기업별 차이')+`<section class="panel"><p class="comparison">${esc(n.comparison)}</p></section>`+heading('5년간 사업은 어떻게 달라졌나',`공시 서술 단계는 AI의 보조 해석 ${help('공시 서술 단계')}`)+`<section class="panel timeline">${n.timeline.map(t=>`<article class="year-row"><strong>${t.year}</strong><div><span class="badge">${esc(t.stage)}</span><p>${esc(t.summary)}</p></div></article>`).join('')}</section>`+heading('앞으로 확인할 변화')+`<section class="panel"><ul class="watch-list">${n.checks.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></section>`;}
function chart(series,key,benchmark=null,relative=false){
 const values=[...series,...(benchmark||[])].map(x=>x[key]).filter(valid);
 if(!values.length)return '<div class="empty">표시할 수 있는 수치가 없습니다.</div>';
 let lo=Math.min(0,...values),hi=Math.max(0,...values); if(hi===lo)hi=lo+1;
 const span=hi-lo; if(relative){lo=0;hi=100;}else{lo-=span*.12;hi+=span*.12;}
 const x=i=>60+i*115, y=v=>175-(v-lo)/(hi-lo)*145;
 const lines=Array.from({length:4},(_,i)=>{const v=lo+(hi-lo)*i/3;return `<line class="gridline" x1="60" x2="520" y1="${y(v)}" y2="${y(v)}"/><text x="48" y="${y(v)+4}" text-anchor="end">${key==='fcf'?money(v):v.toFixed(0)+'%'}</text>`}).join('');
 function path(rows,color){let d='',connected=false;rows.forEach((r,i)=>{if(valid(r[key])){d+=`${connected?'L':'M'}${x(i)},${y(r[key])} `;connected=true;}else connected=false;});return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5"/>`+rows.map((r,i)=>valid(r[key])?`<circle cx="${x(i)}" cy="${y(r[key])}" r="4" fill="${color}"><title>${r.year}: ${pct(r[key])}</title></circle>`:'').join('');}
 return `<svg class="chart" viewBox="0 0 560 210" role="img" aria-label="연도별 지표 추이">${lines}${benchmark?path(benchmark,'#b2bdcf'):''}${path(series,'#315ddd')}${series.map((r,i)=>`<text x="${x(i)}" y="202" text-anchor="middle">${r.year}</text>`).join('')}</svg>`;
}
const options = '<option value="revenue_growth">매출 성장률</option><option value="margin">영업이익률</option><option value="capex_ratio">CAPEX / 매출</option><option value="inventory_growth">재고 증가율</option>';
function render(){
 const code=location.hash.replace('#','');const company=data.companies.find(c=>c.code===code);
 const narrative=company?company.llm:data.llm;
 $('#companies').innerHTML=data.companies.map(c=>`<a href="#${c.code}" class="${company?.code===c.code?'active':''}">${esc(c.name)}</a>`).join('');
 $('.nav').classList.toggle('active',!company);
 const row=(company?company.history:data.industry).at(-1);
 let html=`<div class="intro"><div><div class="eyebrow">${company?'COMPANY':'INDUSTRY'} REPORT</div><h1>${company?esc(company.name):'반도체 사업 분석'}</h1><p class="subtitle">${company?esc(company.description):'기업 공시 속 숫자와 문장을 연결해, 사업의 변화를 살펴봅니다.'}</p></div><span class="badge">${company?esc(company.sector):'실증용 5개 기업 표본'}</span></div><div class="tabs"><a href="#industry" class="${!company?'selected':''}">산업 분석</a><a href="#${company?.code||data.companies[0].code}" class="${company?'selected':''}">기업 분석</a></div>`;
 if(narrative) html+=narrativeIntro(narrative);
 html+=`<div class="metrics">${metric('매출 성장률',pct(row.revenue_growth),company?'직전 사업연도 대비':`표본 중앙값 · ${row.revenue_growth_n}/5개 기업`)}${metric('영업이익률',pct(row.margin),company?'매출 대비 영업이익':`표본 중앙값 · ${row.margin_n}/5개 기업`)}${metric('CAPEX / 매출',pct(row.capex_ratio),company?'현금 유형자산 취득 기준':`표본 중앙값 · ${row.capex_ratio_n}/5개 기업`)}${metric('단순 FCF',money(row.fcf)+' <small style="font-size:12px">억 원</small>',company?'영업현금흐름 − 유형자산 취득':`표본 중앙값 · ${row.fcf_n}/5개 기업`)}</div>`;
 html+=`<div class="grid"><section class="panel"><div class="section-head" style="margin-top:0"><h2>5년의 흐름</h2><select id="chart-metric" aria-label="추이 지표 선택">${company?'<option value="position_margin">영업이익률 상대 위치</option><option value="position_revenue_growth">매출 성장률 상대 위치</option>':''}${options}</select></div><div id="chart"></div><div class="legend"><span><i></i>${company?esc(company.name):'표본 중앙값'}</span>${company?'<span><i class="gray"></i>표본 중앙값</span>':''}</div></section><section class="panel"><h2>${company?'표본 내 상대 위치':'함께 나타나는 변화'}${help(company?'상대 위치':'중앙값')}</h2><p class="small">${company?'큰 값일수록 오른쪽 · 투자 매력도 순위 아님':'전년 대비 증가한 기업 / 비교 가능한 기업'}</p>`;
 if(company){html+= [['revenue_growth','매출 성장률'],['margin','영업이익률'],['capex_ratio','CAPEX / 매출'],['inventory_growth','재고 증가율']].map(([k,label])=>`<div class="position"><span>${label}</span><div class="rail">${valid(row.positions[k])?`<b style="left:${row.positions[k]}%"></b>`:''}</div><em>${valid(row.positions[k])?row.positions[k].toFixed(0)+'%':'—'}</em></div>`).join('');html+='<div class="small">낮음 <span style="float:right">높음</span></div>';}else{html+=data.signals.map(s=>`<div class="signal"><div class="signal-row"><span>${s.title} 증가</span><strong>${s.positive} / ${s.count}개</strong></div><div class="track"><span style="width:${s.count?s.positive/s.count*100:0}%"></span></div><p class="small">증가율 중앙값 ${pct(s.median)}</p></div>`).join('');}
 html+='</section></div>';
 if(company){html+=heading('사업 변화 읽기',narrative?'공시와 재무를 연결한 AI 분석':'수치 기반 관찰과 해석')+cards(narrative?.cards || company.insights);
 if(!narrative) html+=heading('공시에서 읽은 사업 동향',`사업 내용의 주제별 문장 추출 ${help('공시 표현')}`)+`<section class="panel">${Object.entries(company.topics).map(([topic,texts])=>`<div class="topic"><strong>${esc(topic)}</strong>${texts.length?texts.slice(0,2).map(t=>`<p>${esc(t)}</p>`).join(''):'<p>선택 조건에 해당하는 문장이 검출되지 않았습니다.</p>'}</div>`).join('')||'<p>추출된 사업 내용이 없습니다.</p>'}</section>`;
 html+=heading('연도별 재무 요약','단위: 억 원, %')+`<section class="panel table-wrap"><table><thead><tr><th>사업연도</th><th>기준</th><th>매출</th><th>영업이익률</th><th>유형자산 취득</th><th>단순 FCF</th></tr></thead><tbody>${company.history.map(r=>`<tr><td>${r.year}</td><td>${r.basis==='CFS'?'연결':r.basis==='OFS'?'별도':'—'}</td><td>${money(r.revenue)}</td><td>${pct(r.margin)}</td><td>${money(r.capex)}</td><td>${money(r.fcf)}</td></tr>`).join('')}</tbody></table></section>`;
 }else{
 const s=data.signals;
 html+=heading('사업 흐름 요약','확인된 내용 → 변화 신호 → 해석')+cards(narrative?.cards || [
 {title:'매출 변화의 폭',signal:s[0].count?`${s[0].positive}/${s[0].count}개 기업 매출 증가`:'자료 부족',fact:`표본의 매출 성장률 중앙값은 ${pct(row.revenue_growth)}입니다.`,interpretation:'기업별 규모와 제품군이 다르므로 공통 수요 회복으로 단정할 수 없습니다. 메모리·위탁생산·장비의 차이를 개별 보고서에서 함께 확인합니다.'},
 {title:'투자와 현금의 균형',signal:s[1].count?`${s[1].positive}/${s[1].count}개 기업 유형자산 취득 증가`:'자료 부족',fact:`CAPEX / 매출 중앙값 ${pct(row.capex_ratio)}, 단순 FCF 중앙값 ${money(row.fcf)}억 원입니다.`,interpretation:'설비 취득 증가가 향후 생산 확대에 기여할 수 있지만, 수요가 뒤따르지 않으면 현금 부담으로 이어질 수 있습니다.'},
 {title:'재고 흐름 점검',signal:s[2].count?`${s[2].positive}/${s[2].count}개 기업 재고 증가`:'자료 부족',fact:`재고자산 증가율 중앙값은 ${pct(row.inventory_growth)}입니다.`,interpretation:'재고는 생산 준비와 판매 둔화 모두의 영향을 받습니다. 매출 흐름과 함께 살펴야 하며 증가 자체를 위험으로 확정하지 않습니다.'}]);
 html+=heading('기업별 한눈에 보기','기업을 선택하면 상세 보고서로 이동합니다')+`<section class="panel table-wrap"><table><thead><tr><th>기업</th><th>매출 성장률</th><th>영업이익률</th><th>CAPEX / 매출</th><th>단순 FCF · 억 원</th></tr></thead><tbody>${data.companies.map(c=>{const r=c.history.at(-1);return `<tr><td><a href="#${c.code}">${esc(c.name)} ↗</a><span class="small">${esc(c.sector)}</span></td><td>${pct(r.revenue_growth)}</td><td>${pct(r.margin)}</td><td>${pct(r.capex_ratio)}</td><td>${money(r.fcf)}</td></tr>`;}).join('')}</tbody></table></section>`;
 if(!narrative) html+=heading('공시 표현의 변화',`관련 문장이 검출된 기업 수 ${help('공시 표현')}`)+`<section class="panel table-wrap"><table><thead><tr><th>주제</th>${data.years.map(y=>`<th>${y}</th>`).join('')}</tr></thead><tbody>${['AI·고부가 제품','수요·시장','생산·투자','위험 요인'].map(t=>`<tr><td>${t}</td>${data.diffusion.map(d=>`<td>${d.topics[t]} / ${d.count}</td>`).join('')}</tr>`).join('')}</tbody></table><p class="small">문장 검출은 수요 발생·투자 실행을 뜻하지 않습니다. 미검출도 해당 사업이나 위험의 부재를 뜻하지 않습니다.</p></section>`;
 }
 if(narrative?.timeline) html+=narrativeDetails(narrative,company);
 html+=`<div class="note">${esc(data.mode)} · 누락 수치는 —로 표시합니다. ${company?'':'지정된 5개 기업을 실증 표본으로 사용합니다. '}${data.companies.reduce((n,c)=>n+c.report_count,0)}개 정기보고서 수집.</div>`;
 $('#content').innerHTML=html;
 const update=()=>{
  const key=$('#chart-metric').value;
  const relative=key.startsWith('position_');
  const metricKey=relative?key.slice(9):key;
  const series=relative?company.history.map(r=>({year:r.year,[metricKey]:r.positions[metricKey]})):(company?company.history:data.industry);
  $('#chart').innerHTML=chart(series,metricKey,company&&!relative?data.industry:null,relative);
  $('#chart').nextElementSibling.innerHTML=relative?'<span><i></i>표본 내 상대 위치 · 백분위</span>':`<span><i></i>${company?esc(company.name):'표본 중앙값'}</span>${company?'<span><i class="gray"></i>표본 중앙값</span>':''}`;
 };
 $('#chart-metric').addEventListener('change',update);update();
 document.querySelectorAll('[data-help]').forEach(button=>button.addEventListener('click',()=>{$('#help-title').textContent=button.dataset.help;$('#help-body').textContent=tips[button.dataset.help];$('#help').showModal();}));
 window.scrollTo(0,0);
}
$('#close-help').addEventListener('click',()=>$('#help').close());
window.addEventListener('hashchange',()=>data&&render());
fetch('/api/reports').then(r=>{if(!r.ok)throw new Error('보고서 파일을 먼저 생성해 주세요.');return r.json();}).then(value=>{data=value;render();}).catch(error=>{$('#content').innerHTML=`<h1>보고서를 준비해 주세요</h1><p>${esc(error.message)}</p><p>프로젝트 폴더에서 python -m snapdart.analyze 실행 후 새로고침하세요.</p>`;});
