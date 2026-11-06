"""Live system readings from /proc and /sys. Nothing here can wake the discrete GPU."""
import os
import time

NVIDIA = "0x10de"
# Ending these would take the desktop down, so they aren't offered.
PROTECTED = {
    "gnome-shell", "Xorg", "Xwayland", "systemd", "pipewire", "pipewire-pulse", "wireplumber", "dbus-daemon",
    "gnome-session-binary", "gdm-x-session", "gdm-wayland-session", "openarmoury", "python3", "bash", "sh",
}


def _cpu_times(text):
    """Busy and total jiffies from the first line of /proc/stat."""
    parts = [int(v) for v in text.splitlines()[0].split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return sum(parts) - idle, sum(parts)


class Monitor:
    def __init__(self, hw):
        self.hw = hw
        self.last_cpu = None
        self.last_net = None
        self.cpu_percent = 0.0
        self.net_down = 0.0
        self.net_up = 0.0
        self.process_cache = []
        self.temperature_cache = None
        self.temperature_smooth = None

    def sample_slow(self):
        """Work too slow for the UI thread. Runs on a background thread, and a list swap is safe in Python."""
        self.process_cache = self.processes()
        self.temperature_cache = self.hw.cpu_temp()
        self.temperature_smooth = smoothed(self.temperature_smooth, self.temperature_cache)

    def sample(self, now=None):
        """Update the rates. Call at a steady interval."""
        now = time.monotonic() if now is None else now
        stat = self.hw.read("/proc/stat")
        if stat:
            busy, total = _cpu_times(stat)
            if self.last_cpu and total > self.last_cpu[1]:
                self.cpu_percent = 100 * (busy - self.last_cpu[0]) / (total - self.last_cpu[1])
            self.last_cpu = (busy, total)
        received, sent = self.net_totals()
        if self.last_net and now > self.last_net[2]:
            elapsed = now - self.last_net[2]
            self.net_down = max(0, received - self.last_net[0]) / elapsed
            self.net_up = max(0, sent - self.last_net[1]) / elapsed
        self.last_net = (received, sent, now)

    def net_totals(self):
        received = sent = 0
        for line in (self.hw.read("/proc/net/dev", "") or "").splitlines()[2:]:
            name, _, values = line.partition(":")
            if name.strip() == "lo" or not values:
                continue
            fields = values.split()
            received += int(fields[0])
            sent += int(fields[8])
        return received, sent

    def memory(self):
        """Used and total bytes."""
        info = {}
        for line in (self.hw.read("/proc/meminfo", "") or "").splitlines():
            key, _, value = line.partition(":")
            info[key] = int(value.split()[0]) * 1024 if value.split() else 0
        total = info.get("MemTotal", 0)
        return total - info.get("MemAvailable", total), total

    def cpu_mhz(self):
        values = [
            self.hw.read_int(path)
            for path in self.hw._glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
        ]
        values = [v for v in values if v]
        return sum(values) / len(values) / 1000 if values else None

    def disk_temp(self):
        path = self.hw.hwmon("nvme")
        value = self.hw.read_int(f"{path}/temp1_input") if path else None
        return value / 1000 if value is not None else None

    def battery_watts(self):
        for path in self.hw.batteries():
            value = self.hw.read_int(f"{path}/power_now")
            if value is not None:
                return value / 1_000_000
        return None

    def discrete_gpu(self):
        """Only runtime_status is read. It reports the power state without powering the GPU up."""
        for path in self.hw._glob("/sys/bus/pci/devices/*"):
            kind = self.hw.read(f"{path}/class", "")
            if kind.startswith("0x03") and self.hw.read(f"{path}/boot_vga") != "1":
                return {
                    "vendor": "NVIDIA" if self.hw.read(f"{path}/vendor") == NVIDIA else "Discrete GPU",
                    "state": self.hw.read(f"{path}/power/runtime_status", "unknown"),
                }
        return None

    def processes(self):
        """Processes as dicts of pid, name, memory bytes, uid and command line."""
        result = []
        for path in self.hw._glob("/proc/[0-9]*"):
            try:
                pid = int(os.path.basename(path))
            except ValueError:
                continue
            status = self.hw.read(f"{path}/status")
            if not status:
                continue
            fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
            memory = fields.get("VmRSS", "0 kB").split()[0]
            uid = fields.get("Uid", "0").split()[0]
            command = (self.hw.read(f"{path}/cmdline", "") or "").replace("\x00", " ").strip()
            result.append(
                {
                    "pid": pid,
                    "name": fields.get("Name", "").strip(),
                    "memory": int(memory) * 1024,
                    "uid": int(uid),
                    "command": command,
                }
            )
        return result

    def top_processes(self, uid, count=6):
        """The biggest of your own processes that are safe to offer to close."""
        own = [p for p in self.process_cache if p["uid"] == uid and p["name"] not in PROTECTED and p["memory"]]
        return sorted(own, key=lambda p: -p["memory"])[:count]


def smoothed(previous, reading, weight=0.2):
    """A steadier temperature for display. Ryzen chips report brief jumps that don't mean the laptop is hot."""
    if reading is None or previous is None:
        return reading
    return previous + (reading - previous) * weight


def format_rate(value):
    for unit in ("B/s", "KB/s", "MB/s"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} GB/s"
