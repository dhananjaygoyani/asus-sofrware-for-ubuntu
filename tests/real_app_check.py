#!/usr/bin/env python3
"""Drive the real app window against the real laptop, restoring settings afterwards.

Run under Xvfb. Asks for your password. It saves your saved lighting effect to keyboard flash, and sends a
lighting power state. It never turns off the GPU.
"""
import copy
import json
import math
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from openarmoury.config import Config, config_dir  # noqa: E402
from openarmoury.system import fan_curve_writes  # noqa: E402
from openarmoury.ui.app import App, build_context  # noqa: E402
from openarmoury.ui.pages import set_autostart  # noqa: E402

from gi.repository import GLib  # noqa: E402

ALL_KINDS = ["profile", "charge-limit", "brightness", "fan-curve", "effect", "zone-effect", "save", "direct", "power-state", "macro", "detect"]
results = []
finished = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def page(window, title):
    return next(p for p in window.pages if p.title == title)


def tone(path):
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(struct.pack("<h", int(5000 * math.sin(i * 0.2))) for i in range(32000)))


def scenario(app, original):
    window, ctx = app.window, app.ctx
    hw = ctx.hw

    # Home mode tiles
    window.show_page("Home")
    yield 800
    home = page(window, "Home")
    other = next(c for c in hw.profile_choices() if c != original["profile"])
    print("waiting for your password if asked...", flush=True)
    home.mode_buttons[other].set_active(True)
    for _wait in range(1200):
        if hw.profile() == other:
            break
        yield 100
    check("Home tile changes the mode", hw.profile() == other, f"{original['profile']} -> {hw.profile()}")
    home.mode_buttons[original["profile"]].set_active(True)
    yield 800
    check("Home tile changes it back", hw.profile() == original["profile"])

    # Fans page
    window.show_page("Fans")
    yield 500
    fans = page(window, "Fans")
    before = dict(hw.fans())
    fans.preset_row.set_selected(3)
    fans._apply(True)
    yield 1500
    check("Fans page turns on a Cool curve", hw.fan_curve_enabled(fans.channel))
    yield 15000
    check("Fans follow the curve", any(dict(hw.fans())[n] > before[n] for n in before), f"{before} -> {dict(hw.fans())}")
    fans._reset(None)
    yield 1000
    check("Fans page resets to factory", not hw.fan_curve_enabled(fans.channel))

    # Battery care
    window.show_page("System")
    yield 500
    system_page = page(window, "System")
    system_page.care_row.set_selected(1)
    yield 1200
    check("Battery care sets Balanced", hw.battery()["limit"] == 80, str(hw.battery()["limit"]))
    system_page.care_row.set_selected(0)
    yield 1200
    check("Battery care returns to Full", hw.battery()["limit"] == 100)

    # Lighting page, including saving your own effect to the keyboard's flash
    window.show_page("Lighting")
    yield 500
    lighting = page(window, "Lighting")
    level = hw.brightness()
    lighting.brightness_row.set_selected((level + 2) % 4)
    yield 800
    check("Brightness control", hw.brightness() == (level + 2) % 4, str(hw.brightness()))
    lighting.brightness_row.set_selected(level)
    yield 800
    lighting.save_row.set_active(True)
    lighting._apply(None)
    yield 1500
    check("Effect with Save to the keyboard is accepted", ctx.config["lighting"] and ctx.config["lighting"]["save"])
    lighting.save_row.set_active(False)

    # Boot, awake and sleep lighting. Keyboard goes dark for a few seconds, then everything returns on.
    print("keyboard lights should go off for 4 seconds now", flush=True)
    lighting.power_rows[("keyboard", "awake")].set_active(False)
    lighting._apply_power(None)
    yield 4000
    check("Power state with keyboard off is accepted", ctx.config["power_states"]["keyboard"]["awake"] is False)
    lighting.power_rows[("keyboard", "awake")].set_active(True)
    lighting._apply_power(None)
    yield 1500
    check("Power state with everything on is accepted", ctx.config["power_states"]["keyboard"]["awake"] is True)

    # Live lighting from the Studio, for real
    window.show_page("Light Studio")
    yield 500
    studio = page(window, "Light Studio")
    studio.stack.set_visible_child_name("keyframes")
    yield 300
    studio.live_row.set_active(True)
    yield 3000
    check("Live lighting runs", ctx.live_effect is not None)
    studio.live_row.set_active(False)
    yield 1000
    check("Live lighting stops", ctx.live_effect is None)

    # Music: play a short tone and see the app's meter hear it
    studio.stack.set_visible_child_name("music")
    yield 800
    check("Music tab listens", ctx.meter.process is not None)
    with tempfile.TemporaryDirectory() as folder:
        path = f"{folder}/tone.wav"
        tone(path)
        player = subprocess.Popen(["pw-play", "--volume=0.25", path])
        peak = 0.0
        for _step in range(18):
            yield 100
            peak = max(peak, ctx.meter.level)
        player.wait(timeout=5)
    check("Sound moves the music effect", peak > 0.005, f"peak level {peak:.3f}")
    studio.stack.set_visible_child_name("paint")
    yield 500
    check("Listening stops when the effect isn't music", ctx.meter.process is None)

    # A real program starting and stopping
    window.show_page("Scenarios")
    start = hw.profile()
    target = next(c for c in hw.profile_choices() if c != start)
    ctx.config["scenarios"] = [{"name": "Test", "match": "oa-scenario-test", "profile": target, "touchpad": False}]
    program = subprocess.Popen(["bash", "-c", "exec -a oa-scenario-test sleep 300"])
    yield 6000
    check("Scenario switches the mode when its program runs", hw.profile() == target, hw.profile())
    check("Scenario turns the touchpad off", ctx.desktop.touchpad() is False)
    program.terminate()
    program.wait(timeout=5)
    yield 6000
    check("Mode returns when the program closes", hw.profile() == start, hw.profile())
    check("Touchpad returns when the program closes", ctx.desktop.touchpad() is True)

    # Plugged-in rule, which applies now as the laptop is charging
    ctx.config["scenarios"] = []
    check("Laptop reports it's plugged in", not hw.on_battery())
    ctx.config["power_rules"] = {"ac": {"profile": target}, "battery": {}}
    yield 5000
    check("Plugged-in rule applies", hw.profile() == target, hw.profile())
    ctx.config["power_rules"] = {"ac": {}, "battery": {}}
    yield 5000
    check("Mode returns when the rule is removed", hw.profile() == start, hw.profile())

    # NVIDIA readings in the app
    subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=20, check=False)
    ctx.monitor.next_gpu_poll = 0
    window.show_page("Monitor")
    yield 6000
    label = page(window, "Monitor").rows["gpu_temp"].get_label()
    check("Monitor shows the GPU temperature when awake", label.endswith("°C"), label)
    print("waiting for the GPU to fall asleep with the app open...", flush=True)
    asleep = False
    for _wait in range(50):
        yield 1000
        if ctx.monitor.discrete_gpu()["state"] == "suspended":
            asleep = True
            break
    check("GPU falls asleep with the app polling", asleep)
    yield 3000
    check("Monitor clears GPU readings when it sleeps", page(window, "Monitor").rows["gpu_temp"].get_label() == "–")

    # Background: close the window, and rules keep working
    ctx.config["run_in_background"] = True
    window.update_background()
    window.close()
    yield 1000
    check("Window closes, app keeps running", not window.get_visible())
    ctx.config["scenarios"] = [{"name": "Test", "match": "oa-scenario-test", "profile": target}]
    program = subprocess.Popen(["bash", "-c", "exec -a oa-scenario-test sleep 300"])
    yield 6000
    check("Scenarios work with the window closed", hw.profile() == target, hw.profile())
    program.terminate()
    program.wait(timeout=5)
    yield 6000
    check("Mode returns with the window closed", hw.profile() == start, hw.profile())
    ctx.config["scenarios"] = []
    ctx.config["run_in_background"] = False


