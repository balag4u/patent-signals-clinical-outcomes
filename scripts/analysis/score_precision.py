#!/usr/bin/env python3
"""Score the adjudicated precision sample.

Because the sample over-represents risky methods, a raw mean of the verdicts
would UNDERSTATE true precision. Each stratum's observed precision is weighted
by that method's share of the resolved population.

  precision_overall = SUM_m ( pop_share_m * precision_m )

Variance uses the stratified estimator, so the confidence interval reflects the
design rather than pretending it was a simple random sample.
"""
import os, sys
import pandas as pd, numpy as np

VAL = sys.argv[1]
samp = pd.read_csv(os.path.join(VAL, "precision_sample_200.csv"))
wt   = pd.read_csv(os.path.join(VAL, "precision_sample_weights.csv"))

samp["verdict"] = samp.verdict.fillna("").str.strip().str.upper()
done = samp[samp.verdict.isin(["CORRECT", "WRONG", "PARTIAL"])]
if not len(done):
    print("No verdicts recorded yet. Fill the `verdict` column with "
          "CORRECT / WRONG / PARTIAL and re-run."); sys.exit(0)
print(f"adjudicated: {len(done)}/{len(samp)}")
if len(done) < len(samp):
    print("  (interval below is provisional until all rows are judged)")

# PARTIAL = right active ingredient, incomplete (e.g. combination truncated).
# Counted as correct for linkage precision; reported separately.
done = done.copy()
done["correct"] = done.verdict.isin(["CORRECT", "PARTIAL"]).astype(int)
done["strict"]  = done.verdict.eq("CORRECT").astype(int)

rows = []
for meth, g in done.groupby("method"):
    w = wt[wt.method == meth]
    share = float(w.pop_share.iloc[0]) if len(w) else 0.0
    n, k = len(g), int(g.correct.sum())
    p = k / n
    rows.append({"method": meth, "n_judged": n, "n_correct": k,
                 "precision": p, "strict_precision": g.strict.mean(),
                 "pop_share": share, "var_comp": share**2 * p*(1-p)/n})
r = pd.DataFrame(rows)
r["pop_share"] = r.pop_share / r.pop_share.sum()      # renormalise if partial
r["var_comp"]  = r.pop_share**2 * r.precision*(1-r.precision)/r.n_judged

overall = float((r.pop_share * r.precision).sum())
strict  = float((r.pop_share * r.strict_precision).sum())
se = float(np.sqrt(r.var_comp.sum()))
lo, hi = overall - 1.96*se, overall + 1.96*se

print("\n=== PRECISION BY METHOD ===")
print(r[["method","n_judged","n_correct","precision","strict_precision","pop_share"]]
      .round(4).to_string(index=False))
print("\n=== WEIGHTED OVERALL ===")
print(f"  precision (CORRECT or PARTIAL) : {overall:.4f}")
print(f"  strict precision (CORRECT only): {strict:.4f}")
print(f"  standard error                 : {se:.4f}")
print(f"  95% CI                         : [{lo:.4f}, {hi:.4f}]")
print(f"  meets the 90% target           : "
      f"{'YES' if lo >= 0.90 else 'NO - lower bound below 0.90' if overall>=0.90 else 'NO'}")
if (r.precision < 0.85).any():
    print("\n  methods below 0.85 - candidates for removal or tightening:")
    for _, x in r[r.precision < 0.85].iterrows():
        print(f"    {x.method}: {x.precision:.3f} (pop share {x.pop_share:.1%})")
w = done[done.verdict == "WRONG"]
if len(w):
    print(f"\n=== {len(w)} WRONG LINKS (fix the rule, not the row) ===")
    for _, x in w.head(12).iterrows():
        print(f"  [{x.method}] {str(x['norm'])[:42]:44s} -> {str(x.ingredient)[:30]}")
