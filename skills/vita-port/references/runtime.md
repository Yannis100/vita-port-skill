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
11. THUG (Tony Hawk's Underground) native recompile
12. Source engine (HL2): multi-pool memory, kernel exec mapping, ToGLES dialect, threading
13. Source engine (HL2): data-driven cvars, honest performance numbers, packaging/QA
14. ACGC (Animal Crossing GameCube) decomp → vitaGL

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
| DaedalusX64-vitaGL | 256 MiB (`_newlib_heap_size_user`) | clocks 444/222/222/166, 128 MB max ROM in RAM |
| VitaKotor2 | 160 MiB + 64 MiB bigalloc pool (max 8×8 MB segs) | `ATTRIBUTE2=12`, 80 MiB vitaGL threshold, 4 GB `ux0:` data |
| Source engine (HL2, LargeVegetable) | newlib heap 232 MB (`_newlib_heap_size_user`) + 72 MB "large-block" arena via `sceClibMspaceCreate` (≥256 KB allocs) | engine "hunk" committed on demand; GL RAM threshold raised to 88 MB; vitaGL circular pool cut to 9 MB (section 12) |

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

**Partition the newlib heap vs vitaGL explicitly** (from VitaKotor2 `loader/config.h`, 2026-10). The
order matters: set `_newlib_heap_size_user` first, then `MEMORY_VITAGL_THRESHOLD_MB` (the amount
vitaGL must leave unclaimed; vitaGL grabs "everything else" at `vglInitExtended`, which runs before
the game). If you shrink newlib, raise the threshold in step or vitaGL claims the difference and the
game finds nothing. VitaKotor2 used 160 MiB newlib + 80 MiB vitaGL threshold.

**Big-allocation isolation** (VitaKotor2 `loader/bigalloc.c`): mixing multi-MB blocks with a game's
thousands of small long-lived objects shreds the newlib heap — the largest servable block halved
from 32 MB to 512 KB over ~150 s while 46 MB stayed free, ending in an uncaught `bad_alloc` on a 1 MB
request. Fix: serve every request ≥ 256 KB from separate `sceKernelAllocMemBlock` segments (8 MB
each, up to 8, committed lazily). The budget is taken *from* newlib, not added — there is nothing
spare once vitaGL claims everything except `MEMORY_VITAGL_THRESHOLD_MB`.

**Android .so memory map** (VitaKotor2 `loader/config.h`): the loader maps each loaded Android
library at a fixed address so they don't overlap — `libkotor2.so` at `0x98000000`,
`libc++_shared.so` at `0x96000000`, `libLzmaLib.so` at `0x94000000`, `libminiz.so` at `0x92000000`,
`libObbVfs.so` at `0x90000000`. Keep the 192 MB heap out of this range (its base can collide with
`0x8Cxxxxxx`). For N64-class workloads (DaedalusX64), the ROM itself is held wholly in RAM (128 MB
max) with `_newlib_heap_size_user = 256 MB` and an exec-time `sceKernelAllocMemBlock` for the dynarec
code cache.

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
- **DaedalusX64's dynarec** (2026-08-21 series): a working dynarec must invalidate precisely.
  It replaced full cache clears with per-range invalidation (`e9cf3e5`), invalidates only the
  effective range in its Mario/Rugrats HLE (`cd4ffa3`), pre-reserves a 10k-entry fragment vector
  (`172d2b4`), and kept a "fall back hot SMC blocks to interpreter" option (`da3956e`) plus a
  per-game hack (Paper Mario) to always interpret one region (`1c8a31e`). RDRAM texture hashing
  was rewritten with NEON `uint32x4_t` to hash 16 bytes per lane (`722c46b`); N64 texel bytes are
  byte-swapped during the same pass so conversion and hashing share one read. Dynarec code lives
  directly under `Source/SysVita/DynaRec/` and emits ARM (not C) — no dependency on kubridge.

### Vita dynarec without kubridge (DaedalusX64)

DaedalusX64's ARM dynarec is pure C/ARM — no kubridge, no kernel patches:
- JIT code buffer: `sceKernelAllocMemBlockForVM("code", 8*1024*1024 * 2)` (two 8 MB VM blocks), made executable
  with `sceKernelSyncVMDomain`; `kuKernelMemProtect(READ|WRITE|EXEC)` only as fallback.
- Hot trace: interpreter loops until a block crosses `gHotTraceThreshold = 10`, then dynarecs it.
- Precise invalidation: dynarec blocks invalidated only when required and only over the affected range; fragment
  cache is pre-reserved for 10k entries; SMC-heavy regions can fall back to the interpreter per-block.
- 128 MB N64 RDRAM is mapped into CPU RAM; RDRAM is dirty-marked so only changed regions re-upload to the GPU,
  and hashing is NEON-accelerated (`uint32x4_t`, 16 B/lane).
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
  code write. Old ARM `.so` files that use `SWP` atomics need kubridge v0.3.1_hotfix (SWP support landed in the v0.3.1 commit; the release to pin is the hotfix).
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

### 5b. Whole-process pinning layouts (VitaKotor2)

KOTOR II on Vita pins every thread to a fixed 3-core layout (`loader/threads.h`, `loader/threads.c`):

```c
#define CPU_GAME   SCE_KERNEL_CPU_MASK_USER_0   /* SDL_main, nothing else */
#define CPU_AUX_A  SCE_KERNEL_CPU_MASK_USER_1   /* audio mixer, half the workers */
#define CPU_AUX_B  SCE_KERNEL_CPU_MASK_USER_2   /* GL worker, parked main, GC, rest */
```

- `thread_census_add_ex()` records each created thread with its pin mask and old mask; a census
  lists which core is busy and with what. Global `THREAD_PINNING` toggles the whole layout on/off
  (used for A/B testing on hardware); `thread_layout_apply(pinned)` re-applies the recorded layout
  to every thread dynamically, so one session compares pinned vs unpinned.
- `thread_next_worker_mask()` alternates game workers between cores 1 and 2.
- The audio mixer runs at `AUDIO_MIXER_PRIORITY = 0x100000F0` (one step above the default), pinned
  to core 1 (it sleeps in `sceAudioOutOutput` most of the time, so rank it above the game's threads).
- The GL worker (`gl_worker.c`) runs pinned to core 2 at priority `GL_WORKER_PRIORITY=158` with a
  2 MiB stack; the game thread records GL commands, the worker replays them (vitaGL on its own
  core). Config: `GL_WORKER_MODE=2` (0 off, 1 inline record+replay, 2 worker thread), it lets the
  game run `GL_WORKER_FRAMES_AHEAD=1` frame ahead.

Key insight: CPU-bound engine ports on the Vita benefit from **recording GL on the game thread and
replaying on a dedicated core**. KOTOR II measured ~4.5 ms of GL command-capture per frame vs ~8 ms
when the game thread called vitaGL directly (`docs/specs/PERFORMANCE.md` section 5.7). The GL worker
uses a lock-free ring buffer of wrapped calls with semaphores for sync calls that return data
(pointer args refer to producer memory during a sync call). Producer keeps a state copy so the
worker replays with correct buffer binds/attribute pointers.

### GL worker thread (VitaKotor2, gl_worker.c)

For heavy so-loader or engine ports, run all GL calls on a dedicated thread through a lock-free ring buffer:
- wrap all `gl*` with `-Wl,--wrap`, the game thread records calls, a GL thread on core 2 executes them.
- 64-byte cache-line alignment for the shared state is mandatory: a shared cache line rewritten by the worker
  after every command made every recorded call miss (real hardware finding from KOTOR II).
- Generate the wrappers with a small tool (`tools/gen_glw.py` in VitaKotor2) rather than hand-writing them.

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

**Solid 30 FPS instead of uneven 34–37** (VitaKotor2 `loader/frame_pace.c`, v0.4.2): a game whose
engine can render faster than 30 but unevenly is capped at an even 30 by letting each frame cover
exactly two vblanks. Vsync stays on — turning it off measured no faster. Data files can override
it per install (`ux0:data/kotor2/fps_cap.txt` containing `0`). This is a much cheaper cap than a
busy-waited target.

## 7. Files and paths, savedata

- `app0:` is the read-only installed bundle and the default cwd. Write only to
  `ux0:data/<appname>/` (create directories with `mkdir`/`sceIoMkdir`). Some ports also probe
  `uma0:` for SD2Vita. `fopen("ux0:data/x/y.txt", ...)` works.
- Let users keep large assets outside the VPK in `ux0:data/<appname>/`; check at start and show an
  on-screen message with the expected path, then exit cleanly (Halo CE does this).
- Official savedata slots need `sceAppUtilInit` and the `sceAppUtilSaveData*` calls; plain files in
  `ux0:data` are the simpler route for homebrew.
- Mind free space: caching decompressed data can need gigabytes. Document it. VitaKotor2 needs about
  **4 GB free** for the Android game data (1.8 GB OBB + voice packs).
- **Keep saves in a SEPARATE directory from assets** (`ux0:data/<name>/save/` vs
  `ux0:data/<name>/Data/`) so a reinstall or data wipe does not remove progress (THUG).

### 7b. SD-card I/O optimisations (VitaKotor2 patterns)

The Vita memory card is slow (~10 MB/s, seek-heavy). KOTOR II removed whole classes of stutter with
caching, all behind simple file/hook patterns:

- **Archive read cache** (`loader/obb_cache.c`, `ramfile.c`): the engine re-read the same small
  scripts from the card every time. Keep repeated reads in RAM (mean frame 75 → 60 ms).
- **Talk table in RAM** (`loader/ramfile.c`): `dialog.tlk` lookups cost ~38 ms each on the card (the
  game did flush+seek pairs per string). Read the file once; serve every later `fopen` from an
  `fmemopen` stream so seeks/flush/read never reach the card. Removed the 0.2–0.6 s combat stutter.
- **Persistent archive index** (`loader/obb_index.c`): a 1.8 GB OBB's ZIP headers are scattered
  (mean gap 107 KB between headers), defeating read-ahead. The loader records the bytes each boot
  reads and replays them from a small saved file from the second boot on (title ~34 s → ~24 s).
- **Loose-file miss cache** (`loader/fs_patch.c`): the engine stats/opens read-only folders for
  assets that are often not there; answer misses from a per-folder listing made once.
- **Voice/loc text kept open** (`loader/fdtrack.c`): a scene holding hundreds of file handles can
  exhaust the limit if each keeps the file open (Telos: the log then can't reopen). Read the line
  into memory and `close` immediately (about 2 MB for 65 held lines in that scene).
- `sceIoPread` instead of `fseek`+`fread` (one syscall, no newlib buffer invalidation) for archive
  reads.
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
- **4 controllers from one handheld** (DaedalusX64 `Source/SysVita/Input/InputManagerVita.cpp`):
  the N64 has 4 pads, the Vita one. It reads "virtual" controllers 2..4 from the same physical pad
  (port `i ? (i+1) : 0`), zeroing the others; the player switches emulated controllers. Analog is
  normalised from 0..255 to -128..127, then non-linearly smoothed
  (`stick.x = 0.5*stick.x * (1+stick.x*stick.x)`) before mapping to the N64's -80..80 range.
- **Rear-pad L2/R2 quadrants** (DaedalusX64, `gUseRearpad`): split the rear panel into 4 quadrants
  (left = L2/L3, right = R2/R3 by Y halves) so a console with no L2/R2 can trigger them. Dedicated,
  skippable on PS TV.
- **Active-low pad polarity** (THUG, `Code/Sys/SIO/Vita/p_siodev.cpp`): an engine that reads the raw
  DualShock2 byte layout expects buttons ACTIVE-LOW (0xFF minus the pressed bits); inverted polarity
  is the classic "everything pressed" bug. Vita has only 2 triggers → map Xbox L=L1+L2 / R=R1+R2 to
  the L/R buttons; optional DualShock layout (PS TV / DS3/DS4 / rear-touchpad halves = L2/R2) via
  `dualshock_layout=1`.
- Poll the pad OUTSIDE the task loop for long blocking operations (movies): model a
  `ProcessDevices()` on the original console backend (`Code/Sys/SIO/Vita/p_sioman.cpp`).

## 9. Audio, network, system dialogs

**Native audio output pattern reference:** joel16/ElevenMPV and GrapheneCt/ElevenMPV-A
(`sceAudioOutOutput` ring buffer on a decode thread, `sceAudioOutSetVolume` with
`SCE_AUDIO_VOLUME_FLAG_L_CH|R_CH`, static-linked codec libs libopus/libvorbis/libogg/
libxmp-lite/dr_flac/mpg123) — the proven non-Android audio plumbing on Vita.

- **switchfin (Jellyfin client) media stack:** native mpv-on-GXM (`MPV_RENDER_API_TYPE_GXM`, 4x MSAA,
  `rgba8` FBO, `display_buffer_count=1`, `video-latency-hacks yes`, `vd-lavc-threads 4`), FFmpeg SCE hw
  decoders (`aac_vita`/`mp3_vita`/`h264_vita`), curl with a ~20 MiB physically-contiguous pool
  (`sceClibMspace` + `curl_global_init_mem`) and mandatory `CURLOPT_NOSIGNAL`, `_newlib_heap_size_user`
  = 220 MiB, config at `ux0:/data/switchfin`. Reference: dragonflylee/switchfin.
- **Material-Eleven (libvita2d music player):** screen-off music via `sceAppMgrAcquireBgmPort`,
  system-volume param 9, 2 MiB vita2d vertex pool, MSAA chosen from free CDRAM before init, deferred
  audio-thread reaps with a generation counter; mono-track buffer must be `length × channel_count`.
  Reference: Perroabuelo/Material-Eleven.

- Audio: SDL_mixer, openal-soft (Vita-patched 1.19.1), or `sceAudioOut` with your own thread.
  Stream music; decode to 48 kHz S16 stereo. Mixing thread on its own core.
- **FMOD → sceAudiodec/sceAudioOut on the Vita** (VitaKotor2 `loader/audio_patch.c`): the Android
  game uses FMOD; the loader replaces its FMOD channel/stream implementation, decodes MP3 with the
  Vita's hardware `sceAudiodec` (falling back to minimp3 on the audio thread when the hardware
  decoder is busy), and mixes into a single 48 kHz stereo `sceAudioOut` port. KOTOR II's own
  `audio_thread` runs at `0x10000100` (or `AUDIO_MIXER_PRIORITY` when pinned), 32–64 KB stack.
  - Double-buffer pattern (v0.5.5+, `AUDIO_DOUBLE_BUFFER`): hand `sceAudioOutOutput` two buffers
    taken in turn so mixing the next grain never races the playing buffer (SDL's Vita backend does
    the same).
  - Stream long assets (14–24 MB PCM) instead of decoding them whole; skip the FMOD "channel scan"
    (called ~50×/frame) when no sound has ended `g_end_dirty` — about 1 ms/frame.
  - OpenSL ES contract (for Bink movie audio) is implemented narrowly in `opensl_patch.c` — 4
    vtable interfaces + a bounded PCM queue into the same mixer, not a full OpenSL.
- **Bink movies play through the game's embedded decoder** (VitaKotor2 `bink_patch.c`, KOTOR II
  embeds the Bink decoder + renderer + OpenSL adapter in `libkotor2.so`). The loader feeds PCM from
  Bink into its audio mixer and renders frames via vitaGL. Test switches `KOTOR_BINK_SHADER_TEST` /
  `_LEGAL_VIDEO_TEST` / `_OPENSL_TEST` gate the experimental routes.
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

**clang-built Vita workloads are proven beyond VitaSDK GCC**: mh3-wii compiles a large translated C++
base with clang-21 + lld (VitaSDK only for sysroot/packaging), required `--pic-veneer` for the large
code, and ships ThinLTO + PGO release builds (see static-recomp.md).

## 11. THUG (Tony Hawk's Underground) native recompile

Repo: thug-vita-port — THUG's own C++ recompiled natively for Vita on vitaGL (see
`references/port-types.md` section 4c). Runtime lessons that generalise:

