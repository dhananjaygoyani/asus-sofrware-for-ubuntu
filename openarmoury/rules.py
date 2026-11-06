"""Automatic changes: what the laptop should be doing given the power source and running programs."""

KEYS = ("profile", "brightness", "touchpad", "win_key", "low_refresh")
MIN_MATCH = 3


def matches(pattern, process):
    """A short pattern would match by accident, so very short ones never match."""
    pattern = (pattern or "").strip().lower()
    if len(pattern) < MIN_MATCH:
        return False
    return pattern == process["name"].lower() or pattern in process["command"].lower()


def active_scenario(scenarios, processes):
    """The first scenario with a running program."""
    for scenario in scenarios:
        if any(matches(scenario.get("match"), p) for p in processes):
            return scenario
    return None


def desired_state(power_rules, scenarios, on_battery, processes):
    """Power rules first, then a running scenario on top. None means leave it alone."""
    source = power_rules.get("battery" if on_battery else "ac") or {}
    desired = {key: source.get(key) for key in KEYS}
    scenario = active_scenario(scenarios, processes)
    if scenario:
        for key in KEYS:
            if scenario.get(key) is not None:
                desired[key] = scenario[key]
    return desired, scenario


def plan_changes(desired, current, saved):
    """What to change now. Remembers your own setting in saved, and puts it back when a rule ends."""
    changes = {}
    for key in KEYS:
        want = desired.get(key)
        if want is not None:
            if current.get(key) != want:
                saved.setdefault(key, current.get(key))
                changes[key] = want
        elif key in saved:
            original = saved.pop(key)
            if original is not None and current.get(key) != original:
                changes[key] = original
    return changes
