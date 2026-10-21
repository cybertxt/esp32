#!/usr/bin/env python3
"""Regenerate the menu-bar lamp icon (AgentLamp/lamp_icon.png).

The icon is a single-color lightbulb silhouette with a transparent
background, saved as an RGBA PNG so macOS template mode renders it in the
menu bar's own tint. Pure standard library; run from anywhere:

    python3 AgentLamp/tools/make_icon.py
"""

import os
import struct
import zlib

ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lamp_icon.png"
)
SCALE = 2  # 16px art -> 32px image: crisp on retina menu bars

# 16x16 pixel art: "#" opaque, "." transparent.
G = [
    "................",
    "......####......",
    "....########....",
    "...##########...",
    "...##########...",
    "...##########...",
    "....########....",
    ".....######.....",
    "......####......",
    ".....######.....",
    ".....######.....",
    "......####......",
    "......####......",
    ".......##.......",
    "................",
    "................",
]


def chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path, grid, scale):
    h, w = len(grid), len(grid[0])
    raw = bytearray()
    for y in range(h * scale):
        raw.append(0)  # PNG filter type 0 for each scanline
        for x in range(w * scale):
            on = grid[y // scale][x // scale] == "#"
            raw.extend((0, 0, 0, 255 if on else 0))
    ihdr = struct.pack(">IIBBBBB", w * scale, h * scale, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)


def main():
    write_png(ICON_PATH, G, SCALE)
    print("wrote", ICON_PATH, "(%dx%d px)" % (len(G[0]) * SCALE, len(G) * SCALE))


if __name__ == "__main__":
    main()