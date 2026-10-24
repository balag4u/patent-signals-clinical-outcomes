#!/usr/bin/env python3
"""Reconcile the curated assignee names against the real assignee_harmonized vocabulary.

`bigquery_assignee_names.csv` was written by hand from how firms describe
themselves. The probe query in sql/RUNBOOK.md showed that those strings mostly
do not exist in BigQuery: NOVARTIS AG returned 8,724 patents, ELI LILLY AND CO
returned 3, PFIZER INC returned 2, and F HOFFMANN LA ROCHE AG returned nothing.

`assignee_harmonized` is not harmonized to legal names. It abbreviates
(LABORATORIES -> LAB, PHARMACEUTICALS -> PHARMA, INTERNATIONAL -> INT), drops
legal suffixes (PFIZER INC -> PFIZER), and sometimes inverts word order
(ELI LILLY AND CO -> LILLY CO ELI). Exact equality against a hand-written name
can therefore only succeed by luck.

Four things this has to get right:

1. INDIVIDUAL INVENTORS SHARE SURNAMES WITH FIRMS. The dictionary holds over a
   hundred TAKEDA <given name> rows that are people, not Takeda Pharmaceutical,
   plus ROCHE OLIVIER, LILLY BRIAN P, HUANG LILLY and JOHNSON CAROLYN ROCHE.
   Attributing those patents to a sponsor would inflate its portfolio with
   strangers' work. Rows carrying no legal form and no corporate descriptor are
   flagged LIKELY_PERSON rather than matched.

2. ONE FIRM HOLDS PATENTS UNDER MANY NAMES. Roche appears as HOFFMANN LA ROCHE,
   ROCHE PALO ALTO, ROCHE GLYCART, GENENTECH INC and a dozen more. Missing them
   understates the portfolio, which is the error this whole exercise exists to
   prevent.

3. THE TWO MERCKS MUST NOT MERGE. Merck & Co (US) and Merck KGaA (Darmstadt)
   split in 1917 and are unrelated. Both reduce to the token MERCK, so neither
   is matched on that token alone, and every MERCK row is sent to review.
   MERCKLE GMBH is a third, unrelated firm and must not join either.

4. DIVERSIFIED GROUPS PATENT OUTSIDE PHARMA. BAYER AG's 18,712 patents include
   crop science and materials; ROCHE DIAGNOSTICS and ROCHE DIABETES CARE are
   devices. Counting them measures corporate size, not drug-development IP.
   These are flagged NON_PHARMA for an explicit decision rather than silently
   kept or dropped.

Nothing here rewrites bigquery_assignee_names.csv. It emits a crosswalk with a
confidence tier per row, to be adjudicated the same way the 200-link entity
resolution sample is, because the cost of a wrong link is a corrupted portfolio
for the study's central independent variable.

Usage:
    python scripts/prep/prep_12_assignee_crosswalk.py

Reads:
    data/patents/assignee_name_dictionary.csv      (from sql/00_assignee_name_discovery.sql)
    data/analysis_ready/bigquery_assignee_names.csv

Writes:
    data/patents/assignee_crosswalk.csv            proposed links, one per tier
    data/patents/assignee_crosswalk_report.txt     coverage and what needs deciding
"""
import csv
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DICT_CSV = os.path.join(ROOT, "data", "patents", "assignee_name_dictionary.csv")
CURATED_CSV = os.path.join(ROOT, "data", "analysis_ready", "bigquery_assignee_names.csv")
SQL_FILE = os.path.join(ROOT, "sql", "00_assignee_name_discovery.sql")
OUT_CSV = os.path.join(ROOT, "data", "patents", "assignee_crosswalk.csv")
OUT_TXT = os.path.join(ROOT, "data", "patents", "assignee_crosswalk_report.txt")
OUT_VERIFIED = os.path.join(ROOT, "data", "analysis_ready", "bigquery_assignee_verified.csv")

