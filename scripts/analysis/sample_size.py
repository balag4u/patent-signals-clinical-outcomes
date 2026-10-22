#!/usr/bin/env python3
"""QM 640 Capstone - stepwise sample size calculation, RQ1-RQ4.
alpha=0.05 two-tailed, power=0.80. Uses the OBSERVED termination rate from
the ClinicalTrials.gov extract rather than an assumed value."""
import json
import math
from pathlib import Path
Z_A, Z_B = 1.959964, 0.841621     # z(1-0.05/2), z(0.80)
Z_SUM_SQ = (Z_A + Z_B) ** 2        # 7.848877
# Read from the analysis rather than pinned, so this file cannot drift from the
# frame again. The constants below were stale at p = 0.242701 (an earlier, wider
# frame of 49,596 resolved trials) while the report quoted 0.2217 from the final
# 39,437-trial frame, so the two disagreed on every one of the four requirements.
_R = json.loads((Path(__file__).resolve().parents[2] / "docs" /
                 "interim_results.json").read_text())
P_TERM = round(_R["frame"]["p_terminated"], 6)
                                   # (start 2008-2023, Phase II/III interventional drug)

print("=" * 72)
print("SAMPLE SIZE CALCULATION  |  alpha=0.05 (two-tailed), power=0.80")
print(f"(Z_a/2 + Z_b)^2 = ({Z_A:.6f} + {Z_B:.6f})^2 = {Z_SUM_SQ:.6f}")
print(f"Observed termination rate p = {P_TERM:.4f}")
print("=" * 72)

# ---------- RQ1: two independent proportions (Cohen's h) ----------
p1, p2 = P_TERM, P_TERM + 0.05   # observed base rate vs +5 percentage points
phi1, phi2 = 2*math.asin(math.sqrt(p1)), 2*math.asin(math.sqrt(p2))
h = abs(phi2 - phi1)
n1 = Z_SUM_SQ / h**2
print(f"\nRQ1  Two-proportion z-test (high-IP vs low-IP sponsors)")
print(f"  Step 1  p1={p1:.4f} (observed), p2={p2:.4f}")
print(f"  Step 2  phi1 = 2*arcsin(sqrt({p1:.4f})) = {phi1:.6f}")
print(f"          phi2 = 2*arcsin(sqrt({p2:.4f})) = {phi2:.6f}")
print(f"  Step 3  h = |phi2-phi1| = {h:.6f}  (small effect)")
print(f"  Step 4  n/group = {Z_SUM_SQ:.6f} / {h:.6f}^2 = {n1:.1f} -> {math.ceil(n1)}")
RQ1 = 2*math.ceil(n1); print(f"  RQ1 N = 2 x {math.ceil(n1)} = {RQ1}")

# ---------- RQ2: multivariable prediction model (EPV) ----------
K, EPV = 45, 10
events = K*EPV
n2 = events / P_TERM
print(f"\nRQ2  Penalized logistic regression + gradient boosting (EPV rule)")
print(f"  Step 1  candidate predictors k = {K}")
print(f"  Step 2  events required = k x EPV = {K} x {EPV} = {events}")
print(f"  Step 3  N = events / p = {events} / {P_TERM:.4f} = {n2:.1f}")
RQ2 = math.ceil(n2); print(f"  RQ2 N = {RQ2}")

# ---------- RQ3: Cox proportional hazards (Schoenfeld) ----------
HR, pa = 1.25, 0.50
lnhr2 = math.log(HR)**2
d = Z_SUM_SQ / (pa*(1-pa)*lnhr2)
event_frac = round(_R["frame"]["completed"] / _R["frame"]["analytic_n"], 6)
n3 = math.ceil(d) / event_frac
print(f"\nRQ3  Cox proportional hazards (Schoenfeld event-driven formula)")
print(f"  Step 1  HR = {HR}, ln(HR) = {math.log(HR):.6f}, ln(HR)^2 = {lnhr2:.6f}")
print(f"  Step 2  allocation p = {pa}, p(1-p) = {pa*(1-pa):.4f}")
print(f"  Step 3  d = {Z_SUM_SQ:.6f} / ({pa*(1-pa):.4f} x {lnhr2:.6f}) = {d:.1f} events")
print(f"  Step 4  N = ceil(d) / event fraction = {math.ceil(d)} / {event_frac} = {n3:.1f}")
RQ3 = math.ceil(n3); print(f"  RQ3 N = {RQ3}")

# ---------- RQ4: CI method per therapeutic-area stratum ----------
E, STRATA = 0.03, 6
Z2 = Z_A**2
n_str = Z2 * P_TERM*(1-P_TERM) / E**2
print(f"\nRQ4  Moderation by therapeutic area (CI method, per stratum)")
print(f"  Step 1  Z^2 = {Z_A:.6f}^2 = {Z2:.6f}")
print(f"  Step 2  p(1-p) = {P_TERM:.4f} x {1-P_TERM:.4f} = {P_TERM*(1-P_TERM):.6f}")
print(f"  Step 3  margin E = {E}, E^2 = {E**2:.5f}")
print(f"  Step 4  n/stratum = {Z2:.6f} x {P_TERM*(1-P_TERM):.6f} / {E**2:.5f} = {n_str:.1f} -> {math.ceil(n_str)}")
print(f"  Step 5  strata = {STRATA}")
RQ4 = STRATA*math.ceil(n_str); print(f"  RQ4 N = {STRATA} x {math.ceil(n_str)} = {RQ4}")

# ---------- decision ----------
allN = {"RQ1": RQ1, "RQ2": RQ2, "RQ3": RQ3, "RQ4": RQ4}
FINAL = max(allN.values()); which = max(allN, key=allN.get)
print("\n" + "=" * 72)
for k, v in allN.items(): print(f"  {k}: {v:>6,}")
print(f"\n  FINAL N = max(RQ1..RQ4) = {FINAL:,}   (binding constraint: {which})")
print("=" * 72)