- **`vglInitExtended` returns GL_FALSE on SUCCESS and GL_TRUE when the resolution was downgraded.**
  Treating it as an error check kills the nominal path — do not `if (!vglInitExtended(...)) { fail; }`
  (evidence: `vita/src/main_vita.cpp`).
- **Heap split**: keep `sceLibcHeapSize` tiny (4 MB — SceLibc is barely used) and give the newlib
  heap the big share (192 MB `_newlib_heap_size_user`). A first draft's 128 MB `sceLibcHeapSize`
  starved vitaGL's splash texture. Raise `sceUserMainThreadStackSize` to 4 MB because the engine
  puts large QB-parse buffers on the stack. Unlock the extra 109 MB via
  `VITA_MKSFOEX_FLAGS -d ATTRIBUTE2=12` (365 MB total).
- **Audio: three separate `sceAudioOut` ports**, because Vita exposes one stream per port — BGM
  (48 kHz music), VOICE (dialogue), MAIN (software SFX mixer). Decode-on-load for small SFX
  (~48 KB each). Mix with 32-bit accumulate then clamp (16-bit summing of 24 voices clips audibly).
  Fixed-point 16.16 resample 44100→48000 with a separate integer index + 16-bit fraction — a single
  16.16 position overflows at 65536 samples ≈ 1.49 s, breaking looping grind sounds.
