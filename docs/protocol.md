# Protocol notes (Phase 1)

Interoperability notes for ASUS laptop keyboard lighting, fans and power. This file records facts and where
they were observed. It contains no ASUS code. Nothing here has been tested on hardware yet.

## How to read the labels

| Label | Meaning |
|---|---|
| **CONFIRMED** | Seen in ASUS's shipped code with REA, and matches asusctl or the Linux drivers |
| **RE-ONLY** | Seen in ASUS's shipped code only; no open-source match found |
| **UNCERTAIN** | Open-source only, sources disagree, or the meaning is inferred. Needs your approval before it touches hardware |

Facts found only in open source are labelled UNCERTAIN, because the brief's three labels have no separate
"source-only" category.

## Sources

Static analysis only. No ASUS program was run.

| Component | Version / identity | SHA-256 (first 16) |
|---|---|---|
| `AacNBDTHal_x64.dll` (notebook keyboard hardware layer) | Installed with Armoury Crate 6.7.6.0 | `2b74814afdf28dba` |
| `FanControlLibrary.dll` | Same install | `d0f23dc75d1abdff` |
| `ArmouryCrate.ThrottlePlugin.dll` | Same install | `5299b871586f3ff7` |
| `CPUControlLibrary.dll` | Same install | `b09f74780daf81e8` |

- **Why the installed copy:** the official full installer (package 1.4.4.3) keeps its components in encrypted
  `.enc`/`.dat` files. They were not decrypted. The files above were copied read-only from the Windows
  partition on this laptop, where the normal installer had already unpacked them.
- **Decompiler:** Ghidra 12.1.4 through REA. Pseudocode is decompiler output, not original source. REA evidence
  IDs below were retained for that session only and act as digests.
- **Open-source cross-checks:** asusctl `5133a5d` (2026-11-05, MPL-2.0), and `hid-asus.c`, `asus-wmi.c`,
  `asus-wmi.h`, `asus-armoury.c/.h` from upstream Linux master. Upstream master is not guaranteed to match the
  running 7.0 kernel.

## 1. Finding the keyboard

| Fact | Evidence | Cross-check | Label |
|---|---|---|---|
| Lighting uses vendor page `0xFF31`, usage `0x79`, report `0x5D` | Device table at `0x1800580b0`; usage-page test in `0x180009e40` | Your descriptor has exactly this collection (`docs/hardware.md`); asusctl uses `0x5D` | CONFIRMED |
| Usage `0x76` is report `0x5A` | Table entry 2 | Your descriptor; `FEATURE_KBD_REPORT_ID` in `hid-asus.c` | CONFIRMED |
| One product ID can be either zone or per-key | Table entries 5 and 8 for `0x1866`: 4 LEDs and 168 LEDs | asusctl treats these as per-model data | CONFIRMED |

Device table, read directly from file offset `0x566b0` (28-byte rows):

| PID | Usage | Class | LEDs | Report |
|---|---|---|---|---|
| 1866, 19b6, 1869 | 79 | zone (`0x81001`) | 4 | 5D |
| 1866, 19b6 | 79 | per-key (`0x81000`) | 168 (21×8) | 5D |
| 18bc | 79 | per-key | 231 (21×11) | 5D |
| 18c6 | 79 | zone | 10 | 5D |
| 1a30 | 79 | zone | 1 | 5D |
| 1abe, 1b4c, 1866 | 76 | per-key class, "game console" check | 1 | 5A |

This table is incomplete: asusctl also lists `0x1ce6` and others. **The app should discover the interface from
the HID descriptor, not from this list.**

## 2. Self-description handshake

Function `0x180008520`, evidence `ev_a71e9559069712cf`. **This is what makes a model-independent app possible.**

| Step | Bytes (`ID` = report ID) | Label |
|---|---|---|
| 1. Set Feature | `ID` + `ASUS Tech.Inc.` + `00` | CONFIRMED: same bytes in `asus_kbd_init` |
| 2. Get Feature | Read back; the kernel expects an echo | CONFIRMED |
| 3. Set Feature | `ID 05 20 31 00 1A` | CONFIRMED form: kernel sends `05 20 31 00 08` |
| 4. Get Feature | Reply must start `ID 05 20 31 00` | CONFIRMED form |

