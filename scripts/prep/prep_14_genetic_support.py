#!/usr/bin/env python3
"""Does the drug being tested act on a gene with human genetic evidence?

WHY THIS VARIABLE EXISTS
Nelson et al. (2015) and Minikel et al. (2024) found that drugs aimed at a gene
with human genetic evidence linking it to disease succeed roughly twice as
often as drugs without it. That is a larger published effect than anything the
patent measures in this project show, and it comes from data that is free.

It enters this study as a control. Without it, any association between patents
and trial outcome could really be an association between well-resourced
companies and better-validated targets. With it, the patent measures have to
earn their contribution over and above the biology.

HOW A TRIAL IS CONNECTED TO A GENE
Four steps, and the chain is only as strong as its weakest link:

    trial  ->  FDA ingredient       prep_08_entity_resolution.py, 83.7% of trials
           ->  ChEMBL drug          matched on name, synonym or trade name
           ->  gene target          Open Targets mechanism of action
           ->  genetic evidence     Open Targets association scores

WHAT COUNTS AS GENETIC EVIDENCE
Open Targets scores each target-disease pair separately for each kind of
evidence. Only the human genetic sources are used here:

    gwas_credible_sets   genome-wide association studies
    eva                  ClinVar clinical variant submissions
    gene_burden          rare variant burden testing
    genomics_england     PanelApp expert-curated gene panels
    gene2phenotype       curated developmental disorder genes
    clingen              expert-curated gene-disease validity
    orphanet             rare disease gene curation
    uniprot_literature   curated literature variants
    uniprot_variants     curated sequence variants

Three sources are deliberately excluded:

    clinical_precedence  this is derived from drugs already in clinical trials.
                         Using it to predict trial outcomes would be circular:
                         the variable would already contain the answer.
    europepmc            text mined from papers, which reflects how much has
                         been written about a target, not genetic evidence.
    impc                 mouse knockouts, not human genetics.

A KNOWN LIMITATION, STATED PLAINLY
Nelson and Minikel match a target to the specific disease being treated. This
script does not, because mapping free-text trial conditions to the disease
ontology is a separate matching problem of the same size as the drug matching
already done. What is measured here is whether the drug's target has genetic
evidence for ANY disease, which is a weaker claim. A target with strong
evidence in an unrelated condition will score as supported.

That makes this a conservative test. If a weaker measure shows signal, a
sharper one would show at least as much.

Usage:
    python scripts/prep/prep_14_genetic_support.py [open_targets_dir]

Writes:
    data/analysis_ready/genetic_support.parquet
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "analysis_ready")

GENETIC_SOURCES = {
    "gwas_credible_sets", "eva", "gene_burden", "genomics_england",
    "gene2phenotype", "clingen", "orphanet", "uniprot_literature",
    "uniprot_variants",
}


def find_open_targets(explicit=None):
    if explicit:
        return explicit
    hits = sorted(glob.glob(os.path.join(ROOT, "data", "06_target*genetics",
                                         "opentargets_*")))
    return hits[0] if hits else None


def label_of(v):
    """Open Targets stores synonyms either as plain text or as {'label': ...}."""
    if isinstance(v, dict):
        return v.get("label") or v.get("name")
    return v


def drug_name_map(base):
    """Every name a drug is known by, pointing at its ChEMBL identifier."""
    f = glob.glob(os.path.join(base, "drug_molecule", "*.parquet"))
    mol = pd.read_parquet(f[0], columns=["id", "name", "synonyms", "tradeNames"])
    out = {}
    for cid, name, syn, trade in zip(mol.id, mol.name, mol.synonyms, mol.tradeNames):
        names = [name]
        for block in (syn, trade):
            if block is None:
                continue
            if isinstance(block, (list, np.ndarray)):
                names.extend(label_of(x) for x in block)
        for nm in names:
            if isinstance(nm, str) and len(nm) > 2:
                out.setdefault(nm.upper().strip(), cid)
    return out


def drug_to_targets(base):
    """One row per drug and gene it acts on."""
    f = glob.glob(os.path.join(base, "drug_mechanism_of_action", "*.parquet"))
    moa = pd.read_parquet(f[0], columns=["chemblIds", "targets"])
    rows = []
    for ids, tgts in zip(moa.chemblIds, moa.targets):
        if ids is None or tgts is None:
            continue
        for cid in ids:
            for t in tgts:
                rows.append((cid, t))
    return pd.DataFrame(rows, columns=["chembl_id", "target_id"]).drop_duplicates()


def genetic_score_per_target(base):
    """Strongest and average genetic evidence each gene carries, across diseases."""
    files = sorted(glob.glob(os.path.join(base, "association_by_datasource_direct",
                                          "*.parquet")))
    keep = []
    for f in files:
        part = pd.read_parquet(
            f, columns=["targetId", "diseaseId", "aggregationValue",
                        "associationScore", "evidenceCount"])
        keep.append(part[part.aggregationValue.isin(GENETIC_SOURCES)])
    assoc = pd.concat(keep, ignore_index=True)
    return assoc.groupby("targetId", as_index=False).agg(
        genetic_score_max=("associationScore", "max"),
        genetic_score_mean=("associationScore", "mean"),
        genetic_n_diseases=("diseaseId", "nunique"),
        genetic_evidence_count=("evidenceCount", "sum"),
    ), len(assoc)


def main():
    base = find_open_targets(sys.argv[1] if len(sys.argv) > 1 else None)
    if not base or not os.path.isdir(base):
        sys.exit("Open Targets folder not found. Pass it as an argument.")
    print("reading Open Targets from %s" % base)

    names = drug_name_map(base)
    print("  drug names and synonyms: %s" % format(len(names), ","))

    moa = drug_to_targets(base)
    print("  drug to gene links:      %s" % format(len(moa), ","))

    per_target, n_assoc = genetic_score_per_target(base)
    print("  genetic evidence rows:   %s across %s genes"
          % (format(n_assoc, ","), format(len(per_target), ",")))

    res = pd.read_parquet(os.path.join(OUT, "trial_drug_resolution.parquet"),
                          columns=["nct_id", "ingredient"])
    res = res[res.ingredient.notna() & (res.ingredient.astype(str).str.len() > 2)].copy()
    res["chembl_id"] = res.ingredient.astype(str).str.upper().str.strip().map(names)
    matched = res.chembl_id.notna()
    print("  trials whose drug matched a ChEMBL record: %s of %s (%.1f%%)"
          % (format(int(matched.sum()), ","), format(len(res), ","),
             100 * matched.mean()))

    linked = (res[matched]
              .merge(moa, on="chembl_id", how="inner")
              .merge(per_target, left_on="target_id", right_on="targetId", how="left"))

    feat = linked.groupby("nct_id", as_index=False).agg(
        genetic_score_max=("genetic_score_max", "max"),
        genetic_score_mean=("genetic_score_mean", "mean"),
        genetic_n_diseases=("genetic_n_diseases", "max"),
        genetic_n_targets=("target_id", "nunique"),
    )
    # A drug whose target carries no genetic evidence at all is a measured zero,
    # not a missing value: the target is known and the evidence is absent.
    for c in ["genetic_score_max", "genetic_score_mean", "genetic_n_diseases"]:
        feat[c] = feat[c].fillna(0.0)
    feat["has_genetic_support"] = (feat.genetic_score_max > 0).astype(int)

    path = os.path.join(OUT, "genetic_support.parquet")
    feat.to_parquet(path, index=False, compression="zstd")

    trials = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"),
                             columns=["nct_id", "start_year", "is_resolved",
                                      "is_terminated"])
    frame = trials[(trials.start_year.between(2008, 2019)) &
                   (trials.is_resolved == 1)].merge(feat, on="nct_id", how="left")
    have = frame.genetic_score_max.notna()
    print()
    print("coverage on the %s-trial study frame" % format(len(frame), ","))
    print("  drug linked to a gene target : %s (%.1f%%)"
          % (format(int(have.sum()), ","), 100 * have.mean()))
    if have.any():
        sup = frame.has_genetic_support == 1
        print("  of those, target has genetic evidence: %s (%.1f%%)"
              % (format(int(sup.sum()), ","), 100 * sup.sum() / have.sum()))
        print()
        print("  termination rate, as a first look:")
        print("    target has genetic evidence : %.4f  (n = %s)"
              % (frame.loc[sup, "is_terminated"].mean(), format(int(sup.sum()), ",")))
        nos = have & (frame.has_genetic_support == 0)
        print("    target has none             : %.4f  (n = %s)"
              % (frame.loc[nos, "is_terminated"].mean(), format(int(nos.sum()), ",")))
        print("    drug not linked to a gene   : %.4f  (n = %s)"
              % (frame.loc[~have, "is_terminated"].mean(),
                 format(int((~have).sum()), ",")))
    print()
    print("wrote %s (%s rows)" % (path, format(len(feat), ",")))


if __name__ == "__main__":
    main()
