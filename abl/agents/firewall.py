"""Information firewall (DESIGN.md §3): nothing from holdout/ may appear in any prompt, memory file,
retrieval index or reward. This module never opens holdout/; it only knows digests from the seal
record kept in registry/ and refuses any prompt that mentions the sealed directory or a digest."""
from __future__ import annotations

import json
import re

from common import paths

_SEALED_DIR_TOKEN = "hold" + "out/"


class FirewallError(RuntimeError):
    pass


def sealed_digests() -> set[str]:
    f = paths.holdout_seal_file()
    if not f.exists():
        return set()
    seal = json.loads(f.read_text())
    out: set[str] = set()
    for entry in seal.values():
        out.update(entry.get("digests", {}).values())
    return out


def scan_prompt(text: str) -> list[str]:
    """Return the list of violations found in an agent input (empty = clean)."""
    hits: list[str] = []
    if _SEALED_DIR_TOKEN in text or re.search(r"\bhold" + r"out\b", text, flags=re.I):
        hits.append("mentions sealed directory")
    for d in sealed_digests():
        if d in text or d[:16] in text:
            hits.append(f"contains sealed digest {d[:12]}…")
    return hits


def enforce(text: str) -> None:
    hits = scan_prompt(text)
    if hits:
        raise FirewallError("; ".join(hits))
