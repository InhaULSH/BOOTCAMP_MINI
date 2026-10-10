# DART 중앙 DB 팀원용 코드

데이터 담당자 PC의 MySQL(`dart_big_in`)에 읽기 전용으로 접속해 재무·공시 데이터를 조회하고,
공시 문단 **의미(유사도) 검색**까지 내 PC에서 실행하는 코드입니다.

| 파일 | 역할 |
|---|---|
| `dart_db_client.py` | 기업·재무·CAPEX·coverage 조회, 공시 키워드 검색 |
| `dart_semantic_search.py` | 질문과 비슷한 공시 문단 찾기(BGE-M3 + MySQL 벡터) |
| `requirements.txt` | 설치 패키지 |
| `.env.example` | 접속 정보 양식 |

## 1. 준비 (최초 1회)

1. 이 폴더를 내 PC에 내려받는다.
2. 패키지 설치
   ```bash
   pip install -r requirements.txt
   ```
3. `.env.example`을 복사해 `.env`로 저장하고 `MYSQL_PASSWORD`를 채운다(비밀번호는 데이터 담당자에게 1:1로 받기).
4. 데이터 담당자 PC와 **같은 네트워크(192.168.0.x)**에 연결돼 있어야 한다. 연결 확인:
   ```powershell
   Test-NetConnection 192.168.0.232 -Port 3306
   ```

## 2. 재무·텍스트 조회

```python
from dart_db_client import *

list_companies()                                          # 기업 5개
get_financials("삼성전자", 2024, "FY", ["매출액", "영업이익"])  # 재무 값(원)
get_quarterly_trend("삼성전자", "매출액", [2024])            # 분기 단독값 추이
get_capex("원익IPS", 2024)                                 # 설비투자
search_filing_text("HBM", corp_name="SK하이닉스", year=2024)  # 단어가 들어간 문단
query("SELECT COUNT(*) AS n FROM chunk_metadata")          # 직접 SQL (값은 %s로 전달)
```

## 3. 의미(유사도) 검색

**설치 후 처음 한 번은 모델 점검을 실행한다.** 내 PC의 BGE-M3가 MySQL 벡터를 만든 모델과 같은 결과를 내는지
저장된 청크를 다시 임베딩해 비교한다.

```python
from dart_semantic_search import verify_model
verify_model()      # "모델 일치 점검 PASS: 최소 코사인 1.000000" 이 나오면 정상 (기준 0.999)
```

FAIL이면 라이브러리 버전 차이일 수 있으니 결과를 데이터 담당자에게 알려 준다.

```python
from dart_semantic_search import semantic_search

semantic_search("HBM 수요 전망", corp_name="SK하이닉스", year=2024, report_type="FY", top_k=5)
```

- 결과: `rank`, `score`(코사인 유사도, 높을수록 비슷), `chunk_id`, 기업·연도·보고서·접수번호, 섹션, `chunk_text`(본문)
- 필터: `corp_name`, `corp_code`, `year`, `report_type`(Q1/H1/Q3/FY), `rcept_no` — 주면 그 범위 안에서만 찾는다.
- **처음 실행할 때 시간이 걸린다.**
  - BGE-M3 모델(약 2.3GB)을 Hugging Face에서 내려받는다(한 번만).
  - MySQL에서 벡터 21,797개(약 90MB)를 내려받아 `.dart_cache/`에 저장한다. 데이터 버전이 바뀌면 자동으로 다시 받는다.
- GPU가 없어도 동작한다(질문 1개 임베딩은 CPU로 수 초).
- 프로젝트 운영 검색(BGE-M3 Pure Dense)과 **같은 결과**가 나오도록 맞춰져 있다(2026-10-06 질문 6개로 상위 10개 순서 일치 확인).

## 4. 주의

- 계정은 **읽기 전용**이다. 데이터를 바꾸거나 지울 수 없다.
- 금액 단위는 **원**. 분기 비교는 `value_type="quarterly"`만 사용한다(H1·Q3는 누적값).
- 점수는 같은 질문 안에서 순서를 정하는 용도다. 고정 기준값(예: 0.5 이상)으로 쓰지 않는다.
- 모델을 다른 버전으로 바꾸면 결과가 틀어진다. 코드에 고정된 revision을 바꾸지 않는다.
- `.env`(비밀번호)는 Git·드라이브·단톡방에 올리지 않는다.
- 데이터 담당자 PC가 꺼지거나 절전 상태면 접속이 안 된다(한 번 받은 `.dart_cache/` 벡터는 남지만, 본문·재무 조회는 접속이 필요).

## 5. 안 될 때

| 증상 | 확인 |
|---|---|
| `Can't connect` / 시간 초과 | 같은 네트워크인지, 데이터 담당자 PC가 켜져 있는지 |
| `Access denied` | `.env`의 사용자(`dart_backend`)·비밀번호 |
| `KeyError: 'MYSQL_HOST'` | `.env` 파일이 실행 위치에 있는지 |
| 모델 다운로드 실패 | 인터넷 연결, Hugging Face 접속 가능 여부 |
