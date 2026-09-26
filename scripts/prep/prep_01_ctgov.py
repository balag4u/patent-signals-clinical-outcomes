#!/usr/bin/env python3
"""CTgov raw API pages -> trial-level analysis table (Parquet).
Idempotent: re-run as more pages arrive."""
import json, os, sys, re
import pandas as pd

RAW = sys.argv[1]; OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)

def g(d, *ks, default=None):
    for k in ks:
        if not isinstance(d, dict): return default
        d = d.get(k)
        if d is None: return default
    return d

def norm_date(s):
    if not s: return None
    p = s.split("-")
    return f"{p[0]}-{p[1] if len(p)>1 else '01'}-{p[2] if len(p)>2 else '01'}"

TERM = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}

def flatten(st):
    p = st.get("protocolSection", {})
    ident, stat = p.get("identificationModule", {}), p.get("statusModule", {})
    des, spon = p.get("designModule", {}), p.get("sponsorCollaboratorsModule", {})
    ai, elig = p.get("armsInterventionsModule", {}), p.get("eligibilityModule", {})
    out, cl = p.get("outcomesModule", {}), p.get("contactsLocationsModule", {})
    cond = p.get("conditionsModule", {})
    locs = cl.get("locations") or []
    ivs = ai.get("interventions") or []
    crit = elig.get("eligibilityCriteria") or ""
    status = stat.get("overallStatus")
    drug_names = [(i.get("name") or "").strip() for i in ivs
                  if (i.get("type") or "").upper() in ("DRUG", "BIOLOGICAL")]
    return {
      "nct_id": ident.get("nctId"),
      "overall_status": status,
      # --- dependent variables ---
      "is_terminated": 1 if status in TERM else (0 if status == "COMPLETED" else None),
      "is_resolved": 1 if (status in TERM or status == "COMPLETED") else 0,
      "why_stopped": (stat.get("whyStopped") or "")[:500],
      "has_why_stopped": 1 if stat.get("whyStopped") else 0,
      # --- dates ---
      "start_date": norm_date(g(stat, "startDateStruct", "date")),
      "primary_completion_date": norm_date(g(stat, "primaryCompletionDateStruct", "date")),
      "completion_date": norm_date(g(stat, "completionDateStruct", "date")),
      "study_first_post": norm_date(g(stat, "studyFirstPostDateStruct", "date")),
      "results_first_post": norm_date(g(stat, "resultsFirstPostDateStruct", "date")),
      "has_results": int(bool(st.get("hasResults"))),
      # --- design IVs ---
      "phases": "|".join(des.get("phases") or []),
      "is_phase3": int("PHASE3" in (des.get("phases") or [])),
      "enrollment": g(des, "enrollmentInfo", "count"),
      "enrollment_type": g(des, "enrollmentInfo", "type"),
      "allocation": g(des, "designInfo", "allocation"),
      "is_randomized": int((g(des,"designInfo","allocation") or "") == "RANDOMIZED"),
      "intervention_model": g(des, "designInfo", "interventionModel"),
      "primary_purpose": g(des, "designInfo", "primaryPurpose"),
      "masking": g(des, "designInfo", "maskingInfo", "masking"),
      "who_masked_n": len(g(des, "designInfo", "maskingInfo", "whoMasked", default=[]) or []),
      "n_arms": len(ai.get("armGroups") or []),
      "n_interventions": len(ivs),
      "n_primary_outcomes": len(out.get("primaryOutcomes") or []),
      "n_secondary_outcomes": len(out.get("secondaryOutcomes") or []),
      "elig_criteria_chars": len(crit),
      "elig_criteria_lines": (crit.count("\n") + 1) if crit else 0,
      "sex": elig.get("sex"),
      "min_age": elig.get("minimumAge"),
      "max_age": elig.get("maximumAge"),
      "healthy_volunteers": int(bool(elig.get("healthyVolunteers"))),
      "n_locations": len(locs),
      "n_countries": len({l.get("country") for l in locs if l.get("country")}),
      "is_multinational": int(len({l.get("country") for l in locs if l.get("country")}) > 1),
      # --- sponsor IVs ---
      "lead_sponsor": g(spon, "leadSponsor", "name"),
      "lead_sponsor_class": g(spon, "leadSponsor", "class"),
      "is_industry": int((g(spon,"leadSponsor","class") or "") == "INDUSTRY"),
      "n_collaborators": len(spon.get("collaborators") or []),
      # --- linkage keys / context ---
      "drug_names": "|".join(drug_names)[:500],
      "primary_drug": (drug_names[0].upper() if drug_names else None),
      "conditions": "|".join(cond.get("conditions") or [])[:400],
      "primary_condition": ((cond.get("conditions") or [None])[0]),
      "countries": "|".join(sorted({l.get("country") or "" for l in locs}))[:400],
    }

rows = []
pages = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))
for fn in pages:
    try:
        d = json.load(open(os.path.join(RAW, fn)))
    except Exception as e:
        print(f"skip {fn}: {e}"); continue
    for st in d.get("studies", []):
        rows.append(flatten(st))

df = pd.DataFrame(rows).drop_duplicates(subset=["nct_id"])
for c in ["start_date","primary_completion_date","completion_date","study_first_post","results_first_post"]:
    df[c] = pd.to_datetime(df[c], errors="coerce")
df["start_year"] = df["start_date"].dt.year
# duration in months, for the survival RQ
df["months_to_primary_completion"] = (
    (df["primary_completion_date"] - df["start_date"]).dt.days / 30.44).round(2)
df["enrollment"] = pd.to_numeric(df["enrollment"], errors="coerce")

p = os.path.join(OUT, "ctgov_trials.parquet")
df.to_parquet(p, index=False, compression="zstd")
print(f"pages={len(pages)} rows={len(df):,} -> {p} ({os.path.getsize(p)/1e6:.1f} MB)")
res = df[df.is_resolved == 1]
print(f"resolved={len(res):,}  termination_rate={res.is_terminated.mean():.4f}")
ind = res[res.is_industry == 1]
print(f"industry resolved={len(ind):,}  termination_rate={ind.is_terminated.mean():.4f}")
