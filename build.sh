#!/usr/bin/env bash
# Linux: run the tests, then build dist/LCIP/LCIP. The target machine still needs GTK WebKit installed.
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv --system-site-packages .venv; .venv/bin/pip install -q -r requirements.txt; }
.venv/bin/python -m pytest -q -p no:anyio tests
.venv/bin/pyinstaller --noconfirm lcip.spec
echo "Built: dist/LCIP/LCIP"
