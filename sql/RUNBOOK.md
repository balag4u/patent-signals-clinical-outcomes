# How to run the patent queries

Start to finish, about 45 minutes, most of it waiting.

## What you are querying

**`patents-public-data`** is a Google-hosted copy of worldwide patent records,
available to anyone on BigQuery. You do not download it. You run queries
against it where it sits and bring back a small summary. The main table is over
100 GB; what comes back here is a few megabytes.

It is not your data and it is not on your drive. It is a public dataset anyone
can query.

## Why the project needs it

The patent measures are the study's main independent variable, meaning the
thing being tested as a predictor. They do not exist anywhere else. Without
them the model is design and sponsor history only.

## Setting up

Two routes. **The command line is the better one** if you expect to run the
queries more than once, which you probably will.

### Command line (recommended)

```bash
# install, no admin password needed
curl -o gcloud.tar.gz https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-x86_64.tar.gz
tar -xzf gcloud.tar.gz -C ~
export PATH=$HOME/google-cloud-sdk/bin:$PATH

gcloud auth login                       # opens a browser once
gcloud config set project YOUR_PROJECT
```

Use `google-cloud-cli-darwin-arm.tar.gz` on an Apple Silicon Mac. Check with
`uname -m`: `x86_64` means Intel, `arm64` means Apple Silicon.

### Web console

Go to `console.cloud.google.com/bigquery`, sign in, accept the terms, and
create a project. You are placed in the **sandbox**, which gives 1 TiB of query
processing free per month with no credit card. The limits are worth knowing:

- 10 GiB of storage, **for the lifetime of the project**, not per month, and
  not returned when you delete data
- Tables expire after 60 days
- No `INSERT`, `UPDATE` or `DELETE`. Everything here is `SELECT` and file
  uploads, so this does not get in the way

## Step 1: upload the two input lists

BigQuery needs your patent numbers and company names as tables to match
against.

```bash
bq load --replace --source_format=CSV --skip_leading_rows=1 \
  --schema="patent_prefix:STRING" \
  YOUR_PROJECT:capstone.ob_patents \
  data/analysis_ready/bigquery_patent_numbers_clean.csv

bq load --replace --source_format=CSV --skip_leading_rows=1 \
  --schema="corporate_group:STRING,harmonized_name:STRING,n_patents:INTEGER,parent_from_year:INTEGER,source:STRING" \
  YOUR_PROJECT:capstone.assignees_verified \
  data/analysis_ready/bigquery_assignee_verified.csv
```

**Specify the schema rather than letting BigQuery guess.** The patent file is a
single column of text, and automatic detection cannot tell a header row from
data when every value looks the same. It will load the word `patent_prefix` as
if it were a patent number.

Check the counts afterwards. `ob_patents` should hold 6,476 rows and
`assignees_verified` 712.

## Step 2: find out what the patent database actually calls each company

**Run this before anything else.** It is the step that makes the rest work.

The owner field in BigQuery, `assignee_harmonized`, sounds tidy and is not. It
abbreviates, drops company suffixes and sometimes reverses word order:

| Written by hand | What BigQuery holds |
|---|---|
| `ELI LILLY AND CO` | `LILLY CO ELI` |
| `PFIZER INC` | `PFIZER` |
| `ABBOTT LABORATORIES` | `ABBOTT LAB` |
| `F HOFFMANN LA ROCHE AG` | `HOFFMANN LA ROCHE` |

So searching for exact company names mostly fails, and it fails **silently**:
you get a small number back rather than an error. When this was first tried,
Novartis returned 8,724 patents, Eli Lilly returned 3 and Pfizer returned 2.

`00_assignee_name_discovery.sql` searches for distinctive **word fragments**
instead, which survive abbreviation, and returns every real owner name
containing one. That list is then matched offline, where retrying is free.

```bash
sed 's/YOUR_PROJECT/your-project-id/g' sql/00_assignee_name_discovery.sql \
  | bq query --nouse_legacy_sql --format=csv --max_rows=1000000 --quiet \
  > data/patents/assignee_name_dictionary.csv
```

Then build the checked company list:

```bash
python scripts/prep/prep_12_assignee_crosswalk.py
```

This stops with an error if any company on your curated list could not possibly
be found by the search. That is deliberate: a company that returns no patents
because the search never looked for it would otherwise read as a company with
no inventions.

## Step 3: check the cost estimate, every time

```bash
bq query --dry_run --nouse_legacy_sql < sql/03_assignee_portfolio.sql
```

A dry run reports what the query *would* read without running it, and costs
nothing. In the web console the same figure appears at the top right before you
press Run.

**BigQuery charges by how much data a query reads, counted per column**, not by
how many rows come back. Reading a column you do not need costs real money.
Stop and reconsider anything above about 100 GB, and never select
`claims_localized` or `description_localized`: either would consume a month's
allowance in one query. See `README_COST.md`.

## Step 4: run the three queries

| File | Returns | Measured cost |
|---|---|---|
| `01_patent_core.sql` | Owner, patent class, dates, citations and family, for the Orange Book patents | 74.0 GB |
| `02_forward_citations_and_family.sql` | How often each patent is later cited, and how many countries it was filed in | 28.5 GB |
| `03_assignee_portfolio.sql` | Each company's portfolio, year by year | 22.1 GB |

```bash
for q in 01_patent_core 02_forward_citations_and_family 03_assignee_portfolio; do
  sed 's/YOUR_PROJECT/your-project-id/g' "sql/$q.sql" \
    | bq query --nouse_legacy_sql --format=csv --max_rows=1000000 --quiet \
    > "data/patents/$q.csv"
done
```

Rename the outputs to `patent_core.csv`, `forward_citations_family.csv` and
`assignee_portfolio.csv`.

**Query 3 matters most.** It is the only patent measure that exists for every
trial, including drugs that were never approved. That is what keeps the study
from drawing conclusions by looking only at successes.

## Step 5: build the features and re-run the analysis

```bash
python scripts/prep/prep_13_patents.py    # patent results to per-trial measures
python scripts/prep/prep_11_ip_index.py data/analysis_ready
python scripts/analysis/interim_eda.py    # rewrites docs/interim_results.json
```

`prep_13` prints how much of the study it could measure. Expect about 64% of
industry-sponsored trials. University and government sponsors mostly have no
measurable portfolio, which for them is closer to correct than wrong.

## If something comes back empty

Two failures have happened in this project, both silent:

**A filter that matches nothing.** Query 02 originally filtered on
`country = 'US'` in the research table. That table stores country *names*, so
the value is "United States" and the filter matched zero rows. Every citation
count came back empty while the query reported success.
`02a_diagnose_research_country.sql` shows what that field actually contains and
costs almost nothing to run.

**A search term that matches too much.** Terms built from ordinary words behave
badly. `MEDICA` matched 1,884 owners including Toshiba Medical and Olympus
Medical; `INNO` matched 3M Innovative Properties and LG Innotek. The rule is to
count every search term against the returned dictionary before trusting it. A
term matching hundreds of owners is wrong by definition.
