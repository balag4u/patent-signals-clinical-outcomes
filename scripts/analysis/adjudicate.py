#!/usr/bin/env python3
"""Adjudicate the 200-link precision sample one row at a time.

The verdicts are the audit, so this script does not supply any of them. What it
does is remove the friction: it shows one link per screen with the rule that
decides it, groups the mechanical strata first so momentum builds, and writes
the CSV after every keystroke, so the pass can be stopped and resumed.

    python scripts/analysis/adjudicate.py                 # judge the unjudged
    python scripts/analysis/adjudicate.py --review token  # revisit one stratum
    python scripts/analysis/adjudicate.py --all           # include judged rows

The rules are in data/validation/HOW_TO_ADJUDICATE.md; the hints below are a
reminder of them, not a substitute for reading it once before starting.
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CSV = os.path.join(REPO, "data", "validation", "precision_sample_200.csv")

VERDICTS = {"c": "CORRECT", "p": "PARTIAL", "w": "WRONG"}

# Easiest strata first: identity matches, then salt forms, then typo repairs,
# then development codes, and the token splitter last because it is the one
# that actually requires thought.
ORDER = ["exact", "desalt", "fuzzy", "synonym", "token"]

HINT = {
    "exact": "Identity match. CORRECT unless the string itself is a class or a "
             "procedure rather than an agent.",
    "desalt": "Salt/ester stripped. Rule 1: same active moiety is CORRECT; a "
              "genuinely different chemical entity is WRONG.",
    "fuzzy":  "Edit-distance repair. CORRECT for a typo or punctuation fix. "
              "WRONG if the edit changed the molecule (watch short strings).",
    "synonym": "Development code or brand mapped to an ingredient. Rule 5: "
               "CORRECT if the mapping is real, but verify unfamiliar codes. "
               "Rule 4: a general term mapped to a specific product is WRONG.",
    "token":  "One token picked from a longer string. Rule 3: PARTIAL if the "
              "ingredient is genuinely one component of a regimen. Rule 6: "
              "WRONG if the resolver took the comparator or background therapy "
              "and missed the investigational agent.",
}

BANNER = """\
  c = CORRECT     p = PARTIAL     w = WRONG     s = skip (stays unjudged)
  n = add a note  b = back one    q = save and quit
"""


def fmt(row, i, total):
    combo = "  *** COMBINATION, see Rule 3 ***" if int(row.is_combination) else ""
    appl = str(row.appl_no).split(".")[0] if pd.notna(row.appl_no) else "(none)"
    note = f"\n  note       : {row.notes}" if pd.notna(row.notes) and str(row.notes).strip() else ""
    cur = f"\n  current    : {row.verdict}" if pd.notna(row.verdict) and str(row.verdict).strip() else ""
    return f"""
{'=' * 78}
  {i}/{total}   review_id {row.review_id}   method {row.method} (score {row.score}){combo}
{'-' * 78}
  trial      : {row.nct_id}   [{row.modality}]  {row.primary_condition}
  raw text   : {row.raw}
  normalised : {row.norm}
  resolved to: {row.ingredient}        FDA application: {appl}{cur}{note}
{'-' * 78}
  {HINT.get(row.method, '')}
{'=' * 78}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--review", help="only this method")
    ap.add_argument("--all", action="store_true",
                    help="include rows that already carry a verdict")
    args = ap.parse_args()

    # verdict/notes read back as all-NaN float64 on a fresh sample, which makes
    # assigning a string raise a dtype warning; object is what they actually hold.
    d = pd.read_csv(args.csv, dtype={"appl_no": "string"})
    for col in ("verdict", "notes"):
        if col not in d.columns:
            d[col] = pd.NA
        d[col] = d[col].astype("object")

    judged = d.verdict.notna() & d.verdict.astype(str).str.strip().ne("")
    pool = d if args.all else d[~judged]
    if args.review:
        pool = pool[pool.method == args.review]
    if not len(pool):
        print(f"Nothing to judge. {int(judged.sum())}/{len(d)} rows already carry a "
              f"verdict.\nScore with: python scripts/analysis/score_precision.py "
              f"data/validation")
        return

    order = {m: i for i, m in enumerate(ORDER)}
    idx = sorted(pool.index, key=lambda i: (order.get(d.at[i, "method"], 99), i))

    print(f"\n{len(idx)} links to judge   ({int(judged.sum())}/{len(d)} already done)")
    print("Rules: data/validation/HOW_TO_ADJUDICATE.md")
    print(BANNER)

    pos = 0
    while pos < len(idx):
        i = idx[pos]
        print(fmt(d.loc[i], pos + 1, len(idx)))
        try:
            key = input("  verdict > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  interrupted; progress is already saved")
            break

        if key == "q":
            break
        if key == "b":
            pos = max(0, pos - 1)
            continue
        if key == "s":
            pos += 1
            continue
        if key == "n":
            d.at[i, "notes"] = input("  note > ").strip()
            d.to_csv(args.csv, index=False)
            continue
        if key in VERDICTS:
            d.at[i, "verdict"] = VERDICTS[key]
            d.to_csv(args.csv, index=False)
            pos += 1
            continue
        print("  ? use c / p / w / s / n / b / q")

    d.to_csv(args.csv, index=False)
    done = int((d.verdict.notna() & d.verdict.astype(str).str.strip().ne("")).sum())
    print(f"\nsaved {args.csv}")
    print(f"{done}/{len(d)} adjudicated")
    if done == len(d):
        print("\nComplete. Score it:\n  python scripts/analysis/score_precision.py "
              "data/validation")
    else:
        print("\nResume any time with the same command.")


if __name__ == "__main__":
    sys.exit(main())
