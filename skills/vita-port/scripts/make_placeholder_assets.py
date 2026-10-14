#!/usr/bin/env python3
"""Write placeholder LiveArea images so a first VPK installs.

The Vita rejects non-indexed PNGs (error 0x8010113D), so every image is written as 8-bit
palette PNG (colour type 3) using only the standard library. Replace them with real art later.

Usage: make_placeholder_assets.py <sce_sys-dir>
Creates:  icon0.png (128x128), pic0.png (960x544),
          livearea/contents/bg.png (840x500), livearea/contents/startup.png (280x158),
          livearea/contents/template.xml (unless one exists)
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>

<livearea style="a1" format-ver="01.00" content-rev="1">
\t<livearea-background>
\t\t<image>bg.png</image>
\t</livearea-background>

\t<gate>
\t\t<startup-image>startup.png</startup-image>
\t</gate>
</livearea>
"""


def chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def write_indexed_png(path: Path, w: int, h: int, c0: tuple, c1: tuple) -> None:
    """Vertical gradient between c0 and c1 using a 64-entry palette."""
    n = 64
    palette = b"".join(
        bytes(int(c0[k] + (c1[k] - c0[k]) * i / (n - 1)) for k in range(3)) for i in range(n)
    )
    rows = []
    for y in range(h):
        idx = min(n - 1, y * n // h)
        rows.append(b"\x00" + bytes([idx]) * w)  # filter type 0 + pixels
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"PLTE", palette)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sce_sys", type=Path)
    args = ap.parse_args()
    root = args.sce_sys
    spec = [
        (root / "icon0.png", 128, 128, (30, 60, 120), (10, 20, 50)),
        (root / "pic0.png", 960, 544, (20, 20, 40), (60, 20, 80)),
        (root / "livearea/contents/bg.png", 840, 500, (20, 40, 90), (5, 10, 30)),
        (root / "livearea/contents/startup.png", 280, 158, (70, 110, 200), (30, 50, 120)),
    ]
    for path, w, h, a, b in spec:
        write_indexed_png(path, w, h, a, b)
        print(f"wrote {path} ({w}x{h}, indexed)")
    tpl = root / "livearea/contents/template.xml"
    if not tpl.exists():
        tpl.write_text(TEMPLATE, encoding="utf-8")
        print(f"wrote {tpl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
