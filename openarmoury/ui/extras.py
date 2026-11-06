"""Monitor, Scenarios and Macros pages."""
import os
import signal

from gi.repository import Adw, Gio, GLib, Gtk

from .. import games, monitor
from ..restore import macro_slug
from . import design
from .context import Op
from .pages import PROFILE_LABELS, Page
from .widgets import Sparkline, stat_tile

BRIGHTNESS = ["Off", "Low", "Medium", "High"]
HISTORY = 60
MAX_EVENTS = 512
MAX_DELAY_MS = 5000


class MonitorPage(Page):
    title = "Monitor"
    icon = "speedometer-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = page = design.new_page("Monitor", "What your laptop is doing right now.")
        self.history = {"cpu": [], "memory": []}
        self.process_signature = None

        charts = Adw.PreferencesGroup()
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12, homogeneous=True, min_children_per_line=2, max_children_per_line=2)
        self.charts = {}
        for key, title in (("cpu", "CPU usage"), ("memory", "Memory used")):
            box, value, detail = stat_tile(title)
            box.add_css_class("home-card")
            line = Sparkline()
            box.append(line)
            grid.append(box)
            self.charts[key] = (value, detail, line)
        charts.add(grid)
        page.add(charts)

        details = Adw.PreferencesGroup(title="Details")
        self.rows = {}
        for key, title in (
            ("gpu", "Discrete GPU"),
            ("gpu_temp", "GPU temperature"),
            ("gpu_load", "GPU load"),
            ("gpu_memory", "GPU memory"),
            ("gpu_clock", "GPU clock"),
            ("gpu_power", "GPU power"),
            ("disk", "Disk temperature"),
            ("down", "Network download"),
            ("up", "Network upload"),
            ("power", "Battery power"),
        ):
            row = Adw.ActionRow(title=title)
            label = Gtk.Label(label="–", css_classes=["dim-label"])
            row.add_suffix(label)
            details.add(row)
            self.rows[key] = label
        page.add(details)

        self.memory_group = Adw.PreferencesGroup(title="Free up memory", description="Your biggest open programs. Closing one asks it to quit normally, so unsaved work may prompt you first.")
        self.process_rows = []
        page.add(self.memory_group)
        self.refresh()

    def refresh(self):
        meter = self.ctx.monitor
        used, total = meter.memory()
        memory_percent = 100 * used / total if total else 0
        for key, value in (("cpu", meter.cpu_percent), ("memory", memory_percent)):
            self.history[key] = (self.history[key] + [value])[-HISTORY:]
            self.charts[key][2].set_values(self.history[key])
        self.charts["cpu"][0].set_label(f"{meter.cpu_percent:.0f}%")
        mhz = meter.cpu_mhz()
        self.charts["cpu"][1].set_label(f"{mhz / 1000:.2f} GHz average" if mhz else "")
        self.charts["memory"][0].set_label(f"{used / 2**30:.1f} GB")
        self.charts["memory"][1].set_label(f"of {total / 2**30:.1f} GB")

        gpu = meter.discrete_gpu()
        states = {"suspended": "Asleep, saving power", "active": "Awake"}
        self.rows["gpu"].set_label(f"{gpu['vendor']}: {states.get(gpu['state'], gpu['state'])}" if gpu else "None found")
        stats = meter.gpu_stats or {}
        reading = lambda key, form: form.format(stats[key]) if stats.get(key) is not None else "–"  # noqa: E731
        self.rows["gpu_temp"].set_label(reading("temperature", "{:.0f} °C"))
        self.rows["gpu_load"].set_label(reading("load", "{:.0f}%"))
        self.rows["gpu_memory"].set_label(f"{stats['memory_used'] / 1024:.1f} of {stats['memory_total'] / 1024:.1f} GB" if stats.get("memory_used") is not None and stats.get("memory_total") else "–")
        self.rows["gpu_clock"].set_label(reading("clock", "{:.0f} MHz"))
        self.rows["gpu_power"].set_label(reading("power", "{:.0f} W"))
        temperature = meter.disk_temp()
        self.rows["disk"].set_label(f"{temperature:.0f} °C" if temperature is not None else "–")
        self.rows["down"].set_label(monitor.format_rate(meter.net_down))
        self.rows["up"].set_label(monitor.format_rate(meter.net_up))
        watts = meter.battery_watts()
        self.rows["power"].set_label(f"{watts:.1f} W" if watts is not None else "–")
        self._refresh_processes()

    def _refresh_processes(self):
        top = self.ctx.monitor.top_processes(os.getuid())
        signature = [p["name"] for p in top]
        if signature == self.process_signature:
            for row, process in zip(self.process_rows, top):
                row.set_subtitle(f"{process['memory'] / 2**20:.0f} MB")
            return
        self.process_signature = signature
        for row in self.process_rows:
            self.memory_group.remove(row)
        self.process_rows = []
        for process in top:
            row = Adw.ActionRow(title=GLib.markup_escape_text(process["name"]), subtitle=f"{process['memory'] / 2**20:.0f} MB")
            button = Gtk.Button(label="Close", valign=Gtk.Align.CENTER)
            button.connect("clicked", self._ask_close, process)
            row.add_suffix(button)
            self.memory_group.add(row)
            self.process_rows.append(row)

    def _ask_close(self, _button, process):
        dialog = Adw.AlertDialog(heading=f"Close {process['name']}?", body="Unsaved work in this program could be lost.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("close", "Close it")
        dialog.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: response == "close" and self._close(process))
        dialog.present(self.ctx.window)

    def _close(self, process):
        if self.ctx.is_demo:
            self.ctx.toast("Demo mode: nothing was closed.")
            return
        try:
            os.kill(process["pid"], signal.SIGTERM)
        except OSError as err:
            self.ctx.toast(f"Couldn't close it: {err}")


