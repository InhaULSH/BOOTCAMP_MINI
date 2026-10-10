# Financial v11 ↔ Vector·원본 XML 버전 불일치 원인 분석

- 작성일: 2026-10-09
- 범위: 읽기 전용 분석. 운영 SQLite·MySQL·Vector DB·FAISS·임베딩·원본 XML은 변경하지 않았다.
- 보고된 증상: 백엔드 서버 정합성 검사 실패. Financial DB는 `2026-10-09-dart25-h1h3-v11`, 벡터·원본 연결은 `2026-10-08-dart25-bank-xml-v1`.

## 1. 결론

- **실제 데이터 불일치나 손상은 없다.** 벡터 147,720개, 청크, 원본 XML 399개, FAISS가 서로 완전히 일치한다. 현재 버전(v11)이 기록한 해시와도 같다.
- **원인은 버전 표기 정책의 불일치다.**
  - 재무 동기화는 버전마다 `chunk_metadata`와 `embedding_metadata`의 **버전 표기만** 새 버전으로 바꾼다.
  - 벡터·원본 테이블(`chunk_embeddings`, `chunk_source_documents`, `filing_source_documents`)은 별도 스크립트로만 쓰인다. 이 스크립트는 벡터가 마지막으로 바뀐 bank-xml-v1 이후 실행되지 않았다.
  - 그래서 같은 데이터가 두 버전 이름으로 표기돼 있다.
- **불일치 표기:** 활성 행 기준 295,839행
  - `chunk_embeddings` 147,720행(`data_version`, `index_version` 둘 다 bank-xml-v1)
  - `chunk_source_documents` 147,720행
  - `filing_source_documents` 399행

## 2. 버전 정보 현황

| 대상 | 버전 표기 | 내용 해시·건수 |
|---|---|---|
| `data_versions` current | `2026-10-09-dart25-h1h3-v11` | financial `6ea2a85f…`, vector SQLite `a1b6f68e…`, FAISS `d8d17f64…` |
| `embedding_metadata` current | `bge-m3-2026-10-09-dart25-h1h3-v11` | FAISS `d8d17f64…`, SQLite `a1b6f68e…`, 147,720개, built_at 2026-10-08 00:32:37 |
| `chunk_metadata` (활성 147,720) | data/index_version 모두 v11 | content_hash가 로컬 벡터 DB와 147,720건 일치 |
| `chunk_embeddings` (활성 147,720) | data/index_version 모두 bank-xml-v1 | BLOB CRC32가 로컬과 147,720건 일치 |
| `chunk_source_documents` (147,720) | bank-xml-v1 | 청크 ↔ 문서 147,720건 |
| `filing_source_documents` (활성 399) | bank-xml-v1 | 원본 XML 399개 SHA-256 일치 |
| `filings`, `coverage`, 재무 테이블, 표준 뷰 | v11 | – |
| 로컬 파일 | – | FAISS `d8d17f64…`, `filings_bge_m3.db` `a1b6f68e…` |

**벡터 내용은 bank-xml-v1 이후 그대로다.**
- bank-xml-v1부터 h1h3-v11까지 10개 데이터 버전이 모두 같은 벡터·FAISS 해시를 기록했다.
- 그 사이 `embedding_metadata`에는 버전 이름만 다른 행이 하나씩 추가됐다.

## 3. 버전 갱신 경로

| 스크립트 | 쓰는 테이블 | 실행 시점 | 결과 |
|---|---|---|---|
| `infra/mysql/sync_sqlite_to_mysql.py` | `chunk_metadata`, `filings`, `coverage`, 재무 테이블, `embedding_metadata`(새 index_version 행) | 매 데이터 버전(v2~v11) | 행 내용은 그대로 두고 `data_version`·`index_version`을 새 버전으로 갱신 |
| `infra/mysql/sync_embeddings_to_mysql.py` | `chunk_embeddings` | 벡터가 바뀔 때만. 마지막 실행 2026-10-08 10:01, bank-xml-v1 | 이후 미실행이라 bank-xml-v1로 남음 |
| `infra/mysql/sync_source_documents_to_mysql.py` | `filing_source_documents`, `chunk_source_documents` | 마지막 실행 2026-10-08 10:04, bank-xml-v1 | 같음 |

재무 승격(v2~v11) 과정에서 **벡터 데이터는 바뀌지 않았다.** 바뀐 것은 다음 두 가지 버전 메타데이터뿐이다.
- `chunk_metadata.data_version`과 `index_version` 표기
- `embedding_metadata`에 같은 해시로 추가된 index_version 행

## 4. 연결 관계 검증 (읽기 전용 실측)

