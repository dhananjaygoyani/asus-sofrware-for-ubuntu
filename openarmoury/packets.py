"""Lighting packet builders. Layouts and confidence labels are in docs/protocol.md."""

REPORT = 0x5D
OP_EFFECT = 0xB3
OP_COMMIT_B4 = 0xB4  # thought to save to flash, not proven
OP_COMMIT_B5 = 0xB5
OP_DIRECT = 0xBC

SPEEDS = {"low": 0xE1, "medium": 0xEB, "high": 0xF5}
DIRECTIONS = {"right": 0, "left": 1, "up": 2, "down": 3}
MODES = {
    "Static": 0,
    "Breathe": 1,
    "RainbowCycle": 2,
    "RainbowWave": 3,
    "Star": 4,
    "Rain": 5,
    "Highlight": 6,
    "Laser": 7,
    "Ripple": 8,
    "Pulse": 10,
    "Comet": 11,
    "Flash": 12,
}
PER_KEY_ROWS = 11
ZONE_COLOUR_START = 9


def _clamp(colour):
    return [max(0, min(255, int(c))) for c in colour]


def effect(mode, colour, speed="medium", direction="right", zone=0, length=64):
    """A built-in effect. Takes effect only after commit()."""
    packet = bytearray(length)
    packet[:4] = bytes([REPORT, OP_EFFECT, zone, MODES[mode]])
    packet[4:7] = bytes(_clamp(colour))
    packet[7] = SPEEDS[speed]
    packet[8] = DIRECTIONS[direction]
    return bytes(packet)


def commit(save=False, length=64):
    """b5 applies. b4 is added only when the caller asks for it, since it may write flash."""
    ops = [OP_COMMIT_B5, OP_COMMIT_B4] if save else [OP_COMMIT_B5]
    return [bytes([REPORT, op]).ljust(length, b"\x00") for op in ops]


def direct_init(zone_byte=0, length=64):
    """Sent once when switching from a built-in effect to direct colour."""
    return bytes([REPORT, OP_DIRECT, zone_byte]).ljust(length, b"\x00")


def direct_zones(colours, backlight_type=2, length=64):
    """Direct colour for zone keyboards. Never saved to flash."""
    packet = bytearray(length)
    packet[:5] = bytes([REPORT, OP_DIRECT, 2 if backlight_type == 1 else 1, 1, 4 if len(colours) > 1 else 0])
    for index, colour in enumerate(colours):
        start = ZONE_COLOUR_START + 3 * index
        if start + 3 > length:
            break
        packet[start : start + 3] = bytes(_clamp(colour))
    return bytes(packet)


def direct_per_key(colours_by_position, length=64):
    """Direct colour for per-key keyboards. colours_by_position maps (row, column) to a colour."""
    rows = [bytearray(length) for _ in range(PER_KEY_ROWS)]
    for index, row in enumerate(rows):
        row[:8] = bytes([REPORT, OP_DIRECT, 0, 1, 1, 1, index << 4, 0x08 if index == PER_KEY_ROWS - 1 else 0x10])
    for (row, column), colour in colours_by_position.items():
        if 0 <= row < PER_KEY_ROWS and column + 3 <= length:
            rows[row][column : column + 3] = bytes(_clamp(colour))
    return [bytes(row) for row in rows]


def tuf_rgb_mode(mode, colour, speed_index=1, save=False):
    """The kbd_rgb_mode string for keyboards driven through sysfs (TUF)."""
    r, g, b = _clamp(colour)
    return f"{1 if save else 0} {MODES[mode]} {r} {g} {b} {speed_index}"


def is_live_safe(packet):
    """Only direct packets may be streamed by animations. They don't persist."""
    return len(packet) >= 2 and packet[0] == REPORT and packet[1] == OP_DIRECT


def power_state(states, legacy, length=64):
    """Which lights stay on at boot, awake, sleep and shutdown. states maps keyboard/lightbar to on/off dicts."""
    value = 0
    for zone, state in states.items():
        boot, awake, sleep, shutdown = (bool(state.get(k)) for k in ("boot", "awake", "sleep", "shutdown"))
        if legacy:
            value |= (0xC31209 if boot else 0) | (0x300804 if sleep else 0)
            if awake:
                value |= 0x000002 | (0x080000 if zone == "keyboard" else 0x040500)
        elif zone == "keyboard":
            value |= boot << 1 | awake << 3 | sleep << 5 | shutdown << 7
        else:
            value |= boot << 9 | awake << 10 | sleep << 11 | shutdown << 12
    if legacy:
        flags = [value >> 16 & 0xFF, value >> 8 & 0xFF, value & 0xFF, 0]
    else:
        flags = [value & 0xFF, value >> 8 & 0xFF, value >> 16 & 0xFF, value >> 24 & 0xFF]
    return bytes([REPORT, 0xBD, 0x01] + flags).ljust(length, b"\x00")
