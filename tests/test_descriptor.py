"""The parser against the real descriptor and table from docs/hardware.md."""
from openarmoury import demo, hid


def table():
    return {r.id: r for r in hid.parse_descriptor(demo.DESCRIPTOR)}


def test_descriptor_length():
    assert len(demo.DESCRIPTOR) == 331


def test_matches_hand_decoded_table():
    expected = {
        0xA5: (0xFF89, 0x10, 0, 0, 16),
        0xC1: (0xFF82, 0xCF, 16, 60, 60),
        0xC2: (0xFF82, 0xCF, 16, 16, 0),
        0x01: (0x01, 0x06, 60, 1, 0),
        0x5A: (0xFF31, 0x76, 1, 0, 63),
        0x5D: (0xFF31, 0x79, 31, 63, 63),
        0x02: (0x0C, 0x01, 2, 0, 0),
        0x04: (0x01, 0x80, 1, 0, 0),
    }
    reports = table()
    assert set(reports) == set(expected)
    for report_id, (page, usage, inp, out, feature) in expected.items():
        r = reports[report_id]
        assert (r.usage_page, r.usage, r.input, r.output, r.feature) == (page, usage, inp, out, feature), hex(report_id)


def test_lighting_report_prefers_output():
    report = hid.find_lighting_report(hid.parse_descriptor(demo.DESCRIPTOR))
    assert report.id == 0x5D
    assert hid.choose_transport(report) == ("output", 64)


def test_feature_only_device_uses_feature():
    report = hid.Report(0x5D, 0xFF31, 0x79, feature=63)
    assert hid.choose_transport(report) == ("feature", 64)


def test_input_only_report_is_not_lighting():
    assert hid.find_lighting_report([hid.Report(0x5D, 0xFF31, 0x79, input=16)]) is None


def test_non_vendor_page_is_not_lighting():
    assert hid.find_lighting_report([hid.Report(0x5D, 0x0001, 0x06, output=16)]) is None


def test_long_items_and_truncated_data_do_not_crash():
    assert hid.parse_descriptor(bytes([0xFE, 0x02, 0x00, 0xAA, 0xBB])) == []
    assert hid.parse_descriptor(bytes([0x06, 0x89])) == []
    assert hid.parse_descriptor(b"") == []


def test_push_pop_restores_globals():
    data = bytes(
        [0x06, 0x31, 0xFF, 0x09, 0x79, 0xA1, 0x01, 0x85, 0x5D, 0x75, 0x08, 0x95, 0x10]
        + [0xA4, 0x95, 0x02, 0xB4]  # push, count 2, pop
        + [0x91, 0x02, 0xC0]
    )
    assert hid.parse_descriptor(data)[0].output == 16


def test_handshake_packets_match_protocol():
    magic, ask = hid.handshake_packets(64)
    assert magic[:16] == b"\x5dASUS Tech.Inc.\x00" and len(magic) == 64
    assert ask[:6] == bytes.fromhex("5d052031001a") and len(ask) == 64
    assert hid.handshake_packets(64, "GZ701X")[1][5] == 0x10


def test_capabilities_reply():
    caps = hid.parse_capabilities(demo.ZONE_REPLY)
    assert caps["backlight_type"] == 2 and caps["lightbar"] and not caps["logo"]
    assert "series" not in caps  # year 0x21 doesn't report it


def test_capabilities_newer_keyboard_reports_series_and_counts():
    reply = bytearray(64)
    reply[:5] = bytes.fromhex("5d05203100")
    reply[9], reply[10], reply[13], reply[17], reply[18] = 3, 0x23, 0x02, 0x04, 12
    caps = hid.parse_capabilities(bytes(reply))
    assert caps["series"] == "Zephyrus" and caps["led_counts"]["lightbar"] == 12


def test_capabilities_rejects_wrong_echo():
    assert hid.parse_capabilities(bytes(64)) is None
    assert hid.parse_capabilities(b"\x5d\x05") is None


def test_keyboard_kind():
    assert hid.keyboard_kind(3) == "per-key"
    assert [hid.keyboard_kind(t) for t in (1, 2, 4)] == ["zone"] * 3
    assert hid.keyboard_kind(0) is None and hid.keyboard_kind(0xD0) is None