- **Timer must be genuinely real.** A stub timer is a frozen-simulation bug later hunted elsewhere;
  input/save may be neutral stubs ("no controller / no save"), but time must advance.

## 12. Source engine (HL2): multi-pool memory, kernel exec mapping, ToGLES dialect, threading

Repo: `LargeVegetable/source-engine` (branch `vita`). Base: `nillerusr/source-engine` (modified
Source 2017, TF2 2018 leak; D3D9 material system + ToGL/ToGLES). Native recompile via VitaSDK +
vitaGL with a bespoke ELF so-loader; see `port-types.md` section 4d.

- **kubridge is a hard requirement for engines that dlopen/mmap executable code.** User-level Vita
  has no exec-mapping; the ELF so-loader fails fast with a user-facing `FatalError` message if the
  `kubridge` module is not loaded (`launcher_vita/main.cpp`
  `_vshKernelSearchModuleByName("kubridge", ...)`), mirroring the weak-stub boot check in section
  4c.
- **Memory = deliberate multi-pool split**, tuned with instrumentation and documented in comments:
  - newlib heap 232 MB (`_newlib_heap_size_user`);
  - separate 72 MB "large-block" arena via `sceClibMspaceCreate` for ≥256 KB allocations
    (`so_large_heap_init`) — the same big-allocation isolation idea as VitaKotor2's bigalloc
    (section 4);
  - engine "hunk" committed on demand;
  - GL RAM threshold raised to 88 MB.
  Comments record the measurements that drove the split ("heap peaked at ~150 MB... 32 MB moved
  back", "kernel free bottomed at 23 MB on tour 5").
- **vitaGL per-frame circular pool sizing matters as much as the engine heap.** The default 32 MB
  circular pool spilled into VRAM; the port sets `VITA_GL_CIRCULAR_POOL_SIZE = 9 MB` via a
  `--wrap=vglInitExtended` override in the launcher.
- **Renderer swap reuse: keep the engine's own DX9→GLES translator and add a thin dialect
  down-converter instead of hand-rewriting shaders.** Source path: D3D9 shader source → ToGLES
  (GLSL ES 3.00) → `togles/linuxwin/vita_glsl.cpp` rewriting to GLSL ES 1.00 → vitaGL's GLSL→Cg →
  GXM. Plus `appframework/vita_glshims.cpp` provides stand-ins for GL entry points vitaGL lacks
  (sync objects, FBO).
- **Threading: pin PC-era multithreading to the Vita's 4 cores** — server frame as a parallel job
  (`host_thread_mode 1`), `cl_threaded_bone_setup`, `cl_threaded_particles`, render thread pinned
  to its own core; the engine runs on its own 8 MB-stack thread started by a tiny main thread
  (`ENGINE_THREAD_STACK_SIZE`).
- **Physics: keep the engine's native physics** (Source's IVP-based vphysics, forked as
  source-physics) and tune cost with cvars — do not swap in a new solver.

