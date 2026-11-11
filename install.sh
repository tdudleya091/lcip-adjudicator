#!/usr/bin/env bash
# LCIP installer (Linux, user-level; never uses sudo).
#  1. checks for the system GTK/WebKit packages the app window needs
#  2. creates .venv and installs the Python packages
#  3. adds "LCIP Adjudicator" to your app menu and puts an icon on your Desktop
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PY="${LCIP_SYSTEM_PYTHON:-/usr/bin/python3}"   # the system Python: the GTK bindings are compiled for it

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# ---- 1. system packages -------------------------------------------------------
missing=()
"$PY" -c 'import venv, ensurepip' 2>/dev/null || missing+=(python3-venv)
"$PY" -c 'import gi' 2>/dev/null || missing+=(python3-gi)
"$PY" -c 'import gi; gi.require_version("WebKit2", "4.1"); from gi.repository import WebKit2' 2>/dev/null \
  || missing+=(gir1.2-webkit2-4.1)
if [ ${#missing[@]} -gt 0 ]; then
  say "LCIP needs a few system packages first. Install them with:"
  echo "    sudo apt install ${missing[*]}"
  echo "(Fedora: sudo dnf install python3-gobject webkit2gtk4.1 · Arch: sudo pacman -S python-gobject webkit2gtk-4.1)"
  echo "Then run ./install.sh again."
  exit 1
fi

# ---- 2. Python environment ----------------------------------------------------
if [ ! -x "$DIR/.venv/bin/python" ]; then
  say "Creating the Python environment ..."
  "$PY" -m venv --system-site-packages "$DIR/.venv"   # sees the distro's GTK bindings
fi
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
"$DIR/.venv/bin/python" -c 'import gi, webview' || { echo "Python packages failed to import."; exit 1; }

# ---- 3. app menu entry and Desktop icon ---------------------------------------
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
cp "$DIR/assets/lcip.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/lcip.svg"
ENTRY="$HOME/.local/share/applications/lcip.desktop"
cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=LCIP Adjudicator
Comment=Littoral Commander supply, health and combat adjudicator (offline)
Exec="$DIR/.venv/bin/python" "$DIR/main.py"
Path=$DIR
Icon=lcip
Terminal=false
Categories=Game;
EOF
chmod +x "$ENTRY"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP" ]; then
  cp "$ENTRY" "$DESKTOP/lcip.desktop"
  chmod +x "$DESKTOP/lcip.desktop"
  # GNOME only launches Desktop icons marked trusted ("Allow Launching")
  gio set "$DESKTOP/lcip.desktop" metadata::trusted true 2>/dev/null || true
fi

say "Installed. Open 'LCIP Adjudicator' from your app menu or the Desktop icon."
