# Runtime configuration: memory, threads, files, input, audio

Hardware facts and budgets were gathered from vita-headers, newlib, vitasdk samples, shipped ports
and community docs in 2026-10. The Henkaku wiki was not readable (bot challenge), so wiki-derived
numbers are tagged *(wiki, unverified)*. Anything tagged *(unverified)* needs a test on a console.

## Contents
1. Hardware summary
2. Memory budget and the memory flags
3. The settings every port should export
4. Memory blocks and GPU memory (4b: JIT memory, 4c: kubridge)
5. Threads and CPU cores (5a: priority/core affinity mapping)
6. Clocks and frame pacing
7. Files and paths, savedata
8. Input mapping
9. Audio, network, system dialogs
10. 32-bit and portability audit

## 1. Hardware summary

- CPU: quad-core ARM Cortex-A9 (ARMv7-A, NEON), little-endian. **Games get 3 cores**; the 4th is
  reserved for system tasks (about 10-15% load during games).
- GPU: PowerVR SGX543MP4+, tile-based, reached through SceGxm (32x32 tiles).
- RAM: 512 MB main + 128 MB CDRAM (video memory). Per-app budget below.
- Screen: 960x544, 60 Hz. Display pitch must be a multiple of 64 pixels. SDL2 can use 720p/1080i
  output via `VITA_RESOLUTION`; vitaGL has `vglSwapResolution`.
- Input: D-pad, face buttons, L/R, Start/Select, two analog sticks, front multitouch, rear touch,
  gyro + accelerometer. **No L2/R2/L3/R3** on the handheld (PS TV with a DS3/DS4 has them).
- Audio: stereo, main port 48 kHz S16, grain 64..65472 frames.

## 2. Memory budget and the memory flags

Default app budget (Rust-on-Vita book, consistent with ports): about **256 MiB MAIN, 112 MiB CDRAM,
26 MiB PHYCONT, ~8 MiB CDIALOG**. The bits of `ATTRIBUTE2` in `param.sfo` enlarge MAIN (verified in
`vita-mksfoex.c`):

| `ATTRIBUTE2` | Name | Extra MAIN | Total MAIN |
|---|---|---|---|
| `0x4` | MEM29 | +29 MiB | 285 MiB |
| `0x8` | MEM77 | +77 MiB | 333 MiB |
| `0xC` (=12) | MEM109 | +109 MiB | **365 MiB** |

Set it with `vita-mksfoex -d ATTRIBUTE2=12` or `VITA_MKSFOEX_FLAGS`. The value is read at install
time, so reinstall the VPK after changing it. Whether the bit requires an `UNSAFE` eboot is
*(unverified)*; shipped ports (Halo CE, gtasa, bc2_vita, Xash3D) combine them, so test both ways.

Do not assume a bigger figure. A 128 MB "VRAM wall" and a "350 MB" free pool both appear in
unreliable summaries; plan against 256 or 365 MiB MAIN and 112 MiB CDRAM.

Everything in MAIN counts: the newlib heap, thread stacks, the SceLibc heap, vitaGL's RAM pool, and
any `sceKernelAllocMemBlock` arenas. Budget them as a sum.

| Port | Newlib heap | Other |
|---|---|---|
| Quake II | 192 MiB | 16 MB vitaGL threshold, 8 MiB main stack |
| GTA SA loader | 192 MiB | 2 MiB sceLibc, 16 MB threshold |
| bc2_vita | 192 MiB | 8 MiB threshold, `ATTRIBUTE2=12` |
| Halo CE | 48 MiB heap + 112 MiB arena memblock | 16 MiB game-thread stack |

## 3. The settings every port should export

Define these as globals in the program (see `assets/vita_runtime.c`). Missing ones silently use
defaults that are too small for most ports.

```c
unsigned int _newlib_heap_size_user = 192 * 1024 * 1024;  // malloc backing, default 128 MiB
unsigned int sceLibcHeapSize = 4 * 1024 * 1024;           // Sony libc heap, used by Sony libs
const unsigned int sceUserMainThreadStackSize = 8 * 1024 * 1024;  // default is not documented
const int sceUserMainThreadPriority = 0x60;               // see Threads
```

