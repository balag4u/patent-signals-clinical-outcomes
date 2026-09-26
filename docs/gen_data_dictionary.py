#!/usr/bin/env python3
"""Regenerate docs/DATA_DICTIONARY.md from the analysis-ready tables.
Run after any prep script changes a schema:  python docs/gen_data_dictionary.py
"""
import os, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data", "analysis_ready")
out = ["# Data dictionary", "",
       "Generated from the analysis-ready tables by `docs/gen_data_dictionary.py`.",
       "Types are as stored in Parquet.", ""]
for f in sorted(os.listdir(D)):
    if not f.endswith(".parquet"): continue
    d = pd.read_parquet(os.path.join(D, f))
    out += [f"## `{f}`", "", f"{len(d):,} rows x {len(d.columns)} columns "
            f"({os.path.getsize(os.path.join(D, f))/1e6:.2f} MB)", "",
            "| Column | Type | Non-null | Example |", "|---|---|---|---|"]
    for c in d.columns:
        s = d[c].dropna()
        ex = str(s.iloc[0])[:38].replace("|", "\\|") if len(s) else ""
        out.append(f"| `{c}` | {d[c].dtype} | {len(s):,} | {ex} |")
    out.append("")
open(os.path.join(ROOT, "docs", "DATA_DICTIONARY.md"), "w").write("\n".join(out))
print(f"wrote docs/DATA_DICTIONARY.md ({len(out)} lines)")
