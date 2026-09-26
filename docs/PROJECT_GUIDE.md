# Project guide

A plain-language walkthrough: what the research asks, what data answers it, how the data was
built, and what to do next.

---

## 1. The objective, in one page

**The business problem.** A Phase III trial can cost hundreds of millions of dollars. Roughly one
in ten drugs entering clinical testing ever reaches approval. Most of that money is spent on
programmes that fail. Firms decide which programmes to fund largely on expert judgement, with no
calibrated estimate of the risk.

**The idea.** Companies patent their science *before* trials begin. So a sponsor's patent position
is observable at the exact moment a funding decision is made. That makes it a **leading
indicator** rather than hindsight. Nobody has tested whether it predicts whether the drug survives
development.

**The question.** Does a sponsor's intellectual property position predict whether their clinical
trial terminates early — and does that hold across therapeutic areas?

**What is measured.**

| | |
|---|---|
| **Unit of analysis** | One interventional Phase II/III drug trial |
| **Time window** | Trials starting 2008–2019 |
| **Outcome (what we predict)** | Did the trial terminate, withdraw or suspend — or complete? |
| **Predictors** | IP position, trial design, regulatory pathway, sponsor history |
| **Sample** | 39,437 trials with a resolved outcome; 22.17% terminated |

**Four research questions.**

1. **RQ1** — Do strong-IP sponsors terminate trials at a different rate than weak-IP sponsors?
2. **RQ2** — How well can termination be predicted from information available at trial start?
3. **RQ3** — Does IP breadth relate to how long a trial takes to complete?
4. **RQ4** — Does the IP–outcome relationship differ by therapeutic area?

**Why this is a DBA project and not a biology project.** The unit is the *programme*, not the
molecule. The output is a decision-support score for portfolio managers, not a drug.

---

## 2. The datasets and how they fit together

Ten sources. Each answers one part of the chain **patent → trial → approval → market → safety**.

| # | Source | What it contributes | Size |
|---|---|---|---|
| 1 | **ClinicalTrials.gov API v2** | The outcome and all trial-design predictors. 106,311 Phase II/III drug trials | 44 MB |
| 2 | **AACT** (CTTI) | MeSH disease categories → the six RQ4 strata | 2.5 GB |
| 3 | **FDA Orange Book** | Small-molecule patents and exclusivity. 22,303 patent–product links | 8 MB |
| 4 | **FDA Purple Book** | Biologics: 860 BLAs, 251 biosimilars | 0.5 MB |
| 5 | **Drugs@FDA** | Regulatory pathway: priority review, orphan status, NME class | 41 MB |
| 6 | **openFDA** | UNII substance registry — the spine for drug-name normalisation | 87 MB |
| 7 | **FAERS** | Post-market safety, 46 quarters 2015–2026 | 2.8 GB |
| 8 | **Open Targets 26.09** | Genetic evidence, and drug synonyms that decode development codes | 962 MB |
| 9 | **Medicaid SDUD** | Commercial uptake, 12 years | 5.1 GB |
| 10 | **Google Patents (BigQuery)** | **The IP predictors. Not yet retrieved — see section 7** | queried, not downloaded |

### How they join

```
                    ClinicalTrials.gov trial  (nct_id)
                              |
                   intervention free text
                   "DAPAGLIFLOZIN 10 MG"
                              |
                    [ entity resolution ]         <- the hard part, section 5
                    UNII + Open Targets synonyms
                              |
                     FDA ingredient name
                              |
                  Drugs@FDA application (appl_no)
                     /        |         \
                    /         |          \
          Orange Book    Purple Book    FAERS
          (patents,      (biosimilar    (safety
           exclusivity)   status)        signals)
                    \         |          /
                     \        |         /
                      Medicaid (commercial uptake)

        SEPARATELY, and this is the primary IP measure:

              trial lead_sponsor  ->  patent assignee  ->  BigQuery
              (works for EVERY trial, not just approved drugs)
```

**Why two IP paths matter.** The Orange Book path only exists for drugs that got *approved*. If IP
variables came only from there, every trial in the dataset would belong to a drug that succeeded —
circular, and the model would be meaningless. So the **primary** IP block is measured at the
sponsor level via patent assignee, which exists for every trial regardless of outcome. The Orange
Book path is a **validation subsample**.

---

## 3. How the data was cleaned and prepared

Each script takes one raw source and emits one analysis-ready table. Together they reduce ~15 GB
to 17 MB — a 900-fold reduction — by aggregating away detail the analysis never uses.

