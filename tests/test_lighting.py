"""Packets, model matching, effects and the fan curve rules."""
import json
import pathlib

from openarmoury import effects, keyboard, packets
from openarmoury.config import Config


def test_effect_matches_asusctl_vector():
    packet = packets.effect("Static", (0xFF, 0x11, 0xDD), "medium", "right", colour2=(0xA6, 0, 0), length=17)
    assert packet.hex() == "5db30000ff11ddeb0000a6000000000000"


def test_effect_is_padded_to_declared_length():
    assert len(packets.effect("Breathe", (1, 2, 3))) == 64
    assert packets.effect("Pulse", (1, 2, 3))[3] == 10


def test_speed_values():
    assert packets.SPEEDS == {"low": 0xE1, "medium": 0xEB, "high": 0xF5}


def test_commit_does_not_save_by_default():
    assert [p[1] for p in packets.commit()] == [0xB5]
    assert [p[1] for p in packets.commit(save=True)] == [0xB5, 0xB4]


def test_direct_zones_layout():
    packet = packets.direct_zones([(255, 0, 0), (0, 255, 0), (0, 0, 255), (1, 2, 3)])
    assert packet[:5] == bytes.fromhex("5dbc010104")
    assert packet[9:12] == b"\xff\x00\x00" and packet[18:21] == b"\x01\x02\x03"
    assert packets.direct_zones([(1, 2, 3)], backlight_type=1)[2] == 2
    assert packets.direct_zones([(1, 2, 3)])[4] == 0


def test_colours_are_clamped():
    assert packets.direct_zones([(300, -5, 12.7)])[9:12] == bytes([255, 0, 12])


def test_per_key_rows_match_asusctl_header():
    rows = packets.direct_per_key({(1, 24): (9, 8, 7)})
    assert len(rows) == 11 and all(len(r) == 64 for r in rows)
    assert rows[0][:9] == bytes.fromhex("5dbc00010101001000")
    assert rows[3][6] == 0x30 and rows[10][7] == 0x08
    assert rows[1][24:27] == bytes([9, 8, 7])


def test_out_of_range_position_is_ignored():
    assert packets.direct_per_key({(99, 0): (1, 1, 1), (0, 63): (1, 1, 1)})[0][63] == 0


def test_animation_packets_are_live_safe():
    board = keyboard.Keyboard(interface={"transport": ("output", 64)}, support=keyboard.match_support("G513QC"))
    frame = effects.render(effects.BUILTIN_PRESETS["Tide"], board.light_keys(), 1.0)
    assert all(packets.is_live_safe(p) for p in board.frame_to_packets(frame))
    assert not packets.is_live_safe(packets.effect("Static", (1, 1, 1)))
    assert not any(packets.is_live_safe(p) for p in packets.commit(save=True))


def test_rate_limiter_caps_at_15_fps():
    limiter = effects.RateLimiter()
    sent = sum(limiter.allow(i / 240) for i in range(240))  # one second at 240 calls
    assert sent <= 15


def test_support_table_matching():
    entry = keyboard.match_support("G513QC")
    assert entry["device"] == "G513Q" and entry["advanced"] == "none"
    assert keyboard.match_support("G513QR")["advanced"] == "per-key"
    assert keyboard.match_support("UNKNOWN99") is None


def test_handshake_overrides_table():
    interface = {"transport": ("output", 64)}
    zone = keyboard.match_support("G513QR")  # listed as per-key
    assert keyboard.Keyboard(interface, {"backlight_type": 2, "lightbar": False}, zone).kind == "zone"
    assert keyboard.Keyboard(interface, {"backlight_type": 0xD0, "lightbar": False}, zone).kind == "brightness"
    assert keyboard.Keyboard(interface, None, zone).kind == "per-key"


def test_unknown_model_still_works_conservatively():
    board = keyboard.Keyboard({"transport": ("output", 64)})
    assert board.kind == "zone" and board.modes == keyboard.SAFE_MODES and board.light_keys()
    assert board.uncertain_reason("direct")


def test_no_interface_means_brightness_only():
    board = keyboard.Keyboard()
    assert board.kind == "brightness" and not board.can_color and board.modes == []


