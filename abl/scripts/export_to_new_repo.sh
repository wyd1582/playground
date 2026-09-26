#!/usr/bin/env bash
# Export abl/ (with its full commit history) from the playground monorepo into a new, empty
# GitHub repository, as that repository's `main` branch. Run from anywhere inside the playground
# clone:   bash abl/scripts/export_to_new_repo.sh https://github.com/<you>/<new-repo>.git
# Safe to re-run: it rebuilds the split branch and pushes it again (fast-forward only).
set -euo pipefail

NEW_REMOTE="${1:?usage: export_to_new_repo.sh <new-repo-git-url> [source-branch]}"
SRC_BRANCH="${2:-claude/affectionate-franklin-ttwudk}"
TOP="$(git rev-parse --show-toplevel)"
cd "$TOP"

if [ -n "$(git status --porcelain -- abl)" ]; then
  echo "abl/ has uncommitted changes; commit or stash them first." >&2
  exit 1
fi

git fetch origin "$SRC_BRANCH"
echo "==> splitting abl/ out of origin/$SRC_BRANCH (keeps every commit that touched abl/)"
git branch -f abl-export "origin/$SRC_BRANCH"
SPLIT="$(git subtree split --prefix=abl abl-export)"
git branch -f abl-split "$SPLIT"
echo "==> split head: $(git log --oneline -n 1 abl-split)"

echo "==> pushing to $NEW_REMOTE as main"
git push "$NEW_REMOTE" "abl-split:refs/heads/main"
git branch -D abl-export >/dev/null
echo "Done. Next: clone the new repo and follow docs/DEPLOY.zh.md step 3."
