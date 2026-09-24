"""Parser, validator, unit checker and semantic hash for the restricted DSL (dsl/grammar.md)."""
from __future__ import annotations

import ast as _ast
from dataclasses import dataclass, field
from typing import Any

from common.hashing import sha256_json


class DSLError(ValueError):
    """Syntax / grammar / unit / causality violation — the candidate cannot be registered."""


class NeedOperator(DSLError):
    """The hypothesis needs an operator outside the grammar (Builder returns NEED_OPERATOR)."""


# available_at semantics for every field an operator may touch.  "birth" = known when the
# animal is registered (<= any selection_date); "label" = a phenotype whose own available_at
# is checked row by row; "external" = published prior, dated before the campaign.
FIELD_AVAILABILITY: dict[str, str] = {
    "animals.farm": "birth", "animals.line": "birth", "animals.sex": "birth", "animals.birth_t": "birth",
    "animals.sire": "birth", "animals.dam": "birth", "genotypes": "birth",
    "phenotypes.value": "label", "priors.*": "external", "markers.chrom": "external",
}

# name -> {arg: (type, domain-checker, unit)} ; domain-checker returns None or an error string
def _in(lo, hi, closed=True):
    def f(v):
        ok = (lo <= v <= hi) if closed else (lo < v <= hi)
        return None if ok else f"must be in {'[' if closed else '('}{lo}, {hi}]"
    return f


def _enum(*vals):
    return lambda v: None if v in vals else f"must be one of {vals}"


OPERATORS: dict[str, dict[str, Any]] = {
    "champion": {"args": {}, "fields": [], "status": "required"},
    "grm_weights": {"args": {"scheme": (str, _enum("uniform", "maf_inverse", "maf_power"), "-"),
                             "power": (float, _in(-1.0, 1.0), "-")},
                    "optional": {"power"}, "fields": ["genotypes"], "status": "implemented"},
    "region_weight": {"args": {"chrom": (int, lambda v: None if v >= 1 else "chrom >= 1", "-"),
                               "weight": (float, _in(0.0, 10.0), "-")},
                      "fields": ["genotypes", "markers.chrom"], "status": "implemented"},
    "qtl_prior": {"args": {"source": (str, lambda v: None, "-"), "weight": (float, _in(0.0, 10.0), "-")},
                  "fields": ["genotypes", "priors.*"], "status": "implemented"},
    "covariate": {"args": {"field": (str, _enum("farm", "line", "sex", "birth_t"), "categorical")},
                  "fields": ["animals.{field}"], "status": "implemented"},
    "blend_pedigree": {"args": {"w": (float, _in(0.0, 1.0), "fraction")},
                       "fields": ["animals.sire", "animals.dam"], "status": "implemented"},
    "dominance": {"args": {"w": (float, _in(0.0, 1.0, closed=False), "fraction")},
                  "fields": ["genotypes"], "status": "implemented"},
    "snp_subset": {"args": {"strategy": (str, _enum("random", "top_maf", "prior_list"), "-"),
                            "fraction": (float, _in(0.0, 1.0, closed=False), "fraction"),
                            "seed": (int, lambda v: None if v >= 0 else "seed >= 0", "-"),
                            "source": (str, lambda v: None, "-")},
                   "optional": {"seed", "source"}, "fields": ["genotypes"], "status": "implemented"},
    "lambda_scale": {"args": {"factor": (float, _in(0.2, 5.0), "-")}, "fields": [], "status": "implemented"},
    "multi_trait": {"args": {"traits": (list, lambda v: None, "-")}, "fields": ["phenotypes.value"], "status": "reserved"},
    "env_covariate": {"args": {"field": (str, lambda v: None, "-")}, "fields": ["environment.*"], "status": "reserved"},
}


@dataclass(frozen=True)
class Op:
    name: str
    kwargs: tuple[tuple[str, Any], ...]

    def get(self, k: str, default: Any = None) -> Any:
        return dict(self.kwargs).get(k, default)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kwargs": dict(self.kwargs)}

    def text(self) -> str:
        def fmt(v):
            if isinstance(v, float) and not isinstance(v, bool):
                return f"{float(f'{v:.10g}')!r}"
            return repr(v)
        return f"{self.name}(" + ", ".join(f"{k}={fmt(v)}" for k, v in self.kwargs) + ")"


@dataclass
class Program:
    ops: list[Op]
    source: str = ""
    fields: list[str] = field(default_factory=list)

    @property
    def operator_names(self) -> list[str]:
        return [o.name for o in self.ops if o.name != "champion"]

    def canonical(self) -> str:
        rest = sorted((o for o in self.ops if o.name != "champion"), key=lambda o: (o.name, o.kwargs))
        return " + ".join(["champion()"] + [o.text() for o in rest])


def _literal(node: _ast.AST) -> Any:
    if isinstance(node, _ast.Constant):
        return node.value
    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, _ast.USub) and isinstance(node.operand, _ast.Constant):
        return -node.operand.value
    if isinstance(node, (_ast.List, _ast.Tuple)):
        vals = [_literal(e) for e in node.elts]
        if not all(isinstance(v, str) for v in vals):
            raise DSLError("list arguments must contain strings only")
        return vals
    raise DSLError(f"only literal keyword arguments are allowed (got {type(node).__name__})")


