"""Final-stage modelling and figures for the QM 640 final report.

Rebuilds the analytic frame by running interim_eda.py (which also refreshes
docs/interim_results.json), then adds what the final report needs on top of it:

  * model selection on a validation period the test set never sees: each model
    family is tuned on trials starting 2008-2013 and judged on 2014-2015, the
    chosen settings are refitted on 2008-2015, and the 2016-2019 test period is
    scored exactly once;
  * training, validation and test metrics for every family, including a
    feed-forward neural network as the deep-learning comparator;
  * recalibration and an operating threshold, both fixed on the validation period;
  * the confusion matrix, risk concentration by decile, SHAP attributions and a
    worked example of one scored trial;
  * the patent-block increment re-tested with the tuned model;
  * the inclusion/exclusion flow diagram and the system architecture diagram;
  * an inventory of the analysis-ready tables, and a saved model for scoring.

Writes docs/final_results.json, docs/figures/fig10-fig16, and models/.

    python scripts/analysis/final_analysis.py
"""

from __future__ import annotations

import json
import os
import platform
import runpy
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ns = runpy.run_path(str(ROOT / "scripts" / "analysis" / "interim_eda.py"), run_name="__eda__")

import matplotlib.pyplot as plt  # noqa: E402  (style set by interim_eda)
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import brier_score_loss, confusion_matrix, roc_auc_score, roc_curve  # noqa: E402
from sklearn.neural_network import MLPClassifier  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
import statsmodels.api as sm  # noqa: E402

frame = ns["frame"]
R = ns["results"]
SEED = ns["SEED"]
BLUE, ORANGE, AQUA = ns["BLUE"], ns["ORANGE"], ns["AQUA"]
INK, INK_SOFT, GRID = ns["INK"], ns["INK_SOFT"], ns["GRID"]
tidy, save = ns["tidy"], ns["save"]
FIGS = ns["FIGS"]
FEATURE_SETS = ns["FEATURE_SETS"]
FULL = "Design + sponsor + regulatory + IP"
NO_IP = "Design + sponsor + regulatory"
FEATS = FEATURE_SETS[FULL]
out: dict = {}

print("\n[F1] Temporal partitions")
train = frame[frame.start_year <= 2015]
test = frame[frame.start_year >= 2016]
dev = train[train.start_year <= 2013]
val = train[train.start_year >= 2014]
y_tr, y_te = train.is_terminated.to_numpy(), test.is_terminated.to_numpy()
y_dev, y_val = dev.is_terminated.to_numpy(), val.is_terminated.to_numpy()
out["partitions"] = {
    "development": {"years": "2008-2013", "n": len(dev), "terminated": int(y_dev.sum()),
                    "rate": round(float(y_dev.mean()), 4)},
    "validation": {"years": "2014-2015", "n": len(val), "terminated": int(y_val.sum()),
                   "rate": round(float(y_val.mean()), 4)},
    "training": {"years": "2008-2015", "n": len(train), "terminated": int(y_tr.sum()),
                 "rate": round(float(y_tr.mean()), 4)},
    "test": {"years": "2016-2019", "n": len(test), "terminated": int(y_te.sum()),
             "rate": round(float(y_te.mean()), 4)},
    "frame_rate": round(float(frame.is_terminated.mean()), 4),
    "test_rate_by_year": {int(y): round(float(g.is_terminated.mean()), 4)
                          for y, g in test.groupby("start_year")},
}
for k, v in out["partitions"].items():
    print(f"  {k}: {v}")


def make(family, params):
    if family == "L1-penalised logistic regression":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
            LogisticRegression(penalty="l1", solver="liblinear", class_weight="balanced",
                               max_iter=3000, random_state=SEED, **params))
    if family == "Random forest":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            RandomForestClassifier(n_estimators=300, max_features="sqrt",
                                   class_weight="balanced_subsample", n_jobs=-1,
                                   random_state=SEED, **params))
    if family == "Gradient-boosted trees":
        return HistGradientBoostingClassifier(
            max_iter=600, early_stopping=True, validation_fraction=0.15,
            class_weight="balanced", random_state=SEED, **params)
    if family == "Neural network (MLP)":
        # A feed-forward network with two hidden layers. MLPClassifier takes no class
        # weights, so it is trained on the natural class balance; AUC is unaffected
        # and the operating threshold is set on the validation period like the rest.
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
            MLPClassifier(early_stopping=True, validation_fraction=0.15, max_iter=400,
                          learning_rate_init=1e-3, random_state=SEED, **params))
    raise ValueError(family)


