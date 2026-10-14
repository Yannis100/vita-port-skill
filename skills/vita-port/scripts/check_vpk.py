#!/usr/bin/env python3
"""Validate a PS Vita VPK before it goes near a console.

Checks the causes of most "installs but no bubble" and 0x8010113D failures:
  - eboot.bin exists and starts with the SELF magic ("SCE\\0")
  - sce_sys/param.sfo parses; TITLE_ID is exactly 9 characters; APP_VER looks like NN.NN
  - icon0.png / bg / startup (and optional pic0.png) exist, have the right size,
    and are indexed (colour type 3) PNGs; icon0 has no transparency
  - template.xml exists and is well-formed XML
Exit code 0 = no errors (warnings allowed), 1 = errors.

Usage: check_vpk.py game.vpk
"""
from __future__ import annotations

import re
import struct
import sys
import xml.dom.minidom
import zipfile

LIVEAREA = "sce_sys/livearea/contents/"
IMAGES = {
    "sce_sys/icon0.png": ((128, 128), True, True),
    "sce_sys/pic0.png": ((960, 544), False, False),
    LIVEAREA + "bg.png": ((840, 500), True, False),
    LIVEAREA + "bg0.png": ((840, 500), False, False),
    LIVEAREA + "startup.png": ((280, 158), True, False),
}
# path: (expected size, required, must_have_no_alpha)


def parse_sfo(data: bytes) -> dict:
    if data[:4] != b"\x00PSF":
        raise ValueError("bad PSF magic")
    _ver, key_off, data_off, count = struct.unpack_from("<IIII", data, 4)
    out = {}
    for i in range(count):
        koff, fmt, length, _maxlen, doff = struct.unpack_from("<HHIII", data, 20 + 16 * i)
        key = data[key_off + koff : data.index(b"\x00", key_off + koff)].decode("ascii", "replace")
        raw = data[data_off + doff : data_off + doff + length]
        out[key] = struct.unpack("<I", raw[:4])[0] if fmt == 0x0404 else raw.split(b"\x00")[0].decode("utf-8", "replace")
    return out


def png_info(data: bytes) -> dict:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, info, chunks = 8, {}, set()
    while pos + 8 <= len(data):
        length, tag = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8 : pos + 8 + length]
        chunks.add(tag)
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            info.update(w=w, h=h, depth=depth, ctype=ctype)
        pos += 12 + length
        if tag == b"IEND":
            break
    info["has_trns"] = b"tRNS" in chunks
    return info


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    errors: list[str] = []
    warns: list[str] = []
    try:
        z = zipfile.ZipFile(argv[1])
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"ERROR: cannot open VPK: {exc}")
        return 1
    names = set(z.namelist())

    if "eboot.bin" not in names:
        errors.append("eboot.bin missing")
    else:
        head = z.read("eboot.bin")[:4]
        if head != b"SCE\x00":
            errors.append(f"eboot.bin is not a SELF (magic {head!r}); run vita-make-fself")

    if "sce_sys/param.sfo" not in names:
        errors.append("sce_sys/param.sfo missing")
    else:
        try:
            sfo = parse_sfo(z.read("sce_sys/param.sfo"))
            tid = sfo.get("TITLE_ID", "")
            if len(tid) != 9:
                errors.append(f"TITLE_ID {tid!r} must be exactly 9 characters (XXXXYYYYY)")
            elif not re.fullmatch(r"[A-Z]{4}\d{5}", tid):
                warns.append(f"TITLE_ID {tid!r} is not 4 uppercase letters + 5 digits")
            ver = sfo.get("APP_VER", "")
            if not re.fullmatch(r"\d\d\.\d\d", ver):
                warns.append(f"APP_VER {ver!r} should look like 01.00")
            if "ATTRIBUTE2" in sfo:
                a2 = sfo["ATTRIBUTE2"]
                extra = {0x4: 29, 0x8: 77, 0xC: 109}.get(a2 & 0xC, 0)
                print(f"info: ATTRIBUTE2=0x{a2:X} (+{extra} MiB main memory)")
            print(f"info: TITLE_ID={tid} APP_VER={ver} TITLE={sfo.get('TITLE')!r} CATEGORY={sfo.get('CATEGORY')!r}")
        except Exception as exc:  # noqa: BLE001 - report any parse failure
            errors.append(f"param.sfo unreadable: {exc}")

    for path, (size, required, no_alpha) in IMAGES.items():
        if path not in names:
            if required and path != LIVEAREA + "bg.png":
                errors.append(f"{path} missing")
            elif path == LIVEAREA + "bg.png" and LIVEAREA + "bg0.png" not in names:
                errors.append("livearea/contents/bg.png (or bg0.png) missing")
            continue
        raw = z.read(path)
        try:
            info = png_info(raw)
        except ValueError as exc:
            errors.append(f"{path}: {exc}")
            continue
        if (info["w"], info["h"]) != size:
            errors.append(f"{path}: size {info['w']}x{info['h']}, expected {size[0]}x{size[1]}")
        if info["ctype"] != 3:
            errors.append(f"{path}: colour type {info['ctype']} is not indexed (type 3): install error 0x8010113D; use pngquant")
        if no_alpha and info["has_trns"]:
            warns.append(f"{path}: has transparency (tRNS); icon0 should have no alpha")
        if len(raw) > 420 * 1024:
            warns.append(f"{path}: {len(raw) // 1024} KB; community guides cap LiveArea PNGs near 420 KB")

    tpl = LIVEAREA + "template.xml"
    if tpl not in names:
        errors.append(f"{tpl} missing")
    else:
        try:
            xml.dom.minidom.parseString(z.read(tpl))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{tpl}: not well-formed XML ({exc})")
        if len(z.read(tpl)) > 32 * 1024:
            warns.append(f"{tpl}: larger than 32 KB")

    for w in warns:
        print(f"WARN:  {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"{len(names)} entries; {len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
