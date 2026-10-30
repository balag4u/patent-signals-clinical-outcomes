# Project guide

A walkthrough for someone opening this project for the first time: what the
research asks, which data answers it, how that data was built, and what the
answer turned out to be.

No background in statistics or machine learning is assumed. Terms are explained
where they first appear.

---

## 1. The question

**The business problem.** A Phase III trial can cost hundreds of millions of
dollars, and roughly one drug in ten entering clinical testing ever reaches
approval. Most of that money is spent on programmes that fail. Companies decide
which programmes to fund largely on expert judgement, with no calibrated
estimate of the risk.

**The idea being tested.** Companies patent their science *before* trials
begin. So a sponsor's patent position is visible at the exact moment a funding
decision is made. That makes it a **leading indicator**, something you can see
in advance, rather than hindsight. Nobody had tested whether it predicts
whether a drug survives development.

**The question.** Does a sponsor's patent position predict whether its clinical
trial is stopped early, and does the answer differ by disease area?

### What is being measured

| | |
|---|---|
| **One row is** | One interventional Phase II or Phase III drug trial |
| **Time window** | Trials starting 2008 to 2019 |
| **What we predict** | Was the trial terminated, withdrawn or suspended, or did it complete? |
| **What we predict from** | Patent position, trial design, regulatory pathway, sponsor history |
| **Sample** | 39,437 trials with a known outcome, of which 22.17% were terminated |

*Interventional* means the researchers assign the treatment, rather than
observing what patients already take.

### The four research questions

1. **RQ1.** Do sponsors with strong patents stop trials at a different rate
   than sponsors with weak patents?
2. **RQ2.** How well can termination be predicted from what is known at trial
   start, and which pieces of information matter most?
3. **RQ3.** Is a broader patent position related to how long a trial takes to
   finish?
4. **RQ4.** Does the patent relationship differ between disease areas?

**Why this is a business project rather than a biology project.** The unit of
study is the *programme*, not the molecule. The output is a decision-support
score for portfolio managers, not a drug.

### What the answer turned out to be

**Patents do not help.** Adding the company-level patent measures to the
prediction model changes its accuracy by +0.0018, with a p-value of 0.24, and
in the tuned final model the patent measures together add +0.0017, with a
p-value of 0.46. A p-value is the chance of seeing a result this large if there
were really no effect, so values this high are what pure noise looks like.

Trial size and sponsor experience carry the signal instead. The number of sites
a trial registers is the strongest single predictor.

Section 5 explains why an earlier version of the patent measure appeared to
show an effect, and why that appearance was misleading. That explanation is
arguably the most useful thing the project produced.

---

## 2. The datasets and how they connect

Ten sources. Each answers one part of the chain from **patent** to **trial** to
**approval** to **market** to **safety**.

| # | Source | What it contributes | Raw size |
|---|---|---|---|
| 1 | **ClinicalTrials.gov API v2** | The outcome, and every trial-design predictor. 106,311 Phase II and III drug trials | 44 MB |
| 2 | **AACT** | Disease categories, used to form the six groups for RQ4 | 2.5 GB |
| 3 | **FDA Orange Book** | Patents and exclusivity for conventional drugs. 22,303 patent-to-product links | 8 MB |
| 4 | **FDA Purple Book** | Biologic medicines: 860 applications, 251 biosimilars | 0.5 MB |
| 5 | **Drugs@FDA** | Regulatory pathway: priority review, orphan status, new-drug classification | 41 MB |
| 6 | **openFDA** | The official substance registry, used as the spine for matching drug names | 87 MB |
| 7 | **FAERS** | Reported side effects, 46 quarters from 2015 to 2026 | 2.8 GB |
| 8 | **Open Targets** | Genetic evidence, and the synonym list that decodes company code names | 962 MB |
| 9 | **Medicaid** | How much of each product was actually dispensed, over 12 years | 5.1 GB |
| 10 | **Google Patents on BigQuery** | The patent measures. Queried in place, not downloaded | about 100 GB |

A few of those names:

- **AACT** is a public copy of the trial registry kept by the Clinical Trials
  Transformation Initiative, used here because it carries disease
  classifications the main registry does not expose.