GRIDS = {
    "L1-penalised logistic regression": [{"C": c} for c in (0.01, 0.03, 0.1, 0.3, 1.0)],
    "Random forest": [{"min_samples_leaf": m} for m in (5, 20, 50)],
    "Gradient-boosted trees": [
        {"learning_rate": lr, "max_depth": d, "min_samples_leaf": m, "l2_regularization": 1.0}
        for lr in (0.03, 0.06, 0.1) for d in (3, 4, 6) for m in (20, 100)],
    "Neural network (MLP)": [
        {"hidden_layer_sizes": h, "alpha": a}
        for h in ((64, 32), (128, 64)) for a in (1e-4, 1e-3, 1e-2)],
}

print("\n[F2] Model selection on the 2014-2015 validation period")
selection = {}
for fam, grid in GRIDS.items():
    rows = []
    for params in grid:
        t0 = time.perf_counter()
        m = make(fam, params).fit(dev[FEATS], y_dev)
        secs = time.perf_counter() - t0
        pv = m.predict_proba(val[FEATS])[:, 1]
        rows.append({"params": {k: (list(v) if isinstance(v, tuple) else v)
                                for k, v in params.items()},
                     "val_auc": round(float(roc_auc_score(y_val, pv)), 4),
                     "val_brier": round(float(brier_score_loss(y_val, pv)), 4),
                     "fit_seconds": round(secs, 1)})
    best = max(rows, key=lambda r: (r["val_auc"], -r["val_brier"]))
    selection[fam] = {"n_configurations": len(rows), "chosen": best["params"],
                      "chosen_val_auc": best["val_auc"], "grid": rows}
    print(f"  {fam:34s} {len(rows):2d} configs; best val AUC {best['val_auc']:.4f} {best['params']}")
out["selection"] = selection


def youden_threshold(y, p):
    fpr, tpr, thr = roc_curve(y, p)
    return float(thr[np.argmax(tpr - fpr)])


def at_threshold(y, p, thr):
    yh = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, yh, labels=[0, 1]).ravel()
    sens = tp / (tp + fn) if tp + fn else float("nan")
    spec = tn / (tn + fp) if tn + fp else float("nan")
    prec = tp / (tp + fp) if tp + fp else float("nan")
    return {"accuracy": round(float((tp + tn) / len(y)), 4),
            "balanced_accuracy": round(float((sens + spec) / 2), 4),
            "sensitivity": round(float(sens), 4), "specificity": round(float(spec), 4),
            "precision": round(float(prec), 4),
            "f1": round(float(2 * prec * sens / (prec + sens)), 4) if prec + sens else 0.0,
            "flagged_share": round(float(yh.mean()), 4),
            "confusion": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)}}


