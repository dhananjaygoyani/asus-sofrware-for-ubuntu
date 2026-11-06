"""Re-apply saved settings at login. Only re-applies kinds of change you have already approved in the app."""
import re
import sys

from . import packets, system
from .config import Config
from .writer import Helper, WriteError, Writer


def macro_slug(name):
    """The name a macro's desktop shortcut uses."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32]


def plan(hw, config):
    """The writes to make, as tuples. Reads only, so it can be tested."""
    approved = config["approved"]
    steps = []
    if config["profile"] and config["profile"] in hw.profile_choices() and "profile" in approved:
        steps.append(("write", system.PROFILE, config["profile"]))
    battery = hw.battery()
    if config["charge_limit"] and battery and battery["limit"] is not None and "charge-limit" in approved:
        steps.append(("write", battery["limit_path"], config["charge_limit"]))
    if config["brightness"] is not None and hw.brightness() is not None and "brightness" in approved:
        steps.append(("write", f"{system.LED}/brightness", config["brightness"]))
    device = hw.fan_curve_device()
    profile = config["profile"] if config["profile"] in hw.profile_choices() else hw.profile()
    if device and "fan-curve" in approved:
        for channel, entry in config["fan_curves"].get(profile or "default", {}).items():
            if entry.get("enabled"):
                steps += [("write", path, value) for path, value in system.fan_curve_writes(device, channel, entry["points"])]

    lighting = config["lighting"]
    interfaces = hw.hidraw_keyboards()
    # Never re-saves to flash at login, and never repeats a zone-numbered effect you haven't approved.
    if lighting and interfaces and "effect" in approved and (not lighting.get("zone") or "zone-effect" in approved):
        interface = interfaces[0]
        kind, length = interface["transport"]
        packet = packets.effect(
            lighting["mode"], lighting["colour"], lighting["speed"], lighting["direction"], lighting.get("zone", 0), length=length
        )
        steps.append(("hid", interface["node"], kind, packet))
        for commit in packets.commit(save=False, length=length):
            steps.append(("hid", interface["node"], kind, commit))
    return steps


def play_macro(slug):
    """Play a macro by the name its shortcut uses. Used by desktop shortcuts."""
    config = Config()
    for name, events in config["macros"].items():
        if macro_slug(name) == slug:
            helper = Helper()
            try:
                helper.request(op="keys", events=events)
            except (WriteError, OSError) as err:
                print(f"openarmoury: macro failed: {err}", file=sys.stderr)
                return 1
            finally:
                helper.close()
            return 0
    print(f"openarmoury: no macro called {slug}", file=sys.stderr)
    return 1


def run():
    hw = system.Hardware()
    config = Config()
    if not config["restore_at_login"]:
        return 0
    helper = Helper()
    writer = Writer(helper)
    failed = 0
    for step in plan(hw, config):
        try:
            if step[0] == "write":
                writer.write(step[1], step[2])
            else:
                writer.hid(step[1], step[2], step[3])
        except (WriteError, OSError) as err:
            print(f"openarmoury: restore step failed: {err}", file=sys.stderr)
            failed += 1
    helper.close()
    return 1 if failed else 0
