# Precision adjudication — 200-link sample

## What you are judging

Each row is one **link**: a ClinicalTrials.gov trial's intervention text mapped to an
FDA ingredient (and, where available, an FDA application number). You are judging
whether that link is **correct**, not whether the resolver found *every* drug.

That is the precision/recall split: recall (83.7%) is already measured automatically;
precision needs a human because no verified crosswalk exists to check against.

## The three verdicts

Put exactly one of these in the `verdict` column:

| Verdict | Use when | Example |
|---|---|---|
| `CORRECT` | The ingredient is the trial's actual investigational agent | `PEMBROLIZUMAB` → PEMBROLIZUMAB |
| `PARTIAL` | Right active ingredient, but incomplete | `FOLFIRINOX` → LEUCOVORIN (one of four components) |
| `WRONG` | Different molecule, or a class/procedure mapped to a specific product | `STATIN` → STATINE; `INSULIN` → INSULIN DEGLUDEC |

Leave `verdict` blank to skip a row; blanks are excluded, not counted as wrong.

## Rules that decide the hard cases

1. **Salt and ester forms are CORRECT.** `ZOLEDRONATE` → ZOLEDRONATE DISODIUM is the
   same active moiety. But a *different* chemical entity is WRONG:
   `N-ACETYLCYSTEINE` → N-ACETYLCYSTEINE ETHYL ESTER is a distinct compound.
2. **Formulation prefixes are CORRECT.** `NANOPARTICLE ALBUMIN-BOUND PACLITAXEL` →
   PACLITAXEL is right; the active agent is paclitaxel.
3. **Combination regimens are PARTIAL**, not WRONG, when the resolved ingredient is
   genuinely one of the components. Check `is_combination`.
4. **A general term mapped to a specific branded product is WRONG.** `INSULIN` is not
   INSULIN DEGLUDEC. This was the failure mode that caused the `head` method to be
   removed entirely.
5. **Development codes are CORRECT if the mapping is real.** `TAK-438` → VONOPRAZAN
   is right. Verify unfamiliar codes — a quick search of the code plus "INN" usually
   settles it. Watch for substring errors: `APATINIB` is *not* LAPATINIB.
6. **Comparator/background therapy is WRONG** if the trial's actual investigational
   agent is something else and the resolver latched onto the comparator.

Use `notes` for anything ambiguous; those rows are worth discussing with your mentor.

## Scoring

Adjudicate with the helper, which shows one link at a time, groups the easy
strata first, and saves after every keystroke so you can stop and resume:

```bash
~/dba_venv/bin/python scripts/analysis/adjudicate.py
```

Then score:

```bash
~/dba_venv/bin/python scripts/analysis/score_precision.py data/validation
```

The sample deliberately **over-samples risky methods** — all 31 fuzzy and 19 desalt
links are included, though they are under 0.4% of the population. A raw average of
verdicts would therefore understate true precision. The scorer weights each method's
observed precision by that method's share of the resolved population and reports a
stratified 95% confidence interval.

At an expected precision of 0.90, n = 200 gives roughly **±4 percentage points**.

## What to do with the result

The target is a lower confidence bound at or above 0.90. If a method scores below
0.85, fix the *rule* rather than the individual rows — that is how `head` was dropped
and how `fuzzy` gained its length guard. Then re-run the resolver and draw a fresh
sample; re-scoring the same sample after changing the rules would be circular.
