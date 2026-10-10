-- Replace the unused internal bank placeholder with the steel grouping.
-- This changes only index metadata and preserves any unexpected memberships.
SET NAMES utf8mb4;
START TRANSACTION;

INSERT INTO krx_indices (
  index_code, official_index_code, index_name, display_name,
  source_as_of, source_url, is_active
)
SELECT
  'KRX_STEEL', NULL, 'KRX 철강', '철강',
  '2026-10-07', source_url, is_active
FROM krx_indices
WHERE index_code = 'KRX_BANK'
ON DUPLICATE KEY UPDATE
  official_index_code=NULL,
  index_name='KRX 철강',
  display_name='철강',
  source_as_of='2026-10-07',
  is_active=1;

UPDATE krx_index_constituents
SET index_code = 'KRX_STEEL', updated_at = CURRENT_TIMESTAMP
WHERE index_code = 'KRX_BANK';

DELETE FROM krx_indices WHERE index_code = 'KRX_BANK';

COMMIT;