def logit(p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


print("\n[F3] Refit on 2008-2015, score 2016-2019 once")
final_models, test_pred, train_pred = {}, {}, {}
perf = []
nir_acc = float(max(y_te.mean(), 1 - y_te.mean()))
perf.append({"model": "No-information rate (majority class)", "features": "None",
             "train_auc": 0.5, "val_auc": 0.5, "test_auc": 0.5,
             "train_accuracy": round(float(max(y_tr.mean(), 1 - y_tr.mean())), 4),
             "test_accuracy": round(nir_acc, 4),
             "test_brier": round(float(brier_score_loss(y_te, np.full(len(y_te), y_tr.mean()))), 4)})
for fam in GRIDS:
    params = {k: (tuple(v) if isinstance(v, list) else v)
              for k, v in selection[fam]["chosen"].items()}
    # threshold and calibration offset come from the development model scored on
    # the validation period, so neither is tuned on the test set
    m_dev = make(fam, params).fit(dev[FEATS], y_dev)
    pv = m_dev.predict_proba(val[FEATS])[:, 1]
    offset = float(sm.GLM(y_val, np.ones((len(y_val), 1)), family=sm.families.Binomial(),
                          offset=logit(pv)).fit().params[0])
    thr = youden_threshold(y_val, pv)
    t0 = time.perf_counter()
    m = make(fam, params).fit(train[FEATS], y_tr)
    fit_s = time.perf_counter() - t0
    p_tr = m.predict_proba(train[FEATS])[:, 1]
    p_te = m.predict_proba(test[FEATS])[:, 1]
    final_models[fam], test_pred[fam], train_pred[fam] = m, p_te, p_tr
    p_te_cal = 1 / (1 + np.exp(-(logit(p_te) + offset)))
    tr_m, te_m = at_threshold(y_tr, p_tr, thr), at_threshold(y_te, p_te, thr)
    row = {"model": fam, "features": f"All four blocks ({len(FEATS)} predictors)",
           "params": selection[fam]["chosen"],
           "train_auc": round(float(roc_auc_score(y_tr, p_tr)), 4),
           "val_auc": selection[fam]["chosen_val_auc"],
           "test_auc": round(float(roc_auc_score(y_te, p_te)), 4),
           "threshold_from_validation": round(thr, 4),
           "train_accuracy": tr_m["accuracy"], "test_accuracy": te_m["accuracy"],
           "train_balanced_accuracy": tr_m["balanced_accuracy"],
           "test_balanced_accuracy": te_m["balanced_accuracy"],
           "test_sensitivity": te_m["sensitivity"], "test_specificity": te_m["specificity"],
           "test_precision": te_m["precision"], "test_f1": te_m["f1"],
           "test_flagged_share": te_m["flagged_share"], "test_confusion": te_m["confusion"],
           "test_brier_raw": round(float(brier_score_loss(y_te, p_te)), 4),
           "calibration_offset_from_validation": round(offset, 4),
           "test_brier_recalibrated": round(float(brier_score_loss(y_te, p_te_cal)), 4),
           "test_mean_predicted_recalibrated": round(float(p_te_cal.mean()), 4),
           "fit_seconds_full_training": round(fit_s, 1)}
    perf.append(row)
    print(f"  {fam:34s} train {row['train_auc']:.4f}  val {row['val_auc']:.4f}  "
          f"test {row['test_auc']:.4f}  bal.acc {row['test_balanced_accuracy']:.4f}  "
          f"Brier(recal) {row['test_brier_recalibrated']:.4f}  {fit_s:.1f}s")

# paired bootstrap on the test set: interval for each AUC, and the gap to the best
rng = np.random.default_rng(SEED)
boots = [rng.integers(0, len(y_te), len(y_te)) for _ in range(1000)]
boot = {f: np.array([roc_auc_score(y_te[b], test_pred[f][b]) for b in boots]) for f in GRIDS}
best_fam = max(GRIDS, key=lambda f: selection[f]["chosen_val_auc"])
for row in perf[1:]:
    b = boot[row["model"]]
    row["test_auc_ci95"] = [round(float(np.percentile(b, 2.5)), 4),
                            round(float(np.percentile(b, 97.5)), 4)]
    if row["model"] != best_fam:
        d = boot[best_fam] - b
        row["gap_to_best"] = {"delta": round(float(d.mean()), 4),
                              "ci95": [round(float(np.percentile(d, 2.5)), 4),
                                       round(float(np.percentile(d, 97.5)), 4)],
                              "p_two_sided": round(float(2 * min((d <= 0).mean(), (d >= 0).mean())), 4)}
out["performance"] = perf
out["best_model"] = {"family": best_fam, "chosen_by": "highest validation AUC (2014-2015)",
                     "params": selection[best_fam]["chosen"]}
print(f"  best by validation AUC: {best_fam}")

print("\n[F4] Patent-block increment with the tuned model")
bp = {k: (tuple(v) if isinstance(v, list) else v) for k, v in selection[best_fam]["chosen"].items()}
inc = {}
for name, fs in [("without_ip", FEATURE_SETS[NO_IP]), ("with_ip", FEATS)]:
    mm = make(best_fam, bp).fit(train[fs], y_tr)
    inc[name] = mm.predict_proba(test[fs])[:, 1]
b_with = np.array([roc_auc_score(y_te[b], inc["with_ip"][b]) for b in boots])
b_wo = np.array([roc_auc_score(y_te[b], inc["without_ip"][b]) for b in boots])
d = b_with - b_wo
out["ip_increment_tuned"] = {
    "auc_without_ip": round(float(roc_auc_score(y_te, inc["without_ip"])), 4),
    "auc_with_ip": round(float(roc_auc_score(y_te, inc["with_ip"])), 4),
    "delta": round(float(d.mean()), 4),
    "ci95": [round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)],
    "p_two_sided": round(float(2 * min((d <= 0).mean(), (d >= 0).mean())), 4),
    "bootstrap_correlation_of_aucs": round(float(np.corrcoef(b_with, b_wo)[0, 1]), 4),
}
print(f"  {out['ip_increment_tuned']}")

