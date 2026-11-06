"""Settings owned by the desktop rather than the hardware. These need no root."""
import shutil
import subprocess

from gi.repository import Gio, GLib

TOUCHPAD = "org.gnome.desktop.peripherals.touchpad"
MUTTER = "org.gnome.mutter"
NIGHT = "org.gnome.settings-daemon.plugins.color"
MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEY = f"{MEDIA_KEYS}.custom-keybinding"
CUSTOM_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
METHOD_TEMPORARY = 1


def _has_schema(name):
    source = Gio.SettingsSchemaSource.get_default()
    return bool(source and source.lookup(name, True))


def rates_from_state(state):
    """The built-in panel's refresh rates at its current resolution, from Mutter's state."""
    _serial, monitors, _logical, _props = state
    for (spec, modes, _monitor_props) in monitors:
        if not spec[0].startswith(("eDP", "LVDS")):
            continue
        current = next((m for m in modes if m[6].get("is-current")), None)
        if not current:
            continue
        same_size = [m for m in modes if m[1] == current[1] and m[2] == current[2]]
        return {
            "connector": spec[0],
            "current": current[3],
            "modes": sorted(((m[3], m[0]) for m in same_size), key=lambda item: item[0]),
        }
    return None


def apply_config_from_state(state, connector, mode_id):
    """Arguments for ApplyMonitorsConfig: every display kept as it is, except one mode."""
    serial, monitors, logical_monitors, _props = state
    current_modes = {}
    for (spec, modes, _monitor_props) in monitors:
        for mode in modes:
            if mode[6].get("is-current"):
                current_modes[spec[0]] = mode[0]
    layout = []
    for (x, y, scale, transform, primary, specs, _logical_props) in logical_monitors:
        outputs = []
        for spec in specs:
            chosen = mode_id if spec[0] == connector else current_modes.get(spec[0])
            outputs.append((spec[0], chosen, {}))
        layout.append((x, y, scale, transform, primary, outputs))
    return serial, METHOD_TEMPORARY, layout, {}


class GnomeDesktop:
    def __init__(self):
        self.touchpad_settings = Gio.Settings.new(TOUCHPAD) if _has_schema(TOUCHPAD) else None
        self.mutter_settings = Gio.Settings.new(MUTTER) if _has_schema(MUTTER) else None
        self.night_settings = Gio.Settings.new(NIGHT) if _has_schema(NIGHT) else None
        self.keys_settings = Gio.Settings.new(MEDIA_KEYS) if _has_schema(MEDIA_KEYS) else None

    def touchpad(self):
        return self.touchpad_settings.get_string("send-events") != "disabled" if self.touchpad_settings else None

    def set_touchpad(self, enabled):
        if self.touchpad_settings:
            self.touchpad_settings.set_string("send-events", "enabled" if enabled else "disabled")

    def win_key(self):
        return bool(self.mutter_settings.get_string("overlay-key")) if self.mutter_settings else None

    def set_win_key(self, enabled):
        if self.mutter_settings:
            if enabled:
                self.mutter_settings.reset("overlay-key")
            else:
                self.mutter_settings.set_string("overlay-key", "")

    def night_light(self):
        if not self.night_settings:
            return None
        return self.night_settings.get_boolean("night-light-enabled"), self.night_settings.get_uint("night-light-temperature")

    def set_night_light(self, enabled, temperature=None):
        if self.night_settings:
            self.night_settings.set_boolean("night-light-enabled", enabled)
            if temperature is not None:
                self.night_settings.set_uint("night-light-temperature", int(temperature))

    def mic_muted(self):
        if not shutil.which("wpctl"):
            return None
        try:
            output = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return "MUTED" in output if output else None

    def set_mic_muted(self, muted):
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1" if muted else "0"], timeout=2, check=False)

    def _display_proxy(self):
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.gnome.Mutter.DisplayConfig",
            "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig",
            None,
        )

    def _display_state(self):
        return self._display_proxy().call_sync("GetCurrentState", None, Gio.DBusCallFlags.NONE, 2000, None).unpack()

    def refresh_rates(self):
        try:
            return rates_from_state(self._display_state())
        except (GLib.Error, ValueError, KeyError, IndexError):
            return None

    def set_refresh(self, mode_id):
        state = self._display_state()
        rates = rates_from_state(state)
        args = GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", apply_config_from_state(state, rates["connector"], mode_id))
        self._display_proxy().call_sync("ApplyMonitorsConfig", args, Gio.DBusCallFlags.NONE, 5000, None)

    def shortcut(self, slug):
        """The key combination bound to one of our shortcuts, or ''."""
        if not self.keys_settings:
            return ""
        path = f"{CUSTOM_PATH}openarmoury-{slug}/"
        if path not in self.keys_settings.get_strv("custom-keybindings"):
            return ""
        return Gio.Settings.new_with_path(CUSTOM_KEY, path).get_string("binding")

    def set_shortcut(self, slug, name, binding, command):
        """Add, change or remove one of our own shortcuts. Yours are never touched."""
        if not self.keys_settings:
            return
        path = f"{CUSTOM_PATH}openarmoury-{slug}/"
        paths = list(self.keys_settings.get_strv("custom-keybindings"))
        entry = Gio.Settings.new_with_path(CUSTOM_KEY, path)
        if binding:
            entry.set_string("name", name)
            entry.set_string("binding", binding)
            entry.set_string("command", command)
            if path not in paths:
                self.keys_settings.set_strv("custom-keybindings", paths + [path])
        else:
            for key in ("name", "binding", "command"):
                entry.reset(key)
            if path in paths:
                paths.remove(path)
                self.keys_settings.set_strv("custom-keybindings", paths)


class FakeDesktop:
    """For demo mode and tests, so they can't change your real desktop settings."""

    def __init__(self):
        self.state = {"touchpad": True, "win_key": True, "night": (False, 4000), "mic": False, "shortcuts": {}, "refresh": 144.0}

    def touchpad(self):
        return self.state["touchpad"]

    def set_touchpad(self, enabled):
        self.state["touchpad"] = enabled

    def win_key(self):
        return self.state["win_key"]

    def set_win_key(self, enabled):
        self.state["win_key"] = enabled

    def night_light(self):
        return self.state["night"]

    def set_night_light(self, enabled, temperature=None):
        self.state["night"] = (enabled, temperature or self.state["night"][1])

    def mic_muted(self):
        return self.state["mic"]

    def set_mic_muted(self, muted):
        self.state["mic"] = muted

    def refresh_rates(self):
        return {"connector": "eDP-1", "current": self.state["refresh"], "modes": [(60.0, "60"), (144.0, "144")]}

    def set_refresh(self, mode_id):
        self.state["refresh"] = float(mode_id)

    def shortcut(self, slug):
        return self.state["shortcuts"].get(slug, "")

    def set_shortcut(self, slug, _name, binding, _command):
        self.state["shortcuts"][slug] = binding
