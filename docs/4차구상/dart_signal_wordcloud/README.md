# DART 워드클라우드 production

산업 및 기업 공시에서 키워드를 추출·평가해 워드클라우드용 Top-N 결과를 만드는 production 모듈입니다. DB 연결과 공통 환경 설정은 프로젝트 루트의 `README.md`를 참고합니다.

## 프로젝트 구조

| 파일 | 역할 |
|---|---|
| `dart_signal_wordcloud.py` | KRX 섹터 대표기업 공시를 이용하는 산업 워드클라우드 scorer 및 CLI |
| `dart_company_signal_wordcloud.py` | 개별 기업 공시를 이용하는 기업 워드클라우드 scorer 및 CLI |
| `signal_keyword_rules.py` | 공통 후보 규칙과 섹터별 `SectorVocabulary` 설정 |

두 scorer는 프로젝트 루트의 `dart_db_client.query`를 사용합니다. 필요한 패키지는 루트 `requirements.txt`로 설치합니다. Kiwi는 `kiwipiepy` 패키지 설치만으로 동작하며 별도 모델 다운로드 명령은 필요하지 않습니다.

## 산업 워드클라우드

- 기본 표시 개수: Top12
- `CompanyCoverage = company_count / 분석 기업 수 × 100`
- `SpreadScore = 0.6 × CompanyCoverage + 0.4 × EntropyScore`
- `FinalScore = 0.50 × CurrentScore + 0.30 × ChangeScore + 0.20 × SpreadScore - concentration_penalty - generic_business_penalty`
- industry hot: 최종 Top12 중 `ChangeScore >= 90`이고 `ChangeRaw > 0`인 후보를 `ChangeRaw` 내림차순으로 정렬해 최대 3개만 표시합니다.

## 기업 워드클라우드

- 기본 표시 개수: Top12. 최종 후보가 12개 미만이면 존재하는 후보만 반환합니다.
- `DiversityRaw = 0.4 × C2 + 0.6 × C3`
- `support = min(1, context_count / 10)`
- `FinalScore = 0.50 × CurrentScore + 0.30 × ChangeScore + 0.20 × DiversityScore - generic_business_penalty`
- company hot: `ChangeScore >= 97.5`이고 `ChangeRaw > 0`인 후보입니다.

과거 전체 연도가 없는 상장·신규편입 기업은 missing을 0으로 만들지 않습니다. 실제 데이터가 있는 연속 연도 구간만 Change 계산에 사용합니다.

```yaml
2023: 없음
2024: 있음
2025: 있음
Change: 2024→2025만 사용
```

이는 특정 기업을 위한 예외가 아니라 구조적 결측연도에 적용하는 공통 규칙입니다.

## 실행 및 테스트

프로젝트 루트 `team_client/`에서 module 방식으로 실행합니다.

```powershell
# 산업 기본 Top12
python -m dart_signal_wordcloud.dart_signal_wordcloud KRX_SEMI

# 산업 표시 개수 및 특정 키워드 진단
python -m dart_signal_wordcloud.dart_signal_wordcloud KRX_SEMI --top-n 12 --keyword HBM

# 기업 기본 Top12
python -m dart_signal_wordcloud.dart_company_signal_wordcloud 00126380 --sector-index KRX_SEMI

# 워드클라우드 회귀 테스트
python -m unittest discover -s dart_signal_wordcloud -t . -p "test_*.py"
```

새 섹터는 `signal_keyword_rules.py`에 `SectorVocabulary`를 정의하고 `SECTOR_VOCABULARIES`에 지수 코드를 등록합니다. scoring entrypoint는 수정하지 않습니다.

## UI serializer

산업 Top-N은 `wordcloud_items(...)`, 기업 Top-N은 `company_wordcloud_items(...)`로 직렬화합니다.

```python
from dart_signal_wordcloud.dart_signal_wordcloud import wordcloud_items
from dart_signal_wordcloud.dart_company_signal_wordcloud import company_wordcloud_items

industry_payload = wordcloud_items(industry_top)

company_payload = company_wordcloud_items(
    company_top,
    disclosure_contexts=None,
    selection_reasons=None,
    source_urls=None,
)
```

UI keyword payload의 공통 필드는 다음과 같습니다.

| 필드 | JSON 타입 | 설명 |
|---|---|---|
| `keyword` | string | 표시 키워드 |
| `display_weight` | number | UI 글자 크기. 문자열이 아닌 JSON number로 전달합니다. |
| `is_hot` | boolean | 불꽃 표시 여부. JSON boolean으로 전달합니다. |
| `final_signal_score` | number | production 최종 점수 |
| `disclosureContext` | string 또는 null | popup 공시 문맥 |
| `selectionReason` | string 또는 null | popup 선정 이유 |
| `sourceUrl` | string 또는 null | DART 원문 URL |

기업 serializer는 결과에 `approval_reason`이 있으면 기본 `selectionReason`으로 사용할 수 있습니다. 사용자 친화적 설명, 공시 문맥, 원문 URL은 backend에서 enrichment하며, 제공하지 않으면 `null`이어도 됩니다. 산업 결과에도 backend가 같은 popup 필드명을 병합해 전달할 수 있습니다.

## Backend 연동

Frontend renderer는 `keyword`, `display_weight`, `is_hot`을 받아 산업 Top12와 기업 최대 Top12를 렌더링할 수 있습니다. Backend의 책임 범위는 다음과 같습니다.

```text
production Python 실행
→ 산업/기업 결과 생성
→ serializer 호출
→ JSON 또는 API 응답 생성
→ frontend 전달
```

현재 frontend가 `DART_BIG_IN_structure/data/project.json`을 읽는 경우 backend에서 해당 JSON을 생성하거나, frontend의 데이터 adapter를 API 호출 방식으로 연결하면 됩니다.

최종 JSON shape 예시:

```json
{
  "sectors": [
    {
      "id": "KRX_SEMI",
      "keywords": [
        {
          "keyword": "HBM",
          "display_weight": 100.0,
          "is_hot": true,
          "final_signal_score": 91.2,
          "disclosureContext": null,
          "selectionReason": null,
          "sourceUrl": null
        }
      ]
    }
  ],
  "companies": [
    {
      "id": "00126380",
      "keywords": [
        {
          "keyword": "QD-OLED",
          "display_weight": 87.5,
          "is_hot": false,
          "final_signal_score": 84.2,
          "disclosureContext": null,
          "selectionReason": null,
          "sourceUrl": null
        }
      ]
    }
  ]
}
```