print("\n[F5] Best model: calibration, threshold, risk concentration")
bm = final_models[best_fam]
p_best = test_pred[best_fam]
brow = next(r for r in perf if r["model"] == best_fam)
off = brow["calibration_offset_from_validation"]
p_cal = 1 / (1 + np.exp(-(logit(p_best) + off)))
fit_raw = sm.Logit(y_te, sm.add_constant(logit(p_best))).fit(disp=0)
fit_cal = sm.Logit(y_te, sm.add_constant(logit(p_cal))).fit(disp=0)
thr_cal = 1 / (1 + np.exp(-(logit(np.array([brow["threshold_from_validation"]]))[0] + off)))
out["best_calibration"] = {
    "offset_from_validation": off,
    "raw": {"slope": round(float(fit_raw.params[1]), 4), "intercept": round(float(fit_raw.params[0]), 4),
            "mean_predicted": round(float(p_best.mean()), 4),
            "brier": round(float(brier_score_loss(y_te, p_best)), 4)},
    "recalibrated": {"slope": round(float(fit_cal.params[1]), 4),
                     "intercept": round(float(fit_cal.params[0]), 4),
                     "mean_predicted": round(float(p_cal.mean()), 4),
                     "brier": round(float(brier_score_loss(y_te, p_cal)), 4)},
    "observed_rate": round(float(y_te.mean()), 4),
    "no_information_brier": round(float(brier_score_loss(y_te, np.full(len(y_te), y_tr.mean()))), 4),
    "threshold_raw_scale": brow["threshold_from_validation"],
    "threshold_recalibrated_scale": round(float(thr_cal), 4),
}
dec = pd.DataFrame({"p": p_cal, "y": y_te})
dec["decile"] = pd.qcut(dec.p.rank(method="first"), 10, labels=False) + 1
dtab = dec.groupby("decile").agg(n=("y", "size"), terminated=("y", "sum"),
                                 observed=("y", "mean"), predicted=("p", "mean"))
dtab = dtab.sort_index(ascending=False)
dtab["cum_capture"] = dtab.terminated.cumsum() / dtab.terminated.sum()
base = float(y_te.mean())
out["risk_deciles"] = [
    {"decile": int(i), "n": int(r.n), "terminated": int(r.terminated),
     "observed": round(float(r.observed), 4), "predicted": round(float(r.predicted), 4),
     "lift": round(float(r.observed / base), 3), "cumulative_capture": round(float(r.cum_capture), 4)}
    for i, r in dtab.iterrows()]
top10, top20 = dtab.iloc[:1], dtab.iloc[:2]
out["risk_concentration"] = {
    "test_base_rate": round(base, 4),
    "top_decile_rate": round(float(top10.terminated.sum() / top10.n.sum()), 4),
    "top_decile_lift": round(float(top10.terminated.sum() / top10.n.sum() / base), 3),
    "top_quintile_rate": round(float(top20.terminated.sum() / top20.n.sum()), 4),
    "top_quintile_capture": round(float(top20.terminated.sum() / dtab.terminated.sum()), 4),
    "bottom_decile_rate": round(float(dtab.iloc[-1].observed), 4),
}
print(f"  {out['risk_concentration']}")

print("\n[F6] SHAP attributions")
import shap  # noqa: E402

explainer = shap.TreeExplainer(bm) if best_fam == "Gradient-boosted trees" else None
sv = explainer.shap_values(test[FEATS]) if explainer is not None else None
if isinstance(sv, list):
    sv = sv[1]
blocks = {**{c: "Design" for c in ns["DESIGN"]}, **{c: "Sponsor" for c in ns["SPONSOR"]},
          **{c: "Regulatory" for c in ns["REGULATORY"]},
          **{c: "Patent (drug)" for c in ns["IP_DRUG"]},
          **{c: "Patent (sponsor)" for c in ns["IP_SPONSOR"]},
          **{c: "Biosimilar" for c in ns["BIOSIMILAR"]}}
if sv is not None:
    mabs = np.abs(sv).mean(axis=0)
    shap_tab = (pd.DataFrame({"feature": FEATS, "mean_abs_shap": mabs})
                .assign(block=lambda d: d.feature.map(blocks))
                .sort_values("mean_abs_shap", ascending=False))
    by_block = shap_tab.groupby("block").mean_abs_shap.sum()
    out["shap"] = {
        "explainer": "TreeExplainer on the tuned gradient-boosted model, held-out 2016-2019 trials",
        "top": [{"feature": r.feature, "block": r.block, "mean_abs_shap": round(float(r.mean_abs_shap), 4)}
                for r in shap_tab.head(15).itertuples()],
        "share_by_block": {k: round(float(v / by_block.sum()), 4) for k, v in by_block.items()},
        "rank": {r.feature: i for i, r in enumerate(shap_tab.itertuples(), start=1)},
    }
    print(f"  share by block: {out['shap']['share_by_block']}")

