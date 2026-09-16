#!/usr/bin/env bash
# Builds dist/session-timer_<version>_all.deb — a plain Debian package that
# installs the app system-wide and pulls in GTK's Python bindings.
set -euo pipefail

version="${1:-1.0.0}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pkg="$root/dist/session-timer_${version}_all"

rm -rf "$pkg"
mkdir -p "$pkg/DEBIAN" \
         "$pkg/usr/bin" \
         "$pkg/usr/share/applications" \
         "$pkg/usr/share/icons/hicolor/scalable/apps" \
         "$pkg/usr/share/doc/session-timer"

install -m 755 "$root/session_timer.py"      "$pkg/usr/bin/session-timer"
install -m 644 "$root/session-timer.desktop" "$pkg/usr/share/applications/session-timer.desktop"
install -m 644 "$root/session-timer.svg"     "$pkg/usr/share/icons/hicolor/scalable/apps/session-timer.svg"
install -m 644 "$root/LICENSE"               "$pkg/usr/share/doc/session-timer/copyright"
install -m 644 "$root/README.md"             "$pkg/usr/share/doc/session-timer/README.md"

cat > "$pkg/DEBIAN/control" <<CONTROL
Package: session-timer
Version: $version
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-3.0
Maintainer: Muhammad Zeeshan Javed <zeeshanjawed126.mzj@gmail.com>
Homepage: https://github.com/Zee5han/session-timer
Description: Floating glass timer for online lessons
 A small frameless timer that stays above every window so both tutor and
 student can see how long the lesson has run. Start, pause, resume, reset.
CONTROL

dpkg-deb --root-owner-group --build "$pkg" >/dev/null
rm -rf "$pkg"
echo "Built ${pkg}.deb"
