# Static Recompilation Ports on PS Vita

## Overview

Static recompilation lifts an **original closed-source binary** to C ahead of time (N64Recomp-style), then
compiles that generated C for ARM Cortex-A9. This is a proven, shipped route for commercial games with **no
source code and no emulator**: the game logic runs natively on the Vita CPU, and only hardware (GPU/audio/input)
is reimplemented.

Distinct from decompilation (Halo CE pattern) and from Android .so loaders: the source is the original
machine code, not a target platform's documentable API.

## Reference Projects (verified 2026-10)

| Project | Source | Technique | Status |
|---------|--------|-----------|--------|
| Conker's Bad Fur Day | N64 (`CBFD-Recompiled`) | N64Recomp lift → C; GXM renderer; RSP audio microcode on CPU | Playable v1.0.0, 30 fps 16:9, needs user US ROM (SHA-1 checked at boot) + `libshacccg.suprx` |
| The Binding of Isaac: Repentance | PC x86 | x86 → C static recompilation | Playable v0.1.1-alpha, 960x544, user's PC copy |
| Gran Turismo 2 | PS1/MIPS | Decomp tree; removes register-bound overlay loading; memory-card → save-backend swap; GTE-first bring-up | WIP |
| TimeSplitters: Future Perfect | PS2 | ISO9660→P5CK readers; VIF/VU1 interpreter capturing GIF packets; GS-space preview | WIP (architecture validation) |
| AstraRecomp | PS2 | PS2 static recomp framework; PC-assisted lift + Vita runtime; MIPS/EE interpreter as correctness oracle | Research/experimental |
| vitarecomp + ps3recomp + psprecomp | Vita/PS3/PSP | Recompile *console* games → native C ("N64Recomp for Vita"); HLE `sceKernel*`/`sceGxm*` by published NID map | Toolkit |
| Xita (xbox) | Xbox x86 | x86 → C with Vita runtime | Closed, fed into Halo CE |
| SMG Petari | Super Mario Galaxy (Wii) | Decompilation runtime | WIP, 10-20 fps |
| VitaKart64 / sm64ds-remastered-vita | Mario Kart 64 / SM64DS | Decompilation runtimes | Playable |
| MH3rd-HD | Monster Hunter 3rd HD | Recompiled | 60 fps |
| Monster Hunter Tri (Wii) | PowerPC (`sys/main.dol`, relocatables) | Static recomp: C#/.NET8 translator (`recomp.yml`), GX replaced by native C producers + frame-packet render thread, offline psp2cgc shader bank, clang-21+lld toolchain | Full shipping engine port (VPK + launcher), active 2026-10 |

## Technique Details

### N64Recomp Lift Mechanics

1. Use N64Recomp or a game-specific recompiled version (e.g. `CBFD-Recompiled`) to lift N64 MIPS binary → C
2. The generated C is compiled with the Vita toolchain (see toolchain.md; stock VitaSDK is fine, no softfp needed)
3. Hardware layers are written from scratch:
   - **GPU**: N64 fixed-function rendering → GXM renderer
   - **Audio**: RSP audio microcode run on the CPU (no RSP hardware)
   - **Input/display**: native Vita pad + 960x544
4. End-user contract mirrors the ecosystem norm: user supplies their own ROM/data file, checked by SHA-1 at boot

### x86 Lift (Binding of Isaac: Repentance — `repentogxm`)

- Lifts the PC x86 binary to C ahead of time
- Output is native ARM; menus 60 fps, gameplay ~55 fps
- Native 960x544; user supplies their own PC copy (legal model: no redistributed assets)

### MIPS Overlay Removal (GT2-Vita)

- PS1 games used register-bound overlay loading; the port removes overlay swapping entirely
- Memory-card save backend replaced with Vita save backend
- Bring-up order: GTE (geometry) first, then the rest

### PS2 VIF/VU1 Path (TimeSplitters)

