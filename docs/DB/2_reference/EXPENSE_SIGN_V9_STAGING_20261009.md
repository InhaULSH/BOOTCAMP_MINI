# 은행 비용 지표 표준 부호 (expense-sign-v9) staging 검증

- 작성일: 2026-10-09
- 상태: **운영 반영 완료** — SQLite·MySQL current `2026-10-09-dart25-expense-sign-v9` (`financial.db` `e22afed6…`)
- 운영본: SQLite·MySQL current `2026-10-09-dart25-residual-v8` (`financial.db` `72a77cb9…`). 변경하지 않았다.
- staging: `db/staging/20261009_expense_sign_v9/financial.db` (`e22afed6333638388157383aa34c5bdc7ff0a88229cd6b9496792cd3ebacd949`)
- 보고서·증적: 같은 폴더 `reports/` (변경 행 CSV, 검증 출력, 감사, 전체 테스트 기록)
- 조사 배경: `docs/handoff/CREDIT_LOSS_SIGN_INVESTIGATION_20261009.md`

## 1. 결과 요약

| 지표 | 검증 대상(누적·연간) | 근거 확인 | 미검증 | 수정 대상(값 변경) | 부호 확인만(값 유지) |
|---|---:|---:|---:|---:|---:|
| CREDIT_LOSS_EXPENSE | 60 | 60 (소계 24, 표시 방식 36) | 0 | 28 | 92 |
| INTEREST_EXPENSE | 60 | 60 (소계 48, 표시 방식 12) | 0 | 26 | 94 |
| FEE_COMMISSION_EXPENSE | 60 | 60 (소계 48, 표시 방식 12) | 0 | 22 | 98 |

- 지표마다 120행(누적·연간 60, 분기 60)을 표준화했다. 순환입으로 판정된 기간은 0건이다.
- 값이 바뀐 76행은 모두 금액 크기가 그대로이고 부호만 바뀌었다. 검토 상태 변경도 0건이다.
- 값이 그대로인 284행도 근거로 부호를 확인했다. 표준화 기록은 360행 모두에 남겼다.
- 이자비용·수수료비용도 5개사 전 기간의 원문 근거가 확인돼 같은 정책을 적용했다.
  - 카카오뱅크는 순이자·순수수료 소계 줄이 없어서 표시 방식으로 판정했다.

## 2. 구현

| 구성 | 위치 | 역할 |
|---|---|---|
| 근거 판정 | `src/quality/expense_sign_evidence.py` | 원문 손익계산서에서 판정한다. ① 소계 관계(총액 − \|값\| = 순액 → 비용, 총액 + \|값\| = 순액 → 순환입) ② 같은 열 일반관리비와 같은 표시 → 비용. 그 밖에는 판정하지 않는다. `abs()`로 판단하지 않는다 |
| 근거 매니페스트 | `src/db/expense_sign_manifest.json` | 180개 누적 기간의 판정·근거·접수번호. 공시 원값과 정확히 일치할 때만 적용된다 |
| 표준화 단계 | `src/db/expense_sign.py` | `refresh_derived_metrics`의 처음에 원값으로 복원하고(`restore_expense_signs`), 마지막에 표준화한다(`standardize_expense_signs`). 근거 없는 행은 원값 유지 + `review_required` |
| staging 적용 | `src/expense_sign_pipeline.py` | 운영 경로를 거부하고 재계산만 실행한다(지표 행 ID 보존) |
| 감사 | `src/quality/financial_db_audit.py` | 기존 출처 검사(DIRECT = 사실값, DERIVED 재현)는 원값으로 **부호까지** 그대로 수행한다. 별도 항목에서 근거 일치, 크기 일치, 분기 = 표준화 누적 차이를 검사한다 |