def _calls(node: _ast.AST) -> list[_ast.Call]:
    if isinstance(node, _ast.BinOp) and isinstance(node.op, _ast.Add):
        return _calls(node.left) + _calls(node.right)
    if isinstance(node, _ast.Call):
        return [node]
    raise DSLError("expression must be champion() + op(...) + ...")


def parse(text: str) -> Program:
    text = " ".join(text.strip().split())
    try:
        tree = _ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise DSLError(f"syntax error: {e.msg}") from None
    ops: list[Op] = []
    for call in _calls(tree.body):
        if not isinstance(call.func, _ast.Name):
            raise DSLError("operators are plain names")
        if call.args:
            raise DSLError(f"{call.func.id}: positional arguments are not allowed")
        kwargs = tuple(sorted((kw.arg, _literal(kw.value)) for kw in call.keywords))
        ops.append(Op(call.func.id, kwargs))
    return Program(ops, source=text)


def validate(prog: Program, *, max_operators: int = 4, known_priors: set[str] | None = None,
             has_pedigree: bool = True) -> Program:
    """Grammar + units + causality. Raises DSLError / NeedOperator. Returns prog with fields filled."""
    if not prog.ops or prog.ops[0].name != "champion" or prog.ops[0].kwargs:
        raise DSLError("expression must start with champion()")
    names = [o.name for o in prog.ops]
    if names.count("champion") != 1:
        raise DSLError("exactly one champion()")
    if len(names) != len(set(names)):
        raise DSLError("each operator may appear at most once")
    if len(prog.ops) - 1 > max_operators:
        raise DSLError(f"more than {max_operators} operators")
    fields: list[str] = []
    for op in prog.ops:
        spec = OPERATORS.get(op.name)
        if spec is None:
            raise DSLError(f"unknown operator {op.name}")
        if spec["status"] == "reserved":
            raise NeedOperator(f"{op.name} is reserved; minimal spec required before use")
        args = spec["args"]
        optional = spec.get("optional", set())
        given = dict(op.kwargs)
        for k in given:
            if k not in args:
                raise DSLError(f"{op.name}: unknown argument {k}")
        for k, (typ, check, unit) in args.items():
            if k not in given:
                if k in optional:
                    continue
                raise DSLError(f"{op.name}: missing argument {k}")
            v = given[k]
            if typ is float and isinstance(v, bool):
                raise DSLError(f"{op.name}.{k}: bool is not a number")
            if typ is float and isinstance(v, int):
                v = float(v)
            if not isinstance(v, typ):
                raise DSLError(f"{op.name}.{k}: expected {typ.__name__}")
            err = check(v)
            if err:
                raise DSLError(f"{op.name}.{k} ({unit}) {err}")
        if op.name == "grm_weights" and given.get("scheme") == "maf_power" and "power" not in given:
            raise DSLError("grm_weights(scheme='maf_power') needs power")
        if op.name == "qtl_prior" and known_priors is not None and given["source"] not in known_priors:
            raise DSLError(f"qtl_prior: unknown prior source {given['source']!r}; known: {sorted(known_priors)}")
        if op.name == "snp_subset" and given.get("strategy") == "prior_list":
            if "source" not in given:
                raise DSLError("snp_subset(strategy='prior_list') needs source")
            if known_priors is not None and given["source"] not in known_priors:
                raise DSLError(f"snp_subset: unknown prior source {given['source']!r}")
        if op.name == "blend_pedigree" and not has_pedigree:
            raise DSLError("blend_pedigree needs a pedigree; this dataset declares none")
        for f in spec["fields"]:
            fields.append(f.format(**given) if "{" in f else f)
    # causality: every touched field must be knowable at selection_date
    for f in fields:
        key = f if f in FIELD_AVAILABILITY else next((k for k in FIELD_AVAILABILITY if k.endswith(".*") and f.startswith(k[:-1])), None)
        if key is None:
            raise DSLError(f"field {f} has no available_at semantics")
        if FIELD_AVAILABILITY[key] not in ("birth", "label", "external"):
            raise DSLError(f"field {f} is not available at selection_date")
    prog.fields = sorted(set(fields))
    return prog


def semantic_hash(prog: Program) -> str:
    """Order-independent hash; floats rounded so 0.30000001 == 0.3."""
    rest = sorted((o for o in prog.ops if o.name != "champion"), key=lambda o: (o.name, o.kwargs))
    return sha256_json([o.as_dict() for o in rest])


def data_declaration(prog: Program) -> list[dict[str, str]]:
    """Every field with its available_at semantics — the Builder's data declaration."""
    out = []
    for f in prog.fields:
        key = f if f in FIELD_AVAILABILITY else next(k for k in FIELD_AVAILABILITY if k.endswith(".*") and f.startswith(k[:-1]))
        out.append({"field": f, "available_at": FIELD_AVAILABILITY[key],
                    "note": {"birth": "known at registration, <= selection_date",
                             "label": "row-level available_at checked against cutoff",
                             "external": "published before campaign start"}[FIELD_AVAILABILITY[key]]})
    return out