- `_newlib_heap_size_user`: newlib `malloc` takes **one memblock of this size at startup**. If that
  allocation fails, `_init_vita_heap` silently sets base=0 and every `malloc` fails with ENOMEM.
  A game that "crashes on boot with no log" often has a heap larger than free MAIN. `sbrk`
  returns ENOMEM past the limit.
- GPU memory (GXM, vitaGL) is **outside** the newlib heap, but vitaGL's RAM pool is taken from
  whatever user memory is free at init, so size the heap first and let vitaGL have the rest
  (see `references/vitagl.md`).
- `sceLibcHeapSize` belongs to Sony's libc, not the newlib `malloc` path.
- The default main-thread stack size is *(unverified)* and small. Deep recursion or big stack arrays
  crash with no message. Either set `sceUserMainThreadStackSize` or run the game on its own thread
  with a big stack (Halo CE runs the game on a 16 MiB thread because the AI search overflowed the
  main stack).

## 4. Memory blocks and GPU memory

`sceKernelAllocMemBlock(name, type, size, NULL)` then `sceKernelGetMemBlockBase`. Sizes round up to
256 KiB (0x40000). Types (`vita-headers psp2common/kernel/sysmem.h`):

| Type | Value | Use |
|---|---|---|
| `SCE_KERNEL_MEMBLOCK_TYPE_USER_RW` (= USER_MAIN_RW) | 0x0C20D060 | big CPU arenas |
| `..._USER_RW_UNCACHE` | 0x0C208060 | GXM USSE memory, DMA-visible buffers |
| `..._USER_CDRAM_RW` | 0x09408060 | textures, render targets, display buffers |
| `..._USER_MAIN_PHYCONT_(NC_)RW` | 0x0C80D060 / 0x0D808060 | physically contiguous |
| `..._USER_MAIN_CDIALOG_RW` | 0x0CA0D060 | dialog memory |

Free memory can be read with `sceKernelGetFreeMemorySize`. Halo CE allocates one large
`USER_RW` arena up front and sub-allocates from it, which avoids heap fragmentation.

GXM defaults (gxm.h): parameter buffer 16 MiB, VDM ring 128 KiB, vertex ring 2 MiB, fragment ring
512 KiB. Alignment: colour surface 4, texture 16, depth/stencil 16, palette 64. Max 16 vertex
attributes, 16 texture units. `SCE_GXM_INITIALIZE_FLAG_PB_LPDDR` puts the parameter buffer in main
RAM to save CDRAM.

### 4b. Executable memory (JIT and dynarecs)

An ARM JIT is possible; emulators with ARM dynarecs (pcsx_rearmed, PCSX_AwO, flycast-vita,
DaedalusX64, DSVita) ship on the Vita. What is not possible is running x86 code, so a JIT that only
emits x86/x64 must use its interpreter or gain an ARMv7 backend. Two routes, read in source
(pcsx_rearmed `libpcsxcore/new_dynarec/new_dynarec.c`). Both compile, link and pass
`vita-elf-create` on VitaSDK 2026.08 (2026-10-14; kubridge needs `-lkubridge_stub` or
`-lkubridge_stub_weak`, the stock calls need no extra stub), but were never run on a console:

| Route | Allocate | Write vs execute | Before running new code | Needs |
|---|---|---|---|---|
| Stock (upstream pcsx_rearmed) | `sceKernelAllocMemBlockForVM(name, size)` | `sceKernelOpenVMDomain()` to write, `sceKernelCloseVMDomain()` to execute | `sceKernelSyncVMDomain(block, ptr, len)` | nothing extra; works on any firmware |
| kubridge (PCSX_AwO, 2026-10) | `kuKernelAllocMemBlock(name, SCE_KERNEL_MEMBLOCK_TYPE_USER_RW, size, &opt)` then `kuKernelMemProtect(base, size, READ\|WRITE\|EXEC)` (RWX), or toggle `READ\|WRITE` / `READ\|EXEC` per page range | per-range `kuKernelMemProtect` (no global domain switch) | `kuKernelFlushCaches(ptr, len)` | kubridge **v0.2 or later** (bythos14), and firmware 3.60 or 3.65 for `MemProtect` (section 4c) |

