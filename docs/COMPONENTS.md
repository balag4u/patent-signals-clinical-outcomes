# Components

Eight subsystems make up the project. Each section explains what that part *is* and why
it is built that way. Read the README first for how to run things; read this for the
reasoning behind each piece.

| # | Subsystem | Covers |
|---|---|---|
| 1 | [Research pipeline](#1-research-pipeline) | Scope, frame and folder map |
| 2 | [Project guide](#2-project-guide) | Data sources and how they join |
| 3 | [Sponsor-to-assignee mapping](#3-sponsor-to-assignee-mapping) | Corporate rollup for patent matching |
| 4 | [IP strength index (RQ1)](#4-ip-strength-index-rq1) | The strong/weak split |
| 5 | [IP dimensions across RQ1-RQ4](#5-ip-dimensions-across-rq1-rq4) | Five dimensions, used separately in RQ2-RQ4 |
| 6 | [Documentation](#6-documentation) | Reference documentation |
| 7 | [Pharmacovigilance](#7-pharmacovigilance) | FAERS disproportionality signals |
| 8 | [Patent retrieval](#8-patent-retrieval) | BigQuery queries and inputs |

---

## 1. Research pipeline

*Research pipeline: do patent signals predict clinical trial termination?*

Walsh College DBA capstone (QM 640). Tests whether a pharmaceutical sponsor's
intellectual property position predicts whether their clinical trial terminates
early, alongside trial design, regulatory pathway and sponsor characteristics.

Unit of analysis : one interventional Phase II/III drug trial
Window           : trials starting 2008-2019, with a resolved outcome
Outcome          : terminated, withdrawn or suspended, versus completed
Analytic frame   : 39,437 trials; termination rate 22.17%
Required sample  : 4,422 (the maximum across RQ1-RQ4; RQ4 binds)

Contents:
```
  data/analysis_ready/  every analysis input as Parquet, 41 MB
  scripts/prep/         raw source to analysis table, one script per source
  scripts/analysis/     sample size derivation, precision sampling and scoring
  scripts/colab/        notebook executing RQ1-RQ4
  sql/                  BigQuery statements for patent retrieval
  docs/                 data dictionary and source catalogue
```

Raw archives (~15 GB) are not stored here; every one is re-downloadable from
the endpoints recorded in docs/DATA_SOURCES.md, and the prep scripts rebuild
all derived tables from them.

## 2. Project guide

*Project guide: how the ten data sources fit together*

A plain-language walkthrough for anyone opening this repository for the first
time: what the study asks, which dataset answers which part of it, how they
join, how the sampling requirement was derived, and what to run.

The central join problem is that no published crosswalk links ClinicalTrials.gov
intervention text to FDA drug records, so the guide sets out the resolution
strategy and its limits.

docs/PROJECT_GUIDE.md

## 3. Sponsor-to-assignee mapping

*Sponsor-to-assignee mapping for portfolio measurement*

Patents are the study's principal independent variable, and they attach to
corporate assignees rather than to the trial sponsor names the registry records.
This maps one to the other, producing 149 assignee search names across 71
corporate groups and covering 56.4% of industry trials in the frame.

Three properties the mapping has to hold:

- Corporate rollup. Genentech's patents belong to Roche and Janssen's to Johnson & Johnson, so a sponsor's portfolio is understated without it.

- Acquisition timing. Wyeth's patents became Pfizer's in 2009. Because IP is measured as of each trial's start date, a parent applies only from the year it acquired the subsidiary; 27 subsidiaries carry a parent_from_year.

- Merck Sharp & Dohme (US) and Merck KGaA (Germany) are unrelated firms that separated in 1917 and are kept strictly apart.

scripts/prep/prep_10_sponsor_assignee.py

## 4. IP strength index (RQ1)

*Composite intellectual-property strength index for RQ1*

RQ1 compares termination rates between strong-IP and weak-IP sponsors, which
requires two groups. RQ2-RQ4 keep the components separate, since dichotomising
discards information the data collection paid for.

Index construction:

- Components are standardised within trial-start-year cohort, because citation and patent counts accumulate with age; without this, an older patent registers as stronger purely through exposure time.

- Counts are winsorised at the 1st and 99th percentiles before standardising, as patent counts are heavily right-skewed.

- The evergreening ratio is excluded. A high secondary-patent share may mean sophisticated lifecycle management or a primary patent too weak to rely on, and a component of ambiguous sign would corrupt a strength measure. It is kept as a separate predictor.

- Trials whose drug carries no listed patent are unobserved, not weak. Coding them zero would manufacture a result; they are excluded and reported.

Orange Book patent counts are taken at patent level, since one patent is listed
against 3.15 products on average and row-level counting inflates them.

scripts/prep/prep_11_ip_index.py, scripts/prep/prep_02_orangebook.py

## 5. IP dimensions across RQ1-RQ4

*IP strength as five dimensions, and how each research question uses them*

Intellectual property strength is not one quantity. The index spans five
dimensions, with scale-independent measures carrying the weight because a raw
portfolio count is largely a proxy for company size:

```
  Quality  forward citations per patent          weight 1.0
  Breadth  INPADOC family size and country count weight 1.0
  Term     patent life remaining at trial start  weight 1.0
  Focus    share of portfolio in A61K/A61P       weight 1.0
  Scale    portfolio count                       weight 0.5
```

RQ1 uses the composite, because a two-proportion test needs two groups.
RQ2-RQ4 take the dimensions separately, where the models have the degrees of
freedom to use each one. RQ3 uses family size as a continuous breadth covariate
rather than a binary split.

The index reports which dimensions are present and refuses to be mistaken for
a complete measure while any are missing, since four of the five require the
BigQuery patent retrieval that has not yet been run.

scripts/prep/prep_11_ip_index.py, scripts/colab/QM640_Analysis.ipynb

## 6. Documentation

*Documentation: README, project guide, and generated data dictionary*

Reference material for a reader arriving without context.

```
  README.md               pipeline order, design decisions, how to run it
  docs/PROJECT_GUIDE.md   objective, joins, preparation, sampling, BigQuery plan
  docs/DATA_DICTIONARY.md every column of every stored table
  docs/DATA_SOURCES.md    the ten endpoints, with their access quirks
```

The data dictionary is generated from the stored Parquet files by
docs/gen_data_dictionary.py rather than maintained by hand, so it cannot drift
away from the tables it describes.

The README also records the design decisions a reader would otherwise have to
reverse-engineer: why the window closes at 2019 (outcome maturity), why
registry enrollment is excluded (it records actual enrollment, which encodes
the outcome), and why biologics need a different IP measure (the BPCIA imposes
no patent-listing duty, so no drug-level patent record exists).

## 7. Pharmacovigilance

*Pharmacovigilance: adverse-event disproportionality and sponsor safety burden*

FAERS has no exposure denominator, so a raw adverse-event count measures how
widely a drug is used rather than how dangerous it is. Signals are therefore
computed as disproportionality against the whole database, following Evans,
Waller and Davis (2001): PRR and ROR with a Yates-corrected chi-square, over
4.08 million drug-event pairs from 46 quarterly extracts, 2015-2026.

Three steps the analysis depends on:

- Case de-duplication across the full series. One case identifier recurs in many quarters with a rising version number, and only the latest is kept.

- Retracted cases are removed using each quarter's deletion list.

- Only suspect drugs count (primary or secondary). Concomitant medications are not implicated in the report and would dilute every signal.

PRR is unbounded where a cell is sparse, so summaries use the median and are
restricted to cells with at least three reports.

Sponsor burden is linked trial to ingredient to sponsor, not by FAERS reporter,
because the reporter is frequently a generics maker or distributor rather than
the company that ran the trial.

scripts/prep/prep_04_faers.py and companions

## 8. Patent retrieval

*Patent retrieval: BigQuery queries, runbook, and prepared inputs*

Patent data comes from the Google Patents public dataset on BigQuery, queried
in place rather than downloaded: roughly 100 GB of patent records yield a few
megabytes of features. PatentsView, the obvious alternative, now requires an
API key and its bulk endpoint is closed.

- 01_patent_core.sql                   assignee, CPC class, dates, citations, family, for the Orange Book patents 02_forward_citations_and_family.sql  citation impact and geographic breadth 03_assignee_portfolio.sql            sponsor portfolio by year - the measure that exists for every trial, including drugs never approved, and therefore the one free of survivorship bias

RUNBOOK.md gives the console steps; README_COST.md explains that BigQuery bills
by bytes scanned per column, so the full-text claims and description columns
must be left alone.

Inputs are prepared for direct use: 6,476 unique patent publication prefixes
(pediatric-exclusivity suffixes removed, reissue numbers retained) and the 149
assignee search names.

