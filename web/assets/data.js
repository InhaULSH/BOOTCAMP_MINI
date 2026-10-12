// Replace only this adapter when connecting your API. No sample data fallback.
export async function loadProject() {
  const params=new URLSearchParams(location.search); const sector=params.get('sector')||params.get('company')?.split(':').slice(0,-1).join(':');
  const query=new URLSearchParams();if(sector)query.set('sector',sector);
  if(params.get('company'))query.set('code',params.get('company').split(':').at(-1));
  const response=await fetch('/api/project'+(query.size?'?'+query:''));
  if (!response.ok) throw new Error(`데이터 요청 실패 (${response.status})`);
  const data = await response.json();
  if (!Array.isArray(data.sectors) || !Array.isArray(data.companies)) {
    throw new Error('sectors와 companies 배열이 필요합니다.');
  }
  return data;
}

export const number = value => typeof value === 'number' && Number.isFinite(value);
export function marketCap(sector) {
  // Full KRX index constituents only; never substitute the analysis companies.
  if (Array.isArray(sector.constituents) && sector.constituents.length) {
    if (!sector.constituents.every(c => number(c.marketCap) && c.marketCap >= 0)) return null;
    return sector.constituents.reduce((sum, c) => sum + c.marketCap, 0);
  }
  return number(sector.constituentMarketCap) && sector.constituentMarketCap >= 0
    ? sector.constituentMarketCap : null;
}
export const compactPeriod = label => label.replace(/^(\d{2})(\d{2}) Q([1-4])$/, '$2Q$3');
export const ratio = (a, b) => number(a) && number(b) && b > 0 ? a / b * 100 : null;
export const stockChange = value => number(value)
  ? `${value > 0 ? '▲ ' : value < 0 ? '▼ ' : ''}${Math.abs(value).toFixed(2)}%` : '—';
export const direction = value => number(value) ? value > 0 ? 'up' : value < 0 ? 'down' : 'neutral' : 'neutral';
export const metricCatalog = {
  revenue: {title:'매출 지수', question:'매출은 얼마나 성장하고 있나요?', unit:'지수',
    formula:'분기 매출액 ÷ 최초 분석 분기 매출액 × 100',
    help:'기준 분기의 매출을 100으로 놓고, 이후 매출이 얼마나 늘거나 줄었는지 비교합니다. 예를 들어 120이면 기준 분기보다 매출이 20% 늘었다는 뜻입니다.'},
  operating: {title:'영업이익률 추이', question:'팔아서 얼마나 이익을 남기고 있나요?', unit:'%',
    formula:'영업이익 ÷ 매출액 × 100', help:'매출에서 본업에 드는 비용을 빼고 남는 이익의 비율입니다. 10%라면 100원어치를 팔아 본업에서 10원의 이익을 남겼다는 뜻입니다.'},
  capex: {title:'매출 대비 CAPEX', question:'공장과 장비에 얼마나 투자하고 있나요?', unit:'%',
    formula:'CAPEX ÷ 매출액 × 100', help:'매출에 비해 공장·장비 등 자산을 마련하는 데 현금을 얼마나 썼는지 보여줍니다. 비율이 높아져도 매출이 줄어든 결과일 수 있어 실제 투자액도 함께 살펴보세요.'},
  fcf: {title:'투자 후 남은 현금 (FCF)', question:'투자하고도 현금이 남고 있나요?', unit:'%',
    formula:'(영업활동현금흐름 − CAPEX) ÷ 매출액 × 100',
    help:'본업에서 들어온 현금에서 설비투자 지출을 빼고, 남은 현금이 매출의 몇 %인지 보여줍니다. 음수라도 미래를 위한 투자 확대 때문일 수 있으므로 적자와 같은 뜻은 아닙니다.'}
};
export function metricSeries(company, key, periods) {
  const rows = new Map((company.financials || []).map(row => [row.period, row]));

  return periods.map(period => {
    const row = rows.get(period);
    if (!row) return null;
    if (row.metrics) return number(row.metrics[key]) ? row.metrics[key] : null;
    if (key === 'revenue') {const base=rows.get(periods[0]);return row.basis===base?.basis?ratio(row.revenue,base?.revenue):null;}
    if (key === 'operating') return ratio(row.operatingProfit, row.revenue);
    if (key === 'capex') return ratio(row.capex, row.revenue);
    if (key === 'fcf') return ratio(number(row.operatingCashFlow) && number(row.capex)
      ? row.operatingCashFlow - row.capex : null, row.revenue);
    return null;
  });
}
export function financialPeriods(companies, requested) {
  const periods = [...new Set(companies.flatMap(c => (c.financials || []).map(r => r.period)))];
  const candidates=(requested ?? periods).filter(p => /^\d{4} Q[1-4]$/.test(p)).sort();
  const fields=['revenue','operatingProfit','capex','operatingCashFlow','rd',
    'netInterestIncome','netIncome','creditLoss','equity','assets','loans'];
  const available=companies.flatMap(c => (c.financials||[]).filter(r => candidates.includes(r.period) &&
    (fields.some(key => number(r[key])) || Object.values(r.metrics||{}).some(number))).map(r => r.period)).sort();
  const last=available.at(-1);
  return last ? candidates.filter(p => p<=last) : [];
}
