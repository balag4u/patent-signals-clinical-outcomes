#!/usr/bin/env python3
"""FAERS quarterly ASCII extracts -> disproportionality signal tables.

FAERS has no exposure denominator, so raw adverse-event counts are meaningless as
a safety measure (Evans, Waller & Davis, 2001). This builds the standard 2x2
contingency structure per drug-event pair and derives PRR, ROR and chi-square.

Three correctness steps that are easy to skip and wrong to skip:
  1. Case de-duplication. One caseid appears in many quarters with rising
     caseversion; only the latest version is kept, across the whole series.
  2. Deleted cases. Each quarter ships a DELETE list of retracted caseids.
  3. Suspect drugs only. role_cod PS/SS (primary/secondary suspect); concomitant
     medications are not implicated in the report and would dilute every signal.

Outputs (09_analysis_ready/):
  faers_drug_event_signals.parquet  - ingredient x MedDRA PT, with PRR/ROR/chi2
  faers_drug_burden.parquet         - per ingredient, signal and seriousness counts
  faers_sponsor_burden.parquet      - per reporting manufacturer, the synopsis
                                      variable `sponsor_prr_burden`
"""
import os, sys, glob, zipfile, io, gc
from collections import defaultdict
import pandas as pd
import numpy as np

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
ZIPS = sorted(glob.glob(os.path.join(SRC, "*.zip")))
print(f"quarters: {len(ZIPS)}", flush=True)

def members(z, prefix):
    return [i.filename for i in z.infolist()
            if os.path.basename(i.filename).upper().startswith(prefix)
            and i.filename.upper().endswith(".TXT")]

def read(z, name, cols=None):
    with z.open(name) as fh:
        return pd.read_csv(io.TextIOWrapper(fh, encoding="latin-1"), sep="$",
                           usecols=cols, dtype=str, on_bad_lines="skip",
                           low_memory=False)

# ---------------------------------------------------------------- pass 1: cases
print("\n[pass 1] de-duplicating cases across all quarters ...", flush=True)
demo, deleted = [], set()
for zp in ZIPS:
    q = os.path.basename(zp).replace("faers_ascii_", "").replace(".zip", "")
    with zipfile.ZipFile(zp) as z:
        for n in members(z, "DELETE"):
            try: deleted.update(read(z, n).iloc[:, 0].dropna().astype(str))
            except Exception: pass
        m = members(z, "DEMO")
        if not m: continue
        d = read(z, m[0], ["primaryid", "caseid", "caseversion", "mfr_sndr", "fda_dt"])
        d["quarter"] = q
        demo.append(d)
    print(f"  {q}: {len(demo[-1]):>8,} reports", flush=True)

demo = pd.concat(demo, ignore_index=True)
demo["caseversion"] = pd.to_numeric(demo.caseversion, errors="coerce").fillna(0)
n0 = len(demo)
demo = demo[~demo.caseid.astype(str).isin(deleted)]
print(f"\n  raw reports              : {n0:,}")
print(f"  removed as deleted cases : {n0 - len(demo):,}")
demo = (demo.sort_values("caseversion")
             .drop_duplicates(subset="caseid", keep="last"))
print(f"  unique cases (latest ver): {len(demo):,}")
KEEP = set(demo.primaryid.astype(str))
SPONSOR = dict(zip(demo.primaryid.astype(str),
                   demo.mfr_sndr.fillna("").str.upper().str.strip()))
del deleted; gc.collect()

# ------------------------------------------------- pass 2: drug-event pairs
print("\n[pass 2] accumulating suspect drug x reaction pairs ...", flush=True)
pairs = defaultdict(int)          # (ingredient, pt) -> report count
drug_rep = defaultdict(set)       # ingredient -> primaryids
spons_drug = defaultdict(set)     # sponsor -> ingredients
nda_map = defaultdict(set)        # ingredient -> nda numbers
for k, zp in enumerate(ZIPS, 1):
    q = os.path.basename(zp).replace("faers_ascii_", "").replace(".zip", "")
    with zipfile.ZipFile(zp) as z:
        md, mr = members(z, "DRUG"), members(z, "REAC")
        if not md or not mr: continue
        dr = read(z, md[0], ["primaryid", "role_cod", "prod_ai", "drugname", "nda_num"])
        rc = read(z, mr[0], ["primaryid", "pt"])
    dr = dr[dr.primaryid.astype(str).isin(KEEP)]
    dr = dr[dr.role_cod.isin(["PS", "SS"])]
    ai = dr.prod_ai.fillna("").str.upper().str.strip()
    ai = ai.where(ai != "", dr.drugname.fillna("").str.upper().str.strip())
    dr = dr.assign(ingredient=ai)
    dr = dr[dr.ingredient != ""][["primaryid", "ingredient", "nda_num"]].drop_duplicates()
    rc = rc[rc.primaryid.astype(str).isin(KEEP)]
    rc["pt"] = rc.pt.fillna("").str.upper().str.strip()
    rc = rc[rc.pt != ""][["primaryid", "pt"]].drop_duplicates()

    for ing, pid, nda in zip(dr.ingredient, dr.primaryid.astype(str), dr.nda_num):
        drug_rep[ing].add(pid)
        if isinstance(nda, str) and nda.strip():
            nda_map[ing].add(nda.strip())
        s = SPONSOR.get(pid, "")
        if s: spons_drug[s].add(ing)
    j = dr[["primaryid", "ingredient"]].merge(rc, on="primaryid")
    for ing, pt in zip(j.ingredient, j.pt):
        pairs[(ing, pt)] += 1
    print(f"  [{k:>2}/{len(ZIPS)}] {q}: drugs={len(dr):>8,} reacs={len(rc):>8,} "
          f"pairs={len(pairs):>9,}", flush=True)
    del dr, rc, j; gc.collect()

