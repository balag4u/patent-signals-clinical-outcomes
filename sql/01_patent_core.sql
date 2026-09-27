-- =====================================================================
-- QM 640 Capstone | Patent core attributes for Orange Book patents
-- Source: patents-public-data.patents.publications (Google Patents Public Data)
-- Cost control: SELECTs only small scalar/array columns. Do NOT add
--   claims_localized or description_localized here (see 03_claims_expensive.sql).
-- Replace @patent_list with the Orange Book patent numbers.
-- =====================================================================
WITH ob AS (
  -- Orange Book patent numbers, US utility patents
  SELECT DISTINCT CAST(num AS STRING) AS patent_prefix
  FROM UNNEST(@patent_list) AS num
),
pub AS (
  SELECT
    p.publication_number,
    -- US-7625884-B2 -> 7625884
    REGEXP_EXTRACT(p.publication_number, r'^(US-(?:RE)?\d+)-') AS patent_prefix,
    p.application_number,
    p.country_code,
    p.kind_code,
    p.family_id,
    p.publication_date,
    p.filing_date,
    p.priority_date,
    p.grant_date,
    ARRAY_LENGTH(p.cpc)                AS n_cpc_codes,
    ARRAY_LENGTH(p.citation)           AS n_backward_citations,
    ARRAY_LENGTH(p.assignee_harmonized) AS n_assignees,
    ARRAY_LENGTH(p.inventor_harmonized) AS n_inventors,
    (SELECT a.name FROM UNNEST(p.assignee_harmonized) a LIMIT 1) AS assignee_primary,
    (SELECT STRING_AGG(a.name, '|') FROM UNNEST(p.assignee_harmonized) a) AS assignees_all,
    (SELECT a.country_code FROM UNNEST(p.assignee_harmonized) a LIMIT 1) AS assignee_country,
    (SELECT c.code FROM UNNEST(p.cpc) c WHERE c.first LIMIT 1) AS cpc_primary,
    (SELECT STRING_AGG(DISTINCT SUBSTR(c.code,1,4), '|')
       FROM UNNEST(p.cpc) c) AS cpc_subclasses,
    -- A61P = therapeutic activity; A61K = medicinal preparations
    (SELECT COUNTIF(SUBSTR(c.code,1,4) = 'A61P') FROM UNNEST(p.cpc) c) AS n_cpc_a61p,
    (SELECT COUNTIF(SUBSTR(c.code,1,4) = 'A61K') FROM UNNEST(p.cpc) c) AS n_cpc_a61k
  FROM `patents-public-data.patents.publications` p
  WHERE p.country_code = 'US'
    AND REGEXP_EXTRACT(p.publication_number, r'^(US-(?:RE)?\d+)-') IN (SELECT patent_prefix FROM ob)
)
SELECT
  pub.*,
  DATE_DIFF(PARSE_DATE('%Y%m%d', CAST(pub.grant_date AS STRING)),
            PARSE_DATE('%Y%m%d', CAST(pub.priority_date AS STRING)), DAY) / 365.25
    AS years_priority_to_grant
FROM pub;
