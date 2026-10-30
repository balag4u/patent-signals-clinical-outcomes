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
# Genetic support for the drug's target, from prep_14_genetic_support.py.
_gs = DATA / "genetic_support.parquet"
GENETIC_AVAILABLE = _gs.exists()
genetic = pd.read_parquet(_gs) if GENETIC_AVAILABLE else None
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

frame = frame.sort_values("start_date").reset_index(drop=True)

# Phase and sponsor class were each collapsed to a single yes/no flag, which
# merges groups that behave differently. In this frame PHASE1|PHASE2 trials are
# stopped 29.0% of the time against 24.2% for PHASE2 alone, yet both read as
# "not Phase 3". Among sponsors, government bodies other than the NIH stop
# 15.5% of trials, lower than industry's 19.0%, while the NIH stops 26.3%, yet
# all three read as "not industry". The flags below keep those apart.
_ph = frame.phases.astype(str).str.upper()
frame["is_phase1_2"] = _ph.eq("PHASE1|PHASE2").astype(int)
frame["is_phase2_3"] = _ph.eq("PHASE2|PHASE3").astype(int)
_sc = frame.lead_sponsor_class.astype(str).str.upper()
for _lab, _col in [("NIH", "sponsor_is_nih"), ("OTHER_GOV", "sponsor_is_other_gov"),
                   ("NETWORK", "sponsor_is_network"), ("FED", "sponsor_is_fed")]:
    frame[_col] = _sc.eq(_lab).astype(int)

# Two "as of" rules, because the two facts become knowable at different times.
# How many trials a sponsor has already registered IS visible at the focal trial's
# start date, so prior_trials counts trials STARTED earlier. How those trials turned
# out is not: a sibling that started in 2013 may not have reported an outcome until
# 2016, and counting its final status against a 2014 trial is the same look-ahead
# the enrolment field carries (Section 7). Since this is the model's strongest
# feature, that leak inflated it. The completion rate is therefore computed only
# over prior trials RESOLVED before the focal start date.
#
# History is drawn from the full retrieval rather than the analytic frame, so a
# sponsor's pre-2008 and out-of-window trials still count toward what was knowable.
hist = trials[["lead_sponsor", "start_date", "completion_date",
               "is_resolved", "is_terminated"]]

started = {s: np.sort(g.start_date.values)
           for s, g in hist[hist.start_date.notna()].groupby("lead_sponsor")}
resolved_hist = {}
for s, g in hist[(hist.is_resolved == 1) & hist.completion_date.notna()].groupby("lead_sponsor"):
    g = g.sort_values("completion_date")
    resolved_hist[s] = (g.completion_date.values,
                        np.concatenate([[0.0], np.cumsum(g.is_terminated.to_numpy(float))]))

prior_n = np.zeros(len(frame))
prior_res = np.zeros(len(frame))
prior_term = np.zeros(len(frame))
for s, idx in frame.groupby("lead_sponsor").indices.items():
    t0 = frame.start_date.values[idx]
    sd = started.get(s)
    if sd is not None:
        prior_n[idx] = np.searchsorted(sd, t0, side="left")
    rh = resolved_hist.get(s)
    if rh is not None:
        cd, cum = rh
        k = np.searchsorted(cd, t0, side="left")
        prior_res[idx] = k
        prior_term[idx] = cum[k]

frame["sponsor_prior_trials"] = prior_n
frame["sponsor_prior_resolved"] = prior_res
frame["sponsor_prior_terminations"] = prior_term
frame["sponsor_prior_completion_rate"] = np.where(
    prior_res > 0, 1 - prior_term / np.maximum(prior_res, 1), np.nan)

no_history = int((prior_res == 0).sum())
results["sponsor_history"] = {
    "rule": "prior trials counted by start date; completion rate over prior trials "
            "RESOLVED before the focal start date",
    "undefined_no_resolved_prior": no_history,
    "undefined_pct": round(100.0 * no_history / len(frame), 2),
    "median_prior_trials": float(np.median(prior_n)),
    "median_prior_resolved": float(np.median(prior_res)),
}
print(f"  sponsor_prior_completion_rate undefined for {no_history:,} trials "
      f"({100.0 * no_history / len(frame):.1f}%) with no prior RESOLVED trial")

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
    ip[["nct_id", "ip_index", "ip_index_sponsor", "ip_index_drug", "ip_strong", "ip_tertile_extreme",
        "ob_term_remaining_yrs", "assignee_portfolio_size", "assignee_pharma_share",
        "citations_per_patent", "family_size", "family_n_countries",
        "cpc_codes_per_patent", "assignees_per_patent", "inventors_per_patent", "backward_citations_per_patent", "years_priority_to_grant", "pb_is_biosimilar", "pb_is_interchangeable", "pb_is_originator", "pb_n_competing_biosimilars"]],
    on="nct_id",
    how="left",
)

if GENETIC_AVAILABLE:
    frame = frame.merge(genetic, on="nct_id", how="left")

# The sponsor-level patent measure belongs to the sponsor's corporate group, so all
# trials of one group share a single patent position and are not independent pieces
# of evidence. The group is carried here so the RQ1, RQ3 and RQ4 standard errors can
# be clustered on it. Where no group was assigned the registry sponsor name stands in.
_grp = pd.read_parquet(DATA / "sponsor_ip_features.parquet",
                       columns=["nct_id", "corporate_group"]).drop_duplicates("nct_id")
frame = frame.merge(_grp, on="nct_id", how="left")
_cg = frame.corporate_group.astype("string").str.strip()
frame["sponsor_cluster"] = _cg.where(_cg.notna() & _cg.ne(""),
                                     "SPONSOR:" + frame.lead_sponsor.astype(str))

