#!/usr/bin/env python3
"""Open every page in demo mode, exercise it, and save screenshots. Run under Xvfb:

    xvfb-run -a -s "-screen 0 1280x900x24" env GSK_RENDERER=cairo python3 tests/shots.py OUTPUT_DIR
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from openarmoury import demo  # noqa: E402
from openarmoury.ui.app import App, build_context  # noqa: E402
from openarmoury.ui.pages import FAN_PRESETS  # noqa: E402
from gi.repository import Adw, GLib, Gtk  # noqa: E402

SETTINGS_ANIMATIONS = "gtk-enable-animations"

GPU_ATTRIBUTE = "/sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
errors = []
finished = []


def _rows(widget):
    """Every descendant of a widget."""
    child = widget.get_first_child()
    while child:
        yield child
        yield from _rows(child)
        child = child.get_next_sibling()


def page_named(window, title):
    return next(page for page in window.pages if page.title == title)


def capture(window, name):
    paintable = Gtk.WidgetPaintable.new(window)
    width, height = window.get_width(), window.get_height()
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    texture = window.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(str(OUT / f"{name}.png"))
    print("saved", name)


def scenario(app):
    """A generator: each yield lets the UI settle for that many milliseconds."""
    window = app.window
    ctx = app.ctx
    for title in ("Home", "Performance", "Fans", "Lighting", "Light Studio", "Scenarios", "Monitor", "Macros", "System"):
        window.show_page(title)
        yield 700
        capture(window, title.lower().replace(" ", "-"))

    # Home: a mode tile changes the profile, and the tiles follow changes made elsewhere.
    window.show_page("Home")
    home = page_named(window, "Home")
    home.mode_buttons["performance"].set_active(True)
    yield 400
    assert ctx.hw.profile() == "performance", "mode tile did not change the profile"
    assert all(g.value is not None for g in home.gauges.values()), "a gauge has no reading"
    yield 800
    assert all(abs(g.shown - g.value) < 1 for g in home.gauges.values()), "a gauge didn't finish animating"
    capture(window, "home-performance")
    window.show_page("Performance")
    page_named(window, "Performance").buttons["balanced"].set_active(True)
    yield 400
    window.show_page("Home")
    yield 200
    assert home.mode_buttons["balanced"].get_active(), "mode tile out of step"

    # Performance: change the profile through the helper, into the mock tree.
    window.show_page("Performance")
    performance = page_named(window, "Performance")
    performance.buttons["quiet"].set_active(True)
    yield 400
    assert ctx.hw.profile() == "quiet", "profile write did not reach the mock"

    # Fans: drag-equivalent edit, apply, and check monotonic values landed.
    window.show_page("Fans")
    fans = page_named(window, "Fans")
    fans.preset_row.set_selected(3)
    assert fans.curve.points == FAN_PRESETS["Cool"], "preset must be the target straight away"
    yield 500
    assert fans.curve.drawn is None, "curve animation didn't finish"
    fans._apply(True)
    yield 500
    assert ctx.hw.fan_curve_enabled(1), "curve not enabled"
    points = ctx.hw.fan_curve(1)
    assert points == sorted(points), "curve not monotonic"
    capture(window, "fans-applied")

    # Profile change re-applies a saved curve.
    window.last_profile = None
    window._slow()
    yield 300

    # Lighting: ask the mock keyboard, then apply an effect and check packets.
    window.show_page("Lighting")
    lighting = page_named(window, "Lighting")
    ctx.detect_keyboard()
    yield 500
    assert ctx.board.verified_by_keyboard, "handshake failed"
    lighting.mode_row.set_selected(lighting.modes.index("Breathe"))
    lighting._apply(None)
    yield 400
    log = pathlib.Path(ctx.demo_root + "/dev/hidraw0").read_text().splitlines()
    assert any(" 5db30001" in line for line in log), "effect packet not sent"
    assert not any(" 5db4" in line for line in log), "flash packet sent without being asked"
    capture(window, "lighting-detected")

    # Studio: run live for a second and check the packets and rate.
    window.show_page("Light Studio")
    studio = page_named(window, "Light Studio")
    before = len(pathlib.Path(ctx.demo_root + "/dev/hidraw0").read_text().splitlines())
    studio.live_row.set_active(True)
    yield 2000
    log = pathlib.Path(ctx.demo_root + "/dev/hidraw0").read_text().splitlines()[before:]
    studio.live_row.set_active(False)
    yield 300
    after = pathlib.Path(ctx.demo_root + "/dev/hidraw0").read_text().splitlines()
    assert any(" 5db3" in line for line in after[-3:]), "saved effect not restored after live"
    print("live packets in 2s:", len(log))
    assert log and all(" 5dbc" in line for line in log), "live stream sent a non-direct packet"
    assert len(log) <= 32, f"live stream too fast: {len(log)} packets in 2s"
    capture(window, "studio-live")
    for name in ("paint", "smart", "presets"):
        studio.stack.set_visible_child_name(name)
        yield 300
        capture(window, f"studio-{name}")
    studio.stack.set_visible_child_name("paint")
    studio._paint_key(ctx.board.light_keys()[10])
    yield 200

    # Power states go through the helper and the mock keyboard.
    window.show_page("Lighting")
    lighting._apply_power(None)
    yield 400
    assert any(" 5dbd01" in line for line in pathlib.Path(ctx.demo_root + "/dev/hidraw0").read_text().splitlines()), "power state not sent"

    # Music: the audio level drives the effect, and the fake meter is used in demo mode.
    window.show_page("Light Studio")
    studio.stack.set_visible_child_name("music")
    yield 400
    capture(window, "studio-music")
    assert studio.effect["kind"] == "music"
    studio.stack.set_visible_child_name("smart")
    yield 200

    # Scenarios: a running program switches the profile, and ending it puts your setting back.
    window.show_page("Scenarios")
    ctx.hw.profile()
    original = ctx.hw.profile()
    target = "performance" if original != "performance" else "quiet"
    ctx.config["scenarios"] = [{"name": "Browser", "match": "firefox", "enabled": True, "profile": target, "touchpad": False}]
    page_named(window, "Scenarios")._rebuild()
    window.automation.tick()
    yield 400
    assert ctx.hw.profile() == target, "scenario did not switch profile"
    assert ctx.desktop.touchpad() is False, "scenario did not turn the touchpad off"
    capture(window, "scenarios-active")
    ctx.config["scenarios"] = [{"name": "Browser", "match": "firefox", "enabled": False, "profile": target}]
    window.automation.tick()
    yield 400
    assert ctx.hw.profile() == original and ctx.desktop.touchpad() is True, "settings not restored"
    ctx.config["scenarios"] = []
    page_named(window, "Scenarios")._rebuild()

    # Macros: playback goes through the helper, and the helper logs it in demo mode.
    window.show_page("Macros")
    ctx.config["macros"] = {"Hello": [[35, 1, 0], [35, 0, 40]]}
    macros = page_named(window, "Macros")
    macros._rebuild()
    macros._play(ctx.config["macros"]["Hello"])
    yield 400
    assert "[35, 1, 0]" in pathlib.Path(ctx.demo_root + "/dev/uinput").read_text(), "macro not played"
    capture(window, "macros-saved")

    # The monitor has real history after a few samples.
    window.show_page("Monitor")
    for _ in range(3):
        window._slow()
        yield 150
    capture(window, "monitor-live")

    # The gate. Demo mode skips it, so switch that off and check Cancel and Write really behave.
    Context = type(ctx)
    Context.is_demo = property(lambda _self: False)
    ctx.config["approved"] = []
    window.show_page("System")
    limit = "/sys/class/power_supply/BAT0/charge_control_end_threshold"
    results = []
    ctx.submit([ctx.write_op("charge-limit", limit, 70)], results.append)
    yield 400
    dialog = window.get_visible_dialog()
    assert dialog is not None, "first write did not ask"
    capture(window, "gate")
    dialog.close()
    yield 400
    assert results == [False], "cancel was not reported"
    assert ctx.hw.battery()["limit"] != 70, "cancel still wrote"
    assert "charge-limit" not in ctx.config["approved"], "cancel recorded approval"

    ctx.submit([ctx.write_op("charge-limit", limit, 70)], results.append)
    yield 400
    dialog = window.get_visible_dialog()
    dialog.emit("response", "write")
    dialog.force_close()
    yield 400
    assert ctx.hw.battery()["limit"] == 70, "approved write did not happen"
    assert "charge-limit" in ctx.config["approved"], "approval not saved"

    ctx.submit([ctx.write_op("charge-limit", limit, 75)], results.append)
    yield 400
    assert window.get_visible_dialog() is None, "asked twice for the same kind of change"
    assert ctx.hw.battery()["limit"] == 75

    # A warning always asks, even when already approved.
    ctx.submit([ctx.write_op("charge-limit", limit, 80)], results.append, warning="Test warning")
    yield 400
    dialog = window.get_visible_dialog()
    assert dialog is not None, "warning did not ask"
    dialog.close()
    yield 300
    assert ctx.hw.battery()["limit"] == 75

    # Cancelling a mode tile puts it back on the real mode.
    window.show_page("Home")
    yield 200
    before = ctx.hw.profile()
    other = next(c for c in home.mode_buttons if c != before)
    ctx.config["approved"] = []
    home.mode_buttons[other].set_active(True)
    yield 400
    dialog = window.get_visible_dialog()
    assert dialog is not None, "mode tile skipped the gate"
    dialog.close()
    yield 400
    assert home.mode_buttons[before].get_active() and ctx.hw.profile() == before, "tile stayed on a cancelled mode"

    # Cancelling a switch puts it back, so it can't claim a change that didn't happen.
    window.show_page("Performance")
    yield 200
    switch = next(r for r in _rows(page_named(window, "Performance").widget) if isinstance(r, Adw.SwitchRow))
    switch.set_active(True)
    yield 400
    dialog = window.get_visible_dialog()
    assert dialog is not None and "freeze" in dialog.get_body(), "GPU warning not shown"
    capture(window, "gate-gpu")
    dialog.close()
    yield 400
    assert not switch.get_active(), "switch stayed on after cancel"
    assert ctx.hw.read(GPU_ATTRIBUTE) == "0", "cancel still wrote"
    window.show_page("System")

    # Uncertain operations name their reason before anything is sent.
    ctx.submit([ctx.hid_op("save", bytes.fromhex("5db4").ljust(64, b"\x00"), ctx.board.uncertain_reason("save"))], results.append)
    yield 400
    dialog = window.get_visible_dialog()
    assert dialog is not None and "flash" in dialog.get_body(), "uncertain reason not shown"
    capture(window, "gate-uncertain")
    dialog.close()
    yield 300
    assert not any(" 5db4" in line for line in pathlib.Path(ctx.demo_root + "/dev/hidraw0").read_text().splitlines())
    Context.is_demo = property(lambda self: self.demo_root is not None)

    # Both colour schemes.
    manager = Adw.StyleManager.get_default()
    window.show_page("Home")
    for scheme, name in ((Adw.ColorScheme.FORCE_LIGHT, "home-light"), (Adw.ColorScheme.FORCE_DARK, "home-dark")):
        manager.set_color_scheme(scheme)
        yield 900
        capture(window, name)
    manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    yield 300
    window.show_page("Fans")
    yield 600
    capture(window, "fans-light")
    window.show_page("Lighting")
    yield 600
    capture(window, "lighting-light")
    window.show_page("Light Studio")
    yield 600
    capture(window, "studio-light")
    window.show_page("System")
    yield 600
    capture(window, "system-light")
    manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    # With animations off everything still lands immediately on the right values.
    Gtk.Settings.get_default().set_property(SETTINGS_ANIMATIONS, False)
    window.show_page("Home")
    yield 100
    window._slow()
    assert all(abs(g.shown - g.value) < 1 for g in home.gauges.values()), "gauges animate with animations off"
    window.show_page("Fans")
    fans.preset_row.set_selected(1)
    assert fans.curve.drawn is None, "curve animates with animations off"
    Gtk.Settings.get_default().set_property(SETTINGS_ANIMATIONS, True)

    # Narrow window: the sidebar should collapse rather than overflow.
    window.set_default_size(530, 700)
    yield 500
    capture(window, "narrow")


def drive(app):
    steps = scenario(app)

    def advance():
        try:
            delay = next(steps)
        except StopIteration:
            finished.append(True)
            app.window.close()
            app.quit()
            return False
        except Exception as err:  # report and stop, so a failure can't hang the run
            import traceback

            traceback.print_exc()
            errors.append(err)
            app.quit()
            return False
        GLib.timeout_add(delay, advance)
        return False

    GLib.timeout_add(600, advance)
    return False


def main():
    with tempfile.TemporaryDirectory(prefix="oa-shots-") as root:
        demo.build(root)
        ctx = build_context(demo_root=root, config_dir=root + "/config")
        app = App(ctx)
        app.connect("activate", lambda a: GLib.idle_add(drive, a))
        app.run([])
    if errors or not finished:
        print("scenario did not finish", file=sys.stderr)
        sys.exit(1)
    print("all scenarios passed")


main()
