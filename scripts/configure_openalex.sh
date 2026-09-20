#!/bin/sh
# Kept for compatibility: AreaDay key setup now lives in configure_openalex.py,
# which also works without curl, without a GUI editor and without a terminal.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ -x "$SKILL_DIR/.venv/bin/python" ]; then
  PYTHON="$SKILL_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "AreaDay needs Python to configure the OpenAlex key, and none was found." >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/configure_openalex.py" "$@"
