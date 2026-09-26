#!/usr/bin/env python3
"""Entity resolution: ClinicalTrials.gov free-text interventions -> FDA ingredients.

Registry intervention names are unnormalised free text. The same molecule appears
as a brand name, an INN, an internal development code, or a formulation phrase,
often with dose, route and arm-label debris attached:
    "DAPAGLIFLOZIN 10 MG", "EXPERIMENTAL: PLACEBO",
    "AL-4943A OPHTHALMIC SOLUTION", "NANOPARTICLE ALBUMIN-BOUND PACLITAXEL"

Strategy, in descending confidence:
  1  exact     - normalised string equals a known FDA/UNII ingredient
  2  token     - a known ingredient is a token-subsequence of the trial string
  3  fuzzy     - difflib ratio >= 0.92 against a blocked candidate set
Placebo/vehicle/comparator-only arms are excluded, not matched.

Output: trial_drug_resolution.parquet (nct_id, raw, normalised, ingredient,
        appl_no, method, score) + a coverage report.
"""
import os, re, sys, json, glob, zipfile, gc
from difflib import SequenceMatcher
import pandas as pd

OUT = sys.argv[1]; REF = sys.argv[2]
DOSE = re.compile(r"\b\d+(\.\d+)?\s?(MG|MCG|UG|G|ML|L|IU|U|%|MG/ML|MG/KG|MCG/ML|"
                  r"UNITS?|MEQ|MMOL|NG|KG)\b/?(ML|KG|M2|DAY|DOSE|HR)?", re.I)
FORM = re.compile(r"\b(TABLETS?|CAPSULES?|INJECTIONS?|SOLUTIONS?|SUSPENSIONS?|CREAMS?|"
                  r"OINTMENTS?|GELS?|PATCHES?|INHAL\w*|OPHTHALMIC|TOPICAL|ORAL|IV|"
                  r"INTRAVENOUS|SUBCUTANEOUS|INTRAMUSCULAR|SC|IM|PO|INFUSION|"
                  r"EXTENDED[- ]RELEASE|DELAYED[- ]RELEASE|IMMEDIATE[- ]RELEASE|"
                  r"FILM[- ]COATED|LYOPHILIZED|POWDER|SPRAY|DROPS?|SYRUP|SUPPOSITORY)\b", re.I)
LABEL = re.compile(r"^\s*(EXPERIMENTAL|ACTIVE COMPARATOR|PLACEBO COMPARATOR|ARM\s*\w*|"
                   r"GROUP\s*\w*|COHORT\s*\w*|TREATMENT|DRUG|BIOLOGICAL)\s*[:\-]\s*", re.I)
PLACEBO = re.compile(r"\b(PLACEBO|VEHICLE|SALINE|STANDARD OF CARE|BEST SUPPORTIVE CARE|"
                     r"NORMAL SALINE|SHAM|NO INTERVENTION|DILUENT|CONTROL)\b", re.I)
PUNCT = re.compile(r"[^A-Z0-9 \-]")

def normalise(s):
    if not isinstance(s, str): return ""
    s = s.upper().strip()
    s = LABEL.sub("", s)
    s = re.sub(r"\([^)]*\)", " ", s)      # drop parentheticals
    s = DOSE.sub(" ", s)
    s = FORM.sub(" ", s)
    s = PUNCT.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_placebo(s):
    return bool(PLACEBO.search(s or ""))

SALT = re.compile(r"\s+(SODIUM|POTASSIUM|CALCIUM|MAGNESIUM|HYDROCHLORIDE|HCL|MESYLATE|"
                  r"SULFATE|SULPHATE|TARTRATE|MALEATE|CITRATE|ACETATE|PHOSPHATE|"
                  r"SUCCINATE|FUMARATE|BESYLATE|TOSYLATE|BROMIDE|CHLORIDE|NITRATE|"
                  r"OXALATE|LACTATE|GLUCONATE|CARBONATE|BITARTRATE|DIHYDRATE|"
                  r"MONOHYDRATE|TRIHYDRATE|ANHYDROUS|HYDRATE|DISODIUM|HEMIHYDRATE)$")