results["linkage"] = {
    "resolved_to_ingredient": int(frame.ingredient.notna().sum()),
    "resolved_to_ingredient_pct": round(float(frame.ingredient.notna().mean() * 100), 2),
    "resolved_to_application": int(frame.appl_no.notna().sum()),
    "resolved_to_application_pct": round(float(frame.appl_no.notna().mean() * 100), 2),
    "with_regulatory_block": int(frame.fda_appl_type.notna().sum()),
    "with_drug_level_ip": int(frame.ob_n_patents.notna().sum()),
    "with_drug_level_ip_pct": round(float(frame.ob_n_patents.notna().mean() * 100), 2),
    "with_sponsor_level_ip": int(frame.ip_index_sponsor.notna().sum()),
    # Coverage split by sponsor type. Dividing the frame-wide count by the
    # industry count overstates industry coverage, because a few non-industry
    # sponsors do hold portfolios, so each group is counted on its own.
    "sponsor_ip_industry": int(
        (frame.ip_index_sponsor.notna() & frame.is_industry.eq(1)).sum()),
    "sponsor_ip_industry_pct": round(float(
        (frame.ip_index_sponsor.notna() & frame.is_industry.eq(1)).sum()
        / max(int(frame.is_industry.sum()), 1) * 100), 2),
    "sponsor_ip_nonindustry": int(
        (frame.ip_index_sponsor.notna() & frame.is_industry.eq(0)).sum()),
    "sponsor_ip_nonindustry_pct": round(float(
        (frame.ip_index_sponsor.notna() & frame.is_industry.eq(0)).sum()
        / max(int((frame.is_industry == 0).sum()), 1) * 100), 2),
    # Of the trials with no sponsor measure, how many are unmeasurable because
    # the sponsor holds no commercial portfolio, and how many are industry
    # sponsors the name matching did not reach.
    "no_sponsor_ip_nonindustry": int(
        (frame.ip_index_sponsor.isna() & frame.is_industry.eq(0)).sum()),
    "no_sponsor_ip_industry": int(
        (frame.ip_index_sponsor.isna() & frame.is_industry.eq(1)).sum()),
    "no_sponsor_ip_industry_share_of_gap_pct": round(float(
        (frame.ip_index_sponsor.isna() & frame.is_industry.eq(1)).sum()
        / max(int(frame.ip_index_sponsor.isna().sum()), 1) * 100), 2),
}
print(f"  resolved to an FDA ingredient: {frame.ingredient.notna().sum():,}")
print(f"  linked to an FDA application: {frame.appl_no.notna().sum():,}")
print(f"  drug-level IP observable:     {frame.ob_n_patents.notna().sum():,}")
print(f"  sponsor-level IP observable:  {frame.ip_index_sponsor.notna().sum():,}"
      f"  ({results['linkage']['sponsor_ip_industry_pct']}% of industry trials,"
      f" {results['linkage']['sponsor_ip_nonindustry_pct']}% of the rest)")

# ----------------------------------------------------------------------------
# 3b. How far the genetic-evidence measure reaches, and whether it separates
#     terminated trials from the rest before any model is fitted.
# ----------------------------------------------------------------------------
if GENETIC_AVAILABLE:
    have_gene = frame.genetic_score_max.notna()
    supported = have_gene & (frame.has_genetic_support == 1)
    gen = {
        "trials_linked_to_a_gene": int(have_gene.sum()),
        "trials_linked_to_a_gene_pct": round(float(have_gene.mean() * 100), 2),
        "of_those_with_any_evidence_pct": round(
            float(supported.sum() / max(int(have_gene.sum()), 1) * 100), 2),
        "termination_rate_linked": round(
            float(frame.loc[have_gene, "is_terminated"].mean()), 4),
        "termination_rate_not_linked": round(
            float(frame.loc[~have_gene, "is_terminated"].mean()), 4),
    }
    # Quartiles of the strongest evidence score the drug's target carries. A
    # real effect would show a steady rise or fall across the four groups.
    q = frame.loc[have_gene].copy()
    try:
        q["band"] = pd.qcut(q.genetic_score_max, 4, labels=[1, 2, 3, 4],
                            duplicates="drop")
        gen["by_quartile"] = [
            {"quartile": int(b),
             "n": int((q.band == b).sum()),
             "termination_rate": round(
                 float(q.loc[q.band == b, "is_terminated"].mean()), 4)}
            for b in sorted(q.band.dropna().unique())
        ]
    except ValueError:
        gen["by_quartile"] = []
    results["genetic"] = gen
    print(f"  drug linked to a gene target: {gen['trials_linked_to_a_gene']:,} "
          f"({gen['trials_linked_to_a_gene_pct']}%)")
    print(f"  of those, target carries some genetic evidence: "
          f"{gen['of_those_with_any_evidence_pct']}%")
    for row in gen["by_quartile"]:
        print(f"    quartile {row['quartile']}: termination "
              f"{row['termination_rate']:.4f} (n = {row['n']:,})")

# ----------------------------------------------------------------------------
# 4. Candidate predictors, missingness, duplicates, outliers
# ----------------------------------------------------------------------------
print("\n[4] Data quality audit")

DESIGN = [
    "is_randomized", "who_masked_n", "n_arms", "n_locations", "n_countries",
    "is_multinational", "elig_criteria_lines", "n_primary_outcomes",
    "n_secondary_outcomes", "is_phase3", "n_interventions", "is_biologic",
    "is_phase1_2", "is_phase2_3",
]
SPONSOR = ["is_industry", "n_collaborators", "sponsor_prior_trials",
           "sponsor_prior_completion_rate",
           "sponsor_is_nih", "sponsor_is_other_gov", "sponsor_is_network",
           "sponsor_is_fed"]
REGULATORY = ["fda_any_priority", "fda_has_orphan", "fda_is_nme", "fda_n_efficacy_suppl"]
IP_DRUG = [
    "ob_n_patents", "ob_n_primary_patents", "ob_n_secondary_patents",
    "ob_evergreen_ratio", "ob_patent_span_years", "ob_n_exclusivities",
    # QUALITY and BREADTH for the trial's drug, from sql/02 via prep_13. These
    # are Orange Book patents, so they are drug-level and sparse; trees handle
    # the missingness, and they are excluded from the RQ1 composite.
    "family_size", "family_n_countries", "citations_per_patent",
    # further indicators returned by 01_patent_core.sql. cpc_codes_per_patent is
    # the accepted stand-in for how broad a patent's claims are, which cannot be
    # measured directly here; assignees_per_patent above 1 means the patent is
    # co-owned, which usually signals a partnership or licence.
    "cpc_codes_per_patent", "assignees_per_patent", "inventors_per_patent",
    "backward_citations_per_patent", "years_priority_to_grant",
]
# Biosimilar competition, from the Purple Book. Biologics carry no duty to list
# their patents, so for them the number of competitors is a more direct measure
# of commercial pressure than any patent count.
BIOSIMILAR = ["pb_is_biosimilar", "pb_is_interchangeable", "pb_is_originator",
              "pb_n_competing_biosimilars"]
# Human genetic evidence for the gene the drug acts on. Nelson et al. (2015) and
# Minikel et al. (2024) found such targets reach approval about twice as often,
# so this enters as a control: the patent measures have to contribute over and
# above the biology, not instead of it.
#
# has_genetic_support is deliberately left out. Measured across all diseases
# rather than the trial's own, 99.8% of linked targets qualify, so the flag is
# constant and carries no information. The continuous measures are kept.
GENETIC = (["genetic_score_max", "genetic_score_mean", "genetic_n_diseases",
            "genetic_n_targets"] if GENETIC_AVAILABLE else [])
# Sponsor-level IP, from prep_13_patents.py. These are the survivorship-safe
# measures: they do not require the drug to have reached an approved FDA
# application, which the Orange Book block does. Both are cumulative as of the
# trial's start year, so neither can leak the outcome.
IP_SPONSOR = ["assignee_portfolio_size", "assignee_pharma_share"]
CANDIDATES = DESIGN + SPONSOR + REGULATORY + IP_DRUG + IP_SPONSOR + BIOSIMILAR + GENETIC

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
    + ["IP (sponsor level)"] * len(IP_SPONSOR) + ["Biosimilar"] * len(BIOSIMILAR)
    + ["Genetic"] * len(GENETIC)
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
save(ax.figure, "fig04_termination_by_area.png")

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
save(tidy(ax).figure, "fig02_enrollment_leakage.png")

