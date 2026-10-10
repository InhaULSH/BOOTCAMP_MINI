"""팀원용 공시 의미(유사도) 검색 — MySQL 벡터 + 내 PC의 BGE-M3 모델.

프로젝트 운영 검색(BGE-M3 Pure Dense)과 같은 방식으로 동작한다.
    1) 질문에서 기업명·연도 문자열을 지운다(프로젝트와 동일한 전처리)
    2) BGE-M3(고정 revision)로 질문을 1024차원 정규화 벡터로 바꾼다
    3) 기업·연도·보고서·접수번호로 후보 청크를 먼저 거른 뒤
    4) 정규화 벡터 내적(= 코사인 유사도)이 큰 순서로 Top-K를 돌려준다

준비 (팀원 PC, 최초 1회):
    pip install -r requirements.txt
    → 첫 검색 때 BGE-M3 모델(약 2.3GB)을 Hugging Face에서 내려받는다.
    → 첫 실행 때 MySQL에서 벡터(약 90MB)를 내려받아 .dart_cache/ 에 저장한다.
      데이터 버전이 바뀌면 자동으로 다시 받는다.

사용 예:
    from dart_semantic_search import semantic_search
    semantic_search("HBM 수요 전망", corp_name="SK하이닉스", year=2024, report_type="FY", top_k=5)

주의:
    - 모델 revision이 MySQL에 기록된 값과 다르면 실행을 멈춘다(다른 모델이면 점수가 의미 없음).
    - 점수는 같은 질문 안에서 순서를 정하는 용도다. "0.5 이상이면 정답" 같은 기준으로 쓰지 않는다.
    - 필터 없이 전체(약 2만 개)를 검색해도 되지만, 기업·연도를 주면 다른 회사 문단이 섞이지 않는다.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from dart_db_client import query

MODEL_NAME = "BAAI/bge-m3"
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
DIMENSIONS = 1024
CACHE_DIR = Path(os.getenv("DART_CACHE_DIR", ".dart_cache"))
PAGE_SIZE = 2000
META_COLUMNS = ["vector_id", "chunk_id", "corp_name", "corp_code", "year", "report_type", "rcept_no",
                "section_name", "subsection_name", "content_type"]


# ---------------------------------------------------------------------------
# 벡터 내려받기 (데이터 버전별 로컬 캐시)
# ---------------------------------------------------------------------------
def current_data_version() -> str:
    frame = query("SELECT data_version FROM data_versions WHERE is_current = 1")
    if len(frame) != 1:
        raise RuntimeError("MySQL 현재 데이터 버전을 확인할 수 없습니다. 데이터 담당자에게 문의하세요.")
    return str(frame.iloc[0]["data_version"])


def _check_model_contract() -> None:
    frame = query("SELECT DISTINCT embedding_model, model_revision, embedding_dimension "
                  "FROM chunk_embeddings WHERE is_active = 1")
    expected = (MODEL_NAME, MODEL_REVISION, DIMENSIONS)
    found = [tuple(row) for row in frame[["embedding_model", "model_revision", "embedding_dimension"]].itertuples(index=False)]
    if found != [expected]:
        raise RuntimeError(f"MySQL 벡터의 모델 정보 {found}가 이 코드의 {expected}와 다릅니다.")


def _download_embeddings() -> tuple[pd.DataFrame, np.ndarray]:
    _check_model_contract()
    metas: list[pd.DataFrame] = []
    vectors: list[np.ndarray] = []
    last_id = -1
    while True:
        page = query(
            "SELECT e.vector_id, e.embedding, m.chunk_id, m.corp_name, m.corp_code, m.year, m.report_type, "
            "m.rcept_no, m.section_name, m.subsection_name, m.content_type "
            "FROM chunk_embeddings e JOIN chunk_metadata m ON m.chunk_id = e.chunk_id "
            "WHERE e.is_active = 1 AND m.is_active = 1 AND m.is_searchable = 1 AND e.vector_id > %s "
            "ORDER BY e.vector_id LIMIT %s",
            [last_id, PAGE_SIZE],
        )
        if page.empty:
            break
        vectors.append(np.vstack([np.frombuffer(bytes(blob), dtype=np.float32) for blob in page["embedding"]]))
        metas.append(page[META_COLUMNS])
        last_id = int(page["vector_id"].iloc[-1])
        print(f"  벡터 내려받는 중… {sum(len(v) for v in vectors):,}개", flush=True)
    if not metas:
        raise RuntimeError("MySQL에 벡터가 없습니다.")
    meta = pd.concat(metas, ignore_index=True)
    matrix = np.vstack(vectors).astype(np.float32)
    if matrix.shape[1] != DIMENSIONS or not np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=2e-3):
        raise RuntimeError("내려받은 벡터의 차원 또는 정규화가 올바르지 않습니다.")
    return meta, matrix


@lru_cache(maxsize=1)
def load_embeddings(refresh: bool = False) -> tuple[pd.DataFrame, np.ndarray]:
    """(청크 메타데이터, 벡터 행렬[n, 1024]). vector_id 순서이며 두 값의 행 순서가 같다."""
    version = current_data_version()
    cache = CACHE_DIR / f"embeddings_{version}.npz"
    if cache.exists() and not refresh:
        data = np.load(cache, allow_pickle=False)
        meta = pd.DataFrame({column: data[column] for column in META_COLUMNS})
        meta["subsection_name"] = meta["subsection_name"].replace("", None)
        return meta, data["matrix"]
    print(f"MySQL에서 벡터를 내려받습니다(데이터 버전 {version}).")
    meta, matrix = _download_embeddings()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    arrays = {
        column: (meta[column].to_numpy(dtype=np.int64) if pd.api.types.is_numeric_dtype(meta[column])
                 else meta[column].fillna("").astype(str).to_numpy(dtype=str))
        for column in META_COLUMNS
    }
    np.savez(cache, matrix=matrix, **arrays)
    return meta, matrix


# ---------------------------------------------------------------------------
# 질문 임베딩
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_model(device: str | None = None):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=device)
    model.max_seq_length = 8192
    getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    if getter() != DIMENSIONS:
        raise RuntimeError("BGE-M3 출력 차원이 1024가 아닙니다.")
    return model


def effective_query(text: str, corp_name: str | None = None, year: int | None = None) -> str:
    """프로젝트 검색과 동일: 질문에서 기업명·연도 문자열을 지우고 공백을 정리한다."""
    if corp_name:
        text = text.replace(corp_name, "")
    if year:
        text = text.replace(str(year), "")
    return re.sub(r"\s+", " ", text).strip()


def verify_model(samples: int = 5, threshold: float = 0.999) -> pd.DataFrame:
    """내 PC의 모델이 MySQL 벡터를 만든 모델과 같은 결과를 내는지 확인한다.

    MySQL의 청크 몇 개를 프로젝트와 같은 방식(섹션명 + 하위섹션명 + 본문)으로 다시 임베딩해
    저장된 벡터와의 코사인 유사도가 threshold 이상이면 PASS. 처음 설치한 뒤 한 번 실행한다.
    """
    frame = query(
        "SELECT m.chunk_id, m.section_name, m.subsection_name, m.chunk_text, e.embedding "
        "FROM chunk_embeddings e JOIN chunk_metadata m ON m.chunk_id = e.chunk_id "
        "WHERE e.is_active = 1 AND m.is_active = 1 AND m.is_searchable = 1 "
        "ORDER BY e.vector_id LIMIT %s",
        [int(samples)],
    )
    texts = [" ".join(part for part in (row.section_name, row.subsection_name, row.chunk_text)
                      if isinstance(part, str) and part)
             for row in frame.itertuples()]
    mine = np.asarray(load_model().encode(texts, normalize_embeddings=True, show_progress_bar=False),
                      dtype=np.float32)
    stored = np.vstack([np.frombuffer(bytes(blob), dtype=np.float32) for blob in frame["embedding"]])
    similarity = (mine * stored).sum(axis=1)
    result = pd.DataFrame({"chunk_id": frame["chunk_id"], "cosine": similarity})
    status = "PASS" if (similarity >= threshold).all() else "FAIL"
    print(f"모델 일치 점검 {status}: 최소 코사인 {similarity.min():.6f} (기준 {threshold})")
    if status == "FAIL":
        print("  → 라이브러리 버전 차이 가능성. requirements.txt 버전으로 다시 설치한 뒤 데이터 담당자에게 알려 주세요.")
    return result


def embed_query(text: str) -> np.ndarray:
    vector = np.asarray(load_model().encode([text], normalize_embeddings=True, show_progress_bar=False),
                        dtype=np.float32)
    if vector.shape != (1, DIMENSIONS):
        raise RuntimeError(f"질문 벡터 차원 오류: {vector.shape}")
    return vector[0]


# ---------------------------------------------------------------------------
# 검색
# ---------------------------------------------------------------------------
def semantic_search(
    question: str,
    corp_name: str | None = None,
    corp_code: str | None = None,
    year: int | None = None,
    report_type: str | None = None,
    rcept_no: str | None = None,
    top_k: int = 5,
    with_text: bool = True,
) -> pd.DataFrame:
    """질문과 의미가 가까운 공시 문단 Top-K. score = 코사인 유사도(높을수록 비슷)."""
    if top_k <= 0:
        raise ValueError("top_k는 1 이상이어야 합니다.")
    meta, matrix = load_embeddings()
    mask = np.ones(len(meta), dtype=bool)
    for column, value in (("corp_name", corp_name), ("corp_code", corp_code), ("year", year),
                          ("report_type", report_type), ("rcept_no", rcept_no)):
        if value is not None:
            mask &= (meta[column].astype(str) == str(value)).to_numpy()
    if not mask.any():
        return pd.DataFrame(columns=["rank", "score"] + META_COLUMNS)

    candidates = meta[mask].reset_index(drop=True)
    scores = matrix[mask] @ embed_query(effective_query(question, corp_name, year))
    best = np.argsort(scores)[::-1][:top_k]
    result = candidates.iloc[best].reset_index(drop=True)
    result.insert(0, "score", scores[best].astype(float))
    result.insert(0, "rank", range(1, len(result) + 1))
    if with_text and not result.empty:
        texts = query("SELECT chunk_id, chunk_text FROM chunk_metadata WHERE chunk_id IN ("
                      + ", ".join(["%s"] * len(result)) + ")", list(result["chunk_id"]))
        result = result.merge(texts, on="chunk_id", how="left")
    return result


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 60)
    print(semantic_search("HBM 수요 전망", corp_name="SK하이닉스", year=2024, report_type="FY", top_k=5))
