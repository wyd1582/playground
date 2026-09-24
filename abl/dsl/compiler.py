"""Compile a validated Program into a ModelSpec the engine executes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ast import Program, data_declaration, semantic_hash


@dataclass
class ModelSpec:
    dsl_text: str
    semantic_hash: str
    operators: list[dict[str, Any]]
    marker_weight_ops: list[dict[str, Any]] = field(default_factory=list)   # grm_weights / region_weight / qtl_prior
    subset: dict[str, Any] | None = None
    covariates: list[str] = field(default_factory=list)
    blend_w: float = 0.0
    dominance_w: float = 0.0
    lambda_factor: float = 1.0
    fields: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_champion(self) -> bool:
        return not self.operators


def compile_program(prog: Program) -> ModelSpec:
    spec = ModelSpec(dsl_text=prog.canonical(), semantic_hash=semantic_hash(prog),
                     operators=[o.as_dict() for o in prog.ops if o.name != "champion"],
                     fields=data_declaration(prog))
    for op in prog.ops:
        kw = dict(op.kwargs)
        if op.name in ("grm_weights", "region_weight", "qtl_prior"):
            spec.marker_weight_ops.append({"name": op.name, **kw})
        elif op.name == "snp_subset":
            spec.subset = dict(kw)
        elif op.name == "covariate":
            spec.covariates.append(kw["field"])
        elif op.name == "blend_pedigree":
            spec.blend_w = float(kw["w"])
        elif op.name == "dominance":
            spec.dominance_w = float(kw["w"])
        elif op.name == "lambda_scale":
            spec.lambda_factor = float(kw["factor"])
    return spec
