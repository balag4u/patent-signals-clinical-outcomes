# Do a company's patents predict whether its drug trial gets stopped?

A DBA capstone project (Walsh College, QM 640). Everything here can be re-run
from scratch, and every number in the report is produced by code in this
repository rather than typed in by hand.

---

## The question, in plain terms

Drug companies spend enormous sums on Phase II and Phase III trials, and most
of those trials never lead to an approved medicine. This project asks whether
you can tell, on the day a trial opens, which ones are likely to be stopped
early.

The idea being tested is that a company's **patents** might be a clue. Patents
are filed before trials begin, so they are already visible when the funding
decision is made. Almost everything else that predicts failure only becomes
visible later, once the trial is already underway and the money is spent.

**What the study found: patents do not help.** Knowing how many patents a
sponsor holds, and how many of them are pharmaceutical, adds essentially
nothing to a prediction of whether its trial will be stopped. The details, and
why an earlier version of the measure suggested otherwise, are below.

## Some words you will meet

| Term | What it means here |
|---|---|
| **Terminated** | A trial stopped before it finished. This is the outcome being predicted |
| **Sponsor** | The organisation running the trial: a drug company, a university, a government institute |
| **Assignee** | The company that legally owns a patent. Usually not spelled the same as the sponsor name |
| **AUC** | How well a model separates two groups. It is the chance the model scores a stopped trial above a finished one, so 0.50 is a coin toss and 1.00 is perfect |
| **p-value** | The chance of seeing a result this large if there were really no effect. Small means unlikely to be luck |
| **Leakage** | When a predictor secretly contains the answer. A model built on one looks accurate in testing and fails in real use |
| **Phase II / Phase III** | The middle and late stages of human testing. Phase III is the largest and most expensive |

## What is being measured

**One row = one trial.** Specifically, one interventional Phase II or Phase III
drug trial that started between January 2008 and December 2019 and has a known
outcome. Interventional means the researchers assign the treatment rather than
just observing what patients already take.

- **39,437 trials** in the study, drawn from 106,311 retrieved
- **22.2%** of them were terminated
- The sample size calculation calls for 9,786 usable trials once trials are
  allowed to cluster within sponsors; see `docs/PROJECT_GUIDE.md`

## Running it yourself

```bash
git clone https://github.com/balag4u/patent-signals-clinical-outcomes.git
cd patent-signals-clinical-outcomes
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt

# every input the analysis needs is already committed - nothing to download
python scripts/analysis/final_analysis.py   # runs interim_eda.py first
python scripts/analysis/sample_size.py
```

`final_analysis.py` runs `interim_eda.py` and then the final-stage models, so
these two commands rebuild every figure and statistic in the reports and
rewrite the three files the reports are generated from:
`docs/interim_results.json`, `docs/final_results.json` and
`docs/sample_size.json`. They take about seven minutes on a four-thread laptop
processor, with no graphics card, no passwords and no internet connection.
Running `interim_eda.py` on its own, in about three minutes, rebuilds the
interim-stage results only.

To score trials with the saved model:

```bash
python scripts/deploy/score_trials.py INPUT.parquet OUTPUT.csv
```

The input needs the model's predictor columns, built exactly as
`interim_eda.py` builds them. The output gives each trial a calibrated risk, a
risk decile, a review flag, and the three predictors that moved its score most.

`requirements-lock.txt` pins the exact package versions the reported numbers
were produced with. `requirements.txt` gives the looser ranges that also work.

## What is in here

| Folder | What it holds |
|---|---|
| `data/analysis_ready/` | The prepared tables, 14 of them, 22 MB. **This is everything the analysis needs** |
| `data/patents/` | Results downloaded from Google BigQuery, plus the checked list of which patent owner belongs to which company |
| `data/validation/` | A 200-link sample checked by hand, used to measure how accurate the drug matching is |
| `scripts/prep/` | Sixteen scripts that turn raw downloads into the prepared tables |
| `scripts/analysis/` | Sample size calculation, the hand-checking tools, the interim analysis (`interim_eda.py`) and the final-stage models (`final_analysis.py`) |
| `scripts/deploy/` | `score_trials.py`, which scores new trials with the saved model |
| `models/` | The selected model with its recalibration offset, decision threshold and reference risk bands, 0.25 MB |
| `sql/` | The BigQuery queries that fetch patent data, with a cost guide |
| `docs/` | Written explanations, the data dictionary, the figures, and the three results files every reported number comes from |

