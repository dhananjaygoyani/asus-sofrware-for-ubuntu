"""Home, Performance, Fans and System pages."""
import json
import os
import pathlib
import shutil

from gi.repository import Adw, GLib, Gtk

from .. import effects
from ..system import fan_curve_writes
from . import design
from .context import Op
from .widgets import CurveView, Gauge, attribute_row, stat_tile

GPU_ATTRIBUTES = ("gpu_mux_mode", "egpu_enable", "egpu_connected", "dgpu_power_state", "mini_led_mode")
POWER_PREFIXES = ("ppt_", "nv_", "apu_mem")
GPU_WARNINGS = {
    "gpu_mux_mode": "Changing the GPU mode takes effect after a restart. The internal display may go blank if the "
    "graphics driver isn't set up for the new mode.",
    "egpu_enable": "Only change this with the external GPU connected and nothing using it.",
}
# Each state: what the row says, its button, and what the button does.
GPU_STATES = {
    "automatic": ("On, and asleep whenever it's idle.", "Turn off…"),
    "restart-to-unload": ("Step 1 of 2 is done. Restart the laptop, then come back here.", "Cancel"),
    "ready": ("Step 2 of 2: the driver is gone, so it's now safe to turn the GPU off.", "Turn off now"),
    "off": ("Off. Games and apps can't use it until it's turned back on.", "Turn on"),
    "restart-to-load": ("Turned on. Restart the laptop to finish.", None),
    "blocked": ("Unavailable while its driver is loaded, because it can crash the laptop.", None),
}
GPU_OFF_WARNING = (
    "Step 1 of 2. This stops the NVIDIA driver from loading, which takes a few minutes, and then you restart. "
    "Games can't use this GPU until you turn it back on. Automatic sleep already saves nearly the same power."
)
GPU_OFF_NOW_WARNING = (
    "This is stored in the firmware, so the GPU also stays off in Windows until you turn it on again. "
    "External displays wired to this GPU will stop working. This step hasn't been tested on this laptop, "
    "so save your work first."
)
PROFILE_LABELS = {
    "quiet": "Quiet",
    "low-power": "Low power",
    "cool": "Cool",
    "balanced": "Balanced",
    "balanced-performance": "Balanced performance",
    "performance": "Performance",
}
FAN_PRESETS = {
    "Quiet": [[45, 0], [55, 20], [62, 40], [68, 70], [74, 105], [80, 150], [86, 200], [95, 255]],
    "Balanced": [[40, 15], [50, 35], [58, 60], [65, 90], [72, 130], [78, 170], [85, 215], [92, 255]],
    "Cool": [[35, 40], [45, 70], [52, 100], [60, 135], [68, 175], [75, 210], [82, 240], [90, 255]],
    "Full speed": [[30, 255], [40, 255], [50, 255], [60, 255], [70, 255], [80, 255], [90, 255], [100, 255]],
}


class Page:
    title = ""
    icon = ""

    def __init__(self, ctx):
        self.ctx = ctx

    def refresh(self):
        """Called every couple of seconds while visible."""

    def tick(self, now):
        """Called at the frame rate while visible."""


PROFILE_ICONS = {
    "quiet": "power-profile-power-saver-symbolic",
    "low-power": "power-profile-power-saver-symbolic",
    "cool": "power-profile-power-saver-symbolic",
    "balanced": "power-profile-balanced-symbolic",
    "balanced-performance": "power-profile-balanced-symbolic",
    "performance": "power-profile-performance-symbolic",
}


def gpu_summary(stats):
    """A short line of whatever the GPU reports."""
    parts = []
    if stats["load"] is not None:
        parts.append(f"{stats['load']:.0f}% load")
    if stats["power"] is not None:
        parts.append(f"{stats['power']:.0f} W")
    return " · ".join(parts) or stats["name"]


def apply_profile(ctx, choice, done):
    """Change the profile and remember it. Used by every control that offers one."""

    def finished(ok):
        if ok:
            ctx.config["profile"] = choice
        done(ok)

    ctx.submit([ctx.write_op("profile", "/sys/firmware/acpi/platform_profile", choice)], finished)


