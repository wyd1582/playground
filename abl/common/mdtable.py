from __future__ import annotations

import pandas as pd


def md_table(df: pd.DataFrame, floatfmt: str = ".4g") -> str:
    """Minimal GitHub-markdown table (no tabulate dependency)."""
    if df is None or len(df) == 0:
        return "(empty)"
    cols = [str(c) for c in df.columns]

    def fmt(v):
        if v is None or (isinstance(v, float) and v != v):
            return ""
        if isinstance(v, float):
            return f"{v:{floatfmt}}"
        return str(v)

    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in r.values) + " |")
    return "\n".join(lines)
