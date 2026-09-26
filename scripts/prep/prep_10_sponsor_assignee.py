#!/usr/bin/env python3
"""Map ClinicalTrials.gov lead sponsors to patent assignee search names.

Trial sponsors and patent assignees are written differently ("Hoffmann-La Roche"
vs "F. HOFFMANN-LA ROCHE AG"), and the registry sponsor field sometimes contains
prose ("Pfizer's Upjohn has merged with Mylan to form Viatris Inc.").

Three things this has to get right:

1. CORPORATE ROLLUP. Genentech's patents are Roche's; Janssen's are Johnson &
   Johnson's. Without rollup a sponsor's portfolio is understated.

2. ACQUISITION TIMING. Wyeth's patents became Pfizer's in 2009. Because IP is
   measured AS OF each trial's start date, the parent is only applied from the
   acquisition year onward; `parent_from_year` records it.

3. COMPANIES THAT MUST NOT BE MERGED. "Merck Sharp & Dohme" (US) and
   "Merck KGaA, Darmstadt" (Germany) are unrelated firms that split in 1917.
   Merging them would corrupt two of the largest portfolios in the data.
"""
import os, re, sys, json
import pandas as pd

OUT = sys.argv[1]

LEGAL = re.compile(
    r"\b(INC|INCORPORATED|LLC|L\.?L\.?C|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY|"
    r"GMBH|AG|A/S|AB|ASA|NV|N\.?V|SA|S\.?A|SAS|SPA|S\.?P\.?A|PLC|KK|K\.?K|"
    r"PTY|BV|B\.?V|OY|APS|SARL|LP|LLP|HOLDINGS?|GROUP|INTERNATIONAL|GLOBAL|"
    r"WORLDWIDE|USA|US|AMERICA|AMERICAS|EUROPE|JAPAN|CHINA|CANADA)\b\.?", re.I)
NOISE = re.compile(
    r"\b(PHARMACEUTICALS?|PHARMA|PHARMACEUTICA|THERAPEUTICS?|BIOSCIENCES?|"
    r"BIOPHARMACEUTICALS?|BIOPHARMA|BIOTECH\w*|LABORATORIES|LABS?|SCIENCES?|"
    r"RESEARCH|DEVELOPMENT|R&D|CLINICAL|MEDICAL|HEALTHCARE|HEALTH|PRODUCTS?|"
    r"OPERATIONS|COMMERCIALIZATION|INDUSTRIES|MEDICINE|FARMACEUTICI|"
    r"PHARMACEUTIQUES?)\b", re.I)
PROSE = re.compile(r"\(.*?\)|\b(prior sponsor|has merged with|formerly|now part of|"
                   r"a .* company|subsidiary of).*$", re.I)

def norm(s):
    if not isinstance(s, str): return ""
    s = PROSE.sub(" ", s).upper()
    s = re.sub(r"[.,&'`\"/\\-]", " ", s)
    s = LEGAL.sub(" ", s); s = NOISE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b[A-Z]\b", " ", s)          # drop stray single letters
    return re.sub(r"\s+", " ", s).strip()