class HomePage(Page):
    title = "Home"
    icon = "go-home-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.updating = False
        self.mode_buttons = {}
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=18, margin_bottom=24, margin_start=18, margin_end=18)
        clamp = Adw.Clamp(maximum_size=1180, child=body)
        self.widget = Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER)

        identity = ctx.hw.identity()
        body.append(design.large_title(identity["product"].split("_")[0] if identity["product"] else "This laptop", f"Board {identity['board']} · Firmware {identity['bios']}"))

        conflicts = ctx.hw.conflicts()
        if conflicts:
            body.append(Gtk.Label(label=f"{', '.join(conflicts)} is running and controls the same hardware, so settings may fight.", xalign=0, wrap=True, css_classes=["warning"]))

        choices = ctx.hw.profile_choices()
        if choices:
            body.append(Gtk.Label(label="Operating mode", xalign=0, css_classes=["section-title"]))
            row = Gtk.Box(spacing=4, homogeneous=True)
            self.mode_group = design.GlideGroup(row, "accent", 12)
            holder = Gtk.Box(css_classes=["mode-tiles", "stagger-0"], orientation=Gtk.Orientation.VERTICAL)
            holder.append(self.mode_group)
            leader = None
            for choice in choices:
                content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
                image = Gtk.Image(icon_name=PROFILE_ICONS.get(choice, "power-profile-balanced-symbolic"), pixel_size=26)
                image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
                content.append(image)
                content.append(Gtk.Label(label=PROFILE_LABELS.get(choice, choice.title())))
                button = Gtk.ToggleButton(child=content, group=leader, css_classes=["mode-tile"])
                button.update_property([Gtk.AccessibleProperty.LABEL], [f"{PROFILE_LABELS.get(choice, choice.title())} mode"])
                leader = leader or button
                button.connect("toggled", self._mode_toggled, choice)
                row.append(button)
                self.mode_buttons[choice] = button
            body.append(holder)

        body.append(Gtk.Label(label="Live", xalign=0, css_classes=["section-title"], margin_top=6))
        gauges = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10, homogeneous=True, min_children_per_line=2, max_children_per_line=6)
        self.gauges = {"cpu": Gauge("CPU", "°C", 100), "load": Gauge("CPU load", "%", 100), "memory": Gauge("Memory", "%", 100)}
        if ctx.hw.igpu_temp() is not None:
            self.gauges["igpu"] = Gauge("Integrated GPU", "°C", 100)
        if ctx.monitor.discrete_gpu():
            self.gauges["dgpu"] = Gauge("Discrete GPU", "°C", 100)
        self.fan_gauges = {}
        for label, _rpm in ctx.hw.fans():
            self.fan_gauges[label] = Gauge(label, "rpm", 7000)
        for index, gauge in enumerate(list(self.gauges.values()) + list(self.fan_gauges.values())):
            gauges.append(self._card(gauge, index))
        body.append(gauges)

        body.append(Gtk.Label(label="Status", xalign=0, css_classes=["section-title"], margin_top=6))
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10, homogeneous=True, min_children_per_line=2, max_children_per_line=4)
        self.tiles = {}
        for index, (key, title) in enumerate((("dgpu", "Discrete GPU"), ("battery", "Battery"), ("keyboard", "Keyboard"))):
            box, value, detail = stat_tile(title)
            box.add_css_class("home-card")
            box.add_css_class(f"stagger-{index % 6}")
            grid.append(box)
            self.tiles[key] = (value, detail)
        body.append(grid)
        self.refresh()

    @staticmethod
    def _card(child, index):
        box = Gtk.Box(css_classes=["home-card", f"stagger-{index % 6}"])
        box.append(child)
        return box

    def _mode_toggled(self, button, choice):
        if button.get_active():
            self.mode_group.select(button)
            if not self.updating:
                apply_profile(self.ctx, choice, lambda _ok: self.refresh())

    def refresh(self):
        hw = self.ctx.hw
        meter = self.ctx.monitor
        self.updating = True
        profile = hw.profile()
        if profile in self.mode_buttons:
            self.mode_buttons[profile].set_active(True)
        self.updating = False
        self.gauges["cpu"].set_value(meter.temperature_smooth if meter.temperature_smooth is not None else hw.cpu_temp())
        self.gauges["load"].set_value(meter.cpu_percent)
        used, total = meter.memory()
        self.gauges["memory"].set_value(100 * used / total if total else None)
        if "igpu" in self.gauges:
            self.gauges["igpu"].set_value(hw.igpu_temp())
        for label, rpm in hw.fans():
            if label in self.fan_gauges:
                self.fan_gauges[label].set_value(rpm)
        gpu = meter.discrete_gpu()
        states = {"suspended": "Asleep", "active": "Awake"}
        self.tiles["dgpu"][0].set_label(states.get(gpu["state"], gpu["state"].title()) if gpu else "None")
        stats = meter.gpu_stats
        if "dgpu" in self.gauges:
            self.gauges["dgpu"].set_value(stats["temperature"] if stats else None)
        if stats:
            self.tiles["dgpu"][1].set_label(gpu_summary(stats))
        else:
            self.tiles["dgpu"][1].set_label(f"{gpu['vendor']}. Readings appear when it wakes" if gpu else "")
        battery = hw.battery()
        if battery:
            self.tiles["battery"][0].set_label(f"{battery['capacity']}%")
            limit = f", limit {battery['limit']}%" if battery["limit"] else ""
            self.tiles["battery"][1].set_label(f"{battery['status']}{limit}")
        else:
            self.tiles["battery"][1].set_label("No battery found")
        board = self.ctx.board
        names = {"zone": f"{board.zone_count} zones", "per-key": "Per-key", "single": "Single colour", "brightness": "Brightness only"}
        self.tiles["keyboard"][0].set_label(names[board.kind])
        self.tiles["keyboard"][1].set_label("Confirmed by the keyboard" if board.verified_by_keyboard else "Estimated, not yet asked")


