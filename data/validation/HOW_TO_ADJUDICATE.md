# How to check the drug matching by hand

**This has been done.** The 200-link sample was judged and scored: precision is
**0.979**, with a confidence interval of 0.963 to 0.996. These instructions are
kept so the check can be repeated after any change to the matching rules, which
it must be.

## What you are judging

Each row is one **link**: the drug name typed into a trial record, matched to
an official FDA ingredient. You are judging whether that link is **correct**.
You are not judging whether the matcher found every drug.

That distinction has names. **Recall** is how many were found, which software
can count on its own: 83.7%. **Precision** is how many of those are right,
which software cannot check, because there is no answer key to check against.
That is why a person has to read a sample.

## The three verdicts

Put exactly one of these in the `verdict` column:

| Verdict | Use when | Example |
|---|---|---|
| `CORRECT` | The ingredient is the drug the trial was actually testing | `PEMBROLIZUMAB` to PEMBROLIZUMAB |
| `PARTIAL` | Right ingredient, but only part of the picture | `FOLFIRINOX` to LEUCOVORIN, one of four components |
| `WRONG` | A different molecule, or a whole drug class mapped to one specific product | `STATIN` to STATINE |

Leaving `verdict` blank skips the row. Blanks are excluded from the score, not
counted as wrong.

## Rules for the hard cases

1. **Salt and ester forms are CORRECT.** `ZOLEDRONATE` to ZOLEDRONATE DISODIUM
   is the same active substance in a different salt. But a genuinely different
   chemical is WRONG: `N-ACETYLCYSTEINE` to N-ACETYLCYSTEINE ETHYL ESTER is a
   separate compound.
2. **Formulation descriptions are CORRECT.** In
   `NANOPARTICLE ALBUMIN-BOUND PACLITAXEL` the active drug is paclitaxel; the
   rest describes how it is delivered.
3. **Combination treatments are PARTIAL**, not WRONG, when the matched
   ingredient really is one of the components. Check the `is_combination`
   column.
4. **A general term matched to one specific product is WRONG.** `INSULIN` is
   not INSULIN DEGLUDEC. This exact failure is why one matching method was
   removed from the pipeline entirely.
5. **Company code names are CORRECT if the decoding is real.** `TAK-438` to
   VONOPRAZAN is right. Verify unfamiliar codes; searching the code with the
   word "INN" usually settles it. Watch for near-miss names: `APATINIB` is
   **not** LAPATINIB.
6. **A comparator drug is WRONG** if the trial was actually testing something
   else and the matcher latched onto the control arm instead.

Use the `notes` column for anything genuinely ambiguous. Those rows are worth
discussing rather than guessing.

## Doing it

A helper shows one link at a time, puts the easy groups first, and saves after
every keystroke so you can stop and come back:

```bash
python scripts/analysis/adjudicate.py
```

Then score the result:

```bash
python scripts/analysis/score_precision.py data/validation
```

## Why the sample is not a simple random draw

The sample deliberately **over-represents the riskiest matching methods**: all
31 fuzzy matches and all 19 salt-form matches are included, even though
together they are under 0.4% of all links.

The reason is that a plain random sample of 200 would have contained roughly
one fuzzy match, which tells you nothing about whether fuzzy matching works.

Because of that, a simple average of the verdicts would understate the true
accuracy, since the risky methods are deliberately over-represented. The scorer
therefore weights each method's observed accuracy by how common that method
actually is, and reports a confidence interval on that weighted figure.

At around 0.90 accuracy, 200 links gives a margin of roughly 4 percentage
points.

## What to do with the result

The target is a lower confidence bound at or above 0.90, which the current
result of 0.963 clears.

If a method ever scores below 0.85, **fix the rule, not the individual rows**.
That is how the prefix method came to be removed and how fuzzy matching gained
its length guard. Then re-run the matcher and **draw a fresh sample**.
Re-scoring the same sample after changing the rules would be circular: you
would be testing the fix on the examples used to design it.