The length byte is `0x10` for names containing `GZ700`/`GZ701` (`ev_eda86476f01b82f3`). The kernel uses `0x08`
and reads only byte 6.

Reply layout (byte offsets include the report ID):

| Offset | Meaning | Label |
|---|---|---|
| 9 | Backlight type, see section 3 | RE-ONLY |
| 10 | Keyboard year. Values above `0x22` also report series and LED counts. Reading it as a BCD year is an inference | RE-ONLY |
| 12 | Keyboard language | RE-ONLY |
| 13 | Bits: `01` logo, `02` lightbar, `10` V-cut, `20` aero, `40` bump, `80` rear glow | RE-ONLY |
| 14 | Bits: `08` RGB wheel, `40` bit-format key positions, `80` reset key-input target | RE-ONLY |
| 15 | Bit `01` macro key | RE-ONLY |
| 17 | Series: `01` Strix, `02` Flow, `04` Zephyrus, `08` TUF, `10` SE, `20` desktop | RE-ONLY |
| 18–23 | LED counts: lightbar, logo, aero, V-cut, rear glow, bump | RE-ONLY |

Your G513QC is a 2021 model, so its year byte may not exceed `0x22`. If so, the series and LED counts won't be
reported and only the flag bytes apply. **UNCERTAIN until read from the hardware.**

## 3. Backlight type decides the lighting path

Dispatcher `0x18001d500`, with class checks in `0x180009e40`.

| Type | Path | Label |
|---|---|---|
| 1, 2, 4 | Zone direct, `0x180012040`. 4 colours, or 1 for type 4 | RE-ONLY |
| 3 | Per-key, `0x180010e80` | RE-ONLY |
| `0xD0`–`0xD3` | Separate format, `0x180012b20`. The class check labels `0`/`0xD0`–`0xD2` as desktop | RE-ONLY, not for laptops without approval |

asusctl's model table lists `G513Q` as 4-zone with no per-key mode. That matches a zone type on your laptop, but
**the actual type byte is unread**.

## 4. Report transport

`0x18000aee0` and `0x180009e40`, using Windows HID capabilities.

| Fact | Cross-check | Label |
|---|---|---|
| If the collection has an Output report, send with `WriteFile`; otherwise Set Feature | asusctl writes to hidraw | CONFIRMED |
| Buffer length is the Feature report length | asusctl pads to 64 after finding short writes dropped; your `0x5D` is 63 + 1 | CONFIRMED |

## 5. Built-in effects (`b3`)

Builder `0x180010b70`, `ExecCmd2RGBKB` path.

| Byte | 0 | 1 | 2 | 3 | 4–6 | 7 | 8 |
|---|---|---|---|---|---|---|---|
| Value | `5D` | `B3` | zone | mode | R G B | speed | direction |

| Fact | Evidence | Cross-check | Label |
|---|---|---|---|
| Layout above | `0x180010b70` | `builtin_modes.rs` | CONFIRMED |
| Byte 2 is always 0 in this ASUS path | `0x180010b70` | asusctl fills 1–7 for zones, per its captured packets | UNCERTAIN for non-zero values |
| Speed `F5`, `EB`, `E1` | `0x180010b70` | asusctl: High, Med, Low | CONFIRMED |
| Direction at byte 8 | `0x180010b70` | asusctl: 0 right, 1 left, 2 up, 3 down | Position CONFIRMED, meanings UNCERTAIN |
| Second colour at bytes 10–12 | Not set in this ASUS path | asusctl only | UNCERTAIN |

Wire mode values (mapping `0x18000cee0`; names are from asusctl):

| Value | Name | Label |
|---|---|---|
| 0, 1, 2, 3 | Static, Breathe, Colour Cycle, Wave | CONFIRMED |
| 4–8 | Star, Rain, Highlight, Laser, Ripple | Pass-through in ASUS mapping; names UNCERTAIN |
| `0A`, `0B`, `0C` | Pulse, Comet, Flash | CONFIRMED |
| `0D`, `0E` | Unknown | RE-ONLY |

asusctl lists Static, Breathe, Colour Cycle, Wave and Pulse for `G513Q`. **Offer only what's verified per model.**