class PerformancePage(Page):
    title = "Performance"
    icon = "power-profile-performance-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.banner = Adw.Banner(title="A restart is needed for a pending firmware change.")
        self.widget.append(self.banner)
        page = design.new_page("Performance", "How hard your laptop works, and how its graphics behave.")
        page.set_vexpand(True)
        self.widget.append(page)
        self.buttons = {}
        self.updating = True

        group = Adw.PreferencesGroup(title="Profile")
        choices = ctx.hw.profile_choices()
        if choices:
            row = design.SegmentedRow("Performance profile", [PROFILE_LABELS.get(c, c.title()) for c in choices])
            for button, choice in zip(row.buttons, choices):
                button.connect("toggled", self._profile_toggled, choice)
                self.buttons[choice] = button
            group.add(row)
        else:
            group.add(Adw.ActionRow(title="Not available", subtitle="This laptop's kernel exposes no platform profile."))
        page.add(group)

        attributes = ctx.hw.armoury_attributes()
        gpu = [a for a in attributes if a["name"] in GPU_ATTRIBUTES]
        power = [a for a in attributes if a["name"].startswith(POWER_PREFIXES)]
        gpu_group = Adw.PreferencesGroup(title="Graphics", description="These changes can blank the screen or need a restart. Each one asks first.")
        self.gpu_row = None
        if ctx.hw.gpu_switch_state():
            self.gpu_row = Adw.ActionRow(title="Discrete GPU")
            self.gpu_button = Gtk.Button(valign=Gtk.Align.CENTER)
            self.gpu_button.connect("clicked", self._gpu_clicked)
            self.gpu_row.add_suffix(self.gpu_button)
            gpu_group.add(self.gpu_row)
        for attribute in gpu:
            gpu_group.add(attribute_row(ctx, attribute, GPU_WARNINGS.get(attribute["name"]), self.refresh))
        if not gpu and not self.gpu_row:
            gpu_group.add(Adw.ActionRow(title="No graphics controls", subtitle="This laptop's kernel exposes none."))
        page.add(gpu_group)

        if power:
            power_group = Adw.PreferencesGroup(title="Power limits", description="Rows without limits from the kernel can't be changed safely, so they stay read-only.")
            for attribute in power:
                power_group.add(attribute_row(ctx, attribute, on_written=self.refresh))
            page.add(power_group)
        self.updating = False
        self.refresh()

    def _prime_op(self, mode):
        helper = self.ctx.helper
        return Op("graphics-mode", "prime-select (Ubuntu's graphics mode tool)", mode, lambda: helper.request(op="prime", mode=mode))

    def _gpu_clicked(self, _button):
        ctx = self.ctx
        state = ctx.hw.gpu_switch_state()
        path = ctx.hw.gpu_switch_path()
        toast = {"automatic": "Now restart the laptop, then come back here.", "off": "Now restart the laptop to finish."}.get(state)

        def done(ok):
            if ok and toast:
                ctx.toast(toast)
            self.refresh()

        if state == "automatic":
            ctx.submit([self._prime_op("intel")], done, GPU_OFF_WARNING)
        elif state == "restart-to-unload":
            ctx.submit([self._prime_op("on-demand")], done)
        elif state == "ready":
            ctx.submit([ctx.write_op("gpu-switch", path, "1")], done, GPU_OFF_NOW_WARNING)
        elif state == "off":
            ctx.submit([ctx.write_op("gpu-switch", path, "0"), self._prime_op("on-demand")], done)

    def _profile_toggled(self, button, choice):
        if self.updating or not button.get_active():
            return

        apply_profile(self.ctx, choice, lambda _ok: self.refresh())

    def refresh(self):
        self.updating = True
        current = self.ctx.hw.profile()
        if current in self.buttons:
            self.buttons[current].set_active(True)
        self.updating = False
        self.banner.set_revealed(self.ctx.hw.pending_reboot())
        if self.gpu_row:
            subtitle, label = GPU_STATES[self.ctx.hw.gpu_switch_state()]
            self.gpu_row.set_subtitle(subtitle)
            self.gpu_button.set_visible(label is not None)
            self.gpu_button.set_label(label or "")


