# 데이터 사전 (Data Dictionary)

작성일: 2026-10-06 (5개사 확정·MySQL 적재 반영 개정)
대상 독자: 데이터 엔지니어가 아닌 팀원 포함 전원

## 0. 읽는 법

- 이 문서는 정적 코드(스키마 정의 코드)와 기존 문서를 근거로 작성했고, 이후 운영 5개사 DB와 중앙 MySQL 적재 결과로 값을 확인했다.
- 운영 범위: 5개사(삼성전자, SK하이닉스, 한미반도체, 주성엔지니어링, 원익IPS), 2023~2025, Q1/H1/Q3/FY. 16개사 추가 확장은 취소됐다.
- 더 자세한 전체 컬럼 목록은 기존 문서 `docs/data_catalog/PROJECT_COLUMN_DICTIONARY.md`(2026-10-02 기준, 기존 5개사 시점)를 참고한다. 이 문서는 백엔드 연동에 필요한 핵심 필드만 쉽게 정리했다.
- **위치 표기**
  - `[F]` Financial DB(`db/financial/financial.db`)에 실제 컬럼이 있음
  - `[V]` BGE Vector DB(`db/vector/filings_bge_m3.db`)에 실제 컬럼이 있음
  - `[M]` 중앙 MySQL(`dart_big_in`)에 있음. 이름이 다른 경우는 6.1절 참고
  - `[응답]` DB 컬럼은 아니지만 함수 반환값에 있음
  - `[CSV]` 중간 산출 CSV에만 있음
  - `[미구현]` 현재 코드에 없음. 향후 도입 제안
- **원천/가공**: `원천` = DART에서 받은 값 그대로, `가공` = 프로젝트 코드가 만든 값
- 요청서에 적힌 필드명과 실제 컬럼명이 다른 경우가 있다. 각 표의 "실제 컬럼"을 확인한다.

---

## 1. 공통 필드

| 필드명 | 한글 설명 | 타입 | 예시 | null | 원천/가공 | 생성 주체 | 주의사항 |
|---|---|---|---|---|---|---|---|
| `corp_name` | 기업명 | TEXT | `삼성전자` | N | 원천(DART 기업코드 목록) | `DartClient.resolve_companies` | Financial DB 테이블에서는 컬럼명이 **`company_name`**(`companies` 테이블). 조회 결과에서 `corp_name`으로 바뀐다. 기업명은 바뀔 수 있으므로 식별은 `corp_code`로 한다. `[F][V]` |
| `corp_code` | DART 기업 고유번호 | TEXT(8) | `00126380` | N | 원천 | DART corpCode.xml | **문자열**로 저장(앞자리 0 보존). 숫자로 바꾸면 안 된다. `[F][V]` |
| `stock_code` | 상장 종목코드 | TEXT(6) | `005930` | Y | 원천 | DART corpCode.xml | Financial `companies`에만 있다. Vector DB에는 없다. 동명 법인 중 **상장 레코드를 고르는 기준**으로 쓰인다. `[F]` |
| `year` | 사업연도 | INTEGER | `2024` | N | 가공(요청 파라미터) | 수집 코드 | 공시를 **제출한 해가 아니라** 다루는 회계연도. 2024 사업보고서는 2025년 3월에 제출된다. Financial에서는 `periods` 테이블에 있고 `period_id`로 연결. `[F][V]` |
| `report_type` | 보고서 유형 | TEXT | `Q1`, `H1`, `Q3`, `FY` | N | 가공 | `src/config.py` `REPORTS` | DART 보고서 코드: Q1=`11013`(1분기), H1=`11012`(반기), Q3=`11014`(3분기), FY=`11011`(사업보고서). "Q2", "Q4" 보고서는 없다. `[F][V]` |
| `report_code` | DART 보고서 코드 | TEXT | `11011` | N | 원천 | 〃 | `periods` 테이블. `[F]` |
| `rcept_no` | DART 접수번호 | TEXT(14) | `20250325000491` | Financial: Y / Vector: N | 원천 | DART | 재무 숫자와 공시 원문을 잇는 **핵심 연결 키**. 앞 8자리는 접수일(YYYYMMDD). 정정공시가 있으면 최신 접수번호가 선택된다. `[F][V]` |

