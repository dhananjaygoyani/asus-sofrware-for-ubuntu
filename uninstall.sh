#!/bin/sh
# Removes OpenArmoury. Your settings in ~/.config/openarmoury stay unless you delete them.
# Fan curves and lighting already set stay active until a profile change or restart.
set -eu

DESTDIR="${DESTDIR:-}"
if [ -z "$DESTDIR" ] && [ "$(id -u)" -ne 0 ]; then
    echo "Please run with sudo." >&2
    exit 1
fi

rm -rf "$DESTDIR/usr/lib/openarmoury" "$DESTDIR/usr/libexec/openarmoury"
rm -f "$DESTDIR/usr/bin/openarmoury" \
      "$DESTDIR/usr/share/polkit-1/actions/org.openarmoury.helper.policy" \
      "$DESTDIR/usr/share/applications/org.openarmoury.App.desktop" \
      "$DESTDIR/usr/share/icons/hicolor/scalable/apps/org.openarmoury.App.svg" \
      "$DESTDIR/etc/udev/rules.d/70-openarmoury.rules"

if [ -n "${SUDO_USER:-}" ]; then
    home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
    rm -f "$home/.config/autostart/openarmoury-restore.desktop"
fi

if [ -z "$DESTDIR" ]; then
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=hidraw --action=change || true
fi
echo "Removed. Delete ~/.config/openarmoury too if you want your settings gone."
