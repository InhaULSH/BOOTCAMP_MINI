# MySQL 스키마·마이그레이션 인계용 사본

- 원본 위치: `infra/mysql/init/01_schema.sql`, `infra/mysql/migrations/*.sql`
  - `infra/`는 저장소에서 아직 추적하지 않는 작업 폴더라 팀 인계 때 빠질 수 있다.
  - 그래서 비밀 정보가 없는 SQL만 이 폴더에 사본으로 둔다.
- 포함하지 않은 것: `infra/mysql/.env`, `infra/mysql/init/03_users.sh`(계정 생성 스크립트), 동기화 스크립트
  - 접속 정보와 비밀번호는 데이터 담당자에게 1:1로 받는다.
- 무결성: `SHA256SUMS`. 같은 내용의 백업은 `backups/handoff/20261009_infra_mysql_sql/`(저장소 밖)에 있다.
- 원본을 수정하면 이 사본도 다시 복사하고 `SHA256SUMS`를 갱신한다.

## 적용 순서

새로 설치할 때는 `init/01_schema.sql` 하나로 최신 구조가 만들어진다(006 반영본). 기존 DB에는 아직 적용하지 않은 마이그레이션만 번호 순으로 적용한다.

| 파일 | 내용 |
|---|---|
| `migrations/001_add_krx_index_layer.sql` | KRX 지수·구성종목 |
| `migrations/002_add_chunk_embeddings.sql` | 청크 임베딩 |
| `migrations/003_rename_krx_bank_to_steel.sql` | 지수 코드 정정 |
| `migrations/004_add_filing_source_documents.sql` | 원본 XML 문서 |
| `migrations/005_add_financial_metrics.sql` | 금융 지표 계층 |
| `migrations/006_standardized_financials_by_tag.sql` | 표준 뷰를 공식 계정 ID 기준으로 재정의(H1, `2026-10-09-dart25-h1h3-v11`에서 운영 적용) |

## 006 적용과 되돌리기

- **적용:** ETL 계정으로 006을 실행한다. 이 계정은 CREATE VIEW·DROP 권한이 있다.
  - `CREATE OR REPLACE VIEW`라 원자적으로 교체된다.
  - 조회 중인 세션은 짧은 메타데이터 잠금만 받는다.
- **확인**
  - 반환 행 수와 기업·연도별 FY 확보율을 본다(당기순이익·영업이익·영업CF가 일반 59/60, 금융 15/15).
  - 슬롯 중복 0, 자본변동표 행 0이어야 한다.
- **되돌리기:** `backups/mysql/20261009_pre_h1h3_v11/standardized_financials_before_v11.sql`을 같은 계정으로 실행한다.
  - 기존 정의에서 원래 DEFINER(root) 절만 뺀 파일이다.
