const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('web/assets/app.js','utf8');
const code=source.slice(source.indexOf('let activeSubject,'),source.indexOf("document.getElementById('explain-close')"));
let nodes={},body='',calls=[],responses=[];
const context=vm.createContext({
 document:{getElementById:id=>nodes[id]||null},dialog:{open:true},
 URLSearchParams,JSON,Boolean,Math,String,
 escape:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
 safeSource:v=>v.startsWith('https://')?v:null,
 insightMarkup:s=>s.sentences.map(x=>x.text).join(' '),bindCitations:()=>{},
 explain:(title,html)=>{body=html;nodes={};for(const match of html.matchAll(/id="([^"]+)"/g))nodes[match[1]]={disabled:false,textContent:'',innerHTML:''};},
 fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>responses.shift()};},
 setTimeout:()=>{},
});
vm.runInContext(code,context);
const open=(reason,retryable)=>{
 context.keyword={keyword:'HBM',label:'HBM',insight:{sentences:[],fallback_reason:reason,retryable}};
 vm.runInContext("activeSubject={id:'sector'};keywordExplanation(keyword)",context);
};
(async()=>{
 open('verification',false);
 assert(body.includes('최근 공시에서 의미 있게 포착된 키워드이지만, 설명과 근거의 일치 여부를 충분히 확인하지 못했습니다.'));
 assert(body.includes('대신 이 키워드와 관련된 공시를 직접 살펴보시겠어요?'));
 assert(!body.includes('산업 인사이트와 기업별 분석 보기'));
 assert(!nodes['keyword-retry']);
 responses.push({documents:[{company:'기업가',year:2025,report_name:'사업보고서',document_url:'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250301000001'}]});
 await nodes['keyword-filings'].onclick();
 assert(nodes['keyword-filing-list'].innerHTML.includes('기업가'));
 assert(nodes['keyword-filing-list'].innerHTML.includes('target="_blank"'));
 assert.equal(nodes['keyword-filings'].disabled,false);
 open('unavailable',true);
 assert(nodes['keyword-retry']);
 responses.push({insight:{sentences:[{text:'재시도 성공',source_refs:[]}]}});
 await nodes['keyword-retry'].onclick();
 assert.equal(calls.at(-1).options.method,'POST');
 assert.equal(JSON.parse(calls.at(-1).options.body).keyword,'HBM');
 assert(body.includes('재시도 성공'));assert(!nodes['keyword-retry']);
 open('configuration',false);assert(!nodes['keyword-retry']);
 console.log('PASS: keyword popup messages, disclosure list, transient-only retry and success rendering.');
})().catch(error=>{console.error(error);process.exitCode=1;});
