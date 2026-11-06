"""Read-only view of the machine through kernel interfaces. Everything is discovered at runtime."""
import glob
import os

from . import hid

ASUS_VENDOR = "00000B05"
LED = "/sys/class/leds/asus::kbd_backlight"
PROFILE = "/sys/firmware/acpi/platform_profile"
ARMOURY = "/sys/class/firmware-attributes/asus-armoury/attributes"
NB_WMI = "/sys/devices/platform/asus-nb-wmi"
# Only these drivers' sensors are read. Sensors on the discrete GPU's driver can wake it.
CPU_HWMON = ("k10temp", "coretemp", "zenpower")
FAN_CURVE_POINTS = 8


def fan_name(label):
    """cpu_fan becomes CPU fan."""
    return " ".join(w.upper() if w in ("cpu", "gpu") else w for w in label.replace("_", " ").split())


def fan_curve_writes(device, channel, points, enabled=True):
    """The files and values that set a fan curve. The enable comes last, so the kernel checks the whole curve."""
    writes = []
    for index, (temp, pwm) in enumerate(points, 1):
        writes.append((f"{device}/pwm{channel}_auto_point{index}_temp", temp))
        writes.append((f"{device}/pwm{channel}_auto_point{index}_pwm", pwm))
    writes.append((f"{device}/pwm{channel}_enable", 1 if enabled else 2))
    return writes


