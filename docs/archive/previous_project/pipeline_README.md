> 과거 프로젝트 문서입니다. 여기의 이전 경로·설치·실행 명령은 역사적 기록이며 현재 실행 방법은 [통합 README](../../../README.md)를 사용합니다.

# 현재 서비스 연결

BOOTCAMP_MINI_PROTO의 현재 서비스는 `data_new/<섹터>/financial.db`와 `filings.db`를 사용합니다. 재무 조회·계산과 공시 검색은 `snapdart_data`에서 분리해 처리하며, 기존 `data`와 Qdrant는 이 서비스의 실행 경로에서 사용하지 않습니다. 자세한 데이터 구조, 검색 방식과 실행 방법은 [새 서비스 파이프라인 안내](data_new/SERVICE_README.md)를 참고하세요.

아래는 폐기한 XML 전처리·BGE-M3 파이프라인의 과거 기록입니다. 관련 코드·원본·가공·임베딩 자료는 삭제했으며, 문서와 이미지 등은 보존했습니다. 아래의 과거 실행 명령은 더 이상 지원하지 않습니다. 현재 실행 방법은 위의 서비스 안내를 따르세요.

# 공시 원문 → 구조화 자료 + BGE-M3 검색 자료

삼성전자·SK하이닉스·한미반도체·주성엔지니어링·원익IPS의 2023-2025년 정기보고서 60건을 처리합니다. 본문 60개와 첨부 26개 XML을 모두 보존·검증합니다. 자연어와 혼합 문단은 임베딩하고 숫자 중심 표는 구조화 자료로 보존합니다. LLM 답변 생성, 금융 계정의 완전한 정규화는 아직 구현하지 않았습니다.

## 처리 흐름

```text
data/opendart 원본 ZIP (변경하지 않음)
  → 최소 XML 형식 보정 → 엄격한 파싱 → 문자 보존 검사
  → source: 문서·문단·표 전체 보관
     ├─ structured: 숫자 출현 CSV + 표 셀 좌표 CSV
     └─ retrieval: 설명 문단·혼합 문단·정성 표 행 선별
          → 문단/행별 최대 1,000글자, 겹침 0
          → 동일 임베딩 입력의 중복 계산 제거
          → BGE-M3 / Intel Arc 130V / PyTorch XPU
          → Qdrant qdrant_mini, 127.0.0.1:6333
```

## 데이터 폴더

`data/processed`가 실제 사용하는 결과입니다. 재생성 시에는 `data/processed_build`에서 검증·임베딩까지 마친 다음 교체합니다. 실패한 작업이 기존 결과를 덮어쓰지 않습니다.

| 위치 | 저장 내용 |
|---|---|
| `source/documents.json` | 기업·사업연도·보고기간·접수번호·ZIP/XML 위치·원본 SHA256·검사 결과 |
| `source/documents/{document_id}.txt` | 태그를 제거한 문서 전체 내용 |
| `source/blocks/{document_id}.jsonl` | 제목·문단·표 셀 전체 원문과 블록 ID·순서·XML 경로. 검색에서 제외된 내용도 보존 |
| `source/tables/{document_id}.jsonl` | 표별 행·셀·병합·좌표·상위 행에서 이어지는 항목명 |
| `structured/numbers.csv` | 숫자 출현, 단위 후보, 주변 문맥, 기업·보고서·문단·표 ID·문자 위치 |
| `structured/table_cells.csv` | 셀의 원문 값과 행·열 좌표, 병합 정보, 행 항목·헤더 후보 |
| `retrieval/units.jsonl` | 검색 대상으로 선별된 문단·표 행과 원문 블록 ID |
| `retrieval/chunks.jsonl` | 1,000글자 이하 청크, 순서·위치·앞뒤 청크 ID, 임베딩 입력과 해시 |
| `retrieval/embedding_inputs.jsonl` | 중복 제거한 임베딩 입력. 출처별 청크는 별도로 유지 |
| `embeddings/vectors.npy` | 중복 제거된 입력의 1,024차원 float32 벡터 행렬 |
| `embeddings/vector_index.jsonl` | 내용 해시와 벡터 행 번호의 연결 |
| `embeddings/progress.json` | 임베딩·Qdrant 업로드 재개 지점 |
| `embeddings/manifest.json` | 모델 파일 해시·실행 장치·버전·토큰 길이·Qdrant 컬렉션·완료 여부 |
| `audit/` | 보정 XML·변경 기록·블록별 선별 사유·통계·검증 결과 |
| `examples.json` | 실제 자연어·혼합 문단·정성 표 행·수치 예시 |

Qdrant 검색 결과의 `paragraph_ids`와 `document_id`로 `source/blocks`의 원문을 찾습니다. 표는 `table_id`와 `row_index`로 원래 행·열 관계를 확인합니다. 숫자는 같은 문단 ID로 CSV에 연결됩니다. 매 검색마다 CSV를 순회하는 정량 검색기는 아직 구현하지 않았습니다.

## 선별·청킹·임베딩 기준