# Legal forms carry no identifying information and are dropped inconsistently by
# the harmonizer, so they are dropped from both sides. KGAA is deliberately NOT
# here: it is the only thing distinguishing Merck KGaA from Merck & Co.
LEGAL = {
    "INC", "INCORPORATED", "LLC", "LTD", "LIMITED", "CORP", "CORPORATION",
    "CO", "COMPANY", "GMBH", "AG", "AB", "ASA", "NV", "SA", "SAS", "SPA",
    "SRL", "PLC", "KK", "PTY", "BV", "OY", "APS", "SARL", "LP", "LLP",
    "AS", "SE", "SPRL", "DAC", "CIE", "HOLDINGS", "HOLDING", "GROUP",
    # Japanese joint-stock company, the equivalent of Inc. Dropping it is what
    # lets CHUGAI SEIYAKU KABUSHIKI KAISHA reach CHUGAI PHARMACEUTICAL CO LTD.
    "KABUSHIKI", "KAISHA", "GAISHA",
    # Geography is not identity, and the harmonizer keeps it unevenly
    # (JANSSEN R & D IRELAND, ASTRAZENECA CANADA, GLAXOSMITHKLINE ZAGREB).
    "USA", "US", "AMERICA", "AMERICAS", "EUROPE", "JAPAN", "CHINA",
    "CANADA", "UK", "IRELAND", "DEUTSCHLAND", "ITALIA", "AUSTRALIA",
    "ZAGREB", "GLOBAL", "WORLDWIDE",
}

# The harmonizer truncates. Both sides are folded onto the shorter stem.
# SEIYAKU, FARMACEUTICI and FARMA are the Japanese and Italian words for
# pharmaceutical: without them, firms that patent under a local-language name
# never reach their English curated name.
SYNONYM = {
    "LABORATORIES": "LAB", "LABORATORY": "LAB", "LABORATOIRES": "LAB", "LABS": "LAB",
    "PHARMACEUTICALS": "PHARMA", "PHARMACEUTICAL": "PHARMA", "PHARM": "PHARMA",
    "PHARMACEUTICA": "PHARMA", "PHARMAS": "PHARMA", "BIOPHARMA": "PHARMA",
    "SEIYAKU": "PHARMA", "FARMACEUTICI": "PHARMA", "FARMACEUTICA": "PHARMA",
    "FARMA": "PHARMA",
    "INTERNATIONAL": "INT", "INTERNAT": "INT",
    "INDUSTRIES": "IND", "INDUSTRIAL": "IND", "INDUSTRY": "IND", "KOGYO": "IND",
    "CHEMICALS": "CHEM", "CHEMICAL": "CHEM",
    "PRODUCTS": "PROD", "THERAPEUTICS": "THERAP", "THERAPEUT": "THERAP",
    "BIOLOGICALS": "BIOLOG", "BIOLOGICS": "BIOLOG",
    "RESEARCH": "RES", "DEVELOPMENT": "DEV", "MANAGEMENT": "MAN",
    "SCIENTIFIC": "SCIENT", "SCIENCES": "SCI", "SCIENCE": "SCI",
    "HEALTHCARE": "HEALTH", "HEALT": "HEALTH",
    "INTELLECTUAL": "IP", "CENTER": "CT", "CENTRE": "CT",
    "MANUFACTURING": "MFG",
}

# A row carrying one of these is a company, not a person.
CORPORATE = {
    "PHARMA", "LAB", "CHEM", "IND", "PROD", "THERAP", "BIOLOG", "RES", "DEV",
    "MAN", "SCI", "SCIENT", "HEALTH", "IP", "CT", "INT", "PATENT", "PATENTS",
    "VACCINES", "DIAGNOSTICS", "DIAGNOSTIC", "SYSTEMS", "SYSTEM", "SOLUTIONS",
    "OPERATIONS", "TECHNOLOGY", "TECHNOLOGIES", "CONSUMER", "MOLECULAR",
    "SEQUENCING", "BIOTECH", "GENETICS", "MEDICINE", "MEDICAL",
    "VITAMINS", "AGROCHEM", "AGROCHEMICALS", "WORKS", "ENG", "HDAC", "LIFE",
    "NORDISK", "INGELHEIM", "MFG", "SEISAKUSHO", "SCREEN", "MOTORS", "POWER",
    # Institutions and industrial divisions. Without these, ISIS INNOVATION
    # (Oxford's technology transfer arm), UNIV BRISTOL, KIRIN BREWERY and
    # MITSUBISHI NUCLEAR FUEL were all being read as individual inventors.
    "UNIV", "UNIVERSITY", "UNIVERSITE", "INST", "INSTITUTE", "SCHOOL",
    "HOSPITAL", "FOUND", "FOUNDATION", "TRUST", "COUNCIL", "INNOVATION",
    "BREWERY", "BREWING", "METALS", "ALUMINIUM", "ALUMINUM", "SEMICONDUCTOR",
    "NUCLEAR", "FUEL", "SILICON", "COMPRESSORS", "PLASTICS", "PRECISION",
    "AIRCRAFT", "ENTPR", "ENTERPRISES", "VETMEDICA", "VETMED", "KG",
    "SOHN", "SOEHNE", "SOHNE", "SONS", "FROSST", "MILLIPORE", "SPEC",
}

