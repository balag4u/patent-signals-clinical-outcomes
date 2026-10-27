# Where the data comes from

Ten sources. **All are open access**: none needs a university login, a paid
subscription or an institutional agreement. Anyone can download the same files.

The registry and FDA files were retrieved 24 to 26 September 2026. The patent
extraction and the Open Targets release were retrieved 26 October 2026. The raw downloads total about 15 GB and are
not stored in this repository, because they can be fetched again from the
addresses below and the scripts in `scripts/prep/` rebuild every prepared table
from them.

| Source | Where to get it | What it is used for |
|---|---|---|
| ClinicalTrials.gov API v2 | `https://clinicaltrials.gov/api/v2/studies` | The outcome being predicted, and the trial design measures |
| AACT | `https://aact.ctti-clinicaltrials.org/download` | Disease categories, used to form the six groups for RQ4 |
| FDA Orange Book | `https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files` | Patents and exclusivity for conventional drugs |
| FDA Purple Book | `https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/` | Biologic medicines and biosimilar status |
| Drugs@FDA | `https://www.fda.gov/drugs/drug-approvals-and-databases/drugfda-data-files` | Regulatory pathway and special designations |
| openFDA | `https://open.fda.gov/data/downloads/` | The official substance registry, used to standardise drug names |
| FAERS | `https://fis.fda.gov/content/Exports/faers_ascii_YYYYQn.zip` | Reported side effects |
| Open Targets | `https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/26.09/` | Genetic evidence, and the synonyms that decode company code names |
| Medicaid | `https://download.medicaid.gov/data/StateDrugUtilizationData-YYYY.csv` | How much of each product was actually dispensed |
| Google Patents | BigQuery `patents-public-data.patents.publications` | The patent measures |

Some of those names:

- **AACT** is a public copy of the trial registry maintained by the Clinical
  Trials Transformation Initiative. It is used only for its disease
  classification table, which the main registry does not expose.
- **FAERS** is the FDA Adverse Event Reporting System, where suspected side
  effects are reported.
- **Open Targets** is a public drug-target database run by EMBL-EBI and
  partners.

## Access problems that cost time to discover

Recorded so the next person does not lose the same hours.

- **`www.fda.gov` blocks automated downloads.** Scripted requests are served a
  bot-detection page instead of the file. The Orange Book and Drugs@FDA files
  have to be downloaded in a browser, or fetched with full browser-style
  request headers.
- **The Purple Book is not where its search page suggests.** Files are served
  from `accessdata.fda.gov/drugsatfda_docs/PurpleBook/<year>/`. Despite being
  labelled a monthly changes report, the file is the complete listing: only 58
  of 2,272 rows carry a change flag.
- **`data.cms.gov` rejects scripted clients** regardless of headers, so
  Medicare Part D would need a manual browser download. Medicaid is used
  instead. The two cover different populations, which is a limitation rather
  than a substitution.
- **AACT's server throttles heavily.** The ClinicalTrials.gov API is the faster
  route for trial records, so AACT is used only for its disease table.
- **NIH RePORTER does not support resuming an interrupted download**, so a
  failed transfer has to start again from the beginning.
- **PatentsView is no longer usable.** Its API host no longer resolves and its
  public bulk download returns a permission error. The replacement, the USPTO
  Open Data Portal, requires a registered access key. This is why patent data
  comes from BigQuery, and why patent owners are matched by name rather than by
  a disambiguated identifier.

## Limitations worth knowing before using this data

- **Medicaid hides small numbers.** 49.0% of rows are suppressed across 2015 to
  2026, rising from 47.0% to 50.7%. Suppression concentrates in low-volume
  products, so what is missing is not random: it is biased towards rare-disease
  drugs.
- **The trial registry over-represents high-income countries**, so findings
  should not be extrapolated to low- and middle-income settings.
- **FAERS has no denominator.** It records reports but not how many people took
  the drug, so only comparisons against the rest of the database are
  interpretable, never raw counts.
- **Orange Book patents exist only for approved drugs**: 1,348 of 27,428
  applications carry any patent listing. This is the single most important
  limitation in the project. It means the drug-level patent measure can only be
  computed for drugs that already succeeded, which is why the company-level
  measure is the primary one and the drug-level measure is a checking sample.
