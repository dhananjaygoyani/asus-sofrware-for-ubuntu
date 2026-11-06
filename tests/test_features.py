"""Monitoring, automation rules, game discovery, audio level, display settings and backups."""
import array
import json
import os

import pytest

from openarmoury import audio, demo, games, monitor, rules, system
from openarmoury.config import Config

desktop = pytest.importorskip("openarmoury.desktop")


@pytest.fixture
def hw(tmp_path):
    return system.Hardware(demo.build(tmp_path))


def test_cpu_usage_comes_from_the_change(hw):
    meter = monitor.Monitor(hw)
    meter.sample(0)
    demo._write(hw.root, "/proc/stat", "cpu  1100 0 500 8100 200 0 0 0 0 0")
    meter.sample(1)
    assert meter.cpu_percent == 50


def test_network_rate_skips_loopback(hw):
    meter = monitor.Monitor(hw)
    meter.sample(0)
    demo._write(hw.root, "/proc/net/dev", "h\nh\n  lo: 9999 0 0 0 0 0 0 0 9999 0 0 0 0 0 0 0\n eth0: 3000 0 0 0 0 0 0 0 400 0 0 0 0 0 0 0")
    meter.sample(2)
    assert meter.net_down == 1000 and meter.net_up == 100


def test_memory_and_sensors(hw):
    meter = monitor.Monitor(hw)
    assert meter.memory() == (7000000 * 1024, 16000000 * 1024)
    assert meter.disk_temp() == 41 and meter.cpu_mhz() == 3200 and meter.battery_watts() == 19.5


def test_discrete_gpu_state_is_read_without_config_space(hw):
    assert monitor.Monitor(hw).discrete_gpu() == {"vendor": "NVIDIA", "state": "suspended"}


def test_integrated_gpu_is_not_reported_as_discrete(tmp_path):
    root = str(tmp_path)
    demo._write(root, "/sys/bus/pci/devices/a/class", "0x030000")
    demo._write(root, "/sys/bus/pci/devices/a/boot_vga", "1")
    assert monitor.Monitor(system.Hardware(root)).discrete_gpu() is None


def test_desktop_processes_are_never_offered_for_closing(hw):
    meter = monitor.Monitor(hw)
    meter.sample_slow()
    assert [p["name"] for p in meter.top_processes(os.getuid())] == ["firefox", "code"]
    assert meter.top_processes(os.getuid() + 1) == []


def test_format_rate():
    assert monitor.format_rate(500) == "500 B/s" and monitor.format_rate(2048) == "2 KB/s"


def test_battery_health(hw):
    health = hw.battery_health()
    assert round(health["percent"]) == 88 and health["cycles"] == 212


def test_on_battery_follows_mains(hw):
    assert not hw.on_battery()
    demo._write(hw.root, "/sys/class/power_supply/ADP0/online", 0)
    assert hw.on_battery()


PROCESS = {"name": "game.bin", "command": "/home/x/steamapps/common/Hades/game.bin --fast"}


def test_scenario_matching():
    assert rules.matches("game.bin", PROCESS) and rules.matches("steamapps/common/Hades", PROCESS)
    assert not rules.matches("zz", PROCESS) and not rules.matches("", PROCESS) and not rules.matches(None, PROCESS)
    assert not rules.matches("factorio", PROCESS)


def test_scenario_beats_power_rule_and_disabled_is_ignored():
    power = {"ac": {"profile": "balanced"}, "battery": {"profile": "quiet", "low_refresh": True}}
    scenario = {"match": "game.bin", "profile": "performance", "touchpad": False}
    desired, active = rules.desired_state(power, [scenario], False, [PROCESS])
    assert desired["profile"] == "performance" and desired["touchpad"] is False and active is scenario
    desired, active = rules.desired_state(power, [{**scenario, "enabled": False}], False, [PROCESS])
    assert desired["profile"] == "balanced" and active is None
    desired, _ = rules.desired_state(power, [], True, [])
    assert desired["profile"] == "quiet" and desired["low_refresh"] is True


