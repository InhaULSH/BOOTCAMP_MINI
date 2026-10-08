# 데이터 계약

기본 파일: `data/project.json`. API 연동 시에도 동일한 형태로 반환하세요.
기본 파일은 `{ "sectors": [], "companies": [] }`이며 예시 숫자는 없습니다.
숫자는 문자열이 아닌 JSON number로 전달하고, 미확인 값은 null 또는 필드 생략으로 전달합니다.
누락 데이터를 0으로 보내면 실제 0으로 취급되므로 미확인 값에는 사용하지 마세요.

## 최상위

| 필드 | 타입 | 설명 |
|---|---|---|
| sectors | Sector[] | 메인에서 표시할 최대 5개 섹터 |
| companies | Company[] | 기업 목록 |
| marketCapUnit | string | 전체 합계와 구성종목에 공통 적용할 시가총액 단위 |

## Sector

| 필드 | 타입 | 설명 |
|---|---|---|
| id, name | string | 섹터 고유 ID와 이름 |
| constituentMarketCap | number 또는 null | **전체** KRX 섹터지수 구성종목 합계. 분석 기업만의 합계가 아님 |
| constituents | {id:string,marketCap:number}[] | 전체 지수 구성종목 목록. 유효한 목록이 있으면 프런트가 합산. 일부 구성종목만 보내면 안 됨 |
| marketCapUnit | string | 시가총액 표시 단위. 모든 섹터를 같은 단위로 보내야 크기 비교가 정확함 |
| indexReturnPct | number 또는 null | 해당 KRX 지수의 실제 최근 수익률. 퍼센트 포인트 단위 |
| returnPeriod | string | 예: 실제 수익률 산출기간/기준일을 사람이 읽는 문구로 전달 |
| indexName | string | KRX 지수명 |
| indexSeries | {date:string,value:number 또는 null}[] | 지수 관측값. 날짜 오름차순 |
| marketSeriesPeriod | string | 시계열 기간 표시 문구 |
| analysisCompanyIds | string[] | 분석 대상 5개 기업의 ID. companies.id와 연결 |
| periods | string[] | 공통 분기 목록, `YYYY Qn`, 오름차순. 없으면 기업 재무 데이터에서 추출 |
| keywords | Keyword[] | 산업 공시 신호, LLM 중요도 순으로 렌더링 |
| aiInsight | string | 재무 DB·공시 DB를 종합한 LLM 산업 인사이트, 권장 2~3문장 |
| metricInsights | object | revenue/operating/capex/fcf별 LLM 해석 문자열, 선택 사항 |

## Company

| 필드 | 타입 | 설명 |
|---|---|---|
| id, name | string | 기업 ID와 표시명 |
| color | CSS color | 비교 그래프 선 색. 없으면 디자인 팔레트 사용 |
| businessSummary | string | 기업 사업 요약 |
| dailyReturnPct | number 또는 null | 전일 대비 주가 수익률 |
| stockSeries | {date:string,value:number 또는 null}[] | 기업 주가 관측값. 원 단위, 날짜 오름차순 |
| marketSeriesPeriod | string | 주가 기간 표시 문구 |
| amountUnit | string | 재무 금액 단위. 기본 `억원`. 기업별 모든 재무 금액을 같은 단위로 전달 |
| financials | FinancialRow[] | 분기별 매출액/영업이익/CAPEX/영업활동현금흐름 |
| keywords | Keyword[] | 해당 기업 공시에서 평가한 중요 키워드 |
| aiInsight | string | 재무·공시 기반 LLM 기업 인사이트 |
| metricInsights | object | 지표별 LLM 해석, 선택 사항 |

## FinancialRow

`period`: `YYYY Qn` 형식. 누적 실적이 아닌 **해당 분기 실적**을 전달합니다.
`revenue`, `operatingProfit`, `capex`, `operatingCashFlow`: 동일 금액 단위의 number 또는 null.
CAPEX는 지출 규모를 양수로 전달합니다. 영업활동현금흐름과 영업이익은 음수 가능.
백엔드에서 누적값을 분기값으로 변환하고 연결/별도 기준도 일관되게 맞춰주세요.
표시 기간은 백엔드가 최근 3년 범위로 제한해서 전달합니다.

## Keyword

| 필드 | 타입 | 설명 |
|---|---|---|
| label | string | 표시 키워드 |
| importance | number | LLM 중요도. 양수 값만 표시. 화면 내부에서 최대 중요도 대비 상대 크기로 변환 |
| disclosureContext | string | 해당 키워드와 관련하여 공시에서 확인한 내용, 1~2문장 |
| selectionReason | string | 중요 키워드로 선정한 이유. 단순 빈도 설명으로 대체하지 않음 |
| sourceUrl | string | 근거 DART 공시 원문 URL, 선택 사항. http/https만 링크로 표시 |

LLM 평가 기준, 근거 공시와 평가 시점은 백엔드에서 관리하세요.
프런트는 전달받은 중요도·공시 맥락·선정 이유를 표시하는 역할입니다.

## 입력 조건

- 시가총액이 없거나 음수인 섹터는 크기 계산에서 제외합니다.
- constituents가 제공되면 각 구성종목의 시가총액이 모두 유효해야 합니다.
- 동일한 분기에 누락값이 있으면 선을 끊어 표시하며 0으로 바꾸지 않습니다.
- 매출 기준은 조회기간의 첫 표시 분기로 고정합니다. 기업별로 다른 기준을 쓰지 않습니다.
- 최신 분기 중앙값은 그 공통 분기에 값이 있는 기업만 계산합니다.
- 금액·주가·수익률의 단위와 기준일은 API에서 일관되게 맞춰 전달하세요.
