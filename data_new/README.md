> 이 문서는 입력 DB를 만든 상류 파이프라인의 설명을 보존한 자료입니다. 아래 `src.*` 수집 명령은 현재 통합 저장소에 포함되지 않습니다. 현재 서비스 실행·데이터 연결 방법은 [프로젝트 README](../README.md)와 [SERVICE_README](SERVICE_README.md)를 참고하세요.

# DART 재무계정 표준화 파이프라인

OpenDART에서 5개 기업의 연결재무제표를 수집하고, 기업·연도·분기별 계정명과
`account_id`를 비교해 표준화 매핑 초안을 만든 뒤 SQLite Financial DB에 저장합니다.
원본 API 응답은 수정하지 않고 `data/raw`에 보존합니다.

## 기본 분석 기업

- 삼성전자, SK하이닉스, 한미반도체, 주성엔지니어링, 원익IPS
- 기본 수집 기간: 2023-2025년
- 보고서: 1분기, 반기, 3분기, 사업보고서

## 설치와 실행

```bash
cd /Users/minseongyi/project/coding/my-project/dart_beginner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 기존 .env가 있으면 덮어쓰지 마세요
python -m src.pipeline
```

공시 본문은 재무 파이프라인이 확보한 정확한 `rcept_no`를 이용해 별도로 수집합니다.

```bash
python -m src.filing_pipeline
```

연도나 기업을 바꿔 실행할 수도 있습니다.

```bash
python -m src.pipeline --years 2024 2025 --companies 삼성전자 SK하이닉스
```

## 생성 결과

```text
data/raw/corp_codes/                 DART 기업코드 원본 ZIP/XML
data/raw/financial/                  API 원본 JSON (재실행 시 재사용)
data/raw/filings/zip/                document.xml 응답 ZIP 원본
data/raw/filings/xml/                ZIP에서 추출한 공시 원문 XML
data/raw/filings/search/             list.json 검색 응답 원본 JSON
data/processed/financial/financial_accounts_wide.csv 원본 필드 기반 정리 CSV
data/processed/financial/financial_facts.csv 기간 의미별 long-form CSV
data/processed/filings/parsed/       섹션 단위 파싱 JSON
data/processed/filings/chunks/       Vector DB 입력용 JSONL 청크
data/processed/quality/filing_quality_report.csv 문서별 품질검증 결과
data/processed/quality/search_validation_report.csv 검색 상위 결과 검증
data/processed/account_comparison.csv 기업/연도/분기별 계정 비교표
data/mapping/account_mapping_draft.csv 표준화 매핑 초안
data/mapping/account_mapping_prioritized.csv 전체 매핑 검토 우선순위
data/mapping/account_mapping_core.csv MVP 핵심 24개 표준계정 매핑
data/mapping/capex_component_mapping_v2.csv CAPEX 직접/세부/제외 계정 규칙
data/mapping/account_mapping_review_prioritized.csv 충돌 검토 우선순위
db/financial/financial.db            현재 운영/서비스용 기준 Financial DB
db/financial/financial_final.db      승격 직전 검증 완료 스냅샷
db/financial/financial_capex_v2.db   CAPEX 로직 검증용 과도기 DB
db/archive/financial_before_capex_fix.db 승격 전 Financial DB 백업
db/vector/filings.db                 임베딩 및 청크 메타데이터 Vector DB
db/vector/filings_e5.db              Multilingual E5 비교 Vector DB
```

매핑 초안의 `mapping_status`가 `review_required`인 행을 검토한 뒤
`standard_account_name`을 수정하면 됩니다. `account_id`가 있는 계정은 ID를 우선
키로 사용하고, ID가 없는 계정만 정규화한 계정명을 키로 사용합니다.

## DB 구조

- `companies`: 기업 마스터
- `periods`: 연도/분기/보고서 마스터
- `account_mapping`: 표준화 매핑
- `financial_facts`: 재무 계정 원장
- `capex_facts`: 직접 또는 파생한 `유형자산취득(CAPEX)` 원장
- `capex_build_metadata`: 생성 원천·해시와 생성 건수
- `pipeline_runs`: 실행 이력

`src/retrieval`, `src/llm`은 이후 Vector DB 및 LLM 분석을 붙일 경계로 유지했습니다.
현재 파이프라인은 수집/정제/매핑/관계형 DB 적재까지만 책임집니다.

## 기간 의미 표준화

`financial_facts`는 계정 하나를 기간 의미에 따라 여러 레코드로 저장할 수 있습니다.

- `BS`: `point_in_time`. 보고기간 말 현재의 잔액이며 `period_start`는 비웁니다.
- `IS`, `CIS`: 분기 보고서의 `thstrm_amount`는 `quarterly`,
  `thstrm_add_amount`는 `cumulative`로 각각 저장합니다. 사업보고서 값은 `annual`입니다.