---

## 2. Financial 필드

### 2.1 핵심 필드

| 요청 필드명 | 실제 컬럼 | 한글 설명 | 타입 | 예시 | null | 원천/가공 | 생성 주체 | 주의사항 |
|---|---|---|---|---|---|---|---|---|
| `account_id` | `account_id` | DART/XBRL 계정 ID | TEXT | `ifrs-full_Revenue` | Y | 원천 | DART API | 회사가 표준 ID를 안 쓰면 `-표준계정코드 미사용-` 또는 회사 고유 확장 태그. `[F]` |
| — | `account_key` | 내부 매핑 키 | TEXT | `ifrs-full_Revenue` 또는 `name:매출액` | N | 가공 | `clean_financials` | 유효한 account_id가 있으면 그것, 없으면 `name:`+정규화 계정명. `[F]` |
| `account_name` | `original_account_nm` | 원본 계정명 | TEXT | `수익(매출액)` | N | 원천 | DART API(`account_nm`) | 원문 추적용으로 그대로 보존. `[F]` |
| `standard_account` | `standard_account_nm` | 표준 계정명 | TEXT | `매출액` | Y | 가공 | 매핑 단계 | 운영 5개사의 검증된 매핑 결과다. 24개 표준계정만 쓰려면 표준계정 목록으로 거른다. `[F]` |
| — | `sj_div` | 재무제표 종류 | TEXT | `BS`,`IS`,`CIS`,`CF`,`SCE` | N | 원천 | DART API | 같은 계정이 IS와 CIS에 동시에 있을 수 있다. `[F]` |
| `raw_value` | `raw_value` | 원본 값 문자열 | TEXT | `21432773671`, `(1,234)` | Y | 원천 | DART API | 숫자로 계산하지 말고 보존용으로만 본다. `[F]` |
| `value` | `normalized_value` / `calculated_value` | 실제로 쓸 숫자(원 단위) | INTEGER | `21432773671` | Y | 가공 | `parse_amount`, `period_normalizer` | **단일 `value` 컬럼은 없다.** `is_calculated=1`이면 `calculated_value`, 아니면 `normalized_value`를 쓴다. 괄호는 음수로 해석. 단위는 원(KRW). `[F]` |
| — | `is_calculated` | 계산값 여부 | INTEGER(0/1) | `1` | N | 가공 | 〃 | 1이면 DART가 직접 준 값이 아니라 프로젝트가 계산한 값. `[F]` |
| `fs_div` | `fs_div` | 연결/별도 구분 | TEXT | `CFS`, `OFS` | N | 원천(요청값) | 수집 코드 | 같은 기업·기간이라도 CFS와 OFS는 다른 숫자. **섞어서 비교 금지.** `[F]` |
| `period` | `period_type`, `value_type`, `period_start`, `period_end` + `report_type` | 기간 의미 | TEXT/날짜 | `quarterly`, `2024-04-01`~`2024-06-30` | start만 Y | 가공 | `normalize_period_values` | **단일 `period` 컬럼은 없다.** 아래 3장 "기간 개념" 참고. 날짜는 12월 결산 가정으로 보고서 유형에서 추론. `[F]` |
| `value_source` | `value_source` | 값 출처 유형 | TEXT | `reported`, `direct`, `derived` | N | 가공 | `capex_db` | `capex_facts`에만 실제 컬럼(`direct`/`derived`). 통합 VIEW `financial_facts_final`에서는 일반 계정이 `reported`로 표시됨. `[F]`(capex), VIEW |
| `source_values` | `source_values` | 계산에 쓴 원천 값 | TEXT(JSON) | `{"H1": 11066442727, "Q1": 6043262949}` | Y | 가공 | `period_normalizer`, `capex_db` | 문자열로 저장된 JSON. 파싱해서 쓴다. (예시 숫자는 형식 설명용) `[F]` |
| `calculation_method` | `calculation_method` | 계산 방법 | TEXT | `H1 cumulative - Q1 cumulative [...]` | Y | 가공 | 〃 | 직접 값이면 null(일반 계정). `[F]` |
| `mapping_method` | (DB에 없음) | 매핑 방법 | TEXT | `direct`, `alias`, `existing_mapping`, `none` | — | 가공 | — | **현재 운영 데이터에는 이 필드가 없다**(취소된 확장 작업 코드에만 있었음). Financial DB·MySQL 모두 저장하지 않는다. 계정이 어떻게 연결됐는지는 `account_mapping.mapping_status`와 `standard_account_mapping.mapping_confidence`(high=ID 일치, medium=이름 일치)로 판단한다. `[미구현]` |
| `review_status` | (DB에 없음) / 관련: `account_mapping.mapping_status`, `capex_facts.review_required` | 검토 상태 | TEXT / INTEGER | `review_required`, `unmapped`, `auto_account_id` | — | 가공 | 매핑 코드 | 계정 단위 상태는 `account_mapping.mapping_status`(`auto_account_id` / `review_required`), CAPEX는 `review_required`(0/1), 24계정 매핑은 `standard_account_mapping.mapping_status`(`approved`/`review_required`). 이름이 제각각이므로 통일 필요. `[F][M]` |
| — | `currency` | 통화 | TEXT | `KRW` | Y | 원천 | DART API | |
| — | `ord` | DART 표시 순서 | INTEGER | `3` | Y | 원천 | DART API | 고유키에 포함되나 null일 수 있다(MySQL 계획 참고). |