- ISO9660 → P5CK readers replace PS2 disc access
- A VIF/VU1 **interpreter** captures GIF packets (geometry uploads)
- GS-space preview validates the pipeline before full rendering

### Wii → Vita static recompilation (mh3-wii)

`Grarak/mh3-wii` is the reference for porting a Wii game by static recompilation:
- **Translate**: PowerPC from `main.dol` + relocatable modules → C++ ahead of time (C#/.NET 8
  translator driven by `recomp.yml`: function map, entry points, `no_return_functions`, hook sites,
  `hardware_access.inc` / `alias_access.inc` slow-path marking). Flat guest memory spans MEM1/MEM2 as
  one reserved backing block.
- **Replace GX, do not emulate it**: every GX caller is ported to native C producers that record
  typed frame packets; a separate render thread draws them. Any unported GX path panics loudly
  (the 201 GX natives route to `PanicLegacyGx`) so gaps surface instead of failing silently.
- **Shaders offline**: 4,211 vertex + 658 fragment stages precompiled with Sony `psp2cgc.exe`
  (under Wine/Docker) at build time, packed (~2.1 MB), embedded — the release build has no runtime
  shader compiler.
- **Toolchain**: clang-21 + lld for the translated C++ (VitaSDK provides only sysroot/libs/packaging
  via `cmake/toolchains/vita-clang.cmake` adapted from Azahar); `--pic-veneer` linker flag needed
  for the large clang/lld code; ThinLTO + PGO for release.
- **Sizing**: ~1,650 hot functions ported to native C; kernels kubridge 0.3.1+ and CapUnlocker
  (4th core) required; CDRAM ~ 3×3.5 MiB frame slots + 16 MiB converted models + ~47 MiB textures.
- **Order that works** (from the repo docs): recompile + boot on desktop → replace GX family by
  family with native producers → convert assets at load → Vita platform + precompiled shaders →
  profile, port hot functions, move work off the game thread → cut GPU time → ThinLTO+PGO release.

### PS2 → handheld static recomp discipline (universal-ps2-recompiler)

`SandstoneDev/universal-ps2-recompiler` (a PS2→PSP agent kit around the PS2RC static recompiler)
documents transferable discipline for any console→Vita recomp:
- Host-first pipeline: get the main loop running on a PC host build before touching the handheld.
- Replace the renderer at its lowest stable software boundary (the device-driver layer), keeping
  the engine's render logic translated.
- R5900 (PS2) FPU is not IEEE: clamp operands, round toward zero, no fused multiply-add.
- Whole-program width/liveness analysis to a fixpoint; recover function discovery and jump tables
  backwards from `jr`.
- A/B against a reference emulator run for divergence, with honest device numbers — the kit's own
  published floor is ~30 fps indoors / 17-21 fps outdoors on a PSP-3000 at 333 MHz.

## When to Use

Use static recompilation when:
- The game is closed-source with no usable engine source
- A recomp/blob exists (check N64Recomp ecosystem; search "game name + recomp" or "game name + decomp")
- The original runs on N64, PS1, PS2, x86 PC, or other Console with an established lift toolchain
- Note: lift of the *original binary* to C is legal to build only when the user's own assets are used;
  the generated code reimplements the game, it does not redistribute assets (same legal model as the rest of the skill)

## References

- N64Recomp: https://github.com/N64Recomp/N64Recomp
- Conker Vita: https://github.com/HenryKun55/conker-vita
- Binding of Isaac recomp (repentogxm): https://github.com/0xl0cal/repentogxm
- GT2-Vita: https://github.com/limeking614-dev/GT2-Vita
- TimeSplitters: https://github.com/ValdiaKun/TimeSplitters
- AstraRecomp: https://github.com/mirou1611/AstraRecomp
- vitarecomp: https://github.com/sp00nznet/vitarecomp
- Xita (Xbox): https://github.com/Xita-Project/xita
- SMG decomp: https://github.com/SMGCommunity/Petari