- 자연어와 수치가 섞인 설명은 원문 그대로 포함합니다. 숫자 포함 여부만으로 제외하지 않습니다.
- 제목만 있는 블록과 매우 짧은 단편은 임베딩하지 않고 원문에 보존합니다. 제목은 검색 청크의 문맥 정보로 사용합니다.
- 숫자 위주의 재무 표 행은 구조화 자료만 저장합니다. 그 숫자를 추측해서 설명문을 생성하지 않습니다.
- 표 안의 설명 문장 또는 정성 정보가 풍부한 행은 셀 순서·이어지는 행 항목을 유지하여 ` | `로 연결합니다. LLM이 새로 요약한 문장이 아닙니다.
- 선별은 글자 수와 설명 표현을 이용한 규칙입니다. 정확도가 검증된 분류 모델은 아닙니다. 문단별 분류는 `audit/routing.jsonl`, 제외된 원문은 `source`에서 확인합니다.
- 일반 문단을 서로 합치지 않습니다. 표는 개별 숫자 셀 대신 행을 검색 단위로 사용합니다. 각 단위를 최대 1,000글자로 나누며 겹침은 0입니다. 기존 고정 글자 수 분할을 유지하므로 문장 중간에서 잘릴 수 있습니다.
- 임베딩 입력에는 구간 제목(최대 120글자)·소제목(최대 160글자)과 청크 원문을 넣습니다. 기업·기간은 필터 메타데이터입니다. 원문 본문이 겹치지는 않지만 제목은 각 입력에 반복됩니다.
- BGE-M3 dense 벡터만 사용합니다. CLS pooling, 1,024차원, L2 정규화, 코사인 유사도입니다. sparse/ColBERT, BM25, reranker는 구현하지 않았습니다.
- 추론은 Intel XPU FP16, 저장은 float32입니다. 배치 기본 16이며 GPU 메모리 부족 시 절반으로 줄입니다.
- 토큰 수를 미리 계산해 8,192토큰 초과 입력은 중단합니다. 조용히 잘라 넣지 않습니다. 글자 수와 토큰 수는 다릅니다.
- 동일 제목·본문 입력은 한 번만 임베딩합니다. 출처별 Qdrant 포인트는 유지하여 반복 공시도 기업·기간 필터로 구분됩니다.

## 안전한 추출과 수치 해석의 범위

원본 ZIP은 수정하지 않습니다. 정상적인 문자 참조·주석·CDATA를 구분한 뒤 잘못 쓰인 `&`와 확인된 `<ACI 세미나>` 같은 문자 표현만 보정합니다. DTD는 허용하지 않습니다. 엄격한 XML 파싱 및 독립적인 문자 추출과 대조하여 공백을 제외한 전체 문자 순서가 일치해야 합니다. 검증 실패 시 빌드를 중단하며 공개 데이터로 교체하지 않습니다.

수치 CSV는 **숫자 출현 목록**입니다. `year`는 보고서 사업연도이며 해당 숫자의 실제 귀속 연도가 아닐 수 있습니다. 기간·연결/별도·계정명·단위의 의미를 자동 확정하지 않습니다. 표의 헤더는 `header_candidates`로 표시하며 확정된 열 제목으로 취급하지 않습니다. 숫자 계산용 API/XBRL 계정 매핑은 별도 단계입니다. 기존 `data/opendart/*/financial_*.json`은 보조 원본으로 그대로 남습니다.

이미지 참조는 기록하지만 OCR하지 않습니다. 이미 설치된 BGE-M3를 사용하며 모델을 학습하지 않습니다. 외부 LLM API나 Gemini에 공시를 전송하지 않습니다.

## 실행 방법

확인된 실행 환경은 `../BOOTCAMP/.venv/Scripts/python.exe`이며 모델은 `../BOOTCAMP/Models/bge-m3`에 있습니다. 기존 환경과 모델을 재사용하며 수정하지 않습니다. Qdrant는 사용자가 실행한 `qdrant_mini`를 사용합니다.

```powershell
cd C:\Users\LSH\Downloads\Code\BOOTCAMP_MINI
$embeddingPython = (Resolve-Path ..\BOOTCAMP\.venv\Scripts\python.exe).Path

# 새 작업 폴더는 비어 있어야 합니다.
& $embeddingPython -X utf8 -m dart_pipeline.prepare
& $embeddingPython -X utf8 -m dart_pipeline.verify --data data/processed_build
& $embeddingPython -X utf8 -m dart_pipeline.embed --data data/processed_build --batch-size 16

# 위 단계들이 모두 성공했을 때만 실행합니다.
.\scripts\publish_data.ps1

# 원문 청크와 출처를 반환합니다. LLM 답변 생성은 하지 않습니다.
& $embeddingPython -X utf8 -m dart_pipeline.search "반도체 설비투자와 생산능력" --stock-code 005930 --period 2023-03 --top-k 3
```

중단되었다면 `prepare`를 다시 실행하지 말고 같은 `embed` 명령을 실행합니다. 저장된 지점부터 재개합니다. 모델이나 데이터가 달라지면 기존 캐시와 혼합하지 않고 중단합니다. 게시된 자료에서 임베딩 명령을 실행하려면 `--data data/processed`를 지정합니다.

Qdrant에는 데이터·모델 해시로 구분한 컬렉션을 생성합니다. 업로드 개수가 일치한 뒤 `snapdart_current` 별칭을 연결합니다. 다른 컬렉션·컨테이너·볼륨은 삭제하지 않습니다. `publish_data.ps1`은 검증된 작업 폴더를 최종 폴더로 교체하고 이전 가공 자료와 과거 `data/inspection`만 삭제합니다. `data/opendart`, 기존 KRX 자료, `.env`, `BOOTCAMP_MINI_PROTO`는 보존합니다.

검증 환경: Python 3.11.15, torch 2.14.1+xpu, sentence-transformers 5.7.0, transformers 4.57.6, qdrant-client 1.19.1. 전처리는 Python 3.12에서도 사용할 수 있는 문법으로 작성했습니다. 임베딩 의존성은 `requirements-embedding.txt`에 기록되어 있습니다.

공식 참고: [BGE-M3](https://huggingface.co/BAAI/bge-m3), [PyTorch Intel GPU](https://docs.pytorch.org/docs/main/notes/get_start_xpu.html), [Qdrant 포인트](https://qdrant.tech/documentation/manage-data/points/), [Qdrant 필터 인덱스](https://qdrant.tech/documentation/manage-data/indexing/).