이중 부호 변환 방지:
- 모든 파생 계산은 공시 원값을 읽는다. 대상은 순이자이익·순수수료이익, 문서 분기, 검증 Q4다.
- 순이자이익은 계속 `이자수익 − ABS(공시 이자비용)`으로 계산한다.
- 값 가드가 있는 기존 스크립트(`sign_convention_corrections`, `residual_corrections`)는 `filed_value()`로 원값을 비교한다.
- 은행 XML 백필은 원값 복원 → 추출·검증 → 적재 → 재계산을 한 트랜잭션에서 실행한다. 두 번째 실행에서 표준화 값을 기준으로 부호를 맞추던 결함을 이번에 고쳤다.

## 3. 검증

| 항목 | 결과 |
|---|---|
| 운영본 대비 diff | `financial_metric_values` 360행(값·`source_values`)만 변경. 행 수·ID·스키마 동일. `financial_facts`·`capex_facts` 동일 |
| 비용 지표 외 행 | 1,197행 전부 동일(순이자이익·순수수료이익 포함) |
| 무결성·중복 | integrity ok, FK 0, 자연키 중복 0 |
| 재실행 | 변경 0. 현재 코드로 새로 만든 사본과 행 단위로 동일 |
| 전체 재빌드(`materialize`) | 비용 지표 360행이 값·산식·근거·검토 상태까지 재현됨. 차이 34행은 운영본에도 있는 카카오뱅크 순이자·순수수료의 과거 산식 표기 |
| 증분 재계산(`add_missing_fact_metrics`) | 변경 0 |
| 다른 파이프라인 재실행 | 은행 XML 백필, 잔여 보정, v8 보정, 기존 부호 보정 모두 변경 0 |
| 분기 재생성(`compute_quarters`) | 값 불일치 0(사실값 불변) |
| 분기 합 | Q1+Q2+Q3+Q4 = FY: 반영 전 35/45 → 반영 후 45/45 |
| 일반산업 KPI | staging에서 다시 생성한 4,479행이 KPI v7 백업과 동일. 은행 행은 KPI 단계로 바뀌지 않음 |
| 감사 | 위반 0. 신규 항목 "expense metric analysis sign" 360행 통과. 나머지 항목은 운영본과 동일 |
| 감사 민감도 | 부호를 뒤집거나 크기를 바꾸면 위반으로 잡힘(테스트) |
| 미검증 처리 | 근거를 제거하면 원값 유지 + `review_required`, 의존 분기도 `review_required`(테스트) |
| 전체 테스트 | 87개 통과(신규 3개) |
| 보호 대상 | 운영 SQLite·MySQL, Vector DB, FAISS, 임베딩, 원본 XML, KPI v7 백업 불변 |

## 4. 기존 분석 수치 영향

- **바뀌는 것:** 세 비용 지표의 `value` 부호(76행).
  - 백엔드 조회 `get_financial_metrics`와 분석기의 "신용손실·대손·이자비용·수수료" 답변이 모두 "양수 = 비용"으로 일관된다.
  - 예: 우리 2024 신용손실 분기값 −3,665 / −4,090 / −4,783 / 4,625억 → 3,665 / 4,090 / 4,783 / 4,625억
- **바뀌지 않는 것:**
  - 순이자이익·순수수료이익
  - 원천 계정 조회(`get_financial_context`)
  - CAPEX, 일반산업 KPI, KB 재작성 Q4, v8 보정값
  - 금액 크기
- **백엔드가 할 일:** 반영 후 임시 규칙(절댓값 계산)을 제거한다. 정의는 `docs/handoff/DATA_DICTIONARY.md` 8.1절을 따른다. 백엔드 코드는 수정하지 않았다.

## 5. 운영 반영 (승인 후에만)

1. 운영 SQLite·MySQL 백업과 해시 확인
2. staging 해시 확인 후 원자 교체
3. 무결성·재계산·감사·전체 테스트·AppTest
4. MySQL 적재(`--defer-promotion`) → 지표 1,557행 전체 대조 → 승격