def drive(app, original):
    steps = scenario(app, original)

    def advance():
        try:
            delay = next(steps)
        except StopIteration:
            finished.append(True)
            app.window.quit_app()
            app.quit()
            return False
        except Exception as err:  # still restore below
            import traceback

            traceback.print_exc()
            check("scenario stopped early", False, repr(err))
            app.window.quit_app()
            app.quit()
            return False
        GLib.timeout_add(delay, advance)
        return False

    GLib.timeout_add(800, advance)
    return False


def main():
    real = Config()
    with tempfile.TemporaryDirectory(prefix="oa-real-") as folder:
        temp = pathlib.Path(folder) / "config"
        temp.mkdir()
        data = copy.deepcopy(real.data)
        data.update(approved=ALL_KINDS, scenarios=[], power_rules={"ac": {}, "battery": {}}, run_in_background=False, restore_at_login=False)
        (temp / "config.json").write_text(json.dumps(data))
        ctx = build_context(config_dir=temp)
        hw = ctx.hw
        original = {"profile": hw.profile(), "limit": hw.battery()["limit"], "brightness": hw.brightness(), "touchpad": ctx.desktop.touchpad()}
        # Your own fan curves must survive this test, so remember them too.
        original_curves = {c: (hw.fan_curve_enabled(c), hw.fan_curve(c)) for c, _n in hw.fan_curve_channels()}
        print("starting from", original, flush=True)
        app = App(ctx, unique=False)
        app.connect("activate", lambda a: GLib.idle_add(drive, a, original))
        try:
            app.run([])
        finally:
            # Whatever happened, put everything back.
            helper_ctx = build_context(config_dir=temp)
            writes = []
            if hw.profile() != original["profile"]:
                writes.append(("/sys/firmware/acpi/platform_profile", original["profile"]))
            if hw.battery()["limit"] != original["limit"]:
                writes.append((hw.battery()["limit_path"], original["limit"]))
            if hw.brightness() != original["brightness"]:
                writes.append(("/sys/class/leds/asus::kbd_backlight/brightness", original["brightness"]))
            device = hw.fan_curve_device()
            for channel, (enabled, points) in original_curves.items():
                if enabled:
                    writes += fan_curve_writes(device, channel, points)
                elif hw.fan_curve_enabled(channel):
                    writes.append((f"{device}/pwm{channel}_enable", 3))
            for path, value in writes:
                helper_ctx.writer.write(path, value)
            helper_ctx.helper.close()
            ctx.desktop.set_touchpad(original["touchpad"])
            print("restored", writes, flush=True)

        # Command line entry points, against a throwaway config
        restore_dir = pathlib.Path(folder) / "xdg" / "openarmoury"
        restore_dir.mkdir(parents=True)
        (restore_dir / "config.json").write_text(json.dumps({"restore_at_login": True, "profile": original["profile"], "approved": ["profile"]}))
        env = {**os.environ, "XDG_CONFIG_HOME": str(restore_dir.parent), "PYTHONPATH": str(pathlib.Path(__file__).resolve().parent.parent)}
        run = subprocess.run([sys.executable, "-m", "openarmoury", "--restore"], env=env, capture_output=True, text=True, timeout=120, check=False)
        check("--restore works", run.returncode == 0, run.stderr.strip()[:200])
        (restore_dir / "config.json").write_text(json.dumps({"macros": {"Shift": [[42, 1, 0], [42, 0, 40]]}}))
        run = subprocess.run([sys.executable, "-m", "openarmoury", "--macro", "shift"], env=env, capture_output=True, text=True, timeout=120, check=False)
        check("--macro plays a macro", run.returncode == 0, run.stderr.strip()[:200])

    # The login entry, written and removed for real
    entry = config_dir().parent / "autostart" / "openarmoury-restore.desktop"
    existed = entry.exists()
    saved = entry.read_text() if existed else None
    set_autostart(True, False, True)
    check("Login entry is written", "--background" in entry.read_text() and shutil.which("openarmoury"))
    set_autostart(False)
    check("Login entry is removed", not entry.exists())
    if saved is not None:
        entry.write_text(saved)

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed: {failed}", flush=True)
    return 1 if failed or not finished else 0


sys.exit(main())
