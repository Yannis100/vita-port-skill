# Port types, reference repositories and patterns

Use this to choose the route in step 1 and to find real code to copy. Decision order:

1. A port already exists (VitaDB, GitHub topics `vitasdk`, `psvita-homebrew`): fork it.
2. An engine already on the Vita can run the game's data.
3. Source exists in C/C++ and needs GL 2.x or lower: SDL2 or vitaGL.
4. An Android armeabi-v7a build exists: so-loader (advanced).
5. Otherwise reimplement the engine, or decline.
6. The original is in a non-portable language or closed source, but a C/C++ or platform-agnostic
   reimplementation of the same project exists elsewhere (`core`/`common` separated from UI, format
   translations, decomp trees) — fork that and write a Vita front-end; PKSM's `core/`+`common/`+`3ds/`
   split (with on-host `tests/`) is the model.

## Contents
1. Taxonomy
2. Open-source C/C++ with SDL2 or GL
3. Engine reimplementations
4. Decompilation / custom GXM backend (Halo CE example)
4b. Static recompilation (N64/PC/PS2/x86 → C, the newest proven route)
4c. Native recompile + vitaGL backend with a declared source platform: THUG
4d. Native recompile + custom ELF module loader (Source engine / HL2 on Vita)
5. Android `.so` loaders
6. Cross-platform API emulation (3DS→Vita pattern)
7. Interpreters and runners (and Java)
8. Closed-source PC games
9. Reference repositories
10. Release and legal conventions

## 1. Taxonomy

| Type | Feasibility | Effort |
|---|---|---|
| SDL2 2D / software | stock `sdl2` + SDL_Renderer on GXM | hours to days |
| SDL2 + OpenGL (open source) | vitaGL (direct, or `sdl2_vitagl`); no GL3 core / geometry / compute | days to weeks for Quake-class; months for modern GL |
| Engine reimplementation | check upstream Vita backends first | data-only packaging if a port exists; weeks for a new engine |
| Cross-platform API emulation (e.g. 3DS libctru→Vita) | reimplement source API on Vita → vitaGL; see mkwiita, `references/api-emulation.md` | weeks to months; requires shader translation |
| Decompilation / custom renderer | write a GXM device layer — or, when the decomp ships a C-level GX HLE, map it onto vitaGL (GL→GXM) instead (ACGC is the proof; section 4) | months; needs a CPU-profile loop |
| Static recompilation (run the original binary as C) | lift the original machine code (x86, MIPS, N64 RSP, ARM) to C ahead of time with a recompiler (N64Recomp, n64recomp, or a custom lifter), then supply GPU/audio/input backends; see section 4b | months; N64/PS1-class proven playable (Conker, BoI, GT2); PS2/PS3/Xbox research-grade |
| Android `.so` loader | needs ARMv7 lib + GLES1/2; not for arm64-only, Unity (`libunity.so`), libgdx/Java, FMOD Ex | weeks to months; reverse engineering |
| Interpreter / runner | reuse lpp-vita, YoYo loader, Homebrodot | low if the runner exists |
| Emulator or engine with a JIT | ARM dynarecs work with Vita executable memory (`runtime.md` section 4b); x86-only JIT backends fall back to the interpreter | depends on the core; PCSX_AwO, DaedalusX64, flycast-vita are models |
| Java / libGDX | TeaVM C backend + Vita libGDX backend (`java-teavm.md`, limits in its section 2); GL 2.0-class games only without a renderer rewrite | weeks to months; device tuning for memory |
| Closed-source commercial game | find an existing community port (patch-distributed, user supplies assets); Unity Mono has precedent (Hollow Knight Vita); else decline | highest if built from scratch; low if a port exists |

## 2. Open-source C/C++ with SDL2 or GL

Follow the workflow in `SKILL.md`. Typical shape (fheroes2, Quake II, Xash3D):
- A small `#ifdef __vita__` block or `psp2/` directory holds heap/stack/clock setup, input, audio and
  filesystem glue.
- Static link, `-pthread`, `-fsigned-char` where the code assumes signed char, NEON flags.
- The data directory is `ux0:data/<name>/`; the VPK contains only the executable and LiveArea files.
- For GL engines, shaders are precompiled GXP (Quake II, Hexen II, Xash3D) or compiled at runtime
  via vitaGL, with a shader cache.
- **Emulators / JIT hosts** (DaedalusX64): the port is a whole-system emulator with its own ARM
  dynarec. Compile with `-march=armv7-a -mtune=cortex-a9 -mfpu=neon -ffast-math` and keep hot
  emulator code free of calls (the whole source tree in `Source/DynaRec/CodeGeneratorARM.cpp` emits
  ARM directly). Run the emulator's RSP/RDP on the CPU; offload the presentation to vitaGL. A
  128 MB-mapped N64 game fits in a 256 MiB newlib heap with the VM's RDRAM + texture cache in
  CPU RAM (see `references/runtime.md` section 4 for sizes).

## 3. Engine reimplementations