def test_changes_restore_your_setting_when_a_rule_ends():
    saved = {}
    current = {"touchpad": True, "profile": "balanced"}
    assert rules.plan_changes({"touchpad": False}, current, saved) == {"touchpad": False}
    assert saved == {"touchpad": True}
    current["touchpad"] = False
    assert rules.plan_changes({"touchpad": False}, current, saved) == {}
    assert rules.plan_changes({}, current, saved) == {"touchpad": True}
    assert saved == {}


def test_changes_keep_the_first_original_through_several_rules():
    saved = {}
    current = {"profile": "balanced"}
    rules.plan_changes({"profile": "quiet"}, current, saved)
    current["profile"] = "quiet"
    assert rules.plan_changes({"profile": "performance"}, current, saved) == {"profile": "performance"}
    assert saved == {"profile": "balanced"}


def test_steam_games_are_found_and_tools_skipped(tmp_path):
    apps = tmp_path / ".local/share/Steam/steamapps"
    apps.mkdir(parents=True)
    (apps / "appmanifest_1.acf").write_text('"AppState"\n{\n "appid" "1"\n "name" "Hades"\n "installdir" "Hades"\n}')
    (apps / "appmanifest_2.acf").write_text('"AppState"\n{\n "appid" "2"\n "name" "Proton 9.0"\n "installdir" "P"\n}')
    found = games.steam_games(tmp_path)
    assert [g["name"] for g in found] == ["Hades"]
    assert found[0]["launch_uri"] == "steam://rungameid/1" and found[0]["match"] == "steamapps/common/Hades"


def test_no_steam_is_fine(tmp_path):
    assert games.steam_games(tmp_path) == []


def test_audio_level():
    assert audio.level_from_samples(b"") == 0
    assert audio.level_from_samples(array.array("h", [0] * 100).tobytes()) == 0
    assert audio.level_from_samples(array.array("h", [32000, -32000] * 50).tobytes()) == 1.0
    assert 0 < audio.level_from_samples(array.array("h", [3000, -3000] * 50).tobytes()) < 1
    assert audio.level_from_samples(b"\x01") == 0


def mode(mode_id, width, height, rate, current=False):
    return (mode_id, width, height, rate, 1.0, [1.0], {"is-current": True} if current else {})


STATE = (
    7,
    [
        (("HDMI-1", "x", "y", "z"), [mode("h", 2560, 1440, 60.0, True)], {}),
        (("eDP-1", "a", "b", "c"), [mode("p144", 1920, 1080, 144.0, True), mode("p60", 1920, 1080, 60.0), mode("low", 1280, 720, 60.0)], {}),
    ],
    [
        (0, 0, 1.0, 0, True, [("eDP-1", "a", "b", "c")], {}),
        (1920, 0, 1.0, 0, False, [("HDMI-1", "x", "y", "z")], {}),
    ],
    {},
)


def test_panel_rates_use_the_current_resolution_only():
    rates = desktop.rates_from_state(STATE)
    assert rates["connector"] == "eDP-1" and rates["current"] == 144.0
    assert rates["modes"] == [(60.0, "p60"), (144.0, "p144")]


def test_refresh_change_keeps_other_displays():
    serial, method, layout, _props = desktop.apply_config_from_state(STATE, "eDP-1", "p60")
    assert serial == 7 and method == desktop.METHOD_TEMPORARY
    assert layout[0][5] == [("eDP-1", "p60", {})] and layout[1][5] == [("HDMI-1", "h", {})]
    assert layout[1][0] == 1920


def test_no_internal_panel_means_no_rates():
    assert desktop.rates_from_state((1, [(("HDMI-1", "", "", ""), [mode("h", 1, 1, 60.0, True)], {})], [], {})) is None


def test_backup_cannot_approve_changes(tmp_path):
    config = Config(tmp_path)
    config["approved"] = ["profile"]
    assert "approved" not in config.export_data()
    other = Config(tmp_path / "other")
    other.import_data({"approved": ["save", "effect"], "profile": "quiet", "scenarios": []})
    assert other["approved"] == [] and other["profile"] == "quiet"
    for bad in ([], "x", {"approved": ["save"]}, {"unknown": 1}):
        with pytest.raises(ValueError):
            other.import_data(bad)
    assert json.loads(json.dumps(config.export_data()))