print("\n[F7] Worked example")
# Not hand-picked: the test trial whose recalibrated risk sits at the 95th
# percentile, i.e. a trial a committee would see near the top of a review list.
order = np.argsort(p_cal)
ix = int(order[int(0.95 * (len(order) - 1))])
row = test.iloc[ix]
ex = {"nct_id": row.nct_id, "start_year": int(row.start_year),
      "phases": str(row.phases), "lead_sponsor_class": str(row.lead_sponsor_class),
      "therapeutic_area": str(row.therapeutic_area),
      "n_locations": float(row.n_locations), "n_countries": float(row.n_countries),
      "elig_criteria_lines": float(row.elig_criteria_lines),
      "sponsor_prior_trials": float(row.sponsor_prior_trials),
      "sponsor_prior_completion_rate": (None if pd.isna(row.sponsor_prior_completion_rate)
                                        else round(float(row.sponsor_prior_completion_rate), 3)),
      "risk_recalibrated": round(float(p_cal[ix]), 4),
      "risk_percentile": 95,
      "decile": int(dec.decile.iloc[ix]),
      "actual_status": str(row.overall_status),
      "why_stopped": (None if pd.isna(row.why_stopped) else str(row.why_stopped))}
if sv is not None:
    contrib = pd.Series(sv[ix], index=FEATS).sort_values(key=np.abs, ascending=False)
    ex["top_drivers"] = [{"feature": f, "value": (None if pd.isna(test.iloc[ix][f]) else
                                                  round(float(test.iloc[ix][f]), 3)),
                          "shap": round(float(v), 4)} for f, v in contrib.head(5).items()]
out["example"] = ex
print(f"  {json.dumps(ex)[:400]}")

print("\n[F8] Figures")
# Figure 10 - inclusion and exclusion flow
F, L = R["frame"], R["linkage"]
P = out["partitions"]
fig, ax = plt.subplots(figsize=(7.2, 6.6))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x, y, w, h, text, fc="#eef4fc", ec=BLUE, fs=7.6, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                fc=fc, ec=ec, lw=1.1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", linespacing=1.35)


def arrow(x1, y1, x2, y2):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9,
                                 color=INK_SOFT, lw=1.0))


EXC = dict(fc="#fdf0ea", ec=ORANGE)
box(18, 89, 44, 9, f"Phase II/III interventional drug trials\nretrieved from ClinicalTrials.gov API v2\nN = {F['retrieved']:,}", bold=True)
box(68, 89, 31, 9, f"Excluded: start date outside\n2008-2019\nn = {F['retrieved'] - F['in_window_2008_2019']:,}", **EXC)
arrow(62, 93.5, 68, 93.5)
arrow(40, 89, 40, 82)
box(18, 72.5, 44, 9, f"Trials starting 2008-2019\nn = {F['in_window_2008_2019']:,}")
box(68, 70.5, 31, 13, f"Excluded: outcome unresolved\n(recruiting, active, not yet\nrecruiting, by invitation, unknown)\nn = {F['unresolved_dropped']:,}", **EXC)
arrow(62, 77, 68, 77)
arrow(40, 72.5, 40, 66)
box(14, 54.5, 52, 11, f"ANALYTIC FRAME: resolved outcome\nN = {F['analytic_n']:,}  |  terminated {F['terminated']:,} ({F['p_terminated']:.1%})\ncompleted {F['completed']:,}", fc="#e6f6ef", ec=AQUA, bold=True)
# branches
arrow(25, 54.5, 17, 45)
arrow(40, 54.5, 50, 45)
arrow(58, 54.5, 82, 45)
box(1, 26, 31, 18.5, f"RQ2 prediction\n(all {F['analytic_n']:,} trials)\n\nTraining 2008-2015: {P['training']['n']:,}\n  development 2008-2013: {P['development']['n']:,}\n  validation 2014-2015: {P['validation']['n']:,}\nTest 2016-2019: {P['test']['n']:,}", fs=7.2)
box(35, 30, 30, 14.5, f"RQ1 and RQ4\nsponsor patent measure\navailable\nn = {R['rq1']['n_computable']:,}\n({R['rq1_clustered']['n_clusters']} sponsor groups)", fs=7.2)
box(68, 30, 31, 14.5, f"RQ3 time to completion\npositive duration and\nsponsor measure\nn = {R['rq3']['cox_completion']['n']:,}", fs=7.2)
box(35, 7, 30, 17, f"Not measurable on patents\n(kept in RQ2, out of RQ1/3/4)\nn = {R['rq1']['n_not_computable']:,}\nnon-industry sponsor {L['no_sponsor_ip_nonindustry']:,}\nindustry, unmatched {L['no_sponsor_ip_industry']:,}", fs=7.0, **EXC)
arrow(50, 30, 50, 24)
box(68, 7, 31, 17, f"Excluded from RQ3 only:\nmissing or non-positive\nduration, frame-wide\nn = {R['rq3_exclusions']['dropped_no_duration'] + R['rq3_exclusions']['dropped_nonpositive_duration']:,}", fs=7.0, **EXC)
arrow(83, 30, 83, 24)
ax.legend(handles=[Patch(fc="#eef4fc", ec=BLUE, label="Retained records"),
                   Patch(fc="#fdf0ea", ec=ORANGE, label="Excluded records"),
                   Patch(fc="#e6f6ef", ec=AQUA, label="Analytic frame")],
          loc="lower left", fontsize=7, bbox_to_anchor=(0.0, -0.04), ncol=3)
