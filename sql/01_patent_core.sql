-- =====================================================================
-- QM 640 Capstone | Patent core attributes for Orange Book patents
-- Source: patents-public-data.patents.publications (Google Patents Public Data)
--
-- INPUT: capstone.ob_patents, uploaded from
--        data/analysis_ready/bigquery_patent_numbers_clean.csv (6,475 rows,
--        column patent_prefix, e.g. US-7625884).
--
-- COST: this is the most expensive of the three queries, because
-- ARRAY_LENGTH(p.citation) reads the backward-citation array and
-- ARRAY_LENGTH(p.cpc) reads the classification array, both of which are large.
-- Columns read: publication_number, application_number, country_code,
-- kind_code, family_id, publication_date, filing_date, priority_date,
-- grant_date, cpc, citation, assignee_harmonized, inventor_harmonized.
-- CHECK THE ESTIMATE BEFORE RUNNING. If it exceeds about 150 GB, drop
-- n_backward_citations (the citation array) first: it is the single largest
-- column here and is not used by any feature in the interim analysis.
--
-- Never add claims_localized or description_localized. Either one would
-- consume the whole monthly sandbox allowance in a single run.
--
-- Replace YOUR_PROJECT with your project id.
-- =====================================================================
WITH ob AS (
  -- Orange Book patent numbers, US utility patents
  -- LIKE 'US-%' is a guard, not a filter. bigquery_patent_numbers_clean.csv is a
  -- single STRING column, so BigQuery's auto-detect cannot tell its header row
  -- from data and may load the literal text "patent_prefix" as a row. Upload it
  -- with Auto detect OFF, schema "patent_prefix:STRING" and "Header rows to
  -- skip" set to 1. This guard means a stray header row cannot join to anything
  -- even if that is missed. Expect 6,475 rows.
  SELECT DISTINCT UPPER(TRIM(patent_prefix)) AS patent_prefix
  FROM `YOUR_PROJECT.capstone.ob_patents`
  WHERE patent_prefix IS NOT NULL
    AND UPPER(TRIM(patent_prefix)) LIKE 'US-%'
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
