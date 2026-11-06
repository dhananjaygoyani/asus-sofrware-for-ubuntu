"""Saved settings in ~/.config/openarmoury/config.json."""
import copy
import json
import os
import pathlib

DEFAULTS = {
    "restore_at_login": False,
    "profile": None,
    "charge_limit": None,
    "brightness": None,
    "fan_curves": {},  # profile -> channel -> {"enabled": bool, "points": [[temp, pwm], ...]}
    "lighting": None,
    "studio_effect": None,
    "presets": {},
    "capabilities": None,  # the keyboard's handshake reply
    "approved": [],  # uncertain operations you have accepted
    "run_in_background": False,
    "power_rules": {"ac": {}, "battery": {}},
    "scenarios": [],
    "macros": {},
    "power_states": None,
    "full_charge_return": None,  # the limit to go back to after a one-time full charge
}
# A backup file must never be able to approve changes on your behalf.
NOT_BACKED_UP = ("approved", "capabilities")


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return pathlib.Path(base) / "openarmoury"


class Config:
    def __init__(self, directory=None):
        self.path = pathlib.Path(directory or config_dir()) / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        try:
            loaded = json.loads(self.path.read_text())
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            # Keep the damaged file rather than overwriting it on the next save.
            try:
                self.path.replace(self.path.with_suffix(".json.bad"))
            except OSError:
                pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def export_data(self):
        return {key: value for key, value in self.data.items() if key not in NOT_BACKED_UP}

    def import_data(self, loaded):
        """Bring in settings from a backup. Returns how many were recognised."""
        if not isinstance(loaded, dict):
            raise ValueError("Not a settings file")
        known = {key: value for key, value in loaded.items() if key in DEFAULTS and key not in NOT_BACKED_UP}
        if not known:
            raise ValueError("No settings found in this file")
        self.data.update(known)
        self.save()
        return len(known)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=1))
        temp.replace(self.path)
