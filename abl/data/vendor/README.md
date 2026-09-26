# data/vendor — public datasets shipped with ABL

| file | source | sha256 (prefix) | notes |
|---|---|---|---|
| `pig_cleveland_curated.rdata` | Cleveland et al. 2012 (G3), curated copy from `QuantGen/G2P-Datasets@a7bf58a` `Datasets/00070_PigDataPICG3/curated_geno_pheno_map.rdata` | `9968d60791971d9b` | 3,534 animals × 52,843 SNP, trait t1 only, no pedigree, no map, no dates |
| `wheat.RData` | BGLR wheat, `gdlc/BGLR-R@de839cf` `data/wheat.RData` | `8710523389007dd8` | 599 lines × 1,279 DArT markers, 4 environments, A matrix |

Both are public research data. They are vendored so the project runs offline and inside a
Docker image without network access. `dataio/catalog.py` looks here first.
