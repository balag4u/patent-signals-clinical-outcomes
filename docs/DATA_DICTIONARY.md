# Data dictionary

Generated from the analysis-ready tables. Types are as stored in Parquet.

## `ctgov_trials.parquet`

106,311 rows x 50 columns (8.45 MB)

| Column | Type | Non-null | Example |
|---|---|---|---|
| `nct_id` | object | 106,311 | NCT00421564 |
| `overall_status` | object | 106,311 | COMPLETED |
| `is_terminated` | float64 | 72,491 | 0.0 |
| `is_resolved` | int64 | 106,311 | 1 |
| `why_stopped` | object | 106,311 |  |
| `has_why_stopped` | int64 | 106,311 | 0 |
| `start_date` | datetime64[ns] | 105,308 | 2003-02-01 00:00:00 |
| `primary_completion_date` | datetime64[ns] | 100,603 | 2025-08-15 00:00:00 |
| `completion_date` | datetime64[ns] | 102,122 | 2004-12-01 00:00:00 |
| `study_first_post` | datetime64[ns] | 106,311 | 2007-01-12 00:00:00 |
| `results_first_post` | datetime64[ns] | 33,041 | 2019-12-26 00:00:00 |
| `has_results` | int64 | 106,311 | 0 |
| `phases` | object | 106,311 | PHASE2 |
| `is_phase3` | int64 | 106,311 | 0 |
| `enrollment` | float64 | 104,716 | 100.0 |
| `enrollment_type` | object | 101,155 | ACTUAL |
| `allocation` | object | 103,974 | RANDOMIZED |
| `is_randomized` | int64 | 106,311 | 1 |
| `intervention_model` | object | 103,190 | PARALLEL |
| `primary_purpose` | object | 105,744 | TREATMENT |
| `masking` | object | 104,056 | DOUBLE |
| `who_masked_n` | int64 | 106,311 | 0 |
| `n_arms` | int64 | 106,311 | 0 |
| `n_interventions` | int64 | 106,311 | 1 |
| `n_primary_outcomes` | int64 | 106,311 | 1 |
| `n_secondary_outcomes` | int64 | 106,311 | 1 |
| `elig_criteria_chars` | int64 | 106,311 | 872 |
| `elig_criteria_lines` | int64 | 106,311 | 14 |
| `sex` | object | 106,269 | FEMALE |
| `min_age` | object | 102,793 | 18 Years |
| `max_age` | object | 51,100 | 130 Years |
| `healthy_volunteers` | int64 | 106,311 | 0 |
| `n_locations` | int64 | 106,311 | 1 |
| `n_countries` | int64 | 106,311 | 1 |
| `is_multinational` | int64 | 106,311 | 0 |
| `lead_sponsor` | object | 106,311 | Chinese University of Hong Kong |
| `lead_sponsor_class` | object | 106,311 | OTHER |
| `is_industry` | int64 | 106,311 | 0 |
| `n_collaborators` | int64 | 106,311 | 0 |
| `drug_names` | object | 106,311 | DBT-Danggui Buxue Tang |
| `primary_drug` | object | 106,311 | DBT-DANGGUI BUXUE TANG |
| `conditions` | object | 106,311 | Menopause |
| `primary_condition` | object | 106,311 | Menopause |
| `countries` | object | 106,311 | China |
| `start_year` | float64 | 105,308 | 2003.0 |
| `months_to_primary_completion` | float64 | 100,436 | 11.14 |
| `therapeutic_area` | object | 106,311 | Other |
| `intervention_types` | object | 106,311 | DRUG |
| `is_biologic` | int64 | 106,311 | 0 |
| `modality` | object | 106,311 | Small molecule |

## `drugsatfda_regulatory.parquet`

29,351 rows x 18 columns (0.70 MB)

| Column | Type | Non-null | Example |
|---|---|---|---|
| `appl_no` | object | 29,351 | 000004 |
| `fda_appl_type` | object | 29,351 | NDA |
| `fda_sponsor` | object | 29,351 | PHARMICS |
| `fda_n_submissions` | float64 | 26,641 | 3.0 |
| `fda_n_priority` | float64 | 26,641 | 0.0 |
| `fda_any_priority` | float64 | 26,641 | 0.0 |
| `fda_is_nme` | float64 | 26,641 | 0.0 |
| `fda_n_efficacy_suppl` | float64 | 26,641 | 0.0 |
| `fda_has_rems` | float64 | 26,641 | 0.0 |
| `fda_first_action` | datetime64[ns] | 26,641 | 1969-07-16 00:00:00 |
| `fda_last_action` | datetime64[ns] | 26,641 | 1987-05-26 00:00:00 |
| `fda_n_orphan_designations` | int64 | 29,351 | 0 |
| `fda_ingredient` | object | 28,998 | HYDROXYAMPHETAMINE HYDROBROMIDE |
| `fda_drug_name` | object | 28,998 | PAREDRINE |
| `fda_form` | object | 28,998 | SOLUTION/DROPS;OPHTHALMIC |
| `fda_n_products` | float64 | 28,998 | 1.0 |
| `fda_has_orphan` | int64 | 29,351 | 0 |
| `fda_lifecycle_years` | float64 | 26,641 | 17.86 |

## `medicaid_product_year.parquet`

285,308 rows x 10 columns (7.30 MB)