- The VM-domain calls switch write access for every `ForVM` block at once, which is why PCSX_AwO
  moved to kubridge. The size limit of `sceKernelAllocMemBlockForVM` is *(unverified)*; check it
  with your code-cache size on hardware.
- `opt.size = sizeof(opt)` must be set on `SceKernelAllocMemBlockKernelOpt`; round the size up to
  1 MiB as PCSX_AwO does (`(size + 0xfffff) & ~0xfffff`).
- `kuKernelMemProtect` needs an address of at least `0x40000000`, aligned to 4 KiB (the length is
  rounded up to 4 KiB), and a memblock whose paging type kubridge supports; otherwise it returns
  `SCE_KERNEL_ERROR_INVALID_ARGUMENT` or `SCE_KERNEL_ERROR_SYSMEM_MEMBLOCK_ERROR`. Check the return
  and fall back to the stock route or the interpreter.
- PCSX_AwO calls kubridge from a safe (`-s`) eboot; `UNSAFE` is not required for these calls
  *(read in its Makefile, not run)*.

### 4c. kubridge: versions, firmware limits, other calls

kubridge (`kubridge.skprx`, a taiHEN kernel plugin under `*KERNEL`) exposes kernel memory and
exception features to user code. Read at `bythos14/kubridge` `417ddde` (2026-05-31; no licence
file). The VitaSDK `kubridge` package installs its header plus `libkubridge_stub.a` and
`libkubridge_stub_weak.a`.