## 13. Source engine (HL2): data-driven cvars, honest performance numbers, packaging/QA

Same repo as section 12. A PC-era engine copes with **data-driven cvars, not hardcoded cuts**:
`launcher_vita/main.cpp` `WriteDefaultUserConfig` writes a commented ConVar template
(`vita_user.cfg`):

- Xbox 360 AI tuning: `ai_default_efficient 1; ai_strong_optimizations 1`; `ai_think_limit_ms 6`,
  `ai_frametime_limit 0.01`, `ai_vita_idle_think_interval 0.2`
- `mat_picmip 3` (1/8 textures), `r_shadows 0; r_dynamic 1; r_worldlights 0`, no water
  reflections, `r_flex 1` + `r_vita_flex_dist`, `g_ragdoll_maxcount 2`,
  `props_break_max_pieces 4`, `rope_collide 0`, `vita_physics_small_props`, `vita_apc_lock`,
  `vita_queued_render`, `vita_staticprop_minpixels`
- Note: **dynamic lighting is KEPT on** (`r_dynamic 1`, flashlight on, `r_newflashlight 0`); what is
  off is shadows, water reflections, 3D sky, decals, bloom, bump mapping, tonemapping, motion blur,
  brass/flecks.

**Honest performance numbers (correcting the common rumor spread on Reddit):** renders at
640×368; mostly 30–60 fps, heaviest fights dip into the low 20s — NOT "25-45 fps". Clock set via
`scePowerSetArmClockFrequency(444)` = 444 MHz CPU / 222 MHz bus / 222 MHz GPU / 166 MHz Xbar —
the port does NOT request an overclock (no "500 MHz").

