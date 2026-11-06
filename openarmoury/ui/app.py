"""The application window."""
import pathlib
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import demo  # noqa: E402
from . import design  # noqa: E402
from ..effects import FRAME_INTERVAL  # noqa: E402
from .context import Context  # noqa: E402
from .automation import Automation  # noqa: E402
from .extras import MacrosPage, MonitorPage, ScenariosPage  # noqa: E402
from .lighting import LightingPage, StudioPage  # noqa: E402
from .pages import HomePage, FansPage, PerformancePage, SystemPage  # noqa: E402

APP_ID = "org.openarmoury.App"
WINDOW_BUTTONS = "close,minimize,maximize:"
SIDEBAR_COLOURS = {
    "Home": "blue",
    "Performance": "red",
    "Fans": "teal",
    "Lighting": "purple",
    "Light Studio": "pink",
    "Scenarios": "orange",
    "Monitor": "green",
    "Macros": "indigo",
    "System": "gray",
}
ROW_ICONS = {
    "Performance profile": ("power-profile-performance-symbolic", "red"),
    "Turn off discrete GPU": ("video-display-symbolic", "green"),
    "Disable discrete GPU": ("video-display-symbolic", "green"),
    "GPU MUX mode": ("video-display-symbolic", "green"),
    "CPU sustained power limit": ("speedometer-symbolic", "orange"),
    "CPU fast power limit": ("speedometer-symbolic", "red"),
    "Fan": ("weather-windy-symbolic", "teal"),
    "Start from": ("view-list-symbolic", "blue"),
    "Use this curve": ("emblem-ok-symbolic", "green"),
    "Effect": ("starred-symbolic", "purple"),
    "Colour": ("color-select-symbolic", "pink"),
    "Speed": ("speedometer-symbolic", "orange"),
    "Direction": ("object-flip-horizontal-symbolic", "teal"),
    "Area": ("input-keyboard-symbolic", "indigo"),
    "Save to the keyboard": ("document-save-symbolic", "gray"),
    "Level": ("keyboard-brightness-symbolic", "orange"),
    "Run on the keyboard": ("media-playback-start-symbolic", "green"),
    "Brush colour": ("document-edit-symbolic", "pink"),
    "Loop length": ("preferences-system-time-symbolic", "blue"),
    "Spread across the keyboard": ("object-flip-horizontal-symbolic", "teal"),
    "Follow": ("view-list-symbolic", "blue"),
    "Reading now": ("speedometer-symbolic", "green"),
    "Style": ("starred-symbolic", "purple"),
    "Quiet colour": ("audio-volume-low-symbolic", "indigo"),
    "Loud colour": ("audio-volume-high-symbolic", "pink"),
    "Sensitivity": ("audio-input-microphone-symbolic", "orange"),
    "Discrete GPU": ("video-display-symbolic", "green"),
    "Disk temperature": ("drive-harddisk-symbolic", "gray"),
    "Network download": ("go-down-symbolic", "blue"),
    "Network upload": ("go-up-symbolic", "teal"),
    "Battery power": ("battery-full-symbolic", "green"),
    "When plugged in: profile": ("ac-adapter-symbolic", "green"),
    "When plugged in: keyboard brightness": ("keyboard-brightness-symbolic", "orange"),
    "On battery: profile": ("battery-full-symbolic", "green"),
    "On battery: keyboard brightness": ("keyboard-brightness-symbolic", "orange"),
    "Lower the refresh rate on battery": ("video-display-symbolic", "blue"),
    "Charge limit": ("battery-full-symbolic", "green"),
    "Battery care": ("emblem-favorite-symbolic", "pink"),
    "Charge to 100% once": ("battery-full-charging-symbolic", "green"),
    "Battery health": ("emblem-ok-symbolic", "green"),
    "Touchpad": ("input-touchpad-symbolic", "gray"),
    "Win key opens Activities": ("input-keyboard-symbolic", "indigo"),
    "Microphone muted": ("audio-input-microphone-symbolic", "red"),
    "ROG key opens OpenArmoury": ("input-keyboard-symbolic", "red"),
    "Refresh rate": ("video-display-symbolic", "blue"),
    "Night light": ("night-light-symbolic", "orange"),
    "Night light warmth": ("night-light-symbolic", "orange"),
    "Boot sound": ("audio-volume-high-symbolic", "pink"),
    "Charging source": ("ac-adapter-symbolic", "green"),
    "Panel overdrive": ("video-display-symbolic", "teal"),
    "Restore settings at login": ("system-reboot-symbolic", "blue"),
    "Keep running after closing the window": ("emblem-synchronizing-symbolic", "blue"),
    "Quit OpenArmoury": ("application-exit-symbolic", "red"),
    "Settings file": ("document-save-symbolic", "gray"),
    "Product": ("computer-symbolic", "gray"),
    "Board": ("computer-symbolic", "gray"),
    "Firmware": ("computer-symbolic", "gray"),
    "Keyboard interface": ("input-keyboard-symbolic", "indigo"),
    "Key layouts": ("input-keyboard-symbolic", "gray"),
}
PAGES = (HomePage, PerformancePage, FansPage, LightingPage, StudioPage, ScenariosPage, MonitorPage, MacrosPage, SystemPage)


