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
# absorbed automatically once the BigQuery pull lands
SPONSOR = {
    "citations_per_patent":   "patent quality (scale-independent)",
    "family_n_countries":     "geographic breadth",
    "assignee_pharma_share":  "portfolio focus in A61K/A61P",
    "assignee_portfolio_size":"portfolio scale (confounded with firm size)",
}

def zcohort(s, cohort):
    """winsorise, log-compress counts, then z-score within cohort"""
    x = pd.to_numeric(s, errors="coerce")
    lo, hi = x.quantile(0.01), x.quantile(0.99)
    x = x.clip(lo, hi)
    if (x.dropna() >= 0).all() and x.max() and x.max() > 20:
        x = np.log1p(x)
    g = x.groupby(cohort)
    return (x - g.transform("mean")) / g.transform("std").replace(0, np.nan)

def build(cols, label):
    have = [c for c in cols if c in df.columns and df[c].notna().any()]
    if not have:
        print(f"  {label}: no components present - skipped"); return None, []
    Z = pd.DataFrame({c: zcohort(df[c], df.start_year) for c in have})
    idx = Z.mean(axis=1, skipna=True)
    idx[Z.notna().sum(axis=1) < max(2, len(have) - 1)] = np.nan   # need most parts
    return idx, have

print("=== components available ===")
for c, d_ in {**DRUG, **SPONSOR}.items():
    print(f"  {'YES' if c in df.columns and df[c].notna().any() else 'pending':8s} {c:26s} {d_}")

print("\n=== building indices ===")
df["ip_index_drug"], used_drug = build(DRUG, "drug-level")
df["ip_index_sponsor"], used_spon = build(SPONSOR, "sponsor-level")
print(f"  drug-level index from   : {used_drug}")
print(f"  sponsor-level index from: {used_spon or '(pending BigQuery)'}")

PRIMARY = "ip_index_sponsor" if used_spon else "ip_index_drug"
df["ip_index"] = df[PRIMARY]
df["ip_index_source"] = PRIMARY
print(f"  PRIMARY index used      : {PRIMARY}")

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
        "ob_term_remaining_yrs"]
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