# corporate group -> (match keys, BigQuery assignee search names, parent-from-year)
# parent_from_year: patents attribute to this group only for trials starting at or
# after that year; before it the subsidiary stood alone.
GROUPS = {
 "NOVARTIS":      (["NOVARTIS", "SANDOZ", "ALCON"], ["NOVARTIS AG","NOVARTIS PHARMA AG","NOVARTIS VACCINES","SANDOZ AG"], None),
 "ROCHE":         (["ROCHE","HOFFMANN LA ROCHE","GENENTECH","CHUGAI"], ["F HOFFMANN LA ROCHE AG","HOFFMANN LA ROCHE INC","GENENTECH INC","CHUGAI SEIYAKU KABUSHIKI KAISHA"], {"GENENTECH":2009}),
 "PFIZER":        (["PFIZER","WYETH","HOSPIRA","ARRAY BIOPHARMA","UPJOHN"], ["PFIZER INC","WYETH LLC","WYETH","HOSPIRA INC","ARRAY BIOPHARMA INC"], {"WYETH":2009,"HOSPIRA":2015,"ARRAY BIOPHARMA":2019}),
 "MERCK_US":      (["MERCK SHARP","MERCK CO","MERCK","MSD","SCHERING PLOUGH","ORGANON","CUBIST","IDENIX"], ["MERCK SHARP & DOHME CORP","MERCK SHARP & DOHME LLC","SCHERING CORP","SCHERING PLOUGH","ORGANON","CUBIST PHARMACEUTICALS"], {"SCHERING PLOUGH":2009,"CUBIST":2015}),
 "MERCK_KGAA":    (["MERCK KGAA","EMD SERONO","MERCK SERONO"], ["MERCK PATENT GMBH","MERCK KGAA","EMD SERONO","ARES TRADING SA"], None),
 "JOHNSON":       (["JANSSEN","JOHNSON","ACTELION","CENTOCOR","ALIOS","MOMENTA"], ["JANSSEN PHARMACEUTICA NV","JANSSEN BIOTECH INC","JOHNSON & JOHNSON","CENTOCOR","ACTELION PHARMACEUTICALS LTD"], {"ACTELION":2017,"MOMENTA":2020}),
 "ASTRAZENECA":   (["ASTRAZENECA","MEDIMMUNE","ALEXION"], ["ASTRAZENECA AB","ASTRAZENECA UK LIMITED","MEDIMMUNE LLC","ALEXION PHARMACEUTICALS INC"], {"ALEXION":2021}),
 "GSK":           (["GLAXOSMITHKLINE","GLAXO","GSK","VIIV","TESARO","HUMAN GENOME SCIENCES"], ["GLAXOSMITHKLINE LLC","GLAXO GROUP LIMITED","SMITHKLINE BEECHAM","VIIV HEALTHCARE","TESARO INC"], {"TESARO":2019}),
 "SANOFI":        (["SANOFI","GENZYME","AVENTIS","BIOVERATIV","ABLYNX"], ["SANOFI AVENTIS","SANOFI SA","GENZYME CORP","AVENTIS PHARMA SA","BIOVERATIV"], {"GENZYME":2011,"BIOVERATIV":2018,"ABLYNX":2018}),
 "ABBVIE":        (["ABBVIE","ABBOTT","PHARMACYCLICS","STEMCENTRX","ALLERGAN","FOREST LAB","ACTAVIS","WARNER CHILCOTT"], ["ABBVIE INC","ABBOTT LABORATORIES","PHARMACYCLICS LLC","ALLERGAN INC","FOREST LABORATORIES"], {"ALLERGAN":2020,"FOREST LAB":2014,"PHARMACYCLICS":2015}),
 "BMS":           (["BRISTOL","CELGENE","JUNO","MYOKARDIA"], ["BRISTOL MYERS SQUIBB CO","CELGENE CORP","JUNO THERAPEUTICS","E R SQUIBB & SONS"], {"CELGENE":2019,"JUNO":2018,"MYOKARDIA":2020}),
 "TAKEDA":        (["TAKEDA","MILLENNIUM","SHIRE","ARIAD","NYCOMED","BAXALTA"], ["TAKEDA PHARMACEUTICAL CO LTD","MILLENNIUM PHARMACEUTICALS INC","SHIRE","ARIAD PHARMACEUTICALS","BAXALTA"], {"MILLENNIUM":2008,"SHIRE":2019,"ARIAD":2017,"BAXALTA":2019}),
 "LILLY":         (["ELI LILLY","LILLY","LOXO","DERMIRA"], ["ELI LILLY AND CO","LILLY ICOS","LOXO ONCOLOGY","DERMIRA INC"], {"LOXO":2019,"DERMIRA":2020}),
 "BAYER":         (["BAYER"], ["BAYER AG","BAYER HEALTHCARE AG","BAYER PHARMA AG","BAYER INTELLECTUAL PROPERTY GMBH"], None),
 "BOEHRINGER":    (["BOEHRINGER"], ["BOEHRINGER INGELHEIM INTERNATIONAL GMBH","BOEHRINGER INGELHEIM PHARMA GMBH"], None),
 "AMGEN":         (["AMGEN","ONYX","IMMUNEX","FIVE PRIME"], ["AMGEN INC","ONYX THERAPEUTICS","IMMUNEX CORP"], {"ONYX":2013,"FIVE PRIME":2021}),
 "GILEAD":        (["GILEAD","KITE PHARMA","IMMUNOMEDICS"], ["GILEAD SCIENCES INC","KITE PHARMA INC","IMMUNOMEDICS INC"], {"KITE PHARMA":2017,"IMMUNOMEDICS":2020}),
 "NOVO":          (["NOVO NORDISK"], ["NOVO NORDISK AS","NOVO NORDISK HEALTHCARE AG"], None),
 "ASTELLAS":      (["ASTELLAS","AGENSYS","AUDENTES"], ["ASTELLAS PHARMA INC","AGENSYS INC"], {"AUDENTES":2020}),
 "BIOGEN":        (["BIOGEN"], ["BIOGEN MA INC","BIOGEN IDEC MA INC"], None),
 "TEVA":          (["TEVA","CEPHALON","ACTAVIS GENERIC"], ["TEVA PHARMACEUTICAL INDUSTRIES LTD","CEPHALON INC"], {"CEPHALON":2011}),
 "DAIICHI":       (["DAIICHI","PLEXXIKON"], ["DAIICHI SANKYO CO LTD","PLEXXIKON INC"], None),
 "OTSUKA":        (["OTSUKA","ASTEX"], ["OTSUKA PHARMACEUTICAL CO LTD","ASTEX PHARMACEUTICALS"], None),
 "EISAI":         (["EISAI","MORPHOTEK"], ["EISAI CO LTD","EISAI R&D MANAGEMENT","MORPHOTEK INC"], None),
 "VERTEX":        (["VERTEX"], ["VERTEX PHARMACEUTICALS INC"], None),
 "REGENERON":     (["REGENERON"], ["REGENERON PHARMACEUTICALS INC"], None),
 "INCYTE":        (["INCYTE"], ["INCYTE CORP","INCYTE HOLDINGS CORP"], None),
 "BAUSCH":        (["BAUSCH","VALEANT","SALIX"], ["BAUSCH HEALTH","VALEANT PHARMACEUTICALS","BAUSCH & LOMB INC","SALIX PHARMACEUTICALS"], None),
 "SUMITOMO":      (["SUMITOMO","SUNOVION","DAINIPPON"], ["SUMITOMO PHARMA CO LTD","SUNOVION PHARMACEUTICALS INC","DAINIPPON SUMITOMO PHARMA"], None),
 "LUNDBECK":      (["LUNDBECK"], ["H LUNDBECK AS"], None),
 "IPSEN":         (["IPSEN"], ["IPSEN PHARMA SAS"], None),
 "UCB":           (["UCB"], ["UCB BIOPHARMA SPRL","UCB PHARMA SA"], None),
 "CSL":           (["CSL BEHRING","CSL"], ["CSL BEHRING","CSL LIMITED"], None),
 "GRIFOLS":       (["GRIFOLS"], ["GRIFOLS SA"], None),
 "FERRING":       (["FERRING"], ["FERRING BV","FERRING INTERNATIONAL CENTER SA"], None),
 "CHIESI":        (["CHIESI"], ["CHIESI FARMACEUTICI SPA"], None),
 "GALDERMA":      (["GALDERMA"], ["GALDERMA SA","GALDERMA RESEARCH & DEVELOPMENT"], None),
 "LEO":           (["LEO PHARMA"], ["LEO PHARMA AS"], None),
 "KYOWA":         (["KYOWA"], ["KYOWA KIRIN CO LTD","KYOWA HAKKO KIRIN"], None),
 "MITSUBISHI":    (["MITSUBISHI","TANABE"], ["MITSUBISHI TANABE PHARMA CORP"], None),
 "SERVIER":       (["SERVIER"], ["LES LABORATOIRES SERVIER"], None),
 "ALMIRALL":      (["ALMIRALL"], ["ALMIRALL SA"], None),
 "MENARINI":      (["MENARINI"], ["A MENARINI"], None),
 "HENGRUI":       (["HENGRUI"], ["JIANGSU HENGRUI MEDICINE CO LTD"], None),
 "JAZZ":          (["JAZZ"], ["JAZZ PHARMACEUTICALS"], None),
 "ALKERMES":      (["ALKERMES"], ["ALKERMES PHARMA IRELAND"], None),
 "BIOMARIN":      (["BIOMARIN"], ["BIOMARIN PHARMACEUTICAL INC"], None),
 "SEAGEN":        (["SEAGEN","SEATTLE GENETICS"], ["SEAGEN INC","SEATTLE GENETICS INC"], None),
 "MODERNA":       (["MODERNA"], ["MODERNATX INC"], None),
 "BIONTECH":      (["BIONTECH"], ["BIONTECH SE"], None),
 "ALNYLAM":       (["ALNYLAM"], ["ALNYLAM PHARMACEUTICALS INC"], None),
 "IONIS":         (["IONIS","ISIS PHARMACEUTICALS"], ["IONIS PHARMACEUTICALS INC","ISIS PHARMACEUTICALS INC"], None),
 "EXELIXIS":      (["EXELIXIS"], ["EXELIXIS INC"], None),
 "NEUROCRINE":    (["NEUROCRINE"], ["NEUROCRINE BIOSCIENCES INC"], None),
 "SAGE":          (["SAGE THERAPEUTICS"], ["SAGE THERAPEUTICS INC"], None),
 "ACADIA":        (["ACADIA"], ["ACADIA PHARMACEUTICALS INC"], None),
 "INTERCEPT":     (["INTERCEPT"], ["INTERCEPT PHARMACEUTICALS INC"], None),
 "PTC":           (["PTC THERAPEUTICS"], ["PTC THERAPEUTICS INC"], None),
 "SAREPTA":       (["SAREPTA"], ["SAREPTA THERAPEUTICS INC"], None),
 "UNITED_THER":   (["UNITED THERAPEUTICS"], ["UNITED THERAPEUTICS CORP"], None),
 "HORIZON":       (["HORIZON THERAPEUTICS","HORIZON PHARMA"], ["HORIZON THERAPEUTICS","HORIZON PHARMA"], None),
 "ENDO":          (["ENDO"], ["ENDO PHARMACEUTICALS INC"], None),
 "MALLINCKRODT":  (["MALLINCKRODT"], ["MALLINCKRODT"], None),
 "VIATRIS":       (["VIATRIS","MYLAN"], ["MYLAN INC","VIATRIS INC"], None),
 "SUN":           (["SUN PHARMA"], ["SUN PHARMACEUTICAL INDUSTRIES LTD"], None),
 "DR_REDDYS":     (["DR REDDY"], ["DR REDDYS LABORATORIES LTD"], None),
 "ZOETIS":        (["ZOETIS"], ["ZOETIS"], None),
 "CIPLA":         (["CIPLA"], ["CIPLA LTD"], None),
 "RECORDATI":     (["RECORDATI"], ["RECORDATI SPA"], None),
 "ORION":         (["ORION CORPORATION","ORION PHARMA"], ["ORION CORP"], None),
 "VIFOR":         (["VIFOR"], ["VIFOR INTERNATIONAL AG"], None),
}

