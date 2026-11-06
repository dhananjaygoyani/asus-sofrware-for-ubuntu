"""The root helper's whitelist. Run against a mock tree, as the test-root override is refused as root."""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess

import pytest

from openarmoury import demo

HELPER = pathlib.Path(__file__).resolve().parent.parent / "helper" / "openarmoury-helper"


def load():
    loader = importlib.machinery.SourceFileLoader("oa_helper", str(HELPER))
    spec = importlib.util.spec_from_loader("oa_helper", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


helper = load()
CURVE = "/sys/class/hwmon/hwmon7"
ARMOURY = "/sys/class/firmware-attributes/asus-armoury/attributes"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = demo.build(tmp_path)
    monkeypatch.setenv("OPENARMOURY_TEST_ROOT", root)
    return root


@pytest.mark.parametrize(
    "path,value",
    [
        ("/sys/firmware/acpi/platform_profile", "quiet"),
        (f"{ARMOURY}/boot_sound/current_value", "1"),
        (f"{ARMOURY}/ppt_pl1_spl/current_value", "60"),
        ("/sys/devices/platform/asus-nb-wmi/panel_od", "1"),
        (f"{CURVE}/pwm1_enable", "1"),
        (f"{CURVE}/pwm2_auto_point8_pwm", "255"),
        (f"{CURVE}/pwm1_auto_point1_temp", "40"),
        ("/sys/class/leds/asus::kbd_backlight/brightness", "2"),
        ("/sys/class/power_supply/BAT0/charge_control_end_threshold", "80"),
    ],
)
def test_allowed_writes(tree, path, value):
    helper.do_write(path, value)
    assert pathlib.Path(tree + path).read_text().strip() == value


@pytest.mark.parametrize(
    "path,value",
    [
        ("/etc/passwd", "x"),
        ("/sys/firmware/acpi/platform_profile/../../../../etc/passwd", "quiet"),
        ("/sys/firmware/acpi/platform_profile", "ludicrous"),
        ("/sys/firmware/acpi/platform_profile", "quiet\nmore"),
        (f"{ARMOURY}/boot_sound/current_value", "7"),
        (f"{ARMOURY}/ppt_pl1_spl/current_value", "500"),
        (f"{ARMOURY}/ppt_pl2_sppt/current_value", "50"),  # limits unreadable: must not be written
        (f"{ARMOURY}/pending_reboot", "1"),
        (f"{ARMOURY}/../../etc/current_value", "1"),
        ("/sys/devices/platform/asus-nb-wmi/driver_override", "x"),
        ("/sys/devices/platform/asus-nb-wmi/panel_od", "2"),
        (f"{CURVE}/pwm1_enable", "0"),
        (f"{CURVE}/pwm1_auto_point9_pwm", "1"),
        (f"{CURVE}/pwm1_auto_point1_pwm", "256"),
        (f"{CURVE}/pwm1_auto_point1_pwm", "-1"),
        ("/sys/class/hwmon/hwmon6/pwm1_enable", "1"),  # not the curve device
        ("/sys/class/hwmon/hwmon5/pwm1_auto_point1_pwm", "1"),
        ("/sys/class/leds/asus::kbd_backlight/brightness", "4"),
        ("/sys/class/leds/asus::kbd_backlight/trigger", "none"),
        ("/sys/class/power_supply/BAT0/charge_control_end_threshold", "5"),
        ("/sys/class/power_supply/BAT0/charge_control_end_threshold", "101"),
        ("/sys/class/power_supply/ADP0/charge_control_end_threshold", "80"),
        (123, "1"),
        ("/sys/firmware/acpi/platform_profile", 1),
    ],
)
def test_refused_writes(tree, path, value):
    with pytest.raises(helper.Refused):
        helper.check_write(path, value)


def test_symlink_out_of_sys_is_refused(tree, tmp_path):
    outside = tmp_path / "secret"
    outside.write_text("keep")
    target = pathlib.Path(tree + "/sys/class/leds/asus::kbd_backlight/brightness")
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(helper.Refused):
        helper.do_write("/sys/class/leds/asus::kbd_backlight/brightness", "1")
    assert outside.read_text() == "keep"


def test_test_root_ignored_as_root(monkeypatch):
    monkeypatch.setenv("OPENARMOURY_TEST_ROOT", "/tmp/evil")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert helper.test_root() == ""


@pytest.mark.parametrize(
    "packet",
    [
        b"\x5dASUS Tech.Inc.\x00".ljust(64, b"\x00"),
        bytes.fromhex("5d052031001a").ljust(64, b"\x00"),
        bytes.fromhex("5db3").ljust(64, b"\x00"),
        bytes.fromhex("5db4").ljust(64, b"\x00"),
        bytes.fromhex("5db5").ljust(64, b"\x00"),
        bytes.fromhex("5dbc00").ljust(64, b"\x00"),
        bytes.fromhex("5abac5c403").ljust(64, b"\x00"),
        bytes.fromhex("5dbd0108000200").ljust(64, b"\x00"),
    ],
)
def test_allowed_packets(packet):
    helper.check_packet(packet)


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x5d",
        bytes(64),
        bytes.fromhex("01b3").ljust(64, b"\x00"),  # wrong report
        bytes.fromhex("5ab3").ljust(64, b"\x00"),  # lighting opcode on the wrong report
        bytes.fromhex("5dbd02ffffffff").ljust(64, b"\x00"),  # power state sub-command
        bytes.fromhex("5dbd0108000200ff").ljust(64, b"\x00"),  # data after the flags
        bytes.fromhex("5abd0108000200").ljust(64, b"\x00"),
        bytes.fromhex("5dd108").ljust(64, b"\x00"),
        bytes.fromhex("5dc2").ljust(64, b"\x00"),
        bytes.fromhex("5de6").ljust(64, b"\x00"),
        bytes.fromhex("5d05203100ff").ljust(64, b"\x00"),
        bytes.fromhex("5d052031011a").ljust(64, b"\x00"),
        bytes.fromhex("5d052031001a01").ljust(64, b"\x00"),
        bytes.fromhex("5abac5c404").ljust(64, b"\x00"),
        b"\x5dASUS Tech.Evil\x00".ljust(64, b"\x00"),
        b"\x5d\xbc" + bytes(2000),
    ],
)
def test_refused_packets(packet):
    with pytest.raises(helper.Refused):
        helper.check_packet(packet)