| Column | Type | Non-null | Example |
|---|---|---|---|
| `product_norm` | object | 285,308 |  |
| `labeler_code` | int64 | 285,308 | 2 |
| `year` | int64 | 285,308 | 2015 |
| `units` | float64 | 285,308 | 0.0 |
| `scripts` | float64 | 285,308 | 0.0 |
| `reimbursed` | float64 | 285,308 | 0.0 |
| `n_rows` | int64 | 285,308 | 16 |
| `n_suppressed` | int64 | 285,308 | 16 |
| `n_states` | int64 | 285,308 | 1 |
| `log_reimbursed` | float64 | 285,308 | 0.0 |

## `orangebook_ip.parquet`

27,376 rows x 25 columns (0.49 MB)

| Column | Type | Non-null | Example |
|---|---|---|---|
| `appl_no` | object | 27,376 | 000004 |
| `ob_ingredient` | object | 27,376 | HYDROXYAMPHETAMINE HYDROBROMIDE |
| `ob_trade_name` | object | 27,376 | PAREDRINE |
| `ob_applicant` | object | 27,376 | PHARMICS INC |
| `ob_appl_type` | object | 27,376 | N |
| `ob_n_products` | int64 | 27,376 | 1 |
| `ob_approval_date` | object | 27,376 | Approved Prior to Jan 1, 1982 |
| `ob_n_patents` | int64 | 27,376 | 0 |
| `ob_n_primary_patents` | int64 | 27,376 | 0 |
| `ob_n_product_patents` | float64 | 1,336 | 0.0 |
| `ob_n_secondary_patents` | int64 | 27,376 | 0 |
| `ob_n_use_codes` | int64 | 27,376 | 0 |
| `ob_last_patent_expiry` | datetime64[ns] | 1,336 | 2041-07-18 00:00:00 |
| `ob_first_patent_expiry` | datetime64[ns] | 1,336 | 2041-07-18 00:00:00 |
| `ob_first_submission` | datetime64[ns] | 1,306 | 2023-09-21 00:00:00 |
| `ob_last_submission` | datetime64[ns] | 1,306 | 2024-07-31 00:00:00 |
| `ob_evergreen_ratio` | float64 | 1,336 | 9.0 |
| `ob_patent_span_years` | float64 | 1,336 | 0.0 |
| `ob_n_exclusivities` | int64 | 27,376 | 0 |
| `ob_last_exclusivity` | datetime64[ns] | 628 | 2026-07-13 00:00:00 |
| `ob_exclusivity_codes` | object | 628 | RTO |
| `ob_has_orphan_excl` | int64 | 27,376 | 0 |
| `ob_has_pediatric_excl` | int64 | 27,376 | 0 |
| `ob_has_nce_excl` | int64 | 27,376 | 0 |
| `ob_has_patent` | int64 | 27,376 | 0 |

## `purplebook_biologics.parquet`

2,271 rows x 33 columns (0.10 MB)

| Column | Type | Non-null | Example |
|---|---|---|---|
| `change_flag` | object | 2,271 | U |
| `applicant` | object | 2,271 | Merck Sharp & Dohme LLC |
| `bla_number` | object | 2,271 | 101066 |
| `brand_name` | object | 2,271 | Recombivax, Recombivax Hb |
| `proper_name` | object | 2,271 | Hepatitis B Vaccine (Recombinant) |
| `license_type` | object | 2,271 | 351(a) |
| `Strength` | object | 2,271 | 5UG/0.5ML |
| `dosage_form` | object | 2,271 | Injection |
| `route` | object | 2,271 | Intramuscular |
| `Product Presentation` | object | 2,271 | Single-Dose Vial |
| `marketing_status` | object | 2,271 | Rx |
| `licensure` | object | 2,271 | Licensed |
| `approval_date` | datetime64[ns] | 2,256 | 1986-07-23 00:00:00 |
| `Inter. Approval Date` | object | 2,271 |  |
| `ref_product_proper_name` | object | 2,271 |   |
| `Ref. Product Proprietary Name` | object | 2,271 |  |
| `supplement_no` | object | 2,271 | 0 |
| `submission_type` | object | 2,271 | Original |
| `Inter. Supplement Number` | object | 2,271 |  |
| `License Number` | object | 2,271 | 0002 |
| `Product Number` | object | 2,271 | 001 |
| `center` | object | 2,271 | CBER |
| `Date of First Licensure` | object | 2,271 |  |
| `Exclusivity Expiration Date` | object | 2,271 |  |
| `First Interchangeable Exclusivity Exp. Date` | object | 2,271 |  |
| `Ref. Product Exclusivity Exp. Date` | object | 2,271 |  |
| `Orphan Exclusivity Exp. Date` | object | 2,271 |  |
| `Patent List Provided` | object | 2,271 |  |
| `is_biosimilar` | int64 | 2,271 | 0 |
| `is_interchangeable` | int64 | 2,271 | 0 |
| `is_originator` | int64 | 2,271 | 1 |
| `proper_name_norm` | object | 2,271 | HEPATITIS B VACCINE (RECOMBINANT) |
| `applicant_norm` | object | 2,271 | MERCK SHARP & DOHME LLC |

## `trial_drug_resolution.parquet`

39,437 rows x 9 columns (0.98 MB)

| Column | Type | Non-null | Example |
|---|---|---|---|
| `nct_id` | object | 39,437 | NCT01730534 |
| `raw` | object | 39,437 | Dapagliflozin 10 mg |
| `norm` | object | 39,437 | DAPAGLIFLOZIN |
| `ingredient` | object | 39,437 | DAPAGLIFLOZIN |
| `appl_no` | object | 39,437 | 202293 |
| `method` | object | 39,437 | exact |
| `score` | float64 | 39,437 | 1.0 |
| `is_placebo_only` | bool | 39,437 | False |
| `is_combination` | int64 | 39,437 | 0 |