def test_tuf_is_single_zone():
    board = keyboard.Keyboard(tuf=True)
    assert board.kind == "single" and board.zone_count == 1
    assert packets.tuf_rgb_mode("Static", (1, 2, 3)) == "0 0 1 2 3 1"


def test_zone_frame_averages_keys():
    interface = {"transport": ("output", 64)}
    board = keyboard.Keyboard(interface, {"backlight_type": 2, "lightbar": False}, keyboard.match_support("G513I"))
    frame = {k["code"]: [200, 100, 0] for k in board.light_keys()}
    packet = board.frame_to_packets(frame)[0]
    assert packet[9:12] == bytes([200, 100, 0]) and packet[18:21] == bytes([200, 100, 0])


def test_every_per_key_layout_maps_most_keys():
    """Guards the importer: a layout whose keys don't resolve to LEDs can't be painted."""
    data = pathlib.Path(keyboard.__file__).parent / "data" / "asusctl"
    layouts = json.loads((data / "layouts.json").read_text())
    led_map = json.loads((data / "led_map.json").read_text())["per_key"]
    for name, keys in layouts.items():
        assert keys, name
        if "per-key" in name:
            mapped = sum(k["code"] in led_map for k in keys)
            assert mapped / len(keys) > 0.8, name


def test_uncertain_operations_need_approval():
    board = keyboard.Keyboard({"transport": ("output", 64)}, support=keyboard.match_support("G513QC"))
    assert board.uncertain_reason("save") and board.uncertain_reason("zone-effect") and board.uncertain_reason("direct")


def test_keyframes_interpolate_and_wrap():
    keys = [[0.0, [0, 0, 0]], [1.0, [100, 100, 100]]]
    assert effects.sample_keyframes(keys, 0.5) == [50, 50, 50]
    assert effects.sample_keyframes(keys, 1.5) == [50, 50, 50]
    assert effects.sample_keyframes([], 0.5) == [0, 0, 0]


def test_smart_mode_follows_temperature():
    effect = effects.BUILTIN_PRESETS["Temperature"]
    assert effects.temperature_colour(effect, 10) == effect["cold"]
    assert effects.temperature_colour(effect, 200) == effect["hot"]
    assert effects.temperature_colour(effect, None) == effect["cold"]


def test_render_kinds():
    keys = [{"code": "A", "x": 0, "w": 1, "y": 0, "h": 1}]
    assert effects.render({"kind": "paint", "colours": {"A": [1, 2, 3]}}, keys, 0)["A"] == [1, 2, 3]
    assert effects.render({"kind": "paint", "base": [9, 9, 9]}, keys, 0)["A"] == [9, 9, 9]
    assert effects.render({"kind": "nope"}, keys, 0)["A"] == [0, 0, 0]


def test_fan_curve_is_forced_monotonic():
    fixed = effects.monotonic_curve([[60, 100], [50, 50], [300, 999]])
    assert fixed == [[60, 100], [60, 100], [120, 255]]


def test_risky_fan_curve_is_detected():
    assert effects.curve_is_risky([[80, 50], [90, 200]])
    assert effects.curve_is_risky([[40, 50], [60, 100]])
    assert not effects.curve_is_risky([[40, 50], [90, 255]])


def test_config_survives_damage(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken")
    config = Config(tmp_path)
    assert config["presets"] == {}
    assert (tmp_path / "config.json.bad").read_text() == "{broken"
    config["profile"] = "quiet"
    assert Config(tmp_path)["profile"] == "quiet"


def test_direct_init_byte_follows_type():
    interface = {"transport": ("output", 64)}
    assert keyboard.Keyboard(interface, {"backlight_type": 2, "lightbar": False}).direct_init_byte() == 1
    assert keyboard.Keyboard(interface, {"backlight_type": 1, "lightbar": False}).direct_init_byte() == 2
    assert keyboard.Keyboard(interface, {"backlight_type": 3, "lightbar": False}).direct_init_byte() == 0


def test_layouts_start_at_zero():
    layouts = json.loads((pathlib.Path(keyboard.__file__).parent / "data" / "asusctl" / "layouts.json").read_text())
    for name, keys in layouts.items():
        assert min(k["x"] for k in keys) == 0 and min(k["y"] for k in keys) == 0, name