### 2.2 CAPEX 전용 필드 (`capex_facts`)

| 실제 컬럼 | 한글 설명 | 타입 | 예시 | null | 주의사항 |
|---|---|---|---|---|---|
| `cash_outflow_amount` | 설비투자 지출 규모(양수) | INTEGER | `21432773671` | N | 조회 함수는 이 값을 `normalized_value`로 바꿔서 돌려준다. |
| `normalized_value` | 부호 포함 원본 합계 | INTEGER | `-21432773671` | Y | 조회 결과에서는 `signed_normalized_value`로 이름이 바뀜. |
| `sign_normalized` | 음수 값이 있었는지 | INTEGER(0/1) | `1` | N | |
| `is_derived` | 구성계정 합산 여부 | INTEGER(0/1) | `0` | N | derived면 1 |
| `capex_method` | 산출 방식 | TEXT | `direct_account`, `component_fallback` | N | |
| `source_account_ids` / `source_account_names` | 사용 계정 | TEXT(JSON 배열) | `["dart_PurchaseOfLand", ...]` | N | |
| `source_account_count` | 사용 계정 수 | INTEGER | `3` | N | |
| `direct_account_found` | 직접 계정 존재 | INTEGER(0/1) | `1` | N | |
| `review_required` | 사람 검토 필요 | INTEGER(0/1) | `0` | N | 직접 계정이 2개 이상이거나 분기 차감값이 음수면 1 |
| `note` | 설명 | TEXT | `direct CAPEX account selected; ...` | Y | |

### 2.3 Financial DB 테이블 한눈에 보기 (`src/db/financial_db.py`, `src/db/capex_db.py`)

| 테이블 | 한 행의 의미 | 키 |
|---|---|---|
| `companies` | 기업 1개 | PK `corp_code` |
| `periods` | 연도 × 보고서 유형 1개(모든 기업 공용) | PK `period_id`(자동번호), UNIQUE(`year`,`report_type`) |
| `account_mapping` | 매핑 키 × 재무제표 1개 | PK(`account_key`,`sj_div`) |
| `financial_facts` | 기업·기간·계정·값 유형 1개 값 | PK `fact_id`(자동번호), UNIQUE(`corp_code`,`period_id`,`fs_div`,`sj_div`,`account_key`,`ord`,`value_type`,`is_calculated`) |
| `capex_facts` | 기업·기간·fs_div·값 유형 1개 CAPEX | PK `capex_id`(자동번호, 빌드마다 바뀜), UNIQUE(`corp_code`,`period_id`,`fs_div`,`value_type`) |
| `capex_build_metadata` | CAPEX 빌드 정보 key/value | PK `key` |
| `pipeline_runs` | 파이프라인 실행 1회 | PK `run_id` |
| `financial_facts_final` (VIEW) | 일반 계정 + CAPEX 통합 조회 | — |

