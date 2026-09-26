-- =====================================================================
-- Forward citations (impact proxy) + INPADOC family size (geographic breadth)
-- Uses google_patents_research.publications, which pre-computes cited_by,
-- so we avoid a self-join scan over the full citation column.
-- =====================================================================
WITH ob AS (
  SELECT DISTINCT CAST(num AS STRING) AS patent_no FROM UNNEST(@patent_list) AS num
),
fwd AS (
  SELECT
    REGEXP_EXTRACT(r.publication_number, r'^US-(\d+)-') AS patent_no,
    r.publication_number,
    ARRAY_LENGTH(r.cited_by) AS n_forward_citations
  FROM `patents-public-data.google_patents_research.publications` r
  WHERE r.country = 'US'
    AND REGEXP_EXTRACT(r.publication_number, r'^US-(\d+)-') IN (SELECT patent_no FROM ob)
),
fam AS (
  -- family size = number of publications sharing the family_id (geographic breadth)
  SELECT family_id, COUNT(DISTINCT publication_number) AS family_size,
         COUNT(DISTINCT country_code) AS family_n_countries
  FROM `patents-public-data.patents.publications`
  WHERE family_id IN (
    SELECT DISTINCT family_id FROM `patents-public-data.patents.publications`
    WHERE country_code='US'
      AND REGEXP_EXTRACT(publication_number, r'^US-(\d+)-') IN (SELECT patent_no FROM ob)
  )
  GROUP BY family_id
)
SELECT f.*, fam.family_size, fam.family_n_countries
FROM fwd f
LEFT JOIN `patents-public-data.patents.publications` p
  ON p.publication_number = f.publication_number
LEFT JOIN fam ON fam.family_id = p.family_id;
