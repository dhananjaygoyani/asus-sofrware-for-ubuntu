"""A mock sysfs/hidraw tree shaped like the surveyed laptop (docs/hardware.md), for --demo and tests."""
import math
import os
import pathlib
import time

# The real descriptor from docs/hardware.md.
DESCRIPTOR = bytes.fromhex(
    "06 89 ff 09 10 a1 01 85 a5 09 01 15 00 26 ff 00"
    "75 08 95 10 b1 00 c0 06 82 ff 09 cf a1 01 85 c1"
    "09 62 15 00 26 ff 00 75 08 95 3c b1 02 09 66 15"
    "00 26 ff 00 75 08 95 10 81 02 09 61 15 00 26 ff"
    "00 75 08 95 3c 91 02 85 c2 09 8a 15 00 26 ff 00"
    "75 08 95 10 81 02 09 8e 15 00 26 ff 00 75 08 95"
    "10 91 02 c0 05 01 09 06 a1 01 85 01 75 01 95 08"
    "05 07 19 e0 29 e7 15 00 25 01 81 02 95 01 75 08"
    "81 03 95 05 75 01 05 08 19 01 29 05 91 02 95 01"
    "75 03 91 03 05 07 19 00 2a ff 00 15 00 26 ff 00"
    "95 1e 75 08 81 00 05 07 19 00 29 df 15 00 25 01"
    "95 e0 75 01 81 02 c0 06 31 ff 09 76 a1 01 85 5a"
    "19 00 2a ff 00 15 00 26 ff 00 75 08 95 01 81 00"
    "19 00 2a ff 00 15 00 26 ff 00 75 08 95 3f b1 00"
    "c0 06 31 ff 09 79 a1 01 85 5d 19 00 2a ff 00 15"
    "00 26 ff 00 75 08 95 1f 81 00 19 00 2a ff 00 15"
    "00 26 ff 00 75 08 95 3f b1 00 19 00 2a ff 00 15"
    "00 26 ff 00 75 08 95 3f 91 02 c0 05 0c 09 01 a1"
    "01 85 02 19 00 2a 3c 02 15 00 26 3c 02 75 10 95"
    "01 81 00 c0 05 01 09 80 a1 01 85 04 19 81 29 83"
    "15 00 25 01 95 08 75 01 81 02 c0"
)
TOUCHPAD_DESCRIPTOR = bytes.fromhex("05010902a101c0")
# Bytes: echo, then type 2 at offset 9, year 0x21 at 10, language at 12, lightbar flag at 13.
ZONE_REPLY = bytes.fromhex("5d 05 20 31 00 00 00 00 00 02 21 00 00 02").ljust(64, b"\x00")

CURVE_CPU = [(58, 2), (60, 17), (63, 25), (66, 99), (69, 130), (74, 158), (79, 188), (98, 255)]
CURVE_GPU = [(58, 2), (60, 38), (63, 63), (66, 71), (69, 114), (74, 150), (79, 186), (98, 255)]


