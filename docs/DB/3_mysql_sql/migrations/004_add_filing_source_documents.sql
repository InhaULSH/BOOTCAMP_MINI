-- Preserve tag-complete DART source XML and map every operational chunk to one source document.
-- Additive/idempotent migration: existing chunk_metadata rows and text columns are not modified.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS filing_source_documents (
  document_id       CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  rcept_no          CHAR(14)     NOT NULL,
  document_sequence SMALLINT UNSIGNED NOT NULL,
  source_path       VARCHAR(500) NOT NULL,
  file_name         VARCHAR(255) NOT NULL,
  mime_type         VARCHAR(100) NOT NULL DEFAULT 'application/xml',
  detected_encoding VARCHAR(40)  NULL,
  byte_size         BIGINT UNSIGNED NOT NULL,
  sha256            CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  raw_xml           LONGBLOB     NOT NULL,
  data_version      VARCHAR(50)  NOT NULL,
  is_active         TINYINT(1)   NOT NULL DEFAULT 1,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (document_id),
  UNIQUE KEY uk_source_document_path (rcept_no, source_path),
  UNIQUE KEY uk_source_document_sequence (rcept_no, document_sequence),
  KEY ix_source_document_receipt (rcept_no, is_active),
  KEY ix_source_document_sha256 (sha256),
  CONSTRAINT fk_source_document_filing
    FOREIGN KEY (rcept_no) REFERENCES filings (rcept_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chunk_source_documents (
  chunk_id       VARCHAR(100) NOT NULL,
  document_id    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  mapping_method VARCHAR(30)  NOT NULL DEFAULT 'source_path_exact',
  data_version   VARCHAR(50)  NOT NULL,
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (chunk_id),
  KEY ix_chunk_source_document (document_id),
  CONSTRAINT fk_chunk_source_chunk
    FOREIGN KEY (chunk_id) REFERENCES chunk_metadata (chunk_id),
  CONSTRAINT fk_chunk_source_document
    FOREIGN KEY (document_id) REFERENCES filing_source_documents (document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