---

## 3. Vector 필드 (`filing_chunks`, `src/retrieval/bge_m3_indexer.py`)

| 필드명 | 한글 설명 | 타입 | 예시 | null | 원천/가공 | 생성 주체 | 주의사항 |
|---|---|---|---|---|---|---|---|
| `chunk_id` | 청크 고유 ID | TEXT | `20250325000491:v2:12:3` (형식 예시) | N | 가공 | `text_chunker_v2` | 형식 `{rcept_no}:v2:{section_index}:{chunk_index}`. UNIQUE. 한번 정해지면 바꾸지 않는다. |
| `vector_id` | 벡터 번호 | INTEGER | `21797` (형식 예시) | N | 가공 | `bge_m3_indexer` | SQLite PK이자 **FAISS ID와 동일**. 새 청크는 기존 최대값 다음 번호를 받고, 기존 번호는 재배정하지 않는다. legacy `filings.db`에는 없다. |
| `section_name` | 상위 목차명 | TEXT | `II. 사업의 내용` | N | 가공(원문 제목) | `parse_filing_document` | 제목이 없으면 `문서 본문` |
| `subsection_name` | 하위 목차명 | TEXT | `7. 기타 참고사항` | Y | 가공 | 〃 | |
| `source_file` | 원본 XML 경로 | TEXT | `data/raw/filings/xml/<corp_code>/<year>/<type>/<rcept_no>/...` | N | 가공 | 수집·파싱 코드 | 프로젝트 상대경로. 외부 사용자에게 노출 금지. |
| `chunk_text` | 검색·답변용 본문 | TEXT | `당사는 ...` | N | 가공 | `clean_text` | 정제본. 약 600 토큰, 앞뒤 청크와 약 100 토큰 겹침(정확히 보장되지는 않음). |
| `original_text` | 정제 전 원문 | TEXT | | N | 가공(파싱) | `text_chunker_v2` | 감사·검증용 |
| `content_hash` | 본문 해시 | TEXT | sha256 | N | 가공 | 〃 | 같은 본문인지 비교. 재임베딩 판단에 사용 |
| `chunk_version` | 청킹 규칙 버전 | TEXT | `bge-m3-token-v2` | N | 가공 | 〃 | |
| `token_count` | 토큰 수 | INTEGER | `587` | N | 가공 | 〃 | |
| `content_type` | 청크 유형 | TEXT | `narrative`, `table`, `toc`, `governance`, `financial_statement`, `short_statement` | N | 가공 | `_classify` | |
| `search_priority` | 검색 우선순위 | REAL | `1.0` | N | 가공 | 〃 | 운영 기본(pure dense)에서는 **사용하지 않음** |
| `is_searchable` | 검색 대상 여부 | INTEGER(0/1) | `1` | N | 가공 | 〃 | 1인 행만 FAISS에 들어간다 |
| `embedding` | 벡터 값 | BLOB | float32 × 1024 = 4096 bytes | N | 가공 | BGE-M3 | 사람이 읽는 값 아님 |
| `score` | 검색 점수 | float | `0.61` (형식 예시) | N | 가공 | 검색 함수 | `[응답]` DB 컬럼 아님. 아래 "점수" 참고. |

검색 결과의 점수 관련 필드 `[응답]`:

| 필드 | 의미 |
|---|---|
| `dense_score` | 질문 벡터와 청크 벡터의 정규화 내적(= 코사인 유사도). 1에 가까울수록 비슷 |
| `lexical_score` | 키워드 겹침 점수(0~1로 정규화). pure dense에서는 참고용 |
| `final_score` / `score` | 정렬에 쓴 최종 점수. 운영 기본(`bge_m3_dense`)은 `dense_score`와 같음 |
| `rank` | 1부터 시작하는 순위 |
| `retrieval_method` | 실제 사용한 점수 방식 이름 |

> 점수는 **같은 질문·같은 방식 안에서 순서를 정하는 용도**다. 다른 방식끼리 비교하거나 "0.5 이상이면 정답" 같은 고정 기준으로 쓰지 않는다.