def desalt(s):
    prev = None
    while prev != s:
        prev = s; s = SALT.sub("", s).strip()
    return s

# ------------------------------------------------ reference vocabulary
print("building reference vocabulary ...", flush=True)
vocab = {}   # normalised ingredient -> appl_no (or "")
def add(name, appl=""):
    n = normalise(name)
    if len(n) >= 3 and not is_placebo(n):
        vocab.setdefault(n, appl or "")
        if appl and not vocab[n]: vocab[n] = appl

reg = pd.read_parquet(os.path.join(OUT, "drugsatfda_regulatory.parquet"))
for ing, ap in zip(reg.fda_ingredient.fillna(""), reg.appl_no.fillna("")):
    for part in str(ing).split(";"): add(part, ap)
for bn, ap in zip(reg.fda_drug_name.fillna(""), reg.appl_no.fillna("")):
    add(bn, ap)                                    # brand names, e.g. SYMBICORT
print(f"  Drugs@FDA      : {len(vocab):,}")

ob = pd.read_parquet(os.path.join(OUT, "orangebook_ip.parquet"))
for ing, ap in zip(ob.ob_ingredient.fillna(""), ob.appl_no.fillna("")):
    for part in str(ing).split(";"): add(part, ap)
for tn, ap in zip(ob.ob_trade_name.fillna(""), ob.appl_no.fillna("")):
    add(tn, ap)
print(f"  + Orange Book  : {len(vocab):,}")

pbp = os.path.join(OUT, "purplebook_biologics.parquet")
if os.path.exists(pbp):
    pb = pd.read_parquet(pbp)
    for nm in pb.proper_name_norm.fillna(""): add(nm)
    for nm in pb.get("brand_name", pd.Series(dtype=str)).fillna(""): add(nm)
    print(f"  + Purple Book  : {len(vocab):,}")

zf = glob.glob(os.path.join(REF, "openfda_other_unii", "*.zip"))
if zf:
    with zipfile.ZipFile(zf[0]) as z:
        recs = json.loads(z.read(z.namelist()[0]))["results"]
    for r in recs:
        nm = r.get("substance_name", "")
        if len(nm) <= 60 and not any(c.isdigit() for c in nm[:6]):
            add(nm)
    print(f"  + UNII         : {len(vocab):,}")
    del recs; gc.collect()

# Open Targets synonyms resolve internal development codes (TAK-438 -> VONOPRAZAN).
# EXACT matching only: substring matching maps APATINIB onto LAPATINIB.
SYN = {}
import numpy as _np
_otd = os.path.join(os.path.dirname(OUT), "06_targets_genetics", "opentargets_26.09",
                    "drug_molecule")
_fs = glob.glob(os.path.join(_otd, "*.parquet"))
if _fs:
    _dm = pd.read_parquet(_fs[0], columns=["name", "synonyms", "tradeNames"])
    for _nm, _sy, _tn in zip(_dm.name, _dm.synonyms, _dm.tradeNames):
        _canon = normalise(_nm)
        if not _canon: continue
        SYN.setdefault(_canon, _canon)
        for _arr in (_sy, _tn):
            if isinstance(_arr, (list, _np.ndarray)):
                for _e in _arr:
                    _lab = _e.get("label") if isinstance(_e, dict) else _e
                    _k = normalise(str(_lab))
                    if len(_k) >= 3 and not is_placebo(_k):
                        SYN.setdefault(_k, _canon)
    print(f"  + OpenTargets synonyms: {len(SYN):,} keys")
    del _dm; gc.collect()

VOCAB = set(vocab)
BY_FIRST = {}
for v in VOCAB: BY_FIRST.setdefault(v[:3], []).append(v)
# de-salted index, and a head index so "ALENDRONATE" reaches "ALENDRONATE SODIUM"
DESALT = {}
HEAD = {}
for v in VOCAB:
    DESALT.setdefault(desalt(v), v)
    HEAD.setdefault(v.split()[0], v)

