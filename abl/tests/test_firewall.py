"""Holdout firewall (CLAUDE.md rule 1): static grep + runtime checks."""
import re
from pathlib import Path

import pytest

from common import paths

PROJECT = Path(__file__).resolve().parent.parent
AGENT_SIDE_DIRS = ["agents", "dsl", "engine", "genoframe", "sim", "campaigns", "dataio"]
# the only files allowed to spell the sealed directory's name on the agent side:
ALLOWED = {"genoframe/seal.py", "campaigns/final_table.py", "agents/firewall.py"}


def test_agent_side_source_never_opens_the_sealed_directory():
    """No agent-side module may resolve, open or name the sealed directory as a path. Identifiers such
    as the policy flag or the guard function are fine; a path string or holdout_dir() call is not."""
    pattern = re.compile(r"hold" + r"out_dir\(|['\"/]hold" + r"out[/'\"]|read_sealed_for_final_table|pathlib.*hold" + r"out", re.I)
    offenders = []
    for d in AGENT_SIDE_DIRS:
        for f in (PROJECT / d).rglob("*.py"):
            rel = str(f.relative_to(PROJECT))
            if rel in ALLOWED:
                continue
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{rel}:{i}: {line.strip()[:80]}")
    assert not offenders, offenders


def test_only_gates_call_transition():
    offenders = []
    for f in PROJECT.rglob("*.py"):
        rel = str(f.relative_to(PROJECT))
        if rel.startswith((".venv", "gates/", "registry/", "tests/")):
            continue
        if ".transition(" in f.read_text():
            offenders.append(rel)
    assert not offenders, offenders


def test_dashboard_never_imports_agent_stack():
    import ast
    forbidden = {"agents", "engine", "gates", "campaigns", "dsl", "sim", "genoframe", "dataio"}
    for f in (PROJECT / "dashboard").rglob("*.py"):
        if "tests" in f.parts:
            continue
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            bad = set(names) & forbidden
            assert not bad, f"{f.name} imports {bad}"


def test_path_guard_and_prompt_scanner(abl_root):
    sealed = abl_root / "hold" "out" / "x.parquet"
    sealed.parent.mkdir(exist_ok=True); sealed.write_text("x")
    with pytest.raises(PermissionError):
        paths.assert_not_holdout(sealed)
    paths.assert_not_holdout(abl_root / "data" / "ok.csv")
    from agents import firewall
    (abl_root / "registry").mkdir(exist_ok=True)
    import json
    (abl_root / "registry" / "holdout_seal.json").write_text(json.dumps({"sim": {"digests": {"a": "deadbeef" * 8}}}))
    assert firewall.scan_prompt("please load hold" "out/gen5.parquet")
    assert firewall.scan_prompt("digest " + "deadbeef" * 8)
    assert not firewall.scan_prompt("champion() + dominance(w=0.2)")
    with pytest.raises(firewall.FirewallError):
        firewall.enforce("the hold" "out generation")