---

## 4. 운영 필드

| 필드명 | 한글 설명 | 타입 | 예시 | null | 위치 | 생성 주체 | 주의사항 |
|---|---|---|---|---|---|---|---|
| `model_name` | 임베딩 모델명 | TEXT | `BAAI/bge-m3` | N | `[V]` 컬럼명은 **`embedding_model`**, `vector_metadata.embedding_model` | `bge_m3_indexer` | legacy DB는 `local-ko-en-finance-hashing-v1` |
| `model_revision` | 모델 버전(커밋 해시) | TEXT | `5617a9f61b028005a4858fdac845db406aefb181` | N | `[V]` `model_revision`, `vector_metadata` | 〃 | 다르면 운영 검색이 시작되지 않는다(fail-closed) |
| `embedding_dimension` | 벡터 차원 | INTEGER | `1024` | N | `[V]` | 〃 | legacy는 컬럼명 `dimensions`, 값 1536 |
| `retriever` | 검색 방식 | TEXT | `bge_m3_dense`, `feature_hashing_hybrid` | N | `[응답]` `requested_retriever`, `effective_retriever`, 행의 `retrieval_method` / 환경변수 `FILING_RETRIEVER` | `operational_retriever` | fallback이 일어나면 요청값과 실제값이 다르다 |
| `data_version` | 데이터 묶음 버전 | VARCHAR | `2026-10-06-dart5-v1` | N | `[M]` `data_versions` 테이블 + 모든 사실 테이블의 컬럼 | `infra/mysql/sync_sqlite_to_mysql.py` | Financial DB·BGE DB·FAISS 세 파일의 sha256을 한 이름으로 묶는다. 현재 버전은 `data_versions.is_current=1`. SQLite·Python 함수 쪽에는 없다 |
| `manifest_version` | manifest 형식 버전 | TEXT | `1` (제안) | — | `[미구현]` | — | 현재 운영 파이프라인에는 manifest 파일이 없다. 동기화 이력은 MySQL `sync_runs`, 버전은 `data_versions`로 관리한다 |

참고 `vector_metadata` 키(코드 기준): `embedding_model`, `model_revision`, `embedding_dimension`, `normalize_embeddings`, `chunk_version`, `faiss_index_type`(`IndexIDMap2(IndexFlatIP)`), `searchable_vector_count`.

---

## 5. 쉽게 설명하는 개념

### 5.1 재무제표 구분

| 용어 | 쉬운 설명 |
|---|---|
| **CFS** (연결재무제표) | 모회사 + 자회사를 **한 회사처럼 합쳐서** 만든 재무제표. 그룹 전체 성적표. |
| **OFS** (별도재무제표) | 자회사를 빼고 **그 회사 하나만** 본 재무제표. |
| 왜 중요한가 | 같은 회사·같은 기간이라도 숫자가 다르다. 자회사가 없는 회사는 OFS만 있다. 현재 운영 5개사는 **모두 CFS**만 저장돼 있다(수집 기본값 `fs_div="CFS"`). 나중에 자회사가 없는 기업을 추가하면 OFS가 섞이므로, 회사끼리 비교할 때 CFS와 OFS가 섞였는지 꼭 확인한다. |

### 5.2 보고서와 기간

| 용어 | 쉬운 설명 |
|---|---|
| **Q1** | 1분기 보고서(1~3월) |
| **H1** | 반기 보고서(1~6월). "2분기 보고서"는 따로 없다. |
| **Q3** | 3분기 보고서(1~9월) |
| **FY** | 사업보고서(1~12월, 1년 전체) |
| **누적값** (`cumulative`) | 연초부터 그 보고서 시점까지 **쌓인** 값. 예: H1 누적 매출 = 1~6월 매출 합. |
| **단일분기값** (`quarterly`) | **그 분기 3개월만**의 값. 예: 2분기(4~6월) 매출. |
| **연간값** (`annual`) | FY 보고서의 1년 전체 값 |
| **시점값** (`point_in_time`) | 특정 날짜의 잔액(재무상태표). 예: 6월 30일 현재 현금. 더하거나 빼서 분기값을 만들지 않는다. |
| 분기값 계산 | DART가 단일분기값을 안 주는 경우(주로 현금흐름표) 코드가 계산한다: `2분기 = H1 누적 − Q1 누적`, `3분기 = Q3 누적 − H1 누적`, `4분기 = FY 연간 − Q3 누적`. 계산된 값은 `is_calculated=1`. |
| 흔한 실수 | H1의 누적값을 "2분기 값"이라고 말하는 것. 분기 질문에는 `value_type=quarterly`만 쓴다. |