# Figure 4 - missingness by block, which drives the imputation strategy
fig, ax = plt.subplots(figsize=(6.4, 3.6))
m = miss.sort_values("pct_missing")
m = m[m.pct_missing > 0]
block_color = {"Design": BLUE, "Sponsor": BLUE, "Regulatory": ORANGE,
               "IP (drug level)": AQUA, "IP (sponsor level)": AQUA,
               "Biosimilar": ORANGE, "Genetic": ORANGE}
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
save(ax.figure, "fig03_missingness.png")

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
# The sponsor-level index is a property of the SPONSOR, so every trial a corporate
# group runs in a given year carries the same value, and trials of one sponsor share
# its management, pipeline and funding. The 12,712 trials are therefore not 12,712
# independent observations. The naive z above treats them as if they were; the
# clustered fit below is what the standard errors should reflect. Clustering on the
# FDA application, as an earlier version did, is the right unit for the drug-level
# index but the wrong one for the sponsor-level index.
import statsmodels.formula.api as smf

rq1["cluster"] = rq1.sponsor_cluster
cl = smf.logit("is_terminated ~ ip_strong", data=rq1).fit(
    disp=0, cov_type="cluster", cov_kwds={"groups": rq1.cluster})
naive = smf.logit("is_terminated ~ ip_strong", data=rq1).fit(disp=0)
or_ip = float(np.exp(cl.params["ip_strong"]))
or_lo, or_hi = np.exp(cl.conf_int().loc["ip_strong"].to_numpy())
design_effect = float((cl.bse["ip_strong"] / naive.bse["ip_strong"]) ** 2)

results["rq1_clustered"] = {
    "cluster_variable": "sponsor corporate group (registry sponsor name where unassigned)",
    "n_clusters": int(rq1.cluster.nunique()),
    "n_trials": int(len(rq1)),
    "trials_per_cluster": round(float(len(rq1) / rq1.cluster.nunique()), 2),
    "odds_ratio_ip_strong": round(or_ip, 4),
    "or_ci95": [round(float(or_lo), 4), round(float(or_hi), 4)],
    "z": round(float(cl.tvalues["ip_strong"]), 4),
    "p_value": float(cl.pvalues["ip_strong"]),
    "naive_p_value": float(naive.pvalues["ip_strong"]),
    "se_inflation_design_effect": round(design_effect, 2),
}
print(f"  clustered on {rq1.cluster.nunique():,} sponsor groups: OR = {or_ip:.3f} "
      f"[{or_lo:.3f}, {or_hi:.3f}], p = {cl.pvalues['ip_strong']:.2e} "
      f"(naive p = {naive.pvalues['ip_strong']:.2e}, design effect {design_effect:.1f}x)")

# The same contrast on the risk-difference scale, from a linear probability model
# with the same cluster-robust covariance, so the interval and the smallest
# detectable difference reported for RQ1 both reflect the clustering.
lpm = smf.ols("is_terminated ~ ip_strong", data=rq1).fit(
    cov_type="cluster", cov_kwds={"groups": rq1.cluster})
rd_cl_se = float(lpm.bse["ip_strong"])
# One-way ANOVA estimator of the intraclass correlation of the outcome within
# sponsor groups, and the size-weighted mean cluster size m0, so the design effect
# 1 + (m0 - 1) ICC can be stated for the sample size chapter.
_g = rq1.groupby("cluster").is_terminated
_k, _N = int(_g.ngroups), int(len(rq1))
_ni = _g.size().to_numpy(float)
_m0 = (_N - (_ni ** 2).sum() / _N) / (_k - 1)
_ybar = float(rq1.is_terminated.mean())
_msb = float((_ni * (_g.mean().to_numpy() - _ybar) ** 2).sum() / (_k - 1))
_msw = float(((rq1.is_terminated - _g.transform("mean")) ** 2).sum() / (_N - _k))
_icc = (_msb - _msw) / (_msb + (_m0 - 1) * _msw)
results["rq1_clustered"].update({
    "risk_difference": round(float(lpm.params["ip_strong"]), 4),
    "rd_ci95": [round(float(lpm.conf_int().loc["ip_strong", 0]), 4),
                round(float(lpm.conf_int().loc["ip_strong", 1]), 4)],
    "rd_se": round(rd_cl_se, 5),
    "rd_p_value": float(lpm.pvalues["ip_strong"]),
    "minimum_detectable_difference": round((1.959964 + 0.8416212) * rd_cl_se, 4),
    "icc": round(float(_icc), 4),
    "mean_cluster_size_m0": round(float(_m0), 2),
    "design_effect_from_icc": round(float(1 + (_m0 - 1) * _icc), 2),
    "largest_cluster_share": round(float(_ni.max() / _N), 4),
})
print(f"  clustered RD = {lpm.params['ip_strong']:+.4f} "
      f"[{lpm.conf_int().loc['ip_strong', 0]:+.4f}, {lpm.conf_int().loc['ip_strong', 1]:+.4f}]"
      f"  ICC = {_icc:.4f}, m0 = {_m0:.1f}")

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
# ---------------------------------------------------------------------------
# The same comparison, run on the drug-level patent score instead of the
# sponsor-level one. The two differ in who can be measured at all: the Orange
# Book lists patents only for drugs that reached an approved FDA application,
# so the drug-level score exists only for drugs that already succeeded. The
# sponsor-level score needs no approval. Running the identical test on both is
# how the study checks whether an apparent patent effect is really an effect of
# having survived to approval.
_d = frame[frame.ip_index_drug.notna()].copy()
if len(_d) > 100:
    _thr = _d.ip_index_drug.median()
    _d["strong"] = (_d.ip_index_drug > _thr).astype(int)
    _ps = float(_d.loc[_d.strong == 1, "is_terminated"].mean())
    _pw = float(_d.loc[_d.strong == 0, "is_terminated"].mean())
    _ns = int((_d.strong == 1).sum()); _nw = int((_d.strong == 0).sum())
    _rd = _ps - _pw
    _pp = (_ps * _ns + _pw * _nw) / (_ns + _nw)
    _se = math.sqrt(_pp * (1 - _pp) * (1 / _ns + 1 / _nw))
    _z = _rd / _se if _se else float("nan")
    from scipy.stats import norm as _norm
    results["rq1_drug_level"] = {
        "what_this_is": ("the RQ1 test repeated on the Orange Book drug-level score, "
                         "which can only be computed for drugs that reached approval"),
        "n_computable": len(_d),
        "p_term_strong": round(_ps, 4),
        "p_term_weak": round(_pw, 4),
        "n_strong": _ns, "n_weak": _nw,
        "risk_difference": round(_rd, 4),
        "rd_ci95": [round(_rd - 1.96 * _se, 4), round(_rd + 1.96 * _se, 4)],
        "z": round(float(_z), 4),
        "p_value": float(2 * _norm.sf(abs(_z))),
    }
    print(f"  [drug-level, approval-selected] RD = {_rd:+.4f} on {len(_d):,} trials, "
          f"p = {2 * _norm.sf(abs(_z)):.3e}")