- **FAERS** is the FDA Adverse Event Reporting System, the database where
  suspected side effects are reported.
- **Biologic** means a medicine made from living cells, such as an antibody,
  rather than manufactured by chemistry.
- **Biosimilar** is the biologic equivalent of a generic.

The written reports count **eight** sources rather than ten, because two of these
do not feed the analysis directly: the openFDA substance registry serves only
the drug-name matching, and Medicaid is retrieved but used in no model. FAERS is
also kept as context rather than as a predictor. Reports exist only for drugs
already on the market, which repeats the approval problem described in section
5, and the number of reports grows with sales and company size, so a safety
burden is not comparable between a large and a small sponsor.

### How they join

```
                    ClinicalTrials.gov trial
                              |
                  drug name, as free text
                   "DAPAGLIFLOZIN 10 MG"
                              |
                 [ matching step, section 4 ]
                              |
                     FDA ingredient name
                              |
                   Drugs@FDA application
                     /        |        \
            Orange Book   Purple Book   FAERS
            (patents)     (biologics)   (safety)
                     \        |        /
                       Medicaid (uptake)

        SEPARATELY, and this is the main patent measure:

           trial sponsor -> patent owner -> Google Patents
           (works for EVERY trial, not only approved drugs)
```

**Why there are two patent routes, and why it matters enormously.**

The Orange Book route only exists for drugs that were **approved**. If the
patent measures came only from there, every trial in the study would belong to
a drug that had already succeeded. The comparison would be winners against
winners, and the result would be meaningless.

So the **main** patent measure is taken at company level, through the patent
owner, which exists for every trial regardless of how it ended. The Orange Book
route is kept as a **checking sample**.

This distinction is not theoretical. Section 5 shows the two routes giving
opposite answers.

---

## 3. How the data was cleaned and prepared

Each script takes one raw source and produces one prepared table. Together they
reduce about 15 GB to 22 MB, by summarising away detail the analysis never
uses.

| Script | What it does | Output |
|---|---|---|
| `pull_ctgov.py` | Downloads the registry 1,000 trials at a time, saving the raw responses so the download can be audited | 107 JSON files |
| `prep_01_ctgov.py` | Flattens the nested records to one row per trial and derives the outcome | `ctgov_trials.parquet` |
| `prep_02_orangebook.py` | Counts patents per application, separating original compound patents from later method-of-use ones, and keeps the patent-to-application list | `orangebook_ip.parquet` |
| `prep_03_drugsatfda.py` | Extracts priority review, orphan designation and new-drug status | `drugsatfda_regulatory.parquet` |
| `prep_04_faers.py` | Removes duplicate safety reports, then computes how often each drug and side effect appear together relative to chance | `faers_*.parquet` |
| `prep_04b_faers_recompute.py` | Recomputes those measures from the saved counts, correcting a faulty first calculation | `faers_drug_burden.parquet` |
| `prep_04c_sponsor_safety.py` | Links safety burden to the trial sponsor through each trial's resolved ingredient | `faers_sponsor_burden.parquet` |
| `prep_05_medicaid.py` | Aggregates 56 million prescription rows to product-year totals | `medicaid_product_year.parquet` |
| `prep_06_mesh_areas.py` | Groups trials into six disease areas for RQ4 | adds `therapeutic_area` |
| `prep_07_purplebook.py` | Parses biologic products and flags biosimilars | `purplebook_biologics.parquet` |
| `prep_08_entity_resolution.py` | Matches free-text drug names to official FDA ingredients | `trial_drug_resolution.parquet` |
| `prep_09_modality.py` | Classifies each trial as a conventional drug or a biologic | adds `modality` |
| `prep_10_sponsor_assignee.py` | Groups sponsors into parent companies and lists the names to search for in the patent data | `bigquery_assignee_names.csv` |
| `prep_11_ip_index.py` | Combines the patent measures into one score for the RQ1 split | `ip_index.parquet` |
| `prep_12_assignee_crosswalk.py` | Checks which real patent-owner names belong to which company | `bigquery_assignee_verified.csv` |
| `prep_13_patents.py` | Turns the patent query results into per-trial measures, dated to each trial's start year | `sponsor_ip_features.parquet` |
| `prep_14_genetic_support.py` | Joins each trial's drug to the gene it acts on, and that gene to its human genetic evidence | `genetic_support.parquet` |