| Script | Does what | Output |
|---|---|---|
| `pull_ctgov.py` | Pages the API, 1,000 trials at a time, saving raw JSON for reproducibility | 107 JSON pages |
| `prep_01_ctgov.py` | Flattens nested JSON to one row per trial; derives the outcome variable and trial duration | `ctgov_trials.parquet` |
| `prep_02_orangebook.py` | Counts patents per application; separates **primary** (composition-of-matter) from **secondary** (method-of-use) patents → an evergreening ratio | `orangebook_ip.parquet` |
| `prep_03_drugsatfda.py` | Extracts priority review, orphan designation, NME class per application | `drugsatfda_regulatory.parquet` |
| `prep_04_faers.py` | De-duplicates 20M safety reports, then computes PRR/ROR disproportionality | `faers_*.parquet` |
| `prep_05_medicaid.py` | Aggregates 56M prescription rows to product-year totals | `medicaid_product_year.parquet` |
| `prep_06_mesh_areas.py` | Maps trials to six MeSH disease strata for RQ4 | adds `therapeutic_area` |
| `prep_07_purplebook.py` | Parses biologics; flags biosimilar and interchangeable status | `purplebook_biologics.parquet` |
| `prep_08_entity_resolution.py` | Matches free-text drug names to FDA ingredients | `trial_drug_resolution.parquet` |
| `prep_09_modality.py` | Classifies each trial as biologic or small molecule | adds `modality` |

### Three cleaning decisions that changed the results

These are not housekeeping. Each one would have produced a wrong answer if missed.

**(a) The window closes at 2019, not 2023.** Terminated trials resolve fast; completed trials take
years. So recent years look artificially bad. The share of trials with a known outcome falls from
92.6% (2008 starts) to 34.8% (2023 starts), which made the termination rate appear to climb from
20.8% to 33.5%. That climb is an artifact of incomplete follow-up, not a real trend. Closing at
2019 gives 82.8% resolved.

**(b) Enrollment was thrown out.** The registry's enrollment field records how many patients
*actually* enrolled — and a terminated trial has few, *because it stopped*. Median 11 for
terminated trials versus 86 for completed. Used as a predictor it achieves AUC 0.79, which looks
impressive and is entirely circular. Among the few records still showing *planned* enrollment it
achieves 0.47 — no signal at all. Excluded.

**(c) Safety is measured by disproportionality, not counts.** FAERS has no denominator: a drug with
more reports may simply be more widely used. Raw counts are meaningless, so the pipeline computes
PRR and ROR against the whole database.

---

## 4. How the sampling works

This is the part the rubric weights most heavily (27.5 of 100 points).

**The logic:** each research question needs a different statistical test, and each test needs a
different minimum sample. The study must be powered for *all four*, so the final sample is the
**maximum** of the four requirements.

Everything is anchored on a *measured* termination rate of **p = 0.2217** (8,742 terminated of
39,437 resolved), not an assumed one.

| RQ | Test | Why that test | Minimum N |
|---|---|---|---|
| RQ1 | Two-proportion power analysis | Comparing two group rates | 1,166 |
| RQ2 | Events-per-variable | Model stability depends on events, not total N | 2,031 |
| RQ3 | Schoenfeld formula | Survival analysis is driven by number of events | 811 |
| RQ4 | Confidence-interval method | Needs precision *within* each of six strata | **4,422** |

**Final: N = max(1,166; 2,031; 811; 4,422) = 4,422.**

RQ4 binds, and that is informative in itself: estimating six subgroups precisely is far more
demanding than any single pooled test. A study powered only for main effects could not support
the subgroup claims practitioners most want.

**We have 39,437 trials — nearly 9× the requirement.** So 4,422 is a floor, not a target, and the
surplus funds held-out validation and sensitivity checks.

Reproduce it any time: `python scripts/analysis/sample_size.py`

---

## 5. Reliability and mapping

### The problem

The registry stores drug names as free text typed by trial sponsors. The same molecule appears as
a brand name, a generic name, or an internal code, with dose and route attached:

```
DAPAGLIFLOZIN 10 MG              <- dose attached
AL-4943A OPHTHALMIC SOLUTION     <- development code + formulation
EXPERIMENTAL: PLACEBO            <- arm label leaked into the field
NANOPARTICLE ALBUMIN-BOUND PACLITAXEL
TAK-438                          <- internal code, no public name
```

Nothing joins to FDA records without normalising this first. There is **no published crosswalk**,
which is exactly why the problem is hard.

### The solution: a five-stage ladder, strictest first

| Stage | Method | Matches | Example |
|---|---|---|---|
| 1 | **exact** — normalised name equals a known ingredient | 19,874 | `PEMBROLIZUMAB` |
| 2 | **synonym** — Open Targets decodes development codes | 7,024 | `TAK-438` → VONOPRAZAN |
| 3 | **token** — a known ingredient sits inside the phrase | 5,989 | `IVT AFLIBERCEPT` → AFLIBERCEPT |
| 4 | **desalt** — salt forms reconciled | 31 | `ZOLEDRONATE` ↔ ZOLEDRONATE DISODIUM |
| 5 | **fuzzy** — guarded typo correction | 81 | `AMANTADIN` → AMANTADINE |
| — | unresolved | 6,438 | obscure codes, probiotics, procedures |

