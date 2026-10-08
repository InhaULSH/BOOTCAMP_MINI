import {loadProject, number, marketCap, stockChange, direction, metricCatalog, metricSeries, financialPeriods} from './data.js';
import {empty, lineChart, wordCloud} from './charts.js';
import {explain as openExplanation, insightMarkup, bindCitations, showQuarterSource} from './sources.js';

const app=document.getElementById('app'),dialog=document.getElementById('explain');
const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const format=(value,unit='')=>number(value)?value.toLocaleString('ko-KR',{maximumFractionDigits:1})+unit:'—';
const percent=value=>number(value)?(value>0?'+':'')+value.toFixed(2)+'%':'—';
const companyUrl=id=>'company.html?company='+encodeURIComponent(id);
const industryUrl=id=>'industry.html?sector='+encodeURIComponent(id);
const palette=['#d85257','#367aba','#c89b36','#398d78','#9273ac'];
function safeSource(source){try{const url=new URL(source);return ['https:','http:'].includes(url.protocol)?url.href:null;}catch{return null;}}
function explain(title,body){dialog.classList.remove('source-dialog');openExplanation(title,body);}
let activeSubject;
function keywordExplanation(keyword){
  const sector=activeSubject.sectorId||activeSubject.id;
  const summary=keyword.insight;
  const content=(summary?.sentences?.length||summary?.insufficient_reason)?insightMarkup(summary,sector):
    keyword.disclosureContext?insightMarkup({sentences:[{text:keyword.disclosureContext,source_refs:keyword.source_refs||[]}]},sector):
    '짧은 용어 해설과 공시 요약이 아직 생성되지 않았습니다. 관련 공시와 재무 자료를 바탕으로 분석을 재생성하면 표시됩니다.';
  explain(keyword.label,`<strong class="popup-label">용어 해설 · 공시에서 확인한 내용</strong><p id="keyword-context" class="popup-body">${content}</p><p class="popup-note">공시 내용을 간접 인용한 요약입니다. 각주를 누르면 참고한 원문을 확인할 수 있습니다.</p>`);
  bindCitations();
}

