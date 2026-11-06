"""Lighting (built-in effects) and Light Studio (software effects) pages."""
import copy

from gi.repository import Adw, Gtk

from .. import effects, keyboard, packets
from ..system import LED
from .pages import Page
from .widgets import KeyboardView, colour_button


def _combo(title, options, selected=0):
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(options))
    row.set_selected(selected)
    return row


class LightingPage(Page):
    title = "Lighting"
    icon = "keyboard-brightness-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = page = Adw.PreferencesPage()
        saved = ctx.config["lighting"] or {}
        self.colour = saved.get("colour", [255, 40, 0])

        preview = Adw.PreferencesGroup()
        self.view = KeyboardView()
        frame = Gtk.Frame(css_classes=["view"], child=self.view)
        preview.add(frame)
        self.preview_note = Gtk.Label(label="The preview is an approximation. Your keyboard runs the real effect.", xalign=0, wrap=True, css_classes=["dim-label", "caption"], margin_top=6)
        preview.add(self.preview_note)
        page.add(preview)

        self.detect_group = Adw.PreferencesGroup(title="Keyboard")
        self.detect_row = Adw.ActionRow()
        self.detect_button = Gtk.Button(label="Ask the keyboard", valign=Gtk.Align.CENTER)
        self.detect_button.connect("clicked", lambda _b: ctx.detect_keyboard())
        self.detect_row.add_suffix(self.detect_button)
        self.detect_group.add(self.detect_row)
        page.add(self.detect_group)

        self.effect_group = Adw.PreferencesGroup(title="Effect")
        self.mode_row = _combo("Effect", ["Static"])
        self.effect_group.add(self.mode_row)
        self.colour_row = Adw.ActionRow(title="Colour")
        self.colour_row.add_suffix(colour_button(self.colour, self._set_colour))
        self.effect_group.add(self.colour_row)
        self.speed_row = _combo("Speed", ["Low", "Medium", "High"], ["low", "medium", "high"].index(saved.get("speed", "medium")))
        self.effect_group.add(self.speed_row)
        self.direction_row = _combo("Direction", ["Right", "Left", "Up", "Down"], ["right", "left", "up", "down"].index(saved.get("direction", "right")))
        self.effect_group.add(self.direction_row)
        self.zone_row = _combo("Area", ["Whole keyboard"])
        self.effect_group.add(self.zone_row)
        self.save_row = Adw.SwitchRow(title="Save to the keyboard", subtitle="Off keeps it until restart. Which packet writes flash isn't proven, so this stays off unless you choose it.", active=saved.get("save", False))
        self.effect_group.add(self.save_row)
        apply_button = Gtk.Button(label="Apply effect", css_classes=["suggested-action"], halign=Gtk.Align.END, margin_top=12)
        apply_button.connect("clicked", self._apply)
        self.effect_group.add(apply_button)
        page.add(self.effect_group)

        group = Adw.PreferencesGroup(title="Brightness")
        self.brightness_row = _combo("Level", ["Off", "Low", "Medium", "High"], ctx.hw.brightness() or 0)
        self.brightness_row.connect("notify::selected", self._brightness_changed)
        self.brightness_ready = True
        group.add(self.brightness_row)
        if ctx.hw.brightness() is None:
            self.brightness_row.set_sensitive(False)
            self.brightness_row.set_subtitle("No keyboard backlight found.")
        page.add(group)

        for row in (self.mode_row, self.speed_row, self.direction_row):
            row.connect("notify::selected", lambda *_a: self._update_rows())
        ctx.board_listeners.append(self.rebuild)
        self.rebuild()

    def rebuild(self):
        board = self.ctx.board
        self.view.set_keys(board.light_keys())
        self.modes = board.modes or ["Static"]
        saved = self.ctx.config["lighting"] or {}
        self.mode_row.set_model(Gtk.StringList.new([keyboard.MODE_LABELS[m] for m in self.modes]))
        if saved.get("mode") in self.modes:
            self.mode_row.set_selected(self.modes.index(saved["mode"]))
        areas = ["Whole keyboard"]
        if board.kind == "zone" and board.zone_count == 4:
            areas += [f"Zone {n}" for n in range(1, 5)]
        self.zone_row.set_model(Gtk.StringList.new(areas))
        self.effect_group.set_sensitive(board.can_color)
        if board.verified_by_keyboard:
            caps = board.capabilities
            extras = [name.replace("_", " ") for name in ("logo", "lightbar", "vcut", "aero", "bump", "rear_glow") if caps.get(name)]
            self.detect_row.set_title(f"Backlight type {caps['backlight_type']}: {board.kind}")
            self.detect_row.set_subtitle("Also lights: " + ", ".join(extras) if extras else "No extra lit areas reported.")
            self.detect_button.set_label("Ask again")
        elif board.interface:
            self.detect_row.set_title(f"Not asked yet, assuming {board.kind}")
            self.detect_row.set_subtitle("Sends a query that sets no colours, and shows it to you first.")
        else:
            self.detect_row.set_title("Brightness only" if not board.tuf else "Single colour, set through the kernel")
            self.detect_row.set_subtitle("No lighting report was found on this keyboard.")
            self.detect_button.set_visible(False)
        self._update_rows()

    def _update_rows(self):
        mode = self.modes[self.mode_row.get_selected()] if self.mode_row.get_selected() < len(self.modes) else "Static"
        self.colour_row.set_visible(mode not in ("RainbowCycle", "RainbowWave"))
        self.speed_row.set_visible(mode != "Static")
        self.direction_row.set_visible(mode == "RainbowWave")

    def _set_colour(self, colour):
        self.colour = colour

    def _settings(self):
        return {
            "mode": self.modes[self.mode_row.get_selected()],
            "colour": self.colour,
            "speed": ["low", "medium", "high"][self.speed_row.get_selected()],
            "direction": ["right", "left", "up", "down"][self.direction_row.get_selected()],
            "zone": self.zone_row.get_selected(),
            "save": self.save_row.get_active(),
        }

    def _apply(self, _button):
        settings = self._settings()
        ops = effect_ops(self.ctx, settings)
        self.ctx.stop_live()

        def done(ok):
            if ok:
                self.ctx.config["lighting"] = settings
                self.ctx.toast("Effect applied.")

        self.ctx.submit(ops, done)

    def _brightness_changed(self, row, _p):
        if not getattr(self, "brightness_ready", False):
            return
        value = row.get_selected()

        def done(ok):
            if ok:
                self.ctx.config["brightness"] = value
            else:
                self.brightness_ready = False
                row.set_selected(self.ctx.hw.brightness() or 0)
                self.brightness_ready = True

        self.ctx.submit([self.ctx.write_op("brightness", f"{LED}/brightness", value)], done)

    def tick(self, now):
        settings = self._settings()
        keys = self.ctx.board.light_keys()
        if self.ctx.live_effect:
            frame = effects.render(self.ctx.live_effect, keys, now, self.ctx.hw.cpu_temp())
        else:
            frame = effects.preview_builtin(settings["mode"], settings["colour"], settings["speed"], settings["direction"], keys, now)
        level = self.brightness_row.get_selected()
        self.view.set_frame(effects.apply_brightness(frame, level))


