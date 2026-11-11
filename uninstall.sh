#!/usr/bin/env bash
# Removes the app menu entry, Desktop icon and icon. Your saved games in ~/.local/share/lcip are kept.
set -u
DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
rm -f "$HOME/.local/share/applications/lcip.desktop" "$DESKTOP/lcip.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/lcip.svg"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Removed the LCIP launchers. Saved games are still in ~/.local/share/lcip (delete that folder to remove them)."