## 6. Commit and flash

ASUS sends `b4` then `b5` after every `b3` (`0x180010b70`, via `0x18000b380`).

| Fact | Label |
|---|---|
| asusctl calls `b5` SET and `b4` APPLY, and sends effect, `b5`, `b4` | Packets CONFIRMED; **the order differs from ASUS** |
| asusctl's comment says changes don't persist without APPLY, and its temporary path omits `b4` | UNCERTAIN: suggests `b4` saves to flash |
| **Which packet writes flash is not proven** | UNCERTAIN |

Rule for the app: software animations send only `bc` packets, never `b3`, `b4` or `b5`.

## 7. Direct colour (`bc`), non-persistent path

Neither direct path below sends `b4` or `b5` in the code read.

**Zones** (`0x180012040`). First use: `5D BC T` once, where `T` = 2 for type 1, otherwise 1.

| Byte | 0 | 1 | 2 | 3 | 4 | 9… |
|---|---|---|---|---|---|---|
| Value | `5D` | `BC` | `T` | `01` | `00`, or `04` for some classes | R G B per zone |

- asusctl documents `5D BC 01 01 04` with colours from byte 9, which matches type 2/4-zone. CONFIRMED.
- asusctl's single-zone form uses `01` in byte 2, where ASUS uses `02` for type 1. UNCERTAIN.
- Lightbar, logo and other regions occupy later, class-specific offsets. UNCERTAIN.
- **Your LED map:** zone *n* (0–3) is at byte `9 + 3n`. asusctl names them left to right. Physical order is
  UNCERTAIN until seen on your keyboard.

**Per-key** (`0x180010e80`), not applicable to your laptop if it reports a zone type. First use: `5D BC` + zeros.

| Byte | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 9… |
|---|---|---|---|---|---|---|---|---|---|
| Value | `5D` | `BC` | `00` | `01` | `01` | `01` | group << 4 | count (16 max) | R G B |

- Matches `advanced.rs`, including 11 packets for 168 LEDs. CONFIRMED.
- The LED-to-key index isn't in the packet. asusctl has 18 layout files under MPL-2.0, and ASUS can also build a
  map at runtime. Layouts are per-keyboard data, so **per-key on an unlisted model needs a new layout**.

## 8. Brightness and power states

| Fact | Evidence | Label |
|---|---|---|
| Brightness `ID BA C5 C4 level` | `0x18001b790`; `asus_kbd_set_brightness` | CONFIRMED |
| Levels 0–3 | Your sysfs `max_brightness = 3` | CONFIRMED |
| Power states `5D BD 01 b1 b2 b3 b4`, with `0x1866` bits for awake, boot and sleep | asusctl only; no `BD` packet found in this DLL | UNCERTAIN |

Use `/sys/class/leds/asus::kbd_backlight` for brightness. It already works and needs no hidraw.

### Power states, from the second analysis

`ArmouryCrate.AuraPlugin.dll` (SHA-256 `88eefb3e5116c070`), function `0x180241600`, reads the current state back with
`ID 9E 01 15` (or `20`) followed by Get Feature.

| Fact | Evidence | Label |
|---|---|---|
| Reply byte `0x16` bits: `02` keyboard boot, `08` awake, `20` sleep, `80` shutdown; `01` and `04` logo | `0x180241600` | CONFIRMED: matches asusctl's `new_to_byte` for current keyboards |
| Reply also holds the current mode (byte 6), colour (7–9), speed (10), direction (11), second colour (13–15) | `0x180241600` | RE-ONLY, not used |
| Sending uses `5D BD 01` + 4 flag bytes | asusctl only; the sender wasn't located | UNCERTAIN |
| `0x1866` layout: `08 00 02 00` keyboard awake, `04 05 02 00` lightbar awake, `FF 1F 0F 00` all | asusctl tests only | UNCERTAIN, shown with a warning before use |

## 9. Not to be used

| Packet | Observed | Label |
|---|---|---|
| `5D B6 02 …` sync | `0x18001ed80` | RE-ONLY, purpose unclear |
| `5D D1 08 …` | `0x180012860`, series `0x17` only | RE-ONLY |
| `5D C2`, `5E 0D`, `E6` | Matrix, Slash, XG Mobile checks | RE-ONLY, out of scope |

