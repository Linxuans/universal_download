#!/usr/bin/env python3
"""Generate the FetchDesk icon (PNG + multi-size ICO)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "gui" / "assets"
SIZE = 512
RADIUS = 112


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (SIZE, SIZE))
    px = gradient.load()
    top = (255, 199, 110)
    bottom = (230, 139, 18)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,)
        for x in range(SIZE):
            px[x, y] = color
    canvas.paste(gradient, (0, 0), rounded_mask(SIZE, RADIUS))

    draw = ImageDraw.Draw(canvas)
    ink = (27, 18, 4, 255)
    # Download arrow: shaft, head, tray.
    cx = SIZE // 2
    draw.rounded_rectangle((cx - 34, 116, cx + 34, 286), radius=34, fill=ink)
    draw.polygon([(cx - 116, 250), (cx, 366), (cx + 116, 250)], fill=ink)
    draw.rounded_rectangle((136, 386, 376, 424), radius=19, fill=ink)

    # Soft highlight in the upper-left.
    gloss = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gd.ellipse((-120, -190, 330, 210), fill=(255, 255, 255, 24))
    canvas = Image.alpha_composite(canvas, gloss)

    png = OUT / "icon.png"
    canvas.save(png, "PNG")
    ico = OUT / "icon.ico"
    canvas.save(ico, "ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(png)
    print(ico)


if __name__ == "__main__":
    main()