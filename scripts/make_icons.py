#!/usr/bin/env python3
"""Make the app icon's standard sizes from the square artwork. A development tool.

Usage: make_icons.py SOURCE_IMAGE OUTPUT_DIR
"""
import pathlib
import sys

from PIL import Image, ImageDraw

SIZES = (16, 24, 32, 48, 64, 96, 128, 256, 512)
CROP = 0.88  # keeps the shield large, so it still reads at small sizes
CORNER = 0.225  # corner radius as a share of the icon's width
SUPERSAMPLE = 4


def cut_out(image):
    width, height = image.size
    side = int(min(width, height) * CROP)
    left, top = (width - side) // 2, (height - side) // 2
    square = image.crop((left, top, left + side, top + side)).convert("RGBA")
    large = side * SUPERSAMPLE
    mask = Image.new("L", (large, large), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, large - 1, large - 1), radius=int(large * CORNER), fill=255)
    square.putalpha(mask.resize((side, side), Image.LANCZOS))
    return square


def main():
    source, output = Image.open(sys.argv[1]).convert("RGB"), pathlib.Path(sys.argv[2])
    icon = cut_out(source)
    output.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        # Premultiplied, so see-through pixels can't bleed their colour into the edge when scaled.
        scaled = icon.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")
        scaled.putalpha(scaled.getchannel("A").point(lambda a: 0 if a < 8 else a))
        scaled.save(output / f"{size}.png", optimize=True)
    print("source", source.size, "icon", icon.size)


if __name__ == "__main__":
    main()
