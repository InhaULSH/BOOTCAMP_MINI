"""Read-only MySQL BGE-M3 snapshots, local exact cosine search.

The same implementation runs on Windows (NumPy) and Ubuntu (FAISS).
No lexical prefilter, upstream mutation, embedding API or remote search server.
"""
import hashlib
import json
import os
import platform
import re
from zipfile import BadZipFile
import tempfile
import time
from pathlib import Path
from threading import RLock
import numpy as np
from . import db

MODEL = 'BAAI/bge-m3'
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
DIM = 1024
_lock = RLock()
_model_lock = RLock()
_snapshot = None
_model = None
_verified = None
_queries = {}
_integrity = None

def backend():
    value = os.getenv('SEARCH_BACKEND', 'numpy' if platform.system() == 'Windows' else 'faiss')
    if value not in ('numpy', 'faiss', 'keyword'):
        raise ValueError('SEARCH_BACKEND는 numpy/faiss/keyword 중 하나입니다.')
    return value

def contract():
    versions = db.rows('SELECT * FROM data_versions WHERE is_current=1')
    if len(versions) != 1 or not versions[0]['validated']:
        raise RuntimeError('동기화 검증이 완료된 현재 데이터 버전이 필요합니다.')
    version = versions[0]
    metas = db.rows('SELECT * FROM embedding_metadata WHERE is_current=1 AND index_version=:i', {'i': version['index_version']})
    if len(metas) != 1:
        raise RuntimeError('현재 임베딩 메타데이터가 정확히 하나여야 합니다.')
    meta = metas[0]
    if (meta['model_name'], meta['model_revision'], meta['embedding_dimension']) != (MODEL, REVISION, DIM) or not meta['normalize_embeddings']:
        raise ValueError('저장 벡터와 질문 임베딩의 모델·리비전·차원·정규화 계약이 다릅니다.')
    if meta['searchable_vector_count'] != meta['faiss_ntotal']:
        raise ValueError('메타데이터의 검색 청크·벡터 개수가 다릅니다.')
    global _integrity
    signature = (os.getenv('MYSQL_HOST'), os.getenv('MYSQL_DATABASE'), os.getenv('CLOUD_SQL_INSTANCE'), version['data_version'], version['index_version'], meta['faiss_sha256'], meta['searchable_vector_count'])
    # Version/validated state are read every time; full join integrity is checked
    # at most every 30 seconds, and immediately for any new snapshot contract.
    now = time.monotonic()
    if _integrity is None or _integrity[0] != signature or now - _integrity[1] >= 30:
        _check_integrity(version, meta)
        _integrity = (signature, now)
    source = {k: os.getenv(k, '') for k in ('MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_DATABASE', 'CLOUD_SQL_INSTANCE')}
    key = dict(source=source, data_version=version['data_version'], index_version=version['index_version'],
               model=MODEL, revision=REVISION, dimensions=DIM, count=meta['searchable_vector_count'],
               sqlite_sha=meta.get('sqlite_sha256'), faiss_sha=meta.get('faiss_sha256'), format=1)
    return key

def _check_integrity(version, meta):
    check = db.rows('''SELECT COUNT(*) n,COUNT(DISTINCT m.vector_id) unique_n,
        SUM(CASE WHEN e.chunk_id IS NULL OR e.is_active<>1 OR e.vector_id<>m.vector_id
          OR e.data_version<>m.data_version OR e.index_version<>m.index_version
          OR e.embedding_model<>m.embedding_model OR e.model_revision<>m.model_revision
          OR e.embedding_dimension<>m.embedding_dimension THEN 1 ELSE 0 END) bad
        FROM chunk_metadata m LEFT JOIN chunk_embeddings e ON e.chunk_id=m.chunk_id
        WHERE m.is_active=1 AND m.is_searchable=1 AND m.data_version=:v AND m.index_version=:i''',
        {'v': version['data_version'], 'i': version['index_version']})[0]
    if check['n'] != meta['searchable_vector_count'] or check['unique_n'] != check['n'] or check['bad']:
        raise ValueError('현재 청크·벡터 개수·ID·버전이 일치하지 않습니다. 동기화 완료 후 다시 실행하세요.')

def validate(meta, matrix, key):
    if matrix.shape != (key['count'], DIM) or len(meta) != key['count']:
        raise ValueError('벡터 개수·차원과 메타데이터가 다릅니다.')
    if len({r['chunk_id'] for r in meta}) != len(meta) or len({r['vector_id'] for r in meta}) != len(meta):
        raise ValueError('청크 ID 또는 벡터 ID가 중복됩니다.')
    if not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=2e-3):
        raise ValueError('벡터에 비정상 값이 있거나 정규화되지 않았습니다.')
    for r in meta:
        if (r['data_version'], r['index_version'], r['embedding_model'], r['model_revision'], r['embedding_dimension']) != (key['data_version'], key['index_version'], MODEL, REVISION, DIM):
            raise ValueError('청크와 벡터의 데이터 버전·모델 계약이 다릅니다.')