def _write(root, relative, value, mode=0o644):
    path = pathlib.Path(root + relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.chmod(path, 0o644)  # mock files may be read-only, as on the real laptop
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(f"{value}\n")
    os.chmod(path, mode)


def build(root):
    """Create the tree under root and return root."""
    root = str(root)
    dmi = "/sys/class/dmi/id"
    for name, value in {
        "sys_vendor": "ASUSTeK COMPUTER INC.",
        "product_name": "Demo Laptop",
        "board_name": "G513QC",
        "bios_version": "DEMO.1",
    }.items():
        _write(root, f"{dmi}/{name}", value)

    _write(root, "/sys/firmware/acpi/platform_profile", "balanced")
    _write(root, "/sys/firmware/acpi/platform_profile_choices", "quiet balanced performance")

    armoury = "/sys/class/firmware-attributes/asus-armoury/attributes"
    _write(root, f"{armoury}/pending_reboot", "0", 0o444)
    enumerations = {
        "boot_sound": ("0", "0;1", "Set the boot POST sound", 0o644),
        "charge_mode": ("2", "0;1;2", "Show the current mode of charging", 0o444),
        "dgpu_disable": ("0", "0;1", "Disable the dGPU", 0o644),
        "panel_overdrive": ("0", "0;1", "Set the panel refresh overdrive", 0o644),
    }
    for name, (value, choices, label, mode) in enumerations.items():
        _write(root, f"{armoury}/{name}/current_value", value, mode)
        _write(root, f"{armoury}/{name}/possible_values", choices)
        _write(root, f"{armoury}/{name}/display_name", label)
        _write(root, f"{armoury}/{name}/type", "enumeration")
    # ppt_pl2_sppt has no limit files, like the real unreadable attributes. ppt_pl1_spl shows a working integer.
    _write(root, f"{armoury}/ppt_pl1_spl/current_value", "65")
    _write(root, f"{armoury}/ppt_pl1_spl/min_value", "15")
    _write(root, f"{armoury}/ppt_pl1_spl/max_value", "80")
    _write(root, f"{armoury}/ppt_pl1_spl/scalar_increment", "1")
    _write(root, f"{armoury}/ppt_pl1_spl/display_name", "Set the CPU slow package limit")
    _write(root, f"{armoury}/ppt_pl1_spl/type", "integer")
    _write(root, f"{armoury}/ppt_pl2_sppt/display_name", "Set the CPU fast package limit")
    _write(root, f"{armoury}/ppt_pl2_sppt/type", "integer")

    nb = "/sys/devices/platform/asus-nb-wmi"
    for name, value in {"boot_sound": 0, "dgpu_disable": 0, "panel_od": 0, "throttle_thermal_policy": 0}.items():
        _write(root, f"{nb}/{name}", value)

    led = "/sys/class/leds/asus::kbd_backlight"
    _write(root, f"{led}/brightness", 3)
    _write(root, f"{led}/max_brightness", 3, 0o444)

    _write(root, "/sys/class/hwmon/hwmon5/name", "k10temp")
    _write(root, "/sys/class/hwmon/hwmon5/temp1_input", 52000)
    _write(root, "/sys/class/hwmon/hwmon9/name", "amdgpu")
    _write(root, "/sys/class/hwmon/hwmon9/temp1_input", 47000)
    _write(root, "/sys/class/hwmon/hwmon6/name", "asus")
    for number, label, rpm in ((1, "cpu_fan", 1900), (2, "gpu_fan", 2400)):
        _write(root, f"/sys/class/hwmon/hwmon6/fan{number}_input", rpm)
        _write(root, f"/sys/class/hwmon/hwmon6/fan{number}_label", label)
    curve = "/sys/class/hwmon/hwmon7"
    _write(root, f"{curve}/name", "asus_custom_fan_curve")
    for number, points in ((1, CURVE_CPU), (2, CURVE_GPU)):
        _write(root, f"{curve}/pwm{number}_enable", 2)
        for index, (temp, pwm) in enumerate(points, 1):
            _write(root, f"{curve}/pwm{number}_auto_point{index}_temp", temp)
            _write(root, f"{curve}/pwm{number}_auto_point{index}_pwm", pwm)

    battery = "/sys/class/power_supply/BAT0"
    _write(root, f"{battery}/capacity", 87, 0o444)
    _write(root, f"{battery}/status", "Charging", 0o444)
    _write(root, f"{battery}/charge_control_end_threshold", 100)
    _write(root, "/sys/class/power_supply/ADP0/online", 1, 0o444)
    _write(root, "/sys/class/power_supply/ADP0/type", "Mains", 0o444)
    _write(root, f"{battery}/type", "Battery", 0o444)
    _write(root, f"{battery}/energy_full", 79000000, 0o444)
    _write(root, f"{battery}/energy_full_design", 90000000, 0o444)
    _write(root, f"{battery}/cycle_count", 212, 0o444)
    _write(root, f"{battery}/power_now", 19500000, 0o444)

    _write(root, "/proc/stat", "cpu  1000 0 500 8000 200 0 0 0 0 0")
    _write(root, "/proc/meminfo", "MemTotal: 16000000 kB\nMemAvailable: 9000000 kB")
    _write(root, "/proc/net/dev", "h1\nh2\n  lo: 5 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0\n eth0: 1000 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0")
    for pid, name, memory, command in (
        (101, "firefox", 900000, "/usr/bin/firefox"),
        (102, "code", 700000, "/usr/share/code/code --type=renderer"),
        (103, "gnome-shell", 500000, "/usr/bin/gnome-shell"),
    ):
        _write(root, f"/proc/{pid}/status", f"Name:\t{name}\nUid:\t{os.getuid()}\t0\t0\t0\nVmRSS:\t{memory} kB")
        _write(root, f"/proc/{pid}/cmdline", command)
    _write(root, "/sys/class/hwmon/hwmon3/name", "nvme")
    _write(root, "/sys/class/hwmon/hwmon3/temp1_input", 41000)
    _write(root, "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", 3200000)
    _write(root, "/sys/bus/pci/devices/0000:01:00.0/class", "0x030000")
    _write(root, "/sys/bus/pci/devices/0000:01:00.0/vendor", "0x10de")
    _write(root, "/sys/bus/pci/devices/0000:01:00.0/boot_vga", "0")
    _write(root, "/sys/bus/pci/devices/0000:01:00.0/power/runtime_status", "active")
    _write(root, "/mock/nvidia-smi", "58, 34, 1200, 4096, 1500, 42.5, Demo GPU")

    keyboard = "/sys/class/hidraw/hidraw0/device"
    _write(
        root,
        f"{keyboard}/uevent",
        "HID_ID=0003:00000B05:00001866\nHID_NAME=Demo N-KEY Device\nHID_PHYS=usb-demo/input0",
    )
    _write(root, f"{keyboard}/report_descriptor", DESCRIPTOR)
    touchpad = "/sys/class/hidraw/hidraw1/device"
    _write(root, f"{touchpad}/uevent", "HID_ID=0018:000004F3:0000319B\nHID_NAME=Demo Touchpad")
    _write(root, f"{touchpad}/report_descriptor", TOUCHPAD_DESCRIPTOR)
    _write(root, "/dev/hidraw0", "")
    _write(root, "/dev/hidraw0.feature", ZONE_REPLY.hex())
    _write(root, "/dev/hidraw1", "")
    return root


def tick(root, profile=None):
    """Move the fake sensors so the dashboard and temperature mode are visible."""
    t = time.monotonic()
    load = {"quiet": -8, "performance": 12}.get(profile, 0)
    cpu = 58 + load + 18 * math.sin(t / 7)
    _write(root, "/sys/class/hwmon/hwmon5/temp1_input", int(cpu * 1000))
    _write(root, "/sys/class/hwmon/hwmon9/temp1_input", int((cpu - 6) * 1000))
    _write(root, "/sys/class/hwmon/hwmon6/fan1_input", int(max(0, (cpu - 35) * 120)))
    _write(root, "/sys/class/hwmon/hwmon6/fan2_input", int(max(0, (cpu - 32) * 135)))
    busy = int(t * 40)
    _write(root, "/proc/stat", f"cpu  {busy} 0 500 {int(t * 60)} 200 0 0 0 0 0")
    _write(root, "/proc/net/dev", f"h1\nh2\n eth0: {int(t * 90000)} 0 0 0 0 0 0 0 {int(t * 12000)} 0 0 0 0 0 0 0")