### Four cleaning decisions that changed the answer

These are not housekeeping. Each would have produced a wrong result if missed.

**(a) The window closes at 2019, not 2023.**
Trials that are stopped reach their ending quickly; trials that finish take
years. So recent years look artificially bad. The share of trials with a known
outcome falls from 92.6% for 2008 starts to 34.8% for 2023 starts, which made
the termination rate appear to climb from 20.8% to 33.5%. That climb is an
illusion created by incomplete follow-up. Closing at 2019 leaves 82.8% of
trials resolved.

**(b) The enrolment field was thrown out.**
The registry records how many patients a trial *actually* enrolled, and a
stopped trial has few precisely *because* it stopped. The median is 23 patients
for stopped trials against 86 for completed ones. Used as a predictor it
reaches an AUC of 0.74, which looks impressive and is entirely circular. Among
the few records still showing the *planned* figure it reaches 0.48, which is no
signal at all.

A predictor that secretly contains the answer is called **leakage**. A model
built on one tests well and fails in real use, because at prediction time that
information does not exist yet.

**(c) Orange Book patents were being counted twice.**
Category totals were summed across product rows while the overall total counted
each patent once, and one patent is listed against 3.15 products on average.
The result was a ratio above 1.0, which is impossible. Counting is now done per
patent.

**(d) Safety is measured by disproportionality, not by counts.**
FAERS does not record how many people took each drug. A widely used medicine
collects more reports simply because more people take it, so a raw count
measures popularity rather than danger. Instead the pipeline asks whether a
drug and a side effect appear together more often than chance would predict.

---

## 4. Matching drug names, and proving the match is right

### The problem

The registry stores drug names as free text typed by trial staff. The same
molecule appears as a brand name, a generic name or an internal code, often
with the dose attached:

```
DAPAGLIFLOZIN 10 MG              dose attached
AL-4943A OPHTHALMIC SOLUTION     company code plus formulation
EXPERIMENTAL: PLACEBO            the arm label leaked into the field
TAK-438                          internal code, no public name
```

Nothing joins to FDA records without tidying this first, and **no published
lookup table exists**, which is exactly why the problem is hard.

### The approach: five stages, strictest first

| Stage | Method | Matches | Example |
|---|---|---|---|
| 1 | **exact**, the tidied name equals a known ingredient | 19,874 | `PEMBROLIZUMAB` |
| 2 | **synonym**, a public list decodes company codes | 7,024 | `TAK-438` becomes VONOPRAZAN |
| 3 | **token**, a known ingredient sits inside the phrase | 5,989 | `IVT AFLIBERCEPT` becomes AFLIBERCEPT |
| 4 | **salt forms** reconciled | 31 | `ZOLEDRONATE` and ZOLEDRONATE DISODIUM |
| 5 | **fuzzy**, guarded typo correction | 81 | `AMANTADIN` becomes AMANTADINE |
| | unresolved | 6,438 | obscure codes, probiotics, procedures |

**Result: 83.7% matched to an ingredient, 49.5% to a specific FDA
application.**

### Two rules that were removed for being wrong

It is easy to raise the match rate and easy to fool yourself doing it. Two
stages were cut after inspection:

- A prefix rule matched a general term to an arbitrary specific product:
  `INSULIN` became "INSULIN DEGLUDEC AND INSULIN ASPART", and
  `N-ACETYLCYSTEINE` became "N-ACETYLCYSTEINE ETHYL ESTER", **a different
  compound**. Removed entirely.
- Fuzzy matching turned `STATIN` into `STATINE`, a drug class into an amino
  acid. It now requires a longer name, a higher similarity threshold and a
  close length match.

Synonym lookup uses exact matching only, because partial matching turns
`APATINIB` into `LAPATINIB`, two different drugs.

### Proving the match rate is accurate

How many matched is counted automatically. **How many matched correctly cannot
be**, because there is no answer key. A person has to read a sample and judge
it.