# How small an effect this sample could have detected, so that a null result can
# be reported as a precise finding rather than an absence of evidence.
_pp2 = (p_strong * nobs[0] + p_weak * nobs[1]) / (nobs[0] + nobs[1])
_se2 = math.sqrt(_pp2 * (1 - _pp2) * (1 / nobs[0] + 1 / nobs[1]))
results["rq1"]["precision"] = {
    "what_this_is": ("the smallest true difference this sample size could have "
                     "detected with 80% power at the 5% level"),
    "minimum_detectable_difference": round((1.959964 + 0.8416212) * _se2, 4),
    "ci_half_width": round(1.959964 * _se2, 4),
    "required_per_group_from_sample_size_chapter": 583,
    "actual_per_group": int(min(nobs)),
}
print(f"  smallest detectable difference {(1.959964 + 0.8416212) * _se2 * 100:.2f} pp "
      f"with {min(nobs):,} per group")

print(f"  strong {p_strong:.4f} (n={nobs[0]:,})  weak {p_weak:.4f} (n={nobs[1]:,})")
print(f"  RD = {rd:+.4f} [{rd - 1.96 * se_rd:+.4f}, {rd + 1.96 * se_rd:+.4f}]  z = {z:.3f}  p = {p:.3e}")
print(f"  Cramer's V = {cram:.4f}")

# Figure 5 - RQ1, with the uncomputable group shown rather than hidden
fig, ax = plt.subplots(figsize=(6.4, 3.0))
labels = ["Strong patents\n(above median)", "Weak patents\n(below median)", "Sponsor not\nmeasured"]
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
ax.set_title("RQ1: termination rate by sponsor patent strength, with the\nunmeasured group reported alongside")
save(tidy(ax).figure, "fig05_rq1_ip_strength.png")

# ----------------------------------------------------------------------------
# 8. RQ2 - preliminary prediction models on a temporal split
# ----------------------------------------------------------------------------
print("\n[8] RQ2")

model_frame = frame.copy()
train = model_frame[model_frame.start_year <= TRAIN_MAX]
test = model_frame[model_frame.start_year >= TEST_MIN]
print(f"  train {len(train):,} (2008-{TRAIN_MAX})   test {len(test):,} ({TEST_MIN}-2019)")