| Release | Adds |
|---|---|
| v0.1 (TheOfficialFloW, 2021-01; that repo's only release) | `kuKernelAllocMemBlock`, `kuKernelFlushCaches`, `kuKernelCpuUnrestrictedMemcpy` |
| v0.2 (bythos14, 2022-08) | `kuKernelMemProtect`, `MemReserve`/`MemCommit`/`MemDecommit`, abort handler |
| v0.3 (2022-10) | `kuKernelRegisterExceptionHandler` / `Release...` (abort-handler API now deprecated) |
| v0.3.1, v0.3.1_hotfix (2024-02/03) | `kuPowerGet/SetSysClockFrequency`; enables the old ARM `SWP` instruction on all cores; deadlock fix |

- **Name the version in the README.** Older so-loader READMEs link TheOfficialFloW's v0.1, which
  lacks everything after the first row. A port that calls `kuKernelMemProtect` or the exception
  handlers needs bythos14's v0.3.1_hotfix (or at least the release in the table).
- **Firmware limit.** `MemProtect`, `MemReserve`/`Commit`/`Decommit` and the RWX page-table patch
  use hard-coded SceSysmem offsets for **3.60 and 3.65 only**. On any other firmware kubridge logs
  "Offsets are unknown for this firmware. Crashes may occur" and uses the 3.65 offsets; whether
  those match 3.67-3.74 is *(unverified)*. `AllocMemBlock`, `FlushCaches`, `CpuUnrestrictedMemcpy`
  and the exception handlers resolve by NID and do not have this limit. State the supported
  firmware in the README of anything built on `MemProtect`.
- **Start without the plugin, then say what is missing.** Link `-lkubridge_stub_weak`, then check at
  boot, as yoyoloader does (it prints "kubridge.skprx is not installed" instead of crashing):

  ```c
  #include <psp2/vshbridge.h>          /* link -lSceVshBridge_stub */
  int search_unk[2] = {0, 0};
  if (_vshKernelSearchModuleByName("kubridge", search_unk) < 0) { /* show error, exit */ }
  ```

  With the weak stub, an import the installed kubridge does not export stays unresolved. SceLibcPosix
  detects that by checking that the stub's third word no longer holds the function NID
  (`src/internal/vitamman.c`). Use that check, or a version note in the README, before calling
  v0.2+ functions. The weak and strong stubs both built here, with the check above, on 2026-10-14.
- **Fixed virtual address**: set `opt.attr = 0x1` (HAS_VBASE) and `opt.field_C = vaddr` on
  `kuKernelAllocMemBlock`. DSVita puts its JIT block at `0x98000000` and guest memory at chosen
  addresses this way.
- **Reserve, then commit on demand**: `kuKernelMemReserve(&addr, size, type)` takes address space
  without physical pages; `kuKernelMemCommit(addr, len, prot, opt)` backs part of it, and
  `kuKernelMemDecommit` releases it. With `KU_KERNEL_MEM_COMMIT_ATTR_HAS_BASE` plus
  `baseBlock`/`baseOffset`, a commit maps another block's pages, giving mirrored views of one memory
  (DSVita uses this for emulated memory mirrors).
- **so-loader patching**: `kuKernelCpuUnrestrictedMemcpy` writes into read-only `.text` (hooks),
  `kuKernelAllocMemBlock` with `SCE_KERNEL_MEMBLOCK_TYPE_USER_RX` (`0x0C20D050`, not in the user
  headers; so-loaders define it) holds trampolines, and `kuKernelFlushCaches` must follow every
  code write. Old ARM `.so` files that use `SWP` atomics need kubridge v0.3.1+.
- **Crash capture**: exception handlers give a register dump without a core dump; see
  `references/debugging.md`.
- **POSIX `mmap`/`mprotect`**: SonicMastr/SceLibcPosix (2026-10, a C runtime built on SceLibc instead
  of newlib, no licence file) implements them on kubridge with a `ForVM` fallback. Read it for the
  design. Without a licence, do not copy its code.

## 5. Threads and CPU cores

- User core masks: `SCE_KERNEL_CPU_MASK_USER_0/1/2` = `0x10000 / 0x20000 / 0x40000`,
  `_ALL` = `0x70000`, system core `0x80000` (confirmed in Halo CE's `vita_main.c`).
- `sceKernelCreateThread(name, entry, priority, stackSize, attr, cpuAffinityMask, opt)`. Mask 0
  inherits from the caller. Lower number = higher priority; user range about 64..191, default
  `0x10000100`; ports use 64..127 for game threads.
- Pin the render/game-critical thread to one core and workers to others. Halo CE found its render
  thread on core 0 was the limit.
- pthreads work (pthread-embedded, full API incl. mutex, cond, rwlock, sem, barrier, TLS) when
  linked with `-pthread`. Set stack sizes explicitly (`pthread_attr_setstacksize`, at least 128 KB;
  larger for engines). The per-thread reent table has 256 slots.
- `fork`/`exec` return ENOSYS. There is no desktop-style `mmap`; anonymous mappings with
  `mprotect` can be built on kubridge reserve/commit/protect (section 4c).

### 5a. Priority and Core Affinity Mapping (Cross-Platform Pattern)

When porting a game from another platform (e.g., 3DS with priorities `0x18..0x3F` on 2 cores),
map to Vita's 3 cores and priority range `64..191`. Reference: [mkwiita](https://github.com/boomannotjeff/mkwiita).

```cpp
// 3DS prio 0x18..0x3F → Vita priority around 160 (64 highest .. 191 lowest)
static int vitaPriority(int prio) {
    int p = 160 + (prio - 0x30) * 2;
    return p < 64 ? 64 : p > 191 ? 191 : p;
}

// Core affinity: audio on core 2, render/job on core 1, main on core 0
static int vitaAffinity(int prio, int core) {
    if (core < 0) return 0;
    if (prio <= 0x19 || core == 3) return SCE_KERNEL_CPU_MASK_USER_2;
    return core == 0 ? SCE_KERNEL_CPU_MASK_USER_0 : SCE_KERNEL_CPU_MASK_USER_1;
}
```

Key considerations:
- The Vita has 3 user cores (the 4th is reserved for system tasks); the 3DS has 2 application cores.
- Lower priority number = higher priority on Vita. Map the source platform's higher-priority threads
  to lower Vita priority numbers.
- Pin audio/render threads to dedicated cores for consistent frame pacing.
- Thread creation uses `sceKernelCreateThread` with `cpuAffinityMask` set to the result of `vitaAffinity()`.

## 6. Clocks and frame pacing

The common port setting, used by Halo CE, Quake II, GTA SA, fheroes2 and others:

```c
scePowerSetArmClockFrequency(444);
scePowerSetBusClockFrequency(222);
scePowerSetGpuClockFrequency(222);
scePowerSetGpuXbarClockFrequency(166);
```

Allowed values *(wiki / PSVshell docs, unverified)*: ARM 41 83 111 166 222 333 444 500; GPU 41 55 83
111 166 222; bus 55 83 111 166 222; XBAR 83 111 166. Default ARM 333 MHz. 500 MHz may need a kernel
plugin such as PSVshell, and whether a safe eboot may call these is *(unverified)*: test it, and
fall back gracefully if the calls fail. Higher clocks cost battery; expose a setting if the game
runs well without them.

**Frame pacing** for a game or emulator whose rate is not exactly the 60 Hz vblank (50 Hz PAL, 30 fps
caps): `sceKernelDelayThread` alone overshoots, and a pure busy-wait burns a core. PCSX_AwO
(2026-10) sleeps for most of the wait, then spins on the microsecond clock:

```c
static void pace(SceUInt64 *deadline, SceUInt64 interval_us) {
  SceUInt64 now = sceKernelGetSystemTimeWide();
  if (!*deadline || now > *deadline + interval_us || *deadline > now + 2 * interval_us)
    *deadline = now;                              /* resync after a stall or a pause */
  while (now < *deadline) {
    SceUInt64 left = *deadline - now;
    if (left > 700) sceKernelDelayThread(left - 500 > 4000 ? 4000 : left - 500);
    now = sceKernelGetSystemTimeWide();
  }
  *deadline += interval_us;
}
```

Build-verified with the multi-controller and launch-parameter code below (VitaSDK 2026.08, not run).
PCSX_AwO calls it once per emulated frame, before `retro_run()`, with the interval taken from the
core's fps. Its software presenter also waits for vblank, so 50 Hz content still meets a 60 Hz
display (it ships a separate frame-interpolation option). The thresholds are PCSX_AwO's, read in
source and not measured here.

## 7. Files and paths, savedata

- `app0:` is the read-only installed bundle and the default cwd. Write only to
  `ux0:data/<appname>/` (create directories with `mkdir`/`sceIoMkdir`). Some ports also probe
  `uma0:` for SD2Vita. `fopen("ux0:data/x/y.txt", ...)` works.
- Let users keep large assets outside the VPK in `ux0:data/<appname>/`; check at start and show an
  on-screen message with the expected path, then exit cleanly (Halo CE does this).
- Official savedata slots need `sceAppUtilInit` and the `sceAppUtilSaveData*` calls; plain files in
  `ux0:data` are the simpler route for homebrew.
- Mind free space: caching decompressed data can need gigabytes. Document it.
- `sceAppUtilSystemParamGetInt` returns the enter-button assignment (Cross vs Circle by region).
- **Launch parameters** (LiveArea custom bubbles, `psgm:play` URIs): call
  `sceAppMgrGetAppParam(buf)` (1024-byte buffer) at start when `argv` has no path. A bubble launch
  arrives as `psgm:play?titleid=...&param=<URL-encoded path>`. Find `&param=`, stop at the next `&`,
  decode `%XX` and `+`, then `sceIoGetstat` the result before using it (PCSX_AwO
  `frontend/vita/livearea_launch.c` boots a game directly this way).

## 8. Input mapping

- `sceCtrlSetSamplingMode(SCE_CTRL_MODE_ANALOG_WIDE)` (and `sceCtrlSetSamplingModeExt` for the
  `Ext` readers); read with `sceCtrlPeekBufferPositive`, or `sceCtrlPeekBufferPositiveExt2`, which
  also reports L2/R2/L3/R3 from external pads.
- **Several controllers** (PS TV, or a handheld with paired pads via MiniVitaTV): check
  `sceCtrlIsMultiControllerSupported() > 0`, then `sceCtrlGetControllerPortInfo(&info)`. Port 0 is
  the built-in pad (`SCE_CTRL_TYPE_PHY`), ports 1..4 are paired pads; skip
  `SCE_CTRL_TYPE_UNPAIRED` and read each with `sceCtrlPeekBufferPositiveExt2(port, ...)`. Treat a
  pad whose `buttons` has `SCE_CTRL_INTERCEPTED` (system overlay open) as neutral (sticks at 128).
  Pattern from PCSX_AwO `frontend/vita/standalone.c`.
- L2/R2/L3/R3 do not exist physically. Common mappings: L2/R2 to the rear pad (or front corners),
  L3/R3 to front-touch zones or D-pad (Halo CE maps D-pad down/up to stick clicks). Offer a
  remap or an on-screen touch overlay. PCSX_AwO's rear L2/R2 zones use only the upper half of the
  rear panel, and rear X grows toward the left as seen from the screen, so mirror it. It skips the
  rear pad when port 0 is not the built-in pad (PS TV).
- Touch: `sceTouchSetSamplingState(port, START)` first; `SCE_TOUCH_PORT_FRONT=0`, `BACK=1`; read
  ranges from `sceTouchGetPanelInfo` (approximately 1920x1088 front and 1920x890 back, *unverified*).
- Motion: `sceMotion*`. SDL2: set `SDL_HINT_TOUCH_MOUSE_EVENTS=0` when you handle touch yourself,
  and use env `VITA_DISABLE_TOUCH_FRONT` / `_BACK` as needed.
- Add an in-game settings overlay (Halo CE: hold Select+Start) for sensitivity, deadzone, frame
  limit and resolution; ports are much easier to tune on hardware with one.

## 9. Audio, network, system dialogs

- Audio: SDL_mixer, openal-soft (Vita-patched 1.19.1), or `sceAudioOut` with your own thread.
  Stream music; decode to 48 kHz S16 stereo. Mixing thread on its own core.
- Network: BSD sockets work, with `_vita_net_init()` lazily loading SceNet on the first `socket()`
  (about 139 KB). Libraries needing `fcntl(O_NONBLOCK)`, `socketpair` or `pipe2` need the curl-style
  tweaks. HTTPS via SceHttp+SceSsl (`samples/net_https`) or curl+mbedtls.
- Dynamic Sony modules: `sceSysmoduleLoadModule(SCE_SYSMODULE_NET)` etc. IME and message dialogs
  go through SceCommonDialog and must be updated every frame while GXM draws; pass `GL_TRUE` to
  `vglSwapBuffers` while a dialog is active.
- Movies: SceAvPlayer plays H.264 MP4 (Halo CE converts Bink to MP4 with ffmpeg:
  `-c:v libx264 -profile:v baseline -level 3.1 -pix_fmt yuv420p -vf scale=640:-2 -c:a aac`).

## 10. 32-bit and portability audit

`scripts/audit_source.py` flags most of these. What to fix:

- `long`, `size_t` and pointers are 32-bit. Replace `long` assumptions with `int64_t`/`intptr_t`.
- Plain `char` is unsigned on ARM; add `-fsigned-char` for code written for x86 (Quake, Xash3D).
  Some code also needs `-fno-short-enums`.
- Unaligned loads from packed file structs can fault. Halo CE compiles game code with
  `-fmax-type-align=1` and only un-packs hot paths after profiling. Prefer `memcpy` reads.
- x86 intrinsics (`emmintrin.h`, `immintrin.h`, inline asm) need NEON or scalar fallbacks.
  Use `-mfpu=neon -mcpu=cortex-a9` (vitasdk default targets Cortex-A9) and `libmathneon` for trig.
- No `fork`, `exec`, `dlopen` (use `vita-libdl` or static linking; Xash3D uses `XASH_STATIC`), no
  `mmap` file mapping. A JIT needs the Vita executable-memory calls (section 4b). Replace `std::filesystem`-heavy or `getenv`-driven config with
  fixed `ux0:data` paths.
- Optimisation: `-O2`/`-O3 -ffast-math`. Treat LTO as risky: ldhewm3-rearmed (Doom 3) enabled
  `-flto` and removed it on 2026-09-13 because it "causes crashes". If you try it, A/B test on
  hardware. Wrap
  `memcpy`/`memmove`/`memset` to `sceClibMem*` via `-Wl,--wrap,...` when profiling shows it matters.
