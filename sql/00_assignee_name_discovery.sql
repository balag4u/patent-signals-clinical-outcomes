-- 00_assignee_name_discovery.sql
--
-- WHY THIS EXISTS
-- The probe query in RUNBOOK.md Step 2 matched assignee names with exact equality:
--     UPPER(TRIM(a.name)) IN ('NOVARTIS AG','PFIZER INC','ELI LILLY AND CO', ...)
-- On 2026-10-23 that returned NOVARTIS AG 8,724 but ELI LILLY AND CO 3, PFIZER INC 2,
-- and nothing at all for F HOFFMANN LA ROCHE AG or MERCK SHARP & DOHME CORP.
--
-- Cause: assignee_harmonized is not harmonized to legal names. The 1,629-row dictionary
-- this query returned shows what it actually stores:
--
--     curated by hand              assignee_harmonized actually holds
--     F HOFFMANN LA ROCHE AG       HOFFMANN LA ROCHE        (prefix and suffix dropped)
--     ELI LILLY AND CO             LILLY CO ELI             (word order inverted)
--     PFIZER INC                   PFIZER                   (legal suffix dropped)
--     ABBOTT LABORATORIES          ABBOTT LAB               (abbreviated)
--     MERCK SHARP & DOHME CORP     MERCK SHARP & DOHME      (legal suffix dropped)
--     REGENERON PHARMACEUTICALS    REGENERON PHARMA         (abbreviated)
--
-- An earlier reading of this blamed punctuation, on the theory that the harmonizer keeps
-- periods and hyphens the curated names had dropped. It does not: it strips them too.
-- The real mechanism is abbreviation of descriptors (LABORATORIES to LAB,
-- PHARMACEUTICALS to PHARMA, INTERNATIONAL to INT), removal of legal suffixes, and
-- occasional word-order inversion. NOVARTIS AG matched because that string survives all
-- three transformations unchanged, not because Novartis was recorded more carefully.
--
-- Either way the consequence is the same and is the reason this file exists: a
-- hand-written name can match only by luck, and when it fails it returns a small count
-- or no row at all rather than an error.
--
-- Exact matching against guessed strings cannot be repaired name by name. This query
-- discovers the real vocabulary instead: it matches on distinctive company TOKENS, which
-- are unaffected by punctuation, and returns every harmonized name form containing one.
-- The 149 curated names are then matched against that output locally, where iterating
-- costs nothing.
--
-- JIANGSU was removed from the token list: it is a Chinese province, and it returned
-- GLOBE JIANGSU, GREENWORKS JIANGSU and UNIV JIANGSU rather than the sponsor. HENGRUI
-- identifies Jiangsu Hengrui Medicine on its own.
--
-- ORION and UCB were missing from the first version of this token list, run on
-- 2026-10-23, so those two corporate groups were never searched and came back with no
-- candidate at all. Both were added and the query re-run. prep_12_assignee_crosswalk.py
-- now audits every curated name against this pattern and fails loudly on any name the
-- pattern could not have found, so the same omission cannot pass silently again.
--
-- Most tokens match as a prefix, so GLAXO reaches GLAXOSMITHKLINE and SUN PHARMA reaches
-- SUN PHARMACEUTICAL INDUSTRIES. ENDO, ISIS and ROCHE keep a closing word boundary
-- because as prefixes they would pull in endoscopy firms and the University of
-- Rochester. Tokens that are ordinary words or that collide with large
-- non-pharmaceutical firms (ARRAY, FOREST, HORIZON, JOHNSON, JUNO, KITE, LEO, SAGE,
-- SUN, UNITED) are required as phrases. MERCK SHARP & DOHME is reached through DOHME,
-- which avoids SHARP matching Sharp Corporation.
--
-- COST
-- Measured at 6.92 GB on 2026-10-23, roughly 0.68% of the 1 TiB monthly sandbox
-- allowance.
--
-- BigQuery bills bytes scanned per column, not predicate complexity, so switching the
-- predicate from IN to REGEXP_CONTAINS costs nothing. The increase over the 4.38 GB
-- Step 2 probe is entirely the third column: COUNT(DISTINCT p.publication_number) reads
-- publication_number, where the probe's COUNT(*) read no additional column. Columns
-- scanned here are country_code, assignee_harmonized and publication_number.
--
-- COUNT(DISTINCT p.publication_number) is kept because UNNEST emits one row per assignee
-- entry, so a publication listing the same harmonized name twice would otherwise be
-- counted twice. That duplication is rare. If this ever needs re-running on a tight
-- allowance, COUNT(*) gives a near-identical ranking for about 4.4 GB.
--
-- Grant dates are deliberately not selected: grant_date would be a fourth column, bought
-- for information that name matching does not need.
--
-- OUTPUT
-- One row per harmonized assignee name holding 10 or more US publications, largest
-- first. Export with SAVE RESULTS -> CSV to data/patents/assignee_name_dictionary.csv.
-- If the row count exceeds the console's 16,000-row download cap, raise min_patents.

