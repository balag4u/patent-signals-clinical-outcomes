# How each part works, and why it is built that way

The project has ten parts. This document explains the reasoning behind each
one. Read `README.md` first for what the project is and how to run it, and
`docs/PROJECT_GUIDE.md` for the full walkthrough. Read this when you want to
know *why* something is done the way it is.

| # | Part | Question it answers |
|---|---|---|
| 1 | [The study frame](#1-the-study-frame) | Which trials count, and why those |
| 2 | [Matching drugs to FDA records](#2-matching-drugs-to-fda-records) | How free text becomes a usable key |
| 3 | [Matching sponsors to patent owners](#3-matching-sponsors-to-patent-owners) | How a trial sponsor becomes a patent portfolio |
| 4 | [Fetching the patent data](#4-fetching-the-patent-data) | Why the data is queried, not downloaded |
| 5 | [Dating the portfolio](#5-dating-the-portfolio) | Why the year matters more than the total |
| 6 | [The patent strength score](#6-the-patent-strength-score) | How five measures become one |
| 7 | [Safety signals](#7-safety-signals) | Why counts of side effects are misleading |
| 8 | [Genetic evidence for the drug's target](#8-genetic-evidence-for-the-drugs-target) | How the strongest rival signal is measured and controlled for |
| 9 | [The models](#9-the-models) | Why these models and this validation |
| 10 | [Documentation](#10-documentation) | What is written down, and what generates itself |

---

## 1. The study frame

**What it is.** One row per interventional Phase II or Phase III drug trial
starting between 2008 and 2019, where the outcome is known. 39,437 trials, of
which 22.17% were terminated.

**Why the window closes at 2019.** Trials that are stopped reach their ending
quickly; trials that finish take years. Among trials that started recently, the
ones with a known outcome are therefore mostly the stopped ones. The share with
a known outcome falls from 92.6% for 2008 starts to 34.8% for 2023 starts, and
including those years makes the termination rate appear to climb from 20.8% to
33.5%. That climb is an artefact of how long we have been watching, not a real
trend. Closing at 2019 leaves at least six years of follow-up for every trial.

For the same reason, **calendar year is kept out of the predictors**. A model
given the start year could learn the artefact instead of the signal.

**Why the enrolment field is excluded.** The registry records how many patients
a trial *actually* enrolled, and a stopped trial has few precisely because it
stopped. The number contains the answer. On its own it separates stopped from
finished trials with an AUC of 0.74 where the registry holds the real figure,
but only 0.48 where it still holds the original plan, and 0.48 is nothing.

A predictor that secretly contains the outcome is called **leakage**. It makes
a model look accurate in testing and fail in use, because at the moment of
prediction that information does not exist.

`scripts/prep/prep_01_ctgov.py`

---

## 2. Matching drugs to FDA records

**The problem.** The registry stores drug names as free text typed by trial
staff: `DAPAGLIFLOZIN 10 MG`, `TAK-438`, `EXPERIMENTAL: PLACEBO`. FDA files use
standard ingredient names. **No published lookup table connects the two**,
which is why this is the hardest join in the project.

**The approach.** Five stages, strictest first: exact match, then a public
synonym list that decodes company code names, then looking for a known
ingredient inside a longer phrase, then reconciling salt forms, then guarded
typo correction. 83.7% match to an ingredient and 49.5% to a specific FDA
application.

**Why two rules were removed.** It is easy to raise the match rate and easy to
fool yourself doing it:

- A prefix rule turned `INSULIN` into "INSULIN DEGLUDEC AND INSULIN ASPART" and
  `N-ACETYLCYSTEINE` into "N-ACETYLCYSTEINE ETHYL ESTER", a **different
  compound**.
- Fuzzy matching turned `STATIN` into `STATINE`, a drug class into an amino
  acid.

**Why accuracy is checked by hand.** How many matched is counted
automatically. How many matched *correctly* cannot be, because there is no
answer key. A sample of 200 links was judged by a person, giving precision of
0.979. Risky methods were deliberately over-sampled so the sample says
something about them, then weighted back to their true share.

`scripts/prep/prep_08_entity_resolution.py`, `data/validation/`

---

## 3. Matching sponsors to patent owners

**The problem.** Trial registries record a sponsor. Patents record a legal
owner, called an **assignee**. The patent database abbreviates and sometimes
reverses what it stores, so `ELI LILLY AND CO` is held as `LILLY CO ELI` and
`ABBOTT LABORATORIES` as `ABBOTT LAB`. Searching for exact company names fails:
when tried, Novartis returned 8,724 patents while Eli Lilly returned 3.

**The approach.** Search for distinctive **word fragments**, which survive
abbreviation, then check every match offline where retrying costs nothing.

**Three things the matching has to get right:**

- **Group companies with their parents.** Genentech's patents belong to Roche
  and Janssen's to Johnson & Johnson. Without this a sponsor's portfolio is
  understated.
- **Date the acquisitions.** Wyeth's patents became Pfizer's in 2009. Since
  patents are measured as they stood on each trial's start date, a parent
  counts only from the year it bought the subsidiary.
- **Keep same-named firms apart.** Merck & Co of the United States and Merck
  KGaA of Germany separated in 1917 and are unrelated. Schering AG of Berlin
  went to Bayer while Schering Corporation of New Jersey went to Merck.

**Three traps found in the real data:**

- **People share surnames with companies.** Over a hundred patent owners are
  individuals named Takeda; others are named Roche, Lilly or Bayer.
- **Ordinary words are not company names.** Searching for ORION matched Orion
  Energy Systems and Orion Engineered Carbons. TRIS would have matched
  thousands of chemistry patents, because tris is a common laboratory buffer.
- **Large groups patent far outside medicine.** Mitsubishi Electric alone holds
  64,014 patents.

**The safeguard.** Every search term is counted against the returned results
before it is trusted. A term matching hundreds of owners is wrong by
definition. The script also stops with an error if any company on the list
could not possibly be found by the search, so a company never silently reads as
having no patents.

Result: 712 checked owner names across 184 companies, covering 64.4% of
industry-sponsored trials.

`scripts/prep/prep_10_sponsor_assignee.py`,
`scripts/prep/prep_12_assignee_crosswalk.py`

---

## 4. Fetching the patent data

**Why it is queried rather than downloaded.** The Google Patents public dataset
is around 100 gigabytes. The summary this project needs is a few megabytes, so
the work is done where the data already sits, on BigQuery, and only the summary
comes back.

**Why not PatentsView**, the obvious alternative with properly disambiguated
owner identifiers: its public download route closed during this study, and the
replacement requires a registered access key.

**The cost rule that matters.** BigQuery charges by **how much data a query
reads, counted per column**. Reading a column you do not need costs real money.
The full-text columns holding patent claims and descriptions must never be
selected: a single query touching them would consume an entire month's free
allowance.

**The three queries:**

| Query | Returns |
|---|---|
| `01_patent_core.sql` | Owner, patent class, dates, citations and family, for the Orange Book patents |
| `02_forward_citations_and_family.sql` | How often each patent is later cited, and how many countries it was filed in |
| `03_assignee_portfolio.sql` | Each company's portfolio, year by year |

The third matters most. It is the only patent measure that exists for **every**
trial, including drugs that were never approved, which is what keeps the study
from looking only at successes.

`sql/`, with `RUNBOOK.md` for the procedure and `README_COST.md` for charging

---

## 5. Dating the portfolio

**The principle.** A portfolio counted at today's size would say what the
company *became*, not what it was when the trial opened. That is leakage again,
and it is why the query returns a running total per company per year rather
than one total.

**How it works.** For each trial, the portfolio is read off as it stood in that
trial's start year. A company granted no patents in 2013 still owns everything
it owned in 2012, so the last known total is carried forward.

**Acquisitions are dated.** A subsidiary counts towards its parent only from
the year of the acquisition, so a trial starting in 2008 sees Pfizer without
Wyeth.

**Two measures, not one.** The total number of patents, and how many are
classified in the medicine classes. They are kept separate because they
disagree in a way that matters: Bayer holds 25,640 US patents but only 3,859
pharmaceutical ones, a 15% share, against 59% for Roche. Counting everything
would rank Bayer first on the strength of crop science and plastics.

`scripts/prep/prep_13_patents.py`

---

## 6. The patent strength score

**Why a single score exists at all.** RQ1 compares two groups, and a two-group
test needs two groups. RQ2 to RQ4 keep the measures separate, because
collapsing them into one number throws away detail that was expensive to
collect.

**Five dimensions**, with the ones that do not simply track company size
carrying more weight:

```
  Quality  how often later patents cite this one        weight 1.0
  Breadth  how many countries the invention is filed in  weight 1.0
  Term     years of protection remaining at trial start  weight 1.0
  Focus    share of the portfolio in medicine classes    weight 1.0
  Scale    how many patents the company holds            weight 0.5
```

**Why scale counts half.** A raw patent count is largely a measure of company
size. Big companies also run more trials and have more experience, so at full
weight the score would partly measure company size under another name.

**Two preparation steps, each with a reason:**

- **Extreme values are capped** at the 1st and 99th percentile. Patent counts
  are heavily skewed, and a few giants would otherwise set the scale for
  everyone.
- **Measures are standardised within trials that started in the same year.**
  Citations accumulate over time, so a 2009 patent would otherwise look
  stronger than a 2018 one purely from having existed longer.

**The evergreening ratio is deliberately excluded.** Evergreening means filing
later, narrower patents to extend protection on an existing drug. A high share
can mean sophisticated lifecycle management, or it can mean the original patent
was too weak to rely on. A measure that could point either way would corrupt a
strength score, so it is kept as a separate predictor instead.

**Missing is not weak.** A trial whose sponsor cannot be measured is
unmeasured, not weakly protected. Coding it as zero would invent a finding, so
those trials leave the comparison and the exclusion is reported alongside the
result.

**Current state: three of the five dimensions have data behind them.** Term,
focus and scale are built; quality and breadth exist only at drug level. The
script reports this rather than letting the score look complete.

`scripts/prep/prep_11_ip_index.py`

---

## 7. Safety signals

**Why counts would mislead.** FAERS, the FDA Adverse Event Reporting System,
does not record how many people took each drug. A widely used medicine collects
more reports simply because more people take it, so a raw count measures
popularity rather than danger.

**What is used instead.** Disproportionality: rather than counting reports, ask
whether a drug and a side effect appear together more often than you would
expect if they were unrelated. This follows Evans, Waller and Davis (2001), and
covers 4.08 million drug-event pairs across 46 quarterly releases.

**Three steps the result depends on:**

- **Remove duplicates.** One report is often resubmitted across many quarters
  with a rising version number; only the latest is kept.
- **Remove retractions**, using the deletion list published each quarter.
- **Count only suspect drugs.** A report lists everything the patient was
  taking. Medicines merely taken at the same time are not implicated and would
  water down every signal.

**Why safety attaches through the trial, not the report.** The organisation
filing a FAERS report is often a generics maker or distributor rather than the
company that ran the trial, so the link runs trial to ingredient to sponsor.

`scripts/prep/prep_04_faers.py`

---

## 8. Genetic evidence for the drug's target

**Why this is in the project at all.** Nelson et al. (2015) and Minikel et al.
(2024) found that a drug aimed at a gene human genetics has already tied to a
disease reaches approval about twice as often as a drug without that support.
That is a larger published effect than anything claimed for patents, and the
data is free. It enters here as a control: the patent measures have to earn
their contribution over and above the biology, not instead of it.

**How a trial is joined to a gene.** Four links, and the chain is only as
strong as its weakest one:

```
  trial  ->  FDA ingredient     83.7% of trials, from the drug matching
         ->  ChEMBL drug        matched on name, synonym or trade name
         ->  gene target        Open Targets mechanism of action
         ->  genetic evidence   Open Targets association scores
```

**Only human genetic sources count.** Open Targets scores each target and
disease pair separately for each kind of evidence. Nine sources are used:
genome-wide association studies, ClinVar submissions, rare variant burden
tests, PanelApp gene panels, curated developmental disorder genes, expert
gene-disease curation, rare disease curation, and curated literature and
sequence variants.

**Three sources are deliberately left out**, and the first matters most:

- **Clinical precedence** is derived from drugs already in clinical trials.
  Using it to predict trial outcomes would be circular, because the variable
  would already contain the answer.
- **Text mined literature** measures how much has been written about a target,
  not what the genetics shows.
- **Mouse knockouts** are not human genetics.

**A limitation stated plainly.** Nelson and Minikel match a target to the
specific disease being treated. This does not, because mapping the registry's
free-text conditions onto a disease ontology is a separate matching problem the
size of the drug matching already done. What is measured is whether the drug's
target has genetic evidence for **any** disease, which is a weaker claim: a
target with strong evidence in an unrelated condition scores as supported.

The consequence is visible in the output. 99.8% of linked targets qualify, so
the yes-or-no flag is almost constant and carries no information. It is excluded
from the model and only the continuous scores are kept.

That makes this a conservative test rather than a void one. If a weaker measure
had shown signal, a sharper one would be expected to show at least as much.

`scripts/prep/prep_14_genetic_support.py`

---

## 9. The models

**Two models, deliberately.** A penalised logistic regression as the simple
baseline, and gradient-boosted trees as the flexible learner. If the flexible
model does no better, that supports reporting the simple one. If it does, the
gap measures what the simple model misses.

**Why the split is by time, not at random.** Models are trained on trials
starting 2008 to 2015 and tested on 2016 to 2019. A random split would let the
model learn from trials that started *after* the ones it is tested on, which is
not available in real use.

**Why competing risks for the timing question.** A trial that is stopped can
never reach completion. Ordinary survival analysis would treat it as simply
unobserved, which assumes it would have finished given more time. That is
false, and it pushes the result towards the hypothesis being tested. So
completion and termination are modelled as two endings that rule each other
out.

**Why calibration is reported alongside accuracy.** A model can rank trials
correctly while stating the wrong probabilities. Ranking supports triage;
absolute risk statements need the numbers to be right as well.

**Why standard errors are clustered.** Trials of the same drug share a sponsor
and a patent position, so they are not independent pieces of evidence. Treating
them as independent would overstate how much is really known.

`scripts/analysis/interim_eda.py`

---

## 10. Documentation

```
  README.md                what the project is, what it found, how to run it
  docs/PROJECT_GUIDE.md    the full walkthrough
  docs/COMPONENTS.md       this file: why each part is built as it is
  docs/DATA_DICTIONARY.md  every column of every stored table
  docs/DATA_SOURCES.md     where each dataset comes from
  sql/RUNBOOK.md           how to run the patent queries
  sql/README_COST.md       how BigQuery charges, and how to avoid surprises
```

**The data dictionary generates itself** from the stored tables, by
`docs/gen_data_dictionary.py`, rather than being maintained by hand. A
hand-written one drifts away from the data the moment a column changes.

**Every reported number is produced by code.** The analysis writes every
statistic to `docs/interim_results.json`, and the written report reads from
that file. If the analysis changes, the document changes with it, or it does
not change at all. The two cannot quietly disagree.