# Patenting activity that is not drug development. Flagged, not dropped: whether
# a sponsor's device and diagnostics patents belong in its IP position is an
# analytic decision, not a data-cleaning one.
NON_PHARMA = {
    "ELECTRIC", "ELECTRONICS", "WIRING", "RUBBER", "PRINTING", "HEAVY",
    "MOTOREN", "WERKE", "STEEL", "METAL", "MATERIALS", "CEMENT", "GLASS",
    "MINING", "PETROCHEM", "PETROCHEMICAL", "INK", "GAS", "BRUSH", "REALTY",
    "LIGHTING", "CONTROLS", "MATTHEY", "MICROSYSTEMS", "NETWORKS", "HOBBY",
    "AIRLINES", "ELECTROCHROMICS", "COMPUTER", "AGROCHEM", "AGROCHEMICALS",
    "VITAMINS", "DIABETES", "DIAGNOSTICS", "DIAGNOSTIC", "SEQUENCING",
    "NIMBLEGEN", "SURGERY", "BEARINGS", "TIRE", "CABLE", "MOTORS", "POWER",
    "RAYON", "BAKELITE", "PENCIL", "PAPER", "MILLS", "SCREEN", "SEIKA",
    "RIKO", "HITACHI", "CARDIOVASCULAR", "VASCULAR", "OPTICS",
}

# Groups whose token overlap is genuinely ambiguous. Every candidate goes to
# review regardless of tier. See concern 3 in the module docstring.
FORCE_REVIEW_TOKENS = {"MERCK", "SCHERING"}

# ---------------------------------------------------------------------------
# ADJUDICATED DECISIONS, 2026-10-24
#
# Settled with the author after reading the first crosswalk report. Each is a
# measurement choice, recorded here so the reasoning survives in the repository
# rather than in a conversation.
#
# 1. DIAGNOSTICS AND DEVICE ARMS ARE EXCLUDED. The research question is about
#    drug development, and a glucose-meter patent carries no information about
#    the strength of a drug programme. Keeping them would inflate diversified
#    firms (Abbott, Roche) against pure-play pharma (Regeneron), confounding
#    the IP measure with business model. Implemented by dropping links flagged
#    NON_PHARMA.
#
# 2. CONGLOMERATE PARENTS ARE EXCLUDED. Sumitomo Chemical (13,026 patents),
#    Mitsubishi Chemical (6,193) and Kirin Brewery (382) do own pharmaceutical
#    subsidiaries, but counting them would make Sumitomo Pharma look like a
#    patent giant on the strength of agrochemicals and plastics. They are
#    unclaimed already, so this is recorded rather than coded.
#
# 3. VACCINES OVERRIDE THE DIAGNOSTICS EXCLUSION. NOVARTIS VACCINES &
#    DIAGNOSTIC is a single division under a combined name; vaccines are
#    therapeutics, and the curated list names NOVARTIS VACCINES explicitly.
#
# 4. PREDECESSOR NAMES ARE INCLUDED. These are the same firms under earlier
#    names, and parent_from_year already carries the acquisition timing.
#
# 5. BEHRINGWERKE AG (384) IS LEFT UNLINKED. Its line runs Hoechst to Aventis
#    to Sanofi, but CSL acquired Aventis Behring in 2004, so it could belong to
#    either SANOFI or CSL. An ambiguous link is worse than a missing one.
# ---------------------------------------------------------------------------