class FansPage(Page):
    title = "Fans"
    icon = "weather-windy-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = page = design.new_page("Fans", "Decide how quickly the fans respond to heat.")
        self.channels = ctx.hw.fan_curve_channels()
        self.channel = self.channels[0][0] if self.channels else None
        self.updating = False
        if not self.channels:
            group = Adw.PreferencesGroup(title="Fans")
            group.add(Adw.ActionRow(title="Custom fan curves aren't available", subtitle="This laptop's kernel exposes no curve device. Fans stay on firmware control."))
            page.add(group)
            return

        select = Adw.PreferencesGroup(title="Fan curve", description="Each fan has 8 points. Drag a point, or focus the chart and use the arrow keys.")
        self.fan_row = design.choice_row("Fan", [name for _n, name in self.channels])
        self.fan_row.connect("notify::selected", self._fan_changed)
        select.add(self.fan_row)
        self.preset_row = design.choice_row("Start from", ["Current"] + list(FAN_PRESETS))
        self.preset_row.connect("notify::selected", self._preset_changed)
        select.add(self.preset_row)
        page.add(select)

        chart_group = Adw.PreferencesGroup()
        frame = Gtk.Frame(css_classes=["view"])
        self.curve = CurveView(self._edited)
        frame.set_child(self.curve)
        chart_group.add(frame)
        self.risk = Gtk.Label(label="This curve runs the fan slowly at high temperature. Watch your temperatures.", wrap=True, xalign=0, visible=False, css_classes=["warning"], margin_top=8)
        chart_group.add(self.risk)
        page.add(chart_group)

        actions = Adw.PreferencesGroup(description="The curve applies to the current profile, and is re-applied when you switch back to it.")
        self.enable_row = Adw.SwitchRow(title="Use this curve", subtitle="Off means the firmware controls the fan.")
        self.enable_row.connect("notify::active", self._enable_changed)
        actions.add(self.enable_row)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=12)
        reset = Gtk.Button(label="Reset to factory curve")
        reset.connect("clicked", self._reset)
        apply_button = Gtk.Button(label="Apply curve", css_classes=["suggested-action"])
        apply_button.connect("clicked", lambda _b: self._apply(True))
        buttons.append(reset)
        buttons.append(apply_button)
        actions.add(buttons)
        page.add(actions)
        self._load()

    def _saved(self):
        profile = self.ctx.hw.profile() or "default"
        return self.ctx.config["fan_curves"].get(profile, {}).get(str(self.channel))

    def _load(self):
        self.updating = True
        saved = self._saved()
        self.curve.set_points(saved["points"] if saved else self.ctx.hw.fan_curve(self.channel))
        self.enable_row.set_active(self.ctx.hw.fan_curve_enabled(self.channel))
        self.preset_row.set_selected(0)
        self.risk.set_visible(effects.curve_is_risky(self.curve.points))
        self.updating = False

    def _fan_changed(self, row, _p):
        self.channel = self.channels[row.get_selected()][0]
        self._load()

    def _preset_changed(self, row, _p):
        if self.updating or row.get_selected() == 0:
            return
        self.curve.morph_to(FAN_PRESETS[list(FAN_PRESETS)[row.get_selected() - 1]])
        self._edited(self.curve.points)

    def _edited(self, points):
        self.risk.set_visible(effects.curve_is_risky(points))

    def ops_for(self, channel, points, enabled=True):
        device = self.ctx.hw.fan_curve_device()
        return [self.ctx.write_op("fan-curve", path, value) for path, value in fan_curve_writes(device, channel, points, enabled)]

    def _apply(self, enabled):
        points = effects.monotonic_curve(self.curve.points)
        warning = "This curve keeps the fan slow at high temperature, so the laptop may run hot or throttle." if effects.curve_is_risky(points) else None
        channel = self.channel

        def done(ok):
            if ok:
                profile = self.ctx.hw.profile() or "default"
                curves = self.ctx.config["fan_curves"]
                curves.setdefault(profile, {})[str(channel)] = {"enabled": enabled, "points": points}
                self.ctx.config.save()
                self.ctx.toast("Fan curve applied.")
            self.updating = True
            self.enable_row.set_active(enabled if ok else self.ctx.hw.fan_curve_enabled(channel))
            self.updating = False

        self.ctx.submit(self.ops_for(channel, points, enabled), done, warning)

    def _enable_changed(self, row, _p):
        if not self.updating:
            self._apply(row.get_active())

    def _reset(self, _button):
        device = self.ctx.hw.fan_curve_device()
        channel = self.channel

        def done(ok):
            if ok:
                profile = self.ctx.hw.profile() or "default"
                self.ctx.config["fan_curves"].get(profile, {}).pop(str(channel), None)
                self.ctx.config.save()
                self._load()

        self.ctx.submit([self.ctx.write_op("fan-curve", f"{device}/pwm{channel}_enable", 3)], done)

    def profile_changed(self, profile):
        """The firmware drops custom curves on a profile change, so put saved ones back."""
        for channel, entry in self.ctx.config["fan_curves"].get(profile, {}).items():
            if entry.get("enabled") and (self.ctx.is_demo or "fan-curve" in self.ctx.config["approved"]):
                self.ctx.submit(self.ops_for(channel, entry["points"]))
        if self.channel:
            self._load()


