#!/usr/bin/env python3
"""Test real writes through the installed helper, restoring every setting afterwards. Run on the real laptop.

Asks for your password once. It never touches: turning off the GPU, saving to the keyboard's flash, or
boot and sleep lighting. Those can freeze the laptop or last beyond this test.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from openarmoury import hid, monitor, packets, system  # noqa: E402
from openarmoury.config import Config  # noqa: E402
from openarmoury.writer import Helper, Writer  # noqa: E402

hw = system.Hardware()
helper = Helper()
writer = Writer(helper)
results = []
restore = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def write_and_verify(name, path, value):
    original = hw.read(path)
    restore.append((path, original))
    writer.write(path, value)
    time.sleep(0.4)
    check(name, hw.read(path) == str(value), f"{original} -> {hw.read(path)}")


def fans():
    return dict(hw.fans())


def main():
    start = time.time()
    profile = hw.profile()
    for choice in hw.profile_choices():
        write_and_verify(f"profile {choice}", system.PROFILE, choice)
    writer.write(system.PROFILE, profile)
    check("profile restored", hw.profile() == profile, profile)

    battery = hw.battery()
    write_and_verify("charge limit 80", battery["limit_path"], 80)
    writer.write(battery["limit_path"], battery["limit"])
    check("charge limit restored", hw.battery()["limit"] == battery["limit"], str(battery["limit"]))

    brightness = hw.brightness()
    write_and_verify("brightness 1", f"{system.LED}/brightness", 1)
    writer.write(f"{system.LED}/brightness", brightness)

    for attribute in hw.armoury_attributes():
        if attribute["name"] in ("boot_sound", "panel_overdrive") and attribute["writable"]:
            flipped = "1" if attribute["value"] == "0" else "0"
            write_and_verify(attribute["name"], attribute["path"], flipped)
            writer.write(attribute["path"], attribute["value"])
            check(f"{attribute['name']} restored", hw.read(attribute["path"]) == attribute["value"])

    # Fans: the question this test really answers.
    device = hw.fan_curve_device()
    before = fans()
    # Your own fan curves must survive this test, so remember them too.
    original_curves = {c: (hw.fan_curve_enabled(c), hw.fan_curve(c)) for c, _n in hw.fan_curve_channels()}
    full = [[30 + i * 10, 255] for i in range(8)]
    try:
        for channel, _name in hw.fan_curve_channels():
            for path, value in system.fan_curve_writes(device, channel, full):
                writer.write(path, value)
        print("fans set to full speed. Waiting 20 seconds, you should hear them...", flush=True)
        peak = dict(before)
        for _second in range(20):
            time.sleep(1)
            for name, rpm in fans().items():
                peak[name] = max(peak.get(name, 0), rpm)
        check("fans respond to a full speed curve", all(peak[n] > before[n] + 500 for n in before), f"{before} -> {peak}")
    finally:
        for channel, (enabled, points) in original_curves.items():
            if enabled:
                for path, value in system.fan_curve_writes(device, channel, points):
                    writer.write(path, value)
            else:
                writer.write(f"{device}/pwm{channel}_enable", 3)  # back to factory control
    time.sleep(1)
    check("fans back as they were", all(hw.fan_curve_enabled(c) == e for c, (e, _p) in original_curves.items()))

    # Keyboard. Nothing here saves to flash, and the saved effect goes back at the end.
    interface = hw.hidraw_keyboards()[0]
    node, (kind, length) = interface["node"], interface["transport"]
    feature = interface["report"].feature + 1
    for packet in hid.handshake_packets(feature, hw.identity()["board"]):
        writer.hid(node, "feature", packet)
        reply = writer.get_feature(node, hid.LIGHTING_REPORT, feature)
    caps = hid.parse_capabilities(reply)
    check("keyboard query", caps, str(caps and {k: caps[k] for k in ("backlight_type", "lightbar", "language")}))

    def send(*sent):
        for packet in sent:
            writer.hid(node, kind, packet)

    for mode in ("Static", "Breathe", "RainbowCycle", "RainbowWave", "Pulse"):
        send(packets.effect(mode, (0, 120, 255), length=length), *packets.commit(length=length))
        time.sleep(1.5)
        check(f"effect {mode} sent", True)
    for zone in range(1, 5):
        send(packets.effect("Static", [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)][zone - 1], zone=zone, length=length))
    send(*packets.commit(length=length))
    time.sleep(2)
    check("zone colours sent: red, green, blue, yellow from left", True, "look at the keyboard")

    send(packets.direct_init(1, length))
    for step in range(30):
        colours = [(255 * ((step + z) % 4 == 0), 80, 255 * ((step + z) % 4 == 2)) for z in range(4)]
        send(packets.direct_zones(colours, caps["backlight_type"], length))
        time.sleep(1 / 15)
    check("live colour sent for 2 seconds", True, "look at the keyboard")

    saved = Config()["lighting"]
    if saved:
        send(packets.effect(saved["mode"], saved["colour"], saved["speed"], saved["direction"], saved.get("zone", 0), length=length), *packets.commit(length=length))
    check("saved effect restored", True)

    # Macro playback, using only the Shift key so it can't type into anything.
    helper.request(op="keys", events=[[42, 1, 0], [42, 0, 50]])
    check("macro playback through /dev/uinput", True)

    # The GPU: readings, and that it goes back to sleep afterwards.
    meter = monitor.Monitor(hw)
    stats = meter.query_gpu()
    check("nvidia-smi readings", stats and stats["temperature"] is not None, str(stats))
    check("GPU shows awake after a query", meter.discrete_gpu()["state"] == "active")
    waited = 0
    while meter.discrete_gpu()["state"] != "suspended" and waited < 40:
        time.sleep(1)
        waited += 1
    check("GPU falls back asleep", meter.discrete_gpu()["state"] == "suspended", f"after {waited} s")
    print(f"took {time.time() - start:.0f} s")


try:
    main()
except Exception as err:  # still restore everything below
    check("test stopped early", False, repr(err))
finally:
    for path, value in reversed(restore):
        if value is not None and hw.read(path) != value:
            try:
                writer.write(path, value)
            except Exception as err:
                print("RESTORE FAILED", path, err)
    helper.close()

failed = [name for name, ok, _detail in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed: {failed}")
sys.exit(1 if failed else 0)
