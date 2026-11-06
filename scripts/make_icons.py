#!/usr/bin/env python3
"""Cut the app icon out of its light background and write the standard sizes. A development tool.

Usage: make_icons.py SOURCE_IMAGE OUTPUT_DIR
"""
import pathlib
import sys

from PIL import Image, ImageChops, ImageDraw

SIZES = (16, 24, 32, 48, 64, 96, 128)
LIGHT = 40  # how far from the background a pixel must be to count as part of the icon
CORNER = 0.235  # corner radius as a share of the icon's width
SUPERSAMPLE = 4


def icon_bounds(image):
    """The box around everything that isn't the plain background."""
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background).convert("L").point(lambda v: 255 if v > LIGHT else 0)
    return difference.getbbox()


def cut_out(image):
    left, top, right, bottom = icon_bounds(image)
    side = max(right - left, bottom - top)
    square = image.crop((left, top, left + side, top + side)).convert("RGBA")
    # Inset slightly, so no light background shows along the curved edge.
    large = side * SUPERSAMPLE
    mask = Image.new("L", (large, large), 0)
    inset = SUPERSAMPLE
    ImageDraw.Draw(mask).rounded_rectangle((inset, inset, large - inset - 1, large - inset - 1), radius=int(large * CORNER), fill=255)
    square.putalpha(mask.resize((side, side), Image.LANCZOS))
    return square


def main():
    source, output = Image.open(sys.argv[1]).convert("RGB"), pathlib.Path(sys.argv[2])
    icon = cut_out(source)
    output.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        icon.resize((size, size), Image.LANCZOS).save(output / f"{size}.png")
    print("source", source.size, "icon", icon.size)


if __name__ == "__main__":
    main()
