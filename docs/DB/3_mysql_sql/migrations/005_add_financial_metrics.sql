-- Finance-industry profiles, metric mappings, and auditable observations.
-- Additive only: existing general-industry facts and mappings are untouched.
SET NAMES utf8mb4;
START TRANSACTION;

INSERT INTO krx_indices(index_code,index_name,display_name,official_index_code,source_as_of,source_url,is_active)
VALUES ('KRX_BANK','KRX 은행','은행·금융지주',NULL,NULL,NULL,1)
AS new ON DUPLICATE KEY UPDATE
  index_name=new.index_name,display_name=new.display_name,is_active=1;

CREATE TABLE IF NOT EXISTS company_financial_profiles (
  corp_code           CHAR(8) NOT NULL,
  industry_profile    VARCHAR(30) NOT NULL,
  preferred_fs_div    ENUM('CFS','OFS') NOT NULL,
  fallback_fs_div     ENUM('CFS','OFS') NULL,
  comparison_scope    VARCHAR(50) NOT NULL,
  capex_applicable    TINYINT(1) NOT NULL DEFAULT 0,
  valid_from          DATE NOT NULL,
  valid_to            DATE NULL,
  PRIMARY KEY(corp_code),
  CONSTRAINT fk_fin_profile_company FOREIGN KEY(corp_code) REFERENCES companies(corp_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS financial_collection_status (
  corp_code           CHAR(8) NOT NULL,
  year                SMALLINT NOT NULL,
  report_type         ENUM('Q1','H1','Q3','FY') NOT NULL,
  requested_fs_div    ENUM('CFS','OFS') NOT NULL,
  selected_fs_div     ENUM('CFS','OFS') NULL,
  cfs_status          VARCHAR(10) NOT NULL,
  ofs_status          VARCHAR(10) NOT NULL,
  missing_reason      VARCHAR(100) NULL,
  rcept_no            CHAR(14) NULL,
  PRIMARY KEY(corp_code,year,report_type),
  CONSTRAINT fk_fin_collection_company FOREIGN KEY(corp_code) REFERENCES companies(corp_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS financial_metric_definitions (
  metric_code         VARCHAR(60) NOT NULL,
  metric_name         VARCHAR(100) NOT NULL,
  industry_profile    VARCHAR(30) NOT NULL,
  statement_type      VARCHAR(10) NULL,
  metric_type         ENUM('DIRECT','DERIVED','RATIO') NOT NULL,
  period_nature       ENUM('point_in_time','flow','ratio') NOT NULL,
  unit_type           VARCHAR(20) NOT NULL,
  description         VARCHAR(500) NULL,
  is_core             TINYINT(1) NOT NULL,
  is_active           TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY(metric_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS financial_metric_mappings (
  mapping_id             BIGINT NOT NULL AUTO_INCREMENT,
  metric_code            VARCHAR(60) NOT NULL,
  industry_profile       VARCHAR(30) NOT NULL,
  account_id             VARCHAR(255) NOT NULL,
  normalized_account_name VARCHAR(255) NOT NULL DEFAULT '',
  sj_div                 VARCHAR(5) NOT NULL,
  fs_div                 VARCHAR(5) NOT NULL DEFAULT '*',
  applies_to_corp_code   VARCHAR(8) NOT NULL DEFAULT '*',
  mapping_status         VARCHAR(30) NOT NULL,
  mapping_confidence     VARCHAR(20) NOT NULL,
  tag_class              VARCHAR(40) NOT NULL,
  priority               INT NOT NULL DEFAULT 100,
  valid_from             DATE NULL,
  valid_to               DATE NULL,
  review_note            VARCHAR(500) NULL,
  PRIMARY KEY(mapping_id),
  UNIQUE KEY uk_fin_metric_mapping(
    metric_code,industry_profile,account_id(80),normalized_account_name(80),
    sj_div,fs_div,applies_to_corp_code
  ),
  CONSTRAINT fk_fin_metric_mapping_definition FOREIGN KEY(metric_code)
    REFERENCES financial_metric_definitions(metric_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS financial_metric_values (
  metric_value_id       BIGINT NOT NULL AUTO_INCREMENT,
  corp_code             CHAR(8) NOT NULL,
  year                  SMALLINT NOT NULL,
  report_type           ENUM('Q1','H1','Q3','FY') NOT NULL,
  metric_code           VARCHAR(60) NOT NULL,
  value                 BIGINT NULL,
  unit                  VARCHAR(20) NULL,
  value_type            VARCHAR(20) NOT NULL,
  fs_div                ENUM('CFS','OFS') NOT NULL,
  scope                 VARCHAR(50) NOT NULL,
  source_kind           ENUM('DIRECT','DERIVED','DOCUMENT_EXTRACTED') NOT NULL,
  source_type           VARCHAR(40) NOT NULL,
  source_rcept_no       CHAR(14) NULL,
  source_document_id    CHAR(64) NULL,
  source_chunk_id       VARCHAR(100) NULL,
  source_account_id     VARCHAR(255) NULL,
  source_account_name   VARCHAR(255) NULL,
  source_fact_key       CHAR(64) NULL,
  calculation_method    VARCHAR(500) NULL,
  source_values         TEXT NULL,
  review_status         VARCHAR(30) NOT NULL,
  PRIMARY KEY(metric_value_id),
  UNIQUE KEY uk_fin_metric_value(
    corp_code,year,report_type,metric_code,value_type,fs_div,scope,source_kind
  ),
  KEY ix_fin_metric_values_lookup(corp_code,year,report_type,metric_code),
  CONSTRAINT fk_fin_metric_value_company FOREIGN KEY(corp_code) REFERENCES companies(corp_code),
  CONSTRAINT fk_fin_metric_value_definition FOREIGN KEY(metric_code)
    REFERENCES financial_metric_definitions(metric_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

COMMIT;