def effect_ops(ctx, settings):
    """The operations for a built-in effect. Also used to restore at login."""
    board = ctx.board
    if board.kind == "single":
        speed_index = ["low", "medium", "high"].index(settings["speed"])
        value = packets.tuf_rgb_mode(settings["mode"], settings["colour"], speed_index, settings["save"])
        return [ctx.write_op("tuf-rgb", f"{LED}/kbd_rgb_mode", value)]
    length = board.interface["transport"][1]
    zone = settings.get("zone", 0)
    uncertain = board.uncertain_reason("zone-effect") if zone else None
    packet = packets.effect(settings["mode"], settings["colour"], settings["speed"], settings["direction"], zone, length=length)
    ops = [ctx.hid_op("zone-effect" if zone else "effect", packet, uncertain)]
    for commit in packets.commit(save=settings["save"], length=length):
        if commit[1] == packets.OP_COMMIT_B4:
            ops.append(ctx.hid_op("save", commit, board.uncertain_reason("save")))
        else:
            ops.append(ctx.hid_op("effect", commit))
    return ops


class StudioPage(Page):
    title = "Light Studio"
    icon = "applications-graphics-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.effect = copy.deepcopy(ctx.config["studio_effect"] or effects.BUILTIN_PRESETS["Aurora"])
        self.paint_colour = [255, 80, 0]
        self.paint = {"kind": "paint", "colours": {}, "base": [0, 0, 0]}
        self.widget = outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

        frame = Gtk.Frame(css_classes=["view"])
        self.view = KeyboardView(self._paint_key)
        frame.set_child(self.view)
        outer.append(frame)

        controls = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        self.live_row = Adw.SwitchRow(title="Run on the keyboard", subtitle="Sends colours live at up to 15 frames a second. Nothing is saved to the keyboard.")
        self.live_row.connect("notify::active", self._live_changed)
        controls.append(self.live_row)
        outer.append(controls)

        self.stack = Adw.ViewStack(vexpand=True)
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE, halign=Gtk.Align.CENTER)
        outer.append(switcher)
        scroller = Gtk.ScrolledWindow(child=self.stack, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        outer.append(scroller)

        self.stack.add_titled_with_icon(self._paint_tab(), "paint", "Paint", "document-edit-symbolic")
        self.stack.add_titled_with_icon(self._keyframe_tab(), "keyframes", "Keyframes", "media-playback-start-symbolic")
        self.stack.add_titled_with_icon(self._smart_tab(), "smart", "Smart", "dialog-information-symbolic")
        self.stack.add_titled_with_icon(self._presets_tab(), "presets", "Presets", "view-list-symbolic")
        self.stack.connect("notify::visible-child-name", self._tab_changed)
        ctx.board_listeners.append(self.rebuild)
        self.rebuild()

    def rebuild(self):
        board = self.ctx.board
        self.view.set_keys(board.light_keys())
        self.live_row.set_sensitive(board.can_color)
        self.paint_note.set_label(
            "Click or drag over keys to paint them."
            if board.kind == "per-key"
            else f"This keyboard has {board.zone_count} lighting {'zone' if board.zone_count == 1 else 'zones'}, so painting a key colours its whole zone."
        )

    def _tab_changed(self, stack, _p):
        name = stack.get_visible_child_name()
        if name == "paint":
            self._use(self.paint)
        elif name == "keyframes":
            self._use(self.keyframes)
        elif name == "smart":
            self._use(self.smart)

    def _use(self, effect):
        self.effect = effect
        self.ctx.config["studio_effect"] = effect
        if self.ctx.live_effect:
            self.ctx.live_effect = effect

    # Paint

    def _paint_tab(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Paint")
        self.paint_note = Gtk.Label(wrap=True, xalign=0, css_classes=["dim-label"], margin_bottom=8)
        group.add(self.paint_note)
        row = Adw.ActionRow(title="Brush colour")
        row.add_suffix(colour_button(self.paint_colour, lambda c: setattr(self, "paint_colour", c)))
        group.add(row)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=12)
        fill = Gtk.Button(label="Fill all")
        fill.connect("clicked", self._fill)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", self._clear)
        buttons.append(clear)
        buttons.append(fill)
        group.add(buttons)
        page.add(group)
        return page

    def _paint_key(self, key):
        self._use(self.paint)
        board = self.ctx.board
        codes = [key["code"]]
        if board.kind != "per-key":
            keys = [k for k in board.layout if "Lightbar" not in k["code"]]
            extent = max(k["x"] + k["w"] for k in keys)
            if "Lightbar" not in key["code"]:
                zone = board.zone_of(key, extent)
                codes = [k["code"] for k in keys if board.zone_of(k, extent) == zone]
        for code in codes:
            self.paint["colours"][code] = list(self.paint_colour)

    def _fill(self, _button):
        self._use(self.paint)
        self.paint["colours"] = {k["code"]: list(self.paint_colour) for k in self.ctx.board.light_keys()}

    def _clear(self, _button):
        self._use(self.paint)
        self.paint["colours"] = {}

    # Keyframes

    def _keyframe_tab(self):
        self.keyframes = copy.deepcopy(self.effect if self.effect.get("kind") == "keyframes" else effects.BUILTIN_PRESETS["Aurora"])
        page = Adw.PreferencesPage()
        settings = Adw.PreferencesGroup(title="Timing")
        self.duration_row = Adw.SpinRow.new_with_range(0.5, 60, 0.5)
        self.duration_row.set_title("Loop length")
        self.duration_row.set_subtitle("Seconds")
        self.duration_row.set_value(self.keyframes["duration"])
        self.duration_row.connect("notify::value", self._timing_changed)
        settings.add(self.duration_row)
        self.spread_row = Adw.SpinRow.new_with_range(0, 2, 0.05)
        self.spread_row.set_title("Spread across the keyboard")
        self.spread_row.set_subtitle("0 is one colour everywhere. Higher values sweep the colours across.")
        self.spread_row.set_value(self.keyframes["spread"])
        self.spread_row.connect("notify::value", self._timing_changed)
        settings.add(self.spread_row)
        page.add(settings)
        self.keys_group = Adw.PreferencesGroup(title="Keyframes")
        add = Gtk.Button(label="Add", css_classes=["flat"], valign=Gtk.Align.CENTER)
        add.connect("clicked", self._add_key)
        self.keys_group.set_header_suffix(add)
        self.key_rows = []
        page.add(self.keys_group)
        self._rebuild_key_rows()
        return page

    def _timing_changed(self, *_a):
        self.keyframes["duration"] = self.duration_row.get_value()
        self.keyframes["spread"] = self.spread_row.get_value()
        self._use(self.keyframes)

    def _rebuild_key_rows(self):
        for row in self.key_rows:
            self.keys_group.remove(row)
        self.key_rows = []
        for index, (position, colour) in enumerate(self.keyframes["keys"]):
            row = Adw.SpinRow.new_with_range(0, 100, 1)
            row.set_title(f"Keyframe {index + 1}")
            row.set_subtitle("Position in the loop, %")
            row.set_value(position * 100)
            row.connect("notify::value", self._key_moved, index)
            row.add_suffix(colour_button(colour, lambda c, i=index: self._key_coloured(i, c)))
            remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Remove keyframe")
            remove.update_property([Gtk.AccessibleProperty.LABEL], [f"Remove keyframe {index + 1}"])
            remove.connect("clicked", self._remove_key, index)
            remove.set_sensitive(len(self.keyframes["keys"]) > 2)
            row.add_suffix(remove)
            self.keys_group.add(row)
            self.key_rows.append(row)

    def _key_moved(self, row, _p, index):
        self.keyframes["keys"][index][0] = row.get_value() / 100
        self.keyframes["keys"].sort(key=lambda item: item[0])
        self._use(self.keyframes)

    def _key_coloured(self, index, colour):
        self.keyframes["keys"][index][1] = colour
        self._use(self.keyframes)

    def _add_key(self, _button):
        keys = self.keyframes["keys"]
        gaps = [(b[0] - a[0], i) for i, (a, b) in enumerate(zip(keys, keys[1:]))]
        _gap, at = max(gaps)
        position = (keys[at][0] + keys[at + 1][0]) / 2
        keys.insert(at + 1, [position, effects.sample_keyframes(keys, position)])
        self._rebuild_key_rows()
        self._use(self.keyframes)

    def _remove_key(self, _button, index):
        if len(self.keyframes["keys"]) > 2:
            del self.keyframes["keys"][index]
            self._rebuild_key_rows()
            self._use(self.keyframes)

    # Smart

    def _smart_tab(self):
        self.smart = copy.deepcopy(self.effect if self.effect.get("kind") == "smart" else effects.BUILTIN_PRESETS["Temperature"])
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Colour follows CPU temperature")
        self.smart_now = Adw.ActionRow(title="CPU now")
        self.smart_label = Gtk.Label(label="–", css_classes=["dim-label"])
        self.smart_now.add_suffix(self.smart_label)
        group.add(self.smart_now)
        for key, title, kind in (("low", "Cool at", "cold"), ("high", "Hot at", "hot")):
            row = Adw.SpinRow.new_with_range(20, 110, 1)
            row.set_title(title)
            row.set_subtitle("°C")
            row.set_value(self.smart[key])
            row.connect("notify::value", self._smart_changed, key)
            row.add_suffix(colour_button(self.smart[kind], lambda c, k=kind: self._smart_colour(k, c)))
            group.add(row)
        page.add(group)
        return page

    def _smart_changed(self, row, _p, key):
        self.smart[key] = row.get_value()
        self._use(self.smart)

    def _smart_colour(self, key, colour):
        self.smart[key] = colour
        self._use(self.smart)

    # Presets

    def _presets_tab(self):
        page = Adw.PreferencesPage()
        self.preset_page = page
        builtin = Adw.PreferencesGroup(title="Built in")
        for name, effect in effects.BUILTIN_PRESETS.items():
            builtin.add(self._preset_row(name, effect))
        page.add(builtin)
        self.saved_group = Adw.PreferencesGroup(title="Saved", description="Your own effects.")
        self.name_row = Adw.EntryRow(title="Save current effect as")
        save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
        save.connect("clicked", self._save_preset)
        self.name_row.add_suffix(save)
        self.saved_group.add(self.name_row)
        self.saved_rows = []
        page.add(self.saved_group)
        self._rebuild_saved()
        return page

    def _preset_row(self, name, effect, removable=False):
        row = Adw.ActionRow(title=name)
        load = Gtk.Button(label="Use", valign=Gtk.Align.CENTER)
        load.connect("clicked", lambda _b: self._load_preset(effect))
        row.add_suffix(load)
        if removable:
            remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Delete preset")
            remove.update_property([Gtk.AccessibleProperty.LABEL], [f"Delete preset {name}"])
            remove.connect("clicked", lambda _b: self._delete_preset(name))
            row.add_suffix(remove)
        return row

    def _rebuild_saved(self):
        for row in self.saved_rows:
            self.saved_group.remove(row)
        self.saved_rows = []
        for name, effect in self.ctx.config["presets"].items():
            row = self._preset_row(name, effect, removable=True)
            self.saved_group.add(row)
            self.saved_rows.append(row)

    def _load_preset(self, effect):
        effect = copy.deepcopy(effect)
        if effect["kind"] == "paint":
            self.paint = effect
        elif effect["kind"] == "keyframes":
            self.keyframes = effect
            self.duration_row.set_value(effect["duration"])
            self.spread_row.set_value(effect["spread"])
            self._rebuild_key_rows()
        elif effect["kind"] == "smart":
            self.smart = effect
        self._use(effect)

    def _save_preset(self, _button):
        name = self.name_row.get_text().strip()
        if not name:
            self.ctx.toast("Give the preset a name first.")
            return
        presets = self.ctx.config["presets"]
        presets[name] = copy.deepcopy(self.effect)
        self.ctx.config.save()
        self.name_row.set_text("")
        self._rebuild_saved()

    def _delete_preset(self, name):
        self.ctx.config["presets"].pop(name, None)
        self.ctx.config.save()
        self._rebuild_saved()

    # Live

    def _live_changed(self, row, _p):
        if getattr(self, "_live_updating", False):
            return
        if row.get_active():
            def done(ok):
                if not ok:
                    self._live_updating = True
                    row.set_active(False)
                    self._live_updating = False

            self.ctx.start_live(self.effect, done)
        else:
            self.ctx.stop_live()
            saved = self.ctx.config["lighting"]
            if saved:
                self.ctx.submit(effect_ops(self.ctx, saved))
            else:
                self.ctx.toast("The keyboard keeps the last colours until you apply an effect.")

    def tick(self, now):
        keys = self.ctx.board.light_keys()
        frame = effects.render(self.effect, keys, now, self.ctx.hw.cpu_temp())
        self.view.set_frame(frame)
        temperature = self.ctx.hw.cpu_temp()
        if temperature is not None:
            self.smart_label.set_label(f"{temperature:.0f} °C")
