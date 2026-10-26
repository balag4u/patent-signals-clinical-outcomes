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
- The sample size calculation called for 4,422; see `docs/PROJECT_GUIDE.md`

## Running it yourself

```bash
git clone https://github.com/balag4u/patent-signals-clinical-outcomes.git
cd patent-signals-clinical-outcomes
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt

# every input the analysis needs is already committed - nothing to download
python scripts/analysis/interim_eda.py
```

That command rebuilds every figure and statistic in the report and rewrites
`docs/interim_results.json`. It takes about three minutes on a laptop, needs no
passwords and no internet connection.

`requirements-lock.txt` pins the exact package versions the reported numbers
were produced with. `requirements.txt` gives the looser ranges that also work.

## What is in here

| Folder | What it holds |
|---|---|
| `data/analysis_ready/` | The prepared tables, 20 MB. **This is everything the analysis needs** |
| `data/patents/` | Results downloaded from Google BigQuery, plus the checked list of which patent owner belongs to which company |
| `data/validation/` | A 200-link sample checked by hand, used to measure how accurate the drug matching is |
| `scripts/prep/` | Thirteen scripts that turn raw downloads into the prepared tables |
| `scripts/analysis/` | Sample size calculation, the hand-checking tools, and the main analysis |
| `sql/` | The BigQuery queries that fetch patent data, with a cost guide |
| `docs/` | Written explanations, the data dictionary, and the figures |

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
prep_05_medicaid.py          Medicaid spending        ->  product-year usage
prep_06_mesh_areas.py        disease classification   ->  therapeutic areas
prep_07_purplebook.py        FDA Purple Book          ->  biologic products
prep_08_entity_resolution.py trial text               ->  FDA ingredient
prep_09_modality.py          intervention type        ->  small molecule or biologic
prep_10_sponsor_assignee.py  sponsor name             ->  patent-owner names
prep_11_ip_index.py          patent measures          ->  combined patent score
prep_12_assignee_crosswalk.py BigQuery owner names    ->  checked company list
prep_13_patents.py           BigQuery patent results  ->  per-trial patent features
```

Steps 02 to 09 are independent of each other and can run in any order after 01.
Steps 10 to 13 depend on 02, 03 and 08.

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
| Trial design only | 0.636 |
| plus sponsor track record | **0.657** |
| plus regulatory pathway | 0.661 |
| plus patents | 0.664 |

**The number of sites a trial registers is the strongest single predictor**,
followed by the sponsor's past completion rate. Patent measures rank in the
lower half of 31 features.

Adding the company-level patent block moves AUC by **-0.0002, p = 0.93**. A
p-value that high means a difference this size is exactly what random noise
produces. Adding the drug-level and company-level blocks together moves it
+0.0027, p = 0.22, which is still not distinguishable from chance.

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
measure the gap is **+0.79 percentage points, p = 0.36** once the fact that
trials of the same drug are not independent pieces of evidence is accounted
for, which is no effect at all.

This is why the study was designed with a company-level measure from the start.

## How far the null has been tested

A null result is only worth reporting if it can survive the obvious objections.
Three were put to it, in order, each answering a different one.

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

**What the three together establish.** The measure is now wider, richer and
free of its one known directional bias, and the answer is the same each time.
The remaining estimate of the difference in stop rates is 0.79 percentage
points with a confidence interval from -2.12 to +0.53, against a sample able to
detect 1.89 points. The estimate also sits on either side of zero depending on
which companies are measured, while staying equally far from significance,
which is how an estimate behaves when the quantity it estimates is zero.

**What this does not rule out.** Patent strength is measured here from portfolio
size, pharmaceutical focus and remaining term. A sponsor-level measure of
patent quality and geographic breadth is not yet built, and 35.6% of industry
trials still have no measurable sponsor portfolio.

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

**Current state: the score uses three of the five dimensions.** Term, focus and
scale are built. Quality and breadth exist only at drug level so far, and the
script reports this rather than letting the score look complete.

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

Coverage: **64.4% of industry-sponsored trials** have a measured portfolio.
University and government sponsors mostly do not, which for them is closer to
correct than wrong, since they hold few pharmaceutical patents.

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

- The patent score uses **three of five** dimensions.
- **64.4%** of industry trials have a measured sponsor portfolio; the rest are
  recorded as unmeasured rather than zero.
- Patent owners are matched **by name**. The recognised alternative is a
  disambiguated owner identifier, published by PatentsView, whose public
  download route closed during this study.
- The registry over-represents high-income countries, so findings should not be
  extrapolated to low- and middle-income settings.

## Licence

Code: MIT. Data: every source is a US federal public-domain work or openly
licensed. No personal or patient-identifiable data is present; all records are
aggregate registry, regulatory or patent information.
