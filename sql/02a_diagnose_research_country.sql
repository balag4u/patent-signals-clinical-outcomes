-- =====================================================================
-- Two-second diagnostic. Run this BEFORE re-running 02.
--
-- On 2026-10-24, sql/02 returned NULL for every n_forward_citations. The fwd
-- CTE filtered on `r.country = 'US'` in google_patents_research.publications,
-- which appears to return nothing. This query shows what that field actually
-- contains, so the cause is confirmed rather than assumed.
--
-- COST: reads one small string column. Expect well under 1 GB. Check the
-- estimate anyway.
--
-- ANSWER, run 2026-10-25: the field holds country NAMES. Top values were
-- China (56,641,679), Japan (28,374,410) and United States (22,330,398), so
-- `country = 'US'` matched zero rows. Diagnosis confirmed. sql/02 no longer
-- filters on this field at all, because the publication_number prefix already
-- restricts the match to US patents. Kept for the record.
-- =====================================================================
SELECT
  country,
  COUNT(*) AS n_publications
FROM `patents-public-data.google_patents_research.publications`
GROUP BY country
ORDER BY n_publications DESC
LIMIT 15;
