# Android .so Loader Ports on PS Vita

## Overview

The Android .so loader technique enables running Android applications on PS Vita by intercepting Android API calls
and mapping them to VitaSDK equivalents. The loader loads the app's `.so` ELF file, resolves its imported symbols
to Vita functions, and hooks critical paths.

**Reference project:** [soloader-boilerplate](https://github.com/v-atamanenko/soloader-boilerplate) — production-ready
scaffolding maintained by Volodymyr Atamanenko (gl33ntwine). Used as base for ports including Modern Combat 3, Geometry
Dash, Lego Star Wars, Hill Climb Racing, NBA Jam, SoulCalibur.

**Community guide:** [vitasoguide](https://github.com/Rocroverss/vitasoguide) — APK checker tool, porting examples,
FAQ, and install scripts by Rocroverss.

**Portability criteria:** [Android2Vita-Candidate-Ports-List](https://github.com/Rinnegatamante/Android2Vita-Candidate-Ports-List)
— authoritative checklist by Rinnegatamante (original soloader maintainer).

## Port Types

### Non-NDK Ports (JNI_OnLoad entrypoint)

The `.so` has a `JNI_OnLoad` function. The loader resolves this and calls it directly. Most older Android apps/games
fall into this category.

**Init path:** `soloader_init_all()` → `JNI_OnLoad(env, JNI_VERSION_1_4)` → game loop via `Android_main` or similar.

### NDK Ports (`ANativeActivity_onCreate` entrypoint)

NDK apps use the Android NDK activity lifecycle with `ANativeActivity_onCreate`. These require the FalsoNDK submodule.

**Init path:** `soloader_init_all()` → `ANativeActivity_onCreate()` → AInputQueue/AWindow event loop.

Set CMake option `NDK_PORT=ON` for these ports.

## Requirements Checklist

From Rinnegatamante's Android2Vita-Candidate-Ports-List:

| Condition | Status |
|-----------|--------|
| ARMv6 or ARMv7 (armeabi-v7a) executable | Required |
| OpenGL: GLES 1.x or GLES 2.x | Required |
| FMOD: no usage, libfmod.so, or libfmodstudio.so | Acceptable |
| OpenGL: GLES 3+ | Possible but harder (needs vitaGL translation) |
| ARMv8 (arm64-v8a) only | Not supported |
| Kotlin only | Not supported |
| Unity (libunity.so) | Not supported |
| libGDX (libgdx.so) | Not supported |

## Build Setup

### VitaSDK-softfp (Required)

Stock VitaSDK uses **hard-float ABI**. Android .so loader ports require **soft-float ABI** to match Android's calling
convention.

```bash
git clone https://github.com/vitasdk-softfp/vdpm ~/vdpm-softfp
cd ~/vdpm-softfp
./bootstrap-vitasdk.sh
./install-all.sh
```

Set `VITASDK=~/vdpm-softfp/arm-vita-eabi` in your environment for .so loader projects.

### CMake Options

| Option | Default | Description |
|--------|---------|-------------|
| `NDK_PORT` | OFF | Enable for NDK apps (ANativeActivity_onCreate entrypoint) |
| `USE_SCELIBC_IO` | ON | Use SceLibcBridge for file I/O |
| `SHADER_FORMAT` | GLSL | One of GLSL, CG, GXP |
| `DUMP_COMPILED_SHADERS` | ON | Cache compiled shaders to disk for faster iteration |

### Submodules

soloader-boilerplate uses Git submodules:
- `falso_jni` — fake JVM for JNI method/field resolution
- `so_util` — ELF loading, relocation, symbol resolution
- `falso_ndk` — fake NDK activity (NDK_PORT=ON only)
- `vitagl` — OpenGL ES to GXM translation

```bash
git submodule update --init --recursive
```

### kubridge (Required on Hardware)

kubridge is a taihen plugin that provides user-space kernel memory operations. Required for:
- Mapping RX memory blocks (`.so` code)
- Patching kuser helper addresses (atomic operations, memory barriers)
- Memory protection changes

Users must install `kubridge.skprx` via taihen on their Vita (firmware 3.60+).

Error if kubridge not loaded: `"kubridge is not loaded"` at startup.

## Initialization Sequence

The 14-step init sequence runs in `soloader_init_all()` (`source/utils/init.c`):

1. **Parse config** — Check `-config` launch param, redirect to configurator if present
2. **Set CPU/GPU clocks** — Max out to 444/222/222/166 MHz
3. **Initialize FIOS** (if `USE_SCELIBC_IO`) — Fast I/O subsystem
4. **Check kubridge** — Verify taihen plugin loaded
5. **Check `.so` file** — Verify APK's `.so` exists in `ux0:data/<app>/`
6. **Load and relocate `.so`** — ELF loading via so_util
7. **Load settings** — Read `settings.bin` if present
8. **Resolve imports** — Symbol table matching (`dynlib.c`)
9. **Apply patches** — kubridge-based hooks (`patch.c`)
10. **Flush caches** — CPU cache maintenance
11. **Run init arrays** — C++ static initializers
12. **Pre-initialize vitaGL** — GXM context setup
13. **Initialize FalsoJNI** — Fake JVM method/field stubs
14. **Start controls thread** — Input polling thread

## Symbol Resolution (`dynlib.c`)

The symbol resolution table maps Android imports to Vita functions. Structure:

```c
typedef struct {
    const char *name;
    uintptr_t    addr;
} so_dynlib;

so_dynlib default_dynlib[] = {
    // C++ RTTI/exceptions
    { "_ZdlPv", (uintptr_t)&_ZdlPv },      // operator delete(void*)
    { "_Znaj", (uintptr_t)&_Znaj },         // operator new[](unsigned int)
    { "__cxa_guard_acquire", (uintptr_t)&__cxa_guard_acquire },
    
    // C internals
    { "__aeabi_memcpy", (uintptr_t)&sceClibMemcpy },
    { "__aeabi_memset", (uintptr_t)&sceClibMemset },
    { "__aeabi_memmove", (uintptr_t)&sceClibMemmove },
    
    // Math
    { "sincos", (uintptr_t)&sceClibSincos },
    { "sincosf", (uintptr_t)&sceClibSincosf },
    
    // GLES via vitaGL
    { "eglCreateContext", (uintptr_t)&eglCreateContext },
    { "glCreateShader", (uintptr_t)&glCreateShader },
    // ... 1000+ more entries
};
```

**Adding new symbols:** Check logs for "symbol not found" warnings, then add the entry to `dynlib.c` mapping to the
Vita SDK function. Use `nm` on the `.so` to find unresolved symbols:
```bash
arm-vita-eabi-nm -u your_game.so | grep "U "
```

**Bionic-specific data:** Some apps reference BIONIC_ global data (`BIONIC_ctype_`, `BIONIC_tolower_tab_`). Map these
to equivalent data or provide stubs.

## Hooking and Patching (`patch.c`)

### hook_addr() Pattern

Directly patches a memory address to point to a replacement function:

```c
static void hook_addr(uint32_t addr, uintptr_t replacement) {
    uint32_t patch = (uint32_t)((replacement - addr - 4) >> 2);
    kuKernelCpuUnrestrictedMemcpy((void *)addr, &patch, sizeof(uint32_t));
}
```

### SO_CONTINUE Macro

For hooked functions that need to call the original:

```c
#define SO_CONTINUE(fn, ...) \
    (*(typeof(fn) *)(fn))(##__VA_ARGS__)
```

### kubridge Atomic Operation Patches

Android kuser helpers (at fixed addresses `0xFFFF0FA0`, `0xFFFF0FC0`) implement memory barriers and atomics. The
loader maps RX memory and patches these:

```c
void kuser_patch(void) {
    // Allocate RX memory block for kuser replacements
    SceKernelAllocMemBlockKernelOpt opt;
    memset(&opt, 0, sizeof(opt));
    opt.size = sizeof(opt);
    opt.attr = 0x1;
    opt.field_C = 0x9A000000;
    int block = kuKernelAllocMemBlock("atomic", SCE_KERNEL_MEMBLOCK_TYPE_USER_RX, 0x1000, &opt);
    void *addr = 0;
    kuKernelGetMemBlockBase(block, &addr);
    kuKernelMemProtect(addr, 0x1000,
        KU_KERNEL_PROT_EXEC | KU_KERNEL_PROT_READ | KU_KERNEL_PROT_WRITE);

    hook_addr(0x9A000FA0, (uintptr_t)__kuser_memory_barrier);
    hook_addr(0x9A000FC0, (uintptr_t)__atomic_cmpxchg);

    // Scan .text for bionic kuser references and patch them
    for (uint32_t a = so_mod.text_base; a < so_mod.text_base + so_mod.text_size; a += 4) {
        uint32_t *inst = (uint32_t *)a;
        if (*inst == 0xFFFF0FA0) {
            uint32_t patched = 0x9A000FA0;
            kuKernelCpuUnrestrictedMemcpy((void *)a, &patched, 4);
        } else if (*inst == 0xFFFF0FC0) {
            uint32_t patched = 0x9A000FC0;
            kuKernelCpuUnrestrictedMemcpy((void *)a, &patched, 4);
        }
    }
}
```

## FalsoJNI (`java.c`)

Fake JVM implementation stubbing JNI class/method/field lookups.

### Field Resolution

```c
NameToFieldID nameToFieldId[] = {
    { 0, "SDK_INT", FIELD_TYPE_INT },       // android.os.Build$VERSION.SDK_INT
    { 1, "WINDOW_SERVICE", FIELD_TYPE_OBJECT }, // android.content.Context.WINDOW_SERVICE
};

FieldsInt fieldsInt[] = {
    { 0, 19 },  // Android 4.4 KitKat (API level 19)
};

FieldsObject fieldsObject[] = {
    { 1, "window" },
};
```

### Method Resolution

```c
NameToMethodID nameToMethodId[] = {
    { 0, "getSystemService", "(Ljava/lang/String;)Ljava/lang/Object;" },
    // Add more as needed by the app
};
```

## Input Mapping (`reimpl/controls.c`)

### Analog Deadzones

```c
static int16_t stickAxis(int16_t raw) {
    int16_t v = raw - 128;
    // Deadzone: Vita sticks rest slightly off-center
    if (v > -16 && v < 16) return 0;
    // Scale to Android range
    v = v * 156 / 127;
    return v < -156 ? -156 : v > 156 ? 156 : v;
}
```

### Touch Coordinate Scaling

```c
void poll_touch() {
    SceTouchData touch;
    sceTouchPeek(SCE_TOUCH_PORT_FRONT, &touch, 1);
    for (int i = 0; i < touch.reportNum; i++) {
        // Map 1920x1080 → 960x544
        float x = (float)touch.report[i].x * 960.f / 1920.0f;
        float y = (float)touch.report[i].y * 544.f / 1088.0f;
        controls_handler_touch(touch.report[i].id, x, y, CONTROLS_ACTION_DOWN);
    }
}
```

### Face Button Mapping

Follow **Vita's button layout**, not Android/Nintendo:

| Android/Nintendo Button | Vita Physical | Key Macro |
|------------------------|---------------|-----------|
| A | Cross | `KEY_A` |
| B | Circle | `KEY_B` |
| X | Triangle | `KEY_X` |
| Y | Square | `KEY_Y` |

## Asset Manager Bridge (`reimpl/asset_manager.cpp`)

Maps Android `AAssetManager` paths to Vita filesystem:

```cpp
AAsset* AAssetManager_open(AAssetManager* mgr, const char* filename, int mode) {
    // Prepend DATA_PATH + "assets/" to translate Android paths
    std::string realp = std::string(DATA_PATH) + "assets/" + filename;
    a->f = sceLibcBridge_fopen(realp.c_str(), "r");
    sceLibcBridge_fseek(a->f, 0, SEEK_END);
    a->fileSize = sceLibcBridge_ftell(a->f);
    return (AAsset *)a;
}
```

Android asset paths (e.g. `"models/player.obj"`) resolve to `ux0:data/<app>/assets/models/player.obj`.

## Shader Support (`utils/glutil.c`)

### SHADER_FORMAT Options

- **GLSL** — Standard GLSL shaders (default)
- **CG** — NVIDIA Cg shaders (older titles)
- **GXP** — Native GXM shaders (best performance)

### Shader Caching (`DUMP_COMPILED_SHADERS`)

Intercepts `glShaderSource()` and caches compiled binaries:

```c
void glShaderSource_soloader(GLuint shader, GLsizei count,
                              const GLchar **string, const GLint *_length) {
    // Concatenate shader sources
    char *str = malloc(total_length + 1);
    // ... build full shader string
    load_shader(shader, str, total_length);
    free(str);
}
```

Compiled shaders saved to `ux0:data/<app>/shaders/` as binaries for fast reload.
Bypass with `no-shader-cache.txt` (create empty file).

## File I/O Patterns

### Android Path Redirect (`reimpl/io.c`)

```c
FILE * fopen_soloader(const char * filename, const char * mode) {
    if (strcmp(filename, "/proc/cpuinfo") == 0)
        return fopen("app0:/cpuinfo", mode);
    if (strcmp(filename, "/proc/meminfo") == 0)
        return fopen("app0:/meminfo", mode);
    if (strcmp(filename, "/dev/urandom") == 0)
        return fopen("app0:/urandom", mode);
    // Fallback to standard open
    return __real_fopen(filename, mode);
}
```

### Memory Allocation Wrapping

Use `-Wl,--wrap=malloc` to intercept allocations for custom memory management:

```c
void * __wrap_malloc(size_t size) {
    return vglMalloc(size);  // vitaGL-managed pool
}

void __wrap_free(void *ptr) {
    vglFree(ptr);
}
```

## Debugging

### Debug Flags

Set via CMake options or environment:

| Flag | Value | Purpose |
|------|-------|---------|
| `DEBUG_SOLOADER` | 1 | Log symbol resolution, ELF loading steps |
| `DEBUG_OPENGL` | 1 | Trace GL calls, show shader compilation errors |
| `SO_UTIL_VERBOSE` | 1 | Detailed so_util logging |
| `FALSOJNI_DEBUGLEVEL` | 0 | FalsoJNI debug output |

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `"kubridge is not loaded"` | taihen plugin not active | Install kubridge.skprx on Vita |
| `0x80101051` | Missing kubridge/txlet | Check firmware 3.60+, install kubridge |
| `0x8010113D` | LiveArea assets missing | Fix icon0.png, template.xml in sce_sys/ |
| "symbol not found: XYZ" | Missing dynlib.c entry | Add entry mapping to Vita function |
| Black screen | Shader compile failure | Enable DEBUG_OPENGL, check GLSL version |
| Crash on start | .so not found | Verify `ux0:data/<app>/` layout |

### Unresolved Symbol Detection

1. Run with `DEBUG_SOLOADER=1`
2. Watch for "symbol not found" in vitaLog output
3. Note the mangled name (e.g., `_Znwm` for `operator new(unsigned long)`)
4. Add to `source/dynlib.c`:
   ```c
   { "_Znwm", (uintptr_t)&custom_new },
   ```
5. Rebuild and test

## Reference Projects

| Game | Repo | Notes |
|------|------|-------|
| Modern Combat 3 | [v-atamanenko/mc3-vita](https://github.com/v-atamanenko/mc3-vita) | Heavy OpenGL, FMOD |
| Geometry Dash | [hatoving/gdash-vita](https://github.com/hatoving/gdash-vita) | Simple GLES2, minimal hooks |
| SoulCalibur | [Rinnegatamante/soulcalibur_vita](https://github.com/Rinnegatamante/soulcalibur_vita) | Complex input, textures |
| Lego Star Wars | (various) | FMOD, particle effects |
| Hill Climb Racing | (various) | Physics, touch controls |
| NBA Jam | (various) | Multi-touch, 3D rendering |
| 9mm (HD) | [iwannagooutside/9mm-vita](https://github.com/iwannagooutside/9mm-vita) | Clean so-loader wrapper; pitfall: do NOT combine fd_fix with rePatch |
| Prince of Persia Classic, Zenonia 2/3, Asphalt 5, and other MetalSyntax ports | [MetalSyntax](https://github.com/MetalSyntax) | so-loader wrapper family |
| **KOTOR II** | [pyjabox/VitaKotor2](https://github.com/pyjabox/VitaKotor2) | **Hardest-known so-loader**: Android ARM libs + OBB, FMOD→sceAudiodec, Bink, OpenSL, JNI stubs, GL worker, whole-process core pinning, bigalloc heap isolation, 25 FPS |

### KOTOR II (VitaKotor2) — deep-dive patterns

An experimental native loader for the **Android release** of Star Wars KotOR II (`libkotor2.so`,
v2.0.4 only — patched at fixed offsets, so exact-SHA libraries required). Playable ~25 FPS on
hardware. Reads nothing but the user's own Android copy (APK libs + 1.8 GB OBB in
`ux0:data/kotor2/`).

**Port shape** (`loader/main.c`, `so_util.c`, `dynlib.c`):
- Adapts 5 Android `.so`s: `libkotor2.so` (main), `libObbVfs.so` (upward-call companion loading the
  OBB), `libminiz.so` + `libLzmaLib.so` (compression), `libc++_shared.so` (Android C++ runtime).
- **No JNI_OnLoad and no RegisterNatives.** The native surface is statically-exported Android
  callbacks + SDL_main, reached through the game's own `_JNIEnv::` wrappers. `jni_patch.c`
  fabricates a fake `JNIEnv`/`JavaVM` whose function-table slots are typed shims; everything else
  falls through to a traced safe-default so an unexpected call logs instead of dereferencing null.
- Imports wired to VitaSDK `libc`/`libm`/`libstdc++`/`pthread`; a `__sF[0x400]` dummy provides the
  bionic `&__sF[2]` `stderr` address and a safe `fprintf` routes miniz's error logs to the loader
  log (a real `fprintf` on a fake `FILE*` would fault). `KOTOR2_BUILD` gates the KOTOR-II-specific
  hooks from the KOTOR-I (VitaKotor) ancestors.

**ABI warning** (`CMakeLists.txt`): the current SDK/vitaGL/vitashark/mathneon are built **hardfp**,
so the loader itself links hardfp. The Android `armeabi-v7a` ABI is **softfp** (float args in integer
registers), so a runtime `.so` port ultimately needs a **softfp toolchain** (rebuild vitaGL & deps
with `-mfloat-abi=softfp`) to match float return values across the `.so` boundary (e.g.
`CallStaticFloatMethodV`). The skeleton still links hardfp; the authors explicitly defer the softfp
build to the runtime phase. (`SOFTFP_ABI=1` in vitaGL is the flag to use once that toolchain exists.)

**Memory** (`config.h`, `heap.c`, `bigalloc.c`):
- `ATTRIBUTE2=12` (extended 365 MiB MAIN) mandatory. Without it a large newlib heap fails at CRT
  init (`_sbrk_r` before `main()`).
- `_newlib_heap_size_user = 160 MiB`; `MEMORY_VITAGL_THRESHOLD_MB = 80` (what vitaGL must leave
  unclaimed — vitaGL claims "everything else" at init, so its threshold must be raised in step when
  newlib shrinks).
- **BigAlloc isolation** (`bigalloc.c`): allocations ≥ 256 KB jump to private `sceKernelAllocMemBlock`
  segments (8 MB each, up to 8, lazily committed), taken from the newlib budget. Prevents the 1 MB
  `bad_alloc`-death from fragmentation (largest block was halving every ~150 s). Budget is
  **from** newlib, not added.
- `.so` map at fixed addresses: `libkotor2` 0x98000000, `libc++_shared` 0x96000000, `libLzmaLib`
  0x94000000, `libminiz` 0x92000000, `libObbVfs` 0x90000000.

**Performance layers** (each A/B-tested on hardware, `docs/specs/PERFORMANCE.md`):
- **GL worker** (`gl_worker.c`): every `gl*` call is `-Wl,--wrap`-ed into a lock-free ring-buffer
  command stream, replayed on core 2 by a worker thread (vitaGL itself never touches the game
  thread). Sync calls (query results, `glGetIntegerv`-style) run inline. Generated wraps:
  `tools/gen_glw.py` + `cmake/glw_wraps.cmake`.
- **GL state filter** (`gl_state_filter.c`): repeated `glEnable`/binds/texture-unit calls dropped
  before Aspyr's GL→GXM shim (~5 ms/frame).
- **Vertex-program pool** (`gxm_patcher.c`): wraps `sceGxmShaderPatcherCreateVertexProgram` (also
  via `--wrap`) so variants unused for `GXMP_IDLE_FRAMES=30` frames are freed (4 MB pool), fixing
  long-session geometry spikes. `GXMP_SLOTS=8192` open-addressed index.
- **Native DXT** (`dxt_native.c`): DXT1/3/5 textures go to GPU compressed (8.9 → 3.3 s texture
  building). **GPU mipmaps** (`mip_gpu.c`): NPOT images rescaled with NEON, 16-bit conversion with
  NEON (1920x1200: 837 → 354 ms).
- **Contextless tunables** via files in `ux0:data/kotor2/`: `fps_cap.txt`, `ai_mode.txt`,
  `room_distance.txt`, `[vsync-ab]`, `[snd-gap]` A/B — a whole A/B harness readable from card.
- Audio: FMOD replaced (`audio_patch.c`, `audio_mp3.c`, `audio_ring.c`); Bink movies via embedded
  decoder (`bink_patch.c`); narrow OpenSL ES contract (`opensl_patch.c`); hardware MP3 with
  `sceAudiodec`; minimp3 fallback.

**Post-build check** (`tools/check_vitagl_build.sh`, run by CMake POST_BUILD): runs `nm` on the
eboot and fails if `invoke_splashscreen` is present (forgot `NO_SPLASHSCREEN=1`) or the custom
shader cache is linked without an explicit `KOTOR2_ALLOW_UNSAFE_SHADER_CACHE=1` allow flag. A cheap
way to keep build-time flag regressions visible.

**Packaging quirks**: `-Wl,-z,max-page-size=0x10000` — `vita-elf-create` appends ~4.5 KB of SCE
data into the slack between RX and RW segments; at the default 4 KB alignment that slack is one
page and the build fails with "Cannot allocate N bytes for SCE data at end of segment 0"; at 64 KB
the slack is 14× what SCE data needs. The VPK bundles edited GLSL shader chunks (`app0:shaders/`)
and `.txi` font metrics (`app0:fonts/`) served by the loader's `SDL_RWFromFile` hook, so the fixed
shaders (GXM TEXCOORD budget) and fonts always travel with the loader.

### FD_FIX vs rePatch Pitfall (9mm-vita)

FdFix and rePatch both hook the Vita's file/syscall layer. Using them together conflicts:
- Use FdFix when an Android game needs file-descriptor emulation
- Do NOT combine it with rePatch (asset replacement), which installs its own hooks at the same layer
- Symptom of conflict: hangs or crashes on file access at startup
