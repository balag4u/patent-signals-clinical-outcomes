"""Score trials for early-termination risk with the saved model.

Batch scoring for portfolio review. Reads a table of trials carrying the model's
predictor columns (Parquet or CSV), and writes one row per trial with the
recalibrated risk, its decile against the 2016-2019 reference distribution, a
review flag at the threshold fixed on the validation period, and the three
predictors that pushed that trial's score up or down the most (SHAP values).

The predictors must be computed exactly as in scripts/analysis/interim_eda.py,
using only information dated at or before each trial's start, or the score is
not valid. The output is decision support for a human reviewer, not a funding
rule.

    python scripts/deploy/score_trials.py INPUT.parquet OUTPUT.csv
"""

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap

ROOT = Path(__file__).resolve().parents[2]
ART = joblib.load(ROOT / "models" / "termination_model.joblib")


def main(src, dst):
    df = pd.read_parquet(src) if str(src).endswith(".parquet") else pd.read_csv(src)
    missing = [c for c in ART["features"] if c not in df.columns]
    if missing:
        sys.exit(f"input lacks {len(missing)} predictor columns, e.g. {missing[:5]}")
    X = df[ART["features"]]
    raw = np.clip(ART["model"].predict_proba(X)[:, 1], 1e-9, 1 - 1e-9)
    risk = 1 / (1 + np.exp(-(np.log(raw / (1 - raw)) + ART["calibration_offset"])))
    edges = np.asarray(ART["reference_decile_edges"])
    decile = np.clip(np.searchsorted(edges, risk, side="right"), 1, 10)
    sv = shap.TreeExplainer(ART["model"]).shap_values(X)
    drivers = []
    for row in sv:
        top = np.argsort(-np.abs(row))[:3]
        drivers.append("; ".join(
            f"{ART['features'][j]} ({'raises' if row[j] > 0 else 'lowers'} risk)" for j in top))
    out = pd.DataFrame({
        "nct_id": df["nct_id"] if "nct_id" in df.columns else np.arange(len(df)),
        "termination_risk": risk.round(4),
        "risk_decile": decile,
        "flag_for_review": (risk >= ART["threshold_recalibrated"]).astype(int),
        "top_drivers": drivers,
    })
    out.to_csv(dst, index=False)
    print(f"scored {len(out):,} trials -> {dst}  ({int(out.flag_for_review.sum()):,} flagged)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