# A link flagged NON_PHARMA survives only if its name carries one of these.
PHARMA_OVERRIDE = {"VACCINES", "BIOLOG"}

# Real BigQuery name forms the token matcher cannot reach, because the firm
# patents under a descriptor its curated name does not share: a SEIYAKU-era
# name, THERAPEUTICS where the curated name says PHARMACEUTICALS, or a city
# prefix. Verified by hand against the dictionary.
MANUAL_LINKS = [
    ("TAKEDA", "TAKEDA CHEMICAL INDUSTRIES LTD", "", "Takeda's name until 2001"),
    ("KYOWA", "KYOWA HAKKO KOGYO KK", "", "Kyowa Hakko's name until the 2008 Kirin merger"),
    ("DAIICHI", "DAIICHI SEIYAKU CO", "", "Daiichi's name before the 2005 Sankyo merger"),
    ("CHIESI", "CHIESI FARM SPA", "", "abbreviated form of CHIESI FARMACEUTICI"),
    ("OTSUKA", "ASTEX THERAPEUTICS LTD", "2013", "Astex's name before Otsuka acquired it"),
    ("HENGRUI", "Shanghai hengrui pharmaceutical co ltd", "", "Hengrui subsidiary, city-prefixed"),
    ("MERCK_US", "MERCK FROSST CANADA INC", "", "Merck & Co's Canadian arm"),
    ("MERCK_US", "MERCK FROSST CANADA LTD", "", "Merck & Co's Canadian arm"),
    ("BOEHRINGER", "BOEHRINGER SOHN INGELHEIM", "", "founding-family form of the Ingelheim firm"),
    ("ROCHE", "ROCHE PALO ALTO LLC", "", "former Syntex pharmaceutical R&D site"),
]

# The two Mercks split in 1917 and both reduce to the token MERCK, so every
# MERCK row is assigned by hand or left out. Domicile decides: Darmstadt holds
# the PATENT GMBH and Serono entities, Rahway holds Sharp & Dohme and Frosst.
HAND_ASSIGNMENT = {
    "MERCK & CO INC": "MERCK_US",
    "MERCK SHARP & DOHME": "MERCK_US",
    "MERCK SHARP & DOHME LLC": "MERCK_US",
    "MERCK SHARPE & DOHME CORP": "MERCK_US",
    "MERCK SHARPE & DOHME LTD": "MERCK_US",
    "SHARP & DOHME INC": "MERCK_US",
    "MERCK CANADA INC": "MERCK_US",
    "MERCK PATENT GMBH": "MERCK_KGAA",
    "MERCK PATENTGMBH": "MERCK_KGAA",
    "MERCK PATENT GMBH PATENTS & SCIENT INFORMATION": "MERCK_KGAA",
    "MERCK KGAA": "MERCK_KGAA",
    "MERCK GMBH": "MERCK_KGAA",
    "MERCK SERONO SA": "MERCK_KGAA",
    "MERCK MILLIPORE LTD": "MERCK_KGAA",
    "MERCK EPROVA AG": "MERCK_KGAA",
    "MERCK CHEMICALS AND LIFE SCIENCE AB": "MERCK_KGAA",
    "Merck & Cie": "MERCK_KGAA",
    "MERCK AG E": "MERCK_KGAA",
    "FIRM OF E MERCK": "MERCK_KGAA",

    # Schering Corp, Kenilworth NJ: became Schering-Plough, then Merck US 2009.
    "SCHERING CORP": "MERCK_US",
    "SCHERING CORP A NEW JERSEY COR": "MERCK_US",
    "SCHERING CORP AND PHARMACOPEIA": "MERCK_US",
    "SCHERING PLOUGH CORP": "MERCK_US",
    "SCHERING PLOUGH HEALTHCARE": "MERCK_US",
    "SCHERING PLOUGH HEALTHCARE PRODUCTS INC": "MERCK_US",

    # Schering AG, Berlin: an unrelated firm, acquired by Bayer in 2006.
    "SCHERING AG": "BAYER",
    "SCHERING KAHLBAUM AG": "BAYER",
    "FIRM SCHERING KAHLBAUM A G": "BAYER",
    "CHEM FAB VORM E SCHERING": "BAYER",
    "BAYER SCHERING PHARMA AG": "BAYER",
    "BAYER SCHERING PHARMA OY": "BAYER",
}