**Packaging/QA details worth replicating:**
- `param.sfo` `ATTRIBUTE2=12` for extended memory.
- LiveArea art must be 8-bit palette PNGs with a content-rev bump or the shell caches stale art.
- A `-vitadebug` flag gates deep logging (10-s perf/memory lines, heap checks, saved frames,
  shader links) with boot logs rotating `.1`–`.4`.
- A `vita_screenshot` console command captures the next frame + world material under the
  crosshair for bug reports.
- `package_release.sh` refuses to ship builds containing the builder's `$HOME`/username/hostname
  or TODO/`@PLACEHOLDER@`.
- A "map tour" harness (`vita_maptour`) auto-loads 10 late chapters to validate
  memory/shader-slot headroom without human play.

## 14. ACGC (Animal Crossing GameCube) decomp → vitaGL

Repo: `Brendonm17/ACGC-Vita-Port` (branch `vita`) — a native recompile of the ac-decomp C decomp (GameCube,
GAFE01_00 USA), the "decomp + custom renderer" route where a C GX-HLE maps onto **vitaGL** instead of a
hand-written GXM layer (`port-types.md` section 4; shader-bank contrast in `api-emulation.md`). Runtime
lessons that generalise:

- **C GX-HLE emits GL → a project-private vitaGL fork.** `vita/rebuild_vitagl.sh` builds the
  `async-compressed-tex-prep` branch (`vglPrepareCompressedTexture2D` / `vglCommitPendingTexture` for
  off-thread block-compressed texture uploads), patches a Cg row-major `M1*M2 → M2*M1` matrix-multiply bug,
  tunes `MAX_CUSTOM_SHADERS 2048` / `UNIFORM_CIRCULAR_POOL_SIZE 8 MB`, and installs to
  `$VITASDK/arm-vita-eabi/acgc/` (its own SDK dir) so the fork cannot collide with the shared vitaGL.