## 10. WMI device IDs

On Linux, use the kernel interfaces. These IDs confirm those interfaces match what ASUS calls.

| ID | Function | Evidence | Kernel name | Label |
|---|---|---|---|---|
| `0x110024` | CPU fan curve | `FanControlLibrary` `0x180001220` (`ev_c8af70ebc607c3c3`) | `CPU_FAN_CURVE` | CONFIRMED |
| `0x110025` | GPU fan curve | Same | `GPU_FAN_CURVE` | CONFIRMED |
| `0x110032` | Mid fan curve | Same | `MID_FAN_CURVE` | CONFIRMED |
| `0x120075` | Thermal policy | `ThrottlePlugin` `GetThermalPolicy`, `0x180004100` (`ev_f236a3bce0479f74`) | `THROTTLE_THERMAL_POLICY` | CONFIRMED |
| `0x1200A3` | PL1 | `CPUControlLibrary`, within `AmdProcessorDevice_SetCPUTuningValue` (`ev_8bd2186b9b99e31b`) | `PPT_PL1_SPL` | CONFIRMED, weaker: managed code, bytes located but not decoded |
| `0x1200A0`, `0x1200C1`, `0x1200B0`, `0x1200B1` | PL2, PL3, APU, platform | Same region | `PPT_*` | CONFIRMED, weaker |
| `0x110013`, `0x110014` | Fan control | Byte match in `FanControlLibrary` only | `CPU_FAN_CTRL`, `GPU_FAN_CTRL` | UNCERTAIN: usage not read |

### Kernel behaviour

| Fact | Source | Label |
|---|---|---|
| Curve `pwmN_enable`: `1` on, `2` off, `3` reset to factory | `fan_curve_enable_store` | UNCERTAIN (source only) |
| So your `pwm*_enable = 2` means curves are currently off | Same | UNCERTAIN (source only) |
| Fan hwmon `pwm1_enable`: `0` full, `1` manual, `2` auto; the value read is a driver cache | `asus-wmi.c` | UNCERTAIN (source only) |
| `pwm2_enable = 0` may not reflect the real fan state, since your fan was turning below full speed | Your survey | UNCERTAIN |
| Changing `pwm1_enable` disables custom curves | `pwm1_enable_store` | UNCERTAIN (source only) |
| `charge_mode` is read-only; the meaning of `2` remains unknown | `asus-armoury.c` | UNCERTAIN |

### Your CPU power limits

The `power_limits` table in `asus-armoury.h` lists `G513QM` and `G513QY` but not `G513QC`. With no match, the
tunables aren't set up, which fits the ENODEV reads from Phase 0. **The `5` from `asus-nb-wmi` is unexplained.**
The app will show these as unavailable and won't write them. Checked against upstream master, not your 7.0 build.

## 11. Design for "any ASUS laptop"

Detect capabilities at runtime. Don't branch on model names.

| Capability | Detection |
|---|---|
| Keyboard interface | ASUS vendor ID, then a collection on page `0xFF31` with report `0x5D` from the descriptor |
| Output vs Feature, length | Parsed descriptor |
| Zone vs per-key, regions | Handshake reply |
| TUF RGB | `kbd_rgb_mode` exists |
| Brightness | LED class device |
| Profiles, fans, charge limit, firmware attributes | The sysfs files that exist |
| Key layout | Data file per layout, otherwise no per-key painting |

Limits to be honest about:

- Only your G513QC can be tested here. All other models stay **untested**.
- Mode lists can't be fully discovered: the reply doesn't list modes. The list has to be conservative, or come from
  asusctl's table with attribution.
- Older keyboards may not answer the handshake. They fall back to brightness only.
- This file covers one Armoury Crate version. Other families may behave differently.

## 12. Not analysed

- `ArmouryCrate.AuraPlugin.dll`, `AuraEditor.dll` and the `.ini` files. Aura Studio's keyframe editor will be our own
  design, so these weren't needed for the protocol.
- GPU mode logic in `ArmouryCrate.GPUMode.dll`. The kernel's `dgpu_disable` is the interface here.
- Runtime behaviour. Everything here is static; no USB capture was taken.
