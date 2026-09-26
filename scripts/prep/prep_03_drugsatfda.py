#!/usr/bin/env python3
"""Drugs@FDA -> regulatory pathway / designation variables per application."""
import os, sys
import pandas as pd
SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
rd = lambda f: pd.read_csv(os.path.join(SRC, f), sep="\t", dtype=str,
                           encoding="utf-8", encoding_errors="replace")
app, sub, spt = rd("Applications.txt"), rd("Submissions.txt"), rd("SubmissionPropertyType.txt")
lk, prod = rd("SubmissionClass_Lookup.txt"), rd("Products.txt")
sub = sub.merge(lk[["SubmissionClassCodeID","SubmissionClassCode"]],
                on="SubmissionClassCodeID", how="left")
sub["date"] = pd.to_datetime(sub.SubmissionStatusDate, errors="coerce")
sub["is_priority"] = (sub.ReviewPriority.fillna("") == "PRIORITY").astype(int)
sub["is_orig"] = (sub.SubmissionType.fillna("") == "ORIG").astype(int)
sub["is_nme"] = sub.SubmissionClassCode.fillna("").str.startswith("TYPE 1").astype(int)
sub["is_efficacy_suppl"] = (sub.SubmissionClassCode.fillna("") == "EFFICACY").astype(int)
sub["is_rems"] = (sub.SubmissionClassCode.fillna("") == "REMS").astype(int)
orph = (spt[spt.SubmissionPropertyTypeCode == "Orphan"]
        .groupby("ApplNo").size().rename("fda_n_orphan_designations").reset_index())
agg = sub.groupby("ApplNo").agg(
    fda_n_submissions=("SubmissionNo","count"),
    fda_n_priority=("is_priority","sum"),
    fda_any_priority=("is_priority","max"),
    fda_is_nme=("is_nme","max"),
    fda_n_efficacy_suppl=("is_efficacy_suppl","sum"),
    fda_has_rems=("is_rems","max"),
    fda_first_action=("date","min"),
    fda_last_action=("date","max"),
).reset_index()
prod["ApplNo"] = prod.ApplNo.str.strip()
pr = prod.groupby("ApplNo").agg(
    fda_ingredient=("ActiveIngredient", lambda s: str(s.iloc[0]).upper().strip()),
    fda_drug_name=("DrugName","first"),
    fda_form=("Form","first"),
    fda_n_products=("ProductNo","nunique"),
).reset_index()
m = (app.rename(columns={"ApplNo":"ApplNo"})[["ApplNo","ApplType","SponsorName"]]
       .merge(agg, on="ApplNo", how="left").merge(orph, on="ApplNo", how="left")
       .merge(pr, on="ApplNo", how="left"))
m["fda_n_orphan_designations"] = m.fda_n_orphan_designations.fillna(0).astype(int)
m["fda_has_orphan"] = (m.fda_n_orphan_designations > 0).astype(int)
m["fda_lifecycle_years"] = ((m.fda_last_action - m.fda_first_action).dt.days/365.25).round(2)
m = m.rename(columns={"ApplNo":"appl_no","ApplType":"fda_appl_type","SponsorName":"fda_sponsor"})
p = os.path.join(OUT, "drugsatfda_regulatory.parquet")
m.to_parquet(p, index=False, compression="zstd")
print(f"applications={len(m):,} orphan={int(m.fda_has_orphan.sum()):,} "
      f"priority={int(m.fda_any_priority.fillna(0).sum()):,} -> {p} ({os.path.getsize(p)/1e6:.2f} MB)")
