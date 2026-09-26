"""OPS.md C.1 — public data catalogue as data. ★ = use first. Network policy in this environment
allows only GitHub + PyPI, so only the two files already vendored in ../genomic-selection-pig/data are
reachable; everything else is listed with its intended ABL use and marked unavailable here."""
from __future__ import annotations

from pathlib import Path

from common import paths

_HERE = Path(__file__).resolve().parent.parent
# data/vendor/ ships with the project (so a standalone repo or Docker image is self-contained);
# the sibling genomic-selection-pig/data/ is the original location in the playground monorepo.
VENDORED = next((d for d in (_HERE / "data" / "vendor", _HERE.parent / "genomic-selection-pig" / "data")
                 if (d / "pig_cleveland_curated.rdata").exists()), _HERE / "data" / "vendor")

CATALOG: list[dict] = [
    dict(id="g2p_datasets", star=True, name="G2P Datasets (Genetics 2026)", kind="genotype+phenotype", species="60+ species", use="cross-species method benchmark", access="open",
         local=None, note="metadata + download scripts; Cleveland pig curated copy vendored from QuantGen/G2P-Datasets@a7bf58a"),
    dict(id="pig_cleveland_2012", star=True, name="Cleveland 2012 PIC pig data (G3)", kind="genotype+phenotype+EBV", species="pig", use="L1 champion and inner-loop battleground", access="open",
         local=str(VENDORED / "pig_cleveland_curated.rdata"), note="curated copy: 3,534 animals × 52,843 SNP, trait t1 only, no pedigree, no map, no dates"),
    dict(id="bglr_wheat", star=True, name="BGLR wheat", kind="genotype+phenotype", species="wheat", use="cross-species sanity", access="open (R package)",
         local=str(VENDORED / "wheat.RData"), note="599 lines × 1,279 DArT markers, 4 environments, A matrix"),
    dict(id="bglr_mice", star=True, name="BGLR mice", kind="genotype+phenotype", species="mouse", use="cross-species sanity", access="open (R package)", local=None, note="not vendored"),
    dict(id="cropgs_hub", star=True, name="CropGS-Hub (NAR 2024)", kind="genotype+phenotype", species="major crops", use="crop line", access="open", local=None, note="unreachable under this network policy"),
    dict(id="g2f", star=False, name="Genomes to Fields", kind="genotype+phenotype+environment", species="maize", use="G×E operator test bed", access="open", local=None, note="unreachable here"),
    dict(id="farmgtex", star=False, name="FarmGTEx (Pig/Cattle/ChickenGTEx)", kind="molecular QTL", species="pig, cattle, chicken", use="biological-prior operator (eQTL-weighted SNP); chip content design", access="open", local=None, note="unreachable here"),
    dict(id="animal_qtldb", star=False, name="Animal QTLdb", kind="QTL/association", species="livestock", use="Geneticist retrieval; region priors", access="open", local=None, note="unreachable here"),
    dict(id="horvath_methylation", star=False, name="Horvath pan-mammalian methylation (GEO)", kind="methylation+age", species="hundreds of mammals", use="L2 epigenetic clock probe screening", access="open", local=None, note="unreachable here"),
    dict(id="cdcb_interbull", star=False, name="CDCB / Interbull", kind="public bull evaluations", species="dairy cattle", use="label substitute for cattle line", access="open (aggregated)", local=None, note="unreachable here"),
    dict(id="sheep_hapmap", star=False, name="Sheep HapMap / NSIP", kind="genotype / EBV", species="sheep", use="species expansion", access="open", local=None, note="unreachable here"),
    dict(id="cncb_ngdc", star=False, name="CNCB-NGDC (GSA, GVM)", kind="sequence", species="Chinese local breeds", use="low-density panel design; genetic-resource narrative", access="open (partly by application)", local=None, note="unreachable here"),
    dict(id="cn_swine_eval", star=False, name="National swine genetic evaluation centre", kind="summary rankings", species="pig", use="China market calibration; competitor baseline", access="public summary", local=None, note="unreachable here"),
    dict(id="chicken_pairs", star=False, name="Chicken genotype–phenotype pairs", kind="—", species="chicken", use="simulation + customer data only", access="scarce", local=None, note="scarce"),
    dict(id="aquaculture", star=False, name="Aquaculture (salmon, tilapia; shrimp ~none)", kind="—", species="aquatic", use="—", access="scarce", local=None, note="scarce"),
]


def available_locally() -> list[dict]:
    out = []
    for c in CATALOG:
        if c["local"] and Path(c["local"]).exists():
            paths.assert_not_holdout(c["local"])
            out.append(c)
    return out
