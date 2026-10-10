-- DART 중앙 DB 스키마 (MySQL 8.4)
-- 근거: src/db/financial_db.py, src/db/capex_db.py, src/retrieval/bge_m3_indexer.py,
--       src/quality/account_mapping_quality.py, docs/handoff/MYSQL_CENTRALIZATION_PLAN.md
-- 원칙:
--   * SQLite 자동번호(period_id, fact_id, capex_id)는 가져오지 않고 자연키로 동기화한다.
--   * BGE-M3 embedding BLOB은 migration 002의 chunk_embeddings에 저장하며 FAISS 파일은 별도 보존한다.
--   * 금액은 BIGINT(원 단위), JSON 성격 컬럼은 원문 보존을 위해 TEXT로 둔다.
-- 이 파일은 컨테이너 최초 기동 시 MYSQL_DATABASE 안에서 실행된다.

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- 버전·동기화 관리
-- ---------------------------------------------------------------------------
CREATE TABLE data_versions (
  data_version            VARCHAR(50)  NOT NULL,
  description             VARCHAR(500) NULL,
  financial_sqlite_sha256 CHAR(64)     NULL,
  vector_sqlite_sha256    CHAR(64)     NULL,
  faiss_sha256            CHAR(64)     NULL,
  index_version           VARCHAR(50)  NULL,
  manifest_path           VARCHAR(500) NULL,
  manifest_sha256         CHAR(64)     NULL,
  validation_report_path  VARCHAR(500) NULL,
  validated               TINYINT(1)   NOT NULL DEFAULT 0,
  is_current              TINYINT(1)   NOT NULL DEFAULT 0,
  created_at              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (data_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sync_runs (
  sync_run_id      BIGINT       NOT NULL AUTO_INCREMENT,
  data_version     VARCHAR(50)  NOT NULL,
  table_name       VARCHAR(64)  NOT NULL,
  started_at       DATETIME     NOT NULL,
  finished_at      DATETIME     NULL,
  status           ENUM('running','success','failed','aborted') NOT NULL,
  rows_source      BIGINT       NULL,
  rows_inserted    BIGINT       NULL,
  rows_updated     BIGINT       NULL,
  rows_deactivated BIGINT       NULL,
  error_message    TEXT         NULL,
  PRIMARY KEY (sync_run_id),
  KEY ix_sync_runs_version (data_version, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 마스터
-- ---------------------------------------------------------------------------
CREATE TABLE companies (
  corp_code      CHAR(8)      NOT NULL,
  corp_name      VARCHAR(100) NOT NULL,
  stock_code     CHAR(6)      NULL,
  is_operational TINYINT(1)   NOT NULL DEFAULT 1,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (corp_code),
  UNIQUE KEY uk_companies_stock (stock_code),
  KEY ix_companies_name (corp_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- KRX 지수 연결 계층 (기업 원본 데이터는 복제하지 않음)
-- ---------------------------------------------------------------------------
CREATE TABLE krx_indices (
  index_code         VARCHAR(30)  NOT NULL,
  official_index_code VARCHAR(30) NULL,
  index_name         VARCHAR(100) NOT NULL,
  display_name       VARCHAR(50)  NOT NULL,
  source_as_of       DATE         NULL,
  source_url         VARCHAR(500) NULL,
  is_active          TINYINT(1)   NOT NULL DEFAULT 1,
  created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (index_code),
  UNIQUE KEY uk_krx_official_code (official_index_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE krx_index_constituents (
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

CREATE TABLE periods (
  year        SMALLINT    NOT NULL,
  report_type ENUM('Q1','H1','Q3','FY') NOT NULL,
  report_code CHAR(5)     NOT NULL,
  report_name VARCHAR(30) NOT NULL,
  PRIMARY KEY (year, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE filings (
  rcept_no         CHAR(14)     NOT NULL,
  corp_code        CHAR(8)      NOT NULL,
  year             SMALLINT     NOT NULL,
  report_type      ENUM('Q1','H1','Q3','FY') NOT NULL,
  rcept_dt         DATE         NULL,
  dart_report_name VARCHAR(200) NULL,
  is_amended       TINYINT(1)   NULL,
  data_version     VARCHAR(50)  NOT NULL,
  is_active        TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (rcept_no),
  UNIQUE KEY uk_filings_slot (corp_code, year, report_type),
  CONSTRAINT fk_filings_company FOREIGN KEY (corp_code) REFERENCES companies (corp_code),
  CONSTRAINT fk_filings_period  FOREIGN KEY (year, report_type) REFERENCES periods (year, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 계정 매핑
-- ---------------------------------------------------------------------------
CREATE TABLE standard_accounts (
  standard_account_nm VARCHAR(100) NOT NULL,
  category            VARCHAR(20)  NOT NULL,          -- income / balance / cashflow
  sj_divs             JSON         NOT NULL,
  account_ids         JSON         NOT NULL,
  aliases             JSON         NOT NULL,
  period_nature       ENUM('point_in_time','flow') NOT NULL,
  display_order       SMALLINT     NOT NULL,
  PRIMARY KEY (standard_account_nm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- data/mapping/account_mapping_core.csv
CREATE TABLE standard_account_mapping (
  mapping_id          BIGINT       NOT NULL AUTO_INCREMENT,
  standard_account_nm VARCHAR(100) NOT NULL,
  original_account_nm VARCHAR(255) NOT NULL,
  account_id          VARCHAR(255) NOT NULL DEFAULT '',
  sj_div              VARCHAR(5)   NOT NULL,
  fs_div              ENUM('CFS','OFS') NOT NULL,
  mapping_status      VARCHAR(30)  NOT NULL,
  mapping_confidence  VARCHAR(20)  NULL,
  review_required     TINYINT(1)   NOT NULL,
  review_note         VARCHAR(500) NULL,
  corp_names          TEXT         NULL,
  report_types        VARCHAR(50)  NULL,
  data_version        VARCHAR(50)  NOT NULL,
  PRIMARY KEY (mapping_id),
  UNIQUE KEY uk_std_mapping (standard_account_nm, account_id, original_account_nm, sj_div, fs_div),
  CONSTRAINT fk_std_mapping_account FOREIGN KEY (standard_account_nm)
    REFERENCES standard_accounts (standard_account_nm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- SQLite financial.db: account_mapping
CREATE TABLE account_mapping (
  account_key           VARCHAR(255) NOT NULL,
  sj_div                VARCHAR(5)   NOT NULL,
  account_id            VARCHAR(255) NULL,
  standard_account_name VARCHAR(255) NOT NULL,
  source_account_names  TEXT         NULL,
  company_count         INT          NULL,
  observation_count     INT          NULL,
  mapping_status        VARCHAR(30)  NOT NULL,
  data_version          VARCHAR(50)  NOT NULL,
  PRIMARY KEY (account_key, sj_div)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 금융업 전용 프로필·지표 계층은 일반산업 account_mapping을 변경하지 않는다.
CREATE TABLE company_financial_profiles (
  corp_code CHAR(8) NOT NULL, industry_profile VARCHAR(30) NOT NULL,
  preferred_fs_div ENUM('CFS','OFS') NOT NULL, fallback_fs_div ENUM('CFS','OFS') NULL,
  comparison_scope VARCHAR(50) NOT NULL, capex_applicable TINYINT(1) NOT NULL DEFAULT 0,
  valid_from DATE NOT NULL, valid_to DATE NULL,
  PRIMARY KEY(corp_code),
  CONSTRAINT fk_fin_profile_company FOREIGN KEY(corp_code) REFERENCES companies(corp_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE financial_collection_status (
  corp_code CHAR(8) NOT NULL, year SMALLINT NOT NULL,
  report_type ENUM('Q1','H1','Q3','FY') NOT NULL,
  requested_fs_div ENUM('CFS','OFS') NOT NULL, selected_fs_div ENUM('CFS','OFS') NULL,
  cfs_status VARCHAR(10) NOT NULL, ofs_status VARCHAR(10) NOT NULL,
  missing_reason VARCHAR(100) NULL, rcept_no CHAR(14) NULL,
  PRIMARY KEY(corp_code,year,report_type),
  CONSTRAINT fk_fin_collection_company FOREIGN KEY(corp_code) REFERENCES companies(corp_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE financial_metric_definitions (
  metric_code VARCHAR(60) NOT NULL, metric_name VARCHAR(100) NOT NULL,
  industry_profile VARCHAR(30) NOT NULL, statement_type VARCHAR(10) NULL,
  metric_type ENUM('DIRECT','DERIVED','RATIO') NOT NULL,
  period_nature ENUM('point_in_time','flow','ratio') NOT NULL,
  unit_type VARCHAR(20) NOT NULL, description VARCHAR(500) NULL,
  is_core TINYINT(1) NOT NULL, is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY(metric_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE financial_metric_mappings (
  mapping_id BIGINT NOT NULL AUTO_INCREMENT, metric_code VARCHAR(60) NOT NULL,
  industry_profile VARCHAR(30) NOT NULL, account_id VARCHAR(255) NOT NULL,
  normalized_account_name VARCHAR(255) NOT NULL DEFAULT '', sj_div VARCHAR(5) NOT NULL,
  fs_div VARCHAR(5) NOT NULL DEFAULT '*', applies_to_corp_code VARCHAR(8) NOT NULL DEFAULT '*',
  mapping_status VARCHAR(30) NOT NULL, mapping_confidence VARCHAR(20) NOT NULL,
  tag_class VARCHAR(40) NOT NULL, priority INT NOT NULL DEFAULT 100,
  valid_from DATE NULL, valid_to DATE NULL, review_note VARCHAR(500) NULL,
  PRIMARY KEY(mapping_id),
  UNIQUE KEY uk_fin_metric_mapping(metric_code,industry_profile,account_id(80),normalized_account_name(80),sj_div,fs_div,applies_to_corp_code),
  CONSTRAINT fk_fin_metric_mapping_definition FOREIGN KEY(metric_code) REFERENCES financial_metric_definitions(metric_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE financial_metric_values (
  metric_value_id BIGINT NOT NULL AUTO_INCREMENT, corp_code CHAR(8) NOT NULL,
  year SMALLINT NOT NULL, report_type ENUM('Q1','H1','Q3','FY') NOT NULL,
  metric_code VARCHAR(60) NOT NULL, value BIGINT NULL, unit VARCHAR(20) NULL,
  value_type VARCHAR(20) NOT NULL, fs_div ENUM('CFS','OFS') NOT NULL,
  scope VARCHAR(50) NOT NULL,
  source_kind ENUM('DIRECT','DERIVED','DOCUMENT_EXTRACTED') NOT NULL,
  source_type VARCHAR(40) NOT NULL, source_rcept_no CHAR(14) NULL,
  source_document_id CHAR(64) NULL, source_chunk_id VARCHAR(100) NULL,
  source_account_id VARCHAR(255) NULL, source_account_name VARCHAR(255) NULL,
  source_fact_key CHAR(64) NULL, calculation_method VARCHAR(500) NULL,
  source_values TEXT NULL, review_status VARCHAR(30) NOT NULL,
  PRIMARY KEY(metric_value_id),
  UNIQUE KEY uk_fin_metric_value(corp_code,year,report_type,metric_code,value_type,fs_div,scope,source_kind),
  KEY ix_fin_metric_values_lookup(corp_code,year,report_type,metric_code),
  CONSTRAINT fk_fin_metric_value_company FOREIGN KEY(corp_code) REFERENCES companies(corp_code),
  CONSTRAINT fk_fin_metric_value_definition FOREIGN KEY(metric_code) REFERENCES financial_metric_definitions(metric_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 재무 원장
-- ---------------------------------------------------------------------------
-- SQLite financial_facts JOIN periods. UNIQUE 의미는 SQLite와 동일하되
-- period_id → (year, report_type), ord(NULL 가능) → ord_key = COALESCE(ord, -1).
CREATE TABLE financial_facts (
  fact_id             BIGINT       NOT NULL AUTO_INCREMENT,
  corp_code           CHAR(8)      NOT NULL,
  year                SMALLINT     NOT NULL,
  report_type         ENUM('Q1','H1','Q3','FY') NOT NULL,
  rcept_no            CHAR(14)     NULL,
  fs_div              ENUM('CFS','OFS') NOT NULL,
  sj_div              VARCHAR(5)   NOT NULL,
  account_key         VARCHAR(255) NOT NULL,
  account_id          VARCHAR(255) NULL,
  original_account_nm VARCHAR(255) NOT NULL,
  standard_account_nm VARCHAR(255) NULL,
  ord                 INT          NULL,
  ord_key             INT          NOT NULL,
  period_type         VARCHAR(20)  NOT NULL,
  value_type          VARCHAR(20)  NOT NULL,
  period_start        DATE         NULL,
  period_end          DATE         NOT NULL,
  currency            VARCHAR(10)  NULL,
  source_value_field  VARCHAR(50)  NOT NULL,
  raw_value           VARCHAR(100) NULL,
  normalized_value    BIGINT       NULL,
  calculated_value    BIGINT       NULL,
  calculation_method  TEXT         NULL,
  source_values       TEXT         NULL,
  is_calculated       TINYINT(1)   NOT NULL,
  data_version        VARCHAR(50)  NOT NULL,
  is_active           TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (fact_id),
  UNIQUE KEY uk_fact (corp_code, year, report_type, fs_div, sj_div, account_key, ord_key, value_type, is_calculated),
  KEY ix_fact_lookup (corp_code, year, report_type, fs_div),
  KEY ix_fact_std (standard_account_nm),
  KEY ix_fact_account (account_key, sj_div),
  KEY ix_fact_rcept (rcept_no),
  CONSTRAINT fk_fact_company FOREIGN KEY (corp_code) REFERENCES companies (corp_code),
  CONSTRAINT fk_fact_period  FOREIGN KEY (year, report_type) REFERENCES periods (year, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- SQLite capex_facts JOIN periods (capex_id는 빌드마다 바뀌므로 가져오지 않음)
CREATE TABLE capex_facts (
  capex_fact_id        BIGINT       NOT NULL AUTO_INCREMENT,
  corp_code            CHAR(8)      NOT NULL,
  year                 SMALLINT     NOT NULL,
  report_type          ENUM('Q1','H1','Q3','FY') NOT NULL,
  fs_div               ENUM('CFS','OFS') NOT NULL,
  sj_div               VARCHAR(5)   NOT NULL DEFAULT 'CF',
  rcept_no             CHAR(14)     NULL,
  account_id           VARCHAR(255) NOT NULL,
  original_account_nm  VARCHAR(255) NOT NULL,
  standard_account_nm  VARCHAR(100) NOT NULL,
  period_type          VARCHAR(20)  NOT NULL,
  value_type           VARCHAR(20)  NOT NULL,
  period_start         DATE         NULL,
  period_end           DATE         NOT NULL,
  currency             VARCHAR(10)  NOT NULL,
  raw_value            VARCHAR(100) NULL,
  normalized_value     BIGINT       NULL,
  calculated_value     BIGINT       NULL,
  cash_outflow_amount  BIGINT       NOT NULL,
  sign_normalized      TINYINT(1)   NOT NULL,
  is_calculated        TINYINT(1)   NOT NULL,
  is_derived           TINYINT(1)   NOT NULL,
  value_source         ENUM('direct','derived') NOT NULL,
  capex_method         VARCHAR(30)  NOT NULL,
  calculation_method   TEXT         NOT NULL,
  source_account_ids   TEXT         NOT NULL,
  source_account_names TEXT         NOT NULL,
  source_values        TEXT         NOT NULL,
  source_account_count INT          NOT NULL,
  direct_account_found TINYINT(1)   NOT NULL,
  review_required      TINYINT(1)   NOT NULL,
  note                 TEXT         NULL,
  data_version         VARCHAR(50)  NOT NULL,
  is_active            TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (capex_fact_id),
  UNIQUE KEY uk_capex (corp_code, year, report_type, fs_div, value_type),
  KEY ix_capex_rcept (rcept_no),
  CONSTRAINT fk_capex_company FOREIGN KEY (corp_code) REFERENCES companies (corp_code),
  CONSTRAINT fk_capex_period  FOREIGN KEY (year, report_type) REFERENCES periods (year, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 공시 청크 메타데이터 (embedding BLOB 제외)
-- ---------------------------------------------------------------------------
CREATE TABLE embedding_metadata (
  index_version           VARCHAR(50)  NOT NULL,
  model_name              VARCHAR(100) NOT NULL,
  model_revision          CHAR(40)     NOT NULL,
  embedding_dimension     SMALLINT     NOT NULL,
  normalize_embeddings    TINYINT(1)   NOT NULL,
  faiss_index_type        VARCHAR(50)  NOT NULL,
  chunk_version           VARCHAR(50)  NOT NULL,
  faiss_path              VARCHAR(500) NOT NULL,
  faiss_sha256            CHAR(64)     NULL,
  sqlite_path             VARCHAR(500) NOT NULL,
  sqlite_sha256           CHAR(64)     NULL,
  searchable_vector_count INT          NULL,
  faiss_ntotal            INT          NULL,
  max_vector_id           BIGINT       NULL,
  built_at                DATETIME     NULL,
  is_current              TINYINT(1)   NOT NULL DEFAULT 0,
  PRIMARY KEY (index_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE chunk_metadata (
  chunk_id            VARCHAR(100) NOT NULL,
  vector_id           BIGINT       NOT NULL,
  corp_code           CHAR(8)      NOT NULL,
  corp_name           VARCHAR(100) NOT NULL,
  year                SMALLINT     NOT NULL,
  report_type         ENUM('Q1','H1','Q3','FY') NOT NULL,
  rcept_no            CHAR(14)     NOT NULL,
  section_name        VARCHAR(500) NOT NULL,
  subsection_name     VARCHAR(500) NULL,
  source_file         VARCHAR(500) NOT NULL,
  chunk_text          MEDIUMTEXT   NOT NULL,
  original_text       MEDIUMTEXT   NULL,
  content_hash        CHAR(64)     NOT NULL,
  chunk_version       VARCHAR(50)  NOT NULL,
  token_count         INT          NOT NULL,
  content_type        VARCHAR(30)  NOT NULL,
  search_priority     DOUBLE       NOT NULL,
  selection_reason    VARCHAR(200) NOT NULL,
  is_searchable       TINYINT(1)   NOT NULL,
  embedding_model     VARCHAR(100) NOT NULL,
  model_revision      CHAR(40)     NOT NULL,
  embedding_dimension SMALLINT     NOT NULL,
  embedded_at         DATETIME     NULL,
  index_version       VARCHAR(50)  NULL,
  data_version        VARCHAR(50)  NOT NULL,
  is_active           TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (chunk_id),
  UNIQUE KEY uk_chunk_vector (vector_id),
  KEY ix_chunk_filter (corp_code, year, report_type, rcept_no, is_searchable),
  KEY ix_chunk_rcept (rcept_no),
  CONSTRAINT fk_chunk_company FOREIGN KEY (corp_code) REFERENCES companies (corp_code),
  CONSTRAINT fk_chunk_period  FOREIGN KEY (year, report_type) REFERENCES periods (year, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 태그 보존 DART 원본 XML 및 청크→원본 문서 연결
-- ---------------------------------------------------------------------------
CREATE TABLE filing_source_documents (
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
  CONSTRAINT fk_source_document_filing FOREIGN KEY (rcept_no) REFERENCES filings (rcept_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE chunk_source_documents (
  chunk_id       VARCHAR(100) NOT NULL,
  document_id    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  mapping_method VARCHAR(30)  NOT NULL DEFAULT 'source_path_exact',
  data_version   VARCHAR(50)  NOT NULL,
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (chunk_id),
  KEY ix_chunk_source_document (document_id),
  CONSTRAINT fk_chunk_source_chunk FOREIGN KEY (chunk_id) REFERENCES chunk_metadata (chunk_id),
  CONSTRAINT fk_chunk_source_document FOREIGN KEY (document_id)
    REFERENCES filing_source_documents (document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 기업×연도×보고서 슬롯 coverage
-- ---------------------------------------------------------------------------
CREATE TABLE coverage (
  corp_code          CHAR(8)     NOT NULL,
  year               SMALLINT    NOT NULL,
  report_type        ENUM('Q1','H1','Q3','FY') NOT NULL,
  rcept_no           CHAR(14)    NULL,
  financial_rcept_no CHAR(14)    NULL,
  financial_exists   TINYINT(1)  NOT NULL DEFAULT 0,
  fs_div             VARCHAR(10) NULL,
  filing_exists      TINYINT(1)  NOT NULL DEFAULT 0,
  chunk_exists       TINYINT(1)  NOT NULL DEFAULT 0,
  embedding_exists   TINYINT(1)  NOT NULL DEFAULT 0,
  capex_status       ENUM('direct','derived','unresolved','not_applicable') NULL,
  status             ENUM('PASS','SOURCE_ABSENT','MISSING_OR_REVIEW') NOT NULL,
  reason             VARCHAR(500) NULL,
  data_version       VARCHAR(50) NOT NULL,
  PRIMARY KEY (corp_code, year, report_type),
  CONSTRAINT fk_cov_company FOREIGN KEY (corp_code) REFERENCES companies (corp_code),
  CONSTRAINT fk_cov_period  FOREIGN KEY (year, report_type) REFERENCES periods (year, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 백엔드용 조회 VIEW: 24개 표준계정 + CAPEX
-- value = calculated_value(계산값) 또는 normalized_value(직접값)
-- ---------------------------------------------------------------------------
-- 006: 공식 계정 ID + 표 구분으로 매칭, 슬롯당 1행 (infra/mysql/migrations/006_standardized_financials_by_tag.sql)
CREATE VIEW standardized_financials AS
WITH tags (standard_account_nm, account_id, statement_group, priority) AS (
            SELECT '매출액', 'ifrs-full_Revenue', 'IS', 1
  UNION ALL SELECT '매출원가', 'ifrs-full_CostOfSales', 'IS', 1
  UNION ALL SELECT '매출총이익', 'ifrs-full_GrossProfit', 'IS', 1
  UNION ALL SELECT '영업이익', 'dart_OperatingIncomeLoss', 'IS', 1
  UNION ALL SELECT '영업이익', 'ifrs-full_ProfitLossFromOperatingActivities', 'IS', 2
  UNION ALL SELECT '법인세비용차감전순이익', 'ifrs-full_ProfitLossBeforeTax', 'IS', 1
  UNION ALL SELECT '당기순이익', 'ifrs-full_ProfitLoss', 'IS', 1
  UNION ALL SELECT '자산총계', 'ifrs-full_Assets', 'BS', 1
  UNION ALL SELECT '부채총계', 'ifrs-full_Liabilities', 'BS', 1
  UNION ALL SELECT '자본총계', 'ifrs-full_Equity', 'BS', 1
  UNION ALL SELECT '유동자산', 'ifrs-full_CurrentAssets', 'BS', 1
  UNION ALL SELECT '유동부채', 'ifrs-full_CurrentLiabilities', 'BS', 1
  UNION ALL SELECT '이익잉여금', 'ifrs-full_RetainedEarnings', 'BS', 1
  UNION ALL SELECT '현금및현금성자산', 'ifrs-full_CashAndCashEquivalents', 'BS', 1
  UNION ALL SELECT '유형자산', 'ifrs-full_PropertyPlantAndEquipment', 'BS', 1
  UNION ALL SELECT '무형자산', 'ifrs-full_IntangibleAssetsOtherThanGoodwill', 'BS', 1
  UNION ALL SELECT '무형자산', 'ifrs-full_IntangibleAssetsAndGoodwill', 'BS', 2
  UNION ALL SELECT '재고자산', 'ifrs-full_Inventories', 'BS', 1
  UNION ALL SELECT '재고자산', 'ifrs-full_InventoriesTotal', 'BS', 2
  UNION ALL SELECT '매출채권', 'ifrs-full_CurrentTradeReceivables', 'BS', 1
  UNION ALL SELECT '매출채권', 'dart_ShortTermTradeReceivable', 'BS', 2
  UNION ALL SELECT '영업활동현금흐름', 'ifrs-full_CashFlowsFromUsedInOperatingActivities', 'CF', 1
  UNION ALL SELECT '투자활동현금흐름', 'ifrs-full_CashFlowsFromUsedInInvestingActivities', 'CF', 1
  UNION ALL SELECT '재무활동현금흐름', 'ifrs-full_CashFlowsFromUsedInFinancingActivities', 'CF', 1
  UNION ALL SELECT '무형자산취득', 'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities', 'CF', 1
  UNION ALL SELECT '감가상각비', 'ifrs-full_AdjustmentsForDepreciationExpense', 'CF', 1
  UNION ALL SELECT '감가상각비', 'dart_AdjustmentsForDepreciationExpense', 'CF', 2
),
candidates AS (
  SELECT f.*, t.standard_account_nm AS tag_standard_account, t.priority
  FROM financial_facts f
  JOIN tags t
    ON t.account_id = f.account_id
   AND t.statement_group = CASE WHEN f.sj_div IN ('IS', 'CIS') THEN 'IS' ELSE f.sj_div END
  WHERE f.is_active = 1
  UNION ALL
  -- Fallback for lines without an approved tag (company-specific codes): the
  -- stored label, only in the statement and period nature of the account.
  SELECT f.*, s.standard_account_nm, 9
  FROM financial_facts f
  JOIN standard_accounts s ON s.standard_account_nm = f.standard_account_nm
  WHERE f.is_active = 1 AND s.standard_account_nm <> '유형자산취득(CAPEX)'
    AND ((s.category = 'income' AND f.sj_div IN ('IS', 'CIS'))
      OR (s.category = 'balance' AND f.sj_div = 'BS' AND f.value_type = 'point_in_time')
      OR (s.category = 'cashflow' AND f.sj_div = 'CF'))
),
ranked AS (
  SELECT c.*,
         ROW_NUMBER() OVER (
           PARTITION BY c.corp_code, c.year, c.report_type, c.fs_div, c.tag_standard_account, c.value_type
           ORDER BY c.priority, CASE c.sj_div WHEN 'IS' THEN 0 WHEN 'CIS' THEN 1 ELSE 2 END,
                    c.is_calculated, c.ord_key
         ) AS pick
  FROM candidates c
)
SELECT c.corp_code, c.corp_name, r.year, r.report_type, r.rcept_no, r.fs_div, r.sj_div,
       r.tag_standard_account AS standard_account, r.account_id, r.original_account_nm,
       r.period_type, r.value_type, r.period_start, r.period_end,
       CASE WHEN r.is_calculated = 1 THEN r.calculated_value ELSE r.normalized_value END AS value,
       r.raw_value, r.is_calculated, 'reported' AS value_source,
       r.calculation_method, r.source_values, r.currency, r.data_version
FROM ranked r
JOIN companies c ON c.corp_code = r.corp_code
WHERE r.pick = 1
UNION ALL
SELECT c.corp_code, c.corp_name, x.year, x.report_type, x.rcept_no, x.fs_div, x.sj_div,
       x.standard_account_nm, x.account_id, x.original_account_nm,
       x.period_type, x.value_type, x.period_start, x.period_end,
       CASE WHEN x.is_calculated = 1 THEN x.calculated_value ELSE x.cash_outflow_amount END,
       x.raw_value, x.is_calculated, x.value_source,
       x.calculation_method, x.source_values, x.currency, x.data_version
FROM capex_facts x
JOIN companies c ON c.corp_code = x.corp_code
WHERE x.is_active = 1;
