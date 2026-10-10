const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dialog=()=>document.getElementById('explain');
export function explain(title,body){
  document.getElementById('explain-title').textContent=title;
  document.getElementById('explain-content').innerHTML=body;
  if(!dialog().open)dialog().showModal();
}
function tableMarkup(source){
  if(!source?.table)return `<p class="popup-note">${escape(source?.note||'이 자료의 전체 원본 표가 연결되지 않았습니다.')}</p>${source?.source_text?`<p class="source-block">${escape(source.source_text)}</p>`:''}${source?.document_url?`<a class="source-link" href="${escape(source.document_url)}" target="_blank" rel="noopener noreferrer">DART 원문 전체 보기 ↗</a>`:''}`;
  const span=v=>Number.isInteger(v)&&v>0?v:1;
  return `<p>${escape(source.section)} / ${escape(source.heading)} · 원문 단위: ${escape(source.unit)}</p><div class="original-table-scroll"><table class="original-disclosure-table"><tbody>${source.table.rows.map(r=>'<tr>'+r.cells.map(c=>`<${c.header?'th':'td'} rowspan="${span(c.rowspan)}" colspan="${span(c.colspan)}" class="${c.highlight?'original-target':''}">${escape(c.text)}</${c.header?'th':'td'}>`).join('')+'</tr>').join('')}</tbody></table></div><a class="source-link" href="${escape(source.document_url)}" target="_blank" rel="noopener noreferrer">DART 원문 전체 보기 ↗</a>`;
}
export async function showSource(ref,sector){
  explain('공시 원문','<p>근거 문단을 불러오는 중입니다.</p>');dialog().classList.add('source-dialog');
  try{
    const response=await fetch('/api/source?'+new URLSearchParams({ref,sector}));if(!response.ok)throw new Error('각주 위치를 확인하지 못했습니다.');
    const value=await response.json();if(!dialog().open)return;
    explain(value.citation.company+' · '+value.citation.report_name,`<p class="popup-note">${escape(value.citation.period)} / ${escape(value.citation.section)} / ${escape(value.citation.heading)}</p>${value.document_html&&value.original_note?`<p class="popup-note">${escape(value.original_note)}</p>`:''}${value.document_html?`<iframe class="original-document-view" title="원본 공시 문서" sandbox="allow-same-origin" srcdoc="${escape(value.document_html)}"></iframe>`:`<p class="popup-note">${escape(value.original_note||'원본 XML을 불러오지 못했습니다.')}</p>`}${(value.blocks||[]).map(b=>{const text=b.highlight?escape(b.text.slice(0,b.highlight[0]))+'<mark>'+escape(b.text.slice(...b.highlight))+'</mark>'+escape(b.text.slice(b.highlight[1])):escape(b.text);return `<p class="source-block">${text}</p>`;}).join('')}${value.table?tableMarkup(value):`<a class="source-link" href="${escape(value.document_url)}" target="_blank" rel="noopener noreferrer">DART 원문 전체 보기 ↗</a>`}`);
    const frame=document.querySelector('.original-document-view');if(frame)frame.onload=()=>{try{frame.contentDocument.getElementById('evidence-target')?.scrollIntoView({block:'center'});}catch{}};
  }catch(error){explain('공시 원문',`<p>${escape(error.message)}</p>`);}
}
export async function showQuarterSource(company,period,key){
  const [year,q]=period.split(' ');const mapped=(company.metricProfile==='bank'?{revenue:'bank_growth',operating:'roe',capex:'credit_cost',fcf:'equity_ratio'}:{revenue:'revenue',operating:'operating_income',capex:company.metricProfile==='health'?'rd':'capex',fcf:'fcf'})[key];
  explain(company.name+' · '+period+' 원문','<p>분기 수치의 원본 표를 확인하는 중입니다.</p>');dialog().classList.add('source-dialog');
  try{
    const response=await fetch('/api/quarter-source?'+new URLSearchParams({sector:company.sectorId,code:company.code,year,quarter:q.slice(1),key:mapped}));
    if(!response.ok)throw new Error('분기 지표 출처를 확인하지 못했습니다.');const value=await response.json();if(!dialog().open)return;
    explain(company.name+' · '+period+' 원문',`<p class="popup-note">${escape(value.note)}</p>${value.components.map(c=>`<section class="source-component"><h3>${escape(c.reportType)} · ${escape(c.metric)}</h3><p>표준화 값: ${typeof c.value==='number'?c.value.toLocaleString('ko-KR')+'원':'자료 없음'}</p>${tableMarkup(c.source)}</section>`).join('')}`);
  }catch(error){explain('지표 원문',`<p>${escape(error.message)}</p>`);}
}
export function insightMarkup(insight,sector){
  if(typeof insight==='string')return escape(insight);
  let count=0;
  return (insight?.sentences||[]).map(s=>escape(s.text)+(s.source_refs||[]).map(ref=>`<sup><button class="citation" data-ref="${escape(ref)}" data-sector="${escape(sector)}" aria-label="공시 근거 ${count+1} 보기">${++count}</button></sup>`).join('')).join(' ')||escape(insight?.insufficient_reason||'재무·공시 기반 AI 인사이트가 아직 생성되지 않았습니다.');
}
export function bindCitations(){document.querySelectorAll('[data-ref]').forEach(b=>b.onclick=()=>showSource(b.dataset.ref,b.dataset.sector));}