# The regulatory-only step is here so the increment from adding IP can be read on
# its own. Without it the last row bundles regulatory and IP together and no
# IP-specific conclusion can be drawn from the difference.
FEATURE_SETS = {
    "Design only": DESIGN,
    "Design + sponsor": DESIGN + SPONSOR,
    "Design + sponsor + regulatory": DESIGN + SPONSOR + REGULATORY,
    # The two IP blocks are entered separately as well as together, because the
    # whole question is whether the sponsor-level measure carries signal that
    # the drug-level one cannot, being available only for approved drugs.
    "Design + sponsor + regulatory + IP (drug)": DESIGN + SPONSOR + REGULATORY + IP_DRUG,
    "Design + sponsor + regulatory + IP (sponsor)": DESIGN + SPONSOR + REGULATORY + IP_SPONSOR,
    "Design + sponsor + regulatory + IP": DESIGN + SPONSOR + REGULATORY + IP_DRUG
                                           + IP_SPONSOR + BIOSIMILAR,
    "Design + sponsor + regulatory + IP + genetics": CANDIDATES,
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

# Discrimination was reported without any uncertainty attached, so the claim that
# the IP block "adds only 0.007 AUC" could not be distinguished from noise. The
# bootstrap is paired - every model is scored on the same resampled rows - so the
# increment between two nested models has a confidence interval of its own.
print("  bootstrapping AUC (1,000 paired resamples)")
rng = np.random.default_rng(SEED)
yte_arr = test.is_terminated.to_numpy()
boot_rows = [rng.integers(0, len(yte_arr), len(yte_arr)) for _ in range(1000)]
boot_auc = {}
for key, (_, pr) in fitted.items():
    vals = []
    for b in boot_rows:
        yb = yte_arr[b]
        if yb.min() == yb.max():
            continue
        vals.append(roc_auc_score(yb, pr[b]))
    boot_auc[key] = np.asarray(vals)

for row in perf:
    key = (row["features"], row["model"])
    if key in boot_auc:
        lo, hi = np.percentile(boot_auc[key], [2.5, 97.5])
        row["auc_ci95"] = [round(float(lo), 4), round(float(hi), 4)]

GB = "Gradient-boosted trees (HistGB)"


def increment(from_set, to_set):
    d = boot_auc[(to_set, GB)] - boot_auc[(from_set, GB)]
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {"from": from_set, "to": to_set,
            "delta_auc": round(float(d.mean()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "p_two_sided": round(float(2 * min((d <= 0).mean(), (d >= 0).mean())), 4)}


results["rq2_increments"] = [
    increment("Design only", "Design + sponsor"),
    increment("Design + sponsor", "Design + sponsor + regulatory"),
    increment("Design + sponsor + regulatory", "Design + sponsor + regulatory + IP (drug)"),
    increment("Design + sponsor + regulatory", "Design + sponsor + regulatory + IP (sponsor)"),
    increment("Design + sponsor + regulatory", "Design + sponsor + regulatory + IP"),
    increment("Design + sponsor", "Design + sponsor + regulatory + IP"),
    increment("Design + sponsor + regulatory + IP",
              "Design + sponsor + regulatory + IP + genetics"),
]
for inc in results["rq2_increments"]:
    print(f"  + {inc['to'].split('+')[-1].strip():12s} dAUC {inc['delta_auc']:+.4f} "
          f"[{inc['ci95'][0]:+.4f}, {inc['ci95'][1]:+.4f}]  p = {inc['p_two_sided']:.3f}")

# The increments above are computed on the whole holdout, where the drug-level IP
# block is absent for roughly two-thirds of rows and the learner routes those down
# a missing branch. A near-zero increment is therefore partly a measure of how often
# the block is populated rather than of what it carries. The honest test of H2b is
# the same comparison restricted to trials where the block exists, so both are
# reported and the report draws its conclusion from the pair.
print("  increments on the IP-computable subsample")
sub = model_frame[model_frame.ob_n_patents.notna()]
sub_train = sub[sub.start_year <= TRAIN_MAX]
sub_test = sub[sub.start_year >= TEST_MIN]
ysub = sub_test.is_terminated.to_numpy()
rng_sub = np.random.default_rng(SEED + 1)
sub_boot = [rng_sub.integers(0, len(ysub), len(ysub)) for _ in range(1000)]
sub_auc = {}
for set_name, feats in FEATURE_SETS.items():
    g = HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.06, max_iter=400, l2_regularization=1.0,
        class_weight="balanced", early_stopping=True, validation_fraction=0.15,
        random_state=SEED,
    ).fit(sub_train[feats], sub_train.is_terminated)
    pr = g.predict_proba(sub_test[feats])[:, 1]
    vals = []
    for b in sub_boot:
        yb = ysub[b]
        if yb.min() == yb.max():
            continue
        vals.append(roc_auc_score(yb, pr[b]))
    sub_auc[set_name] = np.asarray(vals)


def sub_increment(from_set, to_set):
    d = sub_auc[to_set] - sub_auc[from_set]
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {"from": from_set, "to": to_set,
            "delta_auc": round(float(d.mean()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "p_two_sided": round(float(2 * min((d <= 0).mean(), (d >= 0).mean())), 4)}


results["rq2_increments_subsample"] = {
    "note": "Same nested comparison restricted to trials with an observable "
            "drug-level IP block, so the block is populated for every row.",
    "train_n": int(len(sub_train)),
    "test_n": int(len(sub_test)),
    "test_terminated": int(ysub.sum()),
    "auc_full_model": round(float(np.mean(sub_auc["Design + sponsor + regulatory + IP"])), 4),
    "increments": [
        sub_increment("Design + sponsor", "Design + sponsor + regulatory"),
        sub_increment("Design + sponsor + regulatory", "Design + sponsor + regulatory + IP"),
    ],
}
for inc in results["rq2_increments_subsample"]["increments"]:
    print(f"    [sub] + {inc['to'].split('+')[-1].strip():12s} dAUC {inc['delta_auc']:+.4f} "
          f"[{inc['ci95'][0]:+.4f}, {inc['ci95'][1]:+.4f}]  p = {inc['p_two_sided']:.3f}")

results["rq2_performance"] = perf
results["rq2_split"] = {"train_n": len(train), "test_n": len(test),
                        "test_terminated": int(test.is_terminated.sum()),
                        "test_completed": int((test.is_terminated == 0).sum()),
                        "no_information_rate": round(nir, 4)}

best_key = ("Design + sponsor + regulatory + IP", "Gradient-boosted trees (HistGB)")
best_model, best_pr = fitted[best_key]
feats_best = FEATURE_SETS[best_key[0]]

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
# Van Calster et al. (2019), which this study cites for calibration, define the
# slope as the coefficient from a logistic regression of the outcome on the linear
# predictor at individual level. An OLS line through ten decile points on the
# probability scale measures something else, and reported an intercept near zero
# while mean predicted risk was close to twice the observed rate. Calibration in
# the large is reported alongside, because that is the number that carries the
# severity.
import statsmodels.api as sm

eps = 1e-9
pc = np.clip(best_pr, eps, 1 - eps)
lp = np.log(pc / (1 - pc))
cal_fit = sm.Logit(test.is_terminated.to_numpy(),
                   sm.add_constant(lp)).fit(disp=0)
intercept, slope = float(cal_fit.params[0]), float(cal_fit.params[1])
mean_pred = float(best_pr.mean())
observed = float(test.is_terminated.mean())
ax.set_xlabel("Mean predicted probability")
ax.set_ylabel("Observed termination rate")
ax.set_title(f"RQ2: calibration by risk decile (slope {slope:.2f})\n"
             f"mean predicted {mean_pred:.1%} vs observed {observed:.1%}")
ax.legend(fontsize=8, loc="upper left")
ax.xaxis.grid(True)
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig08_calibration.png")
results["rq2_calibration"] = {
    "method": "logistic recalibration of the outcome on the linear predictor "
              "(Van Calster et al., 2019); ideal slope 1, intercept 0",
    "slope": round(float(slope), 4),
    "intercept": round(float(intercept), 4),
    "mean_predicted_risk": round(mean_pred, 4),
    "observed_rate": round(observed, 4),
    "over_prediction_ratio": round(mean_pred / observed, 3),
    "deciles": [{"decile": int(i) + 1, "predicted": round(float(r.pred), 4),
                 "observed": round(float(r.obs), 4), "n": int(r.n)} for i, r in cal.iterrows()],
}

# The calibration failure is a level shift, which class weighting produces, so it
# should yield to a one-parameter correction: hold the slope at one and re-estimate
# the intercept only. The correction is fitted on the TRAINING period and then
# applied unchanged to the holdout. Fitting it on the holdout would report the
# in-sample fit of the correction itself, which cannot fail and would prove nothing.
# The holdout-fitted value is carried alongside only to show what the transfer costs.
print("  intercept-only recalibration (fitted on train, applied to holdout)")
pc_tr = np.clip(best_model.predict_proba(train[feats_best])[:, 1], eps, 1 - eps)
lp_tr = np.log(pc_tr / (1 - pc_tr))
a_train = float(
    sm.GLM(train.is_terminated.to_numpy(), np.ones((len(train), 1)),
           family=sm.families.Binomial(), offset=lp_tr).fit().params[0]
)
a_test = float(
    sm.GLM(test.is_terminated.to_numpy(), np.ones((len(test), 1)),
           family=sm.families.Binomial(), offset=lp).fit().params[0]
)
pr_corr = 1.0 / (1.0 + np.exp(-(lp + a_train)))
cal_fit_c = sm.Logit(test.is_terminated.to_numpy(),
                     sm.add_constant(np.log(np.clip(pr_corr, eps, 1 - eps) /
                                            (1 - np.clip(pr_corr, eps, 1 - eps))))).fit(disp=0)
results["rq2_calibration_corrected"] = {
    "method": "intercept-only (slope fixed at 1) logistic offset correction; the "
              "offset is estimated on the 2008-2015 training period and applied "
              "unchanged to the 2016-2019 holdout",
    "intercept_offset_fitted_on_train": round(a_train, 4),
    "intercept_offset_fitted_on_holdout": round(a_test, 4),
    "transfer_gap": round(a_test - a_train, 4),
    "slope_after": round(float(cal_fit_c.params[1]), 4),
    "intercept_after": round(float(cal_fit_c.params[0]), 4),
    "mean_predicted_risk_after": round(float(pr_corr.mean()), 4),
    "observed_rate": round(observed, 4),
    "over_prediction_ratio_after": round(float(pr_corr.mean()) / observed, 3),
    "brier_before": round(float(brier_score_loss(test.is_terminated, best_pr)), 4),
    "brier_after": round(float(brier_score_loss(test.is_terminated, pr_corr)), 4),
    "auc_unchanged": round(float(roc_auc_score(test.is_terminated, pr_corr)), 4),
}
_rc = results["rq2_calibration_corrected"]
print(f"    offset {a_train:+.4f} (holdout-fitted {a_test:+.4f})  "
      f"mean predicted {_rc['mean_predicted_risk_after']:.4f} vs observed {observed:.4f}  "
      f"ratio {_rc['over_prediction_ratio_after']:.3f}")

# ----------------------------------------------------------------------------
# RQ1 selection: the drug-level index exists only where a drug reached an approved
# FDA application, so the RQ1 estimate describes an approval-selected population.
# Two treatments are reported. Inverse-probability weighting reweights the observed
# subsample to the full frame on design and sponsor covariates, which identifies the
# frame-level risk difference if observability is ignorable given those covariates.
# That assumption is not testable here, so worst-case bounds are reported alongside:
# the outcome IS known for every trial in the frame, and only the IP class is
# unknown, so assigning the unobserved trials wholly to one group and then the other
# brackets the risk difference without any assumption at all.
# ----------------------------------------------------------------------------
print("\n[9b] RQ1 selection: inverse-probability weighting and worst-case bounds")
# Run on the PRIMARY, sponsor-level measure, since that is the one RQ1 reports.
# An earlier version ran it on the Orange Book measure after the primary had moved.
#
# The reweighting needs every kind of trial to have some chance of being measured.
# Non-industry sponsors have essentially none (a university holds no commercial
# portfolio to match), so no weighting can make measured trials stand in for them,
# and a propensity model on the whole frame is separated by sponsor class. The
# reweighting therefore targets INDUSTRY trials, where coverage is about two in
# three. The worst-case bounds below need no such condition and use the whole frame.
from sklearn.linear_model import LogisticRegression as _LR

sel = frame.copy()
sel["observed_ip"] = sel.ip_strong.notna().astype(int)
ind = sel[sel.is_industry == 1].copy()
_pcols = DESIGN + ["n_collaborators", "sponsor_prior_trials", "sponsor_prior_completion_rate"]
sel_X = ind[_pcols].copy()
sel_X = sel_X.fillna(sel_X.median(numeric_only=True))
_sx = StandardScaler().fit_transform(sel_X.to_numpy(dtype=float))
_pm = _LR(C=1.0, max_iter=2000).fit(_sx, ind.observed_ip.to_numpy())
pi_hat = np.clip(_pm.predict_proba(_sx)[:, 1], 0.02, 0.98)
ind["w"] = np.where(ind.observed_ip == 1, 1.0 / pi_hat, 0.0)
o_ind = ind[ind.observed_ip == 1]
ws, ww = o_ind[o_ind.ip_strong == 1], o_ind[o_ind.ip_strong == 0]
o = sel[sel.observed_ip == 1]


def wmean(g):
    return float(np.average(g.is_terminated, weights=g.w))


rd_ipw = wmean(ws) - wmean(ww)
n_unobs = int((sel.observed_ip == 0).sum())
p_unobs = float(sel.loc[sel.observed_ip == 0, "is_terminated"].mean())
n_s, n_w = int((o.ip_strong == 1).sum()), int((o.ip_strong == 0).sum())
p_s, p_w = float(o.loc[o.ip_strong == 1, "is_terminated"].mean()), float(o.loc[o.ip_strong == 0, "is_terminated"].mean())
# Upper bound on the risk difference: the unobserved go to the strong group.
rd_hi = ((n_s * p_s + n_unobs * p_unobs) / (n_s + n_unobs)) - p_w
# Lower bound: the unobserved go to the weak group.
rd_lo = p_s - ((n_w * p_w + n_unobs * p_unobs) / (n_w + n_unobs))
# The same bounds within industry trials, the population the patent measure can reach.
_ui = ind[ind.observed_ip == 0]
_ni_u, _pi_u = len(_ui), float(_ui.is_terminated.mean())
_ns_i, _nw_i = len(ws), len(ww)
_ps_i, _pw_i = float(ws.is_terminated.mean()), float(ww.is_terminated.mean())
rd_hi_ind = ((_ns_i * _ps_i + _ni_u * _pi_u) / (_ns_i + _ni_u)) - _pw_i
rd_lo_ind = _ps_i - ((_nw_i * _pw_i + _ni_u * _pi_u) / (_nw_i + _ni_u))
results["rq1_selection"] = {
    "observed_n": int(len(o)),
    "unobserved_n": n_unobs,
    "p_term_unobserved": round(p_unobs, 4),
    "ipw": {
        "method": "inverse probability of observability among INDUSTRY trials, "
                  "propensity on the design block and sponsor history, "
                  "probabilities trimmed to [0.02, 0.98]",
        "target_population": "industry-sponsored trials",
        "why_not_whole_frame": "positivity fails: non-industry trials are almost "
                               "never measurable, so no weight can represent them",
        "industry_n": int(len(ind)),
        "industry_measured_n": int(len(o_ind)),
        "risk_difference": round(rd_ipw, 4),
        "unweighted_risk_difference_industry": round(
            float(o_ind.loc[o_ind.ip_strong == 1, "is_terminated"].mean()
                  - o_ind.loc[o_ind.ip_strong == 0, "is_terminated"].mean()), 4),
        "unweighted_risk_difference": round(p_s - p_w, 4),
        "effective_n": round(float(o_ind.w.sum()), 1),
        "assumption": "observability ignorable given design and sponsor history, "
                      "within industry sponsors",
    },
    "worst_case_bounds": {
        "measure": "sponsor-level index (the RQ1 primary)",
        "method": "outcome is observed for all 39,437 trials and only the IP class "
                  "is unknown, so the unobserved are assigned wholly to one group "
                  "and then the other; no ignorability assumption",
        "risk_difference_lower": round(rd_lo, 4),
        "risk_difference_upper": round(rd_hi, 4),
        "sign_identified": bool(rd_lo < 0 and rd_hi < 0),
    },
    "worst_case_bounds_industry": {
        "unobserved_industry_n": int(_ni_u),
        "p_term_unobserved_industry": round(_pi_u, 4),
        "risk_difference_lower": round(rd_lo_ind, 4),
        "risk_difference_upper": round(rd_hi_ind, 4),
    },
}
print(f"  IPW risk difference {rd_ipw:+.4f} (unweighted {p_s - p_w:+.4f})")
print(f"  worst-case bounds [{rd_lo:+.4f}, {rd_hi:+.4f}]  "
      f"sign identified: {results['rq1_selection']['worst_case_bounds']['sign_identified']}")

# ----------------------------------------------------------------------------
# Unresolved outcomes: 8,173 in-window trials are dropped for having no resolved
# status. That exclusion conditions on a variable related to the outcome, so the
# termination probability is bracketed by assigning the dropped trials wholly to
# completion and then wholly to termination. The bounds are wide by construction;
# the point is that the reported rate is not a point estimate of the in-window rate.
# ----------------------------------------------------------------------------
unres_n = int(n_window - len(frame))
term_n = int(frame.is_terminated.sum())
results["unresolved_sensitivity"] = {
    "in_window_n": int(n_window),
    "resolved_n": int(len(frame)),
    "unresolved_n": unres_n,
    "p_terminated_resolved_only": round(float(frame.is_terminated.mean()), 4),
    "p_terminated_if_all_unresolved_complete": round(term_n / n_window, 4),
    "p_terminated_if_all_unresolved_terminate": round((term_n + unres_n) / n_window, 4),
    "note": "Unresolved trials are disproportionately later-starting and still "
            "active; the resolved-only rate is the estimand the study reports and "
            "the bounds state what the exclusion could at most be hiding.",
}
_us = results["unresolved_sensitivity"]
print(f"  p(termination) resolved-only {_us['p_terminated_resolved_only']:.4f}  "
      f"bounds [{_us['p_terminated_if_all_unresolved_complete']:.4f}, "
      f"{_us['p_terminated_if_all_unresolved_terminate']:.4f}]")

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
            **{c: "Regulatory" for c in REGULATORY}, **{c: "IP" for c in IP_DRUG},
            **{c: "IP" for c in IP_SPONSOR},
            **{c: "IP" for c in BIOSIMILAR},
            **{c: "Genetic" for c in GENETIC}}
cmap = {"Design": BLUE, "Sponsor": BLUE, "Regulatory": ORANGE, "IP": AQUA,
        "Genetic": ORANGE}
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
save(ax.figure, "fig07_permutation_importance.png")

# ----------------------------------------------------------------------------
# 9. RQ3 - competing risks, preliminary
# ----------------------------------------------------------------------------
print("\n[9] RQ3")

from lifelines import AalenJohansenFitter, CoxPHFitter
from lifelines.statistics import proportional_hazard_test

surv = frame[frame.months_to_primary_completion.notna()
             & (frame.months_to_primary_completion > 0)].copy()
surv["status"] = np.where(surv.is_terminated == 1, 2, 1)
# Reported rather than silent: the survival models run on fewer trials than the
# classification models, and the cleaning log has to say so.
results["rq3_exclusions"] = {
    "analytic_frame": int(len(frame)),
    "dropped_no_duration": int(frame.months_to_primary_completion.isna().sum()),
    "dropped_nonpositive_duration": int((frame.months_to_primary_completion <= 0).sum()),
    "survival_n": int(len(surv)),
}
results["rq3"] = {
    "n": int(len(surv)),
    "completed": int((surv.status == 1).sum()),
    "terminated_competing": int((surv.status == 2).sum()),
    "median_months_completed": float(surv.loc[surv.status == 1, "months_to_primary_completion"].median()),
    "median_months_terminated": float(surv.loc[surv.status == 2, "months_to_primary_completion"].median()),
}

sv = surv[surv.ip_strong.notna()].copy()
sv["ip_strong"] = sv.ip_strong.astype(int)
sv["cluster"] = sv.sponsor_cluster
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
    cx = sv[["months_to_primary_completion", "status", "cluster"] + COVARS].dropna().copy()
    cx["event"] = (cx.status == cause).astype(int)
    cx = cx.drop(columns="status")
    cph = CoxPHFitter().fit(cx, duration_col="months_to_primary_completion",
                            event_col="event", cluster_col="cluster")
    summ = cph.summary[["exp(coef)", "exp(coef) lower 95%", "exp(coef) upper 95%", "p"]]
    # Schoenfeld (1983) is cited for the sample size but the assumption his test
    # checks was never reported. A global p below .05 means the hazard ratio is not
    # constant over follow-up and the single HR is a time-average.
    ph = proportional_hazard_test(cph, cx, time_transform="rank")
    ph_tbl = ph.summary
    results["rq3"][f"cox_{name}"] = {
        "n": int(len(cx)),
        "events": int(cx.event.sum()),
        "n_clusters": int(cx.cluster.nunique()),
        "standard_errors": "cluster-robust on the sponsor corporate group",
        "concordance": round(float(cph.concordance_index_), 4),
        "ph_test_global_p": round(float(ph_tbl["p"].min()), 6),
        "ph_violations_p05": [str(i) for i, r in ph_tbl.iterrows() if r["p"] < 0.05],
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

    # Reporting that proportional hazards is rejected leaves the reader unable to
    # judge how much it matters. Splitting follow-up at two years and re-fitting
    # within each window makes the time-dependence legible: if the early and late
    # hazard ratios bracket the pooled one and agree in direction, the time-average
    # is conservative but usable, and if they cross, it is not interpretable at all.
    # This is a diagnostic, not a substitute for the Fine-Gray subdistribution model
    # scheduled for week 8.
    pieces = {}
    for lo, hi, lbl in [(0.0, 24.0, "0-24 months"), (24.0, np.inf, "over 24 months")]:
        w = cx.copy()
        if np.isfinite(hi):
            w["event"] = np.where(w.months_to_primary_completion > hi, 0, w.event)
            w["months_to_primary_completion"] = w.months_to_primary_completion.clip(upper=hi)
        else:
            w = w[w.months_to_primary_completion > lo].copy()
        w = w[w.months_to_primary_completion > 0]
        if w.event.sum() < 50 or w.event.nunique() < 2:
            continue
        try:
            c2 = CoxPHFitter().fit(w, duration_col="months_to_primary_completion",
                                   event_col="event", cluster_col="cluster")
            r2 = c2.summary.loc["ip_strong"]
            pieces[lbl] = {
                "events": int(w.event.sum()),
                "hr": round(float(r2["exp(coef)"]), 4),
                "ci95": [round(float(r2["exp(coef) lower 95%"]), 4),
                         round(float(r2["exp(coef) upper 95%"]), 4)],
                "p": float(r2["p"]),
            }
        except Exception as exc:  # a window can be too thin to converge
            pieces[lbl] = {"error": type(exc).__name__}
    hrs = [v["hr"] for v in pieces.values() if "hr" in v]
    results["rq3"][f"cox_{name}"]["piecewise_ip_strong"] = {
        "note": "cause-specific Cox re-fitted within follow-up windows, so the "
                "pooled hazard ratio can be read against its time-specific values",
        "windows": pieces,
        "same_direction": bool(hrs and (all(h < 1 for h in hrs) or all(h > 1 for h in hrs))),
    }
    _pw = results["rq3"][f"cox_{name}"]["piecewise_ip_strong"]
    print("    piecewise HR(ip_strong): " + ", ".join(
        f"{k} {v['hr']:.3f}" for k, v in pieces.items() if "hr" in v)
        + f"  (same direction: {_pw['same_direction']})")

# Fine-Gray subdistribution hazards. The frame holds resolved trials only, so
# follow-up is complete and no trial is censored. With complete data the Fine and
# Gray (1999) estimator reduces exactly to an ordinary Cox fit in which a trial that
# met the competing event stays in the risk set to the end of follow-up, because its
# censoring weight is 1 throughout. It is fitted that way here: the competing
# event's time is moved past the last observed time and coded as censored there.
fine_gray = {}
for cause, name in [(1, "completion"), (2, "termination")]:
    cx = sv[["months_to_primary_completion", "status", "cluster"] + COVARS].dropna().copy()
    t_end = float(cx.months_to_primary_completion.max()) + 1.0
    other = cx.status != cause
    cx["event"] = (~other).astype(int)
    cx.loc[other, "months_to_primary_completion"] = t_end
    cx = cx.drop(columns="status")
    fgf = CoxPHFitter().fit(cx, duration_col="months_to_primary_completion",
                            event_col="event", cluster_col="cluster")
    rr = fgf.summary.loc["ip_strong"]
    fine_gray[name] = {
        "n": int(len(cx)),
        "events": int(cx.event.sum()),
        "shr": round(float(rr["exp(coef)"]), 4),
        "ci95": [round(float(rr["exp(coef) lower 95%"]), 4),
                 round(float(rr["exp(coef) upper 95%"]), 4)],
        "p": float(rr["p"]),
        "industry_shr": round(float(fgf.summary.loc["is_industry", "exp(coef)"]), 4),
    }
    print(f"  Fine-Gray {name}: sHR(ip_strong) = {rr['exp(coef)']:.4f} "
          f"[{rr['exp(coef) lower 95%']:.4f}, {rr['exp(coef) upper 95%']:.4f}], "
          f"p = {rr['p']:.3f}")
results["rq3"]["fine_gray"] = {
    "method": "Fine-Gray subdistribution hazards, fitted exactly as a Cox model with "
              "competing-event trials retained in the risk set (complete follow-up, "
              "no censoring); cluster-robust on the sponsor corporate group",
    **fine_gray,
}
results["rq3"]["event_coding"] = {
    "completion_event": "overall_status COMPLETED, time = primary completion date minus start date",
    "competing_event": "overall_status TERMINATED, WITHDRAWN or SUSPENDED, time = recorded "
                       "primary completion (stop) date minus start date",
    "censored": "none: unresolved statuses (RECRUITING, ACTIVE_NOT_RECRUITING, "
                "NOT_YET_RECRUITING, ENROLLING_BY_INVITATION, UNKNOWN) are outside the frame",
    "n_by_status": {str(k): int(v) for k, v in
                    sv.overall_status.value_counts().items()},
}

# ----------------------------------------------------------------------------
# 10. RQ4 - moderation by therapeutic area, preliminary
# ----------------------------------------------------------------------------
print("\n[10] RQ4")

import statsmodels.formula.api as smf

mod = frame[frame.ip_strong.notna()].copy()
mod["ip_strong"] = mod.ip_strong.astype(int)
mod["cluster"] = mod.sponsor_cluster
# How many trials, and how many terminations, each therapeutic area holds in each
# patent group within the subsample RQ4 actually runs on, so the per-stratum sample
# size requirement can be checked against the usable data rather than the frame.
_cells = (mod.groupby(["therapeutic_area", "ip_strong"])
          .is_terminated.agg(["size", "sum"]).unstack("ip_strong"))
results["rq4_cells"] = [
    {"area": str(a),
     "n_strong": int(r[("size", 1)]), "n_weak": int(r[("size", 0)]),
     "terminated_strong": int(r[("sum", 1)]), "terminated_weak": int(r[("sum", 0)]),
     "p_strong": round(float(r[("sum", 1)] / r[("size", 1)]), 4),
     "p_weak": round(float(r[("sum", 0)] / r[("size", 0)]), 4)}
    for a, r in _cells.iterrows()
]
F0 = "is_terminated ~ ip_strong + C(therapeutic_area) + is_phase3 + is_industry"
F1 = "is_terminated ~ ip_strong * C(therapeutic_area) + is_phase3 + is_industry"
m0 = smf.logit(F0, data=mod).fit(disp=0)
m1 = smf.logit(F1, data=mod).fit(disp=0)
lr_stat = float(2 * (m1.llf - m0.llf))
df_diff = int(m1.df_model - m0.df_model)

# The likelihood ratio test assumes independent observations, which trials sharing a
# sponsor violate. A Wald test on the same interaction terms under a cluster-robust
# covariance is the comparable statistic that does not.
m1c = smf.logit(F1, data=mod).fit(disp=0, cov_type="cluster",
                                  cov_kwds={"groups": mod.cluster})
terms = [k for k in m1c.params.index if "ip_strong:" in k]
names = list(m1c.params.index)
R = np.zeros((len(terms), len(names)))
for i, k in enumerate(terms):
    R[i, names.index(k)] = 1.0
wald = m1c.wald_test(R, scalar=True)

# Holm across the stratum interactions, since six are tested and read individually.
raw_p = np.array([float(m1c.pvalues[k]) for k in terms])
order = np.argsort(raw_p)
holm = np.empty_like(raw_p)
running = 0.0
for rank, j in enumerate(order):
    running = max(running, (len(raw_p) - rank) * raw_p[j])
    holm[j] = min(1.0, running)

results["rq4_clustered"] = {
    "n_clusters": int(mod.cluster.nunique()),
    "wald_chi2": round(float(wald.statistic), 4),
    "df": len(terms),
    "p_value": float(wald.pvalue),
    "interaction_terms": {
        k: {"or": round(float(np.exp(m1c.params[k])), 4),
            "p": float(m1c.pvalues[k]),
            "p_holm": round(float(holm[i]), 4)}
        for i, k in enumerate(terms)
    },
}
print(f"  clustered Wald chi2 = {float(wald.statistic):.3f}, df = {len(terms)}, "
      f"p = {float(wald.pvalue):.4f}  (naive LR p = {chi2_dist.sf(lr_stat, df_diff):.4f})")
print(f"  strata significant after Holm: "
      f"{sum(1 for v in results['rq4_clustered']['interaction_terms'].values() if v['p_holm'] < 0.05)}"
      f"/{len(terms)}")
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

# ----------------------------------------------------------------------------
# 11. Entity-resolution precision, from the adjudicated sample
# ----------------------------------------------------------------------------
# Read back rather than retyped, on the same principle as everything else here:
# the report quotes the audit, so the audit has to reach the report as data.
VAL = ROOT / "data" / "validation"
samp = pd.read_csv(VAL / "precision_sample_200.csv")
wt = pd.read_csv(VAL / "precision_sample_weights.csv")
verdict = samp.verdict.fillna("").str.strip().str.upper()
done = samp[verdict.isin(["CORRECT", "WRONG", "PARTIAL"])].copy()
if len(done):
    print(f"\n[11] Entity-resolution precision ({len(done)}/{len(samp)} adjudicated)")
    done["correct"] = verdict[done.index].isin(["CORRECT", "PARTIAL"]).astype(int)
    done["strict"] = verdict[done.index].eq("CORRECT").astype(int)
    rows = []
    for meth, g in done.groupby("method"):
        w = wt[wt.method == meth]
        rows.append({"method": meth, "n_judged": len(g), "precision": g.correct.mean(),
                     "strict_precision": g.strict.mean(),
                     "pop_share": float(w.pop_share.iloc[0]) if len(w) else 0.0})
    r = pd.DataFrame(rows)
    r["pop_share"] = r.pop_share / r.pop_share.sum()
    overall = float((r.pop_share * r.precision).sum())
    strict = float((r.pop_share * r.strict_precision).sum())
    se = float(np.sqrt((r.pop_share ** 2 * r.precision * (1 - r.precision) / r.n_judged).sum()))
    results["entity_resolution_precision"] = {
        "n_adjudicated": int(len(done)),
        "n_sampled": int(len(samp)),
        "weighting": "stratified by match method, weighted to population share",
        "precision": round(overall, 4),
        "strict_precision": round(strict, 4),
        "se": round(se, 4),
        "ci95": [round(overall - 1.96 * se, 4), round(overall + 1.96 * se, 4)],
        "meets_90pct_target": bool(overall - 1.96 * se >= 0.90),
        "by_method": [
            {"method": x.method, "n_judged": int(x.n_judged),
             "precision": round(float(x.precision), 4),
             "strict_precision": round(float(x.strict_precision), 4),
             "pop_share": round(float(x.pop_share), 4)}
            for x in r.itertuples()
        ],
        "verdict_counts": {k: int(v) for k, v in verdict[done.index].value_counts().items()},
    }
    print(f"  weighted precision {overall:.4f} "
          f"[{overall - 1.96 * se:.4f}, {overall + 1.96 * se:.4f}]  "
          f"strict {strict:.4f}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(results, indent=2, default=str))
print(f"\nwrote {OUT.relative_to(ROOT)}")
print(f"wrote {len(list(FIGS.glob('*.png')))} figures to {FIGS.relative_to(ROOT)}")
