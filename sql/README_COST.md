# BigQuery cost discipline

BigQuery bills on **bytes scanned per column**, not rows returned. The
`patents-public-data.patents.publications` table is large, and some columns are
enormous.

| Column | Approx. relative cost | Use? |
|---|---|---|
| scalar fields (dates, numbers, ids) | very low | yes |
| `assignee_harmonized`, `cpc`, `ipc` | low | yes |
| `citation` | moderate | yes, via ARRAY_LENGTH |
| `abstract_localized` | high | only if needed |
| `claims_localized` | **very high** | avoid on the free tier |
| `description_localized` | **extreme** | never on the free tier |

## Always dry-run first

```bash
bq query --dry_run --use_legacy_sql=false < 01_patent_core.sql
```

This reports bytes that would be processed without consuming quota. The BigQuery
sandbox free tier allows **1 TiB of query processing per month**; confirm current
limits before running anything that reports more than ~50 GB.

## Claim breadth without the claims column

Independent-claim word count is the standard inverse proxy for claim breadth, but
`claims_localized` is too expensive for the sandbox. Two alternatives:

1. Use `google_patents_research.publications.top_terms` (small) as a
   technology-scope proxy instead of claim length.
2. Fetch claims for only the final analytic patent set via the PatentsView API
   (`g_claim` endpoint), which is free and rate-limited rather than byte-billed.

Record whichever you choose in the synopsis Methods section, since it changes the
operational definition of the claim-breadth variable.