# --------------------------------------------------- disproportionality maths
print("\n[pass 3] computing PRR / ROR / chi-square ...", flush=True)
df = pd.DataFrame([(i, p, n) for (i, p), n in pairs.items()],
                  columns=["ingredient", "pt", "a"])
N   = int(df.a.sum())
drug_tot  = df.groupby("ingredient").a.sum().rename("drug_total")
event_tot = df.groupby("pt").a.sum().rename("event_total")
df = df.join(drug_tot, on="ingredient").join(event_tot, on="pt")
a = df.a.astype(float)
b = df.drug_total - a                      # drug, other events
c = df.event_total - a                     # other drugs, this event
d = N - a - b - c                          # other drugs, other events
df["b"], df["c"], df["d"] = b, c, d
with np.errstate(divide="ignore", invalid="ignore"):
    df["prr"] = (a / (a + b)) / (c / (c + d))
    df["ror"] = (a * d) / (b * c)
    exp = (a + b) * (a + c) / N
    df["chi2"] = (np.abs(a - exp) - 0.5) ** 2 * N / ((a+b)*(c+d)*(a+c)*(b+d)/N**2) / N
    se = np.sqrt(1/a + 1/b + 1/c + 1/d)
    df["ror_lo"] = np.exp(np.log(df.ror) - 1.96*se)
    df["ror_hi"] = np.exp(np.log(df.ror) + 1.96*se)
# Evans et al. (2001) signal criterion
df["is_signal"] = ((df.a >= 3) & (df.prr >= 2) & (df.chi2 >= 4)).astype(int)
df = df.replace([np.inf, -np.inf], np.nan)
p = os.path.join(OUT, "faers_drug_event_signals.parquet")
df.to_parquet(p, index=False, compression="zstd")
print(f"  drug-event pairs : {len(df):,}  -> {os.path.getsize(p)/1e6:.1f} MB")
print(f"  flagged signals  : {int(df.is_signal.sum()):,}")

# ------------------------------------------------------------- drug burden
burden = df.groupby("ingredient").agg(
    n_events=("pt", "nunique"), n_reports=("a", "sum"),
    n_signals=("is_signal", "sum"), mean_prr=("prr", "mean"),
    max_prr=("prr", "max")).reset_index()
burden["n_unique_reports"] = burden.ingredient.map(lambda i: len(drug_rep.get(i, ())))
burden["nda_numbers"] = burden.ingredient.map(
    lambda i: "|".join(sorted(nda_map.get(i, ()))[:10]))
burden["signal_rate"] = (burden.n_signals / burden.n_events).round(4)
p2 = os.path.join(OUT, "faers_drug_burden.parquet")
burden.to_parquet(p2, index=False, compression="zstd")
print(f"  ingredients      : {len(burden):,}  -> {os.path.getsize(p2)/1e6:.1f} MB")

# ---------------------------------------------------------- sponsor burden
prr_by_ing = burden.set_index("ingredient").mean_prr
rows = []
for s, ings in spons_drug.items():
    v = prr_by_ing.reindex(list(ings)).dropna()
    sig = burden.set_index("ingredient").n_signals.reindex(list(ings)).fillna(0)
    rows.append({"mfr_sndr": s, "n_ingredients": len(ings),
                 "sponsor_prr_burden": float(v.mean()) if len(v) else np.nan,
                 "sponsor_total_signals": int(sig.sum())})
sp = pd.DataFrame(rows).sort_values("n_ingredients", ascending=False)
p3 = os.path.join(OUT, "faers_sponsor_burden.parquet")
sp.to_parquet(p3, index=False, compression="zstd")
print(f"  sponsors         : {len(sp):,}  -> {os.path.getsize(p3)/1e6:.1f} MB")
print("\ntop sponsors by breadth:")
print(sp.head(8).to_string(index=False))
