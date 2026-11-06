"""Discovery against the mock tree, restore planning, and rules that must hold across the code."""
import pathlib

import pytest

from openarmoury import demo, packets, restore, system
from openarmoury.config import Config

SOURCE = pathlib.Path(demo.__file__).parent


@pytest.fixture
def hw(tmp_path):
    return system.Hardware(demo.build(tmp_path))


def test_finds_only_the_asus_lighting_interface(hw):
    found = hw.hidraw_keyboards()
    assert [k["node"] for k in found] == ["hidraw0"]
    assert found[0]["transport"] == ("output", 64) and found[0]["product"] == "1866"


def test_reads_sensors_and_controls(hw):
    assert hw.cpu_temp() == 52 and hw.igpu_temp() == 47
    assert hw.profile_choices() == ["quiet", "balanced", "performance"]
    assert hw.fans() == [("CPU fan", 1900), ("GPU fan", 2400)]
    assert [c for c, _n in hw.fan_curve_channels()] == [1, 2]
    assert hw.fan_curve(1)[0] == [58, 2] and not hw.fan_curve_enabled(1)
    assert hw.battery()["limit"] == 100


def test_attributes_are_generic_and_handle_unreadable_values(hw):
    attributes = {a["name"]: a for a in hw.armoury_attributes()}
    assert attributes["ppt_pl1_spl"]["min"] == 15 and attributes["ppt_pl1_spl"]["max"] == 80
    assert attributes["ppt_pl2_sppt"]["value"] is None
    assert attributes["boot_sound"]["choices"] == ["0", "1"] and attributes["boot_sound"]["writable"]
    assert not attributes["charge_mode"]["writable"]


def test_missing_hardware_is_not_an_error(tmp_path):
    hw = system.Hardware(str(tmp_path))
    assert hw.cpu_temp() is None and hw.fans() == [] and hw.fan_curve_channels() == []
    assert hw.battery() is None and hw.armoury_attributes() == [] and hw.hidraw_keyboards() == []
    assert hw.profile() is None and hw.brightness() is None


def test_restore_only_repeats_approved_changes(hw, tmp_path):
    config = Config(tmp_path / "config")
    config.data.update(profile="quiet", charge_limit=80, approved=[])
    assert restore.plan(hw, config) == []
    config.data["approved"] = ["profile"]
    assert restore.plan(hw, config) == [("write", system.PROFILE, "quiet")]


def test_restore_applies_the_curve_for_the_saved_profile(hw, tmp_path):
    config = Config(tmp_path / "config")
    points = [[40 + i, 10 * i] for i in range(8)]
    config.data.update(
        profile="quiet",
        approved=["profile", "fan-curve"],
        fan_curves={"quiet": {"1": {"enabled": True, "points": points}}, "balanced": {"2": {"enabled": True, "points": points}}},
    )
    paths = [step[1] for step in restore.plan(hw, config)]
    assert any("pwm1_enable" in p for p in paths) and not any("pwm2_" in p for p in paths)


def test_restore_never_saves_to_flash(hw, tmp_path):
    config = Config(tmp_path / "config")
    config.data.update(
        approved=["effect", "save"],
        lighting={"mode": "Static", "colour": [1, 2, 3], "speed": "medium", "direction": "right", "zone": 0, "save": True},
    )
    sent = [step[3] for step in restore.plan(hw, config) if step[0] == "hid"]
    assert sent[0][1] == packets.OP_EFFECT
    assert not any(p[1] == packets.OP_COMMIT_B4 for p in sent)


def test_restore_skips_unapproved_zone_effect(hw, tmp_path):
    config = Config(tmp_path / "config")
    config.data.update(
        approved=["effect"],
        lighting={"mode": "Static", "colour": [1, 2, 3], "speed": "medium", "direction": "right", "zone": 2, "save": False},
    )
    assert restore.plan(hw, config) == []


@pytest.mark.parametrize("word", ["nvidia-smi", "nvidia_smi", "nvml"])
def test_never_calls_into_the_dgpu(word):
    for path in list(SOURCE.rglob("*.py")) + [SOURCE.parent / "helper" / "openarmoury-helper"]:
        assert word not in path.read_text(), path


def test_only_the_writer_starts_the_privileged_helper():
    for path in SOURCE.rglob("*.py"):
        if path.name != "writer.py":
            assert "pkexec" not in path.read_text(), path


def test_other_programs_run_are_a_known_short_list():
    """Anything launched outside the helper should be easy to audit."""
    allowed = {"audio.py", "desktop.py", "writer.py"}
    for path in SOURCE.rglob("*.py"):
        if path.name not in allowed:
            assert "subprocess" not in path.read_text(), path


def test_demo_never_shares_an_instance_with_the_real_app():
    """A shared instance would turn --demo into a window onto real hardware."""
    text = (SOURCE / "ui" / "app.py").read_text()
    assert "NON_UNIQUE" in text and "not ctx.is_demo" in text