- `CF`: 분기·반기·3분기 값은 연초 이후 `cumulative`, 사업보고서는 `annual`입니다.
  분기 단독값은 누적값 차감으로 별도 계산합니다.
- `SCE`: 자본변동표는 기간 흐름이지만 단순 분기 차감 시 의미가 왜곡될 수 있어
  `cumulative` 또는 `annual` 원본만 보존합니다.

계산된 분기값은 원본값을 바꾸지 않습니다. `is_calculated=1`로 구분하고,
`calculated_value`와 `calculation_method`에 계산값과 사용한 누적값을 기록합니다.
직접 제공된 값은 `raw_value`와 파싱된 `normalized_value`에 저장됩니다.

```text
H1 quarterly = H1 cumulative - Q1 cumulative
Q3 quarterly = Q3 cumulative - H1 cumulative
FY quarterly = FY annual - Q3 cumulative
```

`period_start`와 `period_end`는 현재 대상 기업의 12월 결산을 기준으로 보고서 유형에서
추론한 달력 날짜입니다. 원본 DART JSON은 `data/raw/financial`에서 변경 없이 유지됩니다.

## CAPEX 표준계정

좁은 의미의 CAPEX는 현금흐름표(`sj_div=CF`)에 있는 유형자산 취득 현금유출만
`유형자산취득(CAPEX)`로 표준화합니다. 같은 기업·연도·보고서에
`ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`
(`유형자산의 취득`)이 있으면 그 직접 계정만 사용합니다. 직접 계정이 없을 때만
토지, 건물, 구축물, 기계장치, 차량운반구, 공구와기구, 비품, 건설중인자산의 취득을
합산합니다. 무형자산, 소프트웨어, 회원권, 투자부동산, 영업권은 제외하며 주석 수치는
합산하지 않습니다.

`raw_value`와 `normalized_value`에는 원본 부호를 유지하고, 서비스용 투자 지출 규모는
양수인 `cash_outflow_amount`로 제공합니다. 직접/파생 여부는 `value_source`, 파생에
사용한 계정은 `source_account_ids`, `source_account_names`, `source_values`로 추적할 수
있습니다. 누적 합계를 먼저 만든 뒤 `H1-Q1`, `Q3-H1`, `FY-Q3`으로 분기 단독값을
계산합니다. 본 파이프라인은 정규화된 재무 원장을 임시 DB에 먼저 생성하고 무결성을
확인한 뒤 운영 기준인 `financial.db`를 원자적으로 교체합니다. DB에는 `capex_facts`와
통합 조회 뷰 `financial_facts_final`이 함께 생성됩니다. `financial_final.db`는 승격 직전
검증 스냅샷, `financial_capex_v2.db`는 이전 CAPEX 검증용 과도기 DB로 보존합니다.

재무 파이프라인은 운영 기준 DB를 처음부터 다시 생성합니다. 저장된 처리 결과로 API 호출
없이 검증 스냅샷을 재현하거나, 이전 v2 비교 DB를 다시 만들려면 다음을 실행합니다.

```bash
# financial_final.db 검증 스냅샷 재생성
python -m src.db.final_db
python -m unittest -v tests.test_capex_derivation

# 선택 사항: 이전 CAPEX v2 비교 DB 재생성
python -m src.db.capex_db
```

조회기와 Streamlit은 설정의 `FINANCIAL_DB_PATH`, 즉 `db/financial/financial.db`만 기본
Financial DB로 사용합니다. `HY`, `H1`은 모두 반기 보고서로 받습니다.
CAPEX 조회 결과의 `normalized_value`와 `cash_outflow_amount`는 서비스용 양수 금액이고,
원본 부호를 반영한 합계는 `signed_normalized_value`에서 확인합니다.

```python
from src.retrieval.financial_retriever import get_financial_context

capex = get_financial_context(
    corp_name="주성엔지니어링",
    year=2024,
    report_type="HY",
    account_name="유형자산취득(CAPEX)",
)
```

기업·연도·보고서별 직접/파생 방식과 값은
`data/processed/quality/capex_mapping_validation.csv`에서 확인합니다. 현재 5개 기업은
삼성전자·SK하이닉스·한미반도체·원익IPS가 `direct`, 주성엔지니어링이 `derived`입니다.

## Financial DB와 Vector DB의 원천 구분

현재 서비스의 기본 DB 경로는 다음과 같습니다.

```text
Financial DB: db/financial/financial.db
Vector DB:    db/vector/filings.db
```