def test_hid_refuses_non_asus_node(tree):
    with pytest.raises(helper.Refused):
        helper.do_hid("hidraw1", "output", "5db5" + "00" * 62)


@pytest.mark.parametrize("node", ["hidraw0/../hidraw1", "../hidraw0", "sda", "", 5, "hidraw9"])
def test_hid_refuses_bad_nodes(tree, node):
    with pytest.raises((helper.Refused, OSError)):
        helper.do_hid(node, "output", "5db5" + "00" * 62)


def test_hid_refuses_bad_kind_and_data(tree):
    with pytest.raises(helper.Refused):
        helper.do_hid("hidraw0", "input", "5db5")
    for data in ("zz", "5DB5", "5db", 5):
        with pytest.raises(helper.Refused):
            helper.do_hid("hidraw0", "output", data)


def test_real_process_speaks_json_and_survives_bad_input(tree):
    process = subprocess.run(
        [str(HELPER)],
        input='not json\n{"op":"ping"}\n[]\n{"op":"nope"}\n'
        '{"op":"write","path":"/sys/firmware/acpi/platform_profile","value":"quiet"}\n'
        '{"op":"write","path":"/etc/passwd","value":"x"}\n' + "x" * 9000 + "\n",
        capture_output=True,
        text=True,
        env={**os.environ, "OPENARMOURY_TEST_ROOT": tree},
        check=True,
    )
    replies = [json.loads(line)["ok"] for line in process.stdout.splitlines()]
    assert replies == [False, True, False, False, True, False, False]
    assert pathlib.Path(tree + "/sys/firmware/acpi/platform_profile").read_text().strip() == "quiet"


def test_macro_events_are_bounded():
    helper.check_key_events([[30, 1, 0], [30, 0, 50]])
    for bad in (
        [],
        "x",
        [[30, 1]],
        [[0, 1, 0]],
        [[249, 1, 0]],  # above the keyboard range
        [[30, 2, 0]],
        [[30, 1, -1]],
        [[30, 1, 5001]],
        [[30, True, 0]],
        [[30, 1, 5000]] * 13,  # over a minute in total
        [[30, 1, 0]] * 513,
    ):
        with pytest.raises(helper.Refused):
            helper.check_key_events(bad)


def test_macro_runs_in_test_mode(tree):
    helper.handle({"op": "keys", "events": [[30, 1, 0], [30, 0, 10]]})
    assert "[30, 1, 0]" in pathlib.Path(tree + "/dev/uinput").read_text()