**Raw source files are not stored here** (about 15 GB). Every one can be
downloaded again from the addresses in `docs/DATA_SOURCES.md`, and the scripts
in `scripts/prep/` rebuild the prepared tables from them.

## How the pipeline fits together

```
pull_ctgov.py                ClinicalTrials.gov       ->  raw trial records
prep_01_ctgov.py             raw records              ->  ctgov_trials
prep_02_orangebook.py        FDA Orange Book          ->  drug patents and exclusivity
prep_03_drugsatfda.py        Drugs@FDA                ->  regulatory pathway
prep_04_faers.py             FDA adverse events       ->  safety signals
prep_04b_faers_recompute.py  saved 2x2 counts         ->  corrected safety signals
prep_04c_sponsor_safety.py   trial -> ingredient      ->  sponsor safety burden
prep_05_medicaid.py          Medicaid spending        ->  product-year usage
prep_06_mesh_areas.py        disease classification   ->  therapeutic areas
prep_07_purplebook.py        FDA Purple Book          ->  biologic products
prep_08_entity_resolution.py trial text               ->  FDA ingredient
prep_09_modality.py          intervention type        ->  small molecule or biologic
prep_10_sponsor_assignee.py  sponsor name             ->  patent-owner names
prep_11_ip_index.py          patent measures          ->  combined patent score
prep_12_assignee_crosswalk.py BigQuery owner names    ->  checked company list
prep_13_patents.py           BigQuery patent results  ->  per-trial patent features
prep_14_genetic_support.py   drug, gene, evidence     ->  per-trial genetic support
```

Steps 02 to 09 are independent of each other and can run in any order after 01.
Steps 10 to 13 depend on 02, 03 and 08. Step 04b follows 04, and 04c needs 04b,
08 and 10. The safety tables are kept as context: they are not model inputs.

---

## Three findings that shaped the design

These are recorded because each one changed what the study does, not because
they are interesting trivia.

### 1. Looking at recent trials makes termination look worse than it is

Trials that get stopped reach their ending quickly. Trials that finish take
years. So among trials that started recently, the ones with a known outcome are
mostly the ones that were stopped.

The share of trials with a known outcome falls from 92.6% for 2008 starts to
34.8% for 2023 starts. Looking across the whole period makes the termination
rate appear to climb from 20.8% to 33.5%, which is an illusion created by how
long we have been watching.

**So the study window closes at 2019**, which leaves at least six years of
follow-up for every trial in it, and calendar year is kept out of the
predictors.

### 2. The enrolment field gives away the answer

The registry records how many patients a trial **actually** enrolled, not how
many it planned to. A trial that was stopped has few patients precisely because
it was stopped. The number contains the outcome.

The evidence is clear. Enrolment on its own separates stopped from finished
trials with an AUC of **0.74** where the registry holds the actual figure, but
only **0.48** where it still holds the original plan, and 0.48 is nothing at
all. Planned enrolment carries no signal; achieved enrolment carries the
answer.

**The field is excluded from every model.**

### 3. Biologic drugs have no patent record to find

US law requires patents to be listed for conventional small-molecule drugs but
imposes no equivalent duty for biologics, which are made from living cells.
The result is visible in the data: **zero** biologic trials appear in the
Orange Book patent file, against 14.9% of small-molecule trials.

**So a company-level patent measure is the only one that works across both
kinds of drug**, and the drug-level measure is kept as a checking sample
rather than the main one.

---

## What the analysis shows

