# How BigQuery charges, and how to avoid a surprise bill

## The one rule

**BigQuery charges by how much data your query reads, counted per column.** It
does not charge by how many rows come back.

This is the opposite of what most people expect. A query returning three rows
can cost more than one returning three million, if it touches a bigger column.
Selecting a column you do not need costs real money.

The free allowance is **1 TiB of data processed per month**, which is about
1,100 GB. That is generous, but two careless queries can spend it.

## Which columns are expensive

The patent table `patents-public-data.patents.publications` is large, and some
columns are very large.

| Column | What it holds | Cost | Use it? |
|---|---|---|---|
| dates, numbers, identifiers | small scalar values | very low | yes |
| `assignee_harmonized`, `cpc`, `ipc` | owner names, patent classes | low | yes |
| `citation` | the patents this one cites | moderate | yes, if you need the count |
| `abstract_localized` | the abstract text | high | only if genuinely needed |
| `claims_localized` | the full legal claims | **very high** | avoid |
| `description_localized` | the full patent description | **extreme** | **never** |

A single query touching `claims_localized` or `description_localized` can
consume an entire month's allowance.

## Always check the estimate before you run

Every query in this folder should be estimated first. A dry run reports what a
query *would* read without actually running it, and costs nothing.

From the command line:

```bash
bq query --dry_run --nouse_legacy_sql < 03_assignee_portfolio.sql
```

In the web console, the estimate appears at the top right as
"This query will process X" before you press Run.

**Stop and reconsider anything above about 100 GB.**

## What the queries in this project actually cost

Measured, not estimated:

| Query | Processed |
|---|---|
| Name discovery (`00`) | 7.1 GB |
| Patent core (`01`) | 74.0 GB |
| Citations and family (`02`) | 28.5 GB |
| Company portfolio (`03`) | 22.1 GB |

Query 01 is the most expensive because it reads the `citation` column. That
column is not used by any feature in the analysis, so it could be dropped to
cut the cost by roughly two thirds. It is kept because re-running later to add
it would cost more than keeping it now.

## Measuring how broad a patent claim is

The standard way to measure claim breadth is to count the words in the first
independent claim: broader claims tend to be shorter. That needs
`claims_localized`, which is too expensive here.

Two alternatives:

1. Use `google_patents_research.publications.top_terms`, which is small, as a
   measure of technology scope instead of claim length.
2. Fetch claims only for the final set of patents from a separate source.

**A note on the second option.** This project previously recorded PatentsView
as that source. That is no longer possible: its API host no longer resolves,
and its public bulk download returns a permission error. The replacement, the
USPTO Open Data Portal, requires a registered access key. Anyone picking this
up should treat claim breadth as not currently measurable without that
registration.

Whichever route is taken, record it in the methods section, because it changes
what the claim-breadth variable actually means.
