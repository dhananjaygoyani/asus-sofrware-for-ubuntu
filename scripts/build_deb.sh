#!/bin/sh
# Builds dist/openarmoury_VERSION_all.deb. Needs no root, and reuses install.sh's layout.
# The package leaves out the keyboard udev rule, as it would let programs read key presses.
set -eu
umask 022  # packaged folders such as /usr/bin must not be group-writable

SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/openarmoury/__init__.py")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 0755 "$STAGE"

DESTDIR="$STAGE" "$SRC/install.sh" --no-uaccess >/dev/null
rmdir -p --ignore-fail-on-non-empty "$STAGE/etc/udev/rules.d" 2>/dev/null || true

DOC="$STAGE/usr/share/doc/openarmoury"
mkdir -p "$DOC" "$STAGE/DEBIAN"
cat > "$DOC/copyright" <<COPYRIGHT
OpenArmoury. Not made by or affiliated with ASUS.
Keyboard data in /usr/lib/openarmoury/openarmoury/data/asusctl comes from asusctl and is under the
Mozilla Public License 2.0, with the licence alongside it.
COPYRIGHT

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: openarmoury
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Dhananjay Goyani <dhananjaygoyani000@gmail.com>
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, libgtk-4-1 (>= 4.14), libadwaita-1-0 (>= 1.5), pkexec
Recommends: pipewire-bin
Suggests: nvidia-prime
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Description: Control centre for ASUS gaming laptops
 Performance modes, fan curves, battery charge limits, keyboard lighting,
 per-game scenarios and live monitoring, in one native GTK app.
CONTROL

mkdir -p "$SRC/dist"
dpkg-deb --root-owner-group --build "$STAGE" "$SRC/dist/openarmoury_${VERSION}_all.deb" >/dev/null
echo "$SRC/dist/openarmoury_${VERSION}_all.deb"
