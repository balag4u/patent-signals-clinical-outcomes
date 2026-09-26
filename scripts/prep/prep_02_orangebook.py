#!/usr/bin/env python3
"""Orange Book -> IP/exclusivity variables per FDA application (NDA/BLA/ANDA)."""
import os, sys
import pandas as pd
SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
rd = lambda f: pd.read_csv(os.path.join(SRC, f), sep="~", dtype=str,
                           encoding="utf-8", encoding_errors="replace")
pat, exc, prod = rd("patent.txt"), rd("exclusivity.txt"), rd("products.txt")
pat["appl_no"] = pat.Appl_No.str.strip()
pat["patent_expire"] = pd.to_datetime(pat.Patent_Expire_Date_Text, errors="coerce")
pat["submission_date"] = pd.to_datetime(pat.Submission_Date, errors="coerce")
pat["is_substance"] = (pat.Drug_Substance_Flag.fillna("") == "Y").astype(int)
pat["is_product"]   = (pat.Drug_Product_Flag.fillna("")  == "Y").astype(int)
pat["has_use_code"] = pat.Patent_Use_Code.notna().astype(int)
# secondary patent = neither composition-of-matter nor product; i.e. method-of-use only
pat["is_secondary"] = ((pat.is_substance == 0) & (pat.is_product == 0)).astype(int)

ip = pat.groupby("appl_no").agg(
    ob_n_patents=("Patent_No", "nunique"),
    ob_n_primary_patents=("is_substance", "sum"),
    ob_n_product_patents=("is_product", "sum"),
    ob_n_secondary_patents=("is_secondary", "sum"),
    ob_n_use_codes=("has_use_code", "sum"),
    ob_last_patent_expiry=("patent_expire", "max"),
    ob_first_patent_expiry=("patent_expire", "min"),
    ob_first_submission=("submission_date", "min"),
    ob_last_submission=("submission_date", "max"),
).reset_index()
ip["ob_evergreen_ratio"] = (ip.ob_n_secondary_patents / ip.ob_n_patents).round(4)
ip["ob_patent_span_years"] = ((ip.ob_last_patent_expiry - ip.ob_first_patent_expiry)
                              .dt.days / 365.25).round(2)
# exclusivity
exc["appl_no"] = exc.Appl_No.str.strip()
exc["exc_date"] = pd.to_datetime(exc.Exclusivity_Date, errors="coerce")
ex = exc.groupby("appl_no").agg(
    ob_n_exclusivities=("Exclusivity_Code", "nunique"),
    ob_last_exclusivity=("exc_date", "max"),
    ob_exclusivity_codes=("Exclusivity_Code", lambda s: "|".join(sorted(set(s.dropna())))),
).reset_index()
ex["ob_has_orphan_excl"] = ex.ob_exclusivity_codes.str.contains("ODE", na=False).astype(int)
ex["ob_has_pediatric_excl"] = ex.ob_exclusivity_codes.str.contains("PED", na=False).astype(int)
ex["ob_has_nce_excl"] = ex.ob_exclusivity_codes.str.contains("NCE", na=False).astype(int)
# products -> ingredient linkage key
prod["appl_no"] = prod.Appl_No.str.strip()
prod["ingredient_norm"] = prod.Ingredient.str.upper().str.strip()
pr = prod.groupby("appl_no").agg(
    ob_ingredient=("ingredient_norm", "first"),
    ob_trade_name=("Trade_Name", "first"),
    ob_applicant=("Applicant_Full_Name", "first"),
    ob_appl_type=("Appl_Type", "first"),
    ob_n_products=("Product_No", "nunique"),
    ob_approval_date=("Approval_Date", "first"),
).reset_index()

m = pr.merge(ip, on="appl_no", how="left").merge(ex, on="appl_no", how="left")
for c in ["ob_n_patents","ob_n_primary_patents","ob_n_secondary_patents",
          "ob_n_use_codes","ob_n_exclusivities","ob_has_orphan_excl",
          "ob_has_pediatric_excl","ob_has_nce_excl"]:
    m[c] = m[c].fillna(0).astype(int)
m["ob_has_patent"] = (m.ob_n_patents > 0).astype(int)
p = os.path.join(OUT, "orangebook_ip.parquet")
m.to_parquet(p, index=False, compression="zstd")
print(f"applications={len(m):,} with_patents={int(m.ob_has_patent.sum()):,} -> {p} ({os.path.getsize(p)/1e6:.2f} MB)")
# also save the patent-number list for the BigQuery lookup
pn = sorted(set(pat.Patent_No.dropna().str.strip()))
open(os.path.join(OUT, "orangebook_patent_numbers.txt"), "w").write("\n".join(pn))
print(f"unique patent numbers for BigQuery: {len(pn):,}")
