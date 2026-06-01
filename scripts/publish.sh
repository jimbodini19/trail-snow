#!/usr/bin/env bash
# Regenerate the v2 report and stage it for GitHub Pages.
#
# Usage:
#   ./scripts/publish.sh            # rebuild docs/index.html
#   ./scripts/publish.sh --push     # also commit + push to origin
#
# Pages is configured to serve from /docs on main, so a push deploys.

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "no .venv found. run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e ."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

mkdir -p docs
python -m trailsnow.v2 --all --report docs/index.html

# Tiny no-jekyll marker so GitHub Pages doesn't strip underscore files.
touch docs/.nojekyll

echo
echo "wrote docs/index.html"
echo "open it locally with: open docs/index.html"

if [[ "${1:-}" == "--push" ]]; then
  git add docs/index.html docs/.nojekyll
  git commit -m "report: refresh $(date +%Y-%m-%d)"
  git push origin main
  echo "pushed. Pages will redeploy in ~30s."
fi