save(fig, "fig10_flow_diagram.png")

# Figure 11 - architecture: the required stages, with a legend
fig, ax = plt.subplots(figsize=(7.4, 5.2))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")
C_DATA, C_PROC, C_MODEL, C_DEP = "#eef4fc", "#fff4e0", "#e6f6ef", "#f1ecfb"
E_DATA, E_PROC, E_MODEL, E_DEP = BLUE, "#c98a1b", AQUA, "#7a5cc4"
stages = [
    (2, 72, "1. DATA\n8 public sources:\nClinicalTrials.gov, Orange Book,\nDrugs@FDA, Purple Book,\nGoogle Patents (BigQuery),\nOpen Targets, AACT, FAERS", C_DATA, E_DATA),
    (35, 72, "2. PREPROCESSING\nREST API and bulk ingestion;\nentity resolution (precision 0.98);\nleakage audit; missing values\nby mechanism; outlier audit", C_PROC, E_PROC),
    (68, 72, "3. ANALYTICAL STORE\n14 Parquet tables keyed on\nnct_id, appl_no, ingredient,\ncorporate group; versioned\nin the GitHub repository", C_DATA, E_DATA),
    (68, 40, "4. EDA\nright-censoring, enrolment\nleakage, missingness pattern,\nskew and outliers, termination\nby therapeutic area", C_PROC, E_PROC),
    (35, 40, "5. FEATURE ENGINEERING\n46 predictors in 6 blocks,\nall dated at or before trial\nstart; sponsor history as-of;\ncomposite patent index (RQ1)", C_PROC, E_PROC),
    (2, 40, "6. MODEL\nRQ1/RQ4 clustered logistic;\nRQ3 cause-specific Cox and\nFine-Gray; RQ2 logistic, random\nforest, boosting, neural network", C_MODEL, E_MODEL),
    (2, 6, "7. EVALUATION\ntemporal train / validation /\ntest; bootstrap AUC intervals;\ncalibration; SHAP attribution", C_MODEL, E_MODEL),
    (35, 6, "8. DEPLOYMENT\nsaved model + batch scoring\nscript: calibrated risk, decile\nband, review flag and top\nthree drivers per trial (CSV)", C_DEP, E_DEP),
    (68, 6, "9. AGENTIC LAYER (future)\nLLM assistant drafts review\nmemos from scores and SHAP\ndrivers, human sign-off\nbefore any decision", "#ffffff", E_DEP),
]
for x, y, t, fc, ec in stages:
    ls = "--" if t.startswith("9.") else "-"
    ax.add_patch(FancyBboxPatch((x, y), 30, 24, boxstyle="round,pad=0.4,rounding_size=1.5",
                                fc=fc, ec=ec, lw=1.2, ls=ls))
    head, body = t.split("\n", 1)
    ax.text(x + 15, y + 20.3, head, ha="center", va="center", fontsize=7.6, fontweight="bold", color=INK)
    ax.text(x + 15, y + 9.6, body, ha="center", va="center", fontsize=6.6, color=INK, linespacing=1.3)
