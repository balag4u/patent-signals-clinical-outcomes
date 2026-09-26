-- =====================================================================
-- Sponsor-level IP portfolio, measured AS OF a cutoff year.
-- This is the SURVIVORSHIP-SAFE variable block: it exists for every
-- trial sponsor, not only sponsors whose drug reached approval.
-- @assignee_list = harmonized assignee names matched from trial sponsors.
-- =====================================================================
WITH tgt AS (
  SELECT UPPER(TRIM(name)) AS assignee_norm FROM UNNEST(@assignee_list) AS name
),
pat AS (
  SELECT
    UPPER(TRIM(a.name)) AS assignee_norm,
    p.publication_number,
    CAST(SUBSTR(CAST(p.grant_date AS STRING),1,4) AS INT64) AS grant_year,
    (SELECT COUNTIF(SUBSTR(c.code,1,4) IN ('A61K','A61P','C07D','C12N'))
       FROM UNNEST(p.cpc) c) AS n_pharma_cpc
  FROM `patents-public-data.patents.publications` p,
       UNNEST(p.assignee_harmonized) a
  WHERE p.country_code = 'US'
    AND p.grant_date > 0
    AND UPPER(TRIM(a.name)) IN (SELECT assignee_norm FROM tgt)
)
SELECT
  assignee_norm,
  grant_year,
  COUNT(*)                                   AS patents_granted_that_year,
  COUNTIF(n_pharma_cpc > 0)                  AS pharma_patents_that_year,
  SUM(COUNT(*)) OVER (PARTITION BY assignee_norm ORDER BY grant_year)
                                             AS cumulative_portfolio
FROM pat
GROUP BY assignee_norm, grant_year
ORDER BY assignee_norm, grant_year;