Models are trained on trials that started 2008 to 2015 and tested on 2016 to
2019. Splitting by time rather than at random matters: a model is only useful
if it works on trials it has not seen, in a period it was not trained on.

| What the model is given | AUC |
|---|---|
| Trial design only | 0.637 |
| plus sponsor track record | **0.659** |
| plus regulatory pathway | 0.662 |
| plus patents | 0.664 |

**The number of sites a trial registers is the strongest single predictor**,
followed by the sponsor's past completion rate and the length of the
eligibility criteria. The highest-placed patent measure, the sponsor's
portfolio size, ranks eleventh of 46 features.

Adding the company-level patent block moves AUC by **+0.0018, p = 0.24**, and
adding every patent block together moves it +0.0019, p = 0.39. Neither
interval excludes zero, so neither change can be told apart from random noise.
Only the sponsor's track record adds a clear gain, +0.0218.

### Why an approval-based measure appeared to show an effect

Measured from the FDA Orange Book, strongly protected drugs looked less likely
to be stopped: a gap of 3.64 percentage points with a p-value of 0.0000001.

That measure cannot be trusted, because of **who can be measured at all**. The
Orange Book lists patents only for drugs that already won FDA approval. A drug
abandoned in Phase II never appears there, however many patents its owner
holds. So the measure exists only for drugs that already succeeded, and the
comparison is winners against winners.

Judging a group by looking only at its survivors is called **survivorship
bias**. The company-level measure needs no approval, because a company's patent
portfolio exists whether or not any particular drug reaches the market. On that
measure the gap is **-0.11 percentage points, p = 0.95**, once the fact that
trials run by the same sponsor are not independent pieces of evidence is
accounted for, which is no effect at all.

This is why the study was designed with a company-level measure from the start.

## How far the null has been tested

A null result is only worth reporting if it can survive the obvious objections.
Four were put to it, in order, each answering a different one.

**First: is the null an artefact of measuring too few companies?**
The measured company list was widened from 71 corporate groups to 184, and from
149 search names to 736. Coverage of industry-sponsored trials rose from 56.4%
to 64.4%, adding 1,634 trials to the comparison. The patent contribution did
not move.

**Second: is the null an artefact of too crude a patent measure?**
Six further patent indicators were added, each already standard in the patent
economics literature: how many technology classes a patent is filed under,
which is the accepted stand-in for how broad its claims are; whether it is
co-owned, which signals a partnership or licence; the size of the inventing
team; how much earlier work it builds on; how long the patent office took to
grant it; and, for biologics, how many biosimilar competitors the product
faces. The patent contribution still did not move, and the claim-breadth
measure ranks 45th of 46 features, contributing nothing.

**Third: is the null an artefact of a bias pointing towards it?**
Twelve acquired companies were being routed to their parent for trial matching
but had no name to look up in the patent data, so their patents were never
retrieved. This understates the portfolios of acquisitive companies, and the
most acquisitive companies are the largest, so the error dragged measured
strength down for exactly the firms expected to score highest. Retrieving them
added 8,822 patents, including 5,430 for one company alone. The patent
contribution did not move.

**Fourth: is the null an artefact of patents being the wrong signal entirely?**
This is a different kind of objection. The first three ask whether the patent
measure is good enough. This one asks whether the study could detect any real
signal at all, which is the question a null result has to answer.

The test is the strongest rival signal in the literature. Nelson et al. (2015)
and Minikel et al. (2024) found that drugs aimed at a gene that human genetics
has already tied to a disease reach approval about twice as often as drugs
without that support. That is a larger published effect than anything claimed
for patents, and the data behind it is free.

So it was built. Each trial's drug was matched to the gene it acts on, and that
gene to the genetic evidence it carries. The chain reached **62.4% of the study
frame**, nearly double the 32.2% the sponsor patent measure covers, which makes
it the best-covered variable in the project.

