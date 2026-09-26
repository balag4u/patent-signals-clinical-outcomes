# Data sources

All eight sources are open access and require no institutional subscription. Retrieved
2026-09-24 to 2026-09-26. Raw archives are ~15 GB and are not vendored; each is
re-downloadable from the endpoint below.

| Source | Endpoint | Used for |
|---|---|---|
| ClinicalTrials.gov API v2 | `https://clinicaltrials.gov/api/v2/studies` | Dependent variables; trial design |
| AACT (CTTI) | `https://aact.ctti-clinicaltrials.org/download` | MeSH ancestors for RQ4 strata |
| FDA Orange Book | `https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files` | Small-molecule patents, exclusivity |
| FDA Purple Book | `https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/` | Biologics, biosimilar status |
| Drugs@FDA | `https://www.fda.gov/drugs/drug-approvals-and-databases/drugfda-data-files` | Regulatory pathway, designations |
| openFDA | `https://open.fda.gov/data/downloads/` | UNII registry, NDC, labels, CRLs |
| FAERS quarterly | `https://fis.fda.gov/content/Exports/faers_ascii_YYYYQn.zip` | Disproportionality (PRR/ROR) |
| Open Targets 26.09 | `https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/26.09/` | Genetic evidence, drug synonyms |
| Medicaid SDUD | `https://download.medicaid.gov/data/StateDrugUtilizationData-YYYY.csv` | Commercial uptake |
| Google Patents | BigQuery `patents-public-data.patents.publications` | Patent portfolio variables |

## Access notes that cost time to discover

- **`www.fda.gov` bot-blocks scripted requests**, returning
  `/apology_objects/abuse-detection-apology.html`. Workaround: browser `User-Agent`, a `Referer`,
  `Sec-Fetch-*` headers, and the `?attachment` query parameter.
- **The Purple Book does not live on `purplebooksearch.fda.gov`.** Downloads are served from
  `accessdata.fda.gov/drugsatfda_docs/PurpleBook/<year>/`. Despite a "Monthly Historical Data
  Changes Report" banner, the file is the full standing listing (only 58 of 2,272 rows carry a
  change flag).
- **`data.cms.gov` is behind Akamai edge protection** and rejects scripted clients regardless of
  headers or HTTP version. Medicare Part D therefore needs a manual browser download; Medicaid
  SDUD is used instead, and the two cover different populations.
- **AACT's host throttles heavily.** The ClinicalTrials.gov API v2 is the faster route for trial
  records; AACT is used only for its MeSH ancestor table.
- **NIH RePORTER's endpoint is GET-only** (HEAD returns 405) and **does not support byte ranges**,
  so `curl -C -` silently no-ops — retries must re-download from scratch.
- **PatentsView now requires an API key** and its bulk S3 path returns 403, which is why patent
  data comes from BigQuery instead.

## Known limitations

- Medicaid SDUD suppresses small cells: **49.0% of rows** across 2015–2026, rising from 47.0% to
  50.7%. Suppression concentrates in low-volume products, so missingness is non-random and biased
  toward rare-disease drugs.
- ClinicalTrials.gov over-represents high-income countries.
- FAERS has no exposure denominator; only disproportionality statistics are interpretable.
- Orange Book patent listings exist only for approved applications (1,336 of 27,376), which is why
  drug-level IP is a validation subsample rather than the primary predictor block.