class Window(Adw.ApplicationWindow):
    def __init__(self, app, ctx):
        super().__init__(application=app, title="OpenArmoury", default_width=1220, default_height=780)
        self.ctx = ctx
        ctx.window = self
        self.app = app
        self.quitting = False
        self.automation = Automation(ctx)
        self.sampling = False
        ctx.monitor.sample()
        ctx.monitor.sample_slow()
        self.set_size_request(580, 400)
        self.pages = [page(ctx) for page in PAGES]
        self.stack = design.GlideStack()
        self.content_title = Gtk.Label(label=self.pages[0].title, css_classes=["toolbar-title", "hidden-title"])
        for page in self.pages:
            self.stack.add_named(page.widget, page.title)

        rows = Gtk.ListBox(css_classes=["sidebar-list"])
        for page in self.pages:
            design.decorate_rows(page.widget, ROW_ICONS)
            box = Gtk.Box(spacing=10)
            colour = SIDEBAR_COLOURS.get(page.title, "blue")
            box.append(design.icon_badge(page.icon, colour, 24))
            box.append(Gtk.Label(label=page.title, xalign=0))
            rows.append(Gtk.ListBoxRow(child=box))
        rows.connect("row-selected", self._row_selected)
        self.rows = rows

        sidebar = Adw.ToolbarView()
        header = Adw.HeaderBar(decoration_layout=WINDOW_BUTTONS, show_title=False)
        sidebar.add_top_bar(header)
        self.sidebar_group = design.GlideGroup(rows, "accent", 10)
        self.sidebar_group.set_margin_start(10)
        self.sidebar_group.set_margin_end(10)
        self.sidebar_group.set_valign(Gtk.Align.START)
        sidebar.set_content(Gtk.ScrolledWindow(child=self.sidebar_group, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        sidebar.add_css_class("sidebar-panel")
        sidebar_page = Adw.NavigationPage(title="OpenArmoury", child=sidebar, css_classes=["sidebar-pane"])

        content = Adw.ToolbarView()
        content_header = Adw.HeaderBar(decoration_layout=WINDOW_BUTTONS, show_title=False, css_classes=["content-header"])
        content_header.pack_start(self.content_title)
        content.add_top_bar(content_header)
        self.toasts = Adw.ToastOverlay(child=self.stack)
        ctx.toasts = self.toasts
        if ctx.is_demo:
            banner = Adw.Banner(title="Demo mode: a simulated laptop. Nothing here touches real hardware.", revealed=True)
            content.add_top_bar(banner)
        content.set_content(self.toasts)
        self.content_page = Adw.NavigationPage(title=self.pages[0].title, child=content)

        self.split = Adw.NavigationSplitView(sidebar=sidebar_page, content=self.content_page)
        self.set_content(self.split)
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 860sp"))
        breakpoint_.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint_)

        self.active = self.pages[0]
        self.last_profile = ctx.hw.profile()
        self.start_time = time.monotonic()
        rows.select_row(rows.get_row_at_index(0))
        self.frame_source = GLib.timeout_add(int(FRAME_INTERVAL * 1000), self._frame)
        self.slow_source = GLib.timeout_add_seconds(2, self._slow)
        self.connect("close-request", self._closing)

    def show_page(self, title):
        index = next(i for i, page in enumerate(self.pages) if page.title == title)
        self.rows.select_row(self.rows.get_row_at_index(index))

    def update_background(self):
        self.app.set_background(self.ctx.config["run_in_background"])

    def quit_app(self):
        self.quitting = True
        self.close()

    def _row_selected(self, _rows, row):
        if not row:
            return
        self.active = self.pages[row.get_index()]
        self.stack.set_visible_child_name(self.active.title)
        self.sidebar_group.select(row)
        self.content_title.set_label(self.active.title)
        self._watch_scroll(self.active.widget)
        self.content_page.set_title(self.active.title)
        self.split.set_show_content(True)
        self.active.refresh()

    def _watch_scroll(self, widget):
        """The toolbar title fades in once the page's large title has scrolled away."""
        scroller = widget if isinstance(widget, Gtk.ScrolledWindow) else next((c for c in design.descendants(widget) if isinstance(c, Gtk.ScrolledWindow)), None)
        if scroller is None or isinstance(self.active, StudioPage):
            self.content_title.add_css_class("hidden-title")
            return
        adjustment = scroller.get_vadjustment()
        if not getattr(adjustment, "watched", False):
            adjustment.watched = True
            adjustment.connect("value-changed", self._scrolled, widget)
        self._scrolled(adjustment, widget)

    def _scrolled(self, adjustment, widget):
        if widget is self.active.widget:
            if adjustment.get_value() > 48:
                self.content_title.remove_css_class("hidden-title")
            else:
                self.content_title.add_css_class("hidden-title")

    def _frame(self):
        now = time.monotonic() - self.start_time
        self.ctx.tick_live(now)
        if self.get_mapped() and hasattr(self.active, "view"):
            self.active.tick(now)
        return True

    def _slow(self):
        ctx = self.ctx
        if ctx.is_demo:
            demo.tick(ctx.demo_root, ctx.hw.profile())
        if not self.sampling:
            self.sampling = True
            threading.Thread(target=self._sample, daemon=True).start()
        profile = ctx.hw.profile()
        if profile != self.last_profile:
            self.last_profile = profile
            for page in self.pages:
                if isinstance(page, FansPage):
                    page.profile_changed(profile)
        return True

    def _sample(self):
        """Slow readings on a background thread, so the screen never waits for them."""
        self.ctx.monitor.sample()
        self.ctx.monitor.sample_slow()
        GLib.idle_add(self._sampled)

    def _sampled(self):
        self.sampling = False
        self.automation.tick()
        if self.get_mapped():
            self.active.refresh()
        return False

    def _closing(self, _window):
        if self.ctx.config["run_in_background"] and not self.quitting:
            self.set_visible(False)
            return True
        self.app.set_background(False)
        GLib.source_remove(self.frame_source)
        GLib.source_remove(self.slow_source)
        self.ctx.close()
        return False


class App(Adw.Application):
    def __init__(self, ctx, start_hidden=False, unique=True):
        # Not unique: otherwise a demo or test would hand off to a running real window.
        flags = Gio.ApplicationFlags.DEFAULT_FLAGS if unique and not ctx.is_demo else Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.ctx = ctx
        self.window = None
        self.start_hidden = start_hidden
        self.holding = False

    def _load_theme(self):
        """A base theme, plus light or dark colours that follow the system setting."""
        display = Gdk.Display.get_default()
        manager = Adw.StyleManager.get_default()
        self.colours = None
        priority = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION

        def apply_colours(*_args):
            if self.colours:
                Gtk.StyleContext.remove_provider_for_display(display, self.colours)
            self.colours = _css("theme-dark.css" if manager.get_dark() else "theme-light.css")
            Gtk.StyleContext.add_provider_for_display(display, self.colours, priority)

        Gtk.StyleContext.add_provider_for_display(display, _css("theme.css"), priority)
        apply_colours()
        manager.connect("notify::dark", apply_colours)

    def set_background(self, enabled):
        """Keep the app alive with no window open."""
        if enabled and not self.holding:
            self.hold()
            self.holding = True
        elif not enabled and self.holding:
            self.release()
            self.holding = False

    def do_activate(self):
        if not self.window:
            self._load_theme()
            Gtk.Window.set_default_icon_name(APP_ID)
            self.window = Window(self, self.ctx)
            self.window.update_background()
        if self.start_hidden:
            self.start_hidden = False
            return
        self.window.present()


def _css(name):
    provider = Gtk.CssProvider()
    provider.load_from_path(str(pathlib.Path(__file__).with_name(name)))
    return provider


def build_context(demo_root=None, config_dir=None):
    from ..config import Config
    from ..desktop import FakeDesktop, GnomeDesktop
    from ..system import Hardware
    from ..writer import Helper, Writer

    root = demo_root or ""
    helper = Helper(test_root=demo_root)
    desktop = FakeDesktop() if demo_root else GnomeDesktop()
    return Context(Hardware(root), Config(config_dir), helper, Writer(helper, root), desktop, demo_root)
