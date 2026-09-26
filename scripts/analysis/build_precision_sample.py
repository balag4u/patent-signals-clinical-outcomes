#!/usr/bin/env python3
"""Draw a stratified 200-link sample for manual precision adjudication.

Why stratified and not simple random: a proportional sample would contain ~0.4
fuzzy links, so nothing could be learned about the method most likely to be
wrong. Risky methods are deliberately over-sampled, then weighted back to the
population when precision is computed (see score_precision.py).
"""
import os, sys
import pandas as pd, numpy as np

OUT, VAL = sys.argv[1], sys.argv[2]
os.makedirs(VAL, exist_ok=True)
RNG = 20260926

res = pd.read_parquet(os.path.join(OUT, "trial_drug_resolution.parquet"))
tr  = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"),
                      columns=["nct_id", "brief_title", "primary_condition",
                               "drug_names", "modality"]) \
      if "brief_title" in pd.read_parquet(
            os.path.join(OUT,"ctgov_trials.parquet")).columns \
      else pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"),
                           columns=["nct_id", "primary_condition",
                                    "drug_names", "modality"])
m = res[res.method != "none"].merge(tr, on="nct_id", how="left")

# disproportionate allocation: take everything from the small risky strata
TARGET = {"exact": 40, "synonym": 50, "token": 60, "fuzzy": 31, "desalt": 19}
pop = m.method.value_counts().to_dict()
parts, alloc = [], {}
for meth, want in TARGET.items():
    s = m[m.method == meth]
    n = min(want, len(s))
    alloc[meth] = n
    if n: parts.append(s.sample(n, random_state=RNG))
samp = pd.concat(parts).sample(frac=1, random_state=RNG).reset_index(drop=True)

samp.insert(0, "review_id", range(1, len(samp) + 1))
samp["verdict"] = ""          # CORRECT | WRONG | PARTIAL
samp["notes"] = ""
cols = ["review_id", "nct_id", "raw", "norm", "ingredient", "appl_no",
        "method", "score", "is_combination", "modality", "primary_condition",
        "verdict", "notes"]
cols = [c for c in cols if c in samp.columns]
p = os.path.join(VAL, "precision_sample_200.csv")
samp[cols].to_csv(p, index=False)

wt = pd.DataFrame([{"method": k, "population": pop.get(k, 0), "sampled": v,
                    "weight": pop.get(k, 0) / v if v else 0}
                   for k, v in alloc.items()])
wt["pop_share"] = wt.population / wt.population.sum()
wt.to_csv(os.path.join(VAL, "precision_sample_weights.csv"), index=False)

print(f"sample written: {p}  ({len(samp)} links)")
print("\nallocation (over-sampling the risky methods):")
print(wt[["method","population","sampled","pop_share","weight"]].round(4).to_string(index=False))