def _optional_combo(title, options, value):
    """A choice with a 'No change' first entry. Options are (value, label) pairs."""
    selected = next((index for index, (option, _label) in enumerate(options, 1) if option == value), 0)
    return design.choice_row(title, ["No change"] + [label for _v, label in options], selected)


class ScenariosPage(Page):
    title = "Scenarios"
    icon = "preferences-other-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = page = design.new_page("Scenarios", "Change settings automatically for each game, and for plugged-in or battery use.")
        self.profiles = [(c, PROFILE_LABELS.get(c, c.title())) for c in ctx.hw.profile_choices()]
        self.levels = list(enumerate(BRIGHTNESS))

        power = Adw.PreferencesGroup(title="Plugged in or on battery", description="Applied while the app is running. Turn on “Keep running” in System to have these work with the window closed.")
        for source, title in (("ac", "When plugged in"), ("battery", "On battery")):
            rule = ctx.config["power_rules"].setdefault(source, {})
            row = _optional_combo(f"{title}: profile", self.profiles, rule.get("profile"))
            row.connect("notify::selected", self._rule_changed, source, "profile", self.profiles)
            power.add(row)
            row = _optional_combo(f"{title}: keyboard brightness", self.levels, rule.get("brightness"))
            row.connect("notify::selected", self._rule_changed, source, "brightness", self.levels)
            power.add(row)
        low = Adw.SwitchRow(title="Lower the refresh rate on battery", subtitle="Saves power. Returns to the highest rate when plugged in.", active=bool(ctx.config["power_rules"].get("battery", {}).get("low_refresh")))
        low.connect("notify::active", self._low_refresh_changed)
        power.add(low)
        page.add(power)

        self.group = Adw.PreferencesGroup(title="Scenarios", description="When a program starts, switch to the settings you choose, then go back when it closes.")
        add = Gtk.Button(label="Add", css_classes=["flat"], valign=Gtk.Align.CENTER)
        add.connect("clicked", lambda _b: self._edit())
        self.group.set_header_suffix(add)
        self.rows = []
        page.add(self.group)
        self._rebuild()

        self.library = Adw.PreferencesGroup(title="Game library", description="Steam games and apps your desktop lists as games.")
        page.add(self.library)
        self._load_games()

    def _load_games(self):
        found = [{"name": "Demo Game", "source": "Demo", "match": "demogame"}] if self.ctx.is_demo else games.all_games(os.path.expanduser("~"))
        if not found:
            self.library.add(Adw.ActionRow(title="No games found", subtitle="Install a game through Steam or your software centre, then reopen the app."))
        for game in found:
            row = Adw.ActionRow(title=GLib.markup_escape_text(game["name"]), subtitle=game["source"])
            play = Gtk.Button(label="Play", valign=Gtk.Align.CENTER)
            play.connect("clicked", self._launch, game)
            scenario = Gtk.Button(label="Add scenario", valign=Gtk.Align.CENTER, css_classes=["flat"])
            scenario.connect("clicked", lambda _b, g=game: self._edit({"name": g["name"], "match": g["match"]}))
            row.add_suffix(scenario)
            row.add_suffix(play)
            self.library.add(row)

    def _launch(self, _button, game):
        if self.ctx.is_demo:
            self.ctx.toast("Demo mode: nothing was launched.")
            return
        try:
            if "launch_uri" in game:
                Gio.AppInfo.launch_default_for_uri(game["launch_uri"], None)
            else:
                Gio.DesktopAppInfo.new(game["desktop_id"]).launch([], None)
        except GLib.Error as err:
            self.ctx.toast(f"Couldn't start it: {err.message}")

    def _rule_changed(self, row, _p, source, key, options):
        index = row.get_selected()
        rule = self.ctx.config["power_rules"].setdefault(source, {})
        rule[key] = options[index - 1][0] if index else None
        self.ctx.config.save()

    def _low_refresh_changed(self, row, _p):
        rules = self.ctx.config["power_rules"]
        rules.setdefault("battery", {})["low_refresh"] = True if row.get_active() else None
        rules.setdefault("ac", {})["low_refresh"] = False if row.get_active() else None
        self.ctx.config.save()

    def _rebuild(self):
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        for index, scenario in enumerate(self.ctx.config["scenarios"]):
            parts = []
            if scenario.get("profile"):
                parts.append(PROFILE_LABELS.get(scenario["profile"], scenario["profile"]))
            if scenario.get("brightness") is not None:
                parts.append(f"lights {BRIGHTNESS[scenario['brightness']].lower()}")
            if scenario.get("touchpad") is False:
                parts.append("touchpad off")
            if scenario.get("win_key") is False:
                parts.append("Win key off")
            row = Adw.ActionRow(title=GLib.markup_escape_text(scenario["name"]), subtitle=GLib.markup_escape_text(", ".join(parts) or "No changes chosen"))
            edit = Gtk.Button(icon_name="document-edit-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Edit scenario")
            edit.update_property([Gtk.AccessibleProperty.LABEL], [f"Edit {scenario['name']}"])
            edit.connect("clicked", lambda _b, i=index: self._edit(self.ctx.config["scenarios"][i], i))
            remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Delete scenario")
            remove.update_property([Gtk.AccessibleProperty.LABEL], [f"Delete {scenario['name']}"])
            remove.connect("clicked", lambda _b, i=index: self._delete(i))
            row.add_suffix(edit)
            row.add_suffix(remove)
            self.group.add(row)
            self.rows.append(row)

    def _delete(self, index):
        del self.ctx.config["scenarios"][index]
        self.ctx.config.save()
        self._rebuild()

    def _edit(self, scenario=None, index=None):
        """A small form for one scenario."""
        scenario = scenario or {}
        dialog = Adw.Dialog(title="Scenario", content_width=440)
        content = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        name = Adw.EntryRow(title="Name", text=scenario.get("name", ""))
        match = Adw.EntryRow(title="Program name or part of its path", text=scenario.get("match", ""))
        profile = _optional_combo("Profile", self.profiles, scenario.get("profile"))
        brightness = _optional_combo("Keyboard brightness", self.levels, scenario.get("brightness"))
        touchpad = Adw.SwitchRow(title="Turn off the touchpad", active=scenario.get("touchpad") is False)
        win_key = Adw.SwitchRow(title="Turn off the Win key", active=scenario.get("win_key") is False)
        for row in (name, match, profile, brightness, touchpad, win_key):
            group.add(row)
        content.add(group)

        def save(_button):
            if not name.get_text().strip() or len(match.get_text().strip()) < 3:
                self.ctx.toast("A scenario needs a name, and a program name of at least 3 letters.")
                return
            entry = {
                "name": name.get_text().strip(),
                "match": match.get_text().strip(),
                "profile": self.profiles[profile.get_selected() - 1][0] if profile.get_selected() else None,
                "brightness": self.levels[brightness.get_selected() - 1][0] if brightness.get_selected() else None,
                "touchpad": False if touchpad.get_active() else None,
                "win_key": False if win_key.get_active() else None,
            }
            scenarios = self.ctx.config["scenarios"]
            if index is None:
                scenarios.append(entry)
            else:
                scenarios[index] = entry
            self.ctx.config.save()
            self._rebuild()
            dialog.close()

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        button = Gtk.Button(label="Save", css_classes=["suggested-action"])
        button.connect("clicked", save)
        header.pack_end(button)
        view.add_top_bar(header)
        view.set_content(content)
        dialog.set_child(view)
        dialog.present(self.ctx.window)


