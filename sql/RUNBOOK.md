# BigQuery runbook

Concrete steps. Roughly 45 minutes end to end, most of it waiting.

## What you are querying

**`patents-public-data`** is a Google-hosted BigQuery public dataset of worldwide patents. You do
not download it. You run SQL against it in place and pull back a small summary. The table
`patents.publications` is over 100 GB; your results will be a few megabytes.

It is **not** your data and not on your drive. It is a public dataset anyone can query.

## Why you need it

The patent variables are the study's central independent variable, and they do not exist yet.
Right now the model scores AUC 0.6636 against a 0.6568 baseline, and the IP block contributes
nothing, because it is empty.

## Setup (once, ~20 min, no credit card)

1. `console.cloud.google.com` → sign in
2. Create a project, e.g. `qm640-capstone`
3. Left menu → **BigQuery**
4. You are in the **sandbox**: 1 TiB of query processing free per month, no billing account

## Step 1: upload your two input lists as tables

BigQuery needs your patent numbers and assignee names as tables to join against.

In BigQuery: **+ ADD → Local file**, then for each:

| Upload this file | Dataset | Table name | Schema |
|---|---|---|---|
| `data/analysis_ready/bigquery_patent_numbers_clean.csv` | `capstone` | `ob_patents` | auto-detect |
| `data/analysis_ready/bigquery_assignee_names.csv` | `capstone` | `assignees` | auto-detect |

(Create the dataset `capstone` first: click your project → **CREATE DATASET**, location US.)

## Step 2: the probe query, before anything else

Run this first. It costs almost nothing and tells you whether the assignee name strings are right.
**If Novartis comes back with 12 patents instead of tens of thousands, the name is wrong, not the
company.**

```sql
SELECT a.name AS assignee, COUNT(*) AS n_patents
FROM `patents-public-data.patents.publications` p,
     UNNEST(p.assignee_harmonized) a
WHERE p.country_code = 'US'
  AND UPPER(TRIM(a.name)) IN (
      'NOVARTIS AG','PFIZER INC','ELI LILLY AND CO',
      'F HOFFMANN LA ROCHE AG','MERCK SHARP & DOHME CORP')
GROUP BY assignee
ORDER BY n_patents DESC;
```

Expect thousands to tens of thousands per major firm. A near-zero count means that firm's name
needs correcting in `bigquery_assignee_names.csv` before the full run.

### What this probe actually returned, 2026-10-23

```
NOVARTIS AG         8724
ELI LILLY AND CO       3
PFIZER INC             2
```

`F HOFFMANN LA ROCHE AG` and `MERCK SHARP & DOHME CORP` returned no row at all. So four of
the five names are wrong, and the cause is systematic rather than per-firm.

`assignee_harmonized` is not harmonized to legal names. Running
`00_assignee_name_discovery.sql` returned 1,629 real name forms, and they show the pattern:

| curated by hand | what BigQuery actually holds | transformation |
|---|---|---|
| `F HOFFMANN LA ROCHE AG` | `HOFFMANN LA ROCHE` | prefix and suffix dropped |
| `ELI LILLY AND CO` | `LILLY CO ELI` | word order inverted |
| `PFIZER INC` | `PFIZER` | legal suffix dropped |
| `ABBOTT LABORATORIES` | `ABBOTT LAB` | abbreviated |
| `MERCK SHARP & DOHME CORP` | `MERCK SHARP & DOHME` | legal suffix dropped |

`NOVARTIS AG` matched because that string happens to survive all of this unchanged, not
because Novartis was recorded more carefully than the rest.

**Exact matching against guessed strings cannot be fixed name by name.** Run
`00_assignee_name_discovery.sql` instead. It matches on distinctive company tokens, which
punctuation does not affect, and returns the real harmonized name forms with their patent
counts. Export that to `data/patents/assignee_name_dictionary.csv` and reconcile the 149
curated names against it locally, where iterating is free. It processes 6.92 GB, about
0.68% of the monthly allowance: the regex predicate is free, and the increase over this
probe's 4.38 GB is the one extra column read by `COUNT(DISTINCT publication_number)`.

Only once `bigquery_assignee_names.csv` carries verified harmonized names is
`03_assignee_portfolio.sql` worth running. Run it before that and the primary IP variable is
silently undercounted for most sponsors, which is worse than having no variable at all.

## Step 3: check the cost estimate every time

Before clicking **RUN**, the editor shows *"This query will process X"* at the top right.

- under ~50 GB: fine
- over that: stop and narrow the query

**Never `SELECT claims_localized` or `description_localized`.** BigQuery bills on bytes scanned
per column, and those two columns will consume the entire monthly allowance in a single query.

## Step 4: run the three queries

Replace `@patent_list` / `@assignee_list` with a subquery against the tables you uploaded:

```sql
-- instead of:  FROM UNNEST(@patent_list) AS num
-- use:         FROM `YOUR_PROJECT.capstone.ob_patents`
```

| File | Returns | Feeds |
|---|---|---|
| `01_patent_core.sql` | assignee, CPC class, filing/priority/grant dates, backward citations, family id, for your 6,476 Orange Book patents | drug-level IP block (validation subsample) |
| `02_forward_citations_and_family.sql` | forward citations (QUALITY), INPADOC family size and country count (BREADTH) | two of the five index dimensions |
| `03_assignee_portfolio.sql` | per sponsor per year: patents granted, pharma-CPC share, cumulative portfolio | **the primary IP variable**: SCALE and FOCUS, measured as of each trial's start date |

Query 3 matters most. It is the only IP measure that exists for **every** trial, including drugs
that were never approved, which is what keeps the study free of survivorship bias.

## Step 5: export the results

For each query: **SAVE RESULTS → CSV (local file)** if under ~16k rows, otherwise **→ Google
Drive**, then download.

Put all three in `data/patents/` in the repo:

```
data/patents/patent_core.csv
data/patents/forward_citations_family.csv
data/patents/assignee_portfolio.csv
```

## Step 6: tell me, and I will do the rest

Once those three CSVs are in `data/patents/`, I will write `prep_12_patents.py` to join them
onto the trials table and rebuild the IP index. I have deliberately not written it yet, because
the join has to match the real column names and types that come back, not what I guess they
will be.

After the join the index becomes spec-complete (`ip_index_spec_complete = 1`), RQ1 gets a real
strong/weak split instead of the current TERM-only placeholder, and RQ2 gets its IP block.

**The whole experiment is whether that beats AUC 0.6568.** If it does not, that is a finding worth
reporting, not a failure.