A sample of 200 links was drawn and judged by hand. The sample design matters:
drawing at random would have included almost no fuzzy matches, teaching nothing
about the riskiest method. So risky methods were deliberately over-sampled,
then weighted back to their true share when the score was computed.

**Result: precision 0.979**, with a confidence interval of 0.963 to 0.996. A
confidence interval is the range the true value is likely to lie in.

To repeat it, see `data/validation/HOW_TO_ADJUDICATE.md`, then run:

```bash
python scripts/analysis/score_precision.py data/validation
```

If a method scores below 0.85, fix the rule, re-run the matcher and **draw a
fresh sample**. Re-scoring the same sample after changing the rules would be
circular.

---

## 5. The patent measure, and the trap inside it

### Matching sponsors to patent owners

Trial registries record a sponsor name. Patents record a legal owner. The two
rarely match, and the patent database abbreviates and sometimes reverses what
it stores:

| Written by hand | What the database actually holds |
|---|---|
| `ELI LILLY AND CO` | `LILLY CO ELI` |
| `PFIZER INC` | `PFIZER` |
| `ABBOTT LABORATORIES` | `ABBOTT LAB` |

So searching for exact company names fails. When tried, Novartis returned 8,724
patents while Eli Lilly returned 3 and Pfizer returned 2.

The approach is to search for distinctive **word fragments**, which survive
abbreviation, and then check every match offline where retrying is free. Three
traps, all found in the real data:

- **People share surnames with companies.** Over a hundred patent owners are
  individuals named Takeda.
- **Different companies share a name.** Schering AG of Berlin went to Bayer;
  Schering Corporation of New Jersey became part of Merck. Unrelated firms.
- **Ordinary words are not company names.** Searching for ORION matched Orion
  Energy Systems and Orion Engineered Carbons.

Every search term is counted against the results before being trusted. A term
matching hundreds of owners is wrong by definition.

Coverage: **64.3% of industry-sponsored trials**. Non-industry sponsors are
left unmeasured by design: only commercial assignee names were searched, so a
university's or a hospital's own portfolio was never looked up. Universities do
hold patents, so an empty value here means unmeasured rather than absent, and
coding it as weak would manufacture a finding.

### How patent strength is scored

RQ1 needs two groups, because a two-group comparison demands them. RQ2 to RQ4
keep the measures separate, since combining them throws away detail that was
expensive to collect.

Five dimensions, with the ones that do not simply track company size carrying
more weight:

| Dimension | How it is measured | Weight |
|---|---|---|
| Quality | how often later patents cite this one | 1.0 |
| Breadth | how many countries the invention is filed in | 1.0 |
| Term | years of protection remaining at trial start | 1.0 |
| Focus | share of the portfolio in medicine classes | 1.0 |
| Scale | how many patents the company holds | **0.5** |

Scale counts half because a raw patent count is largely a measure of company
size, and company size is something this study has to hold constant rather than
measure twice.

Two preparation steps, each with a reason:

- **Extreme values are capped** at the 1st and 99th percentile, because patent
  counts are heavily skewed and a few giants would otherwise set the scale.
- **Measures are standardised within trials that started in the same year**,
  because citations accumulate over time and a 2009 patent would otherwise look
  stronger than a 2018 one purely from having existed longer.

The **evergreening ratio is deliberately left out**. Evergreening means filing
later, narrower patents to extend protection. A high share can mean
sophisticated lifecycle management, or it can mean the original patent was too
weak to rely on. A measure that could point either way would corrupt a strength
score, so it is kept as a separate predictor.

**Missing is not weak.** A trial whose sponsor cannot be measured is
unmeasured, not weakly protected. Coding it as zero would invent a finding, so
those trials leave the comparison and the exclusion is reported.

> **Current state: two of the five dimensions are built at sponsor level,
> focus and scale.** Term is designed but cannot yet be computed for a sponsor
> from the extracted patent data, and quality and breadth exist only at drug
> level so far. A sponsor is scored only when both built components are present,
> and the script reports the missing dimensions rather than letting the score
> look complete.

### The trap, and why it matters most

Run the same RQ1 comparison on the two patent routes and they disagree:

| Patent measure | Who can be measured | Difference in stop rate | p-value |
|---|---|---|---|
| Orange Book, drug level | only drugs that won approval | **-3.64 points** | 0.0000001 |
| Company portfolio | every sponsor in the list | **-0.11 points** | 0.95 |

The company-level p-value allows for trials run by the same sponsor being
related rather than independent pieces of evidence (section 6).

The first looks like a strong finding. It is not, because of **who can be
measured at all**. The Orange Book lists patents only for drugs that already
won FDA approval. A drug abandoned in Phase II never appears there, however
many patents its owner holds. So that measure exists only for drugs that
already succeeded, and the comparison is winners against winners.

Judging a group by looking only at its survivors is called **survivorship
bias**. The company-level measure needs no approval, because a company's
patents exist whether or not a particular drug reaches the market.

This is why the company-level measure was specified from the start, and why the
drug-level result is reported as a checking sample rather than a finding.

### How far the null has been tested

A null is only worth reporting if it can survive the obvious objections. Four
were put to it, in order, each answering a different one.

| Objection | What was done | Result |
|---|---|---|
| The measure covers too few companies | Widened from 71 corporate groups to 184, and from 149 search names to 736, taking industry coverage from 56.4% to 64.4% and adding 1,634 trials | No change |
| The measure is too crude | Added six further patent indicators, including the accepted stand-in for claim breadth, co-ownership, inventing-team size, prior art, prosecution length, and biosimilar competition for biologics | No change; the claim-breadth measure ranks 45th of 46 features |
| The measure is biased towards the null | Retrieved the patents of twelve acquired companies that were routed to their parent for trial matching but never searched for in the patent data, which had understated the most acquisitive and therefore largest firms. 8,822 patents recovered | No change |
| Patents are the wrong signal, and the design cannot detect any signal | Built human genetic evidence for the gene each trial's drug acts on, the strongest rival predictor in the literature, reaching 62.4% of the frame against 32.2% for the patent measure | Also null: termination runs 22.9%, 20.2%, 23.8%, 24.5% across quartiles of evidence, and the block changes held-out AUC by -0.0050, p = 0.006, an interval wholly below zero |

The third objection was the serious one. An error that understates the
portfolios of the biggest companies drags any real effect towards zero, which
is the direction of the reported finding. Removing it was the only way to say
the null is not self-inflicted.

The fourth is the one that bounds how the null should be read. Nelson et al.
(2015) and Minikel et al. (2024) found that drugs aimed at a genetically
supported target reach approval about twice as often as drugs without one. If
that signal had shown up here, the patent null would simply mean patents are
the wrong variable. It does not show up, on better coverage than the patent
measures themselves, so the finding is wider than patents: what is being
predicted appears not to depend on the science or the commercial position
behind a drug.

Two limits apply to that fourth test, and both are stated in the report.
The outcome is different, since those studies predict approval while this
predicts whether one trial stops early. And the measure is looser, since it
asks whether a gene has evidence for any disease rather than for the disease
being treated: 99.8% of linked targets qualify on that definition, so the
yes-or-no form of the variable is almost constant and only the continuous
scores enter the model. A looser measure of a real effect should still show
part of it, so this is a conservative test rather than a void one.

What remains is a difference of -0.11 percentage points. Allowing for trials
being grouped within 170 sponsors, its 95% confidence interval runs from -3.54 to
+3.32, and the smallest difference the comparison could detect four times in
five is 4.9 points. A five-point effect, the size the study was designed to
find, is ruled out; a smaller one is not. The
estimate sits on either side of zero depending on which companies are measured
while staying equally far from significance, which is how an estimate behaves
when the quantity it estimates is zero.

What does predict termination is operational: the number of sites a trial opens
and how reliably its sponsor has finished trials before are the top two
features by a wide margin.

This does not rule out an effect of patent **quality** or **geographic breadth**
at company level, which are not yet built, and 35.6% of industry trials still
have no measurable sponsor portfolio. Nor does it close the two sharper tests:
patent breadth read from the claim text, and genetic evidence matched to the
trial's own disease. Each is the tighter form of a measure that gave a null in
its looser form.

---

## 6. How the sample size was worked out

Each research question needs a different statistical test, and each test needs
a different minimum number of trials. The study has to be big enough for **all
four**, so the requirement is the largest of the four.

