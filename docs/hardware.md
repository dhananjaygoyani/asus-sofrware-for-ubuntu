# Hardware survey (Phase 0)

Collected 2026-11-06 with read-only commands and no sudo. Nothing was written to any device.
`dmidecode` needs root, so the identity below comes from `/sys/class/dmi/id`, which holds the same
fields. Serial numbers, UUIDs and `HID_UNIQ` were left out on purpose.

## Identity

| Field | Value |
|---|---|
| Vendor | ASUSTeK COMPUTER INC. |
| Product | ROG Strix G513QC_G513QC |
| Family / board | ROG Strix / G513QC |
| BIOS | G513QC.331 (02/24/2023) |
| Kernel | Linux 7.0.0-42-generic x86_64 |
| OS | Ubuntu 24.04.5 LTS |
| ASUS modules | asus_wmi, asus_nb_wmi, asus_armoury, asus_wireless, hid_asus |
| asusd / asusctl | Not installed, no process running, so no conflict |

## USB (`lsusb`)

```
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 001 Device 002: ID 0b05:1866 ASUSTek Computer, Inc. N-KEY Device
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 002 Device 003: ID 0bda:9210 Realtek Semiconductor Corp. RTL9210 M.2 NVME Adapter
Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 003 Device 002: ID 13d3:3563 IMC Networks Wireless_Device
Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
```

## ASUS hidraw devices

Only `hidraw0` has vendor 0B05. `hidraw1` is the touchpad (04F3:319B) and is out of scope.

```
DRIVER=asus
HID_ID=0003:00000B05:00001866
HID_NAME=ASUSTek Computer Inc. N-KEY Device
HID_PHYS=usb-0000:05:00.3-3/input0
MODALIAS=hid:b0003g0001v00000B05p00001866
```

`/dev/hidraw0` is `crw------- root root`. No existing udev rule grants access to it.

### Report descriptor (331 bytes)

```
00000000: 06 89 ff 09 10 a1 01 85 a5 09 01 15 00 26 ff 00
00000010: 75 08 95 10 b1 00 c0 06 82 ff 09 cf a1 01 85 c1
00000020: 09 62 15 00 26 ff 00 75 08 95 3c b1 02 09 66 15
00000030: 00 26 ff 00 75 08 95 10 81 02 09 61 15 00 26 ff
00000040: 00 75 08 95 3c 91 02 85 c2 09 8a 15 00 26 ff 00
00000050: 75 08 95 10 81 02 09 8e 15 00 26 ff 00 75 08 95
00000060: 10 91 02 c0 05 01 09 06 a1 01 85 01 75 01 95 08
00000070: 05 07 19 e0 29 e7 15 00 25 01 81 02 95 01 75 08
00000080: 81 03 95 05 75 01 05 08 19 01 29 05 91 02 95 01
00000090: 75 03 91 03 05 07 19 00 2a ff 00 15 00 26 ff 00
000000a0: 95 1e 75 08 81 00 05 07 19 00 29 df 15 00 25 01
000000b0: 95 e0 75 01 81 02 c0 06 31 ff 09 76 a1 01 85 5a
000000c0: 19 00 2a ff 00 15 00 26 ff 00 75 08 95 01 81 00
000000d0: 19 00 2a ff 00 15 00 26 ff 00 75 08 95 3f b1 00
000000e0: c0 06 31 ff 09 79 a1 01 85 5d 19 00 2a ff 00 15
000000f0: 00 26 ff 00 75 08 95 1f 81 00 19 00 2a ff 00 15
00000100: 00 26 ff 00 75 08 95 3f b1 00 19 00 2a ff 00 15
00000110: 00 26 ff 00 75 08 95 3f 91 02 c0 05 0c 09 01 a1
00000120: 01 85 02 19 00 2a 3c 02 15 00 26 3c 02 75 10 95
00000130: 01 81 00 c0 05 01 09 80 a1 01 85 04 19 81 29 83
00000140: 15 00 25 01 95 08 75 01 81 02 c0
```

Decoded by hand from the bytes above. Sizes are payload bytes, excluding the report ID. The Phase 2
parser should reproduce this table and use these bytes as its test fixture.

| Report ID | Usage page / usage | Input | Output | Feature | Likely role |
|---|---|---|---|---|---|
| 0xA5 | FF89 / 10 | - | - | 16 | Vendor, unknown |
| 0xC1 | FF82 / CF | 16 | 60 | 60 | Vendor, unknown |
| 0xC2 | FF82 / CF | 16 | 16 | - | Vendor, unknown |
| 0x01 | Generic Desktop / Keyboard | 60 | 1 | - | Keyboard keys and lock LEDs |
| 0x5A | FF31 / 76 | 1 | - | 63 | Vendor, to identify in Phase 1 |
| 0x5D | FF31 / 79 | 31 | 63 | 63 | Vendor, to identify in Phase 1 |
| 0x02 | Consumer / Control | 2 | - | - | Media keys |
| 0x04 | Generic Desktop / System Control | 1 | - | - | System keys |

