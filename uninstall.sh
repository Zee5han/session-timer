#!/usr/bin/env bash
set -euo pipefail
rm -f "$HOME/.local/bin/session-timer" \
      "$HOME/.local/share/applications/session-timer.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/session-timer.svg"
echo "Removed Session Timer. Saved session state is in ~/.config/session-timer if you want to delete it too."