Everything is anchored on a **measured** termination rate of 0.2217, that is
8,742 stopped out of 39,437, rather than an assumed one. Every calculation uses
a 5% significance level and 80% power, meaning a real effect of the stated size
would be found four times in five.

| RQ | Test | Why that test | Minimum | Available |
|---|---|---|---|---|
| RQ1 | Two-group comparison of rates, enlarged for clustering | Compares two group rates; trials of one sponsor are related | **9,786** | 12,712 |
| RQ2 | Power to detect a gain in AUC between two models scored on the same trials | The patent question is whether one model beats another | 3,753 | 12,717 test trials |
| RQ3 | Schoenfeld formula, for each of the two ways a trial can end | Survival analysis is driven by the number of events | 2,847 | 12,658 |
| RQ4 | Precision within each disease area, plus power for the difference between areas | Needs both a precise rate per area and enough data to compare areas | 6,504 | 12,712 |

**Requirement: 9,786 usable trials, set by RQ1.** "Usable" means counted
after every exclusion, inside the group of trials each question is actually
tested on, not the raw download.

**Why RQ1 sets the bar.** Trials run by the same sponsor are related: they
share the sponsor's patent position, its management and its funding, so 100
trials from one company carry less information than 100 trials from 100
companies. The size of that loss is measured from the data. Outcomes within a
sponsor are slightly alike (an intraclass correlation of 0.0445), but sponsors
run many trials each (72.9 on a size-weighted average), and together those
inflate the requirement by a factor of 4.20. Each group needs 4,893 trials, and
each holds 6,356.

**A correction to earlier versions.** The synopsis and the interim report used
the one-group form of the RQ1 formula, which gives half the true requirement:
583 trials per group instead of 1,165 before clustering. The RQ2 calculation
also changed. It used a rule of thumb, ten stopped trials per predictor, which
guards the stability of a model's coefficients but says nothing about power. It
now asks directly how many trials are needed to detect a gain of 0.01 in AUC,
the patent question RQ2 actually poses.

**The one shortfall.** Within the trials that can be measured on patents,
cardiovascular and infectious disease each hold fewer than the 542 trials per
patent group that the RQ4 comparison needs, so the disease-area result is
treated as exploratory.

Having four times the minimum overall is what lets the null result be stated
with some precision. For RQ1 the comparison could have detected a true gap of
4.9 percentage points and found 0.11. "We found no effect" and "we could not
have found one" look identical in a p-value and mean opposite things.

Reproduce the derivation any time; every intermediate number is written to
`docs/sample_size.json`:

```bash
python scripts/analysis/sample_size.py
```

---

## 7. Final-stage models and the scoring tool

`scripts/analysis/final_analysis.py` takes the analysis from preliminary models
to a selected, tested and deployable one.

**How the test is kept honest.** Four kinds of model are tried, each with a
small grid of settings, 32 combinations in all. Each is trained on trials that
started in 2008-2013 and judged on 2014-2015. The best setting of each kind is
then retrained on 2008-2015 and scored **once** on the 12,717 trials that
started in 2016-2019. The cut-off for flagging a trial and the correction to
its probability are also fixed on 2014-2015, so nothing about the test years
influences any choice.

| Model | AUC on its training data | AUC on the test years |
|---|---|---|
| Gradient-boosted trees (**selected**) | 0.746 | **0.669** |
| Random forest | 0.810 | 0.671 |
| Neural network (multilayer perceptron) | 0.690 | 0.631 |
| Penalised logistic regression | 0.631 | 0.619 |

Every model does better on the trials it was trained on than on new ones; that
gap is why only the test years count. The random forest edges the boosted model
by 0.002 on the test years, a difference random noise produces easily
(p = 0.43). The boosted model was chosen by the rule fixed in advance and is
also better calibrated.

**What the score delivers.** Ranked by predicted risk, the top tenth of test
trials were stopped 50.7% of the time, twice the 25.2% average, and the top
fifth contain 34.8% of all terminations. That is a triage tool: it tells a
reviewer where to look first, not which trial will fail.

