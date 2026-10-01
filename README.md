# DART BIG:IN — 통합 로컬 서비스

웹 화면, 분석 코드, DB와 원문, 로컬 모델을 모두 `BOOTCAMP_MINI` 안에서 사용합니다. 이전 `BOOTCAMP_MINI_PROTO` 폴더나 다른 프로젝트의 Python 환경은 필요하지 않습니다.

## 처음 실행하기

PowerShell에서 프로젝트 폴더로 이동합니다.

```powershell
cd C:\Users\LSH\Downloads\Code\BOOTCAMP_MINI
```

이 작업에서 Python 3.12 가상환경과 의존성을 `.venv`에 설치했습니다. 활성화 없이 다음처럼 실행할 수 있습니다.

```powershell
& .\.venv\Scripts\python.exe -X utf8 app.py --no-market-refresh
```

브라우저에서 `http://127.0.0.1:8501`을 엽니다. 저장된 AI 인사이트와 시세를 보여주며 분석을 재생성하지 않습니다. 실행 시 시세를 갱신하려면 `--no-market-refresh`를 생략합니다.

PyCharm에서도 프로젝트 인터프리터를 `.venv\Scripts\python.exe`로 선택합니다.

다른 PC에서 환경을 새로 만들 때:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

## 분석·검색·시세 갱신

Gemini로 인사이트를 재생성합니다. `.env`에 `GEMINI_API_KEY`와 사용할 `GEMINI_MODEL`을 설정합니다.

```powershell
$env:LLM_PROVIDER = "gemini"
& .\.venv\Scripts\python.exe -X utf8 -m snapdart.analyze --refresh-llm --sector 반도체
```

`--llm`은 동일 입력의 응답 캐시를 재사용합니다. `--refresh-llm`은 실제 생성 요청을 다시 보냅니다. AI 생성은 최신 선택 연도에만 수행합니다. 이전 연도에는 공시 발췌를 표시합니다.

API를 호출하지 않고 발췌 보고서를 만들 때:

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m snapdart.analyze --offline --sector 반도체
```

이 명령은 게시된 AI 보고서를 발췌 보고서로 교체합니다. 기존 분석을 유지하려면 앱만 실행하세요.

DB에서 질문과 관련된 근거를 조회합니다. `--llm`을 추가하면 조회 결과로 짧은 답변을 요청합니다.

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m snapdart.query --sector 반도체 --company SK하이닉스 --year 2025 --report-type FY --intent hybrid --question "HBM 수요와 투자 변화"
& .\.venv\Scripts\python.exe -X utf8 -m snapdart.market
```

시세와 최근 공시 목록 갱신은 DB 본문 수집이나 AI 재생성과 별도입니다. `.env`의 `KRX_API`는 KRX 지수 수집에 사용하며 관련 서비스 승인이 필요합니다. 개별 주가와 지수는 실행일 이전 최근 거래일의 종가를 사용합니다.

Ollama를 선택할 때:

```powershell
.\scripts\start_ollama.ps1
$env:LLM_PROVIDER = "ollama"
& .\.venv\Scripts\python.exe -X utf8 -m snapdart.analyze --llm --sector 반도체
```

Ollama 실행 파일과 Qwen 모델은 `.runtime`에 있습니다. `start_ollama.ps1 -Cpu`는 CPU 모드이며, 기본은 기존 Intel GPU 설정을 적용합니다.

## 폴더 구조와 처리 순서

```text
BOOTCAMP_MINI/
  app.py                   로컬 HTTP 서버
  snapdart/                실행 명령, 시세, LLM 전송, 화면 데이터
  snapdart_data/           섹터 탐색, SQL·벡터 검색, 프롬프트, 원문 처리
  web/                     HTML·CSS·JavaScript 화면
  data_new/
    sectors.json           섹터·기업 표시 순서와 검색어
    <섹터>/financial.db    표준화 재무 수치
    <섹터>/filings.db      공시 청크와 저장 벡터
    <섹터>/original/       원문 XML과 manifest
    service/               게시 보고서, 시세, LLM 캐시·진단
  data/krx_api/            KRX 날짜별 조회 캐시
  .runtime/                Ollama 실행 파일과 모델
  .venv/                   Python 3.12 환경
  docs/                    참고 문서와 작업 기록
    archive/               실행에 사용하지 않는 과거 문서·이미지·설정
  tests/                   현재 기능 검증
```

재무 DB에서 지표를 계산하고, 공시 DB에서 기업·연도·보고서 범위에 맞는 청크를 검색합니다. 관련 발췌와 재무자료를 LLM에 전달하고 결과를 검증해 게시 보고서에 저장합니다. 화면은 게시 보고서를 읽고, 각주를 누르면 DB 문단이나 원본 XML의 표를 조회합니다. 이미 저장된 벡터를 사용하며 실행 때 청킹·임베딩을 다시 하지는 않습니다.

## 프롬프트와 근거 표시

[프롬프트 정의서](data_new/프롬프트%20정의서.pdf)의 공통·산업·키워드 지시문을 사용합니다. 산업 인사이트는 2-3문장, 키워드 설명은 1-2문장입니다. Gemini의 temperature는 1이며 출력 예산은 각각 500·300토큰입니다. 정의서가 미정으로 둔 기업 전용 규칙은 기업 분석 목적을 사용하고 임의의 문장 수 상한을 두지 않습니다.

**문장마다 수치 근거 2개와 공시 근거 1개를 붙이는 규칙은 없습니다. 출처 개수의 하한·상한이나 종류별 할당도 없습니다.** 모델이 문장에 필요한 입력 근거만 선택하며, 자료 부족 설명에는 출처를 억지로 붙이지 않을 수 있습니다. 입력에 없는 ID는 거절하고 중복 각주는 제거합니다. 공시가 없더라도 재무자료가 있다면 근거의 한계를 설명할 수 있습니다.

기존 문장별 각주 기능 때문에 반환 JSON은 `sentences[{text, refs}]`를 사용합니다. 정의서의 단일 `industry_insight` 문자열을 문장과 출처 메타데이터로 나눈 전송 구조이며 별도의 분석 조건을 추가한 것은 아닙니다. 근거 금액과 부호를 확인하지만 문장의 의미 전체를 자동으로 입증하지는 않습니다.

더 자세한 데이터 연결·검색·현재 한계는 [SERVICE_README.md](data_new/SERVICE_README.md)에 있습니다. 원본 정의서와 과거 작업 기록은 보존합니다.

## 검증

```powershell
& .\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_*.py"
node tests/test_ui.cjs
& .\.venv\Scripts\python.exe -B -X utf8 scripts/check_service.py
```

테스트는 실제 Gemini 요청을 보내지 않습니다. `.env`, DB·원문·모델은 Git에 포함하지 않습니다.
