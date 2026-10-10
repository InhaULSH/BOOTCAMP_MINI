-- Existing dart_big_in installations: additive KRX index grouping layer.
-- No company, financial, filing, chunk, embedding, or FAISS data is changed.
SET NAMES utf8mb4;
START TRANSACTION;

CREATE TABLE IF NOT EXISTS krx_indices (
  index_code          VARCHAR(30)  NOT NULL,
  official_index_code VARCHAR(30)  NULL,
  index_name          VARCHAR(100) NOT NULL,
  display_name        VARCHAR(50)  NOT NULL,
  source_as_of        DATE         NULL,
  source_url          VARCHAR(500) NULL,
  is_active           TINYINT(1)   NOT NULL DEFAULT 1,
  created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (index_code),
  UNIQUE KEY uk_krx_official_code (official_index_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS krx_index_constituents (
  index_code       VARCHAR(30) NOT NULL,
  corp_code        CHAR(8)     NOT NULL,
  effective_from   DATE        NOT NULL,
  effective_to     DATE        NULL,
  source_as_of     DATE        NOT NULL,
  weight           DECIMAL(16,10) NULL,
  is_current       TINYINT(1)  NOT NULL DEFAULT 1,
  created_at       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (index_code, corp_code, effective_from),
  KEY ix_krx_constituents_index_current (index_code, is_current),
  KEY ix_krx_constituents_corp_current (corp_code, is_current),
  CONSTRAINT fk_krx_constituent_index FOREIGN KEY (index_code) REFERENCES krx_indices(index_code),
  CONSTRAINT fk_krx_constituent_company FOREIGN KEY (corp_code) REFERENCES companies(corp_code),
  CONSTRAINT ck_krx_constituent_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO krx_indices (index_code, index_name, display_name) VALUES
  ('KRX_SEMI', 'KRX 반도체', '반도체'),
  ('KRX_BANK', 'KRX 은행', '은행'),
  ('KRX_AUTO', 'KRX 자동차', '자동차'),
  ('KRX_HEALTH', 'KRX 헬스케어', '헬스케어')
AS new ON DUPLICATE KEY UPDATE
  index_name=new.index_name,
  display_name=new.display_name;

COMMIT;
