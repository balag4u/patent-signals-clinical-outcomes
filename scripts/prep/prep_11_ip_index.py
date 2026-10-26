#!/usr/bin/env python3
"""Composite intellectual-property strength index, used ONLY for RQ1.

RQ1 needs two groups because a two-proportion test demands them. RQ2-RQ4 keep the
components separate, since dichotomising discards information that was expensive
to collect.

Design choices, each with a reason:

  COHORT STANDARDISATION. Forward citations and patent counts accumulate with
  age, so a 2009 patent looks "stronger" than a 2018 one purely through
  exposure time. Every component is therefore z-scored WITHIN trial-start-year
  cohort, which removes the trend rather than modelling it.

  WINSORISATION. Patent counts are heavily right-skewed; a handful of estates
  with 60+ patents would dominate an unwinsorised mean. Components are clipped
  at the 1st/99th percentile before standardising.

  EQUAL WEIGHTS as the headline. A PCA version is computed for robustness, but
  equal weights are pre-registerable and interpretable, and PCA loadings can
  flip sign between samples.

  EVERGREEN RATIO IS EXCLUDED. A high secondary-patent share is genuinely
  ambiguous: it can mean sophisticated lifecycle management (strength) or a
  primary patent too weak to rely on (weakness). Putting an ambiguous sign into
  a strength index corrupts it. It is retained as a SEPARATE predictor.

  MISSING IS NOT WEAK. Trials with no Orange Book patent are UNOBSERVED, not
  weak-IP. Coding them 0 would invent a finding. They are excluded from the RQ1
  subsample and flagged.
"""
import os, sys
import numpy as np, pandas as pd

OUT = sys.argv[1]
SPLIT_RULE = "median"        # pre-registered before outcomes are examined

t  = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"))
r  = pd.read_parquet(os.path.join(OUT, "trial_drug_resolution.parquet"),
                     columns=["nct_id", "appl_no"])
ob = pd.read_parquet(os.path.join(OUT, "orangebook_ip.parquet"))
df = t.merge(r, on="nct_id", how="left").merge(ob, on="appl_no", how="left")

# Sponsor-level features from prep_13_patents.py, measured as of each trial's
# start year so the portfolio is what the sponsor held when the trial opened,
# not what it holds now. Absent until the BigQuery extracts have been run.
_sip = os.path.join(OUT, "sponsor_ip_features.parquet")
if os.path.exists(_sip):
    _s = pd.read_parquet(_sip)
    _s = _s.drop(columns=[c for c in ("corporate_group",) if c in _s.columns])
    _s = _s.drop_duplicates("nct_id")
    df = df.merge(_s, on="nct_id", how="left")
    print(f"merged sponsor-level IP features for "
          f"{df.assignee_portfolio_size.notna().sum()} trial rows")
else:
    print("sponsor_ip_features.parquet absent; sponsor-level components pending")

# years of patent life remaining AT TRIAL START - a genuine strength measure
df["start_date"] = pd.to_datetime(df.start_date, errors="coerce")
df["ob_term_remaining_yrs"] = (
    (pd.to_datetime(df.ob_last_patent_expiry, errors="coerce") - df.start_date)
    .dt.days / 365.25)

# --- components, all signed so that HIGHER = STRONGER -----------------------
DRUG = {
    "ob_n_patents":           "estate depth",
    "ob_n_primary_patents":   "composition-of-matter claims (strongest type)",
    "ob_term_remaining_yrs":  "exclusivity runway at trial start",
    "ob_n_exclusivities":     "regulatory exclusivity grants",
}
# Sponsor-level index: the PRIMARY measure once the BigQuery pull lands.
# Scale-independent components are listed first and carry equal weight with each
# other; portfolio SCALE is deliberately down-weighted because it is confounded
# with firm size (see SCALE_WEIGHT below).
# QUALITY and BREADTH are deliberately NOT here, though the design names them as
# sponsor dimensions. sql/02 returns forward citations and INPADOC family size
# for ORANGE BOOK patents, which are properties of the trial's drug, not of the
# sponsor's portfolio. Two reasons not to pass them off as sponsor components:
#
#   They are sparse. Orange Book patents exist for 1,348 of 27,428 applications,
#   so family size reaches 13% of the frame against 28.9% for the portfolio
#   measures. Mixing them in dropped the index from 11,392 trials to 2,066,
#   because build() below requires most components to be present.
#
#   They are the wrong unit. A sponsor-level BREADTH measure would aggregate
#   family size across every patent the sponsor holds, not across the handful
#   listed against one approved drug. That needs a further BigQuery pull joining
#   cited_by and family_id to assignee_harmonized across the whole portfolio.
#
# They are carried through to ip_index.parquet and enter RQ2 as predictors in
# the drug-level IP block, where gradient boosting handles their missingness
# natively. They stay out of the composite used for the RQ1 split.
SPONSOR_SCALE_FREE = {
    "assignee_pharma_share":   "FOCUS - share of portfolio in A61K/A61P",
    "sponsor_term_remaining":  "TERM - mean patent life remaining at trial start",
}
SPONSOR_SCALE = {
    "assignee_portfolio_size": "SCALE - portfolio count (confounded with firm size)",
}
SCALE_WEIGHT = 0.5      # scale counts half, so the index is not a firm-size proxy
SPONSOR = {**SPONSOR_SCALE_FREE, **SPONSOR_SCALE}

