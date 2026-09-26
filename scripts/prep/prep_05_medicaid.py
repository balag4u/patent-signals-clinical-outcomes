#!/usr/bin/env python3
"""Medicaid State Drug Utilization -> product-year commercial aggregates.
Records the small-cell suppression rate, which is a stated study limitation."""
import os, sys, glob
import pandas as pd

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
USE = ["Utilization Type","State","NDC","Labeler Code","Year","Quarter",
       "Suppression Used","Product Name","Units Reimbursed",
       "Number of Prescriptions","Total Amount Reimbursed"]
frames, supp_rows = [], []
for f in sorted(glob.glob(os.path.join(SRC, "sdud_*.csv"))):
    yr = os.path.basename(f).split("_")[1].split(".")[0]
    n_raw = 0; parts = []
    for ch in pd.read_csv(f, usecols=lambda c: c in USE, chunksize=500_000,
                          low_memory=False, encoding_errors="replace"):
        n_raw += len(ch)
        ch["suppressed"] = ch["Suppression Used"].astype(str).str.lower().eq("true")
        ch["product_norm"] = ch["Product Name"].astype(str).str.upper().str.strip()
        for c in ["Units Reimbursed","Number of Prescriptions","Total Amount Reimbursed"]:
            ch[c] = pd.to_numeric(ch[c], errors="coerce")
        parts.append(ch.groupby(["product_norm","Labeler Code","Year"], dropna=False).agg(
            units=("Units Reimbursed","sum"),
            scripts=("Number of Prescriptions","sum"),
            reimbursed=("Total Amount Reimbursed","sum"),
            n_rows=("NDC","size"),
            n_suppressed=("suppressed","sum"),
            n_states=("State","nunique"),
        ).reset_index())
    d = pd.concat(parts).groupby(["product_norm","Labeler Code","Year"], dropna=False).agg(
        units=("units","sum"), scripts=("scripts","sum"), reimbursed=("reimbursed","sum"),
        n_rows=("n_rows","sum"), n_suppressed=("n_suppressed","sum"),
        n_states=("n_states","max")).reset_index()
    supp = d.n_suppressed.sum() / max(d.n_rows.sum(), 1)
    supp_rows.append({"year": yr, "raw_rows": n_raw, "agg_rows": len(d),
                      "suppression_rate": round(supp, 4)})
    print(f"{yr}: raw={n_raw:>9,} -> agg={len(d):>7,} ({n_raw/max(len(d),1):.0f}x) "
          f"suppressed={supp:.1%}", flush=True)
    frames.append(d)

allp = pd.concat(frames, ignore_index=True)
allp = allp.rename(columns={"Labeler Code": "labeler_code", "Year": "year"})
allp["log_reimbursed"] = pd.np.log1p(allp.reimbursed) if hasattr(pd, "np") else \
    __import__("numpy").log1p(allp.reimbursed.clip(lower=0))
p = os.path.join(OUT, "medicaid_product_year.parquet")
allp.to_parquet(p, index=False, compression="zstd")
sp = pd.DataFrame(supp_rows)
sp.to_csv(os.path.join(OUT, "medicaid_suppression_by_year.csv"), index=False)
raw_mb = sum(os.path.getsize(f) for f in glob.glob(os.path.join(SRC,"sdud_*.csv")))/1e6
print(f"\nTOTAL rows={len(allp):,} -> {p} ({os.path.getsize(p)/1e6:.1f} MB)")
print(f"raw {raw_mb:,.0f} MB -> {os.path.getsize(p)/1e6:.1f} MB "
      f"({raw_mb/(os.path.getsize(p)/1e6):.0f}x reduction)")
print(f"overall suppression rate: {sp.suppression_rate.mean():.1%}")