It does not predict termination either. Sorted into four groups from weakest to
strongest genetic evidence, the share of trials stopped runs **22.9%, 20.2%,
23.8% and 24.5%**: no gradient, and the strongest group stops slightly more
often than the weakest, which is the opposite of the expected direction. Added
to the model on top of every other block it changes held-out accuracy by
**-0.0050 AUC, 95% CI -0.0086 to -0.0015, p = 0.006**. The interval lies wholly
below zero, so the block does not merely fail to help: it measurably costs
accuracy on trials the model has not seen, which is what fitting noise does.

Two limits on that, because without them it reads as a contradiction of the
published work. **The outcome is different:** those studies predict whether a
drug eventually reaches approval, while this one predicts whether a single trial
is stopped early. A target can be well chosen and the trial still stop over
recruitment, dosing or money. **The measure is looser:** they match a gene to
the specific disease being treated, while this matches a gene to evidence for
any disease, because mapping the registry's free-text conditions onto a disease
ontology is a separate matching job the size of the drug matching already done.
The consequence showed up at once: 99.8% of linked targets qualify on the looser
definition, so the yes-or-no form of the variable is almost constant and was
left out of the model, leaving only the continuous scores.

That makes it a conservative test rather than a worthless one. A looser measure
of the same thing should show at least some of the effect if the effect is
there. It shows none, and the disease-matched version stays on the list of work
to do.

**A fault found while checking the fourth.** The sponsor-to-company matching was
attributing commercial portfolios to organisations that do not own them. The
cause is worth recording, because it is the same fault that was found earlier on
the patent-owner side and it will recur anywhere names are matched after
normalisation.

Normalisation strips corporate words so that "Pfizer Inc" and "Pfizer" match,
which is what makes the lookup work at all. The side effect is that a short
company name collapses to an ordinary English word: `SUN PHARMA` becomes `SUN`,
`ZEALAND PHARMA` becomes `ZEALAND`, `UNITED THERAPEUTICS` becomes `UNITED`.
Matched on a word boundary, those then claimed Sun Yat-sen University, the
University of Auckland in New Zealand, and the United States Department of
Defense. A separate key, `ONCOLOGY`, claimed every oncology co-operative group
and twelve unrelated oncology companies for Clovis.

Two rules now prevent it. A commercial portfolio is not attributed to a sponsor
the registry classifies as non-industry, with an explicit allow-list for a
company's own research arm; and the keys that were ordinary words have been
narrowed. Together these removed about 320 false attributions.

**This made the null cleaner, not weaker.** The gap between strongly and weakly
protected sponsors fell from 0.79 percentage points to 0.11, and the p-value
rose from 0.36 to 0.90, with standard errors at that stage clustered on the
FDA application rather than the sponsor. The small apparent gap was partly an artefact of
crediting universities with pharmaceutical companies' patents. A wrong value is
worse than a missing one: it puts a real number on the wrong trial, where a
missing value is simply left out of the test.

**What the four together establish.** The measure is now wider, richer and
free of its one known directional bias, the answer is the same each time, and
the rival signal the literature rates most highly does not predict this outcome
either.
The remaining estimate of the difference in stop rates is -0.11 percentage
points. Once trials are clustered within their 170 sponsor groups, its 95%
confidence interval runs from -3.54 to +3.32, and the smallest difference the
comparison could detect four times in five is 4.9 points. A five-point effect,
the size the study was designed to find, is ruled out; a smaller one is not. The estimate also sits on either side of zero depending on
which companies are measured, while staying equally far from significance,
which is how an estimate behaves when the quantity it estimates is zero.

**What the result points to instead.** The two strongest predictors in the model
are the number of sites a trial opens and how reliably its sponsor has finished
trials before. Both are facts about how a trial is run, not about the science
behind the drug or the commercial position of the company running it. That is
the reading most consistent with the evidence: early termination looks
operational rather than scientific or commercial.

