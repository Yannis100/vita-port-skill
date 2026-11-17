#!/usr/bin/env python3
"""Write a linker-script fragment that puts the hottest functions at the start of .text.

Every function a CPU profile sampled gets the sum, over all profiles, of its share of that profile's
samples (each profile weighs the same). The hottest go first as `*(.text.<mangled>)` input patterns,
then selected whole static libraries (vitaGL, libgcc, libc ...), then every function no profile saw.

WHY THIS MATTERS: on ARM a call more than ~16 MB away cannot be encoded as a direct branch, so the
linker inserts a **long-branch veneer** (an extra branch through a stub) at that call site. A large
Vita binary easily separates its hot code from a cold static library by more than that, which puts a
trampoline on exactly the paths that run most. Ordering `.text` by measured heat removes them from
those paths. It changes link order only -- no algorithm, no source, no behaviour.

Requires `-ffunction-sections`, otherwise every function shares one input section `.text` and none of
the per-function patterns can match. The script warns if the ELF it inspects has no `.text.*`.

WHICH LINKER FLAG -- this differs by linker and the difference is not cosmetic (measured 2026-11-16,
GNU ld 2.46.1 from VitaSDK):

  * GNU ld's `--section-ordering-file` **cannot do this job.** It orders *output* sections, requires
    each named section to already exist ("output section '.text.x' must already exist"), and rejects
    `SECTIONS { }` and bare globs as syntax errors. Passing this fragment to it fails.
  * `-Wl,-T,<this file>` **works**: the fragment is merged after the default script and the listed
    functions come out in the requested order (verified: a 3-function test linked to cold/main/hot at
    offsets 0/4/8, and `.rodata`/`.data`/`.bss` were still present -- 36 sections).
  * `-Wl,--sort-section,name` reorders but **alphabetically**, which is not heat order.

  CAVEAT, and check it on your own build: a `-T` fragment can disturb the default script's segment
  and entry-point handling. On a bare test link the entry point came out 0x0 where the default script
  would have set it, so **verify the entry point and the SELF/VPK still work** before shipping. If they
  do not, define the full output sections in the fragment rather than only `.text`.

Input format (what Vita3K writes with its profiler enabled; one sample per line):
    <thread> <pc-hex> <lr-hex> <weight>
Lines that do not match are ignored, so a filtered emulator log can be fed in directly.

Usage:
    vita_hot_order.py <out.ld> <profile>:<elf> [<profile>:<elf> ...] [--size-elf <elf>]

  <profile>   a CPU profile as above. Several may be given; each is normalised, so a long run cannot
              outvote a short one.
  <elf>       the ELF the profile was taken from; symbols resolve there, so profiles of an older build
              still work.
  --size-elf  after writing, report how much code the hot set covers in this ELF at
              50 / 90 / 99 / 100 % of the sampled weight, and warn past the 16 MB branch range.

Exit status: 0 written; 2 usage or input error.
"""
from __future__ import annotations

import argparse
import bisect
import os
import subprocess
import sys
from collections import Counter

DEFAULT_LIBS = (
    "libvitaGL.a",
    "libgcc.a",
    "libgcc_eh.a",
    "libpthread.a",
    "libm.a",
    "libc.a",
    "libsupc++.a",
    "libstdc++.a",
)

BRANCH_RANGE = 16 * 1024 * 1024


def _nm() -> str:
    """arm-vita-eabi-nm from VITASDK, falling back to PATH."""
    sdk = os.environ.get("VITASDK")
    if sdk:
        cand = os.path.join(sdk, "bin", "arm-vita-eabi-nm")
        if os.path.exists(cand):
            return cand
    return "arm-vita-eabi-nm"


def symbols(elf: str):
    """Address-sorted (addresses, names, sizes) for the text symbols in `elf`."""
    nm = _nm()
    try:
        out = subprocess.run(
            [nm, "-n", "-S", "--defined-only", elf],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit(f"{nm} not found: export VITASDK=/path/to/vitasdk")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"{nm} failed on {elf}: {exc.stderr.strip()[:200]}")

    addrs, names, sizes = [], [], []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[2] not in "tTwW":
            continue
        try:
            addrs.append(int(parts[0], 16) & ~1)  # clear the Thumb bit
            sizes.append(int(parts[1], 16))
        except ValueError:
            continue
        names.append(parts[3])
    if not addrs:
        sys.exit(f"no text symbols in {elf} (pass the ELF, not the packed SELF)")
    return addrs, names, sizes


