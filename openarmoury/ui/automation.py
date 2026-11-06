"""Applies power-source rules and scenarios while the app runs. It never asks for approval by itself."""
from .. import rules, system


class Automation:
    def __init__(self, ctx):
        self.ctx = ctx
        self.saved = {}
        self.active = None
        self.blocked = set()

    def current(self):
        hw, desktop = self.ctx.hw, self.ctx.desktop
        return {
            "profile": hw.profile(),
            "brightness": hw.brightness(),
            "touchpad": desktop.touchpad(),
            "win_key": desktop.win_key(),
            # Asking the display costs time, so only do it when a rule cares.
            "low_refresh": self._low_refresh() if self._uses_refresh() else None,
        }

    def _uses_refresh(self):
        return any((self.ctx.config["power_rules"].get(k) or {}).get("low_refresh") is not None for k in ("ac", "battery")) or "low_refresh" in self.saved

    def _low_refresh(self):
        rates = self.ctx.desktop.refresh_rates()
        return bool(rates and rates["modes"] and rates["current"] == rates["modes"][0][0])

    def tick(self):
        ctx = self.ctx
        config = ctx.config
        self._finish_full_charge()
        scenarios, power = config["scenarios"], config["power_rules"]
        if not scenarios and not any(power.get(k) for k in ("ac", "battery")) and not self.saved:
            return
        processes = ctx.monitor.process_cache if scenarios else []
        desired, scenario = rules.desired_state(power, scenarios, ctx.hw.on_battery(), processes)
        name = scenario["name"] if scenario else None
        if name != self.active:
            self.active = name
            ctx.toast(f"Scenario on: {name}" if name else "Scenario ended.")
        for key, value in rules.plan_changes(desired, self.current(), self.saved).items():
            self._apply(key, value)

    def _apply(self, key, value):
        ctx = self.ctx
        if key == "touchpad":
            ctx.desktop.set_touchpad(value)
        elif key == "win_key":
            ctx.desktop.set_win_key(value)
        elif key == "low_refresh":
            rates = ctx.desktop.refresh_rates()
            if rates and rates["modes"]:
                ctx.desktop.set_refresh(rates["modes"][0 if value else -1][1])
        elif key == "profile" and value in ctx.hw.profile_choices():
            self._write("profile", system.PROFILE, value)
        elif key == "brightness" and ctx.hw.brightness() is not None:
            self._write("brightness", f"{system.LED}/brightness", value)

    def _write(self, key, path, value):
        """Only repeat kinds of change you've already approved, so a rule can't pop up a dialog at random."""
        ctx = self.ctx
        if ctx.is_demo or key in ctx.config["approved"]:
            ctx.submit([ctx.write_op(key, path, value)])
        elif key not in self.blocked:
            self.blocked.add(key)
            ctx.toast(f"A rule wants to change {key}. Change it once by hand to allow that.")

    def _finish_full_charge(self):
        """After a one-time full charge, go back to your usual limit."""
        ctx = self.ctx
        previous = ctx.config["full_charge_return"]
        battery = ctx.hw.battery()
        if previous and battery and battery["capacity"] is not None and battery["capacity"] >= 99:
            ctx.config["full_charge_return"] = None
            ctx.submit([ctx.write_op("charge-limit", battery["limit_path"], previous)])
            ctx.toast(f"Battery full. Charge limit back to {previous}%.")