**What this does not rule out.** Patent strength is measured here from portfolio
size and pharmaceutical focus. A sponsor-level measure of patent
quality and geographic breadth is not yet built, 35.6% of industry trials still
have no measurable sponsor portfolio, and the two sharper measures named above,
patent breadth read from the claim text and genetic evidence matched to the
trial's own disease, are not yet done. Each is the tighter form of a measure
that produced a null in its looser form, so each could still change the
answer.

## Final-stage results

`scripts/analysis/final_analysis.py` adds the stage the final report rests on.
Every model setting is chosen on trials that started in 2014-2015, using models
trained on 2008-2013; the chosen settings are refitted on 2008-2015, and the
12,717 trials that started in 2016-2019 are scored **once**. The decision
threshold and the probability correction are also fixed on 2014-2015, so no
test result informs any choice.

| Model | AUC on its training data | AUC on the test years |
|---|---|---|
| Gradient-boosted trees (**selected**) | 0.746 | **0.669** (95% CI 0.658 to 0.680) |
| Random forest | 0.810 | 0.671 |
| Neural network (multilayer perceptron) | 0.690 | 0.631 |
| Penalised logistic regression | 0.631 | 0.619 |

The random forest scores 0.002 higher on the test years, which is not a real
difference (p = 0.43). The boosted model was selected by the rule fixed in
advance, the best score on 2014-2015, and it is also better calibrated and less
over-fitted.

- **Risk is concentrated.** Trials in the model's highest risk tenth were
  stopped 50.7% of the time, twice the test-period rate of 25.2%, and the top
  fifth contains 34.8% of all terminations.
- **Probabilities need correcting.** Training gives extra weight to stopped
  trials, which inflates every raw probability. One offset fixed on 2014-2015
  brings the Brier score, the average squared error of the predicted
  probability, from 0.222 to 0.174, below the 0.191 of a forecast that ignores
  the trial entirely.
- **Patents still add nothing.** In the tuned model the patent block moves AUC
  by +0.0017, 95% CI -0.0027 to +0.0060, p = 0.46.
- **Time to completion and disease area agree.** A Fine-Gray competing-risks
  model gives a completion ratio of 1.026 (95% CI 0.914 to 1.151) for strongly
  against weakly protected sponsors, and the test of whether the patent effect
  differs by disease area gives p = 0.35.

**Two corrections made at this stage.** First, every test on the sponsor patent
measure now allows for trials run by the same sponsor being related, by
clustering on the sponsor's corporate group; earlier versions clustered on the
FDA application, which is the right unit for the drug-level measure but not for
this one. The estimates did not move, but their intervals widened about 2.6
times. Second, the RQ1 sample size had used the one-group form of the formula,
which halves the requirement. Corrected, and allowing for clustering, the study
needs 9,786 usable trials; `docs/PROJECT_GUIDE.md` sets out every step.

## How patent strength is defined

The combined score uses five dimensions. The ones that do not simply track
company size carry more weight, because a raw patent count is largely a measure
of how big a company is.

| Dimension | How it is measured | Weight |
|---|---|---|
| Quality | how often later patents cite this one | 1.0 |
| Breadth | how many countries the invention is filed in | 1.0 |
| Term | how many years of protection remain at trial start | 1.0 |
| Focus | share of the portfolio in medicine classes | 1.0 |
| Scale | how many patents the company holds | **0.5** |

Why these choices:

- **Compare like with like by year.** Citations build up over time, so a 2009
  patent looks stronger than a 2018 one purely because it has existed longer.
  Each measure is standardised within the trials that started in the same year.
- **Trim the extremes.** Patent counts are heavily skewed, so values are capped
  at the 1st and 99th percentile before combining.
- **Leave out the evergreening ratio.** Evergreening means filing later,
  narrower patents to extend protection. A high share can mean sophisticated
  management, or it can mean the original patent was weak. A measure that could
  point either way would corrupt a strength score, so it is kept separate.
- **Missing is not weak.** A trial whose sponsor cannot be measured is
  unmeasured, not weakly protected. Coding it as zero would invent a finding.