ScummVM has an upstream backend (`backends/platform/sdl/psp2`; `./configure --host=psp2 && make
psp2vpk`, *exact steps unverified*). fheroes2 has upstream support (`Makefile.vita`). Other Vita
ports found: EasyRPG, Wolf4SDL/vitaWolfen, Chocolate Doom, prboom-plus, Quake 1/2/3, RTCW, Hexen II,
Xash3D, Shockolate, gemrb-vita. **Half-Life 2 is now real**: `Barabbo/source-engine` (GPL fork of
Valve's 2020-leaked Source Engine, built on nillerusr/source-engine) shipped `v0.1.0-beta`
(2026-10-12) — multicore stable, dynamic lights and soft shadow maps, playable start to finish,
user copies their own HL2 data; audio partial. Big lesson from the author: the Android build of
HL2 would not compile for Vita (3 months dead end); the win came from porting the **GPL Source
Engine source** instead.
Update (2026-10): the open, *buildable* HL2-on-Vita reference is
[`LargeVegetable/source-engine`](https://github.com/LargeVegetable/source-engine) (branch `vita`,
v0.1.0-beta) — a native recompile with a bespoke ELF so-loader (section 4d).
`Barabbo/source-engine` is a separate **closed-beta twin** that does NOT publish its engine source
("Source code stays private during beta testing"); treat it as news, not as code to copy. The base
PC engine is `nillerusr/source-engine` (note the spelling: **"nillerusr", two r's**).

The same "find the portable core, don't port the platform build" lesson applies to utilities, not just
engines: PKSM keeps its save logic in a platform-agnostic `core/` + shared `common/` with a thin `3ds/`
front-end and host-run tests — the structure to copy when the user's target is an app whose only shipped
build is Android/Java but a portable C++ core exists.

Also new: `WolffsRoom/godot4-vita` is an experimental Godot 4.8-dev7 to
Vita (see section on runners; skill previously said "Godot 4 not found" — now contradicted).
Users supply the original data files. Verified port status (re-checked 2026-10-15): **OpenMW IS
now on Vita** — `TheLostPantheon/openmw` (author "KingTorro", 87★, fork of OpenMW/openmw created
2026-02-14, pushed 2026-10-05) is a full vitaGL port with `vita`/`vita-port`/`vita-rebuild`
branches, a Vita layer (apps/openmw/vita, components/vita, cmake/VitaToolchain.cmake,
Dockerfile.vita, scripts/vita-deps). GameBrew page: gamebrew.org/wiki/OpenMW_Vita (v2.2, updated
2026-08-13); VitaDB id 1390. Runs Morrowind/Tribunal/Bloodmoon at claimed 20-30 FPS (\*not
on-device verified\*). Users copy their own Morrowind data. **DOSBox is also on Vita**, but as
Libretro cores (`dosbox-pure`, `dosbox-svn`) inside the `noword/Emu4VitaPlus` frontend (262★,
v0.81 shipped 2026-10-05; both upstream Makefiles have an official `vita` target, arm-vita-eabi;
DOSPure/DOSSVN also build as standalone apps) — there is still no repo literally named
`dosbox-vita`, and `futureg1rl/psp-windows` (DOSBox 0.71) only runs on Vita through the built-in
PSP emulator (`pspemu/PSP/GAME`), not natively. ECWolf and GZDoom: still no Vita port found.
OpenTTD-vita is an old fork (480x272, no sound or network).

## 4. Decompilation / custom GXM backend: Halo CE example

Repo: github.com/BirchWoodGod/halo-ce-vita (GPL-3.0). A decompilation of the Xbox build, recompiled
natively, with Direct3D 8 translated to GXM. Use as a model when no GL layer fits. Layout of
`port/vita/`:

| Dir | Role |
|---|---|
| `host/` | Vita side, built with VitaSDK GCC: start-up (`vita_main.c`), GXM (`vita_gxm.c`), input, movies (AvPlayer), sockets (sceNet), settings panel, CPU usage |
| `platform/` | built with the game's ABI (clang): the D3D device (`d3d8_gxm.c`), register-combiner and vertex-program → Cg translators, texture decoding |
| `include/` | the narrow boundary header between the two (`vita_host.h`, `vita_gxm.h`) |
| `null/` | a do-nothing GXM so the Linux build can measure CPU cost without hardware |
| `sce_sys/` | LiveArea images |

Patterns worth copying:
- **Two compilers, one boundary.** Game code is clang (to keep an MSVC-like ABI); Vita-facing code is
  VitaSDK GCC; a small header joins them. Built with Python + Ninja and the manual packaging chain
  (`vita-elf-create` → `vita-make-fself -s -c` → `vita-mksfoex` → `vita-pack-vpk`), with link flags
  `-Wl,-q,--defsym=__sce_headroom=0x1000 --gc-sections`.
- **Runtime setup**: `_newlib_heap_size_user = 48 MiB`, a 112 MiB `sceKernelAllocMemBlock`
  contiguous arena, a 16 MiB game thread pinned to a core, clocks 444/222/222/166, `ATTRIBUTE2=12`.
- **Shaders**: Cg compiled on device by SceShaccCg (`libshacccg.suprx`), cached as `.gxp` by hash in
  `ux0:data/<app>/shaders/` and validated with `sceGxmProgramCheck` on reload.
- **Alignment**: `-fmax-type-align=1` for the whole game by default; selectively aligned hot code
  after profiling, because unaligned access can fault on Vita.
- **Testability**: a Linux target with the Vita device over a null GXM; Vita3K for smoke tests (it
  hides some GPU problems: render targets, mip chains); `HALO_*` env switches read from `env.txt`
  for frame timing, GPU stats, screenshots; a heartbeat file to see if the game is still alive.
- **Settings overlay** (Select+Start) for resolution scale (default 75%), frame limit, detail level.
- **Assets**: user supplies the Xbox disc contents in `ux0:data/haloce-vita/`; the game shows the
  expected path and exits if the maps are missing; movies must be converted to MP4.
- **Honest README**: lists performance (20-30 fps), known issues, and "help wanted" items.
- **v1.1.0 (2026-10-14)**: `app0:shaders.pak` precompiled shader bank (`tools/vita_shader_pack.py`,
  gxm-null collect + Vita3K `HALO_SHADER_PRECOMPILE`, on-device Cg fallback), CapUnlocker 4th-core
  helpers, dynamic resolution + profiling presets, crossplay netversion 29, in-game signed update
  channel; `port/windows|android|linux` in-tree.

### Decomp with a C-level GX HLE mapped onto vitaGL: ACGC (Animal Crossing, GameCube)

Same "decomp + custom renderer" family as Halo CE, but the counter-proof of the mapping step: when the
decomp's renderer is a **C reimplementation of the GX call surface**, map it onto **vitaGL (GL→GXM)**
instead of a hand-written GXM device layer. Repo: `Brendonm17/ACGC-Vita-Port` (branch `vita`), the ac-decomp
C decomp (ACreTeam/ac-decomp, GAFE01_00 USA, Metrowerks) forked from the PC port (flyngmt/ACGC-PC-Port).
No static lift — the decomp recompiles natively; the Dolphin GX/OS/VI/PAD/CARD/DVD hardware sources are
excluded and `pc/src/pc_gx.c` reimplements 161 `GX*` functions whose GL output feeds a project-private
vitaGL fork. TEV state is 52 precompiled CG shaders + 1 uber shader, offline psp2cgc→GXP in a generated
3.4 MB header, selected by TEV key at runtime — no runtime GLSL compiler. Mature: 8 releases
(v0.1.0a 2026-04 → v0.5.0 2026-09 "Multiplayer Update"), 4-player online multiplayer, NES subsystem.
- **User-supplied disc image + CC0 decomp is a second accepted Nintendo-target distribution model**
  (GameCube here): the decomp is CC0, the PC port layer MIT, and the user supplies their own GC disc ISO at
  `ux0:data/AnimalCrossing/rom/` — the same user-dump model as mh3-wii.

## 4b. Static recompilation (the newest proven route)

As of late 2026 the community's most productive new route is **ahead-of-time static recompilation
of the original binary into C**, then recompiling that C for ARM. This is the same family as
N64Recomp / n64recomp, and it is distinct from the decompilation + hand-writing route in section 4
(Halo CE) and from so-loaders (section 5). It has produced **playable commercial ports on a real
Vita**, not research only:

Full deep-dive with technique details and a verified project table: `references/static-recomp.md`.

| Port | Source | Repo | Technique / status (retrieved 2026-10) |
|---|---|---|---|
| **Conker's Bad Fur Day** (N64, Rare) | US ROM, user-supplied | [HenryKun55/conker-vita](https://github.com/HenryKun55/conker-vita) | `N64Recomp` lift of CBFD-Recompiled → C, GXM renderer for N64 graphics, RSP audio microcode on CPU. v1.0.0 (2026-10-14): 30 fps, 16:9 (4:3 optional), 444 MHz, 6 languages, saves as N64 EEPROM in `ux0:data/conker/saves`, requires `libshacccg.suprx` + user's US ROM (SHA-1 checked at launch). |
| **The Binding of Isaac: Repentance** (PC, x86) | user's PC copy | [0xl0cal/repentogxm](https://github.com/0xl0cal/repentogxm) | Static recompilation of the PC x86 executable → C for ARM. v0.1.1-alpha (2026-09-07): menus 60 fps, rooms 55-59 fps, dense rooms 33-34 fps, native 960x544. No emulator, no game code in repo. |
| **Gran Turismo 2** (PS1, MIPS) | user's disc | [limeking614-dev/GT2-Vita](https://github.com/limeking614-dev/GT2-Vita) | GT2-DECOMP tree + Vita runtime boundaries; removes MIPS register-bound overlay loading, replaces memory-card access with save backend, GTE before full 3D. WIP (no playable build). |
| **TimeSplitters: Future Perfect** (PS2, MIPS/VU) | user's demo ISO | [ValdiaKun/TimeSplitters](https://github.com/ValdiaKun/TimeSplitters) | Native reimplementation: ISO9660 → P5CK readers, VIF/VU1 interpreter core capturing GIF packets, GS-space preview. Architecture validation only so far. |
| **PS2 on Vita (research)** | — | [mirou1611/AstraRecomp](https://github.com/mirou1611/AstraRecomp) | PC-assisted PS2 static recompilation + Vita "AstraRT" runtime; EE interpreter as correctness oracle. Experimental, no playable retail games. |
| **Vita-native static recompilation toolkit** | — | [sp00nznet/vitarecomp](https://github.com/sp00nznet/vitarecomp) | Reusable recompiler/runtime for recompiling *Vita* games to native C (not emulation; a "N64Recomp for Vita"). Companion ecosystem: `ps3recomp`, `psprecomp`. |
| **Xbox (original) recomp stubborn** | — | [Xita-Project/xita](https://github.com/Xita-Project/xita) | x86→C lift of XBEs with a Vita runtime; fed into Halo CE. Closed, code remains for study. |
| **Monster Hunter Tri** (Wii, PowerPC) | user's Wii dump | [Grarak/mh3-wii](https://github.com/Grarak/mh3-wii) | PowerPC → C++ static recomp (C#/.NET8 translator, `recomp.yml`), GX replaced by native C producers + frame-packet render thread, offline psp2cgc shader bank, clang-21+lld toolchain; full shipping engine port (VPK + launcher), active 2026-10 (v0.2.1, 2026-10-21). |

Repeated here because they contradict earlier "not found" notes: the skill previously said no
DOSBox, GZDoom, OpenMW or ECWolf ports were found. As of 2026-10-15 that is **no longer fully
true**: **OpenMW now exists on Vita** (`TheLostPantheon/openmw`, see section 3 note), and
**DOSBox runs on Vita** as Libretro cores bundled in `noword/Emu4VitaPlus` (frontend, not a
standalone `dosbox-vita` repo — no such repo exists). Still NOT found as of 2026-10-15: GZDoom
and ECWolf Vita ports. Half-Life 2 on Vita is also real: see section 3 note and
[`Barabbo/source-engine`](https://github.com/Barabbo/source-engine).

Why this route matters for triage: when a playable binary exists and the source is closed, static
recompilation is now the community's go-to before writing a from-scratch reimplementation, and it
is the only route that has shipped real commercial-game ports (Conker, BoI) without any source.
Memory budget and libshacccg remain the same constraints as other GXM routes.

### Reverse-engineering resources

Community-recommended tooling for binary analysis of closed-source targets (feeds the static-recomp route):
- Ghidra (NSA, open source): decompilation, function recovery, struct reconstruction for any lifted target.
- rea.tools: online RE suite (assemblers, disassemblers, encoders/decoders, hash tools) useful during asset and
  binary cooking.

## 4c. Native recompile + vitaGL backend with a declared source platform: THUG

Repo: thug-vita-port. A third family: the game's own 2003-era C++ recompiles natively for Vita and a
hand-written vitaGL backend replaces the original renderer — no decompilation (4), no static lift
(4b), no .so loader (5).

- **Source and data platforms are chosen separately and must be declared.** Source is the PC/DX9
  build (kisak-thug PC re-release, `__PLAT_WN32__` path); data is the Xbox USA ISO, declared via
  `HARDWARE_XBOX` in `p_config.cpp`, which drives hundreds of `Config::GetHardware()` switches.
  They behave correctly only because the choice is declared — but document it: it has side effects
  (e.g. music is not paused during save). Assets follow the data platform: `.prx` archives,
  `.tex.xbx` textures, Xbox ADPCM audio.
- **Transferable rule:** which original platform your assets/data come from defines a large fraction
  of port behaviour — make it a deliberate, documented baseline. This is the native-recompile
  analogue of the so-loader's Android `.so` mapping (section 5).
- **Subsystem stub discipline** (`p_link_stubs.S`): link-stubs written by hand in Thumb-2 assembly
  return neutral values; neutral zeroed singleton blocks are wired into the engine's singleton
  table. Careful: an inline `Instance()` reads the static pointer directly, so overriding only the
  setter changes nothing. Instrument stub-hit counting to see what is actually reached.

## 4d. Native recompile + custom ELF module loader: Source engine (HL2 on Vita)

Base engine: `nillerusr/source-engine` — a modified Source engine 2017 (based on the TF2 2018
leaked source; PC build is a Direct3D 9 material system (`materialsystem/shaderapidx9/`) plus
ToGL/ToGLES GL translation; targets Windows/Android/OSX/FreeBSD/Linux via waf; NO Vita support
upstream). Spelling: **`nillerusr`, two r's — NOT "nileusr"**.

Port: [`LargeVegetable/source-engine`](https://github.com/LargeVegetable/source-engine) (default
branch `vita`, tag `v0.1.0-beta`, asset `hl2_vita-0.1.0-beta.zip` ~20 MB with a published
SHA-256) is a **native recompile** to ARMv7 Cortex-A9 NEON via VitaSDK + vitaGL — like THUG
(section 4c) but with a bespoke ELF module loader: `launcher_vita/so_loader.cpp` ("Minimal ELF
shared object loader for PS Vita") maps PT_LOAD segments via kubridge
(`kuKernelMemReserve`/`kuKernelMemCommit` — the only user-space exec-mapping), resolves imports
and runs module ctors. This is a **third flavor** vs THUG (which had no ELF loader): a native
recompile of a D3D-era engine still needs the Vita homebrew kernel stack (kubridge,
libshacccg/vitaShaRK) the moment the engine loads modules dynamically.

- Build flags (`launcher_vita/build.sh`): `-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -mthumb
  -fno-short-enums`. Launcher links `-lvitaGL -lvitashark -lSceShaccCgExt -lmathneon -lSDL2
  -lkubridge`.
- Companion `vitaGL` fork: `LargeVegetable/vitaGL`, branch `hl2-vita` (error logging + the options
  the port needs).
- **Transferable rule: next-gen-console reference targets of a PC engine are ideal Vita
  optimization baselines.** The port deliberately adopts Xbox 360-era Source tuning (AI efficiency
  settings, alternate ticks, thread splits, lower LOD) instead of inventing new cuts.
- Separate competing fork: `Barabbo/source-engine` (own `psvita` branch, own v0.1.0-beta release
  credited "coded by Barabbo, Design by Lucky13x", its own `PLATFORM_PSVITA` macro) DOES NOT
  publish engine source — "Source code stays private during beta testing". Not a buildable
  reference; a closed-beta twin.

## 5. Android `.so` loaders

Used for closed-source Android games (GTA SA, Dead Space, Borderlands-class, bc2_vita). Pieces:
`so_util` (load the ARMv7 `.so`), imports resolved to native functions (GL/EGL → vitaGL),
FalsoJNI as a fake JVM, kubridge (`kuKernelCpuUnrestrictedMemcpy` to hook read-only `.text`, a
`USER_RX` block for trampolines, `kuKernelFlushCaches`; v0.3.1_hotfix also enables `SWP` for old ARM
code; versions and the weak-stub boot check in `runtime.md` section 4c), `_newlib_heap_size_user` + `ATTRIBUTE2=12`,
**everything softfp** (SDK, vitaGL `SOFTFP_ABI=1`, openal, mpg123). Wrap `malloc` with `vglMalloc`
for large allocations. Needs an `UNSAFE` eboot and plugins (kubridge, fd_fix), so documentation
for the end user is substantial. Bionic vs newlib struct layouts differ (`pthread_mutex_t`, `stat`,
`dirent`); wrap them. Start from `v-atamanenko/soloader-boilerplate` and `Rocroverss/vitasoguide`.
Candidate screening: `Rinnegatamante/Android2Vita-Candidate-Ports-List`. Hardware is effectively
required for testing. Treat this route as an expert path and say so.

## 6. Cross-Platform API Emulation: 3DS → Vita (mkwiita)

When the source game targets a different platform with a well-documented API (e.g., 3DS libctru/citro3d),
emulating that API on Vita enables near-zero changes to the original game code. The reference is
[mkwiita](https://github.com/boomannotjeff/mkwiita) — a port of MKW-3DS (1:1 Mario Kart Wii recreation) to Vita.

**Architecture:** The game code (C++) compiles unchanged. A platform layer reimplements the source platform's
API headers and maps them to VitaSDK + vitaGL:

| Source API | Vita Reimplementation | Role |
|---|---|---|
| libctru | `platform/vita/src/ctru_sys.cpp` | threads, sync, input, display, memory |
| citro3d | `platform/vita/src/ctru_gpu.cpp` | GPU state → vitaGL/GXM |
| PICA shaders | `platform/vita/src/ctru_shader.cpp` | dynamic GLSL generation from GPU state |
| NDSP audio | `platform/vita/src/ctru_ndsp.cpp` | software DSP emulator (24 voices) |
| Zeroed alloc | `platform/vita/src/zeroed_new.cpp` | `operator new` → zeroed `calloc` memory |

**Key patterns:**
- **Thread/priority mapping:** 3DS priorities `0x18..0x3F` on 2 cores → Vita `64..191` on 3 cores.
- **Lazy sync objects:** Kernel objects use lazy creation so zero-initialized objects are valid.
- **Shader cache:** Compiled GLSL programs saved as binaries to `ux0:data/<app>/shaders/`.
- **Software DSP:** PCM8/PCM16/ADPCM decoding, resampling, IIR low-pass, surround folding at 48 kHz.
- **Input mapping:** Follow Vita's button layout (A→Cross, B→Circle, X→Triangle, Y→Square), not the 3DS layout.
- **Quality tuning:** `ux0:data/<app>/quality.txt` for runtime settings; empty files for debug switches.

See `references/api-emulation.md` for the full technical reference.

## 7. Interpreters and runners (and Java)

`Rinnegatamante/lpp-vita` runs Lua scripts (LuaJIT 2.1). `yoyoloader_vita` runs GameMaker (Android
bytecode and YYC; PC YYC unsupported). Godot 3.x works via Homebrodot (GLES2, `.pck`). **Godot 4
now has a Vita port** — `WolffsRoom/godot4-vita` (experimental, Godot 4.8-dev7 compiled as a PIC
`libgodot.so` loaded by a small eboot; GXM-native canvas backend via libvita2d or a VitaGL
compatibility renderer with GLES3→Cg shader adaptation; reference game `DodgeTheCreeps-PSVita`;
2D-only, no general 3D or GPU particles, assets must be pre-imported on a host).
fake-08 plays Pico-8. LÖVE has no native Vita port (only LOVE-WrapLua, a 2D subset over
lpp-vita, and an unfinished `vita-love`). A port of such a game usually means porting the runner and
repackaging the game's scripts and data. **Unity** has no official public runtime, but a community
route exists for **Mono-scripted** games (see section 7); IL2CPP games have no known route.

**Java / libGDX** has no JVM on the Vita, but ahead-of-time translation works: STSPSVITA
(github.com/mmrmagno/stspsvita, MIT, pre-alpha) runs Slay the Spire by translating the jar to C with
TeaVM's C backend (STSPSVITA pins 0.15; 0.16 adds full reflection) and swapping in a vitaGL/SceCtrl/OpenAL libGDX backend. Full notes in
`references/java-teavm.md`, which also compares Clearwing VM (the Java-to-C++ transpiler behind the
SwitchGDX libGDX backend; GPL-2.0, no Vita target yet). Do not use an Android so-loader for libGDX games: the game logic is Dalvik
bytecode, not native code.

## 8. Closed-source commercial games

x86 emulation is not available. Static recompilation (section 4b) is nevertheless a real
closed-source route — Conker's Bad Fur Day (N64) and BoI: Repentance (x86 PC) both ship Vita ports
from a recompiled binary, with the user supplying the game data and the repo holding no game code.
So the options are: (a) an existing community port, (b) static recompilation of the user's binary,
(c) reimplement the runtime so it reads the user's own assets, or (d) decline. **Search for (a)
first, every time**; do not tell the user "nobody has ported this" without searching (VitaDB,
GitHub, GameBrew). Note the masterlist gap (section 8): there is no single authoritative port list,
so GitHub topic search (`vitasdk`, `psvita-homebrew`) plus Reddit r/vitahacks/r/vitapiracy release
threads are the practical discovery tools.

**Patch-distribution model (the legitimate pattern for closed-source ports).** The port ships only
code and binary diffs (xdelta/vcdiff), never commercial data. The user runs a patcher against their
own purchased copy, which produces the installable folder. Precedent: *Hollow Knight Vita*
(github.com/PatnosDD/Hollow-Knight-PsVita), a Unity game: `VitaPatchSteam.zip` / `VitaPatchGog.zip`
plus `APPLYPATCH.bat` turn the user's Steam or GOG copy into a ~380-450 MB `HollowKnightVITA.zip`,
installed to `ux0:app/HKVT12222/`. It needs the `ioplus.skprx` kernel plugin, a 500 MHz CPU
overclock, runs at up to 30 fps with long loads. *(Read from the repo page on 2026-10; the page does
not say how the Mono runtime is hosted, its licence, or the version, so check it before relying on it.)*
Supporting piece: **VitaMonoLoader** (GrapheneCt, MIT, v1.0 mid-2022), a Mono runtime for the Vita
that AOT-compiles managed C# to ARM; it uses Unity's PlayStation Vita support files and the
CapUnlocker plugin *(GameBrew page; which Unity versions it supports is not stated)*.

What this means in practice:
- Unity **Mono** games: a route exists but is expert-level, multi-month work and needs a console.
  Point users to an existing port when there is one; do not rebuild it. Say you have not tested it.
- **Java/libGDX** commercial games: a route exists (TeaVM, see `java-teavm.md`) but only as a *local
  build pipeline*: the user feeds in their own jar and builds the VPK themselves; the generated C is
  derived from the game, so never publish a VPK. STSPSVITA (Slay the Spire) is the precedent.
- Unity **IL2CPP**, x86-only native engines: no known route; decline and say why.
- Never put the game's data, or Sony modules, in a VPK. If you cannot find a port, offer a
  user-side alternative such as streaming (Moonlight/Steam Link-style clients exist for the Vita;
  check the current release) or a native Vita game of the same genre.

## 9. Reference repositories

| Repo | Shows |
|---|---|
| vitasdk/samples | CMake skeleton, `VITA_TITLEID`, `newlib_heapsize_ctrl`, `pretty_livearea`, `sdl2/redrectangle` |
| Rinnegatamante/vitaGL (`samples/`) | `vglInit*`, speed hacks, minimal Makefile |
| Rinnegatamante/vitaQuakeII | classic C engine: `psp2/sys_psp2.c` (heap, stack, clocks, net), `glimp_psp2.c`, `in_psp2.c` (touch, gyro), precompiled GXP |
| fgsfdsfgs/vitaXash3D | launcher + engine split, `ATTRIBUTE2`, vitaGL, touch buttons, data layout |
| Northfear/fheroes2-vita (upstream ihhub/fheroes2, `Makefile.vita`) | small `#ifdef __vita__` block on an SDL2 engine |
| TheOfficialFloW/gtasa_vita | canonical so-loader, softfp deps, exemplary end-user README |
| v-atamanenko/soloader-boilerplate | so-loader starter template, FalsoJNI, send/dump targets |
| Rinnegatamante/yoyoloader_vita, lpp-vita, Homebrodot/platform-vita | runners |
| BirchWoodGod/halo-ce-vita | custom GXM backend of a decompilation; v1.1.0: precompiled `app0:shaders.pak` shader bank, CapUnlocker 4th-core helpers, dynamic resolution + presets, crossplay netversion 29, in-tree `port/windows|android|linux` |
| thug-vita-port | **native recompile of a 2003-era C++ engine + hand-written vitaGL backend** with a declared source/data platform (`HARDWARE_XBOX` data from the Xbox USA ISO, PC source); one compat header, per-file `-O2`, three-port audio, active-low input, boot screen before `vglInit` |
| SwitchGDX/switch-gdx, SwitchGDX/clearwing-vm | libGDX backend + Java-to-C++ transpiler for Switch/UWP (GPL-2.0); the alternative AOT route, untested on Vita |
| mmrmagno/stspsvita | Java/libGDX via TeaVM C backend: classpath stubs, generated `GL20` bindings, runtime patches, local-build pipeline for a commercial jar |
| Hammerill/livearea-specs | LiveArea image specs |
| bythos14/kubridge (no licence file) | the maintained kubridge: memory protection, reserve/commit, exception handlers; release notes in `runtime.md` section 4c |
| Grarak/DSVita (GPL-3.0) | NDS emulator in Rust with a JIT: kubridge blocks at fixed addresses, `MemCommit` mirrors of one block, fastmem through an abort handler (`src/mmap/vita.rs`) |
| ScoobyDouche/VitaKotor (`loader/crash.c`) | crash logger on kubridge exception handlers that resolves PC/LR to module + offset |
| Rinnegatamante/PCSX_AwO (fork of notaz/pcsx_rearmed, 2026-10) | kubridge RWX JIT memory, sleep-then-spin frame pacing, PS TV multi-controller and rear-touch L2/R2, LiveArea `psgm:play` launch params, psp2cgc GXP embedded in the eboot, vitaGL on a render thread, SDL3 + imgui frontend |
| Rinnegatamante/DaedalusX64-vitaGL | **N64 emulator on vitaGL**: full ARM dynarec (Cortex-A9), NEON RDRAM hashing, `vglIndexPointerMapped`/`vglDrawObjects` (n64rot-era API), FF-renderer with framebuffer readbacks, Cg post-processing rewritten for USSE speed (2026-10-12), vgl-init with `scePowerSetArmClockFrequency(444)` |
| pyjabox/VitaKotor2 | **hardest-known Android so-loader**: KOTOR II native ARM libs + OBB, FMOD→`sceAudiodec`/`sceAudioOut`, Bink via embedded decoder, OpenSL shim, fake JNIEnv, GL worker on core 2, whole-process core pinning, bigalloc heap isolation, `-Wl,-z,max-page-size=0x10000`, `check_vitagl_build.sh` post-link check. v0.5.6, ~25 FPS on hardware |
| Rinnegatamante/flycast-vita | zero-copy vertex/index lists with `vglMalloc` + `vglBufferData`, 32-bit indices, Cg shaders via `GL_CG_*_SHADER_EXT` |
| Rinnegatamante/ldhewm3-rearmed | Doom 3 on vitaGL: NEON math, dormant entities behind portals, `r_maxLights`, frameskip; LTO tried and removed (crashes) |
| Rinnegatamante/fahrenheit-vita, vitaWolfen, vitaVoyager (2026-09-30 commits) | what breaks when an old port meets the current SDK (`toolchain.md` section 8) |
| HenryKun55/conker-vita | **N64 → Vita static recompilation** (N64Recomp/CBFD-Recompiled, GXM renderer, RSP audio on CPU); v1.0.0 shipped 2026-10-14, 30 fps, 6 languages |
| 0xl0cal/repentogxm | **PC x86 → Vita static recompilation** of BoI:Repentance; playable alpha with per-scene FPS + STATUS.md |
| limeking614-dev/GT2-Vita | PS1 → Vita porting of a decompilation tree (MIPS overlay removal, save-backend swap, GTE-first) |
| ValdiaKun/TimeSplitters | PS2 → Vita native reimplementation of a demo (ISO9660/P5CK/VIF/VU1 pipeline, GS-space preview) |
| sp00nznet/vitarecomp, ps3recomp, psprecomp | reusable static recompilers/runtime for recompiling Vita/PS3/PSP games to native C |
| mirou1611/AstraRecomp, Xita-Project/xita | PS2-on-Vita and Xbox-on-Vita static-recomp research/toolchains (xita now closed; feeds halo-ce-vita) |
| Grarak/mh3-wii | **Wii → Vita static recompilation**: PowerPC→C++ via C#/.NET8 translator (`recomp.yml`), GX → native C producers + frame-packet render thread, offline psp2cgc shader bank, clang-21+lld; full shipping engine port, active 2026-10 (v0.2.1, 2026-10-21) |
| Brendonm17/ACGC-Vita-Port | **GameCube decomp (ac-decomp, C) → Vita native recompile**: C GX-HLE (161 `GX*` in `pc/src/pc_gx.c`) on a project-private vitaGL fork, deferred double-buffered command queue (`vita_gx_cmdbuf.c`), 52 precompiled TEV shaders + uber (offline psp2cgc GXP header), 3-core split, NES via Nofrendo, 4-player online multiplayer; 8 releases, active 2026 |
| nillerusr/source-engine | base engine for the HL2 Vita port: modified Source 2017 (TF2 2018 leak), D3D9 material system + ToGLES translation, waf build, no Vita upstream |
| LargeVegetable/source-engine | **native recompile of the Source engine + bespoke ELF so-loader** (`launcher_vita/so_loader.cpp`, kubridge exec-mapping, section 4d); branch `vita`, v0.1.0-beta, `hl2_vita-0.1.0-beta.zip` ~20 MB with published SHA-256 |
| LargeVegetable/vitaGL (branch `hl2-vita`) | vitaGL fork used by the HL2 port: error logging + the options the port needs |
| Barabbo/source-engine | Half-Life 2 Vita — closed-beta twin (coded by Barabbo, design by Lucky13x): does NOT publish engine source ("stays private during beta testing"), own `PLATFORM_PSVITA` macro; not a buildable reference |
| WolffsRoom/godot4-vita | Godot 4.8-dev7 → Vita (libgodot.so PIC + Vita loader, GXM 2D backend or VitaGL compat renderer); reference game DodgeTheCreeps-PSVita |

Note: `hammerill/ps-vita-porter` is a prior agent-skill repo on this topic; several of its claims
were not supported (GZDoom/OpenMW/DOSBox on Vita, LÖVE as native, a 128 MB "hard wall"). Do not copy
from it without checking.

**Masterlists.** No single authoritative port list exists; the community keeps asking for one
(r/vitahacks posts 2019-02-09 "Homebrew/Port List", 2025-07-06 "Vita port list", 2026-10-12
"We Need a AIO Port List" — all requests, none a maintained answer). Treat any "AIO port list" you
find as community-sourced and re-verify each entry. The closest structured indexes remain
**VitaDB** (vita.nxbeta.com; the 2026-10 mirror `vitadb.rinnegatamante.it` is a JS SPA, so curl
harvesting is not practical) and Reddit r/vitahacks + r/vitapiracy release threads.

## 10. Release and legal conventions

- Port only open-source code, or code and assets the user owns. Never bundle copyrighted data,
  Sony modules (`libshacccg.suprx`), APKs or OBBs. GTA SA ships a VPK plus a `gamefiles.zip` of the
  author's own patches; fheroes2 and Xash3D have users supply `HEROES2.AGG` / the `valve` folder.
- Respect licences: Quake and Doom ports are GPL, vitaShaRK is LGPL-3.0, so-loaders are usually
  MIT. Credit VitaSDK, vitaGL, SDL and upstream authors. Optionally disclose AI involvement.
- README convention: "Setup Instructions (For End Users)" with the exact `ux0:data/<name>/` layout,
  required plugins and modules, where to get legal data; then "Build Instructions (For
  Developers)"; plus a changelog and known issues.
- Title ID: 9 characters `XXXXYYYYY`, unique. Examples: `QUAKE0002`, `HXEN00001`, `GTASA0000`,
  `FHOMM0002`, `XASH00001`; samples use `VSDK000nn`. Ship `.vpk` on GitHub Releases; list on VitaDB.

### Port release-readiness checklist (community feedback)

A port is "done" only when a reviewer can verify, on hardware:
- Main story/game path complete start-to-finish (not just the first levels); timed/end-game content reached.
- Saves: write, reload, and continue across sessions; no per-session-only progress.
- Performance holds in the worst authored scene (not just menus): state the FPS target and the measured floor.
- No crash or soft-lock on: pause/resume, returning to menu, video playback, and the longest load.
- Audio: all missing/placeholder tracks accounted for; disconnect events handled.
- Workarounds are listed and marked (quality.txt, shader-cache toggles, forced settings), not hidden.
- A documented test device/firmware (3.60/3.65/3.68) and the exact plugin set (kubridge, fd_fix, etc.).
If any item is knowingly unverified, ship a "known gaps" section rather than calling the release final.

## 5b. Android .so Loader Ports (deep dive)

### 6.1 Boilerplate
- **soloader-boilerplate**: https://github.com/v-atamanenko/soloader-boilerplate — production-ready starter kit
- **vitasoguide**: https://github.com/Rocroverss/vitasoguide — community guide with APK checker tool
- **Android2Vita-Candidate-Ports-List**: https://github.com/Rinnegatamante/Android2Vita-Candidate-Ports-List — portability criteria

### 6.2 Requirements
- **ABI**: ARMv7 (armeabi-v7a) — ARMv6 possible, ARMv8/arm64 NOT supported
- **Graphics**: GLES 1.x/2.x required; GLES 3+ possible but harder (needs translation)
- **Audio**: FMOD acceptable only as libfmod.so or libfmodstudio.so
- **Frameworks**: Unity (libunity.so) NOT supported; libGDX (libgdx.so) NOT supported
- **Runtime**: kubridge taihen plugin required on hardware (firmware 3.60+)

### 6.3 Portability Checklist
From Rinnegatamante's authoritative list:
- ✔️ ARMv6 or ARMv7 executable
- ✔️ OpenGL: GLES 1 or GLES 2
- ✔️ FMOD: No usage, libfmod.so, libfmodstudio.so
- 🔶 OpenGL: GLES 3+ (possible but harder)
- ❌ FMOD: libfmodevent.so, libfmodex.so
- ❌ ARMv8 executable only
- ❌ Kotlin only
- ❌ Unity games (libunity.so)
- ❌ Java games (libgdx.so)

### 6.4 Build Requirements
- **VitaSDK-softfp** (NOT stock VitaSDK) — Android requires soft-float ABI
- `NDK_PORT=ON` CMake flag for NDK apps
- `SHADER_FORMAT` selection: GLSL (default), CG, or GXP
- kubridge.skprx installed on target Vita via taihen

### 6.5 Key Patterns
- **Symbol resolution**: `dynlib.c` maps 1000+ Android imports to Vita SDK equivalents
- **Hooking**: `hook_addr()` for kuser helper patches, `SO_CONTINUE` for original calls
- **Fake JVM**: FalsoJNI stubs for JNI class/method/field lookups
- **Asset bridge**: `AAssetManager` → `DATA_PATH/assets/` path translation
- **Shader caching**: Compiled GLSL cached to `ux0:data/<app>/shaders/`
- **Controls**: Analog deadzones, touch scaling (1920×1080→960×544), button remapping

### 6.6 Reference Projects
| Game | Repo |
|------|------|
| Modern Combat 3 | https://github.com/v-atamanenko/mc3-vita |
| Geometry Dash | https://github.com/hatoving/gdash-vita |
| SoulCalibur | https://github.com/Rinnegatamante/soulcalibur_vita |