### 5.3 계정 매핑 상태

| 용어 | 쉬운 설명 |
|---|---|
| **direct** | DART 공식 계정 ID(`account_id`)가 표준계정 정의와 **정확히 일치**해서 자동 연결. 가장 믿을 만함. |
| **alias** | ID는 안 맞지만 **계정 이름**이 승인된 별칭 목록과 일치해서 연결. 예: `영업손익` → `영업이익`. |
| **derived** | 여러 계정을 **합쳐서 계산**한 값. 현재는 CAPEX에서만 쓰인다. |
| **unmapped** | 어떤 표준계정에도 연결하지 못함. 값이 틀린 것이 아니라 "아직 연결 안 됨". |
| **review_required** | 후보는 있지만 확신이 부족해 **사람이 확인해야** 함. 임의로 확정하지 않는다. |

### 5.4 CAPEX (설비투자)

CAPEX = 그 기간에 공장·기계·건물 같은 **유형자산을 사기 위해 쓴 현금**. 현금흐름표(CF)에서 가져온다.
`유형자산`(재무상태표의 잔액)과는 다른 개념이다.

| 용어 | 쉬운 설명 |
|---|---|
| **CAPEX direct** | 현금흐름표에 `유형자산의 취득` 총액 계정이 있어서 **그 값을 그대로** 사용. |
| **CAPEX derived** | 총액 계정이 없어서 토지·건물·기계장치·건설중인자산 등 **세부 취득 계정을 합산**. 무형자산·소프트웨어·회원권·투자부동산·영업권은 제외. |
| **CAPEX unresolved** | 직접 계정도 세부 계정도 없어 **계산할 수 없음**. DB에 행이 없다. "0원"이 아니다. MySQL `coverage.capex_status = 'unresolved'`로 표시된다. 현재 5개사는 unresolved 0건(direct 48, derived 12) |

### 5.5 검색(Vector) 관련

| 용어 | 쉬운 설명 |
|---|---|
| **BGE-M3 embedding** | 문장을 **1024개의 숫자 목록**으로 바꾸는 AI 모델(`BAAI/bge-m3`). 뜻이 비슷한 문장은 비슷한 숫자 목록이 된다. |
| **vector (벡터)** | 그 숫자 목록. 문장의 "의미 좌표"라고 생각하면 된다. |
| **FAISS** | 많은 벡터 중에서 질문 벡터와 가장 가까운 것을 빠르게 찾아 주는 라이브러리. 이 프로젝트는 근사 없이 **전부 비교하는 정확 검색**(`IndexFlatIP`)을 쓴다. |
| **SQLite metadata filter** | 벡터 비교 **전에** SQLite에서 기업·연도·보고서·접수번호가 맞는 청크만 먼저 고르는 단계. 그래서 다른 회사·다른 연도 문서가 섞이지 않는다. |
| **normalized inner product** | 길이를 1로 맞춘 두 벡터를 곱해 더한 값 = 코사인 유사도. 방향이 같을수록 1에 가깝다. |
| **Top-K** | 점수가 높은 순서로 **상위 K개**만 돌려준다. 기본 K=5. |
| **chunk (청크)** | 긴 공시를 검색하기 좋게 자른 조각(약 600 토큰). |

---

## 6. 연결 키 요약

| 목적 | 키 |
|---|---|
| 기업 식별 | `corp_code` |
| 기간 식별 | `year` + `report_type` (Financial 내부는 `period_id`) |
| 재무 숫자 ↔ 공시 원문 | `rcept_no` (+ `corp_code`, `year`, `report_type`) |
| 계정 표준화 | `account_key` + `sj_div` |
| 청크 ↔ FAISS | `vector_id` |
| 청크 고유 식별 | `chunk_id` |

