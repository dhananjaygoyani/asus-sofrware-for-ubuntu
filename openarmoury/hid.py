"""HID report descriptor parser and the keyboard self-description handshake (docs/protocol.md)."""
from dataclasses import dataclass

LIGHTING_REPORT = 0x5D
QUERY_LENGTH = 0x1A
QUERY_LENGTH_GZ70X = 0x10
HANDSHAKE = b"ASUS Tech.Inc.\x00"

SERIES = {0x01: "Strix", 0x02: "Flow", 0x04: "Zephyrus", 0x08: "TUF", 0x10: "SE", 0x20: "Desktop"}


@dataclass
class Report:
    id: int
    usage_page: int
    usage: int
    input: int = 0  # payload bytes, excluding the report ID
    output: int = 0
    feature: int = 0


def parse_descriptor(data):
    """Return every report in a descriptor. Sizes come from the items, never from assumptions."""
    reports = {}
    bits = {}
    page = size = count = report_id = 0
    stack = []
    usage = None
    depth = 0
    top_page = top_usage = 0
    i = 0
    while i < len(data):
        prefix = data[i]
        if prefix == 0xFE:  # long item
            i += 3 + data[i + 1] if i + 1 < len(data) else len(data)
            continue
        length = (0, 1, 2, 4)[prefix & 3]
        value = int.from_bytes(data[i + 1 : i + 1 + length], "little")
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        i += 1 + length

        if kind == 1:  # global
            if tag == 0:
                page = value
            elif tag == 7:
                size = value
            elif tag == 8:
                report_id = value
            elif tag == 9:
                count = value
            elif tag == 10:
                stack.append((page, size, count, report_id))
            elif tag == 11 and stack:
                page, size, count, report_id = stack.pop()
        elif kind == 2:  # local
            if tag == 0 and usage is None:
                usage = value
        elif kind == 0:  # main
            if tag == 10:
                if depth == 0:
                    top_page, top_usage = page, usage or 0
                depth += 1
            elif tag == 12:
                depth = max(0, depth - 1)
            elif tag in (8, 9, 11):
                field = {8: "input", 9: "output", 11: "feature"}[tag]
                key = (report_id, top_page, top_usage)
                reports.setdefault(key, Report(report_id, top_page, top_usage))
                bits[(key, field)] = bits.get((key, field), 0) + size * count
            usage = None
    for (key, field), total in bits.items():
        setattr(reports[key], field, (total + 7) // 8)
    return list(reports.values())


def find_lighting_report(reports):
    """The vendor collection carrying the lighting report. Input-only reuse of the ID does not count."""
    for report in reports:
        if report.id == LIGHTING_REPORT and report.usage_page >= 0xFF00 and (report.output or report.feature):
            return report
    return None


def choose_transport(report):
    """Use the Output report when the device has one, otherwise Feature, padded to the declared size."""
    if report.output:
        return "output", report.output + 1
    return "feature", report.feature + 1


def handshake_packets(feature_length, board=""):
    """The two Set Feature packets that ask the keyboard to describe itself."""
    query = QUERY_LENGTH_GZ70X if "GZ700" in board or "GZ701" in board else QUERY_LENGTH
    magic = bytes([LIGHTING_REPORT]) + HANDSHAKE
    ask = bytes([LIGHTING_REPORT, 0x05, 0x20, 0x31, 0x00, query])
    return magic.ljust(feature_length, b"\x00"), ask.ljust(feature_length, b"\x00")


def parse_capabilities(reply):
    """Decode the handshake reply. Returns None if it isn't a valid answer."""
    if len(reply) < 14 or reply[:5] != bytes([LIGHTING_REPORT, 0x05, 0x20, 0x31, 0x00]):
        return None
    flags = reply[13]
    year = reply[10]
    caps = {
        "backlight_type": reply[9],
        "year": year,
        "language": reply[12],
        "logo": bool(flags & 0x01),
        "lightbar": bool(flags & 0x02),
        "vcut": bool(flags & 0x10),
        "aero": bool(flags & 0x20),
        "bump": bool(flags & 0x40),
        "rear_glow": bool(flags & 0x80),
    }
    if year > 0x22 and len(reply) >= 24:
        caps["series"] = SERIES.get(reply[17], "Unknown")
        caps["led_counts"] = dict(zip(("lightbar", "logo", "aero", "vcut", "rear_glow", "bump"), reply[18:24]))
    return caps


def keyboard_kind(backlight_type):
    """Map the keyboard's backlight type to the lighting path. None means don't drive it directly."""
    if backlight_type == 3:
        return "per-key"
    if backlight_type in (1, 2, 4):
        return "zone"
    return None
