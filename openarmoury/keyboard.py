"""What this laptop's keyboard can do, and how to turn a frame of colours into packets.

The keyboard's own reply decides the lighting path. The model table only fills in what the reply can't
say, such as effect lists and key layouts.
"""
import json
import pathlib

from . import hid, packets

DATA = pathlib.Path(__file__).resolve().parent / "data" / "asusctl"
SAFE_MODES = ["Static", "Breathe", "RainbowCycle", "RainbowWave", "Pulse"]
MODE_LABELS = {
    "Static": "Static",
    "Breathe": "Breathe",
    "RainbowCycle": "Colour cycle",
    "RainbowWave": "Wave",
    "Star": "Stars",
    "Rain": "Rain",
    "Highlight": "Highlight",
    "Laser": "Laser",
    "Ripple": "Ripple",
    "Pulse": "Pulse",
    "Comet": "Comet",
    "Flash": "Flash",
}


def _load(name):
    return json.loads((DATA / name).read_text())


def match_support(board, product="", table=None):
    """Find the model entry. Later entries are more specific, so search from the end."""
    table = _load("support.json") if table is None else table
    for entry in reversed(table):
        if entry["device"] and entry["device"] in board and entry["product"] in ("", product):
            return entry
    return None


def generic_layout():
    """A plain keyboard shape for preview when no layout is known for this model."""
    keys = []
    for row, count in enumerate((15, 15, 14, 13, 12)):
        for column in range(count):
            keys.append({"code": f"Generic{row}_{column}", "x": column * 1.2, "y": row * 1.2, "w": 1.0, "h": 1.0})
    keys.append({"code": "GenericSpace", "x": 4.0, "y": 6.0, "w": 6.0, "h": 1.0})
    return keys


class Keyboard:
    """Combines the HID interface, the keyboard's reply and the model table."""

    def __init__(self, interface=None, capabilities=None, support=None, tuf=False):
        self.interface = interface
        self.capabilities = capabilities
        self.support = support
        self.tuf = tuf
        self.layout = self._layout()
        self.led_map = _load("led_map.json")
        self.kind = self._kind()
        self.zone_count = self._zone_count()

    def _layout(self):
        name = self.support["layout"] if self.support else ""
        layouts = _load("layouts.json")
        return layouts.get(name) or generic_layout()

    def _kind(self):
        if self.tuf:
            return "single"
        if not self.interface:
            return "brightness"
        if self.capabilities:
            kind = hid.keyboard_kind(self.capabilities["backlight_type"])
            if kind:
                return kind
            return "brightness"
        if self.support and self.support["advanced"] == "per-key":
            return "per-key"
        return "zone"

    def _zone_count(self):
        if self.kind == "per-key":
            return 0
        if self.capabilities and self.capabilities["backlight_type"] == 4:
            return 1
        if self.tuf or (self.support and not self.support["zones"] and self.support["advanced"] != "zone"):
            return 1
        return 4

    @property
    def can_color(self):
        return self.kind != "brightness"

    @property
    def verified_by_keyboard(self):
        return self.capabilities is not None

    @property
    def modes(self):
        listed = self.support["modes"] if self.support and self.support["modes"] else SAFE_MODES
        return [m for m in listed if m in packets.MODES] if self.can_color else []

    @property
    def has_lightbar(self):
        if self.capabilities:
            return self.capabilities["lightbar"]
        return bool(self.support and "Lightbar" in self.support["power_zones"])

    def light_keys(self):
        """Keys and lit areas to draw. Lightbar entries are dropped if the keyboard says it has none."""
        return [k for k in self.layout if self.has_lightbar or "Lightbar" not in k["code"]]

    def zone_of(self, key, extent):
        """Which zone a key is in, split evenly left to right. Physical order is unverified."""
        if self.zone_count <= 1:
            return 0
        return min(self.zone_count - 1, int((key["x"] + key["w"] / 2) / extent * self.zone_count))

    def frame_to_packets(self, frame):
        """frame maps LED codes to colours. Returns direct packets only, which never persist."""
        length = self.interface["transport"][1] if self.interface else 64
        if self.kind == "per-key":
            positions = {
                tuple(self.led_map["per_key"][code]): colour
                for code, colour in frame.items()
                if code in self.led_map["per_key"]
            }
            return packets.direct_per_key(positions, length)
        keys = [k for k in self.layout if "Lightbar" not in k["code"]]
        extent = max((k["x"] + k["w"] for k in keys), default=1)
        totals = [[0, 0, 0, 0] for _ in range(self.zone_count)]
        for key in keys:
            if key["code"] in frame:
                total = totals[self.zone_of(key, extent)]
                for channel in range(3):
                    total[channel] += frame[key["code"]][channel]
                total[3] += 1
        colours = [[t[c] / t[3] if t[3] else 0 for c in range(3)] for t in totals]
        backlight = self.capabilities["backlight_type"] if self.capabilities else 2
        return [packets.direct_zones(colours, backlight, length)]

    def direct_init_byte(self):
        """Byte 2 of the packet that starts direct colour: 0 for per-key, otherwise the zone form."""
        if self.kind == "per-key":
            return 0
        return 2 if self.capabilities and self.capabilities["backlight_type"] == 1 else 1

    def uncertain_reason(self, operation):
        """Why an operation needs your explicit approval, or None. Mirrors the labels in docs/protocol.md."""
        if operation == "save":
            return "Which packet saves to keyboard flash isn't proven. This one may wear or change saved settings."
        if operation == "zone-effect":
            return "Zone numbers for built-in effects come from asusctl only."
        if operation == "direct" and self.kind == "zone":
            if self.support and self.support["advanced"] != "zone":
                return "asusctl doesn't list direct zone colour for this model, so it is untested here."
            if self.capabilities and self.capabilities["backlight_type"] == 1:
                return "This backlight type uses a packet variant seen only in vendor code."
        if operation == "direct" and not self.verified_by_keyboard:
            return "The keyboard hasn't been asked what it supports yet."
        return None
