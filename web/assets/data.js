// Replace only this adapter when connecting your API. No sample data fallback.
export async function loadProject() {
  const params=new URLSearchParams(location.search); const sector=params.get('sector')||params.get('company')?.split(':').slice(0,-1).join(':');
  const response=await fetch('/api/project'+(sector?'?sector='+encodeURIComponent(sector):''));
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
  revenue: {title:'매출 성장 추이', question:'요즘 성장하고 있나요?', unit:'지수',
    formula:'분기 매출액 ÷ 첫 표시 분기 매출액 × 100',
    help:'각 기업의 첫 표시 분기 매출을 100으로 놓고 성장 흐름을 비교합니다. 툴팁에서는 실제 매출액을 확인할 수 있습니다.'},
  operating: {title:'영업이익률 추이', question:'팔아서 얼마나 남기고 있나요?', unit:'%',
    formula:'영업이익 ÷ 매출액 × 100', help:'매출에서 본업에 드는 비용을 빼고 남는 이익의 비율입니다.'},
  capex: {title:'매출 대비 CAPEX', question:'기업들이 투자를 늘리고 있나요?', unit:'%',
    formula:'CAPEX ÷ 매출액 × 100', help:'매출에 비해 공장·장비 등 투자에 현금을 얼마나 썼는지 보여줍니다.'},
  fcf: {title:'투자 후 남은 현금 (FCF)', question:'투자하고도 현금이 남고 있나요?', unit:'%',
    formula:'(영업활동현금흐름 − CAPEX) ÷ 매출액 × 100',
    help:'본업에서 얻은 현금에서 투자 지출을 뺀 FCF를 매출 대비 비율로 표시합니다. 음수라도 투자 확대 때문일 수 있습니다.'}
};
export function metricSeries(company, key, periods) {
  const rows = new Map((company.financials || []).map(row => [row.period, row]));
  const baseline = rows.get(periods[0])?.revenue;
  return periods.map(period => {
    const row = rows.get(period);
    if (!row) return null;
    if (key === 'revenue') return ratio(row.revenue, baseline);
    if (key === 'operating') return ratio(row.operatingProfit, row.revenue);
    if (key === 'capex') return ratio(row.capex, row.revenue);
    if (key === 'fcf') return ratio(number(row.operatingCashFlow) && number(row.capex)
      ? row.operatingCashFlow - row.capex : null, row.revenue);
    return null;
  });
}
export function financialPeriods(companies) {
  const periods = [...new Set(companies.flatMap(c => (c.financials || []).map(r => r.period)))];
  return periods.filter(p => /^\d{4} Q[1-4]$/.test(p)).sort();
}
