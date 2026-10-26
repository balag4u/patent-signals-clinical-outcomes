#!/usr/bin/env python3
"""Join the BigQuery patent extracts onto the trial frame, measured AS OF each
trial's start year.

Inputs come from sql/01, sql/02 and sql/03, exported to data/patents/. The
output is one row per trial, carrying the sponsor-level intellectual property
features that prep_11_ip_index.py expects.

Five things this has to get right:

1. NO LOOK-AHEAD. A portfolio counted at today's size would tell the model
   what the sponsor became, not what it was when the trial opened. Every
   feature here is the cumulative position at or before the trial's start
   year, taken from the per-year cumulative series the SQL produced. This is
   the same error class as the sponsor-history leakage already documented in
   the report, and it is the reason the portfolio was extracted per year
   rather than as a single total.

2. ACQUISITION TIMING. Wyeth's patents became Pfizer's in 2009. An assignee
   with a parent_from_year contributes to its corporate group only from that
   year onward, so a trial starting in 2008 sees Pfizer without Wyeth. Without
   this the parent's portfolio is overstated for exactly the early years.

3. ABSENCE IS NOT ZERO, EXCEPT WHERE IT IS. A sponsor outside the curated
   list has no portfolio measurement, not a portfolio of zero. For a
   university or a government institute a near-zero pharmaceutical portfolio
   is substantively right; for an unlisted mid-size biotech it is wrong.
   The two cases are distinguished by is_industry and reported separately,
   and nothing is coded zero here. prep_11 excludes missing values from the
   RQ1 subsample rather than treating them as weak.

4. PHARMA SHARE IS THE POINT OF THE CPC SPLIT. Bayer holds 25,640 granted US
   patents in this extract but only 3,859 classified A61K or A61P, a 15%
   pharmaceutical share against 59% for Roche and 67% for GSK. Portfolio size
   alone therefore measures firm breadth, not drug-development IP, which is
   why FOCUS exists as a separate dimension and why SCALE is down-weighted.

5. DRUG-LEVEL QUALITY AND BREADTH NEED A LINK THAT IS NOT ON DISK.
   sql/02 returns forward citations and INPADOC family size per Orange Book
   patent, but attaching them to a trial needs the Orange Book patent-to-
   application mapping, and prep_02_orangebook.py aggregates to appl_no
   without persisting the pairs. Those two dimensions are therefore computed
   only if data/analysis_ready/orangebook_patent_appl_map.parquet exists, and
   their absence is reported rather than passed over. See the note printed at
   the end for how to produce it.

Usage:
    python scripts/prep/prep_13_patents.py [data/analysis_ready]

Writes:
    data/analysis_ready/sponsor_ip_features.parquet
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "analysis_ready")
PAT = os.path.join(ROOT, "data", "patents")

PORTFOLIO = os.path.join(PAT, "assignee_portfolio.csv")
FWD = os.path.join(PAT, "forward_citations_family.csv")
CORE = os.path.join(PAT, "patent_core.csv")
PATMAP = os.path.join(OUT, "orangebook_patent_appl_map.parquet")

WINDOW = range(2008, 2020)      # the analytic window; see the report, Section 3

# ---------------------------------------------------------------------------
# ASSIGNEE EXCLUSIONS, hand-verified 2026-10-24
#
# prep_12 matched on distinctive company tokens, which is what made the real
# vocabulary findable, but a token is not a company. Two kinds of false link
# survived into bigquery_assignee_verified.csv and are removed here rather than
# in the SQL, so that no BigQuery re-run is needed.
#
# 1. INDIVIDUAL INVENTORS. Nineteen people named Bayer, two named Mallinckrodt
#    and others whose given or middle name is Orion, Wyeth or Shire. Their 500
#    or so patents would be credited to the firm that shares the name. Bayer's
#    portfolio was overstated by about 1.7% by this alone.
#
# 2. UNRELATED FIRMS SHARING A BRAND WORD. ORION is the worst case in the whole
#    crosswalk: it is a constellation, and the token matched Orion Energy
#    Systems (lighting), Orion Engineered Carbons (carbon black), Orion
#    Machinery, Thermo Orion, Beijing Orion Star and a dozen more. Of the 877
#    patents measured for the ORION group, 562 belonged to companies with no
#    connection to Orion Oyj, the Finnish pharmaceutical firm. Only ORION CORP
#    and ORION YHTYMAE OY are kept.
#
# Also removed: BAYER CROPSCIENCE and ORION DIAGNOSTICA OY, which are crop
# science and diagnostics, on the same ground as the other exclusions recorded
# in prep_12 (the author's decision of 2026-10-24).
#
# ORION is flagged low-confidence regardless: ORION CORP is the legal English
# name of the Finnish pharmaceutical firm, but also of an unrelated Korean
# confectionery company, and the two cannot be separated from the harmonized
# name alone. The group covers 20 trials in the frame.
# ---------------------------------------------------------------------------
EXCLUDE_ASSIGNEES = {
    # individual inventors
    "BAYER ERWIN", "BAYER STEFAN", "BAYER LEX", "BAYER EBEN", "BAYER ETHAN E",
    "BAYER THOMAS", "BAYER ULLRICH", "BAYER ROBERT", "BAYER ROLAND",
    "BAYER ALEXANDER", "BAYER ROSS DAVID", "BAYER MICHAEL", "BAYER JASON",
    "BAYER ROBERT J", "BAYER ANDREAS", "BAYER JOHANN", "BAYER HANSPETER R",
    "BAYER TRAVIS S", "BAYER JOHANNES",
    "MALLINCKRODT GEORGE E", "PHILIP A MALLINCKRODT",
    "JANKOWSKI ORION D", "WEIHE ORION", "PRITCHARD JEFFREY ORION",
    "WILDER-SMITH OLIVER ORION",
    "WASSERMAN WYETH W", "SHIRE STEVEN J",
    # unrelated firms sharing the word ORION
    "FIRST ORION CORP", "ORION ENERGY SYSTEMS INC", "ORION RESEARCH",
    "ORION INDUSTRIES", "ORION LABS", "ORION LABS INC",
    "ORION MACHINERY CO LTD", "ORION PHOTO IND INC", "THERMO ORION INC",
    "BEIJING ORION STAR TECH CO LTD", "ORION GENOMICS LLC",
    "ORION ENG CARBONS GMBH", "ORION ENG CARBONS IP GMBH & CO KG",
    "ORION BIOTECH INC", "ORION IND LTD", "ORION CO LTD",
    "ORION ENG SEALS LLC", "ORION INNOVATIONS INC", "ORION OPHTHALMOLOGY LLC",
    # crop science and diagnostics
    "BAYER CROPSCIENCE", "ORION DIAGNOSTICA OY",
}

LOW_CONFIDENCE_GROUPS = {"ORION"}



def sponsor_asof(portfolio):
    """Cumulative portfolio per corporate group per year, respecting ownership.

    The SQL returns a cumulative series per assignee name per grant year, with
    gaps in years where that assignee was granted nothing. Carrying the last
    known value forward is what makes "as of 2013" meaningful: a firm that was
    granted no patent in 2013 still holds everything it held in 2012.
    """
    portfolio = portfolio.copy()
    portfolio["grant_year"] = pd.to_numeric(portfolio.grant_year, errors="coerce")
    portfolio["parent_from_year"] = pd.to_numeric(
        portfolio.parent_from_year, errors="coerce")
    portfolio = portfolio.dropna(subset=["grant_year"])
    before = portfolio.cum_all.groupby(portfolio.assignee_norm).max().sum()
    portfolio = portfolio[~portfolio.assignee_norm.str.upper().isin(EXCLUDE_ASSIGNEES)]
    after = portfolio.cum_all.groupby(portfolio.assignee_norm).max().sum()
    print("excluded %d assignee names (individuals and unrelated firms), "
          "removing %s patents" % (len(EXCLUDE_ASSIGNEES), format(int(before - after), ",")))

    out = []
    skipped_by_timing = 0
    for (group, assignee), g in portfolio.groupby(["corporate_group", "assignee_norm"]):
        g = g.sort_values("grant_year").drop_duplicates("grant_year", keep="last")
        series = (g.set_index("grant_year")[["cum_all", "cum_pharma"]]
                   .reindex(range(int(g.grant_year.min()), max(WINDOW) + 1))
                   .ffill())
        owned_from = g.parent_from_year.dropna()
        owned_from = int(owned_from.iloc[0]) if len(owned_from) else None
        for year in WINDOW:
            if year not in series.index:
                continue
            if owned_from is not None and year < owned_from:
                skipped_by_timing += 1
                continue
            row = series.loc[year]
            if pd.isna(row.cum_all):
                continue
            out.append((group, year, float(row.cum_all), float(row.cum_pharma)))

    df = pd.DataFrame(out, columns=["corporate_group", "start_year",
                                    "portfolio_all", "portfolio_pharma"])
    agg = (df.groupby(["corporate_group", "start_year"], as_index=False)
             .agg(assignee_portfolio_size=("portfolio_all", "sum"),
                  assignee_pharma_patents=("portfolio_pharma", "sum")))
    agg["assignee_pharma_share"] = np.where(
        agg.assignee_portfolio_size > 0,
        agg.assignee_pharma_patents / agg.assignee_portfolio_size, np.nan)
    return agg, skipped_by_timing


def drug_level(patmap):
    """Forward citations and family breadth per FDA application.

    Returns None when the patent-to-application mapping is unavailable, rather
    than silently producing a column of nulls that would look like a measured
    zero downstream.
    """
    if not os.path.exists(patmap):
        return None
    m = pd.read_parquet(patmap)
    fwd = pd.read_csv(FWD, dtype={"patent_prefix": str})
    core = pd.read_csv(CORE, dtype={"patent_prefix": str})

    # US-7625884 -> 7625884, which is how the Orange Book stores Patent_No
    for d in (fwd, core):
        d["patent_no"] = (d.patent_prefix.str.replace("US-", "", regex=False)
                           .str.replace("RE", "", regex=False).str.strip())
    m = m.copy()
    m["patent_no"] = m.patent_no.astype(str).str.strip()

    j = (m.merge(fwd[["patent_no", "n_forward_citations", "family_size",
                      "family_n_countries"]].drop_duplicates("patent_no"),
                 on="patent_no", how="left")
          .merge(core[["patent_no", "n_cpc_a61k", "n_cpc_a61p"]]
                 .drop_duplicates("patent_no"), on="patent_no", how="left"))
    return (j.groupby("appl_no", as_index=False)
             .agg(citations_per_patent=("n_forward_citations", "mean"),
                  family_size=("family_size", "mean"),
                  family_n_countries=("family_n_countries", "mean"),
                  drug_patents_matched=("patent_no", "nunique")))


def main():
    for f in (PORTFOLIO, FWD, CORE):
        if not os.path.exists(f):
            sys.exit("missing extract: %s\nRun the queries in sql/ first." % f)

    smap = pd.read_parquet(os.path.join(OUT, "sponsor_assignee_map.parquet"))
    portfolio = pd.read_csv(PORTFOLIO)

    asof, skipped = sponsor_asof(portfolio)
    feat = smap[["nct_id", "corporate_group", "start_year", "is_industry",
                 "is_resolved"]].copy()
    feat = feat.merge(asof, on=["corporate_group", "start_year"], how="left")

    drug = drug_level(PATMAP)
    if drug is not None:
        res = pd.read_parquet(os.path.join(OUT, "trial_drug_resolution.parquet"),
                              columns=["nct_id", "appl_no"])
        feat = feat.merge(res.merge(drug, on="appl_no", how="left")
                             .drop(columns=["appl_no"])
                             .groupby("nct_id", as_index=False).mean(numeric_only=True),
                          on="nct_id", how="left")

    keep = ["nct_id", "corporate_group", "assignee_portfolio_size",
            "assignee_pharma_patents", "assignee_pharma_share",
            "citations_per_patent", "family_size", "family_n_countries",
            "drug_patents_matched"]
    out = feat[[c for c in keep if c in feat.columns]]
    path = os.path.join(OUT, "sponsor_ip_features.parquet")
    out.to_parquet(path, index=False, compression="zstd")

    # ---- coverage, reported per component ---------------------------------
    frame = feat[(feat.start_year.between(2008, 2019)) & (feat.is_resolved == 1)]
    n = len(frame)
    ind = frame[frame.is_industry == 1]
    have = frame.assignee_portfolio_size.notna()

    print("=" * 70)
    print("prep_13: sponsor-level IP features")
    print("=" * 70)
    print("analytic frame trials                %6d" % n)
    print("  with a sponsor-level portfolio     %6d  (%.1f%%)" % (
        have.sum(), 100 * have.mean()))
    print("  industry trials                    %6d" % len(ind))
    print("    with a portfolio                 %6d  (%.1f%%)" % (
        ind.assignee_portfolio_size.notna().sum(),
        100 * ind.assignee_portfolio_size.notna().mean()))
    print("  non-industry trials                %6d  (portfolio not measured)" % (
        len(frame) - len(ind)))
    print()
    print("assignee-years suppressed by acquisition timing: %d" % skipped)
    print()
    print("component coverage on the analytic frame:")
    for col, dim in (("assignee_portfolio_size", "SCALE"),
                     ("assignee_pharma_share", "FOCUS"),
                     ("citations_per_patent", "QUALITY"),
                     ("family_size", "BREADTH")):
        if col in frame.columns:
            pc = 100 * frame[col].notna().mean()
            print("  %-9s %-26s %6.1f%%" % (dim, col, pc))
        else:
            print("  %-9s %-26s %6s" % (dim, col, "absent"))
    print()
    if drug is None:
        print("QUALITY and BREADTH were not computed. sql/02 returned them per")
        print("Orange Book patent, but attaching them to a trial needs the")
        print("patent-to-application mapping, which is not on disk:")
        print("  %s" % PATMAP)
        print()
        print("To produce it, re-download the Orange Book data files and run:")
        print("  python scripts/prep/prep_02_orangebook.py <orange_book_dir> %s" % OUT)
        print("after adding the two lines marked in that script that persist")
        print("the appl_no / patent_no pairs. Nothing else needs re-running.")
        print()
    print("wrote %s  (%d rows)" % (path, len(out)))
    if have.mean() < 0.5:
        print()
        print("NOTE: the sponsor-level measure covers under half the frame, so it")
        print("is not yet the survivorship-safe measure available for every trial")
        print("that README.md describes. The curated list names 71 corporate")
        print("groups; the frame holds thousands of distinct lead sponsors.")


if __name__ == "__main__":
    main()
