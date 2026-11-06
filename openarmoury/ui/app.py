"""The application window."""
import pathlib
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import demo  # noqa: E402
from ..effects import FRAME_INTERVAL  # noqa: E402
from .context import Context  # noqa: E402
from .automation import Automation  # noqa: E402
from .extras import MacrosPage, MonitorPage, ScenariosPage  # noqa: E402
from .lighting import LightingPage, StudioPage  # noqa: E402
from .pages import DashboardPage, FansPage, PerformancePage, SystemPage  # noqa: E402

APP_ID = "org.openarmoury.App"
WINDOW_BUTTONS = "close,minimize,maximize:"
PAGES = (DashboardPage, PerformancePage, FansPage, LightingPage, StudioPage, ScenariosPage, MonitorPage, MacrosPage, SystemPage)


class Window(Adw.ApplicationWindow):
    def __init__(self, app, ctx):
        super().__init__(application=app, title="OpenArmoury", default_width=1220, default_height=780)
        self.ctx = ctx
        ctx.window = self
        self.app = app
        self.quitting = False
        self.automation = Automation(ctx)
        ctx.monitor.sample()
        self.set_size_request(530, 400)
        self.pages = [page(ctx) for page in PAGES]
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.content_title = Gtk.Label(label=self.pages[0].title, css_classes=["toolbar-title"])
        self.page_enter = "page-enter-a"
        for page in self.pages:
            self.stack.add_named(page.widget, page.title)

        rows = Gtk.ListBox(css_classes=["navigation-sidebar"])
        for page in self.pages:
            box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            box.append(Gtk.Image(icon_name=page.icon))
            box.append(Gtk.Label(label=page.title, xalign=0))
            rows.append(Gtk.ListBoxRow(child=box))
        rows.connect("row-selected", self._row_selected)
        self.rows = rows

        sidebar = Adw.ToolbarView()
        header = Adw.HeaderBar(decoration_layout=WINDOW_BUTTONS, show_title=False)
        sidebar.add_top_bar(header)
        sidebar.set_content(Gtk.ScrolledWindow(child=rows, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        sidebar_page = Adw.NavigationPage(title="OpenArmoury", child=sidebar)

        content = Adw.ToolbarView()
        content_header = Adw.HeaderBar(decoration_layout=WINDOW_BUTTONS, show_title=False)
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
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 700sp"))
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
        self.content_title.set_label(self.active.title)
        # Switching between two identical animations restarts it, even for the same page.
        widget = self.active.widget
        widget.remove_css_class("page-enter-a")
        widget.remove_css_class("page-enter-b")
        self.page_enter = "page-enter-b" if self.page_enter == "page-enter-a" else "page-enter-a"
        widget.add_css_class(self.page_enter)
        self.content_page.set_title(self.active.title)
        self.split.set_show_content(True)
        self.active.refresh()

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
        ctx.monitor.sample()
        self.automation.tick()
        if self.get_mapped():
            self.active.refresh()
        profile = ctx.hw.profile()
        if profile != self.last_profile:
            self.last_profile = profile
            for page in self.pages:
                if isinstance(page, FansPage):
                    page.profile_changed(profile)
        return True

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