document.getElementById('explain-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});

function renderHome(project){
  app.innerHTML=`<section class="intro"><p class="eyebrow">DISCOVER INDUSTRIES</p><h1>어떤 산업이 궁금한가요?</h1><p class="intro-description">숫자 너머의 사업 변화, 관심 있는 산업에서 시작하세요.</p></section><section class="sector-field" id="sector-field" aria-label="원의 면적은 전체 KRX 지수 구성종목 시가총액 합계에 비례하고, 색은 해당 지수 수익률"><div class="orbit-ring ring-one"></div><div class="orbit-ring ring-two"></div><div id="sector-nodes"></div><div class="field-legend"><span><i class="up-dot"></i>상승</span><span><i class="down-dot"></i>하락</span></div></section><section class="journey"><article><p class="eyebrow">01 / DISCOVER</p><h2>산업을 발견하고</h2><p>섹터 규모와 시장 움직임을 살펴봅니다.</p></article><article><p class="eyebrow">02 / UNDERSTAND</p><h2>변화를 이해하고</h2><p>성장·수익·투자·현금의 흐름을 읽습니다.</p></article><article><p class="eyebrow">03 / EXPLORE</p><h2>기업으로 깊이 들어갑니다</h2><p>기업의 사업과 재무, 공시를 확인합니다.</p></article></section>`;
  const field=document.getElementById('sector-field'),nodes=document.getElementById('sector-nodes');

  const sectors=project.sectors.map(s=>({...s,cap:marketCap(s)})).sort((a,b)=>(b.cap||0)-(a.cap||0));
  if(!sectors.length)return empty(nodes,'시가총액 데이터 연결 후 섹터가 표시됩니다.');
  const maxCap=Math.max(1,...sectors.map(s=>s.cap||0));
  // Color intensity is scaled to supplied index returns. It never averages company returns.
  const colorScale=Math.max(...sectors.map(s=>number(s.indexReturnPct)?Math.abs(s.indexReturnPct):0))||1;
  const tint=returnValue=>{if(!number(returnValue))return '#eef2ef';const t=Math.min(Math.abs(returnValue)/colorScale,1),base=[247,249,247],end=returnValue>=0?[227,159,167]:[155,189,219];return `rgb(${base.map((v,i)=>Math.round(v+(end[i]-v)*t)).join(',')})`;};
  sectors.forEach((s,i)=>{
    const node=document.createElement('a');node.href=industryUrl(s.id);node.className='sector-node'+(i===0?' primary':'');
    node.style.setProperty('--fill',tint(s.indexReturnPct));node.style.setProperty('--ink',number(s.indexReturnPct)?s.indexReturnPct>=0?'#84414c':'#365f83':'#718277');node.style.setProperty('--edge',number(s.indexReturnPct)?s.indexReturnPct>=0?'#d9abb3':'#b7cddf':'#dce5df');
    node.innerHTML=`<span class="sector-name">${escape(s.name)}</span><span class="sector-return">${percent(s.indexReturnPct)}</span><span class="sector-tooltip"><strong>${escape(s.name)}</strong><span class="tip-period">지수 수익률 <strong>${percent(s.indexReturnPct)}</strong></span><span>${escape(s.returnPeriod||'기간 미지정')}</span><span class="tip-row">전체 KRX 구성종목 시가총액 <strong>${number(s.cap)?format(s.cap)+' '+escape(s.marketCapUnit||project.marketCapUnit||''):'미수집'}</strong></span><span class="tip-row">분석 대상 기업 <strong>${(s.analysisCompanyIds||[]).length}개</strong></span><span class="tip-period">시가총액 기준일: ${escape(s.marketCapTradedAt||'미수집')}${s.marketCapStale?' · 갱신 실패로 저장값 표시':''}</span><span class="tip-action">${escape(s.statusMessage||'클릭하여 산업분석 보기')}</span></span>`;
    node.addEventListener('pointerenter',()=>node.classList.add('is-expanded'));node.addEventListener('pointerleave',()=>node.classList.remove('is-expanded'));if(!number(s.cap))node.classList.add('cap-unavailable');nodes.append(node);
  });
  const layout=()=>{
    const width=field.clientWidth,height=field.clientHeight,mobile=width<640;
    // This viewport bound is a presentation constraint. Relative areas are proportional to official whole-index market caps.
    const desiredBase=mobile?width*.62:Math.min(width*.3,height*.52);
    const positions=sectors.length>5?sectors.map((_,i)=>[50+34*Math.cos(2*Math.PI*i/sectors.length),50+34*Math.sin(2*Math.PI*i/sectors.length)]):mobile?[[50,46],[25,16],[75,16],[25,76],[75,76]]:[[50,48],[18,24],[82,24],[18,74],[82,74]];
    const points=positions.map(([x,y])=>[width*x/100,height*y/100]);
    const distances=points.flatMap((a,i)=>points.slice(i+1).map(b=>Math.hypot(a[0]-b[0],a[1]-b[1])));
    const base=Math.min(desiredBase,Math.min(...distances)*.9);
    field.style.setProperty('--core-size',base+'px');
    sectors.forEach((s,i)=>{const node=nodes.children[i],diameter=number(s.cap)&&s.cap>0?base*Math.sqrt(s.cap/maxCap):base*.8,radius=diameter/2,x=width*positions[i][0]/100,y=height*positions[i][1]/100,tipWidth=Math.min(290,width-24);
      node.style.setProperty('--size',diameter+'px');node.style.left=x+'px';node.style.top=y+'px';node.style.setProperty('--tip-width',tipWidth+'px');node.style.setProperty('--tip-left',(Math.max(12,Math.min(x-tipWidth/2,width-tipWidth-12))-x+radius)+'px');node.classList.toggle('tip-above',positions[i][1]>60);
      // On narrow viewports, keep labels accessible even when bubbles are compact.
      const compact=diameter<100;node.classList.toggle('is-compact',compact);node.querySelector('.sector-return').style.display=compact?'none':'';node.setAttribute('aria-label',s.name+' '+percent(s.indexReturnPct));
    });
  };
  new ResizeObserver(layout).observe(field);layout();
}

function metricCards(companies,periods){return Object.entries(metricCatalog).map(([key,m])=>`<article class="panel metric"><p class="metric-question">${escape(m.question)}</p><div class="panel-top"><div class="company-metric-heading"><h3>${escape(m.title)}</h3><button class="metric-help" data-help="${key}" aria-label="${escape(m.title)} 설명">?</button></div><div class="metric-summary"><small>${companies.length===1?'최근 분기':'최근 분기 중앙값'}</small><strong data-summary="${key}"></strong></div></div><p class="definition">${escape(m.formula)} · ${escape(m.unit)}</p><div class="chart" data-metric="${key}"></div><div class="legend"></div><div data-metric-insight="${key}"></div></article>`).join('');}
function renderAnalysis(project,subject,selectedCompanies,isCompany){
  const periods=subject.periods||financialPeriods(selectedCompanies);
  activeSubject=subject; const header=subject.name;
  const parent=project.sectors.find(s=>(s.analysisCompanyIds||[]).includes(subject.id));
  document.title=header+' | DART BIG:IN';
  app.innerHTML=`<a class="back" href="${isCompany&&parent?industryUrl(parent.id):'index.html'}">‹ ${isCompany&&parent?escape(parent.name)+' 산업분석':'한국 주요 시장'}</a><div class="title-row"><div><p class="eyebrow">${isCompany?'기업 상세분석':'산업분석'}</p><h1>${escape(header)}</h1><p class="company-subtitle">${escape(subject.businessSummary||'')}</p></div></div><section class="top-grid company-top"><article class="panel"><div class="panel-top"><h2>${escape(isCompany?subject.name:(subject.indexName||'섹터지수'))}</h2><span class="meta">${escape(subject.marketSeriesPeriod||'')}</span></div><div class="stock-heading"><strong id="market-value"></strong><span id="market-change"></span></div><div class="chart" id="market-chart"></div></article><article class="panel"><div class="panel-top"><h2>${isCompany?'기업 공시 클라우드':'공시 신호 워드클라우드'}</h2></div><p class="definition">키워드를 선택하여 용어 해설과 공시 내용을 살펴보세요.</p><div class="cloud" id="cloud"></div></article></section><section class="ai"><div class="ai-head"><div class="ai-title"><span class="ai-icon" aria-hidden="true">AI</span><h2>AI ${isCompany?'기업':'산업'} 인사이트</h2></div></div><p id="insight"></p></section>${isCompany?'<section class="detail-kpis" id="kpis"></section>':'<section><div class="section-head"><h2>분석 대상 기업</h2></div><div class="company-cards" id="company-cards"></div></section>'}<section><div class="section-head"><h2>주요 재무 지표 흐름</h2><span class="meta">${periods.length?escape(periods[0]+' - '+periods.at(-1)):''}</span></div><p class="metric-basis">매출 기준: ${periods.length?escape(periods[0])+' = 100':'기준 분기 데이터 미연결'}</p><div class="metrics-grid">${metricCards(selectedCompanies,periods)}</div></section>${isCompany?'':'<section class="panel comparison"><div class="panel-top"><h2>기업 한눈에 비교</h2></div><div class="table-wrap" tabindex="0" role="region" aria-label="기업 비교표"><table><thead><tr><th>기업</th>'+Object.values(metricCatalog).map(m=>'<th>'+escape(m.title)+'</th>').join('')+'<th>주가 · 전일 대비</th></tr></thead><tbody id="comparison"></tbody></table></div></section>'}`;
  const coverage=(isCompany?parent:subject)?.coverage;
  if(coverage&&(coverage.unbuilt_companies?.length||coverage.missing_chunk_companies?.length||coverage.incomplete_reports?.length)){
    const names=[...new Set([...(coverage.unbuilt_companies||[]),...(coverage.missing_chunk_companies||[])])];
    app.querySelector('.title-row').insertAdjacentHTML('afterend',`<p class="insight-basis">현재 공시 분석 대상은 데이터가 준비된 ${coverage.operational_count}개 기업입니다.${names.length?' 미연결 기업: '+names.map(escape).join(' · ')+'.':''}${coverage.incomplete_reports?.length?' 일부 보고서의 원천 자료가 없거나 확인 중입니다.':''}</p>`);
  }
  document.getElementById('insight').innerHTML=insightMarkup(subject.aiInsight,subject.sectorId||subject.id);bindCitations();
  document.getElementById('insight').insertAdjacentHTML('afterend','<p class="insight-basis">기존 인사이트는 연간·누적 공시 자료를 종합합니다. 아래 지표는 개별 분기 실적입니다.</p>');
  document.querySelector('#cloud').previousElementSibling.textContent='키워드를 눌러 용어 해설과 공시 내용을 확인하세요. 🔥는 최근 공시에서 언급이 늘어난 키워드입니다.';
  const series=Object.fromEntries(Object.keys(metricCatalog).map(key=>[key,selectedCompanies.map((c,i)=>({id:c.id,name:c.name,color:c.color||palette[i%palette.length],company:c,values:metricSeries(c,key,periods)}))]));
  document.querySelectorAll('[data-summary]').forEach(n=>n.parentElement.title='공통 최신 분기에 값이 있는 기업만 포함합니다.');
  const medians={};Object.entries(series).forEach(([key,sets])=>{const values=sets.map(s=>s.values.at(-1)).filter(number).sort((a,b)=>a-b);const middle=Math.floor(values.length/2);medians[key]=values.length?(values.length%2?values[middle]:(values[middle-1]+values[middle])/2):null;document.querySelector(`[data-summary="${key}"]`).textContent=format(medians[key],metricCatalog[key].unit==='%'?'%':'');const insight=subject.metricInsights?.[key];if(insight)document.querySelector(`[data-metric-insight="${key}"]`).innerHTML=`<div class="metric-insight"><small>AI 흐름 읽기</small><p>${escape(insight)}</p></div>`;});
  document.querySelectorAll('[data-help]').forEach(button=>button.addEventListener('click',()=>{const m=metricCatalog[button.dataset.help];explain(m.title,`<p class="popup-body">${escape(m.help)}</p><p class="popup-formula">${escape(m.formula)}</p>`);}));
  if(isCompany){const summary=subject.disclosureSummary;app.insertAdjacentHTML('beforeend',`<section class="panel disclosure-summary"><h2>공시에서 살펴본 내용</h2><div class="summary-columns"><article><h3>사업의 모습</h3><p>${escape(subject.businessSummary||'사업 개요가 연결되지 않았습니다.')}</p></article><article><h3>실적과 연결해 보기</h3><p>${insightMarkup(subject.aiInsight,subject.sectorId)}</p></article><article><h3>다음에 확인할 내용</h3><p>${escape(summary?.checks||'제공된 후속 확인 항목이 없습니다.')}</p></article></div></section>`);bindCitations();}
  if(isCompany)document.getElementById('kpis').innerHTML=Object.entries(metricCatalog).map(([key,m])=>`<article class="detail-kpi"><small>${escape(m.title)}</small><strong>${format(medians[key],m.unit==='%'?'%':'')}</strong><span>${escape(periods.at(-1)||'')}</span></article>`).join('');
  else {
    document.getElementById('company-cards').innerHTML=selectedCompanies.map(c=>`<a class="company-card" href="${companyUrl(c.id)}"><div class="company-name">${escape(c.name)}</div><div class="company-change ${direction(c.dailyReturnPct)}">${stockChange(c.dailyReturnPct)}</div><small>전일 대비 · 기업 분석 보기</small></a>`).join('');
    if(!selectedCompanies.length)empty(document.getElementById('company-cards'),'분석 대상 기업 데이터가 없습니다.');
    document.getElementById('comparison').innerHTML=selectedCompanies.map((c,i)=>`<tr><th>${escape(c.name)}</th>${Object.keys(metricCatalog).map(key=>'<td>'+format(series[key][i].values.at(-1),metricCatalog[key].unit==='%'?'%':'')+'</td>').join('')}<td class="${direction(c.dailyReturnPct)}">${stockChange(c.dailyReturnPct)}</td></tr>`).join('');
  }
  const rawMarketPoints=(isCompany?subject.stockSeries:subject.indexSeries)||[];
  const monthEnds=new Map();rawMarketPoints.forEach(p=>monthEnds.set(p.date.slice(0,7),p));
  const marketPoints=rawMarketPoints.length>80?[...monthEnds.values()]:rawMarketPoints;
  const marketMeta=document.querySelector('.company-top .meta');
  marketMeta.textContent=rawMarketPoints.length?rawMarketPoints[0].date+' - '+rawMarketPoints.at(-1).date+(rawMarketPoints.length>80?' · 월말·최신 종가':' · 종가'):'시세 미연결';
  const marketValue=document.getElementById('market-value');marketValue.textContent=format(marketPoints.at(-1)?.value,isCompany?'원':'pt');
  const change=document.getElementById('market-change');change.textContent=stockChange(isCompany?subject.dailyReturnPct:subject.indexReturnPct);change.className=direction(isCompany?subject.dailyReturnPct:subject.indexReturnPct);
  const selectedSeries=Object.fromEntries(Object.keys(metricCatalog).map(key=>[key,series[key][0]?.id]));
  const render=()=>{
    lineChart(document.getElementById('market-chart'),[{id:subject.id,name:subject.name,color:'#c96d75',values:marketPoints.map(p=>p.value)}],marketPoints.map(p=>p.date),{unit:isCompany?'원':'pt',label:subject.name+(isCompany?' 주가':' 지수')});
    const cloud=document.getElementById('cloud');
    cloud.style.height=document.getElementById('market-chart').clientHeight+'px';
    wordCloud(cloud,subject.keywords,keywordExplanation);
    Object.entries(metricCatalog).forEach(([key,m])=>{
      const container=document.querySelector(`[data-metric="${key}"]`);
      lineChart(container,series[key],periods,{quarterly:true,baseline:key==='revenue',unit:m.unit,label:m.title,describe:(s,i,v)=>{
        const row=(s.company.financials||[]).find(r=>r.period===periods[i]);
        let text=`${s.name}\n${periods[i]}\n${m.title}: ${format(v,m.unit==='%'?'%':'')}`;
        if(key==='revenue')text+='\n실제 매출액: '+format(row?.revenue, ' '+(s.company.amountUnit||'억원'));
        if(key==='operating')text+='\n실제 영업이익: '+format(row?.operatingProfit,' '+(s.company.amountUnit||'원'));
        if(key==='capex')text+='\nCAPEX: '+format(row?.capex,' '+(s.company.amountUnit||'억원'));
        if(key==='fcf')text+='\nFCF: '+format(number(row?.operatingCashFlow)&&number(row?.capex)?row.operatingCashFlow-row.capex:null,' '+(s.company.amountUnit||'억원'));
        return text;
      },onSelect:(s,i)=>showQuarterSource(s.company,periods[i],key)});
      const legend=container.nextElementSibling;legend.replaceChildren();
      const selectCompany=id=>{
        selectedSeries[key]=id;
        container.querySelectorAll('.chart-series').forEach(group=>{
          group.classList.toggle('is-highlighted',id!=null&&group.dataset.company===id);
          group.classList.toggle('is-muted',id!=null&&group.dataset.company!==id);
        });
        const selectedGroup=[...container.querySelectorAll('.chart-series')].find(group=>group.dataset.company===id);
        if(selectedGroup)selectedGroup.parentNode.append(selectedGroup);
        legend.querySelectorAll('.legend-item').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.company===id)));
      };
      series[key].forEach(s=>{
        const button=document.createElement('button');button.type='button';button.dataset.company=s.id;
        button.innerHTML=`<i style="--series:${s.color}"></i>${escape(s.name)}`;button.className='legend-item';
        button.setAttribute('aria-label',s.name+' 그래프 강조');
        button.addEventListener('click',()=>selectCompany(selectedSeries[key]===s.id?null:s.id));legend.append(button);
      });
      selectCompany(selectedSeries[key]);
    });
  };
  let observedWidth=0;new ResizeObserver(entries=>{if(entries[0].contentRect.width!==observedWidth){observedWidth=entries[0].contentRect.width;requestAnimationFrame(render);}}).observe(app);document.fonts.ready.then(render);
}

document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('chart-tip').hidden=true;});

async function boot(){
  try {
    const project=await loadProject(),page=document.body.dataset.page,params=new URLSearchParams(location.search);
    if(page==='index')renderHome(project);
    else if(page==='industry'){
      const sector=project.sectors.find(s=>s.id===params.get('sector'));
      if(!sector)empty(app,'해당 섹터 데이터가 없습니다. 메인페이지에서 섹터를 선택하세요.');
      else if(sector.status==='unavailable')empty(app,sector.name+' · '+sector.statusMessage);
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
