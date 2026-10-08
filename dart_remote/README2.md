# 공시 신호 워드클라우드 scoring 인수인계

KRX 섹터 대표기업의 정기공시 chunk 원문에서 키워드를 추출해 산업 신호 점수를 계산하는 기능입니다. 아래 명령은 로컬 프로젝트 루트 또는 배포의 deploy 디렉터리에서 해당 Python 실행환경을 활성화한 뒤 실행합니다.

## 전달 파일과 의존성

| 파일 | 역할 |
| --- | --- |
| `dart_signal_wordcloud.py` | DB chunk 조회, 후보 추출·필터링·점수 계산, Top N 출력 및 키워드 진단을 수행하는 실행 파일. 서비스의 읽기 전용 `dart_remote.db.rows` 연결 풀을 사용합니다. |
| `signal_keyword_rules.py` | 공통 필터·section 정책과 `SectorVocabulary`별 alias·복합어·기술어 규칙을 관리합니다. |
| `test_signal_sector_isolation.py` | 다른 섹터에 반도체 전용 규칙이 유입되지 않는지 확인하는 회귀 테스트입니다. 운영 실행에는 필수는 아니지만 함께 전달하는 것을 권장합니다. |

`dart_db_client.py`, `.env`, DB 접속 환경은 팀의 기존 파일과 설정을 사용합니다. 서비스에서는 `wordcloud.py`가 보고서·캐시·기업 화면을 연결하며, 어휘 규칙은 `signal_keyword_rules.py`를 사용합니다.

## 필요한 Python 패키지 설치

형태소 분석과 DB 연결에 필요한 주요 패키지입니다. 전체 의존성은 해당 실행 환경의 requirements.txt를 설치합니다. 표준 라이브러리와 자동 설치되는 하위 의존성은 제외했습니다.

| 코드의 import | pip 패키지 | 용도 | 설치 명령 |
| --- | --- | --- | --- |
| `pandas` | `pandas` | DB 조회 결과와 후보별 점수 표 처리 | `python -m pip install pandas` |
| `kiwipiepy` | `kiwipiepy` | Kiwi 형태소 분석을 통한 후보 추출 | `python -m pip install kiwipiepy` |
| `pymysql` | `pymysql` | 기존 DB 접속 모듈의 MySQL 연결 | `python -m pip install pymysql` |
| `dotenv` | `python-dotenv` | 기존 DB 접속 모듈의 `.env` 로딩 | `python -m pip install python-dotenv` |

미설치된 패키지를 한 번에 설치하려면 실행에 사용할 **같은 Python 환경**에서 다음을 실행합니다.

```powershell
python -m pip install -r requirements.txt
```