def snapshot(key):
    global _snapshot
    with _lock:
        if _snapshot is not None and _snapshot[0] == key:
            return _snapshot[1:]
        digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
        directory = Path(os.getenv('DART_CACHE_DIR', str(Path(__file__).resolve().parents[1] / '.dart_cache')))
        path = directory / (digest + '.npz')
        meta = matrix = None
        if path.exists():
            try:
                with np.load(path, allow_pickle=False) as cached:
                    meta = json.loads(str(cached['metadata'].item()))
                    matrix = cached['matrix']
                    expected = str(cached['sha256'].item())
                if hashlib.sha256(matrix.tobytes() + json.dumps(meta, sort_keys=True).encode()).hexdigest() != expected:
                    raise ValueError('벡터 캐시 무결성 오류')
                validate(meta, matrix, key)
            except (ValueError, KeyError, OSError, EOFError, BadZipFile):
                meta = matrix = None  # Never use a corrupt/partial cache.
        if matrix is None:
            params = {'v': key['data_version'], 'i': key['index_version']}
            count = db.rows('SELECT COUNT(*) n FROM chunk_metadata WHERE is_active=1 AND is_searchable=1 AND data_version=:v AND index_version=:i', params)[0]['n']
            if count != key['count']:
                raise ValueError('DB 청크 개수와 검증된 벡터 개수가 다릅니다. 동기화를 확인하세요.')
            meta, vectors, last = [], [], -1
            while True:
                page = db.rows('''SELECT m.chunk_id,m.vector_id,m.content_hash,m.data_version,m.index_version,
                    m.embedding_model,m.model_revision,m.embedding_dimension,e.embedding,
                    e.vector_id AS embedding_id,e.data_version AS embedding_version,e.index_version AS embedding_index,
                    e.embedding_model AS vector_model,e.model_revision AS vector_revision,e.embedding_dimension AS vector_dimension
                    FROM chunk_metadata m JOIN chunk_embeddings e ON e.chunk_id=m.chunk_id
                    WHERE m.is_active=1 AND m.is_searchable=1 AND e.is_active=1
                    AND m.data_version=:v AND m.index_version=:i AND m.vector_id>:last
                    ORDER BY m.vector_id LIMIT 2000''', dict(params, last=last))
                if not page: break
                for row in page:
                    blob = row.pop('embedding')
                    if (row.pop('embedding_id'), row.pop('embedding_version'), row.pop('embedding_index'),
                        row.pop('vector_model'), row.pop('vector_revision'), row.pop('vector_dimension')) != (row['vector_id'], key['data_version'], key['index_version'], MODEL, REVISION, DIM):
                        raise ValueError('청크·벡터 연결 또는 동기화 버전이 다릅니다.')
                    if len(blob) != DIM * 4: raise ValueError('벡터 BLOB 길이가 잘못되었습니다.')
                    vectors.append(np.frombuffer(blob, dtype='<f4').copy()); meta.append(row)
                last = page[-1]['vector_id']
                print(f'공시 벡터 준비: {len(meta):,}/{key["count"]:,}', flush=True)
            matrix = np.asarray(vectors, dtype=np.float32)
            validate(meta, matrix, key)
            if contract() != key: raise RuntimeError('벡터 다운로드 중 데이터가 바뀌었습니다. 다시 실행하세요.')
            directory.mkdir(parents=True, exist_ok=True)
            metadata = json.dumps(meta, sort_keys=True)
            fd, name = tempfile.mkstemp(suffix='.npz', dir=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    np.savez(stream, matrix=matrix, metadata=metadata,
                             sha256=hashlib.sha256(matrix.tobytes() + metadata.encode()).hexdigest())
                os.replace(name, path)
            finally:
                if os.path.exists(name): os.unlink(name)
        _snapshot = (key, meta, matrix)
        return meta, matrix

def model():
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL, revision=REVISION, device=os.getenv('BGE_M3_DEVICE', 'cpu'),
                                         cache_folder=os.getenv('BGE_M3_CACHE_DIR'), token=os.getenv('HF_TOKEN') or os.getenv('HUGGINGFACE_TOKEN'))
            _model.max_seq_length = 8192
            getter = getattr(_model, 'get_embedding_dimension', None) or _model.get_sentence_embedding_dimension
            if getter() != DIM: raise ValueError('질문 모델 출력 차원 오류')
        return _model