**Current state: the sponsor-level score uses two of the five dimensions,
focus and scale.** Term is designed but cannot yet be computed at sponsor level
from the extracted patent data, and quality and breadth exist only at drug
level so far. A sponsor is scored only when both components are present, and
the script reports the missing dimensions rather than letting the score look
complete.

## Matching sponsors to patent owners

Trial registries record a sponsor name. Patents record a legal owner name. The
two rarely match, and BigQuery's owner field abbreviates and sometimes reverses
what it stores:

| Written by hand | What BigQuery actually holds |
|---|---|
| `ELI LILLY AND CO` | `LILLY CO ELI` |
| `PFIZER INC` | `PFIZER` |
| `ABBOTT LABORATORIES` | `ABBOTT LAB` |
| `F HOFFMANN LA ROCHE AG` | `HOFFMANN LA ROCHE` |

So searching for exact company names fails. The approach is to search for
distinctive **word fragments**, which survive abbreviation, then check every
match offline where trying again is free.

Three traps this has to avoid, each of which was found in the real data:

- **People share surnames with companies.** Over a hundred patent owners are
  individuals named Takeda; others are named Roche, Lilly or Bayer.
- **Different companies share a name.** Schering AG of Berlin went to Bayer;
  Schering Corporation of New Jersey became part of Merck. They are unrelated.
- **Ordinary words are not company names.** Searching for ORION matched Orion
  Energy Systems and Orion Engineered Carbons. Searching for TRIS would match
  thousands of chemistry patents, because tris is a common laboratory buffer.

Every search term is counted against the results before it is trusted. A term
matching hundreds of owners is wrong by definition.

Coverage: **64.3% of industry-sponsored trials** have a measured portfolio.
Non-industry sponsors are left unmeasured by design, because only commercial
assignee names were searched in the patent data. That is not a claim that they
hold no patents: universities do hold them, and US institutions have held title
to federally funded inventions since the Bayh-Dole Act of 1980. Their
portfolios were simply never looked up, so an empty value means unmeasured, not
absent.

## Matching trials to drugs

Registry drug names are free text typed by trial staff: `DAPAGLIFLOZIN 10 MG`,
`AL-4943A OPHTHALMIC SOLUTION`, `EXPERIMENTAL: PLACEBO`.
`prep_08_entity_resolution.py` matches **83.7%** of trials to an FDA ingredient
and **49.5%** to a specific FDA application.

Two matching methods were removed after checking, and the reasons generalise:

- A prefix rule mapped `INSULIN` onto "INSULIN DEGLUDEC AND INSULIN ASPART",
  and `N-ACETYLCYSTEINE` onto "N-ACETYLCYSTEINE ETHYL ESTER", a different
  compound.
- Fuzzy matching mapped `STATIN` onto `STATINE`, turning a drug class into an
  amino acid.

Accuracy is measured rather than assumed: a 200-link sample was judged by hand,
giving precision of **0.979**. See `data/validation/HOW_TO_ADJUDICATE.md`.

## Known limits

- The sponsor-level patent score uses **two of five** dimensions.
- Site count and eligibility length come from the 2026 registry snapshot, not
  the protocol in force when each trial started. A trial that stopped early may
  never have opened every site it lists, so this is the most likely remaining
  leak.
- After recalibration the model still under-predicts risk in the 2016-2019 test
  years (22.1% predicted against 25.2% observed), because the termination rate
  drifts upward over time. Its scores should be read as risk bands.
- **64.3%** of industry trials have a measured sponsor portfolio; the rest are
  recorded as unmeasured rather than zero, which matters because coding an
  unmeasured sponsor as weak would manufacture a finding.
- Patent owners are matched **by name**. The recognised alternative is a
  disambiguated owner identifier, published by PatentsView, whose public
  download route closed during this study.
- The registry over-represents high-income countries, so findings should not be
  extrapolated to low- and middle-income settings.

## Licence

Code: MIT. Data: every source is a US federal public-domain work or openly
licensed. No personal or patient-identifiable data is present; all records are
aggregate registry, regulatory or patent information.
