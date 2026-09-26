#!/usr/bin/env python3
"""Map trials to six mutually exclusive therapeutic-area strata for RQ4,
using AACT's precomputed MeSH ancestor terms (top-level MeSH disease categories).

Assignment is PRIORITY-ORDERED because a trial may sit under several top-level
categories (e.g. lung cancer is both Neoplasms and Respiratory Tract Diseases).
The order places the most clinically distinctive category first.
"""
import os, sys
import pandas as pd

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)

# top-level MeSH disease categories -> analysis strata, in priority order
PRIORITY = [
    ("Oncology",              ["Neoplasms"]),
    ("Infectious Disease",    ["Infections"]),
    ("Neurology & Psychiatry",["Nervous System Diseases", "Mental Disorders"]),
    ("Cardiovascular",        ["Cardiovascular Diseases"]),
    ("Metabolic & Endocrine", ["Nutritional and Metabolic Diseases",
                               "Endocrine System Diseases"]),
]
WANTED = {t for _, terms in PRIORITY for t in terms}

print("reading browse_conditions ...", flush=True)
keep = []
for ch in pd.read_csv(os.path.join(SRC, "browse_conditions.txt"), sep="|",
                      usecols=["nct_id", "mesh_term", "mesh_type"], chunksize=1_000_000,
                      dtype=str, encoding_errors="replace", on_bad_lines="skip"):
    keep.append(ch[ch.mesh_term.isin(WANTED)][["nct_id", "mesh_term"]])
bc = pd.concat(keep, ignore_index=True).drop_duplicates()
print(f"  rows matching top-level categories: {len(bc):,}  trials: {bc.nct_id.nunique():,}")

# pivot to a membership set per trial
memb = bc.groupby("nct_id").mesh_term.apply(set)

def assign(terms):
    for area, keys in PRIORITY:
        if any(k in terms for k in keys):
            return area
    return "Other"

area = memb.map(assign).rename("therapeutic_area").reset_index()
print("\nassignment across ALL trials with MeSH mapping:")
print(area.therapeutic_area.value_counts().to_string())

# join onto the analytic frame
trials = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"))
m = trials.merge(area, on="nct_id", how="left")
m["therapeutic_area"] = m.therapeutic_area.fillna("Other")
m.to_parquet(os.path.join(OUT, "ctgov_trials.parquet"), index=False, compression="zstd")

frame = m[(m.start_year.between(2008, 2019)) & (m.is_resolved == 1)]
print(f"\n=== RQ4 STRATA CHECK (frame N={len(frame):,}, requirement 737/stratum) ===")
summ = frame.groupby("therapeutic_area").agg(
    n=("nct_id", "size"), p_term=("is_terminated", "mean")).reset_index()
summ["meets_737"] = summ.n >= 737
summ["margin_at_n"] = (1.959964 * (summ.p_term*(1-summ.p_term)/summ.n)**0.5).round(4)
summ = summ.sort_values("n", ascending=False)
print(summ.to_string(index=False))
print(f"\nstrata meeting requirement: {int(summ.meets_737.sum())}/{len(summ)}")
summ.to_csv(os.path.join(OUT, "rq4_strata_check.csv"), index=False)
