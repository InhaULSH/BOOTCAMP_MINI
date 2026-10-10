-- 공시 청크 임베딩 벡터 테이블 (팀원이 MySQL에서 벡터를 내려받아 직접 유사도 계산할 수 있도록)
-- 원천: db/vector/filings_bge_m3.db filing_chunks.embedding (FAISS와 같은 vector_id)
-- 기존 테이블·데이터는 바꾸지 않는다. dart_etl 권한(CREATE)으로 적용 가능.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS chunk_embeddings (
  vector_id           BIGINT       NOT NULL,          -- FAISS ID와 동일
  chunk_id            VARCHAR(100) NOT NULL,
  embedding           BLOB         NOT NULL,          -- float32 little-endian × embedding_dimension (1024 → 4096 bytes), L2 정규화됨
  embedding_model     VARCHAR(100) NOT NULL,          -- BAAI/bge-m3
  model_revision      CHAR(40)     NOT NULL,
  embedding_dimension SMALLINT     NOT NULL,
  index_version       VARCHAR(50)  NULL,
  data_version        VARCHAR(50)  NOT NULL,
  is_active           TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (vector_id),
  UNIQUE KEY uk_embedding_chunk (chunk_id),
  CONSTRAINT fk_embedding_chunk FOREIGN KEY (chunk_id) REFERENCES chunk_metadata (chunk_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
