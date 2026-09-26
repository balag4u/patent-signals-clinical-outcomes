# Patent Portfolio Signals as Predictors of Clinical Development Outcomes

Reproducible pipeline for a DBA capstone (Walsh College, QM 640) testing whether a sponsor's
intellectual property position predicts clinical trial termination, alongside trial design,
regulatory pathway and sponsor characteristics.

**Unit of analysis:** interventional Phase II/III drug trial, start date 2008–2019, resolved outcome.
**Analytic frame:** N = 39,437 trials · termination rate p = 0.2217 · required N = 4,422.

---

## Quick start

```bash
git clone https://github.com/<user>/qm640-capstone.git
cd qm640-capstone
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# every analysis input is already in data/analysis_ready/ - nothing to download
python -c "import pandas as pd; d=pd.read_parquet('data/analysis_ready/ctgov_trials.parquet'); print(d.shape)"
```

To run the analysis, open `scripts/colab/QM640_Analysis.ipynb` in Google Colab or Jupyter and
point `DATA` at `data/analysis_ready`.

## What is in this repository

| Path | Contents |
|---|---|
| `data/analysis_ready/` | Analysis-ready Parquet tables (17 MB). **This is all you need to reproduce the analysis.** |
| `data/validation/` | 200-link precision adjudication sample + scoring weights + instructions |
| `scripts/pull_ctgov.py` | Retrieves Phase II/III drug trials from the ClinicalTrials.gov API v2 |
| `scripts/prep/` | Nine reduction scripts, raw source → analysis-ready table |
| `scripts/analysis/` | Sample size calculation, precision sampling, precision scoring |
| `scripts/colab/` | Analysis notebook covering RQ1–RQ4 |
| `sql/` | BigQuery statements for Google Patents Public Data, with a cost guide |
| `docs/` | Data dictionary |

**Raw sources are not vendored** (~15 GB). Every one is re-downloadable from the endpoints in
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), and `scripts/prep/` regenerates the derived tables.

## Pipeline order

```
pull_ctgov.py            ClinicalTrials.gov API v2      ->  raw JSON pages
prep_01_ctgov.py         raw pages                      ->  ctgov_trials.parquet
prep_02_orangebook.py    Orange Book patent/exclusivity ->  orangebook_ip.parquet
prep_03_drugsatfda.py    Drugs@FDA submissions          ->  drugsatfda_regulatory.parquet
prep_04_faers.py         FAERS 46 quarters              ->  faers_*_.parquet  (PRR/ROR)
prep_05_medicaid.py      Medicaid SDUD 2015-2026        ->  medicaid_product_year.parquet
prep_06_mesh_areas.py    AACT MeSH ancestors            ->  therapeutic_area (RQ4 strata)
prep_07_purplebook.py    Purple Book                    ->  purplebook_biologics.parquet
prep_08_entity_resolution.py  trial text -> FDA ingredient  ->  trial_drug_resolution.parquet
prep_09_modality.py      intervention type + BLA link   ->  is_biologic / modality
```

Steps 02–09 are independent of one another and can run in any order after 01.

## Three findings that shaped the design

These are documented because they change results, not because they are interesting trivia.

**1. Right-censoring inflates the outcome rate.** The share of trials with resolved outcomes falls
from 92.6% (2008 starts) to 34.8% (2023 starts) — terminated trials resolve quickly, completed
ones take years. Restricting to resolved trials across the full period makes the termination rate
appear to climb from 20.8% to 33.5%, which is an artifact. **The window therefore closes at 2019**
(82.8% resolved) and calendar year is excluded from the predictor set.

**2. Registry `enrollment` is an outcome, not a predictor.** 98% of records carry *actual*
enrollment, and a terminated trial's actual enrollment is low *because it terminated*. Median is
11 participants for terminated trials against 86 for completed. Enrollment alone discriminates at
AUC 0.79; among the few records still reporting *estimated* enrollment it discriminates at 0.47,
i.e. not at all. **It is excluded from the model.**

**3. Biologics have no drug-level patent record.** Hatch-Waxman obliges Orange Book patent listing
for small molecules; the BPCIA imposes no equivalent duty on biologics. Empirically, zero
BLA-linked trials appear in the Orange Book patent file against 14.9% of small-molecule trials,
and the Purple Book's patent indicator is populated for 49 of 2,271 products with no patent
numbers. **Sponsor-portfolio measurement is therefore the only IP measure valid across both
modalities**, and the Orange Book block is a small-molecule validation subsample.

Leakage-free baseline (temporal split, train 2008–2015 / test 2016–2019):
gradient boosting **AUC 0.676**, penalised logistic **AUC 0.600**. This is the bar the patent
features must beat.

## Entity resolution

Registry intervention names are free text (`DAPAGLIFLOZIN 10 MG`, `AL-4943A OPHTHALMIC SOLUTION`,
`EXPERIMENTAL: PLACEBO`). `prep_08_entity_resolution.py` resolves **83.7%** of the frame to an FDA
ingredient and **49.4%** to an FDA application number, via exact → token → de-salt → Open Targets
synonym → guarded fuzzy matching.

Two methods were removed after a precision audit, and the reasons generalise:

- A `head` stage mapped `INSULIN` onto "INSULIN DEGLUDEC AND INSULIN ASPART" and
  `N-ACETYLCYSTEINE` onto "N-ACETYLCYSTEINE ETHYL ESTER" — a different compound. Dropped.
- Fuzzy matching mapped `STATIN` onto `STATINE`, a drug class onto an amino acid. It now
  requires length ≥ 6, ratio ≥ 0.93 and a length difference ≤ 3.

Synonym lookup uses **exact** matching only: substring matching maps `APATINIB` onto `LAPATINIB`.

Precision is established by human adjudication of a stratified 200-link sample — see
[data/validation/HOW_TO_ADJUDICATE.md](data/validation/HOW_TO_ADJUDICATE.md).

## Reproducing the sample size calculation

```bash
python scripts/analysis/sample_size.py
```

Prints the stepwise derivation for RQ1–RQ4 and the final decision
`N = max(1,166; 2,031; 811; 4,422) = 4,422` (binding constraint: RQ4).

## Licence

Code: MIT. Data: all sources are US federal public-domain works or open-licensed
(Open Targets, CC0). No human-subject data is present; all records are aggregate registry,
regulatory or bibliographic.
