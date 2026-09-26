#!/usr/bin/env python3
"""Add intervention modality (biologic vs small molecule) to the trials table.
Modality is taken from the registry's own intervention TYPE field, then refined
with the FDA application type (BLA vs NDA) where the trial resolves to one."""
import json, os, sys, glob
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
rows = []
for fn in sorted(glob.glob(os.path.join(RAW, "*.json"))):
    for st in json.load(open(fn)).get("studies", []):
        p = st.get("protocolSection", {})
        ivs = (p.get("armsInterventionsModule", {}) or {}).get("interventions") or []
        types = sorted({(i.get("type") or "").upper() for i in ivs if i.get("type")})
        rows.append({"nct_id": p.get("identificationModule", {}).get("nctId"),
                     "intervention_types": "|".join(types)})
iv = pd.DataFrame(rows).drop_duplicates("nct_id")
print(f"intervention types extracted for {len(iv):,} trials")

t = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"))
t = t.drop(columns=[c for c in ("intervention_types","is_biologic","modality") if c in t.columns])
t = t.merge(iv, on="nct_id", how="left")
t["intervention_types"] = t.intervention_types.fillna("")
t["is_biologic"] = t.intervention_types.str.contains("BIOLOGICAL").astype(int)

# refine with FDA application type where the trial resolved to an application
rp = os.path.join(OUT, "trial_drug_resolution.parquet")
if os.path.exists(rp):
    r = pd.read_parquet(rp, columns=["nct_id", "appl_no"])
    reg = pd.read_parquet(os.path.join(OUT, "drugsatfda_regulatory.parquet"),
                          columns=["appl_no", "fda_appl_type"])
    r = r[r.appl_no != ""].merge(reg, on="appl_no", how="left")
    bla = set(r[r.fda_appl_type == "BLA"].nct_id)
    t.loc[t.nct_id.isin(bla), "is_biologic"] = 1
    print(f"  refined by FDA BLA linkage: +{len(bla):,} trials")

t["modality"] = t.is_biologic.map({1: "Biologic", 0: "Small molecule"})
t.to_parquet(os.path.join(OUT, "ctgov_trials.parquet"), index=False, compression="zstd")

f = t[(t.start_year.between(2008, 2019)) & (t.is_resolved == 1)]
print(f"\n=== MODALITY IN ANALYTIC FRAME (N={len(f):,}) ===")
s = f.groupby("modality").agg(n=("nct_id","size"), p_term=("is_terminated","mean"),
                              p_phase3=("is_phase3","mean"),
                              p_industry=("is_industry","mean")).round(4)
print(s.to_string())
print(f"\nbiologic share: {f.is_biologic.mean():.1%}")
print(f"meets RQ4 stratum requirement (737): "
      f"{'yes' if f.is_biologic.sum() >= 737 else 'no'}")