- 제안 버전명: `2026-10-09-dart25-expense-sign-v9`
- 신규 공시를 수집한 뒤에는 `python -m src.quality.expense_sign_evidence`로 근거를 판정한다.
  - 새 기간은 근거를 추가하기 전까지 `review_required`로 표시된다.
  - 근거를 추가할 때는 `--write`로 매니페스트를 갱신하고, 바뀐 내용을 검토해 커밋한다.

## 6. 운영 반영 결과 (2026-10-09 수행)

| 항목 | 결과 |
|---|---|
| 반영 전 | SQLite·MySQL current `2026-10-09-dart25-residual-v8`, `financial.db` `72a77cb9…` |
| 로컬 백업 | `backups/local/20261009_pre_expense_sign_v9/financial.db`. 운영본과 바이트 단위로 같음, integrity ok, `SHA256SUMS` |
| MySQL 백업 | `backups/mysql/20261009_pre_expense_sign_v9/dart_big_in_pre_expense_sign_v9.sql` (`f93b714e…`). 23개 테이블 511,426행이 덤프 전 MySQL 행 수와 일치 |
| SQLite 교체 | staging 해시 확인 후 원자 교체 → `e22afed6333638388157383aa34c5bdc7ff0a88229cd6b9496792cd3ebacd949` |
| 변경 범위 | 지표 360행(`value`·`source_values`). 값이 바뀐 것은 76행이고 크기는 그대로. 검토 상태 변경 0. 사실값·CAPEX·기업·프로필·매핑 불변 |
| 파생 지표 | 순이자이익·순수수료이익 240행 불변 |
| 검증 | integrity ok, FK 0, 중복 0. 분기 재생성 불일치 0. 증분 재계산 재현. 전체 재빌드 시 비용 지표 재현(차이는 기존 카카오 산식 표기 34행뿐) |
| 테스트·감사 | 전체 87개 통과, AppTest 예외 0·기업 25, 감사 결과 staging과 동일 |
| MySQL | `--defer-promotion` 적재 → 지표 1,557행(20개 열)·부호 수정 76행·파생 240행·사실값 62,608행 전체 일치, 전체 검증 PASS 2회 후 current 승격 |
| 불변 | Vector DB, FAISS(`d8d17f64…`), 임베딩, 원본 XML, KPI v7 백업(`SHA256SUMS` 확인) |

복구 절차:
1. `backups/local/20261009_pre_expense_sign_v9/financial.db`를 운영 경로로 복사하고 SHA-256(`72a77cb9…`)을 확인한다.
2. MySQL은 덤프를 복원하거나, 복구한 로컬 파일로 새 버전을 적재한다.
3. 검증 스크립트를 실행한 뒤 `--promote`한다.

## 7. 백엔드 전달 사항

- **정의:** `CREDIT_LOSS_EXPENSE`, `INTEREST_EXPENSE`, `FEE_COMMISSION_EXPENSE`의 `value`는 양수 = 비용 발생, 음수 = 순환입이다. 현재 360행 모두 양수다.
- **임시 규칙 폐기:** 반영 전에 안내한 "절댓값으로 계산"을 없앤다.
  - `value`를 그대로 증감·순위·비교에 쓴다.
  - 절댓값 처리를 남겨 두면 앞으로 순환입(음수)이 비용으로 바뀌어 보인다.
- **원본 부호:** 공시 원값은 `source_values.sign_standardization.original_value`(MySQL은 `JSON_EXTRACT`로 조회) 또는 `financial_facts.raw_value`에 있다.
- **변경 전후:** 76행의 목록은 `db/staging/20261009_expense_sign_v9/reports/changed_rows.csv`에 있고, 요약은 `docs/handoff/DATA_DICTIONARY.md` 8.1절에 있다.
- **새 공시:** 근거 매니페스트에 없는 기간은 원값 그대로 `review_required`로 들어온다(자동 승인하지 않음).
  - `review_required` 행은 부호 의미가 확인되지 않은 값이다.
- **바뀌지 않은 것:** 순이자이익·순수수료이익, 원천 계정 조회(`get_financial_context`), 백엔드 코드
