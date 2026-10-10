# DART Big:in Financial DB 인계 자료 (2026-10-09)

- 운영 버전: `2026-10-09-dart25-h1h3-v11`. SQLite·MySQL이 동기화돼 있다.
- 검증: 자동 테스트 97개, 데이터 감사, MySQL 전체 검증 통과
- 범위: 25개사(반도체·헬스케어·철강·자동차·금융 각 5개사), 2023~2025 분기·연간
  - 2026 Q1/H1은 아직 운영에 없다.

## 먼저 읽을 것

1. `1_backend_guide/BACKEND_QUERY_GUIDE_H2_M1.md` — **백엔드 연동 시 반드시 반영할 조회 규칙**
   - Q4 계산 제한
   - review_required 지표 처리
   - 자본총계 기준
   - 조회 결과 200행 제한

## 폴더 구성

| 폴더 | 내용 |
|---|---|
| `1_backend_guide/` | 백엔드 조회·분기 계산 가이드(필수) |
| `2_reference/DATA_DICTIONARY.md` | 데이터 사전. 8절에 은행 비용 지표 부호(양수 = 비용) 규칙 |
| `2_reference/FINANCIAL_DB_BACKEND_READINESS_20261009.md` | 백엔드 사용 준비도 평가(판정 근거, 발견 사항, 데이터 사용 규칙) |
| `2_reference/BACKEND_FIX_H1_H3_STAGING_20261009.md` | v11 변경 내용: MySQL 표준 뷰 재정의, 에이치브이엠 별도재무제표 |
| `2_reference/EXPENSE_SIGN_V9_STAGING_20261009.md` | 금융 비용 지표 부호 표준화 상세 |
| `3_mysql_sql/` | MySQL 초기 스키마와 마이그레이션 001~006(적용 순서는 내부 README) |
| `4_team_client/` | MySQL 조회용 파이썬 모듈과 사용법 |

## 접속

- `4_team_client/.env.example`을 `.env`로 복사해 접속 정보를 채운다.
- **비밀번호는 이 자료에 없다.** 데이터 담당자에게 1:1로 받는다.
- `.env`는 Git·메신저·드라이브에 올리지 않는다.
- 백엔드 계정(`dart_backend`)은 읽기 전용(SELECT)이다.

## 참고

- 문서 안의 `src/…`, `db/…`, `backups/…` 경로는 데이터 담당자 작업 환경 기준이다. 팀원 환경에는 없을 수 있다.
- MySQL에서는 `standardized_financials` 뷰(24개 표준계정)와 `financial_metric_values`(금융 지표)를 기본 조회 대상으로 쓴다.
