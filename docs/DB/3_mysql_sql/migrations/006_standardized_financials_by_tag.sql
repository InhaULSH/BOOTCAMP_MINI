-- 006: standardized_financials by official account id (H1, 2026-10-09)
--
-- Before: facts joined the 24 standard accounts by the stored display label
-- (financial_facts.standard_account_nm = standard_accounts.standard_account_nm).
-- The same official tag is stored under label variants ("당기순이익(손실)",
-- "영업이익(손실)", "영업활동으로 인한 현금흐름"), so net income was missing for
-- every company and operating income / operating cash flow for about half.
--
-- After: facts are matched by official account id and statement group
-- (IS and CIS form one group) through the approved tags below (taken from
-- standard_account_mapping, plus ifrs-full_ProfitLossFromOperatingActivities
-- as the second operating-income tag).  One row is returned per company,
-- period, statement scope, standard account and value type: tag priority,
-- then IS before CIS, then the reported value before a calculated one, then
-- display order.  Lines without an approved tag fall back to the stored label,
-- but only in the statement and period nature of the standard account, so
-- statement of changes in equity rows, cash flow opening/closing balances and
-- cash flow working-capital changes are no longer returned as balances.
-- Values, signs and units are unchanged; CAPEX still comes from capex_facts.
CREATE OR REPLACE VIEW standardized_financials AS
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
