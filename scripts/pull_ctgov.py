#!/usr/bin/env python3
"""Pull Phase 2/3 interventional drug trials from ClinicalTrials.gov API v2.
Writes raw JSON pages (reproducibility) + flattened CSV (analysis)."""
import json, os, sys, time, csv, urllib.parse, urllib.request

OUT = sys.argv[1]
RAW = os.path.join(OUT, "raw_pages"); os.makedirs(RAW, exist_ok=True)
FILT = ("AREA[StudyType]INTERVENTIONAL AND AREA[Phase](PHASE2 OR PHASE3) "
        "AND AREA[InterventionType]DRUG")
BASE = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ("IdentificationModule,StatusModule,SponsorCollaboratorsModule,DesignModule,"
          "ArmsInterventionsModule,OutcomesModule,ConditionsModule,EligibilityModule,"
          "ContactsLocationsModule")

def fetch(token=None, tries=5):
    q = {"pageSize": "1000", "filter.advanced": FILT, "countTotal": "true", "fields": FIELDS}
    if token: q["pageToken"] = token
    url = BASE + "?" + urllib.parse.urlencode(q)
    for a in range(tries):
        try:
            rq = urllib.request.Request(url, headers={"Accept": "application/json",
                 "User-Agent": "WalshCollege-QM640-Research/1.0"})
            with urllib.request.urlopen(rq, timeout=300) as r:
                return json.load(r)
        except Exception as e:
            if a == tries - 1: raise
            time.sleep(8 * (a + 1))

def g(d, *ks, default=None):
    for k in ks:
        if not isinstance(d, dict): return default
        d = d.get(k)
        if d is None: return default
    return d

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
    return {
      "nct_id": ident.get("nctId"),
      "brief_title": (ident.get("briefTitle") or "")[:300],
      "overall_status": stat.get("overallStatus"),
      "why_stopped": (stat.get("whyStopped") or "")[:500],
      "start_date": g(stat, "startDateStruct", "date"),
      "primary_completion_date": g(stat, "primaryCompletionDateStruct", "date"),
      "completion_date": g(stat, "completionDateStruct", "date"),
      "study_first_post": g(stat, "studyFirstPostDateStruct", "date"),
      "results_first_post": g(stat, "resultsFirstPostDateStruct", "date"),
      "has_results": bool(st.get("hasResults")),
      "phases": "|".join(des.get("phases") or []),
      "enrollment": g(des, "enrollmentInfo", "count"),
      "enrollment_type": g(des, "enrollmentInfo", "type"),
      "allocation": g(des, "designInfo", "allocation"),
      "intervention_model": g(des, "designInfo", "interventionModel"),
      "primary_purpose": g(des, "designInfo", "primaryPurpose"),
      "masking": g(des, "designInfo", "maskingInfo", "masking"),
      "who_masked_n": len(g(des, "designInfo", "maskingInfo", "whoMasked", default=[]) or []),
      "lead_sponsor": g(spon, "leadSponsor", "name"),
      "lead_sponsor_class": g(spon, "leadSponsor", "class"),
      "n_collaborators": len(spon.get("collaborators") or []),
      "n_arms": len(ai.get("armGroups") or []),
      "n_interventions": len(ivs),
      "intervention_names": "|".join((i.get("name") or "")[:60] for i in ivs)[:600],
      "intervention_types": "|".join(sorted({i.get("type") or "" for i in ivs})),
      "conditions": "|".join(cond.get("conditions") or [])[:400],
      "n_primary_outcomes": len(out.get("primaryOutcomes") or []),
      "n_secondary_outcomes": len(out.get("secondaryOutcomes") or []),
      "eligibility_criteria_chars": len(crit),
      "eligibility_criteria_lines": crit.count("\n") + 1 if crit else 0,
      "sex": elig.get("sex"), "min_age": elig.get("minimumAge"),
      "max_age": elig.get("maximumAge"),
      "healthy_volunteers": elig.get("healthyVolunteers"),
      "n_locations": len(locs),
      "n_countries": len({l.get("country") for l in locs if l.get("country")}),
      "countries": "|".join(sorted({l.get("country") or "" for l in locs}))[:400],
    }

rows, token, page, total = [], None, 0, None
while True:
    d = fetch(token)
    if total is None:
        total = d.get("totalCount"); print(f"totalCount={total}", flush=True)
    page += 1
    with open(os.path.join(RAW, f"page_{page:04d}.json"), "w") as f:
        json.dump(d, f)
    for st in d.get("studies", []):
        rows.append(flatten(st))
    token = d.get("nextPageToken")
    print(f"page {page}: {len(rows)} rows", flush=True)
    if not token: break
    time.sleep(0.4)

cols = list(rows[0].keys())
csvp = os.path.join(OUT, "ctgov_phase23_drug_trials.csv")
with open(csvp, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f"DONE rows={len(rows)} pages={page} -> {csvp}", flush=True)
