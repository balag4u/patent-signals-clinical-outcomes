#!/usr/bin/env python3
"""Purple Book -> biologics (BLA) reference table.

The published CSV carries a monthly 'changes' banner and a repeated header row,
then the FULL standing product listing. Both are parsed; the N/R/U flag is kept
so the small changes subset stays identifiable.
"""
import os, sys, csv
import pandas as pd

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
rows = list(csv.reader(open(SRC, encoding="utf-8", errors="replace")))
hdr_i = next(i for i, r in enumerate(rows) if r and r[0].strip() == "N/R/U")
cols = [c.strip() for c in rows[hdr_i]]
data = [r for r in rows[hdr_i+1:]
        if any(c.strip() for c in r) and r[0].strip() != "N/R/U"]
df = pd.DataFrame(data, columns=cols[:len(data[0])] if data else cols)
df.columns = [c.strip() for c in df.columns]

ren = {"N/R/U":"change_flag","Applicant":"applicant","BLA Number":"bla_number",
       "Proprietary Name":"brand_name","Proper Name":"proper_name",
       "License Type":"license_type","Marketing Status":"marketing_status",
       "Approval Date":"approval_date","Licensure":"licensure",
       "Supplement Number":"supplement_no","Submission Type":"submission_type",
       "Center":"center","Route of Administration":"route","Dosage Form":"dosage_form",
       "Ref. Product Proper Name":"ref_product_proper_name"}
df = df.rename(columns={k:v for k,v in ren.items() if k in df.columns})
# Two-digit years ("23-Jul-86") roll forward past the pivot, so anything landing
# in the future is shifted back a century.
_d = pd.to_datetime(df.get("approval_date"), errors="coerce", format="mixed", dayfirst=False)
_future = _d > pd.Timestamp.today()
df["approval_date"] = _d.mask(_future, _d - pd.DateOffset(years=100))
lt = df.get("license_type", pd.Series(dtype=str)).fillna("")
df["is_biosimilar"]      = lt.str.contains("351\\(k\\)", regex=True).astype(int)
df["is_interchangeable"] = lt.str.contains("Interchangeable", case=False).astype(int)
df["is_originator"]      = lt.str.contains(r"351\(a\)", regex=True).astype(int)
df["proper_name_norm"]   = df.get("proper_name","").astype(str).str.upper().str.strip()
df["applicant_norm"]     = df.get("applicant","").astype(str).str.upper().str.strip()

p = os.path.join(OUT, "purplebook_biologics.parquet")
df.to_parquet(p, index=False, compression="zstd")
print(f"products={len(df):,}  unique BLA={df.bla_number.nunique():,}  -> {p} "
      f"({os.path.getsize(p)/1e6:.2f} MB)")
print(f"  originator 351(a)     : {int(df.is_originator.sum()):,}")
print(f"  biosimilar 351(k)     : {int(df.is_biosimilar.sum()):,}")
print(f"  of which interchangeable: {int(df.is_interchangeable.sum()):,}")
print(f"  unique applicants     : {df.applicant_norm.nunique():,}")
print(f"  approval date range   : {df.approval_date.min():%Y-%m-%d} .. {df.approval_date.max():%Y-%m-%d}")