### 6.1 MySQL에서 이름·형태가 다른 것

| SQLite | MySQL `dart_big_in` | 설명 |
|---|---|---|
| `companies.company_name` | `companies.corp_name` | 이름만 다름 |
| `period_id` → `periods` | `year`, `report_type` 컬럼 | MySQL은 기간을 직접 저장(자동번호 미사용) |
| `financial_facts.fact_id` | `financial_facts.fact_id` | MySQL 자체 번호. SQLite 번호와 다름, 외부 키로 쓰지 않음 |
| `financial_facts.ord` | `ord` + `ord_key` | `ord_key = ord`(NULL이면 -1). 중복 방지용 |
| `capex_facts.capex_id` | `capex_facts.capex_fact_id` | MySQL 자체 번호 |
| `filing_chunks`(BGE DB) | `chunk_metadata` | **`embedding` BLOB 제외**. `index_version` 추가 |
| `vector_metadata`(key/value) | `embedding_metadata`(1행) | FAISS·SQLite 파일 sha256과 벡터 수 포함 |
| — | `filings` | 공시 1건 = 1행(`rcept_no`), `rcept_dt`는 접수번호 앞 8자리 |
| — | `coverage` | 기업×기간 슬롯별 존재 여부 |
| — | `is_active` | 동기화 때 사라진 행은 지우지 않고 0으로 표시. 조회 시 `is_active = 1` |
| — | `data_version` | 이 행을 넣은 데이터 버전 |
| `financial_facts_final` VIEW | `standardized_financials` VIEW | MySQL VIEW는 24개 표준계정 + CAPEX만, `value` 단일 컬럼 |

## 7. 추후 확인 필요

1. `financial_facts.standard_account_nm`은 메인 파이프라인 매핑 초안의 이름(가장 많이 쓰인 계정명)이라, 24개 표준계정 이름과 항상 같지는 않다. 24개 기준 조회는 MySQL `standardized_financials` VIEW 또는 `standard_accounts`로 거른다.
2. 검토 상태 필드(`mapping_status`, `review_required` 등) 이름을 통일할지.
3. `manifest_version` 도입 여부(현재 버전 관리는 MySQL `data_versions`로 대체).
4. 현재 5개사는 모두 12월 결산이다. 다른 결산월 기업을 추가하면 `period_start/end` 계산 규칙을 바꿔야 한다.

## 8. 주의: 은행 비용 지표의 부호 (2026-10-09 조사)

대상: `financial_metric_values`의 `CREDIT_LOSS_EXPENSE`(신용손실비용), `INTEREST_EXPENSE`(이자비용), `FEE_COMMISSION_EXPENSE`(수수료비용)

- **부호는 비용/환입을 뜻하지 않는다.** 값은 공시 API(XBRL)가 보낸 부호를 그대로 따른다. 회사·연도·보고서마다 비용을 양수로 보내기도 하고 음수로 보내기도 한다.
  - 예: 신한 2024 신용손실비용은 Q1~Q3 음수, Q4 양수다. 우리 2024도 Q1~Q3 음수, Q4 양수다.
- 2023~2025년 금융 5개사의 신용손실비용은 **모든 기간이 실제 비용(순전입)**이다. 원문 손익계산서 소계와 표시 방식으로 확인했다. 음수 28행도 환입이 아니다.
- **증감 해석 금지 예:** 우리 2024 Q3 −4,783억 → Q4 +4,625억은 "9,408억 증가"가 아니다. 실제로는 158억 감소다.
- 표준 부호 정책(양수 = 비용)이 반영되기 전까지:
  - 증감·순위·평균은 절댓값으로 계산한다. 이 가정은 위 범위에서만 검증됐다.
  - 새 기간이나 새 회사는 원문 확인 전까지 같은 가정을 쓰지 않는다.
  - 원본 부호가 필요하면 `financial_facts.raw_value`를 쓴다.
- 상세: `docs/handoff/CREDIT_LOSS_SIGN_INVESTIGATION_20261009.md`