**Result: 83.7% resolved to an ingredient; 49.4% to an FDA application number.**

### Two matching rules that were removed for being wrong

Recall is easy to inflate and easy to fool. Two stages were cut after inspection:

- A **`head`** stage matched a general term to an arbitrary specific product: `INSULIN` →
  "INSULIN DEGLUDEC AND INSULIN ASPART", and `N-ACETYLCYSTEINE` → "N-ACETYLCYSTEINE ETHYL ESTER",
  which is a *different compound*. Removed entirely.
- **Fuzzy matching** mapped `STATIN` → `STATINE` — a drug class onto an amino acid. It now
  requires length ≥ 6, similarity ≥ 0.93, and a length difference ≤ 3.

Synonym lookup uses **exact** matching only, because substring matching maps `APATINIB` onto
`LAPATINIB` — two different drugs.

### Proving precision

Recall is measured automatically. **Precision cannot be** — there is no truth file, so a human
must read a sample and judge it.

`data/validation/precision_sample_200.csv` holds 200 links awaiting judgement. The design matters:
a simple random sample would contain 0.4 fuzzy links, teaching nothing about the riskiest method.
So risky methods are deliberately **over-sampled**, then weighted back to their true population
share when precision is computed.

At an expected precision of 0.90, n = 200 gives a confidence interval of about **±4 percentage
points**.

To do it: follow `data/validation/HOW_TO_ADJUDICATE.md`, fill the `verdict` column with
CORRECT / PARTIAL / WRONG, then run:

```bash
python scripts/analysis/score_precision.py data/validation
```

If a method scores below 0.85, **fix the rule and re-run the resolver, then draw a fresh sample**.
Re-scoring the same sample after changing rules is circular.

---

## 6. What to do now

### On your Mac

Raw data lives at `/Volumes/Big256/DBA - Project Datasets` (~15 GB). Keep it. It is the archive,
and re-downloading is slow and partly rate-limited.

```bash
source ~/dba_venv/bin/activate          # Python 3.9 + pandas, sklearn, lifelines
cd ~/DBA_Capstone/patent-signals-clinical-outcomes
```

Outstanding on the Mac:
1. **FAERS prep is running** — finishes on its own, then produces three safety tables.
2. **Adjudicate the 200 links** (~2 hours). This is the one task nobody else can do.

### On GitHub

`https://github.com/balag4u/patent-signals-clinical-outcomes` — **private**.

> **Action required:** the rubric wants *open access*. A private repo scores zero if the grader
> gets a 404. Either add your mentor and grader as collaborators, or run
> `gh repo edit --visibility public` before submission.

Everyday use:

```bash
git add -A && git commit -m "message" && git push
```

### Running the build

Nothing needs re-downloading. The analysis inputs are in the repo.

```bash
# 1. verify the data loads and matches the synopsis
python -c "
import pandas as pd
d = pd.read_parquet('data/analysis_ready/ctgov_trials.parquet')
f = d[(d.start_year.between(2008,2019)) & (d.is_resolved==1)]
print(f'frame {len(f):,}  p_term {f.is_terminated.mean():.4f}')"
# expect: frame 39,437  p_term 0.2217

# 2. reproduce the sample size derivation
python scripts/analysis/sample_size.py

# 3. run the analysis
jupyter notebook scripts/colab/QM640_Analysis.ipynb
```

**For Colab:** upload `data/analysis_ready/` to Google Drive, open the notebook in Colab, and set
`DATA` to that folder. The extract is small enough to load in seconds.

### Week-by-week

| Week | Do |
|---|---|
| 2–3 | Adjudicate 200 links · set up Google Cloud · run BigQuery patent queries |
| 4–5 | Join patent features · exploratory analysis · missingness audit |
| 5–6 | RQ1 and RQ3 |
| 6–7 | RQ2: train, temporally validate, SHAP attribution |
| 7–8 | RQ4 moderation · subgroup equity audit · interim report |
| 9–11 | Presentation · final report · make repo public |

---

## 7. The patent data: Google BigQuery

### Why BigQuery and not a download

Patents are the **central independent variable** and the only major source not yet retrieved.

The obvious route, PatentsView, is closed: the legacy API was retired, the current Search API
requires a key, and the bulk S3 path returns 403. USPTO's own Open Data Portal also requires a key.

