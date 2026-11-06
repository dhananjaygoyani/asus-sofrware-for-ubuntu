#!/bin/sh
# Installs OpenArmoury. Nothing is downloaded and no hardware is touched.
# Usage: sudo ./install.sh [--no-uaccess]
set -eu

UACCESS=1
for arg in "$@"; do
    case "$arg" in
        --no-uaccess) UACCESS=0 ;;
        *) echo "Usage: sudo $0 [--no-uaccess]" >&2; exit 2 ;;
    esac
done

DESTDIR="${DESTDIR:-}"
if [ -z "$DESTDIR" ] && [ "$(id -u)" -ne 0 ]; then
    echo "Please run with sudo." >&2
    exit 1
fi
if [ -z "$DESTDIR" ] && ! python3 -c 'import gi; gi.require_version("Adw", "1"); gi.require_version("Gtk", "4.0")' 2>/dev/null; then
    echo "GTK4 and libadwaita for Python are missing. Install them with:" >&2
    echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" >&2
    exit 1
fi

SRC="$(cd "$(dirname "$0")" && pwd)"
LIB="$DESTDIR/usr/lib/openarmoury"

rm -rf "$LIB"
mkdir -p "$LIB"
cp -r "$SRC/openarmoury" "$LIB/"
find "$LIB" -name '__pycache__' -type d -prune -exec rm -rf {} +
chmod -R a+rX,go-w "$LIB"

install -D -m 0755 "$SRC/helper/openarmoury-helper" "$DESTDIR/usr/libexec/openarmoury/openarmoury-helper"
install -D -m 0644 "$SRC/data/org.openarmoury.helper.policy" "$DESTDIR/usr/share/polkit-1/actions/org.openarmoury.helper.policy"
install -D -m 0644 "$SRC/data/org.openarmoury.App.desktop" "$DESTDIR/usr/share/applications/org.openarmoury.App.desktop"
rm -f "$DESTDIR/usr/share/icons/hicolor/scalable/apps/org.openarmoury.App.svg"  # from older versions
for size in 16 24 32 48 64 96 128; do
    install -D -m 0644 "$SRC/data/icons/$size.png" "$DESTDIR/usr/share/icons/hicolor/${size}x${size}/apps/org.openarmoury.App.png"
done

mkdir -p "$DESTDIR/usr/bin"
cat > "$DESTDIR/usr/bin/openarmoury" <<'LAUNCHER'
#!/bin/sh
PYTHONPATH=/usr/lib/openarmoury exec /usr/bin/python3 -m openarmoury "$@"
LAUNCHER
chmod 0755 "$DESTDIR/usr/bin/openarmoury"

RULE="$DESTDIR/etc/udev/rules.d/70-openarmoury.rules"
if [ "$UACCESS" -eq 1 ]; then
    install -D -m 0644 "$SRC/data/70-openarmoury.rules" "$RULE"
else
    rm -f "$RULE"
fi

if [ -z "$DESTDIR" ]; then
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=hidraw --action=change || true
    gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi
echo "Installed. Open it from your apps, or run: openarmoury"