class Hardware:
    def __init__(self, root=""):
        self.root = root

    def _p(self, path):
        return self.root + path

    def read(self, path, default=None):
        try:
            with open(self._p(path), encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except OSError:
            return default

    def read_int(self, path, default=None):
        try:
            return int(self.read(path, ""))
        except ValueError:
            return default

    def exists(self, path):
        return os.path.exists(self._p(path))

    def is_writable_attr(self, path):
        """Whether the kernel offers the file for writing at all, regardless of who we are."""
        try:
            return bool(os.stat(self._p(path)).st_mode & 0o222)
        except OSError:
            return False

    def _glob(self, pattern):
        return [p[len(self.root) :] for p in sorted(glob.glob(glob.escape(self.root) + pattern))]

    def identity(self):
        dmi = "/sys/class/dmi/id"
        return {
            "vendor": self.read(f"{dmi}/sys_vendor", ""),
            "product": self.read(f"{dmi}/product_name", ""),
            "board": self.read(f"{dmi}/board_name", ""),
            "bios": self.read(f"{dmi}/bios_version", ""),
        }

    def hwmon(self, *names):
        for path in self._glob("/sys/class/hwmon/hwmon*"):
            if self.read(f"{path}/name") in names:
                return path
        return None

    def cpu_temp(self):
        path = self.hwmon(*CPU_HWMON)
        value = self.read_int(f"{path}/temp1_input") if path else None
        return value / 1000 if value is not None else None

    def igpu_temp(self):
        path = self.hwmon("amdgpu", "i915", "xe")
        value = self.read_int(f"{path}/temp1_input") if path else None
        return value / 1000 if value is not None else None

    def fans(self):
        path = self.hwmon("asus")
        if not path:
            return []
        result = []
        for item in self._glob(f"{path}/fan*_input"):
            label = self.read(item.replace("_input", "_label"), os.path.basename(item))
            result.append((fan_name(label), self.read_int(item, 0)))
        return result

    def fan_curve_device(self):
        return self.hwmon("asus_custom_fan_curve")

    def fan_curve_channels(self):
        """Fan channels that have a curve, with a label from the driver when one exists."""
        path = self.fan_curve_device()
        if not path:
            return []
        fans = self.hwmon("asus")
        names = {1: "CPU", 2: "GPU", 3: "Middle"}
        channels = []
        for number in (1, 2, 3):
            if self.exists(f"{path}/pwm{number}_auto_point1_pwm"):
                label = self.read(f"{fans}/fan{number}_label") if fans else None
                channels.append((number, fan_name(label) if label else f"{names[number]} fan"))
        return channels

    def fan_curve(self, channel):
        path = self.fan_curve_device()
        points = []
        for index in range(1, FAN_CURVE_POINTS + 1):
            points.append(
                [
                    self.read_int(f"{path}/pwm{channel}_auto_point{index}_temp", 0),
                    self.read_int(f"{path}/pwm{channel}_auto_point{index}_pwm", 0),
                ]
            )
        return points

    def fan_curve_enabled(self, channel):
        return self.read_int(f"{self.fan_curve_device()}/pwm{channel}_enable") == 1

    def profile(self):
        return self.read(PROFILE)

    def profile_choices(self):
        return (self.read(f"{PROFILE}_choices") or "").split()

    def batteries(self):
        return self._glob("/sys/class/power_supply/BAT*")

    def battery(self):
        for path in self.batteries():
            return {
                "path": path,
                "capacity": self.read_int(f"{path}/capacity"),
                "status": self.read(f"{path}/status", "Unknown"),
                "limit": self.read_int(f"{path}/charge_control_end_threshold"),
                "limit_path": f"{path}/charge_control_end_threshold",
            }
        return None

    def on_battery(self):
        """True only when a mains supply reports it's unplugged."""
        for path in self._glob("/sys/class/power_supply/*"):
            if self.read(f"{path}/type") == "Mains":
                return self.read(f"{path}/online") == "0"
        return False

    def gpu_driver_loaded(self):
        """While this is true the GPU can't safely be turned off: doing so crashed the kernel when tested."""
        return self.exists("/sys/module/nvidia") or self.exists("/sys/module/nouveau")

    def gpu_switch_path(self):
        for path in (f"{ARMOURY}/dgpu_disable/current_value", f"{NB_WMI}/dgpu_disable"):
            if self.exists(path):
                return path
        return None

    def gpu_switch_state(self):
        """Where turning the GPU off has got to. The driver must be gone before the switch is safe."""
        path = self.gpu_switch_path()
        if not path:
            return None
        if self.read(path) == "1":
            return "off"
        loaded = self.gpu_driver_loaded()
        prime = self.read("/etc/prime-discrete")
        if prime is None:
            return "blocked" if loaded else "ready"
        if prime == "off":
            return "restart-to-unload" if loaded else "ready"
        return "automatic" if loaded else "restart-to-load"

    def battery_health(self):
        """Current full capacity as a share of its design capacity, and the cycle count."""
        for path in self.batteries():
            for full, design in (("energy_full", "energy_full_design"), ("charge_full", "charge_full_design")):
                now, new = self.read_int(f"{path}/{full}"), self.read_int(f"{path}/{design}")
                if now and new:
                    return {"percent": 100 * now / new, "cycles": self.read_int(f"{path}/cycle_count")}
            return {"percent": None, "cycles": self.read_int(f"{path}/cycle_count")}
        return None

    def armoury_attributes(self):
        """Every firmware attribute, whatever the kernel exposes. Unreadable fields become None."""
        attributes = []
        for path in self._glob(f"{ARMOURY}/*"):
            name = os.path.basename(path)
            if not self.exists(f"{path}/current_value") and not self.exists(f"{path}/type"):
                continue
            current = f"{path}/current_value"
            attributes.append(
                {
                    "name": name,
                    "path": current,
                    "type": self.read(f"{path}/type", "enumeration"),
                    "label": self.read(f"{path}/display_name", name.replace("_", " ").capitalize()),
                    "value": self.read(current),
                    "min": self.read_int(f"{path}/min_value"),
                    "max": self.read_int(f"{path}/max_value"),
                    "step": self.read_int(f"{path}/scalar_increment", 1),
                    "choices": (self.read(f"{path}/possible_values") or "").split(";"),
                    "writable": self.is_writable_attr(current),
                }
            )
        return attributes

    def pending_reboot(self):
        return self.read(f"{ARMOURY}/pending_reboot") == "1"

    def nb_wmi(self, name):
        """Fallback when asus-armoury isn't present."""
        return self.read(f"{NB_WMI}/{name}")

    def brightness(self):
        return self.read_int(f"{LED}/brightness")

    def max_brightness(self):
        return self.read_int(f"{LED}/max_brightness")

    def has_tuf_rgb(self):
        return self.exists(f"{LED}/kbd_rgb_mode")

    def hidraw_keyboards(self):
        """ASUS hidraw nodes with a lighting report, found from the descriptor rather than a PID list."""
        found = []
        for path in self._glob("/sys/class/hidraw/hidraw*"):
            uevent = self.read(f"{path}/device/uevent", "")
            fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
            parts = fields.get("HID_ID", "").split(":")
            if len(parts) != 3 or parts[1].upper() != ASUS_VENDOR:
                continue
            try:
                with open(self._p(f"{path}/device/report_descriptor"), "rb") as f:
                    reports = hid.parse_descriptor(f.read())
            except OSError:
                continue
            report = hid.find_lighting_report(reports)
            if report:
                found.append(
                    {
                        "node": os.path.basename(path),
                        "product": parts[2][-4:].lower(),
                        "name": fields.get("HID_NAME", ""),
                        "report": report,
                        "transport": hid.choose_transport(report),
                    }
                )
        return found

    def conflicts(self):
        """Other programs that would fight over the same hardware."""
        names = []
        for comm in glob.glob("/proc/[0-9]*/comm"):
            try:
                with open(comm, encoding="ascii", errors="replace") as f:
                    name = f.read().strip()
            except OSError:
                continue
            if name in ("asusd", "supergfxd") and not self.root:
                names.append(name)
        return sorted(set(names))
