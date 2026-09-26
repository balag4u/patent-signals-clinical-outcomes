#!/usr/bin/env python3
"""Sponsor-level safety burden, linked through TRIALS rather than FAERS reporters.

prep_04 aggregated by FAERS `mfr_sndr`, which is whoever submitted the adverse
event report - often a generics manufacturer or a distributor, not the company
that ran the trial. The synopsis variable `sponsor_prr_burden` is a property of
the TRIAL SPONSOR, so the correct path is:

    trial -> resolved ingredient -> FAERS burden -> aggregate to sponsor

Values are measured across the sponsor's resolved portfolio. PRR is summarised
by the MEDIAN because it is unbounded on sparse cells.
"""
import os, sys
import numpy as np, pandas as pd
OUT = sys.argv[1]
tr = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"),
                     columns=["nct_id","lead_sponsor","start_year","is_resolved","is_industry"])
res = pd.read_parquet(os.path.join(OUT, "trial_drug_resolution.parquet"),
                      columns=["nct_id","ingredient"])
bur = pd.read_parquet(os.path.join(OUT, "faers_drug_burden.parquet"))
grp = pd.read_parquet(os.path.join(OUT, "sponsor_assignee_map.parquet"),
                      columns=["nct_id","corporate_group"])

d = tr.merge(res, on="nct_id", how="left").merge(grp, on="nct_id", how="left")
d["ingredient"] = d.ingredient.fillna("")
d = d.merge(bur, on="ingredient", how="left")
cov = d.median_prr.notna().mean()
print(f"trials with a FAERS-linked ingredient: {d.median_prr.notna().sum():,} ({cov:.1%})")

for key, name in [("lead_sponsor", "sponsor"), ("corporate_group", "group")]:
    agg = (d[d.median_prr.notna()].groupby(key)
           .agg(n_trials=("nct_id","nunique"),
                n_ingredients=("ingredient","nunique"),
                sponsor_prr_burden=("median_prr","median"),
                sponsor_total_signals=("n_signals","sum"),
                sponsor_mean_signal_rate=("signal_rate","mean")).reset_index())
    p = os.path.join(OUT, f"faers_{name}_burden.parquet")
    agg.to_parquet(p, index=False, compression="zstd")
    print(f"  {name:8s}: {len(agg):,} rows -> {os.path.basename(p)}")

g = pd.read_parquet(os.path.join(OUT, "faers_group_burden.parquet"))
print("\ntop corporate groups by trial count (sanity check):")
print(g.nlargest(8, "n_trials")[
    ["corporate_group","n_trials","n_ingredients",
     "sponsor_prr_burden","sponsor_total_signals"]].round(3).to_string(index=False))