Financial DB는 핵심 표준계정, 분기/누적 구분, CFS/OFS 구분, `rcept_no` 연결과
CAPEX direct/derived 표준화를 포함합니다.

두 데이터 흐름은 접수번호(`rcept_no`)로 연결하지만 원천은 서로 다릅니다.

```text
OpenDART fnlttSinglAcntAll.json
  -> data/raw/financial/*.json
  -> 기간/계정 표준화
  -> Financial DB

OpenDART document.xml (실제 응답은 ZIP binary)
  -> data/raw/filings/zip/*.zip
  -> data/raw/filings/xml/*.xml
  -> 섹션 파싱 JSON
  -> 출처 메타데이터가 포함된 JSONL 청크
  -> Vector DB (후속 단계)
```

사용하는 OpenDART endpoint는 다음과 같습니다.

- `GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json`: 구조화 재무제표 JSON
- `GET https://opendart.fss.or.kr/api/list.json`: 공시 목록 검색 JSON
- `GET https://opendart.fss.or.kr/api/document.xml`: 접수번호별 공시 원문 ZIP
- `GET https://opendart.fss.or.kr/api/corpCode.xml`: 기업코드 ZIP/XML

현재 공시 파이프라인은 재무 응답에 포함된 정확한 접수번호를 우선 사용하므로 같은
보고서의 원문과 재무수치를 직접 연결합니다. `list.json` 메서드는 재무 API에 없는
공시를 추가로 찾을 때 사용할 수 있으며 검색 응답도 원본 영역에 저장합니다.

파싱 결과와 청크에는 `corp_name`, `corp_code`, `report_name`, `report_type`, `year`,
`rcept_no`, `section_name`, `source_file`, `original_text`, `cleaned_text`가 포함됩니다.
`source_file`로 언제든 보존된 XML 원문까지 추적할 수 있습니다.

전체 수집 전에 일부만 검증하려면 다음처럼 실행할 수 있습니다.

```bash
python -m src.filing_pipeline --companies 삼성전자 --years 2025 --limit 1
```

## 전체 데이터셋 구축 순서

```bash
# 1. 구조화 재무정보 수집 및 기본 financial.db 구축
python -m src.pipeline

# 저장된 처리 결과로 승격 전 검증 스냅샷만 재생성할 때
python -m src.db.final_db

# 2. 동일 rcept_no의 공시 원문 ZIP/XML 수집, 파싱, 청킹, 품질보고서 생성
python -m src.filing_pipeline

# 3. 품질 기준을 통과한 청크 임베딩 및 Vector DB 구축
python -m src.vector_pipeline

# 4. 대표 검색 질문의 상위 5개 결과 저장
python -m src.quality.search_validation

# 5. 계정 우선순위·핵심 매핑과 Financial DB 품질검증
python -m src.quality.account_mapping_quality
python -m src.quality.financial_quality
python -m unittest -v tests.test_capex_derivation

# 6. 선택 사항: 별도 transformer DB와 검색 비교 보고서
HF_HOME="$PWD/db/vector/model_cache" python -m src.retrieval.transformer_retriever
HF_HOME="$PWD/db/vector/model_cache" python -m src.quality.vector_comparison

# 7. 통합 라우팅·출처 검증
python -m src.quality.integration_validation

# 8. Gemini 실제 답변 5건 및 근거 일치 자동검증 (명시적으로 외부 호출할 때만 실행)
python -m src.quality.llm_validation

# 9. 결정적 원화 단위 환산 테스트와 v2 Gemini 재검증
python -m unittest -v tests.test_financial_units
python -m src.quality.unit_normalization_validation
python -m src.quality.llm_validation_v2

# 10. 기본 DB 승격 후 Financial/Vector/CAPEX/Streamlit/Gemini 종합 점검
python -m src.quality.post_promotion_smoke_test
```

현재 임베딩은 외부 API나 별도 대형 런타임 없이 재현 가능하도록 한국어·영문 단어,
단어 바이그램, 문자 n-gram을 결합한 `local-ko-en-finance-hashing-v1`을 사용합니다.
Vector DB는 SQLite에 정규화된 float32 임베딩 BLOB과 청크·출처 메타데이터를 함께
저장하며, 검색 시 코사인 유사도와 금융 문서 키워드 점수를 결합합니다. 향후
transformer 임베딩으로 교체해도 `filing_chunks` 메타데이터 인터페이스는 유지됩니다.
비교용으로 `intfloat/multilingual-e5-small` 384차원 DB도 별도 구축합니다. 현재 의미형
질문 5개의 섹션 적합도 비교에서는 feature-hashing 하이브리드가 상위 25건 중 13건,
E5가 9건으로 판정되어 기본 검색은 기존 하이브리드 방식을 유지합니다.

