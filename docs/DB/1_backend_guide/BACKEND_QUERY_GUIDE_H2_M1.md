# 백엔드 조회·분기 계산 가이드 (H2·M1 및 Medium 항목)

- 대상: 백엔드 팀(분석기·조회 로직 담당)
- 근거: `docs/handoff/FINANCIAL_DB_BACKEND_READINESS_20261009.md`, `docs/handoff/BACKEND_FIX_H1_H3_STAGING_20261009.md`
- 데이터팀은 백엔드 코드(`src/llm/analyzer.py`, `src/retrieval/financial_retriever.py`)를 수정하지 않았다. 아래는 권장 수정이다.

## H2. 실행 시 Q4 계산이 의미 없는 값을 만드는 문제

**발생 위치:** `analyzer._quarterly_financial_context`. 같은 (표, 계정 ID)에 저장된 Q4 분기값이 없으면, FY 보고서의 모든 `annual` 행에서 `FY annual − Q3 cumulative`를 계산한다.

**발생 조건과 실측(일반 20개사 × 2023~2025, "분기별 추이" 질문)**

| 행 종류 | 생성 건수 | 예 |
|---|---:|---|
| 현금흐름표 기초·기말 현금(잔액) | 114 | 삼성전자 2023 "Q4 기말현금" −6.06조, "Q4 기초현금" 0 |
| 자본변동표 행(기초·기말 자본, 배당 등) | 448 | 잔액끼리 뺀 값 |
| 주당이익 | 12 | SK하이닉스 2023 Q4 EPS −1,972원(근사값) |
| DB가 근거 부족으로 보류한 분기 | 29 | 계정명 변경·태그 없음 항목을 부호만 보고 계산 |

- v10에서 DB에 저장된 같은 오류 553행은 제거했다.
- 그러나 이 계산이 남아 있으면 답변에서 같은 값이 다시 나타난다.

**권장 정책(우선순위 순)**
1. **저장된 분기값만 사용한다(가장 안전).** Q4는 FY 보고서의 `value_type='quarterly'` 행을 쓴다.
   - DB는 근거가 있는 분기만 저장하고, 나머지는 의도적으로 비워 둔다.
2. 계산을 유지한다면 다음 조건을 모두 만족할 때만 계산한다.
   - `sj_div IN ('IS','CIS','CF')`이다. `SCE`와 `BS`는 제외한다.
   - 현금흐름표 잔액 줄이 아니다. 계정 ID `dart_CashAndCashEquivalentsAtBeginningOfPeriodCf`, `dart_CashAndCashEquivalentsAtEndOfPeriodCf`, `ifrs-full_CashAndCashEquivalents`와, 계정명에 "기초·기말·분기말·반기말"과 "현금"이 함께 있는 줄을 뺀다.
     - DB 측 판별 함수: `src/preprocess/period_normalizer.is_cf_balance_line`
   - 주당이익이 아니다(계정 ID에 `PerShare`, 계정명에 "주당").
   - FY와 Q3의 부호가 같다(현재 코드와 동일).
   - 결과에 "계산값(FY − Q3)"임을 표시한다.
3. 위 조건으로도 값이 없으면 "해당 분기 값 없음"으로 답한다. 0이나 추정값으로 채우지 않는다.

**확인 방법:** 수정 후 "분기별 추이"를 일반 20개사 × 3년으로 실행한다. 계산 행 중 잔액 줄·자본변동표·주당이익이 0건이어야 한다.

## M1. 검토 필요(review_required) 금융 지표의 표시

**발생 위치:** `_finance_metric_context`는 `review_status`를 행에 담는다. 그러나 `_format_financial`이 프롬프트에 넣지 않아, LLM이 확정값으로 다룬다.

**대상(운영 v10, 10행)**

| 회사 | 지표 | 기간 | 이유 |
|---|---|---|---|
| 우리금융지주 | `LOANS_AT_AMORTISED_COST` | 2023 Q1·H1·Q3·FY, 2024 Q1·H1·Q3 | 대출채권과 기타금융자산이 합쳐진 공시 줄. 대출채권만의 값은 `LOANS_AT_AMORTISED_COST_NOTE`(주석 추출, approved)를 쓴다 |
| KB금융 | `OWNERS_NET_INCOME`, `PRETAX_INCOME`, `OPERATING_INCOME` | 2023 Q4(분기) | 2023 Q3 누적을 FY 기준으로 재작성해 계산. 저장된 Q1~Q3와 기준이 달라 네 분기 합이 FY와 맞지 않음 |

**권장 규칙**
1. `review_status != 'approved'` 행은 답변에 "(검토 필요: 사유)"를 붙인다. 순위·합계·증감 계산에는 쓰지 않는다.
2. 같은 질문에 approved 대안이 있으면 대안을 우선한다(우리 대출채권 → `_NOTE`).
3. 프롬프트 행 형식에 `review_status`를 추가한다.
4. 앞으로 2026 신규 공시에서도 근거 판정 전 금융 비용 지표는 `review_required`로 들어온다(staging 확인: 60행). 같은 규칙이 적용된다.

## M2. "자본총계" 계정 식별

- 자본변동표(SCE)의 "자본총계" 행 값은 23개 기업-연도에서 지배기업 소유주지분이다.
  - 예: 삼성전자 2024는 391.69조인데, 총자본은 402.19조다.
- **규칙:** 자본총계·자산총계·부채총계와 모든 잔액은 `sj_div='BS'`, `value_type='point_in_time'`만 쓴다.
- MySQL 표준 뷰는 006 반영 후 이 규칙을 강제한다(SCE·CF 잔액 행 제외).
- SQLite 원천 조회(`get_financial_context`)는 이름 검색이라 두 행이 모두 나온다. 백엔드가 BS만 고르도록 한다.

## M4. 조회 결과 상한(200·80행)

- `_quarterly_financial_context`는 200행, `_financial_context`는 80행에서 자른다.
- 계정을 지정하지 않은 분기 추이 질문은 60건 중 57건에서 일부가 잘린다.
  - 정렬이 (연도, 분기) 순이라 **Q4·후순위 계정이 먼저 빠진다.**
- **권장:** 질문에서 계정을 정하지 못하면 핵심 계정(매출액·영업이익·순이익·영업현금흐름)으로 한정한다. 또는 잘렸다는 사실을 답변에 표시한다.

## 그 밖의 조회 규칙 요약

| 규칙 | 내용 |
|---|---|
| 값 | `is_calculated=1`이면 `calculated_value`, 아니면 `normalized_value`. 단위는 원 |
| 기간 | 잔액 `point_in_time`, 연간 `annual`, 누적 `cumulative`, 3개월 `quarterly`. 분기 비교는 `quarterly`끼리만 |
| 연결·별도 | 회사당 한 기준. 23개사 CFS, 카카오뱅크·에이치브이엠 OFS. H3 반영 후 AUTO가 에이치브이엠을 OFS로 조회 |
| 금융 비용 | `value` 양수 = 비용, 음수 = 순환입. 절댓값 처리 금지. 원값은 `source_values.sign_standardization.original_value` |
| 값 없음 | "없음"으로 답함. 0이나 누적 차감으로 만들지 않음 |
| MySQL | `is_active=1` 행만. 006 반영 전에는 순이익·영업이익·영업CF를 `financial_facts`의 공식 태그로 조회 |