for (x1, y1), (x2, y2) in [((32.4, 84), (34.6, 84)), ((65.4, 84), (67.6, 84)),
                           ((83, 71.6), (83, 64.4)), ((67.6, 52), (65.4, 52)),
                           ((34.6, 52), (32.4, 52)), ((17, 39.6), (17, 30.4)),
                           ((32.4, 18), (34.6, 18))]:
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=10, color=INK_SOFT, lw=1.2))
ax.add_patch(FancyArrowPatch((65.4, 18), (67.6, 18), arrowstyle="-|>", mutation_scale=10,
                             color=INK_SOFT, lw=1.2, ls="--"))
ax.legend(handles=[Patch(fc=C_DATA, ec=E_DATA, label="Data and storage"),
                   Patch(fc=C_PROC, ec=E_PROC, label="Processing and analysis"),
                   Patch(fc=C_MODEL, ec=E_MODEL, label="Modelling and evaluation"),
                   Patch(fc=C_DEP, ec=E_DEP, label="Deployment"),
                   Patch(fc="#ffffff", ec=E_DEP, ls="--", label="Planned, not built")],
          loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=5, fontsize=6.6,
          handlelength=1.4, columnspacing=1.0)
save(fig, "fig11_architecture.png")

# Figure 12 - ROC on the test period for the four tuned families
fig, ax = plt.subplots(figsize=(4.6, 4.3))
cols = {"Gradient-boosted trees": BLUE, "Random forest": AQUA,
        "L1-penalised logistic regression": ORANGE, "Neural network (MLP)": "#7a5cc4"}
for fam in GRIDS:
    fpr, tpr, _ = roc_curve(y_te, test_pred[fam])
    r_ = next(r for r in perf if r["model"] == fam)
    ax.plot(fpr, tpr, color=cols[fam], lw=1.8 if fam == best_fam else 1.3,
            label=f"{fam} (test AUC {r_['test_auc']:.3f})")
fpr, tpr, _ = roc_curve(y_tr, train_pred[best_fam])
ax.plot(fpr, tpr, color=BLUE, lw=1.0, ls=":", label=f"{best_fam}, training data (AUC {brow['train_auc']:.3f})")
ax.plot([0, 1], [0, 1], color=INK_SOFT, lw=1, ls="--", label="Chance (AUC 0.500)")
ax.set_xlabel("False positive rate (1 - specificity)")
ax.set_ylabel("True positive rate (sensitivity)")
ax.set_title("ROC curves, held-out 2016-2019 trials")
ax.legend(fontsize=6.6, loc="upper center", bbox_to_anchor=(0.5, -0.17))
ax.set_aspect("equal")
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig12_roc_final.png")

# Figure 13 - confusion matrix at the validation-fixed threshold
cm = brow["test_confusion"]
mat = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
fig, ax = plt.subplots(figsize=(4.2, 3.6))
ax.imshow(mat, cmap="Blues", vmin=0, vmax=mat.max() * 1.15)
labels = [["True negative", "False positive"], ["False negative", "True positive"]]
for i in range(2):
    for j in range(2):
        ax.text(j, i, f"{labels[i][j]}\n{mat[i, j]:,}\n({mat[i, j] / mat[i].sum():.1%} of row)",
                ha="center", va="center", fontsize=8,
                color="white" if mat[i, j] > mat.max() * 0.6 else INK)
ax.set_xticks([0, 1], ["Predicted completed", "Predicted terminated"])
ax.set_yticks([0, 1], ["Actually completed", "Actually terminated"])
ax.grid(False)
ax.set_title(f"Confusion matrix, test 2016-2019\n{best_fam}, threshold fixed on validation")
save(fig, "fig13_confusion_matrix.png")

# Figure 14 - calibration before and after the validation-fitted offset
fig, ax = plt.subplots(figsize=(4.4, 4.0))
for probs, lab, col, mk in [(p_best, "Before recalibration", ORANGE, "s"),
                            (p_cal, "After recalibration", BLUE, "o")]:
    dd = pd.DataFrame({"p": probs, "y": y_te})
    dd["b"] = pd.qcut(dd.p.rank(method="first"), 10, labels=False)
    g = dd.groupby("b").agg(pred=("p", "mean"), obs=("y", "mean"))
    ax.plot(g.pred, g.obs, color=col, lw=1.8, marker=mk, ms=4, label=lab)
ax.plot([0, 0.8], [0, 0.8], color=INK_SOFT, lw=1, ls="--", label="Perfect calibration")
ax.set_xlabel("Mean predicted probability (decile)")
ax.set_ylabel("Observed termination rate")
ax.set_title("Calibration by risk decile, test 2016-2019")
ax.legend(fontsize=7.5, loc="upper left")
tidy(ax, hide_x_grid=False)
save(ax.figure, "fig14_calibration_final.png")

