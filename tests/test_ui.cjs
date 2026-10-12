const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
 // 화면 모듈의 구문 오류는 API 호출 전 초기화를 멈추므로 전체 진입 파일을 검사한다.
 const fs=require('node:fs');
 const {spawnSync}=require('node:child_process');
 for(const directory of ['web/assets','deploy/web/assets']){
  for(const filename of fs.readdirSync(directory).filter(name=>name.endsWith('.js'))){
   const source=fs.readFileSync(path.join(directory,filename),'utf8');
   const checked=spawnSync(process.execPath,['--input-type=module','--check'],{input:source,encoding:'utf8'});
   assert.equal(checked.status,0,`${directory}/${filename}: ${checked.stderr}`);
  }
 }
 const {metricSeries,financialPeriods,marketCap}=await import(pathToFileURL(path.resolve('web/assets/data.js')).href);
 const periods=['2023 Q1','2023 Q2','2023 Q3'];
 const company={financials:[{period:periods[0],revenue:100,operatingProfit:-10,capex:20,operatingCashFlow:10},{period:periods[1],revenue:200,operatingProfit:20,capex:30,operatingCashFlow:40}]};
 assert.deepEqual(metricSeries(company,'revenue',periods),[100,200,null]);
 assert.deepEqual(metricSeries(company,'operating',periods),[-10,10,null]);
 assert.deepEqual(metricSeries(company,'fcf',periods),[-10,5,null]);
 assert.deepEqual(metricSeries(company,'revenue',['2022 Q4',...periods]),[null,null,null,null]);
 assert.equal(marketCap({constituents:[{marketCap:100},{marketCap:null}],constituentMarketCap:500}),null);
 assert.equal(marketCap({constituentMarketCap:500}),500);
 assert.deepEqual(financialPeriods([company]),periods.slice(0,2));
 assert.deepEqual(metricSeries({financials:[{period:'2022 Q1',revenue:50},{period:'2023 Q1',revenue:100}]},'revenue',['2023 Q1']),[100]);
 assert.deepEqual(metricSeries({financials:[{period:'2023 Q1',metrics:{operating:7,capex:2}}]},'operating',['2023 Q1']),[7]);
 const future=['2026 Q1','2026 Q2','2026 Q3','2026 Q4'];
 const partial={financials:future.map((period,i)=>({period,revenue:i===1?0:null,metrics:{operating:null}}))};
 assert.deepEqual(financialPeriods([partial],future),future.slice(0,2));
 assert.deepEqual(financialPeriods([partial]),future.slice(0,2));
 assert.deepEqual(financialPeriods([{financials:future.map(period=>({period,metrics:{operating:null}}))}],future),[]);
 const later={financials:[{period:'2026 Q3',metrics:{operating:-5}}]};
 assert.deepEqual(financialPeriods([partial,later],future),future.slice(0,3));
 assert.equal(metricSeries(partial,'operating',financialPeriods([partial,later],future)).at(-1),null);
 console.log('Storyboard UI calculations OK: first-period base-100 index, missing gaps, signed ratios, complete market-cap requirements.');
})().catch(error=>{console.error(error);process.exit(1)});