### 8.1 표준 부호 정책 (2026-10-09 `expense-sign-v9` 운영 반영)

아래 규칙이 운영에 적용됐다. 위 8절의 "절댓값으로 계산" 임시 안내는 폐기한다. 이제 `value`를 그대로 쓴다.

| 항목 | 내용 |
|---|---|
| 적용 지표 | 금융 5개사의 `CREDIT_LOSS_EXPENSE`, `INTEREST_EXPENSE`, `FEE_COMMISSION_EXPENSE` (각 120행: 누적·연간 60, 분기 60) |
| `value` 의미 | **양수 = 비용 발생(순전입), 음수 = 순환입(이익)**. 2023~2025 전 기간이 비용이므로 현재 값은 모두 양수 |
| 원본 부호 | `financial_facts`(API 원값)는 바꾸지 않는다. 지표 행의 `source_values.sign_standardization.original_value`에 공시 원값이 남는다 |
| 판단 근거 | 원문 손익계산서의 소계 관계(예: 총영업이익 − 신용손실 = 순영업이익) 또는 같은 표 일반관리비와의 표시 방식. 근거 없으면 원값 유지 + `review_required` |
| 분기값 | 표준화한 누적값의 차이. Q1+Q2+Q3+Q4 = FY가 45/45 은행-연도-지표에서 성립(반영 전 35/45) |
| 영향 없음 | 순이자이익·순수수료이익(공시 원값으로 계산), 원천 사실값, CAPEX, 일반산업 데이터·KPI |

`source_values.sign_standardization` 필드:

| 필드 | 뜻 |
|---|---|
| `policy` | `expense_positive` |
| `original_value` / `original_sign` | 공시(API·XML 추출) 원값과 부호 |
| `standardized_value` | 표준화 값(= `value`). 근거가 없으면 `null` |
| `status` | `standardized` 또는 `unverified` |
| `meaning` | `expense`(비용) 또는 `reversal`(순환입) |
| `basis` | `subtotal`, `reference_line`, 분기는 `standardized cumulative difference` |
| `evidence`, `evidence_rcept_no` | 근거 내용과 근거 공시 접수번호(누적·연간 행) |
| `inputs` | 분기 행 계산에 쓴 표준화 누적값 |
| `source_rcept_no`, `method` | 원값의 공시 접수번호와 계산 방식 |
| `original_review_status` | 표준화 전 검토 상태 |

변경 전후(값이 바뀐 76행, 크기는 모두 그대로):

| 지표 | 회사(연도) | 바뀐 행 |
|---|---|---:|
| CREDIT_LOSS_EXPENSE | 신한(2023 8·2024 6), 우리(2023 2·2024 6), 하나(2023 6) | 28 |
| INTEREST_EXPENSE | 신한(2023 8·2024 6), 하나(2023 8·2024 2), 카카오뱅크(2023 2) | 26 |
| FEE_COMMISSION_EXPENSE | 신한(2023 8·2024 6), 하나(2023 6), 카카오뱅크(2023 2) | 22 |

예시(분기값, 억원):
- 우리 2024 신용손실: 반영 전 −3,665 / −4,090 / −4,783 / 4,625 → 반영 후 3,665 / 4,090 / 4,783 / 4,625
- 신한 2024 이자비용: 반영 전 −43,746 / −44,231 / −45,477 / 44,616 → 반영 후 43,746 / 44,231 / 45,477 / 44,616

주의:
- 반영 후에는 `value`를 그대로 증감·비교에 쓰면 된다. 절댓값 처리를 따로 하면 순환입(음수)이 비용으로 바뀌므로 하지 않는다.
- 공시 표시 그대로의 부호가 필요하면 `original_value` 또는 `financial_facts`를 쓴다.
- 순이자이익 = 이자수익 − |이자비용| 계산은 지표 계층이 이미 공시 원값으로 하므로, 백엔드가 표준화 값으로 다시 계산할 필요가 없다.
- 새 기간·새 회사는 근거 매니페스트(`src/db/expense_sign_manifest.json`)에 없으면 `review_required`로 들어온다. 수집 후 `python -m src.quality.expense_sign_evidence --write`로 근거를 갱신하고 검토한다.