# Figure 15 - SHAP global importance, coloured by block
if sv is not None:
    top = shap_tab.head(15).iloc[::-1]
    bcol = {"Design": BLUE, "Sponsor": "#7a5cc4", "Regulatory": ORANGE,
            "Patent (drug)": AQUA, "Patent (sponsor)": AQUA, "Biosimilar": AQUA}
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.barh(np.arange(len(top)), top.mean_abs_shap, color=[bcol[b] for b in top.block], height=0.66)
    for yv, v in enumerate(top.mean_abs_shap):
        ax.text(v + top.mean_abs_shap.max() * 0.015, yv, f"{v:.3f}", va="center", fontsize=7.5, color=INK)
    ax.set_yticks(np.arange(len(top)), top.feature)
    ax.set_xlim(0, top.mean_abs_shap.max() * 1.15)
    ax.set_xlabel("Mean absolute SHAP value (log-odds), held-out trials")
    ax.set_title("Which predictors drive the tuned model's risk scores")
    ax.legend(handles=[Patch(color=BLUE, label="Trial design"), Patch(color="#7a5cc4", label="Sponsor"),
                       Patch(color=ORANGE, label="Regulatory"), Patch(color=AQUA, label="Patent and biosimilar")],
              fontsize=7.5, loc="lower right")
    ax.yaxis.grid(False)
    tidy(ax, hide_x_grid=False)
    save(ax.figure, "fig15_shap_importance.png")

# Figure 16 - risk concentration: observed rate by decile and cumulative capture
dt = pd.DataFrame(out["risk_deciles"]).sort_values("decile")
fig, ax = plt.subplots(figsize=(6.4, 3.3))
ax.bar(dt.decile, dt.observed, color=BLUE, width=0.66, label="Observed termination rate")
ax.plot(dt.decile, dt.predicted, color=ORANGE, marker="o", ms=4, lw=1.6, label="Mean predicted (recalibrated)")
ax.axhline(base, color=INK_SOFT, ls="--", lw=1)
ax.text(1.0, base + 0.012, f"test base rate {base:.1%}", fontsize=7.5, color=INK_SOFT)
ax.set_xticks(dt.decile)
ax.set_xlabel("Decile of predicted risk (1 = lowest, 10 = highest)")
ax.set_ylabel("Termination rate")
ax.set_title("Risk concentration on held-out 2016-2019 trials")
ax.legend(fontsize=7.5, loc="upper left")
save(tidy(ax).figure, "fig16_risk_deciles.png")

print("\n[F9] Analytical store inventory and runtime")
inv = []
for pq in sorted((ROOT / "data" / "analysis_ready").glob("*.parquet")):
    t = pd.read_parquet(pq)
    inv.append({"table": pq.name, "rows": int(len(t)), "columns": int(t.shape[1]),
                "mb": round(pq.stat().st_size / 1e6, 2),
                "keys": [k for k in ("nct_id", "appl_no", "ingredient", "corporate_group",
                                     "lead_sponsor", "sponsor") if k in t.columns]})
out["store_inventory"] = inv
out["environment"] = {"python": platform.python_version(), "platform": platform.platform(),
                      "processor": "Intel Core i5-4278U, 2.6 GHz, 2 cores / 4 threads",
                      "memory_gb": 8, "gpu": "none (all training on CPU)",
                      "cpu_count": os.cpu_count()}
print(f"  {len(inv)} tables")

print("\n[F10] Saving the scoring artefact")
MODELS = ROOT / "models"
MODELS.mkdir(exist_ok=True)
edges = np.quantile(p_cal, np.linspace(0, 1, 11)).tolist()
joblib.dump({"model": bm, "features": FEATS, "family": best_fam,
             "params": selection[best_fam]["chosen"],
             "calibration_offset": off,
             "threshold_recalibrated": out["best_calibration"]["threshold_recalibrated_scale"],
             "reference_decile_edges": edges,
             "trained_on": "trials starting 2008-2015",
             "blocks": blocks}, MODELS / "termination_model.joblib", compress=3)
out["artefact"] = {"path": "models/termination_model.joblib",
                   "mb": round((MODELS / "termination_model.joblib").stat().st_size / 1e6, 2)}

OUTF = ROOT / "docs" / "final_results.json"
OUTF.write_text(json.dumps(out, indent=2, default=str))
print(f"\nwrote {OUTF.relative_to(ROOT)}")
