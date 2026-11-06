"""Software lighting effects. They render colours per key, for the preview and for direct packets."""
import math

MAX_FPS = 15
FRAME_INTERVAL = 1 / MAX_FPS

BUILTIN_PRESETS = {
    "Ember": {
        "kind": "keyframes",
        "duration": 6.0,
        "spread": 0.35,
        "keys": [[0.0, [255, 60, 0]], [0.5, [255, 170, 40]], [1.0, [255, 60, 0]]],
    },
    "Tide": {
        "kind": "keyframes",
        "duration": 8.0,
        "spread": 0.6,
        "keys": [[0.0, [0, 60, 200]], [0.5, [0, 220, 190]], [1.0, [0, 60, 200]]],
    },
    "Aurora": {
        "kind": "keyframes",
        "duration": 10.0,
        "spread": 0.8,
        "keys": [[0.0, [40, 255, 120]], [0.33, [40, 120, 255]], [0.66, [190, 60, 255]], [1.0, [40, 255, 120]]],
    },
    "Pulse White": {
        "kind": "keyframes",
        "duration": 3.0,
        "spread": 0.0,
        "keys": [[0.0, [30, 30, 30]], [0.5, [255, 255, 255]], [1.0, [30, 30, 30]]],
    },
    "Temperature": {"kind": "smart", "low": 45, "high": 90, "cold": [0, 120, 255], "hot": [255, 30, 0]},
}


def lerp(a, b, amount):
    return [a[i] + (b[i] - a[i]) * amount for i in range(3)]


def sample_keyframes(keys, position):
    """Colour at a position from 0 to 1 along keyframes sorted by position."""
    if not keys:
        return [0, 0, 0]
    position %= 1.0
    if position <= keys[0][0]:
        return list(keys[0][1])
    for (start, a), (end, b) in zip(keys, keys[1:]):
        if position <= end:
            return lerp(a, b, (position - start) / (end - start) if end > start else 0)
    return list(keys[-1][1])


def temperature_colour(effect, temperature):
    span = max(1, effect["high"] - effect["low"])
    amount = max(0.0, min(1.0, ((temperature or effect["low"]) - effect["low"]) / span))
    return lerp(effect["cold"], effect["hot"], amount)


def render(effect, keys, t, temperature=None):
    """Colours for every key at time t. keys are layout entries with code, x, w."""
    kind = effect.get("kind")
    if kind == "paint":
        colours = effect.get("colours", {})
        base = effect.get("base", [0, 0, 0])
        return {k["code"]: colours.get(k["code"], base) for k in keys}
    if kind == "smart":
        colour = temperature_colour(effect, temperature)
        return {k["code"]: colour for k in keys}
    if kind == "keyframes":
        extent = max((k["x"] + k["w"] for k in keys), default=1) or 1
        duration = max(0.1, effect.get("duration", 4.0))
        spread = effect.get("spread", 0.0)
        return {
            k["code"]: sample_keyframes(effect["keys"], t / duration + spread * (k["x"] + k["w"] / 2) / extent)
            for k in keys
        }
    return {k["code"]: [0, 0, 0] for k in keys}


def preview_builtin(mode, colour, speed, direction, keys, t):
    """An approximation of a built-in effect for the on-screen preview. The keyboard does the real one."""
    rate = {"low": 0.5, "medium": 1.0, "high": 2.0}.get(speed, 1.0)
    extent = max((k["x"] + k["w"] for k in keys), default=1) or 1
    height = max((k["y"] + k["h"] for k in keys), default=1) or 1
    frame = {}
    for key in keys:
        x, y = (key["x"] + key["w"] / 2) / extent, (key["y"] + key["h"] / 2) / height
        offset = {"right": -x, "left": x, "up": y, "down": -y}.get(direction, -x)
        if mode == "Breathe":
            value = lerp([0, 0, 0], colour, 0.5 + 0.5 * math.sin(t * rate * 1.6))
        elif mode == "RainbowCycle":
            value = _hue(t * rate * 0.15)
        elif mode == "RainbowWave":
            value = _hue(t * rate * 0.25 + offset)
        elif mode == "Pulse":
            value = lerp([0, 0, 0], colour, abs(math.sin(t * rate * 2.2)) ** 3)
        elif mode == "Flash":
            value = colour if int(t * rate * 3) % 2 else [0, 0, 0]
        elif mode in ("Comet", "Laser", "Ripple", "Highlight"):
            head = (t * rate * 0.5 + offset) % 1
            value = lerp([0, 0, 0], colour, max(0.0, 1 - head * 5))
        elif mode in ("Star", "Rain"):
            seed = math.sin(hash(key["code"]) % 997 + int(t * rate * 2)) * 0.5 + 0.5
            value = colour if seed > 0.85 else [0, 0, 0]
        else:
            value = colour
        frame[key["code"]] = value
    return frame


def _hue(position):
    position %= 1.0
    sector = position * 6
    fraction = sector - int(sector)
    table = [
        (1, fraction, 0),
        (1 - fraction, 1, 0),
        (0, 1, fraction),
        (0, 1 - fraction, 1),
        (fraction, 0, 1),
        (1, 0, 1 - fraction),
    ]
    return [c * 255 for c in table[int(sector) % 6]]


def apply_brightness(frame, level, maximum=3):
    """Dim the preview to match the keyboard's brightness level."""
    amount = (level or 0) / (maximum or 1)
    return {code: [c * amount for c in colour] for code, colour in frame.items()}


class RateLimiter:
    """Refuses a send if the last one was under a frame ago, whatever the caller's timer does."""

    def __init__(self, interval=FRAME_INTERVAL):
        self.interval = interval
        self.last = None

    def allow(self, now):
        if self.last is not None and now - self.last < self.interval:
            return False
        self.last = now
        return True


def monotonic_curve(points):
    """Force a fan curve to be non-decreasing in both temperature and speed."""
    fixed = []
    for temp, pwm in points:
        temp = int(max(0, min(120, temp)))
        pwm = int(max(0, min(255, pwm)))
        if fixed:
            temp = max(temp, fixed[-1][0])
            pwm = max(pwm, fixed[-1][1])
        fixed.append([temp, pwm])
    return fixed


def curve_is_risky(points):
    """True if the fan would still be slow when the chip is hot."""
    return any(temp >= 80 and pwm < 100 for temp, pwm in points) or points[-1][1] < 150
