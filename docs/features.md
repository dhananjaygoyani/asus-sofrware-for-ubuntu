# Armoury Crate feature comparison

Features were listed from Armoury Crate 6.7.6.0 as installed on this laptop's Windows partition: its plugin folders
(`Load.conf`), resource names in `resources.pri`, and strings and decompiled code in its plugins using REA. No ASUS
code or assets are in OpenArmoury; these features are written from scratch on Linux interfaces.

"Your laptop" means the ROG Strix G513QC. "Tested" below means on a mock laptop unless it says otherwise.

## Built

| Armoury Crate feature | Evidence | In OpenArmoury | How it works on Linux |
|---|---|---|---|
| Operating modes | `ThrottleMonitorPlugin` | Performance | `platform_profile` |
| Manual fan control, Fan Xpert | `FanControlLibrary` | Fans, including a full-speed preset | `asus_custom_fan_curve` |
| GPU mode: Eco and Standard | `GPUMode` | Performance | `dgpu_disable`, with warnings |
| GPU mode: Ultimate | `GPUMode` | Performance, if the laptop has a MUX switch | `gpu_mux_mode`. **Your laptop has none** |
| Manual CPU and GPU power limits | `CPUControlLibrary` | Performance, using the kernel's limits | Firmware attributes. **Not available on your laptop**: the kernel has no limits for it |
| Panel overdrive, boot sound, charging info, and other firmware settings | `SystemFeature` | System | Firmware attributes |
| Battery care charge limits | `resources.pri` | System: Full, Balanced, Longest life | `charge_control_end_threshold` |
| One-time full charge | `resources.pri` | System | Same, then restores your limit |
| Battery information | `resources.pri` | System and Monitor | `power_supply` |
| Touchpad lock | `SystemFeature` | System and scenarios | GNOME setting |
| Win key lock | `SystemFeature` | System and scenarios | GNOME setting. **Partial**: stops Activities, while Win+ shortcuts still work |
| ROG key | `SystemFeature` | System: opens the app | GNOME shortcut |
| Microphone mute | `CustomHotkey` | System | PipeWire |
| Panel refresh rate, Panel Power Saver | `SystemFeature` | System, and automatic on battery | GNOME display settings. **GNOME only** |
| Lighting effects | `AacNBDTHal` | Lighting | HID packets |
| Brightness | `AacNBDTHal` | Lighting | LED class device |
| Boot, awake, sleep and shutdown lighting | `AuraPlugin` | Lighting | HID packet, gated as unproven |
| Lighting on battery | `AuraPlugin` | Scenarios: brightness on battery | LED class device |
| Aura Creator effects | `AuraEditor` | Light Studio | Own keyframe editor and direct packets |
| Smart lighting: by CPU or GPU temperature, or CPU load | `resources.pri` | Light Studio, plus battery level | Sensors |
| Music effect | `resources.pri` | Light Studio | PipeWire loudness |
| Resource monitor | `ThrottleMonitorPlugin` | Monitor | `/proc` and `/sys` |
| Free up memory | `SystemFeature` | Monitor: close large apps | Asks programs to quit normally |
| Scenario Profiles | `ScenarioProfile` | Scenarios | Watches running programs |
| Game Library | `GameLibraryPlugin` | Scenarios: list, launch, add a scenario | Steam manifests and the desktop's app list |
| Macros | `Macros` | Macros | Recording in-app, playback through `/dev/uinput` |
| Custom hotkeys | `CustomHotkey` | Macros: a shortcut per macro | GNOME shortcuts |
| Back up settings | `resources.pri` | System | JSON file; approvals are never included |
| Runs in the background | Service design | System | Keeps running without a window |

## Partly built

| Feature | What's missing | Why |
|---|---|---|
| GameVisual | Only night light and its warmth | Colour presets need per-display colour calibration. GNOME's own colour settings cover profiles |
| Reactive lighting (keys light when pressed) | Not built | It needs to read every keypress system-wide, which is keylogger-level access. Not worth that risk by default |
| Screen-matching lighting | Not built | Needs screen capture permission on each start under Wayland, and would use a lot of CPU |
| Aura Sync across other devices | Laptop keyboard only | Each mouse, headset or motherboard has its own protocol, and none are here to test on |
| Hardware key remapping | ROG key only | Fn+F5 uses a key code the desktop can't bind. The kernel handles it where supported |

## Not built, on purpose

| Feature | Why |
|---|---|
| Firmware updates, device updates | A failed update can break hardware. Use Ubuntu's Firmware Updater (`fwupd`) |
| Driver and service updates | Ubuntu's `apt` and "Additional Drivers" handle these |
| GPU overclocking | Needs a dGPU tool and wakes the GPU; the risk isn't justified without vendor limits |
| AniMe Matrix, Slash lighting, Keystone, MultiWheel | Your laptop has none of this hardware, so none of it could be tested |
| ASUS account, News, Store, Deals, Redemption, Feedback, telemetry | Online ASUS services. They don't control the laptop |
| GlideX, Mobile Control, Xbox Game Bar widget | Windows-only or tied to ASUS's cloud |
| AI Noise Cancelling | Would need a separate audio pipeline. Worth doing separately if you want it |
| BitLocker prompts, Virtual Drive, WSC | Windows-only |