The roles of 0x5A and 0x5D are not established yet. Phase 1 has to determine them.

## Platform profile

- `/sys/firmware/acpi/platform_profile`: `balanced`
- Choices: `quiet balanced performance`
- Class device: `/sys/class/platform-profile/platform-profile-0`

## Firmware attributes (`asus-armoury`)

`pending_reboot = 0`

| Attribute | Type | Current | Possible values / range | Display name |
|---|---|---|---|---|
| boot_sound | enumeration | 0 | 0;1 | Set the boot POST sound |
| charge_mode | enumeration | 2 | 0;1;2 | Show the current mode of charging |
| dgpu_disable | enumeration | 0 | 0;1 | Disable the dGPU |
| panel_overdrive | enumeration | 0 | 0;1 | Set the panel refresh overdrive |
| ppt_pl1_spl | integer | read fails (ENODEV) | min/max/default also fail; `scalar_increment = 1` | Set the CPU slow package limit |
| ppt_pl2_sppt | integer | read fails (ENODEV) | min/max/default also fail; `scalar_increment = 1` | Set the CPU fast package limit |

## `asus-nb-wmi` platform device

| File | Mode | Value |
|---|---|---|
| boot_sound | rw | 0 |
| charge_mode | ro | 2 |
| cpufv | write-only | not read |
| dgpu_disable | rw | 0 |
| panel_od | rw | 0 |
| ppt_pl1_spl | rw | 5 |
| ppt_pl2_sppt | rw | 5 |
| throttle_thermal_policy | rw | 0 |

## LEDs

`/sys/class/leds/asus::kbd_backlight`: `brightness = 3`, `max_brightness = 3`,
`brightness_hw_changed = 3`.

It has **no** `kbd_rgb_mode`, `kbd_rgb_state` or `multi_intensity` files, so the TUF sysfs RGB path does
not exist here. Colour control has to go through hidraw.

## hwmon

`asus` (hwmon6, the index can change between boots):

| File | Value |
|---|---|
| fan1_label / fan1_input | cpu_fan / 1900 RPM |
| fan2_label / fan2_input | gpu_fan / 2400 RPM |
| pwm1_enable | 2 |
| pwm2_enable | 0 |

`asus_custom_fan_curve` (hwmon7): `pwm1_enable = 2`, `pwm2_enable = 2`, 8 points per fan.

| Point | CPU temp °C | CPU pwm | GPU temp °C | GPU pwm |
|---|---|---|---|---|
| 1 | 58 | 2 | 58 | 2 |
| 2 | 60 | 17 | 60 | 38 |
| 3 | 63 | 25 | 63 | 63 |
| 4 | 66 | 99 | 66 | 71 |
| 5 | 69 | 130 | 69 | 114 |
| 6 | 74 | 158 | 74 | 150 |
| 7 | 79 | 188 | 79 | 186 |
| 8 | 98 | 255 | 98 | 255 |

Other hwmon: ADP0, acpitz, BAT0, nvme, ucsi_source_psy_USBC000:001, k10temp, mt7921_phy0, amdgpu.

## Battery

`/sys/class/power_supply/BAT0/charge_control_end_threshold = 100`

## Build and test environment

| Item | State |
|---|---|
| Python | 3.12.3 |
| GTK4 + libadwaita | Import works, Adw 1.5 |
| pkexec, xxd, pytest | Installed |
| Xvfb | **Not installed**, candidate `xvfb 2:21.1.12-1ubuntu1.9` |

## Findings that affect the design

1. **The PPT limits can't be rendered generically.** Every value read through `asus-armoury` fails with
   ENODEV, while `asus-nb-wmi` reports `5` for both. A 5 W limit is implausible for this laptop, so the
   `5` should not be trusted as a real limit. The app needs to handle unreadable attributes and must not
   write these until Phase 1 explains them.
2. **No GPU MUX or eGPU attributes exist.** `dgpu_disable` is the only GPU mode control here. The NVIDIA
   driver is loaded, so a dGPU-disable write needs a strong warning.
3. **Lighting beyond brightness needs hidraw.** There is no sysfs RGB interface on this model, so the udev
   rule and the root helper are required for colour.
4. **Whether this keyboard is per-key RGB is not known yet.** The survey can't show it. Phase 1 has to
   establish it before Aura Studio per-key painting is built.
5. **The meaning of some values is unverified.** `pwm2_enable = 0` on the `asus` hwmon, `pwm*_enable = 2` on
   the curve, and `charge_mode = 2` all need checking against the driver source in Phase 1.
6. **hwmon and hidraw numbers are not stable.** Find them by `name` and by HID vendor/product, never by
   index.
