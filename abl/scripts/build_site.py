"""make site — build the static landing site for Vercel into site/dist/ (stdlib only).

Copies the user manuals, design docs, reports and screenshots, and writes a bilingual
index.html plus a markdown viewer page. Markdown is rendered in the browser (marked.js from
jsDelivr), so the build needs nothing but Python 3. ABL_APP_URL (the dashboard's public URL)
is injected into the landing page; set it in Vercel's environment variables.
"""
from __future__ import annotations

import html
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site"
DIST = SRC / "dist"
DOCS = ["USER_MANUAL.zh.md", "USER_MANUAL.md", "DEPLOY.zh.md", "DEPLOY.md", "DESIGN.md", "OPS.md"]
REPORTS = ["sim_controls.md", "scorecard.md", "final_holdout_sim.md", "BreedingPackage_pig_cleveland.md",
           "digest_example.zh.md", "digest_example.md"]
IMAGES = ["dashboard_full_zh.png", "dashboard_full.png", "dashboard_explain_candidate.png"]


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "docs").mkdir(parents=True)
    (DIST / "reports").mkdir()
    (DIST / "img").mkdir()
    for f in DOCS:
        if (ROOT / "docs" / f).exists():
            shutil.copy(ROOT / "docs" / f, DIST / "docs" / f)
    for f in REPORTS:
        if (ROOT / "reports" / f).exists():
            shutil.copy(ROOT / "reports" / f, DIST / "reports" / f)
    for f in IMAGES:
        if (ROOT / "reports" / f).exists():
            shutil.copy(ROOT / "reports" / f, DIST / "img" / f)
    app_url = os.environ.get("ABL_APP_URL", "").strip()
    for page in ("index.html", "view.html", "style.css"):
        text = (SRC / page).read_text(encoding="utf-8")
        text = text.replace("__ABL_APP_URL__", html.escape(app_url or "#"))
        text = text.replace("__ABL_APP_URL_JSON__", json.dumps(app_url))
        (DIST / page).write_text(text, encoding="utf-8")
    print(f"site built → {DIST} (app url: {app_url or 'not set'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