| 검사 | 결과 |
|---|---|
| vector_id 집합 | MySQL `chunk_metadata` = `chunk_embeddings` = 로컬 `filing_chunks` = FAISS id_map (147,720) |
| chunk_id | 메타데이터 ↔ 임베딩 147,720/147,720 |
| 청크 메타데이터(접수번호·회사·연도·보고서·원본 경로·content_hash) | 로컬 벡터 DB와 147,720/147,720 |
| 임베딩 바이트 | CRC32 147,720/147,720. FAISS 재구성 표본 300/300이 SQLite 벡터와 일치 |
| 임베딩 모델 | 전부 `BAAI/bge-m3` @ `5617a9f6…`, 1024차원(MySQL·로컬 동일) |
| 청크 → 원본 문서 | 147,720건 연결, 접수번호 147,720/147,720 일치, 연결 문서 모두 활성 |
| 원본 XML | 399개 파일 SHA-256 일치, 누락 0. 원본 경로가 없는 청크 0 |
| 해시 | 로컬 FAISS·벡터 DB가 current `data_versions`와 `embedding_metadata`의 기록값과 일치 |

## 5. 백엔드 정합성 검사 조건

- **확인한 범위:** 저장소에는 백엔드 서버 코드가 없다.
  - 저장소의 앱(`validate_bge_operational_assets`)은 파일 해시와 메타데이터만 비교하며, 통과한다.
  - 인계 명세 `BACKEND_INTERFACE_SPEC.md`는 `data_version` 정책을 "추후 정의"로 두었다.
- **추정:** 실패한 검사는 백엔드가 정한 규칙이고, "모든 활성 행의 `data_version`이 current와 같아야 한다"로 보인다.
- **백엔드 팀에 확인할 것**
  1. 검사 대상 테이블과 열(`data_version`, `index_version`, 해시 중 무엇을 비교하는지)
  2. 비교 기준(current 문자열 일치인지, 해시 일치인지)
  3. 실패 시 서비스 동작(차단인지 경고인지)

## 6. 권장 해결 방법 (벡터 재생성 불필요)

**A. 검사 기준을 "내용 해시 일치"로 정의한다(권장, 데이터 변경 0).**
- 벡터·원본 행의 `data_version`이 다음 조건의 버전 중 하나이면 정합으로 본다.
  - 해당 버전의 `data_versions.vector_sqlite_sha256`과 `faiss_sha256`이 current의 값과 같다.
  - 현재는 bank-xml-v1~v11이 모두 해당한다.
- `embedding_metadata`(current)의 `faiss_sha256`·`sqlite_sha256`이 실제 파일과 같은지 함께 확인한다.
- 의미상 정확하다. 벡터는 bank-xml-v1에서 만들어졌고 이후 바뀌지 않았다.

**B. 표기를 v11로 맞춘다(백엔드가 문자열 일치를 유지해야 할 때, MySQL 변경, 별도 승인).**
- 기존 동기화 스크립트를 v11로 다시 실행한다. **재생성이 아니라 같은 바이트를 검증하며 다시 적재하는 것**이다.
  - `sync_embeddings_to_mysql.py --data-version 2026-10-09-dart25-h1h3-v11`
    - current의 벡터 SQLite 해시가 실제 파일과 같을 때만 실행된다.
    - FAISS 표본 바이트 대조와 CRC 대조를 한다.
  - `sync_source_documents_to_mysql.py --data-version 2026-10-09-dart25-h1h3-v11`
    - 원본 바이트를 그대로 다시 적재하고 `chunk_source_documents` 표기를 갱신한다.
- 사전에 MySQL 백업을 받는다.
- 사후에 4절 검사를 다시 하고, 불일치 표기 0인지 확인한다.
- 범위: 약 295,839행 upsert(내용 동일). 임베딩·FAISS 파일과 원본 XML은 바뀌지 않는다.
- **하지 말 것:** 라벨 열만 `UPDATE`로 강제 변경(검증 단계가 빠짐)

**C. 재발 방지(A·B 어느 쪽이든)**
- 버전 정책을 하나로 정해 인계 명세에 적는다.
  - "벡터 계열은 벡터가 바뀐 버전으로 표기하고, 정합성은 해시로 판단"
  - 또는 "모든 계열을 매 승격마다 current로 재표기"
- 후자라면 승격 절차에 B의 두 스크립트를 포함한다.

## 7. 필요한 수정 범위

| 방법 | SQLite | MySQL | Vector·FAISS·XML | 백엔드 |
|---|---|---|---|---|
| A | 없음 | 없음 | 없음 | 정합성 검사 기준 변경 |
| B | 없음 | `chunk_embeddings`·`chunk_source_documents`·`filing_source_documents`의 표기(내용 동일 upsert) | 없음 | 없음 |
| C | 없음 | 없음 | 없음 | 인계 명세의 버전 정책 확정 |