# ------------------------------------------------ trial side
print("\nresolving trial interventions ...", flush=True)
tr = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"),
                     columns=["nct_id", "drug_names", "start_year", "is_resolved"])
frame = tr[(tr.start_year.between(2008, 2019)) & (tr.is_resolved == 1)].copy()

def pick(names):
    """first non-placebo drug in the intervention list"""
    for n in str(names).split("|"):
        if n.strip() and not is_placebo(n):
            return n.strip()
    return ""

frame["raw"] = frame.drug_names.map(pick)
frame["norm"] = frame.raw.map(normalise)

cache = {}
def resolve(n):
    if n in cache: return cache[n]
    if not n or len(n) < 3: r = ("", "", "none", 0.0)
    elif n in VOCAB:        r = (n, vocab[n], "exact", 1.0)
    else:
        toks = n.split()
        hit = ""
        for k in range(len(toks), 0, -1):          # longest token run first
            for i in range(len(toks) - k + 1):
                cand = " ".join(toks[i:i+k])
                if cand in VOCAB and len(cand) >= 4:
                    hit = cand; break
            if hit: break
        if hit: r = (hit, vocab[hit], "token", 0.95)
        elif desalt(n) in VOCAB:
            m = desalt(n); r = (m, vocab[m], "desalt", 0.97)
        elif n in DESALT:
            m = DESALT[n]; r = (m, vocab[m], "desalt", 0.97)
        elif n in SYN:
            m = SYN[n]
            r = (m, vocab.get(m, "") or vocab.get(desalt(m), ""), "synonym", 0.94)
        else:
            best, bs = "", 0.0
            for c in BY_FIRST.get(n[:3], []):
                s = SequenceMatcher(None, n, c).ratio()
                if s > bs: best, bs = c, s
            ok = bs >= 0.93 and len(n) >= 6 and abs(len(n) - len(best)) <= 3
            r = (best, vocab.get(best, ""), "fuzzy", round(bs, 3)) if ok \
                else ("", "", "none", round(bs, 3))
    cache[n] = r
    return r

res = frame.norm.map(resolve)
frame["ingredient"] = [x[0] for x in res]
frame["appl_no"]    = [x[1] for x in res]
frame["method"]     = [x[2] for x in res]
frame["score"]      = [x[3] for x in res]
frame["is_placebo_only"] = frame.raw.eq("")
COMBO = re.compile(r"\b(AND|PLUS|WITH|COMBINATION|CO[- ]ADMINISTER\w*|\+)\b", re.I)
frame["is_combination"] = frame.norm.str.contains(COMBO, na=False).astype(int)

p = os.path.join(OUT, "trial_drug_resolution.parquet")
frame[["nct_id","raw","norm","ingredient","appl_no","method","score",
       "is_placebo_only","is_combination"]].to_parquet(p, index=False, compression="zstd")

n = len(frame); matched = (frame.method != "none").sum()
print(f"\n=== COVERAGE (frame N={n:,}) ===")
print(frame.method.value_counts().to_string())
print(f"\nresolved to an ingredient : {matched:,} ({matched/n:.1%})")
print(f"  with an FDA appl_no     : {(frame.appl_no != '').sum():,} "
      f"({(frame.appl_no != '').sum()/n:.1%})")
print(f"placebo/comparator only   : {int(frame.is_placebo_only.sum()):,}")
print(f"distinct ingredients      : {frame[frame.ingredient!=''].ingredient.nunique():,}")
print(f"combination regimens      : {int(frame.is_combination.sum()):,} "
      f"({frame.is_combination.mean():.1%}) - resolved to primary agent only")
print(f"vocabulary size           : {len(VOCAB):,}")
print("\nunresolved sample:")
for s in frame[frame.method=="none"].norm.head(12): print("   ", s[:66])
