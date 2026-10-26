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
import os, re, sys, json, unicodedata
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
    # Fold accents to ASCII BEFORE the [^A-Z0-9 ] substitution below. That
    # substitution replaces any character outside A-Z0-9 with a space, so
    # without this step an accented letter is deleted rather than converted:
    # Grunenthal arrived as "GR NENTHAL", Dompe as "DOMP" and Abello as
    # "ABELL". Those strings match nothing in assignee_harmonized, so the firm
    # silently lost its entire patent portfolio. NFKD splits a letter from its
    # diacritic and the ascii encode drops only the diacritic.
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
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

 # ---- expansion of 2026-10-25: the 137 largest unmatched industry sponsors,
 # 2323 trials. Each key is a distinctive token, or a two-word phrase taken from
 # the RAW sponsor string where the normalised name is an ordinary word, a
 # place, a surname, a chemical term or a conglomerate stem. ORION showed what
 # a bare brand word does: it matched Orion Energy Systems, Orion Engineered
 # Carbons, Thermo Orion and fifteen more. TRIS and SPECTRUM would be worse.
 "SANTEN":          (["SANTEN"], ["SANTEN INC"], None),
 "BEIGENE":         (["BEIGENE"], ["BEIGENE"], None),
 "PEARL":           (["PEARL THERAPEUTICS"], ["PEARL THERAPEUTICS INC"], None),
 "HANMI":           (["HANMI"], ["HANMI PHARMACEUTICAL COMPANY LIMITED"], None),
 "REPROS":          (["REPROS"], ["REPROS THERAPEUTICS INC"], None),
 "LEXICON":         (["LEXICON"], ["LEXICON PHARMACEUTICALS"], None),
 "LAKEFRONT_BIOTHERAPEUTICS": (["LAKEFRONT"], ["LAKEFRONT BIOTHERAPEUTICS NV"], None),
 "PACIRA":          (["PACIRA"], ["PACIRA PHARMACEUTICALS INC"], None),
 "MUNDIPHARMA":     (["MUNDIPHARMA"], ["MUNDIPHARMA RESEARCH LIMITED"], None),
 "IMMUNITYBIO":     (["IMMUNITYBIO"], ["IMMUNITYBIO INC"], None),
 "EUROFARMA_LABORATORIOS": (["EUROFARMA"], ["EUROFARMA LABORATORIOS S A"], None),
 "MERZ":            (["MERZ PHARMACEUTICALS"], ["MERZ PHARMACEUTICALS GMBH"], None),
 "SHIONOGI":        (["SHIONOGI"], ["SHIONOGI"], None),
 "SUPERNUS":        (["SUPERNUS"], ["SUPERNUS PHARMACEUTICALS INC"], None),
 "SPECTRUM":        (["SPECTRUM PHARMACEUTICALS"], ["SPECTRUM PHARMACEUTICALS INC"], None),
 "HELSINN":         (["HELSINN"], ["HELSINN THERAPEUTICS U S INC"], None),
 "BRAINTREE":       (["BRAINTREE"], ["BRAINTREE LABORATORIES"], None),
 # D-Pharm Ltd is dropped: norm() reduces "D-Pharm" to the bare word PHARM,
 # and prep_12 then folds PHARM to the PHARMA synonym, so the group claimed
 # every harmonized name containing PHARMA (THERAVANCE BIOPHARMA, MALLINCKRODT
 # PHARMA IP, K D PHARMA BEXBACH). 24 trials go unmeasured instead.
 "VYNE":            (["VYNE THERAPEUTICS"], ["VYNE THERAPEUTICS INC"], None),
 "CHONG_KUN_DANG":  (["DANG"], ["CHONG KUN DANG PHARMACEUTICAL"], None),
 "ULTRAGENYX":      (["ULTRAGENYX"], ["ULTRAGENYX PHARMACEUTICAL INC"], None),
 "YUHAN":           (["YUHAN"], ["YUHAN CORPORATION"], None),
 "AVID_RADIOPHARM": (["AVID RADIOPHARM"], ["AVID RADIOPHARMACEUTICALS"], None),
 "MARUHO":          (["MARUHO"], ["MARUHO CO LTD"], None),
 "AERIE":           (["AERIE"], ["AERIE PHARMACEUTICALS"], None),
 "PIERRE_FABRE_MEDICAMENT": (["FABRE"], ["PIERRE FABRE MEDICAMENT"], None),
 "ONO":             (["ONO PHARMA"], ["ONO PHARMA USA INC"], None),
 "ACLARIS":         (["ACLARIS"], ["ACLARIS THERAPEUTICS INC"], None),
 "KYNTRA_BIO":      (["KYNTRA"], ["KYNTRA BIO"], None),
 "DR_FALK":         (["DR FALK"], ["DR FALK PHARMA GMBH"], None),
 "MEDY_TOX":        (["MEDY TOX"], ["MEDY TOX"], None),
 "GRUNENTHAL":      (["GRUNENTHAL"], ["GRUNENTHAL GMBH"], None),
 "BIOCRYST":        (["BIOCRYST"], ["BIOCRYST PHARMACEUTICALS"], None),
 "BIOCAD":          (["BIOCAD"], ["BIOCAD"], None),
 "IDORSIA":         (["IDORSIA"], ["IDORSIA PHARMACEUTICALS LTD"], None),
 "OPKO":            (["OPKO"], ["OPKO HEALTH INC"], None),
 "PADAGIS":         (["PADAGIS"], ["PADAGIS LLC"], None),
 "CYTOKINETICS":    (["CYTOKINETICS"], ["CYTOKINETICS"], None),
 "OTONOMY":         (["OTONOMY"], ["OTONOMY INC"], None),
 "LG_LIFE":         (["LG LIFE"], ["LG LIFE SCIENCES"], None),
 "DEXA_MEDICA":     (["DEXA MEDICA"], ["DEXA MEDICA GROUP"], None),
 "NOBELPHARMA":     (["NOBELPHARMA"], ["NOBELPHARMA"], None),
 "ESPERION":        (["ESPERION"], ["ESPERION THERAPEUTICS INC"], None),
 "XOMA":            (["XOMA US"], ["XOMA US LLC"], None),
 "DAEWOONG":        (["DAEWOONG"], ["DAEWOONG PHARMACEUTICAL CO LTD"], None),
 "NIHON":           (["NIHON"], ["NIHON PHARMACEUTICAL CO LTD"], None),
 "MELINTA":         (["MELINTA"], ["MELINTA THERAPEUTICS INC"], None),
 "PHARMACOSMOS":    (["PHARMACOSMOS"], ["PHARMACOSMOS A S"], None),
 "BIAL_PORTELA":    (["BIAL"], ["BIAL PORTELA C S A"], None),
 "ACHE_LABORATORIOS_FARMACEUTICOS": (["FARMACEUTICOS"], ["ACHE LABORATORIOS FARMACEUTICOS S A"], None),
 "AMPHASTAR":       (["AMPHASTAR"], ["AMPHASTAR PHARMACEUTICALS INC"], None),
 "DOMP":            (["DOMP"], ["DOMPE FARMACEUTICI S P A"], None),
 "PURDUE":          (["PURDUE PHARMA"], ["PURDUE PHARMA LP"], None),
 "KISSEI":          (["KISSEI"], ["KISSEI PHARMACEUTICAL CO LTD"], None),
 "AKEBIA":          (["AKEBIA"], ["AKEBIA THERAPEUTICS"], None),
 "BORYUNG":         (["BORYUNG"], ["BORYUNG PHARMACEUTICAL CO LTD"], None),
 "KARYOPHARM":      (["KARYOPHARM"], ["KARYOPHARM THERAPEUTICS INC"], None),
 "TG":              (["TG THERAPEUTICS"], ["TG THERAPEUTICS INC"], None),
 "HUTCHISON_MEDIPHARMA": (["HUTCHISON"], ["HUTCHISON MEDIPHARMA LIMITED"], None),
 "VANDA":           (["VANDA PHARMACEUTICALS"], ["VANDA PHARMACEUTICALS"], None),
 "BIODELIVERY":     (["BIODELIVERY"], ["BIODELIVERY SCIENCES INTERNATIONAL"], None),
 "RIGEL":           (["RIGEL PHARMACEUTICALS"], ["RIGEL PHARMACEUTICALS"], None),
 "CARA":            (["CARA THERAPEUTICS"], ["CARA THERAPEUTICS INC"], None),
 "OCTAPHARMA":      (["OCTAPHARMA"], ["OCTAPHARMA"], None),
 "ALDEYRA":         (["ALDEYRA"], ["ALDEYRA THERAPEUTICS INC"], None),
 "CHIA_TAI_TIANQING": (["TIANQING"], ["CHIA TAI TIANQING PHARMACEUTICAL GROUP CO LTD"], None),
 "NEKTAR":          (["NEKTAR"], ["NEKTAR THERAPEUTICS"], None),
 "DEBIOPHARM":      (["DEBIOPHARM"], ["DEBIOPHARM INTERNATIONAL SA"], None),
 "NEWLINK_GENETICS": (["NEWLINK"], ["NEWLINK GENETICS CORPORATION"], None),
 "ARDEA":           (["ARDEA BIOSCIENCES"], ["ARDEA BIOSCIENCES INC"], None),
 "ACORDA":          (["ACORDA"], ["ACORDA THERAPEUTICS"], None),
 "ZEALAND":         (["ZEALAND PHARMA"], ["ZEALAND PHARMA"], None),
 "MIRUM":           (["MIRUM PHARMACEUTICALS"], ["MIRUM PHARMACEUTICALS INC"], None),
 "IRONWOOD":        (["IRONWOOD"], ["IRONWOOD PHARMACEUTICALS INC"], None),
 "INSYS":           (["INSYS"], ["INSYS THERAPEUTICS INC"], None),
 "XERIS":           (["XERIS PHARMACEUTICALS"], ["XERIS PHARMACEUTICALS"], None),
 "HERON":           (["HERON THERAPEUTICS"], ["HERON THERAPEUTICS"], None),
 "AMICUS":          (["AMICUS"], ["AMICUS THERAPEUTICS"], None),
 "PHARMAMAR":       (["PHARMAMAR"], ["PHARMAMAR"], None),
 "INNOVENT_BIOLOGICS": (["INNOVENT"], ["INNOVENT BIOLOGICS SUZHOU CO LTD"], None),
 "JW":              (["JW PHARMACEUTICAL"], ["JW PHARMACEUTICAL"], None),
 "SK_LIFE":         (["SK LIFE"], ["SK LIFE SCIENCE INC"], None),
 "IMPAX":           (["IMPAX"], ["IMPAX LABORATORIES LLC"], None),
 "INDIVIOR":        (["INDIVIOR"], ["INDIVIOR INC"], None),
 "INNOCOLL":        (["INNOCOLL"], ["INNOCOLL"], None),
 "SECURABIO":       (["SECURABIO"], ["SECURABIO"], None),
 "STEALTH_BIOTHERAPEUTICS": (["BIOTHERAPEUTICS"], ["STEALTH BIOTHERAPEUTICS INC"], None),
 "CAN_FITE":        (["FITE"], ["CAN FITE BIOPHARMA"], None),
 "IROKO":           (["IROKO"], ["IROKO PHARMACEUTICALS LLC"], None),
 "TAIWAN_LIPOSOME": (["LIPOSOME"], ["TAIWAN LIPOSOME COMPANY"], None),
 "TAIHO":           (["TAIHO"], ["TAIHO PHARMACEUTICAL CO LTD"], None),
 "SUZHOU_ZELGEN":   (["ZELGEN"], ["SUZHOU ZELGEN BIOPHARMACEUTICALS CO LTD"], None),
 "NORGINE":         (["NORGINE"], ["NORGINE"], None),
 "ANTHERA":         (["ANTHERA"], ["ANTHERA PHARMACEUTICALS"], None),
 "ALK_ABELL":       (["ABELL"], ["ALK ABELLO A S"], None),
 "TALPHERA":        (["TALPHERA"], ["TALPHERA INC"], None),
 "TRIS":            (["TRIS PHARMA"], ["TRIS PHARMA INC"], None),
 "TONIX":           (["TONIX PHARMACEUTICALS"], ["TONIX PHARMACEUTICALS INC"], None),
 "CUMBERLAND":      (["CUMBERLAND"], ["CUMBERLAND PHARMACEUTICALS"], None),
 "TRAWS":           (["TRAWS"], ["TRAWS PHARMA INC"], None),
 "HANLIM_PHARM":    (["HANLIM"], ["HANLIM PHARM CO LTD"], None),
 "ACERTA":          (["ACERTA"], ["ACERTA PHARMA BV"], None),
 "GLENMARK_INDIA":  (["GLENMARK"], ["GLENMARK PHARMACEUTICALS LTD INDIA"], None),
 "CHELSEA":         (["CHELSEA THERAPEUTICS"], ["CHELSEA THERAPEUTICS"], None),
 "TARGACEPT":       (["TARGACEPT"], ["TARGACEPT INC"], None),
 "MATI":            (["MATI"], ["MATI THERAPEUTICS INC"], None),
 "THERAVANCE":      (["THERAVANCE"], ["THERAVANCE BIOPHARMA"], None),
 "THROMBOGENICS":   (["THROMBOGENICS"], ["THROMBOGENICS"], None),
 "KYTHERA":         (["KYTHERA"], ["KYTHERA BIOPHARMACEUTICALS"], None),
 "TAIHO_ONCOLOGY":  (["TAIHO"], ["TAIHO ONCOLOGY INC"], None),
 "RADIUS":          (["RADIUS PHARMACEUTICALS"], ["RADIUS PHARMACEUTICALS INC"], None),
 "IBSA_INSTITUT":   (["IBSA INSTITUT"], ["IBSA INSTITUT BIOCHIMIQUE SA"], None),
 "REVANCE":         (["REVANCE"], ["REVANCE THERAPEUTICS INC"], None),
 "ASAHI_KASEI":     (["KASEI"], ["ASAHI KASEI PHARMA AMERICA CORPORATION"], None),
 "AROG":            (["AROG PHARMACEUTICALS"], ["AROG PHARMACEUTICALS INC"], None),
 "ARDELYX":         (["ARDELYX"], ["ARDELYX"], None),
 "SWEDISH_ORPHAN_BIOVITRUM": (["ORPHAN"], ["SWEDISH ORPHAN BIOVITRUM"], None),
 "OCULAR_THERAPEUTIX": (["THERAPEUTIX"], ["OCULAR THERAPEUTIX INC"], None),
 "LABORATOIRES_THEA": (["THEA"], ["LABORATOIRES THEA"], None),
 "ARENA":           (["ARENA PHARMACEUTICALS"], ["ARENA PHARMACEUTICALS"], None),
 "ITALFARMACO":     (["ITALFARMACO"], ["ITALFARMACO"], None),
 "SK_CHEMICALS":    (["SK CHEMICALS"], ["SK CHEMICALS CO LTD"], None),
 "MUNDIPHARMA_KG":  (["MUNDIPHARMA"], ["MUNDIPHARMA RESEARCH GMBH & CO KG"], None),
 "AMAG":            (["AMAG PHARMACEUTICALS"], ["AMAG PHARMACEUTICALS INC"], None),
 "CLOVIS_ONCOLOGY": (["ONCOLOGY"], ["CLOVIS ONCOLOGY INC"], None),
 "AZIDUS_BRASIL":   (["AZIDUS"], ["AZIDUS BRASIL"], None),
 "RESILIENT":       (["RESILIENT PHARMACEUTICALS"], ["RESILIENT PHARMACEUTICALS"], None),
 "AVEO":            (["AVEO PHARMACEUTICALS"], ["AVEO PHARMACEUTICALS INC"], None),
 "INTRA_CELLULAR_THERAPIES": (["CELLULAR"], ["INTRA CELLULAR THERAPIES INC"], None),
 "ARROWHEAD":       (["ARROWHEAD"], ["ARROWHEAD PHARMACEUTICALS"], None),
 "PHARMAAND":       (["PHARMAAND"], ["PHARMAAND GMBH"], None),
 "PORTOLA":         (["PORTOLA"], ["PORTOLA PHARMACEUTICALS"], None),
 "PHILOGEN":        (["PHILOGEN"], ["PHILOGEN S P A"], None),
 "SYMPHOGEN":       (["SYMPHOGEN"], ["SYMPHOGEN A S"], None),
 "LABORATORIOS_SOPHIA_DE": (["SOPHIA"], ["LABORATORIOS SOPHIA S A DE C V"], None),

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