현재 코드는 `Kiwi(num_workers=1)`로 기본 모델을 사용합니다. `kiwipiepy`를 pip로 설치하면 모델 데이터 패키지 `kiwipiepy_model`이 의존성으로 자동 설치되므로, 별도의 모델·사전 다운로드나 초기화 명령은 필요하지 않습니다. [Kiwi 공식 설치 안내](https://github.com/bab2min/kiwipiepy/blob/main/README.md)

## 실행 전 확인

- `dart_signal_wordcloud.py`, `signal_keyword_rules.py`, 기존 `dart_db_client.py`가 같은 프로젝트에서 import 가능해야 합니다.
- 팀의 기존 `.env`와 DB 접속 설정을 사용하며, DB 연결과 필요한 공시 chunk 데이터가 준비돼 있어야 합니다. 이 문서에는 접속 정보나 비밀번호를 기재하지 않습니다.
- 기본 분석은 지수 비중 상위 5개 기업의 2023·2024·2025년 Q1/H1/Q3/FY 검색 가능 chunk를 대상으로 합니다. 분석 연도별 데이터가 없으면 실행할 수 없습니다.

## 실행

```powershell
# KRX_SEMI 기본 실행: 최종 후보 수와 final_signal_score 상위 12개 출력
python -m dart_remote.dart_signal_wordcloud KRX_SEMI

# 최종 표시 개수 변경
python -m dart_remote.dart_signal_wordcloud KRX_SEMI --top-n 15

# 점수 구성과 최신연도 기업별 chunk 수 확인
python -m dart_remote.dart_signal_wordcloud KRX_SEMI --keyword HBM
```

`--keyword`는 scoring 후보에 있는 **정규화된 키워드와 정확히 일치**해야 합니다. 후보에 없으면 오류가 납니다. 필요 시 실제 지원 옵션인 `--years 2023 2024 2025`, `--top-companies 5`도 지정할 수 있습니다.

## 현재 production 점수

각 연도의 `S연도`는 해당 키워드가 등장한 chunk 수를 그 연도 분석 대상 전체 chunk 수로 나눈 비율입니다. 같은 chunk 안의 반복 언급은 한 번만 셉니다. 최신연도 등장 chunk 수가 2개 이상이고, 최신연도 등장 기업 수가 2개 이상인 후보만 scoring합니다.

```text
CurrentRaw = S25
CurrentScore = 후보군 내 CurrentRaw의 percentile rank × 100
ChangeRaw = 0.4 × (S24 - S23) + 0.6 × (S25 - S24)
ChangeScore = 후보군 내 ChangeRaw의 percentile rank × 100
SpreadScore = company_count / 5 × 100    # 기본 Top 5 기업일 때

signal_score = 0.50 × CurrentScore + 0.30 × ChangeScore + 0.20 × SpreadScore
max_company_share = 최신연도 최다 언급 기업의 chunk 수 / 해당 키워드 최신연도 chunk 수
concentration_penalty = min(15, max(0, (max_company_share - 0.50) × 30))
generic_business_penalty = 2 if generic_business else 0
final_signal_score = signal_score - concentration_penalty - generic_business_penalty
```

최종 워드클라우드는 `final_signal_score` 내림차순 기본 Top 12를 사용합니다. 🔥는 별도 상승 신호(`change_score >= 90`이고 `change_raw > 0`)이며 점수 가산은 없습니다. `홍보·수식` 분류는 감점하지 않습니다. `--top-companies`를 바꾸면 SpreadScore의 분모도 실제 선정 기업 수로 바뀝니다.

## 새 섹터 추가

`signal_keyword_rules.py`에 새 `SectorVocabulary`를 정의하고, 같은 파일의 `SECTOR_VOCABULARIES`에 지수 코드와 함께 등록합니다. 필요한 경우 그 섹터의 alias, 복합어 패턴, 기술어 정규식, 단독 유지어, 제외 토큰 등을 해당 vocabulary 필드에 넣습니다. `SignalConfig(index_code)`가 등록된 vocabulary를 선택하므로 `dart_signal_wordcloud.py`의 scoring 본체는 수정하지 않습니다. 등록하지 않은 코드는 `GENERIC_VOCABULARY`를 사용합니다.

현재 section 선택 정책은 공통으로 고정돼 있습니다. 다른 섹터의 실제 DB section 구성이 다르면 적용 전에 corpus 포함 범위를 검증하고, 정책 변경이 필요할 수 있습니다.

## 테스트

```powershell
python -m unittest -v dart_remote.test_signal_sector_isolation
```

이 테스트는 dummy 섹터에 반도체 alias·기술어 정규식·제외 토큰이 자동 적용되지 않고, 섹터별 vocabulary 주입이 유지되는지 확인합니다. `dart_signal_wordcloud.py`를 import하므로 기존 DB 모듈과 위 패키지는 import 가능해야 하지만, 테스트 자체는 실제 DB 조회를 하지 않습니다.

## 문제 해결

| 증상 | 확인할 점 |
| --- | --- |
| `ModuleNotFoundError: kiwipiepy` | 실행 중인 Python에 `python -m pip install kiwipiepy`로 설치했는지 확인합니다. |
| `ModuleNotFoundError: signal_keyword_rules` | 전달받은 파일이 실행 프로젝트에서 import 가능한 위치에 있는지 확인합니다. |
| `ModuleNotFoundError: dart_db_client` | 팀의 기존 DB 접속 모듈 위치와 실행 디렉터리를 확인합니다. |
| DB 접속 또는 조회 오류 | 기존 `.env`, DB 접근 권한, 지수 구성기업과 분석 연도의 검색 가능 chunk 존재 여부를 확인합니다. |
| 새 섹터 규칙이 적용되지 않음 | `signal_keyword_rules.py`의 `SECTOR_VOCABULARIES`에 정확한 지수 코드가 등록됐는지 확인합니다. |


## 현재 서비스 통합 사용법 (2026-10-07)

서비스 패키지에서는 상대 import를 사용하며 DB 조회는 기존 읽기 전용 연결 풀을 사용합니다. 진단 명령은 루트에서 `python -m dart_remote.dart_signal_wordcloud KRX_SEMI`, 분리 테스트는 `python -m unittest dart_remote.test_signal_sector_isolation`입니다. 본문 명령도 현재 패키지 실행 방식으로 갱신했습니다.

로컬과 배포는 `wordcloud.apply`를 통해 같은 점수 계산·Top 12 선정·표시 가중치를 사용합니다. `display_weight`는 Top N 선정 뒤 점수 차이의 제곱 항 70%와 순위 항 30%를 반영해 30-100으로 계산합니다. 웹에서는 재정규화하거나 count/importance로 대체하지 않습니다. 기본 글자 크기는 (display_weight/100)^1.15 × min(70, 화면 폭×0.15)로 계산합니다. 크기 차이를 조금 더 강조하기 위한 1.15제곱 변환이며 점수 순서는 유지하지만 엄밀한 정비례는 아닙니다. 긴 단어의 폭과 공간 부족은 모든 단어에 동일한 배율을 적용해 처리합니다. 워드 클라우드 높이는 왼쪽 지수/주가 그래프와 같고, 영역을 늘리지 않습니다. 🔥는 단어 중앙 뒤에 글자 크기의 1.15배로 표시하며 이모티콘에만 opacity=0.5를 적용합니다. 상승 표시는 is_hot=true인 경우에만 표시합니다.

기업 화면의 기존 지원을 유지하기 위해 SignalConfig에 company_scope와 min_latest_companies를 추가했습니다. 산업 기본 규칙은 그대로 기업 2개 이상·집중 감점 적용이고, 기업별 화면만 기업 1개·집중 감점 없음으로 계산합니다. 산업 점수로 기업 점수를 대신하지 않습니다. 원본의 섹터별 vocabulary 격리와 회귀 테스트도 유지합니다.

DB 데이터 버전·규칙 파일·기업 범위별 캐시를 저장하여 웹 방문마다 형태소 분석을 반복하지 않습니다. 캐시가 처음 만들어지는 경우에는 수만 개 청크를 분석하므로 최초 조회가 느릴 수 있습니다. 배포 전 수동 build로 준비하는 것이 좋습니다. Gemini 프롬프트는 변경하지 않았으며 새로 선정된 키워드의 설명은 --llm/--refresh-llm 생성 때만 갱신합니다. 재무·공시 검색 및 그래프 기능은 별개로 유지합니다.