**Why the probabilities are corrected.** The models give extra weight to stopped
trials during training so they do not ignore the rarer outcome. That inflates
every raw probability, to an average of 46.6% against 25.2% observed. One offset,
estimated on 2014-2015, pulls them back. The Brier score, the average squared
error of a predicted probability, falls from 0.222 to 0.174, better than the
0.191 of a forecast that ignores the trial altogether.

**What drives the score.** SHAP values split each prediction into the
contribution of each predictor. Trial design accounts for 58.4% of the total,
sponsor history 16.9%, and the patent and biosimilar measures 16.4%. The model
does use the patent measures, but removing them costs nothing, because the same
information is available from correlated sponsor and regulatory measures.

**The scoring tool.** `models/termination_model.joblib` holds the selected
model with its correction, cut-off and reference risk bands.
`scripts/deploy/score_trials.py` applies it to any table of trials and writes,
for each one, a calibrated risk, a risk band from 1 to 10, a review flag, and
the three predictors that moved its score most. Run on the worked example in the
final report, trial NCT03038477, it returns a risk of 39.4% in the top band,
driven by the sponsor's 62.5% past completion rate, a single site and long
eligibility criteria.

---

## 8. Running it

### Everything needed is already in the repository

```bash
git clone https://github.com/balag4u/patent-signals-clinical-outcomes.git
cd patent-signals-clinical-outcomes
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt

python scripts/analysis/final_analysis.py   # runs interim_eda.py first
python scripts/analysis/sample_size.py
```

That rebuilds every figure and statistic and rewrites the three files the
written reports read from: `docs/interim_results.json`,
`docs/final_results.json` and `docs/sample_size.json`. It takes about seven
minutes on a laptop processor, with no graphics card, no passwords and no
internet connection. `interim_eda.py` alone rebuilds the interim-stage results
in about three minutes.

Check the data loads as expected:

```bash
python -c "
import pandas as pd
d = pd.read_parquet('data/analysis_ready/ctgov_trials.parquet')
f = d[(d.start_year.between(2008,2019)) & (d.is_resolved==1)]
print(f'frame {len(f):,}  termination rate {f.is_terminated.mean():.4f}')"
# expect: frame 39,437  termination rate 0.2217
```

### Why the report reads from a file

Numbers typed into a document by hand drift the moment the analysis is re-run,
and afterwards nobody can tell which version of the code produced which figure.
So every statistic is written to one of the three results files and the
reports are built from them. If the analysis changes, the document changes with it, or it
does not change at all. The two cannot quietly disagree.

### Re-running the patent queries

Only needed if the company list changes. See `sql/RUNBOOK.md` for the full
procedure and `sql/README_COST.md` for how BigQuery charges.

The short version: BigQuery bills by **how much data a query reads**, counted
per column, so reading a column you do not need costs real money. Always check
the estimate before running, and never select the full-text patent columns,
which would consume an entire month's free allowance in one query.

---

## 9. What is not finished

Stated plainly, because a reader should not have to discover these.

- **The sponsor patent score uses two of five dimensions.** Term is not yet
  computable at sponsor level, and quality and breadth exist only at drug level.
- **Two predictors come from a 2026 snapshot.** Site count and eligibility
  length are read from the current registry record, not the protocol in force
  when each trial started. A trial that stopped early may never have opened
  every site it lists, so this is the most likely remaining leak.
- **Risk drifts over time.** After correction the model predicts 22.1% risk in
  the 2016-2019 test years against 25.2% observed, so its scores should be read
  as bands and the correction refreshed regularly.
- **RQ4 is short of data in two areas.** Cardiovascular and infectious disease
  hold fewer than the 542 trials per patent group the interaction test needs.
- **64.3% of industry trials have a measured sponsor portfolio.** The rest are
  recorded as unmeasured rather than zero.
- **Patent owners are matched by name.** The recognised alternative is a
  disambiguated owner identifier, published by PatentsView, whose public
  download route closed during this study. Accuracy was therefore checked by
  hand instead.
- **The registry over-represents high-income countries**, so findings should
  not be extrapolated to low- and middle-income settings.
- **Twenty-one of the 205 company groups match no patents at all.** For some,
  such as privately held firms, that is a real result. For others it may be a
  name the search did not find, and the two cannot currently be told apart.