# Unattributable on purpose: bare MERCK could be either firm, MERCKLE GMBH is
# an unrelated German generics house, DU PONT MERCK was a dissolved joint
# venture whose IP was split, and MERCK HDAC RES is a shell of unclear parent.
HAND_DROP = {
    "MERCK", "MERCKLE GMBH", "DU PONT MERCK PHARMA", "MERCK HDAC RES LLC",
    # Crop science and animal health are not human drug development, the same
    # ground on which the diagnostics arms are excluded.
    "SCHERING AGROCHEMICALS LTD", "HOECHST SCHERING AGREVO GMBH",
    "SCHERING PLOUGH ANIMAL HEALTH", "SCHERING PLOUGH VETERINARY COR",
}

PUNCT = re.compile(r"[^A-Z0-9&]+")


def tokens(name):
    """Reduce a name to comparable identifying tokens."""
    up = PUNCT.sub(" ", name.upper()).strip()
    out = []
    for tok in up.split():
        tok = SYNONYM.get(tok, tok)
        if tok in LEGAL:
            continue
        out.append(tok)
    return out


def classify_unmatched(toks, raw):
    """Why a dictionary row matched nothing."""
    tokset = set(toks)
    if tokset & NON_PHARMA:
        return "NON_PHARMA", sorted(tokset & NON_PHARMA)[0]
    has_corporate = bool(tokset & CORPORATE)
    has_legal = any(t in LEGAL for t in PUNCT.sub(" ", raw.upper()).split())
    single_initial = any(len(t) == 1 and t != "&" for t in toks)
    if not has_corporate and not has_legal and (len(toks) <= 3 or single_initial):
        return "LIKELY_PERSON", "no legal form, no corporate descriptor"
    return "REVIEW", "unclaimed"


def audit_pattern_covers(curated):
    """Stop if the discovery query could not have found a curated name.

    The first run of 00_assignee_name_discovery.sql omitted the ORION and UCB
    tokens, so those two groups came back with no candidate. That looks
    identical to a firm holding no US patents, and it is not: it is a bug in
    the query. A group reported as absent must be absent from the patent
    record, never absent from the search.
    """
    try:
        src = open(SQL_FILE).read()
        raw = re.search(r"    r'(.+)' AS token_pattern", src).group(1)
    except (IOError, OSError, AttributeError):
        print("warning: no token pattern found in %s, coverage not audited" % SQL_FILE)
        return
    pat = re.compile(raw)
    blind = [c for c in curated if not pat.search(c["name"].upper())]
    if blind:
        print("The discovery query cannot find these curated names:")
        for c in blind:
            print("  %-14s %s" % (c["group"], c["name"]))
        sys.exit("Add their tokens to sql/%s, re-run it, and re-download the "
                 "dictionary before trusting any coverage figure."
                 % os.path.basename(SQL_FILE))


