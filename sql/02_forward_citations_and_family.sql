-- =====================================================================
-- Forward citations (QUALITY) and INPADOC family size and spread (BREADTH).
-- Two of the five dimensions of the IP strength index.
--
-- INPUT: capstone.ob_patents, uploaded from
--        data/analysis_ready/bigquery_patent_numbers_clean.csv (6,475 rows,
--        column patent_prefix, e.g. US-7625884).
--
-- Forward citations come from google_patents_research.publications, which
-- pre-computes cited_by. Counting them from patents.publications instead would
-- need a self-join across the whole citation column, which is far more
-- expensive.
--
-- COST: the cited_by array is the large column here. patents.publications is
-- read twice, but only for publication_number, family_id and country_code,
-- which are small scalars. Check the estimate before running.
--
-- Two corrections to the earlier version of this file:
--
-- 1. It started FROM fwd, so any Orange Book patent absent from the research
--    table was dropped silently rather than returned with a null citation
--    count. Coverage of that table is not complete, and a missing patent is
--    not a patent with zero citations. This version starts from the Orange
--    Book patents themselves, so absence is visible as NULL and can be
--    distinguished from a genuine zero downstream.
--
-- 2. It read patents.publications a third time, purely to recover family_id
--    for the family join. family_id is now carried through from ob_pubs.
--
-- Replace YOUR_PROJECT with your project id.
-- =====================================================================
WITH ob AS (
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

-- The Orange Book patents as publications, carrying family_id so the family
-- statistics join without reading publications again.
ob_pubs AS (
  SELECT
    REGEXP_EXTRACT(p.publication_number, r'^(US-(?:RE)?\d+)-') AS patent_prefix,
    p.publication_number,
    p.family_id
  FROM `patents-public-data.patents.publications` p
  WHERE p.country_code = 'US'
    AND REGEXP_EXTRACT(p.publication_number, r'^(US-(?:RE)?\d+)-')
        IN (SELECT patent_prefix FROM ob)
),

-- The country predicate that used to sit here was `r.country = 'US'`, and it
-- matched nothing, so every n_forward_citations came back NULL and the QUALITY
-- dimension could not be built. Confirmed by 02a_diagnose_research_country.sql
-- on 2026-10-25: this table stores the country NAME, not the ISO code. The top
-- values are China, Japan and "United States" (22,330,398 publications), so
-- 'US' was never going to match. patents.publications uses country_code = 'US'
-- for the same records, which is why the family half of this query worked and
-- the citation half silently returned nothing.
--
-- The filter is not reinstated with the corrected value, because it is
-- redundant: the patent_prefix regex below already restricts the match to US
-- publications. Dropping it also reads one column fewer.
fwd AS (
  SELECT
    r.publication_number,
    ARRAY_LENGTH(r.cited_by) AS n_forward_citations
  FROM `patents-public-data.google_patents_research.publications` r
  WHERE REGEXP_EXTRACT(r.publication_number, r'^(US-(?:RE)?\d+)-')
        IN (SELECT patent_prefix FROM ob)
),

-- INPADOC family size and country spread: every publication worldwide sharing
-- a family_id with one of the Orange Book patents. This is the breadth measure,
-- so it must not be restricted to US publications.
fam AS (
  SELECT
    family_id,
    COUNT(DISTINCT publication_number) AS family_size,
    COUNT(DISTINCT country_code)       AS family_n_countries
  FROM `patents-public-data.patents.publications`
  WHERE family_id IN (SELECT DISTINCT family_id FROM ob_pubs)
  GROUP BY family_id
)

SELECT
  o.patent_prefix,
  o.publication_number,
  o.family_id,
  f.n_forward_citations,
  fam.family_size,
  fam.family_n_countries
FROM ob_pubs o
LEFT JOIN fwd f ON f.publication_number = o.publication_number
LEFT JOIN fam   ON fam.family_id = o.family_id
ORDER BY o.patent_prefix, o.publication_number;