# longest keys first so "MERCK SHARP" wins before any shorter "MERCK" key
KEYS = sorted([(norm(k), g) for g, (ks, _, _) in GROUPS.items() for k in ks],
              key=lambda x: -len(x[0]))

# The registry often states the parent in prose:
#   "ArQule, Inc., a subsidiary of Merck Sharp & Dohme LLC"
#   "Genzyme, a Sanofi Company"
# That text is stripped by norm(), so the parent must be read from the RAW
# string first - otherwise every such subsidiary is treated as an independent
# firm and the parent's portfolio is understated.
PARENT = re.compile(
    r"(?:subsidiary|wholly[- ]owned subsidiary|affiliate|division|company|"
    r"business|member)\s+of\s+(.+?)(?:$|[,(])|[,\-–]\s*an?\s+(.+?)\s+"
    r"(?:company|group|business)\b", re.I)

def _match_keys(n):
    for key, grp in KEYS:
        if key and re.search(rf"\b{re.escape(key)}\b", n):
            return grp
    return ""

def assign(n, raw=""):
    # 1. explicit parent stated in prose wins
    if raw:
        for m in PARENT.finditer(raw):
            parent = next((g for g in m.groups() if g), "")
            g = _match_keys(norm(parent))
            if g: return g
    # 2. otherwise match the cleaned sponsor name
    return _match_keys(n)