def build_verified(links, dictionary):
    """Apply the adjudicated decisions and emit the upload-ready assignee list.

    This is the file that replaces the hand-written names in BigQuery. The
    original bigquery_assignee_names.csv is left untouched: it records what was
    guessed, this records what was verified, and keeping both makes the
    correction auditable.
    """
    counts = {d["name"]: d["n"] for d in dictionary}
    rows = {}
    dropped = {"non_pharma": [], "unattributable": [], "unmapped": []}

    for r in links:
        name = r["harmonized_name"]
        flags = r["flags"]
        group = r["corporate_group"]

        if "FORCED_REVIEW" in flags:
            continue  # every MERCK row is resolved from HAND_ASSIGNMENT below

        if "NON_PHARMA" in flags:
            if not (set(tokens(name)) & PHARMA_OVERRIDE):
                dropped["non_pharma"].append((group, name, r["n_patents"]))
                continue

        rows[(group, name)] = {
            "corporate_group": group,
            "harmonized_name": name,
            "n_patents": r["n_patents"],
            "parent_from_year": r["parent_from_year"],
            "source": r["tier"],
        }

    # Merck, decided by domicile rather than by token overlap. Names already
    # settled in MANUAL_LINKS (the Frosst entities) are skipped here so they
    # are not reported as unmapped by a check that runs before them.
    manual_names = {name for _, name, _, _ in MANUAL_LINKS}
    for d in dictionary:
        name = d["name"]
        if not (set(tokens(name)) & FORCE_REVIEW_TOKENS):
            continue
        if name in manual_names:
            continue
        if name in HAND_DROP:
            dropped["unattributable"].append(("", name, d["n"]))
            continue
        group = HAND_ASSIGNMENT.get(name)
        if group is None:
            dropped["unmapped"].append(("", name, d["n"]))
            continue
        rows[(group, name)] = {
            "corporate_group": group,
            "harmonized_name": name,
            "n_patents": d["n"],
            "parent_from_year": "",
            "source": "HAND_ADJUDICATED",
        }

    # Names the token matcher could not reach.
    missing_manual = []
    for group, name, year, why in MANUAL_LINKS:
        if name not in counts:
            missing_manual.append((group, name))
            continue
        rows[(group, name)] = {
            "corporate_group": group,
            "harmonized_name": name,
            "n_patents": counts[name],
            "parent_from_year": year,
            "source": "MANUAL",
        }

    out = sorted(rows.values(), key=lambda r: (r["corporate_group"], -r["n_patents"]))
    with open(OUT_VERIFIED, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "corporate_group", "harmonized_name", "n_patents",
            "parent_from_year", "source"])
        w.writeheader()
        w.writerows(out)
    return out, dropped, missing_manual