def read_profile(path: str, addrs, names, sizes) -> Counter:
    """Sample weights attributed to symbols, for one profile."""
    weights: Counter = Counter()
    seen = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) != 4:
                continue
            try:
                pc = int(parts[1], 16) & ~1
                weight = int(parts[3])
            except ValueError:
                continue
            seen += 1
            i = bisect.bisect_right(addrs, pc) - 1
            # A stub, a veneer's padding, or a system module: not our code.
            if i < 0 or pc >= addrs[i] + max(sizes[i], 2):
                continue
            weights[names[i]] += weight
    if seen == 0:
        print(
            f"warning: {path}: no '<thread> <pc> <lr> <weight>' lines",
            file=sys.stderr,
        )
    return weights


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Write a linker-script fragment ordering .text by CPU profile heat.",
    )
    ap.add_argument("out", help="linker-script fragment to write; pass it to the link as -Wl,-T,<out>")
    ap.add_argument(
        "specs",
        nargs="+",
        metavar="PROFILE:ELF",
        help="a profile and the ELF it was taken from",
    )
    ap.add_argument("--size-elf", metavar="ELF", help="report the hot set's coverage in this ELF")
    ap.add_argument(
        "--libs",
        metavar="NAMES",
        default=",".join(DEFAULT_LIBS),
        help="comma-separated static libraries placed whole after the hot set (default: %(default)s)",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=0,
        metavar="N",
        help="emit at most N functions (0 = all sampled)",
    )
    args = ap.parse_args(argv)

    total: Counter = Counter()
    for spec in args.specs:
        if ":" not in spec:
            ap.error(f"expected PROFILE:ELF, got {spec!r}")
        profile, elf = spec.rsplit(":", 1)
        if not os.path.exists(profile):
            ap.error(f"no such profile: {profile}")
        addrs, names, sizes = symbols(elf)
        weights = read_profile(profile, addrs, names, sizes)
        if not weights:
            print(f"warning: {profile}: nothing attributed, skipped", file=sys.stderr)
            continue
        profile_total = sum(weights.values()) or 1
        for name, weight in weights.items():
            total[name] += weight / profile_total  # normalise: one run, one vote
        print(f"{profile}: {len(weights)} functions", file=sys.stderr)

    if not total:
        ap.error("no profile attributed any samples; nothing to order")

    order = [name for name, _ in total.most_common() if "veneer" not in name]
    if args.top:
        order = order[: args.top]
    libs = [lib.strip() for lib in args.libs.split(",") if lib.strip()]

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(
            "/* Generated by vita-port/scripts/vita_hot_order.py -- do not edit by hand.\n"
            "   The functions a CPU profile sampled, hottest first, so the linker places them\n"
            "   contiguously at the start of .text and calls among them stay inside direct-branch\n"
            "   range. Link with -Wl,-T,<this file>. Regenerate after large changes: a stale order\n"
            "   is worse than none. */\n"
            "SECTIONS\n{\n"
            "  .text :\n  {\n"
        )
        for name in order:
            # .text.hot.<name> is where GCC puts a function its own PGO profile found hot.
            handle.write(f"    *(.text.{name} .text.hot.{name})\n")
        for lib in libs:
            # Libraries built without -ffunction-sections, or whose sampled parts are hand-written
            # assembly, have to go whole -- but immediately after the sampled set, not far away.
            handle.write(f"    *{lib}:*(.text .text.*)\n")
        handle.write("    *(.text .text.*)\n")
        handle.write("  }\n}\n")

    print(f"{args.out}: {len(order)} functions", file=sys.stderr)

    if args.size_elf:
        _, names, sizes = symbols(args.size_elf)
        size_of = dict(zip(names, sizes))
        hot_total = sum(total[name] for name in order) or 1
        cumulative_weight = cumulative_bytes = 0.0
        marks = [0.5, 0.9, 0.99, 1.0]
        for name in order:
            cumulative_weight += total[name]
            cumulative_bytes += size_of.get(name, 0)
            while marks and cumulative_weight / hot_total >= marks[0] - 1e-9:
                print(
                    f"{marks.pop(0) * 100:5.1f}% of the samples: {cumulative_bytes / 1024:8.0f} KB",
                    file=sys.stderr,
                )
        if cumulative_bytes > BRANCH_RANGE:
            print(
                "warning: hot set exceeds 16 MB; calls within it will still need veneers",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