def encode(texts):
    with _model_lock:
        value = np.asarray(model().encode(texts, normalize_embeddings=True, show_progress_bar=False,
                                         batch_size=1), dtype=np.float32)
    if value.shape != (len(texts), DIM) or not np.isfinite(value).all() or not np.allclose(np.linalg.norm(value, axis=1), 1, atol=2e-3):
        raise ValueError('질문 임베딩 형식·정규화 오류')
    return value

def verify_model(key, meta, matrix):
    global _verified
    with _model_lock:
        if _verified == key: return
        chosen = meta[:min(5, len(meta))]
        if not chosen: raise ValueError('모델 일치를 검증할 공시 벡터가 없습니다.')
        params = {f'c{i}': r['chunk_id'] for i, r in enumerate(chosen)}
        rows = db.rows('SELECT chunk_id,section_name,subsection_name,chunk_text FROM chunk_metadata WHERE chunk_id IN (' + ','.join(':'+p for p in params) + ') AND is_active=1 AND data_version=:v', dict(params, v=key['data_version']))
        texts = {r['chunk_id']: ' '.join(p for p in (r['section_name'], r['subsection_name'], r['chunk_text']) if p) for r in rows}
        if len(texts) != len(chosen): raise ValueError('모델 검증 중 청크가 변경되었습니다.')
        mine = encode([texts[r['chunk_id']] for r in chosen])
        scores = np.sum(mine * matrix[:len(chosen)], axis=1)
        if np.any(scores < 0.999): raise ValueError('BGE-M3 재임베딩 검증 실패: 라이브러리·전처리·모델 버전을 확인하세요.')
        print(f'BGE-M3 모델 일치 검증 완료: 최소 유사도 {scores.min():.6f}', flush=True)
        _verified = dict(key)

def top_indices(matrix, query, top_k, method):
    matrix = np.ascontiguousarray(matrix, dtype=np.float32)
    if method == 'faiss':
        import faiss
        index = faiss.IndexFlatIP(DIM); index.add(matrix)
        scores, ids = index.search(query.reshape(1, DIM), min(top_k, len(matrix)))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
    scores = matrix @ query
    return [(int(i), float(scores[i])) for i in np.argsort(-scores, kind='stable')[:top_k]]

def rank(query, rows, top_k, index_version, method):
    key = contract()  # Outside caches: check the current version on every search.
    if key['index_version'] != index_version: raise RuntimeError('분석 시작 후 데이터 버전이 변경되었습니다. 분석을 다시 시작하세요.')
    if not rows: return [], method + '-bge-m3-cosine'
    meta, matrix = snapshot(key)
    positions = {r['chunk_id']: (i, r) for i, r in enumerate(meta)}
    indices = []
    for row in rows:
        found = positions.get(row['chunk_id'])
        if found is None or any(row[k] != found[1][k] for k in ('vector_id', 'data_version', 'index_version', 'content_hash', 'embedding_model', 'model_revision', 'embedding_dimension')):
            raise ValueError('검색 후보와 캐시의 청크·벡터·본문 버전이 다릅니다.')
        indices.append(found[0])
    verify_model(key, meta, matrix)
    text = query
    for name in {r['corp_name'] for r in rows}:
        text = text.replace(name, '')
    years = {r['year'] for r in rows}
    if len(years) == 1: text = text.replace(str(next(iter(years))), '')
    text = re.sub(r'\s+', ' ', text).strip()
    if not text: raise ValueError('질문이 비어 있습니다.')
    if len(text) > 8000: raise ValueError('검색 질문은 8,000자 이내로 입력하세요.')
    with _model_lock:
        if text not in _queries:
            if len(model().tokenizer(text, truncation=False)['input_ids']) > 8192:
                raise ValueError('질문이 BGE-M3의 8,192토큰 한도를 초과합니다. 질문을 줄이세요.')
            if len(_queries) >= 128: _queries.pop(next(iter(_queries)))
            _queries[text] = encode([text])[0]
        vector = _queries[text]
    selected = top_indices(matrix[indices], vector, top_k, method)
    if contract() != key: raise RuntimeError('검색 도중 데이터가 변경되었습니다. 다시 실행하세요.')
    return [(rows[i], score) for i, score in selected], method + '-bge-m3-cosine'

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('query', nargs='?', default='HBM 수요와 설비투자 확대 계획')
    parser.add_argument('--sector', default='반도체')
    parser.add_argument('--company'); parser.add_argument('--year', type=int)
    parser.add_argument('--report-type', choices=['FY','Q1','H1','Q3']); parser.add_argument('--top-k', type=int, default=5)
    args = parser.parse_args()
    from .repository import Repository
    hits, status = Repository(args.sector).search(args.query, args.company, args.year, args.report_type, args.top_k)
    print(json.dumps(dict(status=status, hits=hits), ensure_ascii=False, indent=2))
