"""Exploratory analysis and preliminary models for the interim report.

Everything the interim report asserts about the data is computed here, so a number
in the report can be traced to a line of code rather than to a notebook cell that
has since been re-run. Writes figures to docs/figures/ and a machine-readable
record of every statistic to docs/interim_results.json.

Run from the repository root:

    python scripts/analysis/interim_eda.py

The analytic frame is fixed by the study design: interventional Phase II/III drug
trials with a start date in 2008-2019 and a resolved outcome. The window closes at
2019 because resolution is still accruing after that, and calendar year is excluded
from the predictors for the same reason.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2 as chi2_dist
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    brier_score_loss,
    confusion_matrix,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.proportion import proportion_confint, proportions_ztest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "analysis_ready"
FIGS = ROOT / "docs" / "figures"
OUT = ROOT / "docs" / "interim_results.json"

START_MIN, START_MAX = 2008, 2019
TRAIN_MAX, TEST_MIN = 2015, 2016
SEED = 42

# Figure styling. Light surface only: these are print figures for an APA document,
# and the palette slots are used in documented order so the colour-blind separation
# checks that validated the palette still hold.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_SOFT, GRID = "#0b0b0b", "#52514e", "#d8d7d2"

plt.rcParams.update(
    {
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "font.size": 9,
        "font.family": "DejaVu Sans",
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK,
        "axes.titlesize": 10,
        "axes.titleweight": "semibold",
        "axes.titlecolor": INK,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": INK_SOFT,
        "ytick.color": INK_SOFT,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)

results: dict = {}


def tidy(ax, *, hide_x_grid=True):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if hide_x_grid:
        ax.xaxis.grid(False)
    return ax


def save(fig, name):
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    path = FIGS / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")


# ----------------------------------------------------------------------------
# 1. Frame construction - the numbers behind the data-cleaning log
# ----------------------------------------------------------------------------
print("\n[1] Frame construction")

trials = pd.read_parquet(DATA / "ctgov_trials.parquet")
ip = pd.read_parquet(DATA / "ip_index.parquet")
res = pd.read_parquet(DATA / "trial_drug_resolution.parquet")
ob = pd.read_parquet(DATA / "orangebook_ip.parquet")
reg = pd.read_parquet(DATA / "drugsatfda_regulatory.parquet")

retrieved = len(trials)
dup_nct = int(trials.nct_id.duplicated().sum())
in_window = trials.start_year.between(START_MIN, START_MAX)
n_window = int(in_window.sum())
frame = trials[in_window & (trials.is_resolved == 1)].copy()

results["frame"] = {
    "retrieved": retrieved,
    "duplicate_nct_ids": dup_nct,
    "in_window_2008_2019": n_window,
    "unresolved_dropped": int(n_window - len(frame)),
    "analytic_n": len(frame),
    "terminated": int(frame.is_terminated.sum()),
    "completed": int((frame.is_terminated == 0).sum()),
    "p_terminated": round(float(frame.is_terminated.mean()), 6),
    "industry_n": int(frame.is_industry.sum()),
}
print(f"  retrieved {retrieved:,} -> in window {n_window:,} -> resolved {len(frame):,}")
print(f"  duplicate NCT ids: {dup_nct}  |  p(termination) = {frame.is_terminated.mean():.4f}")

# Right-censoring evidence: resolution rate by start year over the full retrieval,
# which is what justifies closing the window at 2019 rather than at the extract date.
by_year = (
    trials[trials.start_year.between(2008, 2023)]
    .groupby("start_year")
    .agg(n=("nct_id", "size"), resolved=("is_resolved", "mean"))
)
resolved_only = trials[(trials.is_resolved == 1) & trials.start_year.between(2008, 2023)]
by_year["p_term_resolved"] = resolved_only.groupby("start_year").is_terminated.mean()
results["censoring_by_year"] = {
    int(y): {
        "n": int(r.n),
        "resolution_rate": round(float(r.resolved), 4),
        "p_term_among_resolved": round(float(r.p_term_resolved), 4),
    }
    for y, r in by_year.iterrows()
}

# ----------------------------------------------------------------------------
# 2. Sponsor history, computed from past-only information
# ----------------------------------------------------------------------------
print("\n[2] Sponsor history (past-only)")

frame = frame.sort_values("start_date")
g = frame.groupby("lead_sponsor")
frame["sponsor_prior_trials"] = g.cumcount()
frame["sponsor_prior_terminations"] = g["is_terminated"].cumsum() - frame["is_terminated"]
frame["sponsor_prior_completion_rate"] = np.where(
    frame.sponsor_prior_trials > 0,
    1 - frame.sponsor_prior_terminations / frame.sponsor_prior_trials,
    np.nan,
)
first_trial = int((frame.sponsor_prior_trials == 0).sum())
print(f"  sponsor_prior_completion_rate undefined for {first_trial:,} first-ever trials")

# ----------------------------------------------------------------------------
# 3. Linkage: trial -> FDA application -> regulatory and drug-level IP blocks
# ----------------------------------------------------------------------------
print("\n[3] Linkage coverage")

link = res[["nct_id", "appl_no", "ingredient", "method", "score"]].drop_duplicates("nct_id")
# The resolution table records a failed match as an empty string rather than a null,
# so coverage has to be counted on emptiness; left as-is it reads as 100 percent and
# an empty key would join against any empty key on the other side.
for col in ("appl_no", "ingredient"):
    link[col] = link[col].replace("", pd.NA)
frame = frame.merge(link, on="nct_id", how="left")
frame = frame.merge(reg, on="appl_no", how="left")
ob_cols = [
    "appl_no",
    "ob_n_patents",
    "ob_n_primary_patents",
    "ob_n_secondary_patents",
    "ob_evergreen_ratio",
    "ob_patent_span_years",
    "ob_n_exclusivities",
]
frame = frame.merge(ob[ob_cols].drop_duplicates("appl_no"), on="appl_no", how="left")
frame = frame.merge(
    ip[["nct_id", "ip_index", "ip_index_sponsor", "ip_strong", "ip_tertile_extreme", "ob_term_remaining_yrs"]],
    on="nct_id",
    how="left",
)

results["linkage"] = {
    "resolved_to_ingredient": int(frame.ingredient.notna().sum()),
    "resolved_to_ingredient_pct": round(float(frame.ingredient.notna().mean() * 100), 2),
    "resolved_to_application": int(frame.appl_no.notna().sum()),
    "resolved_to_application_pct": round(float(frame.appl_no.notna().mean() * 100), 2),
    "with_regulatory_block": int(frame.fda_appl_type.notna().sum()),
    "with_drug_level_ip": int(frame.ob_n_patents.notna().sum()),
    "with_drug_level_ip_pct": round(float(frame.ob_n_patents.notna().mean() * 100), 2),
    "with_sponsor_level_ip": int(frame.ip_index_sponsor.notna().sum()),
}
print(f"  resolved to an FDA ingredient: {frame.ingredient.notna().sum():,}")
print(f"  linked to an FDA application: {frame.appl_no.notna().sum():,}")
print(f"  drug-level IP observable:     {frame.ob_n_patents.notna().sum():,}")
print(f"  sponsor-level IP observable:  {frame.ip_index_sponsor.notna().sum():,} (BigQuery pull pending)")

# ----------------------------------------------------------------------------
# 4. Candidate predictors, missingness, duplicates, outliers
# ----------------------------------------------------------------------------
print("\n[4] Data quality audit")

DESIGN = [
    "is_randomized", "who_masked_n", "n_arms", "n_locations", "n_countries",
    "is_multinational", "elig_criteria_lines", "n_primary_outcomes",
    "n_secondary_outcomes", "is_phase3", "n_interventions", "is_biologic",
]
SPONSOR = ["is_industry", "n_collaborators", "sponsor_prior_trials", "sponsor_prior_completion_rate"]
REGULATORY = ["fda_any_priority", "fda_has_orphan", "fda_is_nme", "fda_n_efficacy_suppl"]
IP_DRUG = [
    "ob_n_patents", "ob_n_primary_patents", "ob_n_secondary_patents",
    "ob_evergreen_ratio", "ob_patent_span_years", "ob_n_exclusivities",
]
CANDIDATES = DESIGN + SPONSOR + REGULATORY + IP_DRUG

miss = pd.DataFrame(
    {
        "variable": CANDIDATES,
        "n_missing": [int(frame[c].isna().sum()) for c in CANDIDATES],
    }
)
miss["pct_missing"] = (miss.n_missing / len(frame) * 100).round(2)
miss["block"] = (
    ["Design"] * len(DESIGN) + ["Sponsor"] * len(SPONSOR)
    + ["Regulatory"] * len(REGULATORY) + ["IP (drug level)"] * len(IP_DRUG)
)
results["missingness"] = miss.to_dict("records")
print(miss.sort_values("pct_missing", ascending=False).head(12).to_string(index=False))

# Duplicates are checked on identity and on content. A repeated NCT id would be a
# retrieval fault; a repeated design signature is a real pattern (platform trials
# registered separately per cohort) and must not be deduplicated away.
sig_cols = ["lead_sponsor", "start_date", "primary_drug", "primary_condition", "enrollment"]
dup_sig = int(frame.duplicated(subset=sig_cols, keep=False).sum())
results["duplicates"] = {
    "duplicate_nct_ids": dup_nct,
    "duplicate_design_signatures": dup_sig,
    "duplicate_design_signature_pct": round(dup_sig / len(frame) * 100, 2),
    "action": "none removed; NCT id is unique by construction and repeated design "
              "signatures are legitimately distinct registrations",
}
print(f"\n  duplicate NCT ids {dup_nct} | repeated design signatures {dup_sig:,}")

# Outliers: the count predictors are right-skewed, so the question is how much mass
# sits beyond a winsorisation bound, not whether any single value is 'wrong'.
skewed = ["n_locations", "n_countries", "elig_criteria_lines", "n_arms",
          "n_secondary_outcomes", "sponsor_prior_trials"]
rows = []
for c in skewed:
    s = frame[c].dropna()
    q1, q3 = s.quantile([0.25, 0.75])
    iqr = q3 - q1
    hi = q3 + 1.5 * iqr
    p99 = s.quantile(0.99)
    rows.append(
        {
            "variable": c,
            "median": round(float(s.median()), 2),
            "p99": round(float(p99), 2),
            "max": round(float(s.max()), 2),
            "skew": round(float(s.skew()), 2),
            "n_above_iqr_fence": int((s > hi).sum()),
            "pct_above_iqr_fence": round(float((s > hi).mean() * 100), 2),
        }
    )
outl = pd.DataFrame(rows)
results["outliers"] = outl.to_dict("records")
print("\n" + outl.to_string(index=False))

# Descriptive summary of the continuous design block
desc = frame[["n_locations", "n_countries", "elig_criteria_lines", "n_arms",
              "n_primary_outcomes", "n_secondary_outcomes", "sponsor_prior_trials"]].describe().T
desc = desc[["count", "mean", "50%", "std", "min", "max"]].round(2)
results["descriptives"] = desc.reset_index().rename(columns={"index": "variable"}).to_dict("records")

# ----------------------------------------------------------------------------
# 5. The enrollment leakage check, quantified
# ----------------------------------------------------------------------------
print("\n[5] Enrollment leakage")

enr = frame[frame.enrollment.notna() & (frame.enrollment > 0)]
actual = enr[enr.enrollment_type.str.upper().eq("ACTUAL")] if "enrollment_type" in enr else enr
est = enr[enr.enrollment_type.str.upper().eq("ESTIMATED")] if "enrollment_type" in enr else enr.iloc[:0]
leak = {
    "pct_actual": round(float(enr.enrollment_type.str.upper().eq("ACTUAL").mean() * 100), 2),
    "median_enrollment_terminated": float(enr.loc[enr.is_terminated == 1, "enrollment"].median()),
    "median_enrollment_completed": float(enr.loc[enr.is_terminated == 0, "enrollment"].median()),
}
for label, subset in [("actual", actual), ("estimated", est)]:
    if len(subset) > 50 and subset.is_terminated.nunique() == 2:
        leak[f"auc_enrollment_alone_{label}"] = round(
            float(roc_auc_score(subset.is_terminated, -subset.enrollment)), 4
        )
        leak[f"n_{label}"] = int(len(subset))
results["enrollment_leakage"] = leak
print("  " + json.dumps(leak, indent=2).replace("\n", "\n  "))

# ----------------------------------------------------------------------------
# 6. Figures
# ----------------------------------------------------------------------------
print("\n[6] Figures")

# Figure 1 - why the window closes at 2019
fig, ax = plt.subplots(figsize=(6.4, 3.3))
yrs = by_year.index.to_numpy()
ax.plot(yrs, by_year.resolved, color=BLUE, lw=2, marker="o", ms=4, label="Outcome resolved")
ax.plot(yrs, by_year.p_term_resolved, color=ORANGE, lw=2, marker="s", ms=4,
        label="Termination rate among resolved")
ax.axvspan(START_MIN - 0.5, START_MAX + 0.5, color=BLUE, alpha=0.06, zorder=0)
ax.axvline(START_MAX + 0.5, color=INK_SOFT, lw=1, ls="--")
ax.annotate("analytic window closes", xy=(START_MAX + 0.5, 0.92), xytext=(2014.2, 0.95),
            fontsize=8, color=INK_SOFT,
            arrowprops=dict(arrowstyle="->", color=INK_SOFT, lw=0.8))
for x, y, dx, ha in [(2008, by_year.resolved.iloc[0], 4, "left"),
                     (2023, by_year.resolved.iloc[-1], -6, "right")]:
    ax.annotate(f"{y:.1%}", (x, y), textcoords="offset points", xytext=(dx, 9),
                ha=ha, fontsize=8, color=INK)
ax.set_xlabel("Trial start year")
ax.set_ylabel("Proportion")
ax.set_ylim(0, 1.05)
ax.set_title("Outcome resolution and apparent termination rate by start year")
ax.legend(loc="center left", fontsize=8)
save(tidy(ax).figure, "fig01_resolution_by_year.png")

# Figure 2 - therapeutic area strata, the RQ4 heterogeneity
areas = []
for a, grp in frame.groupby("therapeutic_area"):
    lo, hi = proportion_confint(int(grp.is_terminated.sum()), len(grp), method="wilson")
    areas.append({"area": a, "n": len(grp), "p": float(grp.is_terminated.mean()),
                  "lo": float(lo), "hi": float(hi), "margin": float((hi - lo) / 2)})
areas = pd.DataFrame(areas).sort_values("p", ascending=True)
results["rq4_strata"] = [
    {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
    for r in areas.sort_values("n", ascending=False).to_dict("records")
]

fig, ax = plt.subplots(figsize=(6.4, 3.2))
ypos = np.arange(len(areas))
colors = [AQUA if a == "Other" else BLUE for a in areas.area]
ax.barh(ypos, areas.p, color=colors, height=0.62)
ax.errorbar(areas.p, ypos, xerr=[areas.p - areas.lo, areas.hi - areas.p],
            fmt="none", ecolor=INK_SOFT, elinewidth=1, capsize=2.5)
for y, (p, hi_, n) in enumerate(zip(areas.p, areas.hi, areas.n)):
    ax.text(hi_ + 0.009, y, f"{p:.1%}  (n = {n:,})", va="center", fontsize=8, color=INK)
ax.axvline(frame.is_terminated.mean(), color=ORANGE, lw=1.5, ls="--", zorder=3)
ax.text(frame.is_terminated.mean() + 0.004, -0.42,
        f"pooled {frame.is_terminated.mean():.1%}", fontsize=8, color=ORANGE)
ax.set_yticks(ypos, areas.area)
ax.set_xlim(0, 0.46)
ax.set_ylim(-0.75, len(areas) - 0.3)
ax.set_xlabel("Termination rate (95% Wilson CI)")
ax.set_title("Termination rate by therapeutic area")
ax.yaxis.grid(False)
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig02_termination_by_area.png")

# Figure 3 - the enrollment leakage, shown rather than asserted
fig, ax = plt.subplots(figsize=(6.4, 3.0))
bins = np.logspace(0, 4, 36)
for lab, mask, col in [("Completed", frame.is_terminated == 0, BLUE),
                       ("Terminated", frame.is_terminated == 1, ORANGE)]:
    s = frame.loc[mask & frame.enrollment.gt(0), "enrollment"].dropna()
    ax.hist(s, bins=bins, color=col, alpha=0.62, label=f"{lab} (median {s.median():.0f})")
ax.set_xscale("log")
ax.set_xlabel("Recorded enrollment (log scale, participants)")
ax.set_ylabel("Trials")
ax.set_title("Recorded enrollment by outcome: a consequence, not a predictor")
ax.legend(fontsize=8)
save(tidy(ax).figure, "fig03_enrollment_leakage.png")

# Figure 4 - missingness by block, which drives the imputation strategy
fig, ax = plt.subplots(figsize=(6.4, 3.6))
m = miss.sort_values("pct_missing")
m = m[m.pct_missing > 0]
block_color = {"Design": BLUE, "Sponsor": BLUE, "Regulatory": ORANGE, "IP (drug level)": AQUA}
ax.barh(np.arange(len(m)), m.pct_missing, color=[block_color[b] for b in m.block], height=0.66)
for y, v in enumerate(m.pct_missing):
    ax.text(v + 0.7, y, f"{v:.1f}%", va="center", fontsize=8, color=INK)
ax.set_yticks(np.arange(len(m)), m.variable)
ax.set_xlim(0, 105)
# Headroom below the shortest bar so the legend does not sit on top of a value label.
ax.set_ylim(-2.6, len(m) - 0.4)
ax.set_xlabel("Percent missing in the analytic frame (N = 39,437)")
ax.set_title("Missingness is structural, not random: it tracks the data block")
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in [BLUE, ORANGE, AQUA]]
ax.legend(handles, ["Design / sponsor (registry)", "Regulatory (Drugs@FDA)", "IP (Orange Book)"],
          fontsize=8, loc="lower right", ncol=3, columnspacing=1.0, handlelength=1.2)
ax.yaxis.grid(False)
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig04_missingness.png")

# ----------------------------------------------------------------------------
# 7. RQ1 - termination rate by IP strength
# ----------------------------------------------------------------------------
print("\n[7] RQ1")

rq1 = frame[frame.ip_strong.notna()].copy()
rq1["ip_strong"] = rq1.ip_strong.astype(int)
ct = pd.crosstab(rq1.ip_strong, rq1.is_terminated)
cnt = [int(ct.loc[1, 1]), int(ct.loc[0, 1])]
nobs = [int(ct.loc[1].sum()), int(ct.loc[0].sum())]
z, p = proportions_ztest(cnt, nobs)
from scipy.stats import chi2_contingency

chi2, pchi, dof, _ = chi2_contingency(ct)
cram = math.sqrt(chi2 / (ct.values.sum() * min(ct.shape[0] - 1, ct.shape[1] - 1)))
p_strong, p_weak = cnt[0] / nobs[0], cnt[1] / nobs[1]
rd = p_strong - p_weak
se_rd = math.sqrt(p_strong * (1 - p_strong) / nobs[0] + p_weak * (1 - p_weak) / nobs[1])

# The computable-vs-not comparison is the survivorship check, not an aside: if the
# subsample on which the index exists differs in outcome from the rest, the RQ1
# estimate cannot be read as a population quantity.
obs = frame.ip_strong.notna()
z_sel, p_sel = proportions_ztest(
    [int(frame.loc[obs, "is_terminated"].sum()), int(frame.loc[~obs, "is_terminated"].sum())],
    [int(obs.sum()), int((~obs).sum())],
)
results["rq1"] = {
    "n_computable": int(len(rq1)),
    "n_not_computable": int((~obs).sum()),
    "p_term_strong": round(p_strong, 4),
    "p_term_weak": round(p_weak, 4),
    "n_strong": nobs[0],
    "n_weak": nobs[1],
    "risk_difference": round(rd, 4),
    "rd_ci95": [round(rd - 1.96 * se_rd, 4), round(rd + 1.96 * se_rd, 4)],
    "z": round(float(z), 4),
    "p_value": float(p),
    "chi2": round(float(chi2), 3),
    "cramers_v": round(cram, 4),
    "selection_check": {
        "p_term_computable": round(float(frame.loc[obs, "is_terminated"].mean()), 4),
        "p_term_not_computable": round(float(frame.loc[~obs, "is_terminated"].mean()), 4),
        "z": round(float(z_sel), 3),
        "p_value": float(p_sel),
    },
}
print(f"  strong {p_strong:.4f} (n={nobs[0]:,})  weak {p_weak:.4f} (n={nobs[1]:,})")
print(f"  RD = {rd:+.4f} [{rd - 1.96 * se_rd:+.4f}, {rd + 1.96 * se_rd:+.4f}]  z = {z:.3f}  p = {p:.3e}")
print(f"  Cramer's V = {cram:.4f}")

# Figure 5 - RQ1, with the uncomputable group shown rather than hidden
fig, ax = plt.subplots(figsize=(6.4, 3.0))
labels = ["Strong IP\n(above median)", "Weak IP\n(below median)", "IP index not\ncomputable"]
vals = [p_strong, p_weak, float(frame.loc[~obs, "is_terminated"].mean())]
ns = [nobs[0], nobs[1], int((~obs).sum())]
cols = [BLUE, BLUE, AQUA]
bars = ax.bar(np.arange(3), vals, color=cols, width=0.56)
for i, (v, n) in enumerate(zip(vals, ns)):
    lo, hi = proportion_confint(int(round(v * n)), n, method="wilson")
    ax.errorbar(i, v, yerr=[[v - lo], [hi - v]], fmt="none", ecolor=INK_SOFT,
                elinewidth=1, capsize=3)
    ax.text(i, hi + 0.006, f"{v:.1%}\nn = {n:,}", ha="center", fontsize=8, color=INK)
ax.set_xticks(np.arange(3), labels)
ax.set_ylim(0, max(vals) * 1.42)
ax.set_ylabel("Termination rate")
ax.set_title("RQ1: termination rate by drug-level IP strength, with the\nuncomputable group reported alongside")
save(tidy(ax).figure, "fig05_rq1_ip_strength.png")

# ----------------------------------------------------------------------------
# 8. RQ2 - preliminary prediction models on a temporal split
# ----------------------------------------------------------------------------
print("\n[8] RQ2")

model_frame = frame.copy()
train = model_frame[model_frame.start_year <= TRAIN_MAX]
test = model_frame[model_frame.start_year >= TEST_MIN]
print(f"  train {len(train):,} (2008-{TRAIN_MAX})   test {len(test):,} ({TEST_MIN}-2019)")

FEATURE_SETS = {
    "Design only": DESIGN,
    "Design + sponsor": DESIGN + SPONSOR,
    "Design + sponsor + regulatory + IP": CANDIDATES,
}
nir = float(max(test.is_terminated.mean(), 1 - test.is_terminated.mean()))
perf = [
    {
        "model": "No-information rate (majority class)",
        "features": "-",
        "validation": "Temporal holdout 2016-2019",
        "auc": 0.5,
        "accuracy": round(nir, 4),
        "brier": round(float(brier_score_loss(test.is_terminated,
                                              np.full(len(test), test.is_terminated.mean()))), 4),
    }
]

fitted = {}
for set_name, feats in FEATURE_SETS.items():
    Xtr, ytr = train[feats], train.is_terminated
    Xte, yte = test[feats], test.is_terminated

    # L1 logistic needs complete data, so the structurally absent blocks are median
    # imputed with the model told which rows were imputed. Gradient boosting routes
    # missing values down their own branch and needs neither.
    logit = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        LogisticRegression(penalty="l1", solver="liblinear", C=0.1,
                           class_weight="balanced", max_iter=2000, random_state=SEED),
    ).fit(Xtr, ytr)
    gb = HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.06, max_iter=400, l2_regularization=1.0,
        class_weight="balanced", early_stopping=True, validation_fraction=0.15,
        random_state=SEED,
    ).fit(Xtr, ytr)

    for label, mdl in [("L1-penalised logistic regression", logit),
                       ("Gradient-boosted trees (HistGB)", gb)]:
        pr = mdl.predict_proba(Xte)[:, 1]
        yh = (pr >= 0.5).astype(int)
        tn, fp, fn, tp = confusion_matrix(yte, yh).ravel()
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        spec = tn / (tn + fp)
        perf.append(
            {
                "model": label,
                "features": set_name,
                "validation": "Temporal holdout 2016-2019",
                "auc": round(float(roc_auc_score(yte, pr)), 4),
                "accuracy": round(float((tp + tn) / len(yte)), 4),
                "precision": round(float(prec), 4),
                "recall": round(float(rec), 4),
                "specificity": round(float(spec), 4),
                "f1": round(float(2 * prec * rec / (prec + rec)), 4),
                "balanced_accuracy": round(float((rec + spec) / 2), 4),
                "brier": round(float(brier_score_loss(yte, pr)), 4),
                "confusion": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)},
            }
        )
        fitted[(set_name, label)] = (mdl, pr)
        print(f"  {set_name:36s} {label[:28]:30s} AUC {perf[-1]['auc']:.4f}")

results["rq2_performance"] = perf
results["rq2_split"] = {"train_n": len(train), "test_n": len(test),
                        "test_terminated": int(test.is_terminated.sum()),
                        "test_completed": int((test.is_terminated == 0).sum()),
                        "no_information_rate": round(nir, 4)}

best_key = ("Design + sponsor + regulatory + IP", "Gradient-boosted trees (HistGB)")
best_model, best_pr = fitted[best_key]

# Figure 6 - ROC on the held-out period
fig, ax = plt.subplots(figsize=(4.4, 4.0))
for (set_name, label), col in [
    (("Design + sponsor + regulatory + IP", "Gradient-boosted trees (HistGB)"), BLUE),
    (("Design + sponsor + regulatory + IP", "L1-penalised logistic regression"), ORANGE),
    (("Design only", "Gradient-boosted trees (HistGB)"), AQUA),
]:
    _, pr = fitted[(set_name, label)]
    fpr, tpr, _ = roc_curve(test.is_terminated, pr)
    a = roc_auc_score(test.is_terminated, pr)
    short = "Gradient boosting, all blocks" if col == BLUE else (
        "L1 logistic, all blocks" if col == ORANGE else "Gradient boosting, design only")
    ax.plot(fpr, tpr, color=col, lw=2, label=f"{short} (AUC {a:.3f})")
ax.plot([0, 1], [0, 1], color=INK_SOFT, lw=1, ls="--", label="Chance (AUC 0.500)")
ax.set_xlabel("False positive rate")
ax.set_ylabel("True positive rate")
ax.set_title("RQ2: discrimination on held-out\n2016-2019 trials")
# Below the axes: the labels are too long to sit in the lower-right corner without
# covering the curves they describe.
ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.17))
ax.set_aspect("equal")
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig06_roc.png")

# Figure 7 - calibration, which matters as much as ranking for a triage score
fig, ax = plt.subplots(figsize=(4.4, 4.0))
dec = pd.DataFrame({"p": best_pr, "y": test.is_terminated.to_numpy()})
dec["bin"] = pd.qcut(dec.p, 10, labels=False, duplicates="drop")
cal = dec.groupby("bin").agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
ax.plot([0, cal.pred.max() * 1.1], [0, cal.pred.max() * 1.1], color=INK_SOFT, lw=1, ls="--",
        label="Perfect calibration")
ax.plot(cal.pred, cal.obs, color=BLUE, lw=2, marker="o", ms=5, label="Gradient boosting, by decile")
slope, intercept = np.polyfit(cal.pred, cal.obs, 1)
ax.set_xlabel("Mean predicted probability")
ax.set_ylabel("Observed termination rate")
ax.set_title(f"RQ2: calibration by risk decile\n(slope {slope:.2f}, intercept {intercept:+.2f})")
ax.legend(fontsize=8, loc="upper left")
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig07_calibration.png")
results["rq2_calibration"] = {
    "slope": round(float(slope), 4),
    "intercept": round(float(intercept), 4),
    "deciles": [{"decile": int(i) + 1, "predicted": round(float(r.pred), 4),
                 "observed": round(float(r.obs), 4), "n": int(r.n)} for i, r in cal.iterrows()],
}

# Figure 8 - permutation importance, model-agnostic and computed on held-out data
print("  permutation importance (held-out, 10 repeats)")
feats = FEATURE_SETS["Design + sponsor + regulatory + IP"]
pi = permutation_importance(best_model, test[feats], test.is_terminated, n_repeats=10,
                            random_state=SEED, scoring="roc_auc", n_jobs=-1)
imp = (pd.DataFrame({"feature": feats, "drop": pi.importances_mean, "sd": pi.importances_std})
       .sort_values("drop", ascending=False))
results["rq2_importance"] = [
    {"feature": r.feature, "auc_drop": round(float(r.drop), 5), "sd": round(float(r.sd), 5)}
    for r in imp.itertuples()
]
# Sixteen rows rather than ten, because the point of the figure is where the IP
# block lands relative to design and sponsor, and the first IP feature is rank 15.
top = imp.head(16).iloc[::-1]
fig, ax = plt.subplots(figsize=(6.4, 4.4))
block_of = {**{c: "Design" for c in DESIGN}, **{c: "Sponsor" for c in SPONSOR},
            **{c: "Regulatory" for c in REGULATORY}, **{c: "IP" for c in IP_DRUG}}
cmap = {"Design": BLUE, "Sponsor": BLUE, "Regulatory": ORANGE, "IP": AQUA}
ax.barh(np.arange(len(top)), top["drop"], color=[cmap[block_of[f]] for f in top.feature],
        height=0.66, xerr=top.sd, error_kw=dict(ecolor=INK_SOFT, elinewidth=0.8))
for y, v in enumerate(top["drop"]):
    ax.text(v + imp["drop"].max() * 0.02, y, f"{v:.4f}", va="center", fontsize=7.5, color=INK)
ax.set_yticks(np.arange(len(top)), top.feature)
ax.set_xlim(0, imp["drop"].max() * 1.18)
ax.set_xlabel("Decrease in held-out AUC when the feature is permuted")
ax.set_title("RQ2: which features carry the predictive signal")
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in [BLUE, ORANGE, AQUA]]
ax.legend(handles, ["Design / sponsor", "Regulatory", "IP (drug level)"], fontsize=8,
          loc="lower right")
ax.yaxis.grid(False)
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig08_permutation_importance.png")

# ----------------------------------------------------------------------------
# 9. RQ3 - competing risks, preliminary
# ----------------------------------------------------------------------------
print("\n[9] RQ3")

from lifelines import AalenJohansenFitter, CoxPHFitter

surv = frame[frame.months_to_primary_completion.notna()
             & (frame.months_to_primary_completion > 0)].copy()
surv["status"] = np.where(surv.is_terminated == 1, 2, 1)
results["rq3"] = {
    "n": int(len(surv)),
    "completed": int((surv.status == 1).sum()),
    "terminated_competing": int((surv.status == 2).sum()),
    "median_months_completed": float(surv.loc[surv.status == 1, "months_to_primary_completion"].median()),
    "median_months_terminated": float(surv.loc[surv.status == 2, "months_to_primary_completion"].median()),
}

sv = surv[surv.ip_strong.notna()].copy()
sv["ip_strong"] = sv.ip_strong.astype(int)
fig, ax = plt.subplots(figsize=(6.4, 3.4))
for lvl, lab, col in [(1, "Strong IP", BLUE), (0, "Weak IP", ORANGE)]:
    s = sv[sv.ip_strong == lvl]
    ajf = AalenJohansenFitter(calculate_variance=False, seed=SEED)
    ajf.fit(s.months_to_primary_completion, s.status, event_of_interest=1)
    cif = ajf.cumulative_density_
    ax.step(cif.index, cif.iloc[:, 0], where="post", color=col, lw=2,
            label=f"{lab} (n = {len(s):,})")
    results["rq3"][f"cif_completion_60mo_{'strong' if lvl else 'weak'}"] = round(
        float(cif.iloc[:, 0].asof(60)), 4)
ax.set_xlim(0, 120)
ax.set_ylim(0, 1)
ax.set_xlabel("Months from trial start")
ax.set_ylabel("Cumulative incidence of primary completion")
ax.set_title("RQ3: cumulative incidence of primary completion (Aalen-Johansen,\ntermination treated as the competing event)")
ax.legend(fontsize=8, loc="lower right")
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig09_rq3_cumulative_incidence.png")

COVARS = ["ip_strong", "is_phase3", "n_locations", "is_industry", "is_biologic",
          "sponsor_prior_trials"]
for cause, name in [(1, "completion"), (2, "termination")]:
    cx = sv[["months_to_primary_completion", "status"] + COVARS].dropna().copy()
    cx["event"] = (cx.status == cause).astype(int)
    cx = cx.drop(columns="status")
    cph = CoxPHFitter().fit(cx, duration_col="months_to_primary_completion", event_col="event")
    summ = cph.summary[["exp(coef)", "exp(coef) lower 95%", "exp(coef) upper 95%", "p"]]
    results["rq3"][f"cox_{name}"] = {
        "n": int(len(cx)),
        "events": int(cx.event.sum()),
        "concordance": round(float(cph.concordance_index_), 4),
        "coefficients": {
            idx: {"hr": round(float(r["exp(coef)"]), 4),
                  "ci95": [round(float(r["exp(coef) lower 95%"]), 4),
                           round(float(r["exp(coef) upper 95%"]), 4)],
                  "p": float(r["p"])}
            for idx, r in summ.iterrows()
        },
    }
    print(f"  cause-specific {name}: C = {cph.concordance_index_:.4f}, "
          f"HR(ip_strong) = {summ.loc['ip_strong', 'exp(coef)']:.4f}")

# ----------------------------------------------------------------------------
# 10. RQ4 - moderation by therapeutic area, preliminary
# ----------------------------------------------------------------------------
print("\n[10] RQ4")

import statsmodels.formula.api as smf

mod = frame[frame.ip_strong.notna()].copy()
mod["ip_strong"] = mod.ip_strong.astype(int)
m0 = smf.logit("is_terminated ~ ip_strong + C(therapeutic_area) + is_phase3 + is_industry",
               data=mod).fit(disp=0)
m1 = smf.logit("is_terminated ~ ip_strong * C(therapeutic_area) + is_phase3 + is_industry",
               data=mod).fit(disp=0)
lr_stat = float(2 * (m1.llf - m0.llf))
df_diff = int(m1.df_model - m0.df_model)
results["rq4_moderation"] = {
    "n": int(len(mod)),
    "lr_chi2": round(lr_stat, 4),
    "df": df_diff,
    "p_value": float(chi2_dist.sf(lr_stat, df_diff)),
    "main_effect_or_ip_strong": round(float(np.exp(m1.params["ip_strong"])), 4),
    "interaction_terms": {
        k: {"or": round(float(np.exp(v)), 4), "p": float(m1.pvalues[k])}
        for k, v in m1.params.items() if "ip_strong:" in k
    },
}
print(f"  LR chi2 = {lr_stat:.3f}, df = {df_diff}, p = {chi2_dist.sf(lr_stat, df_diff):.4f}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(results, indent=2, default=str))
print(f"\nwrote {OUT.relative_to(ROOT)}")
print(f"wrote {len(list(FIGS.glob('*.png')))} figures to {FIGS.relative_to(ROOT)}")