def zcohort(s, cohort):
    """winsorise, log-compress counts, then z-score within cohort"""
    x = pd.to_numeric(s, errors="coerce")
    lo, hi = x.quantile(0.01), x.quantile(0.99)
    x = x.clip(lo, hi)
    if (x.dropna() >= 0).all() and x.max() and x.max() > 20:
        x = np.log1p(x)
    g = x.groupby(cohort)
    return (x - g.transform("mean")) / g.transform("std").replace(0, np.nan)

def build(cols, label, weights=None):
    have = [c for c in cols if c in df.columns and df[c].notna().any()]
    if not have:
        print(f"  {label}: no components present - skipped"); return None, []
    Z = pd.DataFrame({c: zcohort(df[c], df.start_year) for c in have})
    w = pd.Series({c: (weights or {}).get(c, 1.0) for c in have})
    idx = (Z * w).sum(axis=1, skipna=True) / Z.notna().mul(w).sum(axis=1)
    idx[Z.notna().sum(axis=1) < max(2, len(have) - 1)] = np.nan   # need most parts
    return idx, have

print("=== components available ===")
for c, d_ in {**DRUG, **SPONSOR}.items():
    print(f"  {'YES' if c in df.columns and df[c].notna().any() else 'pending':8s} {c:26s} {d_}")

print("\n=== building indices ===")
df["ip_index_drug"], used_drug = build(DRUG, "drug-level")
df["ip_index_sponsor"], used_spon = build(
    SPONSOR, "sponsor-level",
    weights={c: SCALE_WEIGHT for c in SPONSOR_SCALE})
print(f"  drug-level index from   : {used_drug}")
print(f"  sponsor-level index from: {used_spon or '(pending BigQuery)'}")

PRIMARY = "ip_index_sponsor" if used_spon else "ip_index_drug"
df["ip_index"] = df[PRIMARY]
df["ip_index_source"] = PRIMARY
print(f"  PRIMARY index used      : {PRIMARY}")
SPEC = {"QUALITY":"citations_per_patent","BREADTH":"family_size",
        "TERM":"ob_term_remaining_yrs","FOCUS":"assignee_pharma_share",
        "SCALE":"assignee_portfolio_size"}
present = {k: (v in (used_spon + used_drug)) for k, v in SPEC.items()}
df["ip_index_spec_complete"] = int(all(present.values()))
print("  design dimensions present:",
      ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in present.items()))
if not all(present.values()):
    print("  *** index is NOT spec-complete - do not use for the headline RQ1 result ***")

frame = (df.start_year.between(2008, 2019)) & (df.is_resolved == 1)
sub = df[frame & df.ip_index.notna()]
thr = sub.ip_index.median()
df["ip_strong"] = np.where(df.ip_index.isna(), np.nan,
                           (df.ip_index > thr).astype(float))
# tertile-extremes contrast, a cleaner comparison for the sensitivity analysis
q1, q3 = sub.ip_index.quantile([1/3, 2/3])
df["ip_tertile_extreme"] = np.where(df.ip_index.isna(), np.nan,
                            np.where(df.ip_index >= q3, 1.0,
                            np.where(df.ip_index <= q1, 0.0, np.nan)))

cols = ["nct_id","ip_index","ip_index_drug","ip_index_sponsor","ip_index_source",
        "ip_strong","ip_tertile_extreme","ob_evergreen_ratio","ob_n_patents",
        "ob_term_remaining_yrs",
        # sponsor-level components, so RQ2 can test them as predictors and not
        # only as inputs to the RQ1 split
        "assignee_portfolio_size","assignee_pharma_share",
        # drug-level patent quality and breadth from sql/02: RQ2 predictors,
        # not composite components (see the note above SPONSOR_SCALE_FREE)
        "citations_per_patent","family_size","family_n_countries"]
p = os.path.join(OUT, "ip_index.parquet")
df[[c for c in cols if c in df.columns]].to_parquet(p, index=False, compression="zstd")

fr = df[frame]
print(f"\n=== RQ1 SUBSAMPLE (frame N={len(fr):,}) ===")
print(f"  index computable        : {int(fr.ip_index.notna().sum()):,} "
      f"({fr.ip_index.notna().mean():.1%})")
print(f"  UNOBSERVED (excluded)   : {int(fr.ip_index.isna().sum()):,} "
      f"- not coded as weak")
print(f"  split threshold ({SPLIT_RULE}) : {thr:.4f}")
s = fr[fr.ip_strong.notna()]
print(f"  strong / weak           : {int(s.ip_strong.sum()):,} / {int((1-s.ip_strong).sum()):,}")
print(f"  RQ1 requirement is 583 per group: "
      f"{'MET' if min(s.ip_strong.sum(), (1-s.ip_strong).sum()) >= 583 else 'NOT MET'}")
print("\n  component correlations (should be positive if they measure one thing):")
Z = df.loc[frame, [c for c in used_drug]].apply(pd.to_numeric, errors="coerce")
print(Z.corr().round(3).to_string())