def main():
    for path in (DICT_CSV, CURATED_CSV):
        if not os.path.exists(path):
            sys.exit("missing input: %s" % path)

    curated = []
    with open(CURATED_CSV, newline="") as fh:
        for row in csv.DictReader(fh):
            name = row["assignee_name"].strip()
            if not name:
                continue
            curated.append({
                "group": row["corporate_group"].strip(),
                "name": name,
                "parent_from_year": (row.get("parent_from_year") or "").strip(),
                "tokens": set(tokens(name)),
            })

    audit_pattern_covers(curated)

    dictionary = []
    with open(DICT_CSV, newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row["harmonized_name"].strip()
            dictionary.append({
                "name": raw,
                "n": int(row["n_patents"]),
                "tokens": tokens(raw),
            })

    links = []
    unmatched = []
    for d in dictionary:
        dset = set(d["tokens"])
        if not dset:
            continue
        best = []
        for c in curated:
            cset = c["tokens"]
            if not cset:
                continue
            if cset == dset:
                tier = "A_exact"
            elif cset < dset:
                tier = "B_subsidiary"      # harmonized name is more specific
            elif dset < cset:
                tier = "C_parent"          # harmonized name is less specific
            else:
                continue
            best.append((tier, c))
        if not best:
            kind, why = classify_unmatched(d["tokens"], d["name"])
            unmatched.append((d, kind, why))
            continue
        # One harmonized name can satisfy several curated names in the same
        # group (NOVARTIS AG and NOVARTIS PHARMA AG both reduce toward
        # NOVARTIS), which produces duplicate rows saying the same thing. Keep
        # the strongest tier per group. Every distinct group is kept, so
        # cross-group ambiguity stays visible to the adjudicator.
        groups = {c["group"] for _, c in best}
        forced = bool(set(d["tokens"]) & FORCE_REVIEW_TOKENS)
        per_group = {}
        for tier, c in best:
            held = per_group.get(c["group"])
            if held is None or tier < held[0]:
                per_group[c["group"]] = (tier, c)
        for tier, c in sorted(per_group.values(), key=lambda t: t[0]):
            flags = []
            if forced:
                flags.append("FORCED_REVIEW")
            if len(groups) > 1:
                flags.append("MULTI_GROUP:" + "/".join(sorted(groups)))
            if set(d["tokens"]) & NON_PHARMA:
                flags.append("NON_PHARMA:" + sorted(set(d["tokens"]) & NON_PHARMA)[0])
            links.append({
                "corporate_group": c["group"],
                "curated_name": c["name"],
                "harmonized_name": d["name"],
                "n_patents": d["n"],
                "tier": "D_review" if forced else tier,
                "parent_from_year": c["parent_from_year"],
                "flags": ";".join(flags),
            })

    links.sort(key=lambda r: (r["corporate_group"], -r["n_patents"]))
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "corporate_group", "curated_name", "harmonized_name", "n_patents",
            "tier", "parent_from_year", "flags"])
        w.writeheader()
        w.writerows(links)

    # ---- report -----------------------------------------------------------
    by_tier = defaultdict(int)
    for r in links:
        by_tier[r["tier"]] += 1
    matched_curated = {r["curated_name"] for r in links}
    missing = [c for c in curated if c["name"] not in matched_curated]
    groups_with = {r["corporate_group"] for r in links}
    all_groups = {c["group"] for c in curated}

    by_kind = defaultdict(list)
    for d, kind, why in unmatched:
        by_kind[kind].append((d, why))

    L = []
    L.append("Assignee crosswalk report")
    L.append("=" * 72)
    L.append("")
    L.append("dictionary rows in                 %5d" % len(dictionary))
    L.append("curated names in                   %5d" % len(curated))
    L.append("corporate groups in                %5d" % len(all_groups))
    L.append("")
    L.append("proposed links                     %5d" % len(links))
    for tier in sorted(by_tier):
        L.append("  %-32s %5d" % (tier, by_tier[tier]))
    L.append("")
    orphan_groups = all_groups - groups_with
    subsumed = [c for c in missing if c["group"] in groups_with]
    truly_absent = [c for c in missing if c["group"] not in groups_with]
    L.append("groups with no link at all         %5d of %d  <- the real gap" % (
        len(orphan_groups), len(all_groups)))
    L.append("curated names not chosen for a row %5d of %d" % (len(missing), len(curated)))
    L.append("  subsumed by a stronger match       %3d" % len(subsumed))
    L.append("  in a group with no link at all     %3d" % len(truly_absent))
    L.append("")
    L.append("unclaimed dictionary rows          %5d" % len(unmatched))
    for kind in sorted(by_kind):
        rows = by_kind[kind]
        L.append("  %-32s %5d  (%s patents)" % (
            kind, len(rows), format(sum(d["n"] for d, _ in rows), ",")))
    L.append("")

    L.append("-" * 72)
    L.append("DECIDE THESE: largest unclaimed rows marked REVIEW")
    L.append("-" * 72)
    L.append("A large patent count here means a real assignee the curated list")
    L.append("does not name. Each is either a missing name or a different firm.")
    L.append("")
    for d, why in sorted(by_kind.get("REVIEW", []), key=lambda t: -t[0]["n"])[:30]:
        L.append("  %8s  %s" % (format(d["n"], ","), d["name"]))
    L.append("")

    L.append("-" * 72)
    L.append("CURATED NAMES NOT CHOSEN FOR A ROW")
    L.append("-" * 72)
    L.append("Most of these are harmless. Where two curated names in one group")
    L.append("reduce to the same tokens, only the stronger tier is kept, so")
    L.append("F HOFFMANN LA ROCHE AG disappears behind HOFFMANN LA ROCHE INC")
    L.append("while the Roche group itself is well covered. Read the group")
    L.append("column, not this list, to judge coverage.")
    L.append("")
    for c in sorted(subsumed, key=lambda c: (c["group"], c["name"])):
        L.append("  subsumed   %-14s %s" % (c["group"], c["name"]))
    for c in sorted(truly_absent, key=lambda c: (c["group"], c["name"])):
        L.append("  NO LINK    %-14s %s" % (c["group"], c["name"]))
    L.append("")

    if orphan_groups:
        L.append("-" * 72)
        L.append("GROUPS WITH NO LINK AT ALL")
        L.append("-" * 72)
        L.append("These sponsors would carry a portfolio of zero. Confirm the firm")
        L.append("really holds no US patents before accepting that.")
        L.append("")
        for g in sorted(orphan_groups):
            L.append("  " + g)
        L.append("")

    L.append("-" * 72)
    L.append("LARGEST ROWS FLAGGED NON_PHARMA")
    L.append("-" * 72)
    L.append("Patenting outside drug development. Keeping them measures firm")
    L.append("size; dropping them narrows the portfolio to therapeutics.")
    L.append("")
    seen = set()
    for d, why in sorted(by_kind.get("NON_PHARMA", []), key=lambda t: -t[0]["n"])[:20]:
        L.append("  %8s  %-44s (%s)" % (format(d["n"], ","), d["name"], why))
        seen.add(d["name"])
    linked_np = sorted([r for r in links if "NON_PHARMA" in r["flags"]],
                       key=lambda r: -r["n_patents"])
    for r in linked_np[:20]:
        if r["harmonized_name"] not in seen:
            seen.add(r["harmonized_name"])
            L.append("  %8s  %-44s (linked to %s)" % (
                format(r["n_patents"], ","), r["harmonized_name"], r["corporate_group"]))
    L.append("")

    L.append("-" * 72)
    L.append("SAMPLE OF ROWS FLAGGED LIKELY_PERSON")
    L.append("-" * 72)
    L.append("Individual inventors sharing a surname with a firm. LIKELY_PERSON")
    L.append("and REVIEW are both excluded from linking, so a row in the wrong")
    L.append("one of the two costs reading time, not accuracy. Only a wrong")
    L.append("LINK corrupts a portfolio.")
    L.append("")
    for d, why in sorted(by_kind.get("LIKELY_PERSON", []), key=lambda t: -t[0]["n"])[:20]:
        L.append("  %8s  %s" % (format(d["n"], ","), d["name"]))
    L.append("")

    text = "\n".join(L) + "\n"
    with open(OUT_TXT, "w") as fh:
        fh.write(text)
    print(text)
    verified, dropped, missing_manual = build_verified(links, dictionary)
    vgroups = {r["corporate_group"] for r in verified}
    print("-" * 72)
    print("VERIFIED ASSIGNEE LIST")
    print("-" * 72)
    print("names            %5d" % len(verified))
    print("groups           %5d of %d" % (len(vgroups), len(all_groups)))
    print("patents covered  %s" % format(sum(r["n_patents"] for r in verified), ","))
    print("")
    print("dropped as diagnostics or non-pharma  %3d (%s patents)" % (
        len(dropped["non_pharma"]),
        format(sum(n for _, _, n in dropped["non_pharma"]), ",")))
    for g, n, c in sorted(dropped["non_pharma"], key=lambda t: -t[2]):
        print("    %8s  %-42s was %s" % (format(c, ","), n, g))
    print("")
    print("hand-assigned rows deliberately left out  %3d" % len(dropped["unattributable"]))
    for _, n, c in sorted(dropped["unattributable"], key=lambda t: -t[2]):
        print("    %8s  %s" % (format(c, ","), n))
    if dropped["unmapped"]:
        print("")
        print("ambiguous-name rows in neither map nor drop list -- DECIDE THESE  %3d" % len(
            dropped["unmapped"]))
        for _, n, c in sorted(dropped["unmapped"], key=lambda t: -t[2]):
            print("    %8s  %s" % (format(c, ","), n))
    if missing_manual:
        print("")
        print("MANUAL_LINKS names absent from the dictionary -- FIX THESE")
        for g, n in missing_manual:
            print("    %-14s %s" % (g, n))
    if all_groups - vgroups:
        print("")
        print("groups with no verified name: %s" % ", ".join(sorted(all_groups - vgroups)))
    print("")
    print("wrote %s" % OUT_CSV)
    print("wrote %s" % OUT_TXT)
    print("wrote %s" % OUT_VERIFIED)


if __name__ == "__main__":
    main()
