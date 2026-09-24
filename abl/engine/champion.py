"""The frozen champion: (ss)GBLUP with uniform marker weights and the campaign's REML λ."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from common.hashing import sha256_json


@dataclass
class ChampionConfig:
    name: str = "ssGBLUP_uniform"
    blend_w: float = 0.0                 # 0 without a pedigree; ssGBLUP-style blended G otherwise
    covariates: list[str] = field(default_factory=list)
    lam: float = 1.0
    h2: float = 0.5
    ridge_eps: float = 0.01
    trait: str = ""
    frozen_on_split: str = ""

    @property
    def champion_id(self) -> str:
        return "champ_" + sha256_json(asdict(self))[:10]

    def as_dict(self) -> dict:
        return dict(asdict(self), champion_id=self.champion_id)


def freeze_champion(evaluator, split, *, blend_w: float, covariates: list[str]) -> ChampionConfig:
    """REML once on the first split's training data, then never again (research-to-live parity)."""
    cfg = ChampionConfig(blend_w=blend_w, covariates=list(covariates), trait=evaluator.trait,
                         frozen_on_split=split.split_id)
    evaluator.champion = cfg
    est = evaluator.reml_on_split(split)
    cfg.lam, cfg.h2 = float(est["lam"]), float(est["h2"])
    evaluator.champion = cfg
    return cfg
