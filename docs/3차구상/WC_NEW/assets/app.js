import {loadProject, number, marketCap, stockChange, direction, metricCatalog, metricSeries, financialPeriods} from './data.js';
import {empty, lineChart, wordCloud} from './charts.js';

const app=document.getElementById('app'),dialog=document.getElementById('explain');
const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const format=(value,unit='')=>number(value)?value.toLocaleString('ko-KR',{maximumFractionDigits:1})+unit:'—';
const percent=value=>number(value)?(value>0?'+':'')+value.toFixed(2)+'%':'—';
const companyUrl=id=>'company.html?company='+encodeURIComponent(id);
const industryUrl=id=>'industry.html?sector='+encodeURIComponent(id);
const palette=['#d85257','#367aba','#c89b36','#398d78','#9273ac'];
function safeSource(source){try{const url=new URL(source);return ['https:','http:'].includes(url.protocol)?url.href:null;}catch{return null;}}
function explain(title,body){document.getElementById('explain-title').textContent=title;document.getElementById('explain-content').innerHTML=body;dialog.showModal();}
function keywordExplanation(keyword){
  const source=safeSource(keyword.sourceUrl);
  explain(keyword.label,`<strong class="popup-label">공시에서 확인한 내용</strong><p class="popup-body">${escape(keyword.disclosureContext||'공시 맥락이 아직 연결되지 않았습니다.')}</p><strong class="popup-label">주요 키워드로 선정한 이유</strong><p class="popup-body">${escape(keyword.selectionReason||'선정 이유가 아직 연결되지 않았습니다.')}</p>${source?`<a class="source-link" href="${escape(source)}" target="_blank" rel="noopener noreferrer">관련 공시 원문</a>`:''}`);
}
document.getElementById('explain-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});

function renderHome(project){
  app.innerHTML=`<section class="intro"><p class="eyebrow">DISCOVER INDUSTRIES</p><h1>어떤 산업이 궁금한가요?</h1><p class="intro-description">숫자 너머의 사업 변화, 관심 있는 산업에서 시작하세요.</p></section><section class="sector-field" id="sector-field" aria-label="원의 면적은 KRX 섹터지수 전체 구성종목 시가총액 합계, 색은 해당 지수 수익률"><div class="orbit-ring ring-one"></div><div class="orbit-ring ring-two"></div><div id="sector-nodes"></div><div class="field-legend"><span><i class="up-dot"></i>상승</span><span><i class="down-dot"></i>하락</span></div></section><p class="interaction-hint">관심 있는 원에 마우스를 올리면 세부 정보를 볼 수 있어요.</p><div class="data-guide"><span>면적 · KRX 섹터지수 전체 구성종목의 시가총액 합계</span><span>색 · KRX 섹터지수 수익률</span></div><section class="journey"><article><p class="eyebrow">01 / DISCOVER</p><h2>산업을 발견하고</h2><p>섹터 규모와 시장 움직임을 살펴봅니다.</p></article><article><p class="eyebrow">02 / UNDERSTAND</p><h2>변화를 이해하고</h2><p>성장·수익·투자·현금의 흐름을 읽습니다.</p></article><article><p class="eyebrow">03 / EXPLORE</p><h2>기업으로 깊이 들어갑니다</h2><p>기업의 사업과 재무, 공시를 확인합니다.</p></article></section>`;
  const field=document.getElementById('sector-field'),nodes=document.getElementById('sector-nodes');
  const sectors=project.sectors.map(s=>({...s,cap:marketCap(s)})).filter(s=>number(s.cap)&&s.cap>0).sort((a,b)=>b.cap-a.cap).slice(0,5);
  if(!sectors.length)return empty(nodes,'시가총액 데이터 연결 후 섹터가 표시됩니다.');
  const maxCap=Math.max(...sectors.map(s=>s.cap));
  // Color intensity is scaled to supplied index returns. It never averages company returns.
  const colorScale=Math.max(...sectors.map(s=>number(s.indexReturnPct)?Math.abs(s.indexReturnPct):0))||1;
  const tint=returnValue=>{if(!number(returnValue))return '#eef2ef';const t=Math.min(Math.abs(returnValue)/colorScale,1),base=[247,249,247],end=returnValue>=0?[227,159,167]:[155,189,219];return `rgb(${base.map((v,i)=>Math.round(v+(end[i]-v)*t)).join(',')})`;};
  sectors.forEach((s,i)=>{
    const node=document.createElement('a');node.href=industryUrl(s.id);node.className='sector-node'+(i===0?' primary':'');
    node.style.setProperty('--fill',tint(s.indexReturnPct));node.style.setProperty('--ink',number(s.indexReturnPct)?s.indexReturnPct>=0?'#84414c':'#365f83':'#718277');node.style.setProperty('--edge',number(s.indexReturnPct)?s.indexReturnPct>=0?'#d9abb3':'#b7cddf':'#dce5df');
    node.innerHTML=`<span class="sector-name">${escape(s.name)}</span><span class="sector-return">${percent(s.indexReturnPct)}</span><span class="sector-tooltip"><strong>${escape(s.name)}</strong><span class="tip-period">지수 수익률 <strong>${percent(s.indexReturnPct)}</strong></span><span>${escape(s.returnPeriod||'기간 미지정')}</span><span class="tip-row">전체 구성종목 시가총액 <strong>${format(s.cap)} ${escape(s.marketCapUnit||project.marketCapUnit||'')}</strong></span><span class="tip-row">분석 대상 기업 <strong>${(s.analysisCompanyIds||[]).length}개</strong></span><span class="tip-action">클릭하여 산업분석 보기</span></span>`;
    node.addEventListener('pointerenter',()=>node.classList.add('is-expanded'));node.addEventListener('pointerleave',()=>node.classList.remove('is-expanded'));nodes.append(node);
  });
  const layout=()=>{
    const width=field.clientWidth,height=field.clientHeight,mobile=width<640;
    // This viewport bound is a presentation constraint. Relative areas come entirely from market caps.
    const desiredBase=mobile?width*.62:Math.min(width*.3,height*.52);
    const positions=mobile?[[50,46],[25,16],[75,16],[25,76],[75,76]]:[[50,48],[18,24],[82,24],[18,74],[82,74]];
    const points=positions.map(([x,y])=>[width*x/100,height*y/100]);
    const distances=points.flatMap((a,i)=>points.slice(i+1).map(b=>Math.hypot(a[0]-b[0],a[1]-b[1])));
    const base=Math.min(desiredBase,Math.min(...distances)*.9);
    field.style.setProperty('--core-size',base+'px');
    sectors.forEach((s,i)=>{const node=nodes.children[i],diameter=base*Math.sqrt(s.cap/maxCap),radius=diameter/2,x=width*positions[i][0]/100,y=height*positions[i][1]/100,tipWidth=Math.min(290,width-24);
      node.style.setProperty('--size',diameter+'px');node.style.left=x+'px';node.style.top=y+'px';node.style.setProperty('--tip-width',tipWidth+'px');node.style.setProperty('--tip-left',(Math.max(12,Math.min(x-tipWidth/2,width-tipWidth-12))-x+radius)+'px');node.classList.toggle('tip-above',positions[i][1]>60);
      // Extremely small market shares remain true to area, while accessible hover/focus details retain their labels.
      const compact=diameter<100;node.querySelector('.sector-name').style.display=compact?'none':'';node.querySelector('.sector-return').style.display=compact?'none':'';node.setAttribute('aria-label',s.name+' '+percent(s.indexReturnPct));
    });
  };
  new ResizeObserver(layout).observe(field);layout();
}

function metricCards(companies,periods){return Object.entries(metricCatalog).map(([key,m])=>`<article class="panel metric"><p class="metric-question">${escape(m.question)}</p><div class="panel-top"><div class="company-metric-heading"><h3>${escape(m.title)}</h3><button class="metric-help" data-help="${key}" aria-label="${escape(m.title)} 설명">?</button></div><div class="metric-summary"><small>${companies.length===1?'최근 분기':'최근 분기 중앙값'}</small><strong data-summary="${key}"></strong></div></div><p class="definition">${escape(m.formula)} · ${escape(m.unit)}</p><div class="chart" data-metric="${key}"></div><div class="legend"></div><div data-metric-insight="${key}"></div></article>`).join('');}
function renderAnalysis(project,subject,selectedCompanies,isCompany){
  const periods=isCompany?financialPeriods(selectedCompanies):(subject.periods||financialPeriods(selectedCompanies));
  const header=isCompany?subject.name:subject.name+' 산업분석';
  const parent=project.sectors.find(s=>(s.analysisCompanyIds||[]).includes(subject.id));
  document.title=header+' | DART BIG:IN';
  app.innerHTML=`<a class="back" href="${isCompany&&parent?industryUrl(parent.id):'index.html'}">‹ ${isCompany&&parent?escape(parent.name)+' 산업분석':'한국 주요 시장'}</a><div class="title-row"><div><p class="eyebrow">${isCompany?'기업 상세분석':'산업분석'}</p><h1>${escape(header)}</h1><p class="company-subtitle">${escape(subject.businessSummary||'')}</p></div></div><section class="top-grid company-top"><article class="panel"><div class="panel-top"><h2>${escape(isCompany?subject.name:(subject.indexName||'섹터지수'))}</h2><span class="meta">${escape(subject.marketSeriesPeriod||'')}</span></div><div class="stock-heading"><strong id="market-value"></strong><span id="market-change"></span></div><div class="chart" id="market-chart"></div></article><article class="panel"><div class="panel-top"><h2>${isCompany?'기업 공시 클라우드':'공시 신호 워드클라우드'}</h2></div><p class="definition">키워드를 선택하여 공시 내용과 중요도 선정 이유를 살펴보세요.</p><div class="cloud" id="cloud"></div></article></section><section class="ai"><div class="ai-head"><div class="ai-title"><span class="ai-icon" aria-hidden="true">🤖</span><h2>AI ${isCompany?'기업':'산업'} 인사이트</h2></div></div><p id="insight"></p></section>${isCompany?'<section class="detail-kpis" id="kpis"></section>':'<section><div class="section-head"><h2>분석 대상 기업</h2></div><div class="company-cards" id="company-cards"></div></section>'}<section><div class="section-head"><h2>주요 재무 지표 흐름</h2><span class="meta">${periods.length?escape(periods[0]+' – '+periods.at(-1)):''}</span></div><p class="metric-basis">매출 기준: ${periods.length?escape(periods[0])+' = 100':'기준 분기 데이터 미연결'}</p><div class="metrics-grid">${metricCards(selectedCompanies,periods)}</div></section>${isCompany?'':'<section class="panel comparison"><div class="panel-top"><h2>기업 한눈에 비교</h2></div><div class="table-wrap" tabindex="0" role="region" aria-label="기업 비교표"><table><thead><tr><th>기업</th>'+Object.values(metricCatalog).map(m=>'<th>'+escape(m.title)+'</th>').join('')+'<th>주가 · 전일 대비</th></tr></thead><tbody id="comparison"></tbody></table></div></section>'}`;
  document.getElementById('insight').textContent=subject.aiInsight||'재무·공시 기반 AI 인사이트가 아직 연결되지 않았습니다.';
  const series=Object.fromEntries(Object.keys(metricCatalog).map(key=>[key,selectedCompanies.map((c,i)=>({id:c.id,name:c.name,color:c.color||palette[i%palette.length],company:c,values:metricSeries(c,key,periods)}))]));
  const medians={};Object.entries(series).forEach(([key,sets])=>{const values=sets.map(s=>s.values.at(-1)).filter(number).sort((a,b)=>a-b);const middle=Math.floor(values.length/2);medians[key]=values.length?(values.length%2?values[middle]:(values[middle-1]+values[middle])/2):null;document.querySelector(`[data-summary="${key}"]`).textContent=format(medians[key],metricCatalog[key].unit==='%'?'%':'');const insight=subject.metricInsights?.[key];if(insight)document.querySelector(`[data-metric-insight="${key}"]`).innerHTML=`<div class="metric-insight"><small>AI 흐름 읽기</small><p>${escape(insight)}</p></div>`;});
  document.querySelectorAll('[data-help]').forEach(button=>button.addEventListener('click',()=>{const m=metricCatalog[button.dataset.help];explain(m.title,`<p class="popup-body">${escape(m.help)}</p><p class="popup-formula">${escape(m.formula)}</p>`);}));
  if(isCompany)document.getElementById('kpis').innerHTML=Object.entries(metricCatalog).map(([key,m])=>`<article class="detail-kpi"><small>${escape(m.title)}</small><strong>${format(medians[key],m.unit==='%'?'%':'')}</strong><span>${escape(periods.at(-1)||'')}</span></article>`).join('');
  else {
    document.getElementById('company-cards').innerHTML=selectedCompanies.map(c=>`<a class="company-card" href="${companyUrl(c.id)}"><div class="company-name">${escape(c.name)}</div><div class="company-change ${direction(c.dailyReturnPct)}">${stockChange(c.dailyReturnPct)}</div><small>전일 대비 · 기업 분석 보기</small></a>`).join('');
    if(!selectedCompanies.length)empty(document.getElementById('company-cards'),'분석 대상 기업 데이터가 없습니다.');
    document.getElementById('comparison').innerHTML=selectedCompanies.map((c,i)=>`<tr><th>${escape(c.name)}</th>${Object.keys(metricCatalog).map(key=>'<td>'+format(series[key][i].values.at(-1),metricCatalog[key].unit==='%'?'%':'')+'</td>').join('')}<td class="${direction(c.dailyReturnPct)}">${stockChange(c.dailyReturnPct)}</td></tr>`).join('');
  }
  const marketPoints=(isCompany?subject.stockSeries:subject.indexSeries)||[];
  const marketValue=document.getElementById('market-value');marketValue.textContent=format(marketPoints.at(-1)?.value,isCompany?'원':'pt');
  const change=document.getElementById('market-change');change.textContent=stockChange(isCompany?subject.dailyReturnPct:subject.indexReturnPct);change.className=direction(isCompany?subject.dailyReturnPct:subject.indexReturnPct);
  const render=()=>{
    lineChart(document.getElementById('market-chart'),[{id:subject.id,name:subject.name,color:'#c96d75',values:marketPoints.map(p=>p.value)}],marketPoints.map(p=>p.date),{unit:isCompany?'원':'pt',label:subject.name+(isCompany?' 주가':' 지수')});
    wordCloud(document.getElementById('cloud'),subject.keywords,keywordExplanation);
    Object.entries(metricCatalog).forEach(([key,m])=>{
      const container=document.querySelector(`[data-metric="${key}"]`);
      lineChart(container,series[key],periods,{quarterly:true,baseline:key==='revenue',unit:m.unit,label:m.title,describe:(s,i,v)=>{
        const row=(s.company.financials||[]).find(r=>r.period===periods[i]);
        let text=`${s.name}\n${periods[i]}\n${m.title}: ${format(v,m.unit==='%'?'%':'')}`;
        if(key==='revenue')text+='\n실제 매출액: '+format(row?.revenue, ' '+(s.company.amountUnit||'억원'));
        if(key==='capex')text+='\nCAPEX: '+format(row?.capex,' '+(s.company.amountUnit||'억원'));
        if(key==='fcf')text+='\nFCF: '+format(number(row?.operatingCashFlow)&&number(row?.capex)?row.operatingCashFlow-row.capex:null,' '+(s.company.amountUnit||'억원'));
        return text;
      }});
      const legend=container.nextElementSibling;legend.replaceChildren();
      series[key].forEach(s=>{const button=document.createElement('button');button.type='button';button.innerHTML=`<i style="--series:${s.color}"></i>${escape(s.name)}`;button.className='legend-item';
        const highlight=()=>container.querySelectorAll('.chart-series').forEach(group=>{group.classList.toggle('is-highlighted',group.dataset.company===s.id);group.classList.toggle('is-muted',group.dataset.company!==s.id);});
        const clear=()=>container.querySelectorAll('.chart-series').forEach(group=>group.classList.remove('is-highlighted','is-muted'));
        button.addEventListener('pointerenter',highlight);button.addEventListener('pointerleave',clear);button.addEventListener('focus',highlight);button.addEventListener('blur',clear);legend.append(button);
      });
    });
  };
  let observedWidth=0;new ResizeObserver(entries=>{if(entries[0].contentRect.width!==observedWidth){observedWidth=entries[0].contentRect.width;requestAnimationFrame(render);}}).observe(app);document.fonts.ready.then(render);
}

async function boot(){
  try {
    const project=await loadProject(),page=document.body.dataset.page,params=new URLSearchParams(location.search);
    if(page==='index')renderHome(project);
    else if(page==='industry'){
      const sector=project.sectors.find(s=>s.id===params.get('sector'));
      if(!sector)empty(app,'해당 섹터 데이터가 없습니다. 메인페이지에서 섹터를 선택하세요.');
      else renderAnalysis(project,sector,(sector.analysisCompanyIds||[]).map(id=>project.companies.find(c=>c.id===id)).filter(Boolean),false);
    }else{
      const company=project.companies.find(c=>c.id===params.get('company'));
      if(!company)empty(app,'해당 기업 데이터가 없습니다. 산업분석에서 기업을 선택하세요.');
      else renderAnalysis(project,company,[company],true);
    }
  }catch(error){empty(app,error.message);}
  finally{app.setAttribute('aria-busy','false');}
}
boot();
