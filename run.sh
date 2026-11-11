#!/usr/bin/env bash
# Linux: create the virtualenv on first run, then start the app. Extra args pass through (e.g. --browser).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  if ! python3 -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null; then
    echo "GTK WebKit is missing. Install it with:"
    echo "  sudo apt install python3-gi gir1.2-webkit2-4.1     (Debian/Ubuntu)"
    echo "  sudo dnf install python3-gobject webkit2gtk4.1     (Fedora)"
    echo "Or run ./run.sh --browser to use your web browser instead."
  fi
  # --system-site-packages lets the venv see the distro's GTK bindings (python3-gi)
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python main.py "$@"
