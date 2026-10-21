# Cross-Platform API Emulation

Emulating a different platform's API (e.g., 3DS libctru/citro3d) on the Vita enables near-zero changes to
the original game code. The reference project is [mkwiita](https://github.com/boomannotjeff/mkwiita) — a
port of MKW-3DS (a 1:1 Mario Kart Wii recreation) to Vita.

## Architecture

```
Game (MKW-3DS C++)
    ├── libctru headers/types → platform/vita/include/3ds.h (reimplemented)
    ├── citro3d headers/types  → platform/vita/include/3ds/gpu/citro3d.h (reimplemented)
    └── game code (src/)       → compiled unchanged
                              ↓
platform/vita/src/             → VitaSDK + vitaGL
    ├── ctru_sys.cpp           → threads, sync, input, display, memory
    ├── ctru_gpu.cpp           → citro3d GPU state → vitaGL/GXM
    ├── ctru_shader.cpp        → GLSL vertex/fragment management
    ├── ctru_ndsp.cpp          → software DSP emulator (audio)
    └── zeroed_new.cpp         → operator new → zeroed memory
```

## Key Techniques

### Thread / Priority Mapping

The 3DS has 2 application cores with priorities `0x18..0x3F`. The Vita has 3 cores with priorities `64..191`.

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

### Lazy Synchronization Object Creation

Kernel objects (LightLock, RecursiveLock, LightEvent) use lazy creation so zero-initialized objects are valid:

```cpp
template <class Create>
static int lazyUid(volatile int& state, int& uid, Create create) {
    auto* s = reinterpret_cast<std::atomic<int>*>(const_cast<int*>(&state));
    if (s->load(std::memory_order_acquire) == 2) return uid;
    int expected = 0;
    if (s->compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) {
        uid = create();
        s->store(2, std::memory_order_release);
        return uid;
    }
    while (s->load(std::memory_order_acquire) != 2) sceKernelDelayThread(10);
    return uid;
}
```

### Dynamic Shader Generation from GPU State

PICA texture combiner (TEV) stages translated to GLSL at runtime:

- `FragmentKey` struct (64 bytes) encodes all combiner state (source registers, operators, functions per stage)
- `source()`, `colorOperand()`, `alphaOperand()`, `combine()` generate per-stage GLSL expressions
- Compiled programs cached as binaries on disk (`ux0:data/<app>/shaders/`)

### Production-Scale HAL Reference (encounter/aurora)

[encounter/aurora](https://github.com/encounter/aurora) is production-scale evidence for this exact route — a GameCube/Wii
Dolphin-SDK HAL (C++20, MIT) that decompiled PowerPC game source `#include`s unchanged and links against:
- GX emulated via FF/FD/FEF state-keyed TEV→shader codegen (`lib/gx/shader_info.cpp`, `lib/gx/shader.cpp`,
  `lib/gx/pipeline.cpp`) + GX FIFO command processor (`lib/gx/command_processor.cpp`); texture replacement included
- Pipeline cache in SQLite+zstd with background build thread (`lib/gfx/pipeline_cache.cpp`); CARD `.gci`/`.raw` save compat
- Not Vita-runnable (WebGPU/Dawn → D3D12/Vulkan/Metal; zero Vita support), but the cleanest reference for what a
  console-SDK HLE surface must cover: GX, GD, OS, PAD, SI, VI, DVD, CARD, AR, THP

Validates the skill's compiled-shader-binary-cache practice (mkwiita's `ux0:data/<app>/shaders/` binaries above):
a GPU-state-keyed pipeline cache is what makes TEV→shader translation repeatable — the same principle as aurora's
`lib/gfx/pipeline_cache.cpp`.

#### Counter-example — ACGC: plain C GX reimplementation + precompiled shader bank

aurora's FF/FD/FEF state-keyed runtime codegen + FIFO processor is NOT the only GX-HLE shape that works on the
Vita. [`Brendonm17/ACGC-Vita-Port`](https://github.com/Brendonm17/ACGC-Vita-Port) (Animal Crossing GameCube → Vita)
reimplements the GX call surface in plain C — 161 `GX*` functions in `pc/src/pc_gx.c` matching the decomp's
Dolphin header names — with no state-keyed runtime codegen and no FIFO command processor, and it ships playable.
TEV state selects among **52 precompiled CG shaders + 1 uber shader** (offline psp2cgc → GXP, embedded in a
generated 3.4 MB header) by TEV-configuration key at runtime (`pc/src/pc_gx_tev.c`). The required HAL coverage
is the same and all of it is stubbed in `pc/*.c`: GX/OS/VI/PAD/CARD/DVD (+ AI/AR/DSP), with the Dolphin hardware
sources excluded from the build. Practical difference: a precompiled bank has **no runtime GLSL compiler in the
loop** (like mkwiita's on-disk cache) — faster and safer for a fixed game; aurora-style runtime codegen earns
its complexity only when the game's shader state space is unbounded or unknown in advance.

### Software DSP Audio Emulator

Full NDSP software emulator with 24 voices:

- Decoding: PCM8, PCM16, mono/stereo, DSP-ADPCM (8-byte frames, 14 samples each)
- Resampling: linear interpolation with fractional stepping
- Per-voice IIR low-pass: `y = (1-e)x + ey'` with `e = exp(-2πf₀/Fs)`
- Mix: 12-channel surround → front L/R with surround folding
- Runs at highest priority on dedicated core (core 2)

### Input Mapping

Follow **Vita's button layout, not the source platform's**:

| Source Button | Vita Physical | Key Macro |
|---------------|---------------|-----------|
| A (3DS) | Cross | `KEY_A` |
| B (3DS) | Circle | `KEY_B` |
| X (3DS) | Triangle | `KEY_X` |
| Y (3DS) | Square | `KEY_Y` |

Stick axis handling includes a center deadzone for hardware variance.

### Runtime Quality Tuning

Quality settings stored in `ux0:data/<app>/quality.txt` (name=value pairs), e.g.:
```
framerate=60
resolution=1.5
shadowVolumes=1
bloomBlurRounds=2
```

Debug switches via empty files (e.g., `gpu-sync.txt`, `no-shader-cache.txt`).

### QA File I/O Tracing

Link-time `fopen` wrapping via `-Wl,--wrap=fopen` to count opens and measure timing.

## When to Use

- The source game targets a different handheld/console with a well-documented API
- The game code is largely unchanged and only the platform layer differs
- The target platform's GPU API (GXM/vitaGL) can express the source's fixed-function pipeline
- A full reimplementation would be more work than an emulation layer

## Reference Project

[mkwiita](https://github.com/boomannotjeff/mkwiita) — MKW-3DS (Mario Kart Wii for 3DS) → Vita:
- Platform layer: ~2200 lines across 7 C++ files
- Build: CMake + Python orchestrator (`tools/vita/build.py`)
- Dependencies: pinned via `dependencies.json`
- Shader cache: compiled programs saved as binaries to `ux0:data/mkw/shaders/`
