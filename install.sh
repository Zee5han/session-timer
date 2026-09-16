#!/usr/bin/env bash
# Installs Session Timer for the current user (no sudo needed).
# Puts the app in ~/.local/bin and adds it to the app grid.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor/scalable/apps"

if ! /usr/bin/python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null; then
  echo "GTK 3 Python bindings are missing. Install them with:"
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0"
  exit 1
fi

mkdir -p "$bin" "$apps" "$icons"
install -m 755 "$here/session_timer.py" "$bin/session-timer"
install -m 644 "$here/session-timer.svg" "$icons/session-timer.svg"
install -m 644 "$here/session-timer.desktop" "$apps/session-timer.desktop"
update-desktop-database "$apps" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed. Find 'Session Timer' in your app grid, or run: session-timer"
case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "Note: $bin is not on your PATH yet; the app grid entry works regardless." ;;
esac