WITH params AS (
  SELECT
    10 AS min_patents,
    r'\b(?:ENDO|ISIS|ORION|ROCHE|UCB)\b|\b(?:ABBOTT|ABBVIE|ACADIA|ACTELION|AGENSYS|ALEXION|ALKERMES|ALLERGAN|ALMIRALL|ALNYLAM|AMGEN|ARIAD|ASTELLAS|ASTEX|ASTRAZENECA|AVENTIS|BAUSCH|BAXALTA|BAYER|BEECHAM|BEHRING|BIOGEN|BIOMARIN|BIONTECH|BIOVERATIV|BOEHRINGER|BRISTOL|CELGENE|CENTOCOR|CEPHALON|CHIESI|CHUGAI|CIPLA|CUBIST|DAIICHI|DAINIPPON|DERMIRA|DOHME|EISAI|EXELIXIS|FERRING|GALDERMA|GENENTECH|GENZYME|GILEAD|GLAXO|GRIFOLS|HENGRUI|HOFFMANN|HOSPIRA|IMMUNEX|IMMUNOMEDICS|INCYTE|INGELHEIM|INTERCEPT|IONIS|IPSEN|JANSSEN|JAZZ|KIRIN|KYOWA|LILLY|LOXO|LUNDBECK|MALLINCKRODT|MEDIMMUNE|MENARINI|MERCK|MILLENNIUM|MITSUBISHI|MODERNATX|MORPHOTEK|MYLAN|NEUROCRINE|NORDISK|NOVARTIS|ONYX|ORGANON|OTSUKA|PFIZER|PHARMACYCLICS|PLEXXIKON|RECORDATI|REDDY|REGENERON|SALIX|SANDOZ|SANKYO|SANOFI|SAREPTA|SCHERING|SEAGEN|SERONO|SERVIER|SHIRE|SMITHKLINE|SQUIBB|SUMITOMO|SUNOVION|TAKEDA|TANABE|TESARO|TEVA|VALEANT|VERTEX|VIATRIS|VIFOR|VIIV|WYETH|ZOETIS|ARES TRADING|ARRAY BIOPHARMA|CSL BEHRING|CSL LIMITED|FOREST LABORATOR|HORIZON PHARMA|HORIZON THERAPEUT|JOHNSON & JOHNSON|JOHNSON AND JOHNSON|JUNO THERAPEUT|KITE PHARMA|LEO PHARMA|PTC THERAPEUT|SAGE THERAPEUT|SEATTLE GENETICS|SUN PHARMA|UNITED THERAPEUT)' AS token_pattern
)

SELECT
  a.name     AS harmonized_name,
  COUNT(DISTINCT p.publication_number) AS n_patents
FROM `patents-public-data.patents.publications` p,
     UNNEST(p.assignee_harmonized) a
CROSS JOIN params
WHERE p.country_code = 'US'
  AND REGEXP_CONTAINS(UPPER(a.name), params.token_pattern)
GROUP BY harmonized_name
HAVING n_patents >= (SELECT min_patents FROM params)
ORDER BY n_patents DESC;