- **3-core thread split with explicit affinity + `__sync_synchronize` fences.** core0 = game+submit; core1 =
  the emu64 display-list interpreter worker (~92% of frame time; 512 KB stack, priority `0x10000100`); core2 =
  the "prededup" pass. `vita_pin_hidden_threads()` re-pins the SDL/VitaGL/system threads after creation
  (`vita/src/vita_platform.c`).
- **Deferred double-buffered draw submission.** `vita_gx_cmdbuf.c` (~2260 lines) records + prededups + culls +
  builds indices on the workers; `submit_frame` only replays (`pc_gx_flush_vertices` →
  `vita_gx_flush_vertices_cmdbuf`).
- **Memory:** 104 MB newlib heap + 4 MB main stack (1 MB caused corruption) under `ATTRIBUTE2=12`. **Keep the
  perf-log `FILE*` open once** — a per-call `fopen` triggers an eMMC metadata sync that drops frames.
- **Sleep-aware lifespan:** the Vita monotonic clock stops during suspend, so the day/night cycle re-anchors at
  boot; `scePowerRegisterCallback` on a parked thread is the only pre-kill signal; auto-save only while walking
  outside (`vita/README.md`).
- **Embedded sub-console swap:** replace the embedded NES core (`ks_nes_core.cpp` PPC-ASM NES CPU/PPU) with
  Nofrendo (scanline-based, 40+ mappers); keep game-side `famicom.cpp` ROM loader + the `vita_nes_fixnes.c`
  `ksNesDraw*` API shim.
- **Honest perf posture:** no headline FPS/clock; resolution scale 100/75/50% = 960x544/720x408/480x272,
  MSAA 0/2/4; "60 fps" is a design target, not a device-verified claim.
- **HD texture packs:** Dolphin DDS (BC7/BC3) → DXT1/DXT5 conversion; V3 pre-swizzled GXM Morton layout =
  direct memcpy to VRAM vs V2 linear = swizzle on worker; 48 MB `VTC_VRAM_BUDGET` LRU with tombstones +
  refcounts (`vita/src/vita_vtc.c`).
- **Build/deploy:** WSL builds sync to ext4 (NTFS is 10-50x slower); `deploy.sh` hot-deploys just `eboot.bin`
  over VitaCompanion FTP ports 1337/1338.
- **Multiplayer (port-added):** up to 4 players ad-hoc `scePspnetAdhoc` / LAN / Internet UDP 19520,
  NAT-PMP→UPnP, CGNAT detection, IME overlay chat — the port outgrew the original game's LAN scope.