tr = pd.read_parquet(os.path.join(OUT, "ctgov_trials.parquet"),
                     columns=["nct_id","lead_sponsor","lead_sponsor_class",
                              "is_industry","start_year","is_resolved"])
tr["sponsor_norm"] = tr.lead_sponsor.map(norm)
uniq = tr[["lead_sponsor","sponsor_norm"]].drop_duplicates()
uniq["corporate_group"] = [assign(n, raw) for n, raw in
                           zip(uniq.sponsor_norm, uniq.lead_sponsor)]
tr = tr.merge(uniq, on=["lead_sponsor","sponsor_norm"], how="left")

# unmatched sponsors fall back to their own normalised name as their own group
tr["corporate_group"] = tr.corporate_group.replace("", pd.NA).fillna(tr.sponsor_norm)
tr["matched_curated"] = [1 if assign(n, raw) else 0 for n, raw in
                         zip(tr.sponsor_norm, tr.lead_sponsor)]

p = os.path.join(OUT, "sponsor_assignee_map.parquet")
tr[["nct_id","lead_sponsor","sponsor_norm","corporate_group",
    "matched_curated","is_industry","start_year","is_resolved"]] \
  .to_parquet(p, index=False, compression="zstd")

# BigQuery search list
rows = []
for g, (keys, names, acq) in GROUPS.items():
    for nm in names:
        rows.append({"corporate_group": g, "assignee_name": nm,
                     "parent_from_year": (acq or {}).get(
                         next((k for k in (acq or {}) if norm(k) in norm(nm)), ""), "")})
