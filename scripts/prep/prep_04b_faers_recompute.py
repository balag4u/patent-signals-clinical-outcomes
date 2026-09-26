#!/usr/bin/env python3
"""Recompute FAERS disproportionality from the saved 2x2 cells.

prep_04 shipped a mangled chi-square, so is_signal was 0 for all 4.08M pairs,
and PRR was summarised with a mean over sparse cells (a=1 against a rare event
gives an unbounded ratio), which produced nonsense sponsor burdens.

Because a, b, c and d were persisted, both can be fixed without re-reading the
7 GB of quarterly extracts.
"""
import os, sys
import numpy as np, pandas as pd
OUT = sys.argv[1]
p = os.path.join(OUT, "faers_drug_event_signals.parquet")
df = pd.read_parquet(p)
print(f"loaded {len(df):,} drug-event pairs", flush=True)

a, b, c, d = (df[x].astype(float) for x in "abcd")
tot = a + b + c + d
with np.errstate(divide="ignore", invalid="ignore"):
    df["prr"] = (a / (a + b)) / (c / (c + d))
    df["ror"] = (a * d) / (b * c)
    df["chi2"] = (tot * (np.abs(a*d - b*c) - tot/2)**2
                  / ((a+b) * (c+d) * (a+c) * (b+d)))
    se = np.sqrt(1/a + 1/b + 1/c + 1/d)
    df["ror_lo"] = np.exp(np.log(df.ror) - 1.96*se)
    df["ror_hi"] = np.exp(np.log(df.ror) + 1.96*se)
df = df.replace([np.inf, -np.inf], np.nan)
# Evans, Waller & Davis (2001)
df["is_signal"] = ((df.a >= 3) & (df.prr >= 2) & (df.chi2 >= 4)).astype(int)
df.to_parquet(p, index=False, compression="zstd")
print(f"chi2   : median={df.chi2.median():.3f}  max={df.chi2.max():,.0f}")
print(f"signals: {int(df.is_signal.sum()):,} ({df.is_signal.mean():.2%} of pairs)")

ev = df[df.a >= 3]
burden = df.groupby("ingredient").agg(
    n_events=("pt","nunique"), n_reports=("a","sum"),
    n_signals=("is_signal","sum")).reset_index()
burden = burden.merge(
    ev.groupby("ingredient").agg(median_prr=("prr","median"),
                                 p90_prr=("prr", lambda x: x.quantile(0.9)),
                                 n_evaluable=("prr","size")).reset_index(),
    on="ingredient", how="left")
burden["signal_rate"] = (burden.n_signals / burden.n_events).round(4)
bp = os.path.join(OUT, "faers_drug_burden.parquet")
burden.to_parquet(bp, index=False, compression="zstd")
print(f"\ningredients: {len(burden):,}")
print(f"  median_prr across ingredients: median={burden.median_prr.median():.3f} "
      f"p99={burden.median_prr.quantile(.99):.2f}")
print(f"  ingredients with >=1 signal  : {int((burden.n_signals>0).sum()):,}")
print("\ntop 8 ingredients by signal count:")
print(burden.nlargest(8, "n_signals")[
    ["ingredient","n_events","n_signals","median_prr"]].to_string(index=False))
