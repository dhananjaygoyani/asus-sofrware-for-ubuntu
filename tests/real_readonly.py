#!/usr/bin/env python3
"""Open the app against the real machine and screenshot it. Sends no writes and never starts the helper.

    xvfb-run -a -s "-screen 0 1280x900x24" env GSK_RENDERER=cairo python3 tests/real_readonly.py OUTPUT_DIR
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from openarmoury.ui.app import App, build_context  # noqa: E402

from gi.repository import GLib, Gtk  # noqa: E402

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


def capture(window, name):
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    window.get_native().get_renderer().render_texture(snapshot.to_node(), None).save_to_png(str(OUT / f"{name}.png"))


def main():
    with tempfile.TemporaryDirectory() as config:
        ctx = build_context(config_dir=config)
        app = App(ctx)
        hw = ctx.hw
        print("identity", {k: hw.identity()[k] for k in ("product", "board", "bios")})
        print("cpu", hw.cpu_temp(), "igpu", hw.igpu_temp(), "fans", hw.fans())
        print("profile", hw.profile(), hw.profile_choices())
        print("curves", hw.fan_curve_channels(), hw.fan_curve(1)[:2])
        print("battery", {k: hw.battery()[k] for k in ("status", "limit")})
        for attribute in hw.armoury_attributes():
            print("attr", attribute["name"], attribute["type"], attribute["value"], attribute["min"], attribute["writable"])
        print("board", ctx.board.kind, ctx.board.zone_count, ctx.board.modes, ctx.board.support and ctx.board.support["device"])
        interface = ctx.board.interface
        print("interface", interface and (interface["node"], interface["product"], interface["transport"]))
        print("conflicts", hw.conflicts())

        def run():
            window = app.window
            names = ["dashboard", "performance", "fans", "lighting", "studio", "system"]

            def step(index=0):
                if index:
                    capture(window, names[index - 1])
                if index == len(names):
                    assert ctx.helper.process is None, "helper was started"
                    print("helper started:", ctx.helper.process is not None)
                    window.close()
                    app.quit()
                    return False
                window.show_page(index)
                GLib.timeout_add(500, step, index + 1)
                return False

            GLib.timeout_add(500, step)
            return False

        app.connect("activate", lambda _a: GLib.idle_add(run))
        app.run([])


main()