class MacrosPage(Page):
    title = "Macros"
    icon = "input-keyboard-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = page = design.new_page("Macros", "Record a series of keys and replay it anywhere.")
        self.group = Adw.PreferencesGroup(
            title="Your macros",
            description="Record keys inside the recording window only, then replay them anywhere. Don't record passwords: macros are stored as plain text. Playback goes through the helper, so it may ask for your password.",
        )
        add = Gtk.Button(label="Record", css_classes=["flat"], valign=Gtk.Align.CENTER)
        add.connect("clicked", lambda _b: self._record())
        self.group.set_header_suffix(add)
        self.rows = []
        page.add(self.group)
        self._rebuild()

    def _rebuild(self):
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        for name, macro in self.ctx.config["macros"].items():
            row = Adw.EntryRow(title=GLib.markup_escape_text(f"{name}: shortcut, such as <Super>F9"), text=self.ctx.desktop.shortcut(macro_slug(name)), show_apply_button=True)
            row.connect("apply", self._set_shortcut, name)
            play = Gtk.Button(label="Play in 3 s", valign=Gtk.Align.CENTER, tooltip_text="Gives you time to switch to the window you want")
            play.connect("clicked", lambda _b, m=macro: GLib.timeout_add_seconds(3, self._play, m))
            remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Delete macro")
            remove.update_property([Gtk.AccessibleProperty.LABEL], [f"Delete {name}"])
            remove.connect("clicked", lambda _b, n=name: self._delete(n))
            row.add_suffix(play)
            row.add_suffix(remove)
            self.group.add(row)
            self.rows.append(row)

    def _set_shortcut(self, row, name):
        binding = row.get_text().strip()
        slug = macro_slug(name)
        self.ctx.desktop.set_shortcut(slug, f"OpenArmoury macro: {name}", binding, f"openarmoury --macro {slug}")
        self.ctx.toast("Shortcut saved." if binding else "Shortcut removed.")

    def _play(self, macro):
        helper = self.ctx.helper
        op = Op("macro", "/dev/uinput", f"{len(macro)} key presses and releases", lambda: helper.request(op="keys", events=macro))
        self.ctx.submit([op])
        return False

    def _delete(self, name):
        self.ctx.desktop.set_shortcut(macro_slug(name), "", "", "")
        self.ctx.config["macros"].pop(name, None)
        self.ctx.config.save()
        self._rebuild()

    def _record(self):
        dialog = Adw.Dialog(title="Record macro", content_width=420)
        events = []
        held = set()
        last = {"time": None}
        status = Gtk.Label(label="Press keys now. They're only recorded while this window is open.", wrap=True, justify=Gtk.Justification.CENTER, margin_top=18, margin_bottom=18)
        name = Adw.EntryRow(title="Macro name")
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)

        def record(code, value):
            now = GLib.get_monotonic_time() // 1000
            delay = 0 if last["time"] is None else min(MAX_DELAY_MS, now - last["time"])
            last["time"] = now
            if len(events) < MAX_EVENTS:
                events.append([code, value, delay])
            status.set_label(f"{len(events)} key events recorded")

        def pressed(_controller, _keyval, keycode, _state):
            # Typing the name isn't part of the macro. Hardware keycodes are the evdev code plus 8.
            if name.get_focus_child() is not None:
                return False
            code = keycode - 8
            if 1 <= code <= 248 and code not in held:
                held.add(code)
                record(code, 1)
            return True

        def released(_controller, _keyval, keycode, _state):
            code = keycode - 8
            if code in held:
                held.discard(code)
                record(code, 0)

        keys.connect("key-pressed", pressed)
        keys.connect("key-released", released)
        dialog.add_controller(keys)

        def save(_button):
            title = name.get_text().strip()
            if not title or not macro_slug(title) or not events:
                self.ctx.toast("Record some keys and give the macro a name first.")
                return
            # A key still held when recording stopped would otherwise stay down.
            for code in held:
                events.append([code, 0, 0])
            self.ctx.config["macros"][title] = events
            self.ctx.config.save()
            self._rebuild()
            dialog.close()

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        button = Gtk.Button(label="Save", css_classes=["suggested-action"], focusable=False)
        button.connect("clicked", save)
        header.pack_end(button)
        view.add_top_bar(header)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_bottom=12)
        body.append(status)
        listing = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        listing.append(name)
        body.append(listing)
        view.set_content(body)
        dialog.set_child(view)
        dialog.present(self.ctx.window)
