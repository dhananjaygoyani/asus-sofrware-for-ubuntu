#!/usr/bin/env python3
"""Convert asusctl's keyboard data (MPL-2.0) to JSON. A development tool, not needed at runtime.

Usage: import_asusctl.py /path/to/asusctl
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "openarmoury" / "data" / "asusctl"


def strip_comments(text):
    return re.sub(r"//[^\n]*", "", text)


def parse_support(text):
    entries = []
    for chunk in re.findall(r"\(\s*device_name:.*?power_zones: \[[^\]]*\],?\s*\)", strip_comments(text), re.S):
        def field(name):
            found = re.search(name + r': "([^"]*)"', chunk)
            return found[1] if found else ""

        def listing(name):
            found = re.search(name + r": \[([^\]]*)\]", chunk)
            return re.findall(r"\w+", found[1]) if found else []

        advanced = re.search(r"advanced_type: (r#None|PerKey|Zoned\(\[([^\]]*)\]\))", chunk)
        zoned = re.findall(r"\w+", advanced[2]) if advanced and advanced[2] else []
        kind = "per-key" if advanced and advanced[1] == "PerKey" else "zone" if zoned else "none"
        entries.append(
            {
                "device": field("device_name"),
                "product": field("product_id"),
                "layout": field("layout_name"),
                "modes": listing("basic_modes"),
                "zones": listing("basic_zones"),
                "advanced": kind,
                "advanced_zones": zoned,
                "power_zones": listing("power_zones"),
            }
        )
    return entries


def parse_layout(text):
    text = strip_comments(text)
    shapes = {}
    for name, kind, body in re.findall(r'"(\w+)":\s*(Led|Blank)\((.*?)\)', text, re.S):
        values = {k: float(v) for k, v in re.findall(r"(\w+): (-?[\d.]+)", body)}
        shapes[name] = (kind, values)
    keys = []
    y = 0.0
    for row_body in re.findall(r"\(\s*pad_left:.*?row: \[(.*?)\],?\s*\)", text, re.S):
        x = 0.0
        height = 0.0
        for code, shape in re.findall(r'\((\w+), "(\w+)"\)', row_body):
            kind, v = shapes[shape]
            if kind == "Blank":
                x += v.get("width", 0)
                continue
            left, top = v.get("pad_left", 0), v.get("pad_top", 0)
            keys.append(
                {
                    "code": code,
                    "x": round(x + left, 3),
                    "y": round(y + top, 3),
                    "w": v["width"],
                    "h": v["height"],
                }
            )
            x += left + v["width"] + v.get("pad_right", 0)
            height = max(height, top + v["height"] + v.get("pad_bottom", 0))
        y += height
    # Some layouts use negative padding, so shift everything to start at zero.
    min_x = min((k["x"] for k in keys), default=0)
    min_y = min((k["y"] for k in keys), default=0)
    for key in keys:
        key["x"] = round(key["x"] - min_x, 3)
        key["y"] = round(key["y"] - min_y, 3)
    return keys


def parse_led_map(text):
    """LED code to (row, column) in the per-key packets, and to column in the zone packet."""
    per_key = {}
    zoned = {}
    body = text[text.index("fn rgb_for_led_code") :]
    body = body[: body.index("return None")]
    pattern = r"((?:LedCode::\w+\s*\|?\s*)+)=>\s*(?:if zoned \{\(0, (\d+)\)\}\s*else\s*\{\s*)?\((\d+), (\d+)\)"
    for names, zone_column, row, column in re.findall(pattern, body):
        for name in re.findall(r"LedCode::(\w+)", names):
            per_key[name] = [int(row), int(column)]
            if zone_column:
                zoned[name] = int(zone_column)
            elif int(row) == 0:
                zoned[name] = int(column)
    return {"per_key": per_key, "zoned": zoned}


def main():
    source = pathlib.Path(sys.argv[1])
    data = source / "rog-aura" / "data"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "support.json").write_text(
        json.dumps(parse_support((data / "aura_support.ron").read_text()), indent=0) + "\n"
    )
    layouts = {
        path.name[: -len("_US.ron")]: parse_layout(path.read_text()) for path in sorted((data / "layouts").glob("*_US.ron"))
    }
    (OUT / "layouts.json").write_text(json.dumps(layouts, separators=(",", ":")) + "\n")
    led_map = parse_led_map((source / "rog-aura" / "src" / "keyboard" / "advanced.rs").read_text())
    (OUT / "led_map.json").write_text(json.dumps(led_map, indent=0) + "\n")
    shutil.copy(source / "LICENSE", OUT / "LICENSE")
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (OUT / "NOTICE").write_text(
        "support.json, layouts.json and led_map.json are converted from asusctl\n"
        f"(https://github.com/opengamingcollective/asusctl, commit {commit}).\n"
        "They remain under the Mozilla Public License 2.0; see LICENSE in this folder.\n"
    )
    print(len(layouts), "layouts,", len(led_map["per_key"]), "LEDs")


if __name__ == "__main__":
    main()
