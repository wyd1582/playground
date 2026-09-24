"""JSON schemas for structured agent outputs (used as output_config.format with the SDK)."""
from __future__ import annotations

GENETICIST = {
    "type": "object",
    "properties": {
        "mechanism": {"type": "string"},
        "direction": {"type": "string"},
        "operator_plan": {"type": "string", "description": "ABL DSL expression per dsl/grammar.md"},
        "falsifiers": {"type": "array", "items": {"type": "string"}},
        "expected_gain": {"type": "object", "properties": {"delta_oos": {"type": "number"}, "dispersion_b": {"type": "number"}},
                          "required": ["delta_oos", "dispersion_b"], "additionalProperties": False},
        "novelty_check": {"type": "string"},
        "source_refs": {"type": "array", "items": {"type": "string"}},
        "mechanism_cluster": {"type": "string"},
    },
    "required": ["mechanism", "direction", "operator_plan", "falsifiers", "expected_gain", "novelty_check", "source_refs", "mechanism_cluster"],
    "additionalProperties": False,
}

BUILDER = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["OK", "NEED_OPERATOR"]},
        "dsl": {"type": "string"},
        "data_declaration": {"type": "array", "items": {"type": "object", "properties": {
            "field": {"type": "string"}, "available_at": {"type": "string"}, "note": {"type": "string"}},
            "required": ["field", "available_at", "note"], "additionalProperties": False}},
        "tests": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                                             "required": ["name", "description"], "additionalProperties": False}},
        "thesis_to_code": {"type": "string"},
        "operator_spec": {"type": "string"},
    },
    "required": ["status", "dsl", "data_declaration", "tests", "thesis_to_code", "operator_spec"],
    "additionalProperties": False,
}

CRITIC = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "RETURN_TO_BUILDER", "REJECT"]},
        "leak_type": {"type": "array", "items": {"type": "string", "enum": ["temporal", "relatedness", "structure", "thesis_code", "dispersion", "plan"]}},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "file": {"type": "string"}, "line": {"type": "string"}, "field": {"type": "string"}, "note": {"type": "string"}},
            "required": ["file", "line", "field", "note"], "additionalProperties": False}},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "leak_type", "evidence", "rationale"],
    "additionalProperties": False,
}

ANALYST = {
    "type": "object",
    "properties": {
        "disposition_summary": {"type": "string"},
        "diagnosis": {"type": "string"},
        "limiting_gate": {"type": "string"},
        "next_experiment": {"type": "object", "properties": {"mechanism": {"type": "string"}, "dsl": {"type": "string"}, "rationale": {"type": "string"}},
                            "required": ["mechanism", "dsl", "rationale"], "additionalProperties": False},
        "evaluation_section": {"type": "string"},
        "mechanism_cluster": {"type": "string"},
    },
    "required": ["disposition_summary", "diagnosis", "limiting_gate", "next_experiment", "evaluation_section", "mechanism_cluster"],
    "additionalProperties": False,
}
