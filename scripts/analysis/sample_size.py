#!/usr/bin/env python3
"""QM 640 Capstone - stepwise sample size calculation, RQ1-RQ4.

alpha = 0.05 two-tailed and power = 0.80 throughout. Every event probability is the
OBSERVED one from the analytic frame, read from docs/interim_results.json rather
than pinned here, so this file cannot drift from the analysis. The results, with
every intermediate quantity, are written to docs/sample_size.json so the report
quotes them as data rather than retyping them.

Each research question is sized by a power or confidence-interval method matched
to the test that answers it:

  RQ1  two independent proportions, Cohen's h, inflated by the design effect for
       trials clustered within sponsor groups (Donner & Klar, 2000).
  RQ2  power for the paired difference between two correlated AUCs on the same
       held-out trials (Hanley & McNeil, 1982, 1983), the test behind H2b. The
       power for H2a and the confidence-interval width for the AUC are computed as
       checks. An earlier version sized RQ2 by events per variable, which is a
       rule of thumb for coefficient stability rather than a power or precision
       calculation, and is no longer used.
  RQ3  Schoenfeld (1983) events for a proportional-hazards contrast, computed for
       BOTH competing causes and converted to trials by each cause's observed
       probability (Latouche et al., 2004).
  RQ4  the confidence-interval method for each stratum's proportion, AND the power
       to detect an interaction, a difference between two strata in the risk
       difference, which the precision calculation alone does not establish.

    python scripts/analysis/sample_size.py
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = json.loads((ROOT / "docs" / "interim_results.json").read_text())
OUT = ROOT / "docs" / "sample_size.json"

Z_A, Z_B = 1.959964, 0.841621          # z(1 - 0.05/2), z(0.80)
Z_SUM = Z_A + Z_B
Z_SUM_SQ = Z_SUM ** 2
P = round(R["frame"]["p_terminated"], 4)            # 0.2217, termination
Q = round(1 - P, 4)                                  # 0.7783, completion
PQ = P * Q
out = {"alpha": 0.05, "power": 0.80, "z_alpha_2": Z_A, "z_beta": Z_B,
       "z_sum_sq": round(Z_SUM_SQ, 6), "p_terminated": P, "p_completed": Q,
       "pq": round(PQ, 6)}

print("=" * 76)
print("SAMPLE SIZE  |  alpha = 0.05 two-tailed, power = 0.80")
print(f"(z_a/2 + z_b)^2 = ({Z_A} + {Z_B})^2 = {Z_SUM_SQ:.6f}")
print(f"observed p(termination) = {P}, p(completion) = {Q}, pq = {PQ:.6f}")
print("=" * 76)

# ---------------------------------------------------------------------------
# RQ1  two independent proportions, Cohen's h, then the clustering design effect
# ---------------------------------------------------------------------------
DELTA1 = 0.05
p1, p2 = P, round(P + DELTA1, 4)
phi1, phi2 = 2 * math.asin(math.sqrt(p1)), 2 * math.asin(math.sqrt(p2))
h = phi2 - phi1
# Var(phi_hat) = 1/n, so Var(phi1_hat - phi2_hat) = 2/n for two groups of n, and
# n per group = 2 (z_a/2 + z_b)^2 / h^2. The earlier calculation used (z)^2 / h^2,
# the one-sample form, which halves the requirement.
n1_raw = 2 * Z_SUM_SQ / h ** 2
n1 = math.ceil(n1_raw)
C = R["rq1_clustered"]
ICC, M0 = C["icc"], C["mean_cluster_size_m0"]
DEFF = 1 + (M0 - 1) * ICC
n1_cl = math.ceil(n1 * DEFF)
out["rq1"] = {
    "method": "two independent proportions, Cohen's h, with design effect for clustering",
    "p1": p1, "p2": p2, "delta": DELTA1, "relative_change": round(DELTA1 / P, 4),
    "phi1": round(phi1, 6), "phi2": round(phi2, 6), "h": round(h, 6),
    "n_per_group_unclustered_raw": round(n1_raw, 2), "n_per_group_unclustered": n1,
    "n_total_unclustered": 2 * n1,
    "icc": ICC, "m0": M0, "design_effect": round(DEFF, 4),
    "n_per_group": n1_cl, "n_total": 2 * n1_cl,
    "available_per_group": min(R["rq1"]["n_strong"], R["rq1"]["n_weak"]),
    "available_total": R["rq1"]["n_computable"],
    "n_clusters_available": C["n_clusters"],
}
print("\nRQ1  two-proportion test, strong vs weak sponsor patent position")
print(f"  1  p1 = {p1} (observed), p2 = p1 + {DELTA1} = {p2}")
print(f"  2  phi1 = 2 asin(sqrt({p1})) = {phi1:.6f}; phi2 = 2 asin(sqrt({p2})) = {phi2:.6f}")
print(f"  3  h = phi2 - phi1 = {h:.6f}")
print(f"  4  n/group = 2 x {Z_SUM_SQ:.6f} / {h:.6f}^2 = {n1_raw:.2f} -> {n1}")
print(f"  5  DEFF = 1 + (m0 - 1) ICC = 1 + ({M0} - 1) x {ICC} = {DEFF:.4f}")
print(f"  6  n/group = {n1} x {DEFF:.4f} = {n1 * DEFF:.1f} -> {n1_cl};  N = {2 * n1_cl:,}")

# ---------------------------------------------------------------------------
# RQ2  correlated AUCs on the same held-out trials (Hanley & McNeil, 1982, 1983)
# ---------------------------------------------------------------------------
K = Q / P                                   # non-events per event


def per_event_var(a):
    """Hanley & McNeil (1982) variance of an AUC, times the number of events, for
    large samples with K non-events per event: [Q1 - A^2 + K (Q2 - A^2)] / K."""
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    return (q1 - a * a + K * (q2 - a * a)) / K, q1, q2


A0, A1, DELTA2, RHO = 0.65, 0.66, 0.01, 0.95
v0, q1_0, q2_0 = per_event_var(A0)
v1, q1_1, q2_1 = per_event_var(A1)
v_diff = v0 + v1 - 2 * RHO * math.sqrt(v0 * v1)
ev_b = Z_SUM_SQ * v_diff / DELTA2 ** 2
ev_b_n = math.ceil(ev_b)
n2b = math.ceil(ev_b_n / P)
# H2a: AUC 0.65 against chance, variance under each hypothesis
vh0, _, _ = per_event_var(0.5)
ev_a = ((Z_A * math.sqrt(vh0) + Z_B * math.sqrt(v0)) / (A0 - 0.5)) ** 2
n2a = math.ceil(math.ceil(ev_a) / P)
# precision: 95% CI half-width of 0.025 around AUC 0.65
E_AUC = 0.025
ev_c = Z_A ** 2 * v0 / E_AUC ** 2
n2c = math.ceil(math.ceil(ev_c) / P)
# How much the answer depends on the assumed correlation between the two AUCs. The
# realised correlation is measured from the paired bootstrap in final_analysis.py.
rho_sens = {}
for r_ in (0.90, 0.95):
    vd = v0 + v1 - 2 * r_ * math.sqrt(v0 * v1)
    ev = math.ceil(Z_SUM_SQ * vd / DELTA2 ** 2)
    rho_sens[str(r_)] = {"events": ev, "n_total": math.ceil(ev / P)}
out["rq2"] = {
    "method": "power for the paired difference of two correlated AUCs (H2b)",
    "auc_reference": A0, "auc_alternative": A1, "delta_auc": DELTA2, "rho": RHO,
    "k_nonevents_per_event": round(K, 4),
    "q1_ref": round(q1_0, 6), "q2_ref": round(q2_0, 6),
    "q1_alt": round(q1_1, 6), "q2_alt": round(q2_1, 6),
    "per_event_var_ref": round(v0, 6), "per_event_var_alt": round(v1, 6),
    "per_event_var_diff": round(v_diff, 6),
    "events_raw": round(ev_b, 2), "events": ev_b_n, "n_total": n2b,
    "check_h2a_auc_vs_chance": {"auc_null": 0.5, "auc_alt": A0,
                                "per_event_var_null": round(vh0, 6),
                                "events": math.ceil(ev_a), "n_total": n2a},
    "check_ci_precision": {"half_width": E_AUC, "events": math.ceil(ev_c), "n_total": n2c},
    "rho_sensitivity": rho_sens,
    "applies_to": "the held-out evaluation set, where H2a and H2b are tested",
    "available_test_n": R["rq2_split"]["test_n"],
    "available_test_events": R["rq2_split"]["test_terminated"],
    "training_events_per_candidate_predictor": round(
        (R["frame"]["terminated"] - R["rq2_split"]["test_terminated"])
        / len(R["missingness"]), 1),
}
print("\nRQ2  H2b: paired difference in AUC from adding the patent block")
print(f"  1  K = {Q}/{P} = {K:.4f} non-events per event")
print(f"  2  A = {A0}: Q1 = {q1_0:.6f}, Q2 = {q2_0:.6f}, V/event = {v0:.6f}")
print(f"     A = {A1}: Q1 = {q1_1:.6f}, Q2 = {q2_1:.6f}, V/event = {v1:.6f}")
print(f"  3  Var(diff)/event = {v0:.6f} + {v1:.6f} - 2 x {RHO} x sqrt(...) = {v_diff:.6f}")
print(f"  4  events = {Z_SUM_SQ:.6f} x {v_diff:.6f} / {DELTA2}^2 = {ev_b:.1f} -> {ev_b_n}")
print(f"  5  N = {ev_b_n} / {P} = {ev_b_n / P:.1f} -> {n2b:,}")
print(f"     check H2a (0.65 vs 0.50): {math.ceil(ev_a)} events, N = {n2a:,}")
print(f"     check CI half-width {E_AUC}: {math.ceil(ev_c)} events, N = {n2c:,}")
print(f"     sensitivity to rho: " + ", ".join(
    f"rho {k}: {v['events']} events, N = {v['n_total']:,}" for k, v in rho_sens.items()))

# ---------------------------------------------------------------------------
# RQ3  Schoenfeld (1983) events, for each competing cause
# ---------------------------------------------------------------------------
HR, ALLOC = 1.25, 0.50
ln2 = math.log(HR) ** 2
d_raw = Z_SUM_SQ / (ALLOC * (1 - ALLOC) * ln2)
d = math.ceil(d_raw)
n3_comp = math.ceil(d / Q)
n3_term = math.ceil(d / P)
out["rq3"] = {
    "method": "Schoenfeld events for each cause, converted by that cause's probability",
    "hr": HR, "ln_hr_sq": round(ln2, 6), "allocation": ALLOC,
    "events_raw": round(d_raw, 2), "events": d,
    "n_completion": n3_comp, "n_termination": n3_term, "n_total": max(n3_comp, n3_term),
    "binding_cause": "termination" if n3_term >= n3_comp else "completion",
    "available_n": R["rq3"]["cox_completion"]["n"],
    "available_completion_events": R["rq3"]["cox_completion"]["events"],
    "available_termination_events": R["rq3"]["cox_termination"]["events"],
}
print("\nRQ3  Schoenfeld, both causes")
print(f"  1  ln(HR)^2 = ln({HR})^2 = {ln2:.6f}; allocation {ALLOC}, pi(1-pi) = 0.25")
print(f"  2  d = {Z_SUM_SQ:.6f} / (0.25 x {ln2:.6f}) = {d_raw:.2f} -> {d} events per cause")
print(f"  3  completion:  N = {d} / {Q} = {d / Q:.1f} -> {n3_comp:,}")
print(f"     termination: N = {d} / {P} = {d / P:.1f} -> {n3_term:,}")

# ---------------------------------------------------------------------------
# RQ4  per-stratum precision, then power for the interaction
# ---------------------------------------------------------------------------
E4, STRATA = 0.03, 6
n4a_raw = Z_A ** 2 * PQ / E4 ** 2
n4a = math.ceil(n4a_raw)
DELTA4 = 0.10       # a 5-point gap in one area and the reverse 5 points in another
n4b_raw = Z_SUM_SQ * 4 * PQ / DELTA4 ** 2
n4b = math.ceil(n4b_raw)
cells = R.get("rq4_cells", [])
under = [c["area"] for c in cells if min(c["n_strong"], c["n_weak"]) < n4b]
out["rq4"] = {
    "method": "CI precision per stratum, and power for a difference in risk differences",
    "precision": {"margin": E4, "z_sq": round(Z_A ** 2, 6), "n_per_stratum_raw": round(n4a_raw, 2),
                  "n_per_stratum": n4a, "strata": STRATA, "n_total": STRATA * n4a},
    "interaction": {"delta_rd": DELTA4, "n_per_cell_raw": round(n4b_raw, 2),
                    "n_per_cell": n4b, "n_per_stratum": 2 * n4b,
                    "n_total": STRATA * 2 * n4b},
    "n_total": max(STRATA * n4a, STRATA * 2 * n4b),
    "available_n": R["rq4_moderation"]["n"],
    "cells": cells,
    "strata_below_cell_requirement": under,
}
print("\nRQ4  moderation by therapeutic area")
print(f"  a  precision: n = {Z_A ** 2:.6f} x {PQ:.6f} / {E4}^2 = {n4a_raw:.1f} -> {n4a} "
      f"per stratum; x {STRATA} = {STRATA * n4a:,}")
print(f"  b  interaction: n/cell = {Z_SUM_SQ:.6f} x 4 x {PQ:.6f} / {DELTA4}^2 = "
      f"{n4b_raw:.1f} -> {n4b}; per stratum {2 * n4b:,}; x {STRATA} = {STRATA * 2 * n4b:,}")
if cells:
    print(f"     strata with a cell below {n4b} in the usable subsample: {under or 'none'}")

# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------
req = {"RQ1": out["rq1"]["n_total"], "RQ2": out["rq2"]["n_total"],
       "RQ3": out["rq3"]["n_total"], "RQ4": out["rq4"]["n_total"]}
final = max(req.values())
out["required"] = req
out["final_n"] = final
out["binding"] = max(req, key=req.get)
OUT.write_text(json.dumps(out, indent=2))
print("\n" + "=" * 76)
for k, v in req.items():
    print(f"  {k}: {v:>7,}")
print(f"  FINAL N = max(RQ1..RQ4) = {final:,}  (binding: {out['binding']})")
print(f"wrote {OUT.relative_to(ROOT)}")
print("=" * 76)
