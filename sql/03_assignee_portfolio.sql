-- =====================================================================
-- Sponsor-level IP portfolio, measured AS OF a cutoff year.
--
-- This is the SURVIVORSHIP-SAFE variable block: it exists for every trial
-- sponsor, not only sponsors whose drug reached approval. It is the study's
-- primary independent variable.
--
-- INPUT: capstone.assignees_verified, uploaded from
--        data/analysis_ready/bigquery_assignee_verified.csv, which is written
--        by scripts/prep/prep_12_assignee_crosswalk.py.
--
-- Do NOT run this against bigquery_assignee_names.csv. Those names were
-- written by hand and four of five probed names returned nothing or almost
-- nothing, because assignee_harmonized abbreviates, drops legal suffixes and
-- sometimes inverts word order. See sql/RUNBOOK.md Step 2.
--
-- THREE PORTFOLIO DEFINITIONS, REPORTED SIDE BY SIDE
-- The author's decision of 2026-10-24 was to compute the portfolio both
-- unfiltered and restricted to pharmaceutical classification, and to report
-- the IP effect under each as a robustness check rather than pick one. A
-- hand-curated exclusion list is harder to defend than a published
-- classification scheme, so the restriction is done by CPC code here:
--
--   cum_all      every granted US patent. Measures the firm, not the drug
--                programme: Bayer AG's 18,712 patents include crop science
--                and materials.
--   cum_pharma   A61K and A61P only. This matches the FOCUS dimension as
--                README.md defines it (share of portfolio in A61K/A61P), so
--                the headline and the index definition agree.
--   cum_broad    A61K, A61P, C07D, C12N. Adds heterocyclic chemistry and
--                microorganisms/enzymes. Catches platform and biologics IP
--                that carries no therapeutic-use class, at the cost of
--                pulling in industrial chemistry.
--
-- The earlier version of this file counted the broad set and called it
-- "pharma", which would have reported a figure the README's own definition
-- does not describe.
--
-- CORPORATE ROLLUP IS DELIBERATELY NOT DONE HERE. corporate_group and
-- parent_from_year are carried through unaggregated, because the rollup has
-- to compare parent_from_year against each TRIAL's start year, which this
-- query cannot see. Wyeth's patents are Pfizer's from 2009, not before.
-- prep_13 applies that.
--
-- COST: this reads the cpc array, which the probe and discovery queries did
-- not. Expect materially more than their 6.92 GB. CHECK THE ESTIMATE IN THE
-- EDITOR BEFORE RUNNING, and if it exceeds about 100 GB, stop and narrow it.
-- Never add claims_localized or description_localized.
--
-- Replace YOUR_PROJECT with your project id.
-- =====================================================================
WITH verified AS (
  SELECT
    UPPER(TRIM(harmonized_name)) AS assignee_norm,
    ANY_VALUE(corporate_group)   AS corporate_group,
    ANY_VALUE(parent_from_year)  AS parent_from_year
  FROM `YOUR_PROJECT.capstone.assignees_verified`
  WHERE harmonized_name IS NOT NULL
  GROUP BY assignee_norm
),

pat AS (
  SELECT
    UPPER(TRIM(a.name)) AS assignee_norm,
    p.publication_number,
    CAST(SUBSTR(CAST(p.grant_date AS STRING), 1, 4) AS INT64) AS grant_year,
    (SELECT COUNTIF(SUBSTR(c.code, 1, 4) IN ('A61K', 'A61P'))
       FROM UNNEST(p.cpc) c) AS n_cpc_pharma,
    (SELECT COUNTIF(SUBSTR(c.code, 1, 4) IN ('A61K', 'A61P', 'C07D', 'C12N'))
       FROM UNNEST(p.cpc) c) AS n_cpc_broad
  FROM `patents-public-data.patents.publications` p,
       UNNEST(p.assignee_harmonized) a
  WHERE p.country_code = 'US'
    AND p.grant_date > 0
    AND UPPER(TRIM(a.name)) IN (SELECT assignee_norm FROM verified)
),

-- One publication can list the same assignee twice, so de-duplicate to
-- patent level before counting. Without this the portfolio is inflated for
-- exactly the large firms whose filings carry several assignee entries.
dedup AS (
  SELECT DISTINCT assignee_norm, publication_number, grant_year,
         n_cpc_pharma, n_cpc_broad
  FROM pat
),

yearly AS (
  SELECT
    assignee_norm,
    grant_year,
    COUNT(*)                        AS granted_all,
    COUNTIF(n_cpc_pharma > 0)       AS granted_pharma,
    COUNTIF(n_cpc_broad > 0)        AS granted_broad
  FROM dedup
  GROUP BY assignee_norm, grant_year
)

SELECT
  v.corporate_group,
  v.parent_from_year,
  y.assignee_norm,
  y.grant_year,
  y.granted_all,
  y.granted_pharma,
  y.granted_broad,
  SUM(y.granted_all)    OVER w AS cum_all,
  SUM(y.granted_pharma) OVER w AS cum_pharma,
  SUM(y.granted_broad)  OVER w AS cum_broad,
  SAFE_DIVIDE(SUM(y.granted_pharma) OVER w,
              SUM(y.granted_all) OVER w) AS pharma_share_to_date
FROM yearly y
JOIN verified v ON v.assignee_norm = y.assignee_norm
WINDOW w AS (
  PARTITION BY y.assignee_norm
  ORDER BY y.grant_year
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
ORDER BY v.corporate_group, y.assignee_norm, y.grant_year;