품질보고서는 다음 경로에 생성됩니다.

- `data/processed/quality/financial_quality_report.csv`
- `data/processed/quality/financial_core_validation.csv`
- `data/processed/quality/capex_mapping_validation.csv`
- `data/processed/quality/capex_final_validation.csv`
- `data/processed/quality/financial_final_regression.csv`
- `data/processed/quality/final_db_llm_validation.json`
- `data/processed/quality/final_db_llm_validation_summary.csv`
- `data/processed/quality/vector_search_comparison.csv`
- `data/processed/quality/integration_validation.json`
- `data/processed/quality/gemini_llm_validation.json`
- `data/processed/quality/gemini_llm_validation_summary.csv`
- `data/processed/quality/unit_normalization_test_v2.json`
- `data/processed/quality/gemini_llm_validation_v2.json`
- `data/processed/quality/gemini_llm_validation_summary_v2.csv`
- `data/processed/quality/post_promotion_smoke_test.json`
- `data/processed/quality/post_promotion_smoke_test_summary.csv`

LLM 통합 단계에서는 다음 함수를 사용합니다.

```python
from src.retrieval.financial_retriever import get_financial_context
from src.retrieval.vector_retriever import search_filing_context

financial = get_financial_context("삼성전자", 2025, "FY")
filings = search_filing_context(
    "반도체 사업 위험요인", corp_name="삼성전자", year=2025,
    report_type="FY", top_k=5,
)
```

두 결과 모두 `corp_code`, `year`, `report_type`, `rcept_no`로 동일 보고서를 연결할 수
있습니다. Financial DB는 금액의 `currency`, 원본값, 정규화값, 계산값과 계산 입력값을
구분하며 결측값을 0으로 바꾸지 않습니다.

## 통합 질문 라우팅과 LLM 연결

`src.llm.analyzer.analyze_company()`는 숫자 질문을 Financial DB, 설명 질문을 Vector DB,
원인·재무효과 질문을 양쪽 DB로 라우팅합니다. 결과에는 `financial_sources`와
`filing_sources`가 항상 포함됩니다. 기본 실행은 외부 전송 없이 근거 미리보기를 만들며,
실제 LLM 호출은 호출자가 명시적으로 제공한 `llm_client(prompt)` 콜백으로만 수행합니다.

`src.quality.llm_validation`은 `.env`의 `GEMINI_API_KEY`를 인증 헤더에만 사용합니다.
요청 본문에는 공개 DART 재무수치, 공개 공시 청크, 공개 접수번호와 질문만 포함되며,
API 키·로컬 경로·시스템 정보가 감지되면 호출 전에 차단합니다. 검증 결과에는 질문별
실제 재무 근거, 청크 본문, `rcept_no`, Gemini 답변과 숫자 환각·근거 불일치·연도 혼합·
다른 기업 혼입 검사 결과가 함께 저장됩니다. 기존 DB와 원본 파일은 읽기만 합니다.

## 금액 단위 정규화

`src.financial_units.normalize_financial_value()`가 `원`, `천원`, `백만원`, `억원`,
`조원`을 LLM 호출 전에 KRW로 결정적으로 환산합니다. 원본값·원본단위와 함께
`normalized_value`, `normalized_unit`, `unit_conversion_applied`, `conversion_formula`,
원화·억원·조원 표시 문자열을 유지합니다. 검색된 공시 청크도 명시된 단위와 주요
시설투자 표를 파싱하여 같은 구조로 프롬프트에 제공합니다.

LLM은 제공된 `normalized_value`와 `display_*` 문자열을 그대로 인용하며 자체 단위
변환을 하지 않습니다. v2 검증기는 답변 금액을 근거 값과 대조하고 10배, 100배,
1,000배, 100,000,000배 차이를 단위 환산 오류로 기록합니다. Streamlit의 재무·공시
출처 상세 화면에서는 원본 단위와 코드 환산 원화/조원 표시를 함께 확인할 수 있습니다.

```python
from src.llm.analyzer import analyze_company

result = analyze_company(
    "삼성전자 2025년 실적 변화와 그 원인을 설명해줘.",
    corp_name="삼성전자", year=2025, report_type="FY",
)
```

## Streamlit 실행

운영 기준 DB를 다시 구축한 뒤 앱을 실행하는 기본 순서는 다음과 같습니다.

```bash
cd /Users/minseongyi/project/coding/my-project/dart_beginner
source .venv/bin/activate
python -m src.pipeline
streamlit run app/app.py
```

화면에서 기업·연도·보고서·검색 방식을 선택할 수 있으며 라우팅 결과, 재무 출처,
공시 출처와 LLM 전달용 근거 프롬프트를 확인할 수 있습니다.
