const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
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
 console.log('Storyboard UI calculations OK: fixed first-quarter baseline, missing gaps, signed ratios, complete market-cap requirements.');
})().catch(error=>{console.error(error);process.exit(1)});