bq = pd.DataFrame(rows)
bq.to_csv(os.path.join(OUT, "bigquery_assignee_names.csv"), index=False)
open(os.path.join(OUT, "bigquery_assignee_names.json"), "w").write(
    json.dumps(sorted(bq.assignee_name.unique().tolist()), indent=1))

f = tr[(tr.start_year.between(2008,2019)) & (tr.is_resolved==1) & (tr.is_industry==1)]
print(f"=== COVERAGE (industry trials in frame: {len(f):,}) ===")
print(f"  matched to a curated corporate group : {int(f.matched_curated.sum()):,} "
      f"({f.matched_curated.mean():.1%})")
print(f"  distinct curated groups present      : "
      f"{f[f.matched_curated==1].corporate_group.nunique()}")
print(f"  unmatched sponsors (own group)       : "
      f"{f[f.matched_curated==0].corporate_group.nunique():,}")
print(f"\nBigQuery search names: {bq.assignee_name.nunique()} "
      f"across {bq.corporate_group.nunique()} groups")
print(f"acquisition-dated subsidiaries: {int((bq.parent_from_year!='').sum())}")
print("\ntop groups by trial count:")
top = f[f.matched_curated==1].corporate_group.value_counts().head(12)
for g_, c in top.items(): print(f"   {c:5,}  {g_}")