**Google Patents Public Data** is a free BigQuery public dataset covering worldwide patents —
assignees, classifications, citations, family members, claims. It needs no key and no download:
you query it where it sits and pull back only the summarised result. Roughly 100 GB of patent
data becomes a few megabytes of features.

### When you need it

**Weeks 2–3.** Not needed for the synopsis, which is finished. But RQ1 cannot run without it —
the "strong IP vs weak IP" split *is* the patent variable. Until then the notebook uses sponsor
prior-trial count as a stand-in, which is a proxy for company size, not IP.

### Setting it up (about 20 minutes, no credit card)

1. Go to `https://console.cloud.google.com` and sign in.
2. Create a project — call it `qm640-capstone`.
3. Open **BigQuery** from the left menu.
4. You are now in the **sandbox**: 1 TB of query processing free per month, no billing account.
5. Find the data: search `patents-public-data` in the Explorer panel, or open
   `https://console.cloud.google.com/bigquery?p=patents-public-data&d=patents`.

### The cost rule that matters most

**BigQuery bills by bytes scanned per column, not rows returned.** A careless `SELECT *` on this
table burns the monthly allowance in one query.

| Column | Cost | Use it? |
|---|---|---|
| dates, ids, numbers | very low | yes |
| `assignee_harmonized`, `cpc` | low | yes |
| `citation` (via `ARRAY_LENGTH`) | moderate | yes |
| `abstract_localized` | high | only if needed |
| `claims_localized` | **very high** | **no** |
| `description_localized` | **extreme** | **never** |

**Always dry-run first.** In the console, the editor shows "This query will process X" before you
run it. If X exceeds ~50 GB, stop and narrow the query.

### The three queries, and what each is for

In `sql/`, run in this order.

**`01_patent_core.sql` — patent attributes**
Input: the 7,079 Orange Book patent numbers in
`data/analysis_ready/orangebook_patent_numbers.txt`.
Returns per patent: assignee, CPC class, filing/priority/grant dates, backward citations, family
id, and years from priority to grant.
→ Feeds the drug-level IP block (the validation subsample).

**`02_forward_citations_and_family.sql` — impact and breadth**
Forward citations (how often later patents cite this one) as a quality proxy, and INPADOC family
size and country count as geographic breadth. Uses the pre-computed `cited_by` field in
`google_patents_research`, which avoids an expensive self-join.
→ Feeds `n_forward_citations`, `family_size`, `family_n_countries`.

**`03_assignee_portfolio.sql` — THE IMPORTANT ONE**
Returns, for each sponsor and each year, how many US patents they had been granted and how many
are pharmaceutical (CPC A61K/A61P/C07D/C12N), as a cumulative portfolio.
→ Feeds `assignee_portfolio_size`, **the primary IP variable**, measured *as of each trial's start
date* so there is no look-ahead.

This is the survivorship-safe measure: it exists for every sponsor whether or not their drug was
ever approved.

### The step that is not yet built

Query 3 needs a list of **patent assignee names**. Trial sponsors are recorded as
"Hoffmann-La Roche"; patents are assigned to "F. HOFFMANN-LA ROCHE AG". These must be matched —
a second entity-resolution problem, separate from the drug-name one.

The scale is manageable:

- 2,799 unique industry sponsors in the frame
- the **top 20 cover 34%** of industry trials
- the **top 200 cover 63%**

So: hand-curate aliases for the top ~200 sponsors, then fall back to fuzzy matching for the tail,
and record which trials got an exact versus fuzzy sponsor match so the distinction can be tested
in a sensitivity analysis. Budget half a day.

### Running and retrieving

1. Paste a query into the BigQuery editor.
2. Supply the input list — either upload `orangebook_patent_numbers.txt` as a table, or replace
   `@patent_list` with a literal array for a first test.
3. Check the dry-run estimate.
4. Run, then **Save results → CSV** (or to Drive if the result is large).
5. Put the CSV in `data/patents/` in the repo.
6. Write `prep_10_patents.py` to join it onto the trials table by `appl_no` (queries 1–2) and by
   harmonised sponsor name and year (query 3).

### Test it cheaply first

Before running against all 7,079 patents, run one query with five patent numbers. It costs almost
nothing and confirms the syntax, the join, and the output shape.

### What success looks like

Once joined, the analytic table gains roughly 10 IP columns. Then:

- **RQ1** becomes real: split sponsors on `assignee_portfolio_size` instead of the trial-count proxy.
- **RQ2** gets its IP block: the test is whether it beats the leakage-free baseline of **AUC 0.676**.
- **RQ3** uses `family_size` as the breadth measure in the survival model.
- **RQ4** tests whether any of it varies across the six therapeutic areas.

That comparison against 0.676 is the whole experiment. If patent features do not move it, that is
a finding worth reporting, not a failure.
