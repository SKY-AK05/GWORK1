#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPANY="${COMPANY:-ORCHVATE}"
COUNTRY="${COUNTRY:-India}"
DEPTH="${DEPTH:-comprehensive}"
OUTPUT_DIR="${OUTPUT_DIR:-reports/orchvate-india}"
MEMORY_DB="${COMPANY_MEMORY_DB:-$HOME/.cache/deepresearch/company_intelligence.sqlite3}"

cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env in repository root. Copy the configured local .env there first." >&2
  exit 2
fi
if ! git check-ignore -q .env; then
  echo ".env is not ignored by Git; refusing to continue." >&2
  exit 2
fi

# Detect python in venv (Linux/macOS vs Windows Git Bash)
if [[ -f .venv/bin/python ]]; then
  VENV_PY=".venv/bin/python"
  VENV_ACT=".venv/bin/activate"
elif [[ -f .venv/Scripts/python.exe ]]; then
  VENV_PY=".venv/Scripts/python.exe"
  VENV_ACT=".venv/Scripts/activate"
else
  echo "Missing .venv. Create it first." >&2
  exit 2
fi

if [[ -f "$VENV_ACT" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_ACT"
fi

"$VENV_PY" - <<'PY'
import os
from dotenv import load_dotenv
load_dotenv()
required = ("AI_MODEL", "AZURE_AI_API_KEY", "AZURE_AI_ENDPOINT", "AZURE_AI_DEPLOYMENT", "COMPANIES_HOUSE_API_KEY")
missing = [key for key in required if not os.getenv(key)]
for key in required:
    print(f"{key}={'set' if os.getenv(key) else 'missing'}")
if missing:
    print(f"\n[Warning] The following recommended keys are not set: {', '.join(missing)}")
PY

export PYTHONPATH="."
pytest -q || "$VENV_PY" -m pytest -q
"$VENV_PY" -m compileall -q app src webapp tests scripts

mkdir -p "$OUTPUT_DIR"
"$VENV_PY" -m app research \
  --company "$COMPANY" \
  --country "$COUNTRY" \
  --depth "$DEPTH" \
  --output-dir "$OUTPUT_DIR" \
  --memory-db "$MEMORY_DB"

echo "Workflow complete. Artifacts in: $OUTPUT_DIR"
printf '%s\n' "- company_research_report.md" "- company_research.json" "- sources.json" "- run_metadata.json" "- changes.json"