class SystemPage(Page):
    title = "System"
    icon = "preferences-system-symbolic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.widget = page = design.new_page("System", "Battery, input, display and how the app runs.")
        battery = ctx.hw.battery()
        charging = Adw.PreferencesGroup(title="Battery")
        if battery and battery["limit"] is not None:
            self.limit_row = Adw.SpinRow.new_with_range(20, 100, 5)
            self.limit_row.set_title("Charge limit")
            self.limit_row.set_subtitle("Stopping at around 80% helps a battery that's mostly on AC last longer.")
            self.limit_row.set_value(battery["limit"])
            button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
            button.connect("clicked", self._apply_limit, battery["limit_path"])
            self.limit_row.add_suffix(button)
            charging.add(self.limit_row)
            self.care_values = [100, 80, 60]
            current = self.care_values.index(battery["limit"]) if battery["limit"] in self.care_values else 0
            self.care_row = design.SegmentedRow("Battery care", ["Full", "Balanced", "Longest life"], current, "Full for travel, lower limits for a laptop mostly on AC.")
            self.care_updating = False
            self.care_row.connect("notify::selected", self._care_changed, battery["limit_path"])
            charging.add(self.care_row)
            full = Adw.ActionRow(title="Charge to 100% once", subtitle="Goes back to your limit when full. Needs the app running until then.")
            full_button = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
            full_button.connect("clicked", self._full_charge, battery["limit_path"])
            full.add_suffix(full_button)
            charging.add(full)
        else:
            charging.add(Adw.ActionRow(title="Charge limit isn't available on this laptop"))
        health = ctx.hw.battery_health()
        if health:
            capacity = f"{health['percent']:.0f}% of its original capacity" if health["percent"] else "Capacity not reported"
            cycles = f"{health['cycles']} charge cycles" if health["cycles"] else "Cycles not reported"
            charging.add(Adw.ActionRow(title="Battery health", subtitle=f"{capacity}. {cycles}."))
        page.add(charging)

        desktop = ctx.desktop
        controls = Adw.PreferencesGroup(title="Keyboard and touchpad")
        if desktop.touchpad() is not None:
            row = Adw.SwitchRow(title="Touchpad", active=desktop.touchpad())
            row.connect("notify::active", lambda r, _p: desktop.set_touchpad(r.get_active()))
            controls.add(row)
        if desktop.win_key() is not None:
            row = Adw.SwitchRow(title="Win key opens Activities", subtitle="Turn off so it can't pull you out of a game. Shortcuts such as Win+L still work.", active=desktop.win_key())
            row.connect("notify::active", lambda r, _p: desktop.set_win_key(r.get_active()))
            controls.add(row)
        if desktop.mic_muted() is not None:
            row = Adw.SwitchRow(title="Microphone muted", active=desktop.mic_muted())
            row.connect("notify::active", lambda r, _p: desktop.set_mic_muted(r.get_active()))
            controls.add(row)
        row = Adw.SwitchRow(title="ROG key opens OpenArmoury", subtitle="Adds a desktop shortcut for the key. Fn+F5 changes the fan profile through the kernel, where the laptop supports it.", active=bool(desktop.shortcut("rog-key")))
        row.connect("notify::active", lambda r, _p: desktop.set_shortcut("rog-key", "OpenArmoury", "XF86Launch3" if r.get_active() else "", "openarmoury"))
        controls.add(row)
        page.add(controls)

        self.rates = desktop.refresh_rates()
        display = Adw.PreferencesGroup(title="Display")
        if self.rates and len(self.rates["modes"]) > 1:
            labels = [f"{rate:.0f} Hz" for rate, _id in self.rates["modes"]]
            rates = [rate for rate, _id in self.rates["modes"]]
            self.rate_row = design.choice_row("Refresh rate", labels, rates.index(self.rates["current"]) if self.rates["current"] in rates else 0, "Higher is smoother, and lower saves battery. Resets on restart.")
            self.rate_row.connect("notify::selected", self._rate_changed)
            display.add(self.rate_row)
        night = desktop.night_light()
        if night:
            enabled, temperature = night
            row = Adw.SwitchRow(title="Night light", subtitle="Warmer colours that are easier on your eyes.", active=enabled)
            row.connect("notify::active", lambda r, _p: desktop.set_night_light(r.get_active()))
            display.add(row)
            warm = Adw.SpinRow.new_with_range(1700, 4700, 100)
            warm.set_title("Night light warmth")
            warm.set_subtitle("Kelvin. Lower is warmer.")
            warm.set_value(temperature)
            warm.connect("notify::value", lambda r, _p: desktop.set_night_light(desktop.night_light()[0], r.get_value()))
            display.add(warm)
        page.add(display)

        other = [a for a in ctx.hw.armoury_attributes() if a["name"] not in GPU_ATTRIBUTES and not a["name"].startswith(POWER_PREFIXES)]
        if other:
            firmware = Adw.PreferencesGroup(title="Firmware settings", description="Read directly from the kernel, so the list depends on your laptop.")
            for attribute in other:
                firmware.add(attribute_row(ctx, attribute))
            page.add(firmware)

        startup = Adw.PreferencesGroup(title="Startup")
        self.restore_row = Adw.SwitchRow(
            title="Restore settings at login",
            subtitle="Re-applies your profile, fan curves, charge limit and lighting. Asks for your password at login unless lighting is all that's saved.",
            active=ctx.config["restore_at_login"],
        )
        self.restore_row.connect("notify::active", self._restore_changed)
        startup.add(self.restore_row)
        self.background_row = Adw.SwitchRow(
            title="Keep running after closing the window",
            subtitle="Lets scenarios, battery rules and live lighting carry on, and starts at login if restore is on.",
            active=ctx.config["run_in_background"],
        )
        self.background_row.connect("notify::active", self._background_changed)
        startup.add(self.background_row)
        quit_row = Adw.ActionRow(title="Quit OpenArmoury", subtitle="Stops everything, including background rules.")
        quit_button = Gtk.Button(label="Quit", valign=Gtk.Align.CENTER)
        quit_button.connect("clicked", lambda _b: ctx.window.quit_app())
        quit_row.add_suffix(quit_button)
        startup.add(quit_row)
        page.add(startup)

        backup = Adw.PreferencesGroup(title="Backup", description="Saves your scenarios, macros, presets, curves and rules to a file. Approvals aren't included, so restoring still asks before new kinds of change.")
        row = Adw.ActionRow(title="Settings file")
        export_button = Gtk.Button(label="Save copy", valign=Gtk.Align.CENTER)
        export_button.connect("clicked", self._export)
        import_button = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
        import_button.connect("clicked", self._import)
        row.add_suffix(import_button)
        row.add_suffix(export_button)
        backup.add(row)
        page.add(backup)

        about = Adw.PreferencesGroup(title="About")
        identity = ctx.hw.identity()
        about.add(self._info("Product", identity["product"]))
        about.add(self._info("Board", identity["board"]))
        about.add(self._info("Firmware", identity["bios"]))
        interface = ctx.board.interface
        about.add(self._info("Keyboard interface", f"{interface['node']}, 0b05:{interface['product']}" if interface else "None found"))
        about.add(self._info("Key layouts", "Model data from asusctl (MPL-2.0)"))
        page.add(about)

    @staticmethod
    def _info(title, value):
        row = Adw.ActionRow(title=title)
        row.add_suffix(Gtk.Label(label=value or "–", selectable=True, css_classes=["dim-label"]))
        return row

    def _apply_limit(self, _button, path):
        value = int(self.limit_row.get_value())

        def done(ok):
            if ok:
                self.ctx.config["charge_limit"] = value
                self.ctx.toast(f"Charge limit set to {value}%.")
            self._sync_limit()

        self.ctx.submit([self.ctx.write_op("charge-limit", path, value)], done)

    def _care_changed(self, row, _p, path):
        if not self.care_updating:
            self.limit_row.set_value(self.care_values[row.get_selected()])
            self._apply_limit(None, path)

    def _sync_limit(self):
        """Show the limit the battery really has, so a cancelled change can't look applied."""
        limit = self.ctx.hw.battery()["limit"]
        self.care_updating = True
        self.limit_row.set_value(limit)
        if limit in self.care_values:
            self.care_row.set_selected(self.care_values.index(limit))
        self.care_updating = False

    def _full_charge(self, _button, path):
        battery = self.ctx.hw.battery()
        previous = battery["limit"] if battery else None

        def done(ok):
            if ok and previous and previous < 100:
                self.ctx.config["full_charge_return"] = previous
                self.ctx.toast("Charging to 100%. Your limit comes back when it's full.")

        self.ctx.submit([self.ctx.write_op("charge-limit", path, 100)], done)

    def _rate_changed(self, row, _p):
        _rate, mode_id = self.rates["modes"][row.get_selected()]
        try:
            self.ctx.desktop.set_refresh(mode_id)
        except GLib.Error as err:
            self.ctx.toast(f"Couldn't change the refresh rate: {err.message}")

    def _restore_changed(self, row, _p):
        self.ctx.config["restore_at_login"] = row.get_active()
        set_autostart(row.get_active(), self.ctx.is_demo, self.ctx.config["run_in_background"])

    def _background_changed(self, row, _p):
        self.ctx.config["run_in_background"] = row.get_active()
        set_autostart(self.ctx.config["restore_at_login"], self.ctx.is_demo, row.get_active())
        self.ctx.window.update_background()

    def _export(self, _button):
        dialog = Gtk.FileDialog(initial_name="openarmoury-settings.json")

        def chosen(source, result):
            try:
                target = source.save_finish(result)
            except GLib.Error:
                return
            with open(target.get_path(), "w", encoding="utf-8") as f:
                json.dump(self.ctx.config.export_data(), f, indent=1)
            self.ctx.toast("Settings saved.")

        dialog.save(self.ctx.window, None, chosen)

    def _import(self, _button):
        dialog = Gtk.FileDialog()

        def chosen(source, result):
            try:
                target = source.open_finish(result)
            except GLib.Error:
                return
            try:
                with open(target.get_path(), encoding="utf-8") as f:
                    count = self.ctx.config.import_data(json.load(f))
            except (OSError, ValueError) as err:
                self.ctx.toast(f"Couldn't restore that file: {err}")
                return
            self.ctx.toast(f"Restored {count} settings. Reopen the app to see them.")

        dialog.open(self.ctx.window, None, chosen)


def set_autostart(enabled, is_demo=False, background=False):
    """Add or remove the per-user login entry. A demo session must not change the real login."""
    if is_demo:
        return
    base = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "autostart"
    entry = base / "openarmoury-restore.desktop"
    if not enabled:
        entry.unlink(missing_ok=True)
        return
    command = shutil.which("openarmoury") or "openarmoury"
    base.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=OpenArmoury restore\n"
        f"Exec={command} {'--background' if background else '--restore'}\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n"
    )
