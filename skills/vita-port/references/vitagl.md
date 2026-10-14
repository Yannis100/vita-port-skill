# vitaGL: OpenGL on the Vita

Source: github.com/Rinnegatamante/vitaGL, read at commit `cdbba42` (2026-10-04) and re-checked
at `a85cb8d` (main, 2026-10-13), LGPL-3.0, no releases or tags (track HEAD). It translates GL calls to sceGxm. Everything here that is
tagged *(inferred)* was read from source but not run, because no Vita SDK was available when this
was written.

**The library you link may be older than GitHub HEAD.** `vdpm install vitaGL` gives a prebuilt
`libvitaGL.a` (a trial build reported r1488) and the matching `$VITASDK/arm-vita-eabi/include/vitaGL.h`.
Treat that installed header as the authority for names and signatures; use the repo for explanations.
If a function you read here is missing from the installed header, you are ahead of the package.

## Contents
1. Stale names to avoid
2. What it supports and what it does not
3. Build and link
4. Initialisation order and API
5. Memory model and sizing
6. Shaders and `libshacccg.suprx`
7. SDL2, GL4ES, EGL and loaders
8. Porting a GL game: checklist
9. Common problems

## 1. Stale names to avoid

Tutorials and LLM memory still use these. They were removed (checked in git history or the tree):

| Old | Now |
|---|---|
| `HAVE_SHARK=1/2` | removed 2021: the runtime shader compiler is always on |
| `vglEnableRuntimeShaderCompiler` | removed 2022 |
| `HAVE_GLSL_SUPPORT=1/2` | removed 2026-04: GLSL translator always on (some READMEs still cite it) |
| `vglSetVertexPoolSize` | `vglSetCircularPoolSize(uint32_t)`, default 32 MiB; circular pool on by default (`NO_CIRCULAR_POOL=1` disables) |
| `vglUseVram` | removed 2026-05 (memory rework); `vglUseVramForUSSE` remains |
| `vglSetupDisplayRenderTarget` | `vglSetupRenderTargetScenesNum(uint8_t display, uint8_t fbo)` |
| `VGL_MEM_SLOW` | `VGL_MEM_PHYCONT` |
| `vglDrawObjects`, `vgl*Pointer` family | need `ENABLE_LEGACY_PIPELINE=1`; `vglDrawObjects(mode, count, GL_TRUE)` is now `vglDrawObjects(mode, count)`, `vglVertexPointerMapped(ptr)` is now `vglVertexPointerMapped(size, ptr)` |
| `vglStartRendering()` / `vglStopRendering()` | `vglSwapBuffers(GL_FALSE)` |
| `SHADER_COMPILER_SPEEDHACK`, `CIRCULAR_VERTEX_POOL=2` | removed; DaedalusX64 replaced them with `CIRCULAR_POOL_SPEEDHACK=1` (2026-10-04) |
| `SHADER_CACHE_MAGIC` (as the FFP cache key) | `FFP_SHADER_CACHE_MAGIC`; `SHADER_CACHE_MAGIC` now keys the `HAVE_SHADER_CACHE` cache |
| Cg source passed to `glCreateShader(GL_VERTEX_SHADER)` | `GL_CG_VERTEX_SHADER_EXT` / `GL_CG_FRAGMENT_SHADER_EXT`; plain `GL_*_SHADER` now always means GLSL and goes through the translator (flycast-vita had to switch, 2026-04) |
| Raw `.gxp` passed to `glShaderBinary` | `vglShaderGxpBinary`; `glShaderBinary` expects vitaGL's serialized format (section 6) |
| `SAFE_MODE`, `SHADER_COMPILER` | do not exist; nearest are `SAFE_DRAW`, `SAFE_UNIFORMS`, `SAFE_ETC1` |

If the API in a port's old code does not exist, grep `source/vitaGL.h` in the vitaGL checkout.

## 2. What it supports and what it does not

- `glGetString`: GL_VERSION `"OpenGL ES 2.0 VitaGL"`, GLSL `"1.00 ES"`, renderer `"SGX543MP4+"`.
- **Fixed function** is complete enough for GL 1.x games: matrix stacks, 8 lights, fog, texenv incl.
  COMBINE/dot3, 7 user clip planes, `glBegin/glEnd` immediate mode, `GL_QUADS`,
  `glInterleavedArrays`, `glPushAttrib`. Display lists need `HAVE_DISPLAY_LISTS=1`. Fixed-function
  variants are compiled at runtime, so even FFP-only apps need `libshacccg.suprx`. Without
  `HAVE_HIGH_FFP_TEXUNITS=1` only 2 FFP texture units exist.
- **Shaders**: GLSL ES 1.00-style, Cg (`GL_CG_VERTEX_SHADER_EXT` / `GL_CG_FRAGMENT_SHADER_EXT`),
  or precompiled GXP (`vglShaderGxpBinary`; see section 6 for `glShaderBinary`). No geometry, tessellation or compute
  shaders, no transform feedback.
- **Not present** *(inferred from the proc table)*: `glTexImage3D`, `glTexStorage*`, `glFenceSync`,
  `glGetTexImage`, `glPrimitiveRestartIndex`, `glLogicOp`, `glBindFragDataLocation`,
  `glVertexAttribIPointer`, `glTexBuffer`, `glDrawArraysIndirect`, `glDrawBuffers` (one colour
  attachment, no MRT). `GL_FLAT` becomes smooth; instance divisor > 1 clamps to 1.
- **Limits**: max texture/renderbuffer/viewport 4096; cube map 1024; vertex uniform vectors 128;
  **fragment uniform vectors 16**; varyings 8; vertex attribs 16; texture units 16; shaders 2048,
  programs 1024. `glDrawArrays` / `glDrawArraysInstanced` take at most **49152 (0xC000) vertices**:
  they draw through one built-in index buffer of that size (`MAX_IDX_NUMBER`), and a larger count
  reads past it, giving garbage geometry with no log in a `NO_DEBUG` build (the vdpm package allocates
  the same 0x18000-byte buffers, checked 2026-10-14). `glDrawElements` uses your indices and has no
  such cap.
- **Texture formats native**: RGBA8, RGB888, RGB565, RGBA4444, RGB5A1, L8, A8, LA8, RG8, R8,
  RGBA16F (half only), P4/P8 palettes (mipmaps since 2026-10-07), DXT1/3/5, RGTC, PVRTC v1/v2, ETC1, YUV420 planar. Other
  formats convert on the CPU (slow). NPOT is advertised; mipmaps on NPOT textures are broken
  (upstream issue #24). Cubemap mip upload is level 0 only. Depth/stencil is not stored by default
  (`STORE_DEPTH_STENCIL=1` to read it back; costs speed; sample depth with `vglTexImageDepthBuffer`).
- `glReadPixels` is fast only on exact format matches; otherwise use `vglReadPixels` or
  `READBACKS_SPEEDHACK`.
- All GL calls must come from the thread that called `vglInit*`. `DEBUG_THREAD_SAFENESS=1` reports
  violations.

## 3. Build and link

```bash
git clone https://github.com/Rinnegatamante/vitaGL && cd vitaGL
export VITASDK=...            # SDK path
make NO_DEBUG=1 install       # installs libvitaGL.a + vitaGL.h under $VITASDK/arm-vita-eabi
```
Dependencies (each `make install`): `Rinnegatamante/math-neon` (libmathneon),
`Rinnegatamante/vitaShaRK` (libvitashark), `bythos14/SceShaccCgExt`. Or `vdpm install vitaGL
vitaShaRK SceShaccCgExt libmathneon taihen`. The vdpm vitaGL is built with `NO_DEBUG=1`.

Link line copied from the official samples (`glesgear`, `uniform_buffers`):
```
-lvitaGL -lstdc++ -lc -lm -lmathneon -lvitashark -lSceShaccCgExt -ltaihen_stub -lSceShaccCg_stub \
-lSceGxm_stub -lSceDisplay_stub -lSceCommonDialog_stub -lSceAppMgr_stub -lSceKernelDmacMgr_stub
```
Add `-lSceSysmodule_stub -lSceCtrl_stub -lSceAppUtil_stub` when used. Base CFLAGS in vitaGL:
`-O3 -ffast-math -mtune=cortex-a9 -mfpu=neon -mfp16-format=ieee`.

Build flags (full list in the vitaGL README; group by purpose):
- **Debug**: `LOG_ERRORS=1` (or `2` for file), `HAVE_SHARK_LOG=1` (shader compiler log via
  `glGetShaderInfoLog`), `HAVE_PROFILING`, `HAVE_DEBUGGER=1|2`, `DEBUG_THREAD_SAFENESS`,
  `DEBUG_GLSL_TRANSLATOR=1`, `DEBUG_GLSL_PREPROCESSOR=1`.
- **Compatibility**: `SOFTFP_ABI` (so-loader ports; whole SDK must be softfp), `HAVE_CUSTOM_HEAP`,
  `STORE_DEPTH_STENCIL`, `HAVE_HIGH_FFP_TEXUNITS`, `HAVE_DISPLAY_LISTS`, `SAFE_ETC1`, `SAFE_DRAW`,
  `SAFE_UNIFORMS`, `UNPURE_TEXFORMATS`, `UNPURE_TEXTURES`, `UNPURE_TEXCOORDS`,
  `ENABLE_LEGACY_PIPELINE`, experimental `HAVE_GLSL_TEXTURE_SIZE`, `HAVE_GLSL_UBOS`,
  `HAVE_FFP_SHADER_SUPPORT`, `HAVE_FIXED_ATTRIBUTES`.
- **Speed hacks (each can break rendering or crash; add one at a time and retest)**: `NO_DEBUG=1`
  (skips GL error handling, the usual first step), `DRAW_SPEEDHACK=1|2`, `BUFFERS_SPEEDHACK`,
  `INDICES_DRAW_SPEEDHACK`, `INDICES_SPEEDHACK` (breaks instancing), `MATH_SPEEDHACK`,
  `TEXTURES_SPEEDHACK`, `TEXTURE_UPLOADS_SPEEDHACK`, `SAMPLERS_SPEEDHACK`, `PRIMITIVES_SPEEDHACK`,
  `DEPTH_STENCIL_HACK`, `READBACKS_SPEEDHACK`, `CIRCULAR_POOL_SPEEDHACK`, `NO_TEX_COMBINER`.
- **Misc**: `NO_SPLASHSCREEN=1` (the boot splash is on by default; swaps are ignored while it
  runs), `HAVE_UNFLIPPED_FBOS`, `HAVE_WVP_ON_GPU`, `SHARED_RENDERTARGETS`, `HAVE_SHADER_CACHE`
  (path via `vglSetShaderCachePath`, default `ux0:data/shader_cache`), `HAVE_VERTEX_LAYOUT_CACHE`,
  `HAVE_TEXTURE_CACHE`, `SINGLE_THREADED_GC`, `HAVE_PTHREAD`, `USE_SCRATCH_MEMORY`,
  `PHYCONT_ON_DEMAND`, `NO_DMAC`, `NO_CIRCULAR_POOL`, `HAVE_VITA3K_SUPPORT`.

Real recipes: bc2_vita `SOFTFP_ABI=1 DRAW_SPEEDHACK=1`; rvgl `SOFTFP_ABI=1 HAVE_CUSTOM_HEAP=1
NO_DEBUG=1 SINGLE_THREADED_GC=1`. Current ones (2026-10): PCSX_AwO `HAVE_SHADER_CACHE=1 NO_DEBUG=1
READBACKS_SPEEDHACK=1 CIRCULAR_POOL_SPEEDHACK=1 DEPTH_STENCIL_HACK=1`; DaedalusX64
`READBACKS_SPEEDHACK=1 HAVE_GLSL_TEXTURE_SIZE=1 NO_DEBUG=1 HAVE_UNFLIPPED_FBOS=1 NO_TEX_COMBINER=1
HAVE_CUSTOM_HEAP=1 SINGLE_THREADED_GC=1 HAVE_FFP_SHADER_SUPPORT=1 DEPTH_STENCIL_HACK=1
CIRCULAR_POOL_SPEEDHACK=1 ENABLE_LEGACY_PIPELINE=1 NO_SPLASHSCREEN=1`; yoyoloader `DEPTH_STENCIL_HACK=1
SOFTFP_ABI=1 NO_DEBUG=1 SHARED_RENDERTARGETS=1 NO_SPLASHSCREEN=1 ENABLE_LEGACY_PIPELINE=1` (adding
`ENABLE_LEGACY_PIPELINE=1` fixed its black screen on the 2026-05 vitaGL).

Several ports build their own vitaGL with these flags instead of the vdpm package, sometimes from a
fork (PCSX_AwO uses a `vitaGL-pcsx-rearmed` checkout). Pin the vitaGL commit in the port's build
instructions, because HEAD changes weekly.

## 4. Initialisation order and API

```c
GLboolean vglInit(int legacy_pool_size);       // = vglInitExtended(pool, 960, 544, 0x1000000, 4x MSAA)
GLboolean vglInitExtended(int legacy_pool_size, int w, int h, int ram_threshold, SceGxmMultisampleMode msaa);
GLboolean vglInitWithCustomThreshold(int pool, int w, int h, int ram_thr, int cdram_thr,
                                     int phycont_thr, int cdlg_thr, SceGxmMultisampleMode msaa);
GLboolean vglInitWithCustomSizes(int pool, int w, int h, int ram_pool, int cdram_pool,
                                 int phycont_pool, int cdlg_pool, SceGxmMultisampleMode msaa);
void vglSwapBuffers(GLboolean has_commondialog);
void vglWaitVblankStart(GLboolean enable);     // vsync; eglSwapInterval also works
void vglSetupRuntimeShaderCompiler(shark_opt opt, int32_t fastmath, int32_t fastprecision, int32_t fastint);
void vglSetDisplayCallback(void (*cb)(void *framebuf));  // CPU overlay hook
GLboolean vglSwapResolution(int w, int h);     // queued, applied at next vglSwapBuffers
```

Order: tuning calls, `vglSetupRuntimeShaderCompiler`, `vglInit*`, `vglWaitVblankStart(GL_TRUE)`, GL
setup, then loop: draw, `vglSwapBuffers(GL_FALSE)`.

Call before `vglInit*`: `vglSetParamBufferSize`, `vglSetVDMBufferSize`, `vglSetVertexBufferSize`,
`vglSetUSSEBufferSize`, `vglSetFragmentBufferSize`, `vglSetupShaderPatcher`, `vglUseCachedMem`,
`vglSetupGarbageCollector`, `vglSetShaderCachePath`, `vglSetCircularPoolSize`. Also available:
`vglUseTripleBuffering`, `vglSetDisplayBufferCount`, `vglUseExtraMem`, `vglUseLowPrecision`,
`vglSetupScratchMemory`, `vglMemFree(type)`, `vglMemTotal(type)`.

`legacy_pool_size` is the per-frame pool for `glBegin/glEnd`; pass 0 if unused (samples use 0x100000
to 0x800000 otherwise). `SHARK_OPT_*`: SLOW, SAFE, DEFAULT, FAST, UNSAFE; default FAST.

A real init sequence (PCSX_AwO `plugins/gpu_vita_ctr/native_gpu.c`, 2026-10, read not run). It
runs on a dedicated render thread, so every later GL call must come from that thread too:

```c
vglSetupRenderTargetScenesNum(2, 2);                  /* display, fbo scenes per frame */
vglSetShaderCachePath("ux0:data/<app>/shader_cache"); /* needs HAVE_SHADER_CACHE=1 */
vglUseLowPrecision(GL_TRUE);                           /* translator maps float->half, int->short */
vglSetupRuntimeShaderCompiler(SHARK_OPT_UNSAFE, GL_TRUE, GL_TRUE, GL_TRUE);
vglInitExtended(0, w, h, 24 * 1024 * 1024, SCE_GXM_MULTISAMPLE_4X);
```

`vglUseLowPrecision` is a speed trade: a half float has 11 significant bits, so normalized texture
coordinates on textures 1024 texels or wider, and large positions, lose accuracy. Test it per game.

Less-known calls worth knowing (all in the vdpm header unless noted):
- **Zero-copy buffers**: allocate with `vglMalloc` (GPU-mapped), fill on the CPU, attach with
  `vglBufferData(target, ptr)` instead of `glBufferData` (no copy), free with `vglLazyFree` (waits
  until the GPU is done). flycast-vita builds its per-frame vertex and index lists this way and
  uses 32-bit indices on the Vita to skip a conversion pass.
- **Textures you fill yourself**: `vglGetTexDataPointer`, `vglOverloadTexDataPointer`, and
  `vglSetupTexture(target, data, SceGxmTextureFormat, SceGxmTextureType, w, h, mips)` (added
  2026-10-06; not yet in the vdpm header checked 2026-10-14) to wrap existing GXM-format memory as a
  GL texture.

Minimal triangle. Build-verified 2026-10 (compiles and links with the link line in section 3 against
the vdpm `vitaGL` package, GCC 15.2, and passes `vita-elf-create`); **never run on a console**, so
treat shader behaviour as untested:

```c
#include <vitaGL.h>
static const char *vs = "attribute vec3 position; attribute vec4 color; varying vec4 vcol;"
                        "void main(){ gl_Position = vec4(position,1.0); vcol = color; }";
static const char *fs = "precision mediump float; varying vec4 vcol; void main(){ gl_FragColor = vcol; }";
static const float pos[] = {-0.5f,-0.5f,0, 0.5f,-0.5f,0, 0,0.5f,0};
static const float col[] = {1,0,0,1, 0,1,0,1, 0,0,1,1};
int main(void) {
  vglInitExtended(0, 960, 544, 0x1000000, SCE_GXM_MULTISAMPLE_NONE);
  vglWaitVblankStart(GL_TRUE);
  GLuint v = glCreateShader(GL_VERTEX_SHADER), f = glCreateShader(GL_FRAGMENT_SHADER), p = glCreateProgram();
  glShaderSource(v,1,&vs,NULL); glCompileShader(v);
  glShaderSource(f,1,&fs,NULL); glCompileShader(f);
  glAttachShader(p,v); glAttachShader(p,f);
  glBindAttribLocation(p,0,"position"); glBindAttribLocation(p,1,"color");
  glLinkProgram(p); glUseProgram(p);     // GLSL really compiles at link (POSTPONED mode)
  for (;;) {
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glEnableVertexAttribArray(0); glEnableVertexAttribArray(1);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,0,pos);
    glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,0,col);
    glDrawArrays(GL_TRIANGLES,0,3);
    vglSwapBuffers(GL_FALSE);
  }
}
```

## 5. Memory model and sizing

Pools (`vglMemType`): `VGL_MEM_VRAM` (CDRAM), `VGL_MEM_RAM` (user RW), `VGL_MEM_PHYCONT`,
`VGL_MEM_BUDGET` (CDLG), `VGL_MEM_EXTERNAL` (newlib heap). Allocation order for GPU-side
allocations is VRAM, RAM, PHYCONT, CDLG, newlib; for CPU-mapped it is RAM, PHYCONT, CDLG, VRAM,
newlib. The newlib fallback is used only while `vglUseExtraMem(GL_TRUE)` (default).

Sizing: with `vglInitExtended` the **RAM pool = free user memory at init minus `ram_threshold`**, so
`ram_threshold` is what you leave for the newlib heap, stacks and libraries. Order of operations:
decide the newlib heap (`_newlib_heap_size_user`) first, then set `ram_threshold` so the sum fits the
budget in `references/runtime.md`. CDRAM and PHYCONT pools take all free memory minus their
thresholds (0 by default). The uncached RAM pool is capped at 0xC800000 (200 MiB).

Defaults worth changing: `vglInit` forces 4x MSAA (pass `SCE_GXM_MULTISAMPLE_NONE` to save VRAM);
the circular pool is 32 MiB; triple buffering is on; shader patcher buffers 1 MiB each.

Real values: bc2_vita newlib 192 MiB + `vglInitWithCustomThreshold(0,960,544,8<<20,0,0,0,4x)` +
`ATTRIBUTE2=12`; Northfear's SDL `vglInitExtended(0,960,544,12 MiB,msaa)`.

## 6. Shaders and `libshacccg.suprx`

- vitaGL compiles shaders **at runtime** through vitaShaRK, which wraps Sony's `libshacccg.suprx`
  (and `SceShaccCgExt`). The module must be on the console at `ur0:data/libshacccg.suprx`
  (`shark_init` also tries `ur0:data/external/libshacccg.suprx`). It is Sony's file: **never
  bundle it**; the end-user README must tell users to extract it themselves (community guide:
  cimmerian.gitbook.io/vita-troubleshooting-guide/shader-compiler/extract-libshacccg.suprx).
  Without it `glCompileShader` sets `GL_INVALID_OPERATION` and you get a black screen or an exit.
- **Semantic binding mode** defaults to `VGL_MODE_POSTPONED`: GLSL is compiled at `glLinkProgram`;
  `glCompileShader` is a no-op and `GL_COMPILE_STATUS` is always true, so errors surface at link.
  `vglSetSemanticBindingMode(VGL_MODE_SHADER_PAIR | VGL_MODE_GLOBAL)` and `vglAddSemanticBinding`
  tune varying-to-semantic mapping.
- **GLSL translator** (`source/utils/glsl_utils.c`): comments out `#version`/`#extension`, strips
  `precision`, handles `attribute`/`varying`, `gl_FragColor`, `texture2D`, `textureCube`,
  `texture2DLod`, `dFdx`, `gl_PointCoord`, `gl_FragCoord`, `gl_FrontFacing`, instancing,
  `gl_ClipDistance`, centroid. It has no handling of `in`/`out`/`layout`, `texture()`,
  `texelFetch` *(inferred)*: **rewrite GLSL 1.30+ shaders to GLSL ES 1.00 style** (`attribute`,
  `varying`, `texture2D`, `gl_FragColor`). `textureSize` exists only in a vitaGL built with
  `HAVE_GLSL_TEXTURE_SIZE` (mip 0 only); the vdpm package is not. Fragment shaders have only 16
  uniform vectors.
- Translator quirks (verified in `source/shaders/glsl_translator_hdr.h` at `a85cb8d`): the preamble
  `#define`s these identifiers, so **a shader variable or function with one of these names breaks**:
  `s`, `t`, `st`, `ts`, `ss`, `tt` (swizzles), `matrix`, `Matrix`, `sampler`, `vgl`, `mod`, `atan`,
  `inversesqrt`, `texture2D`, `samplerCube`, and the `vec*`/`ivec*`/`bvec*`/`mat*` types. A loop
  counter named `s` or `t` is the usual victim; rename it. With `vglUseLowPrecision(GL_TRUE)`,
  `float*` become `half*` and `int*` become `short*` as well. `mod` maps to `vgl_mod` (GLSL
  semantics, `x - y*floor(x/y)`), no longer to `fmod`. `glsl_inject_mul` rewrites `*` between
  matrices/vectors. The text is scanned with plain `strstr` for `attribute`/`varying` without
  skipping comments, so those words in a shader comment can confuse it. Keep shader text lean and
  comment-free in the shipped copy.
- Recently added to the translator (2026-10-01..07, HEAD only until the vdpm package catches up):
  `gl_ClipDistance`, `not()`, `matrixCompMult`, boolean `equal`/`notEqual`, `texture2DProjLod`,
  `textureCubeLod`, fixed comparison ops and negative `mod`. On an older vitaGL these fail, so
  check the installed version before blaming the shader.
- To avoid first-use stutter use `HAVE_SHADER_CACHE` (xxHash file cache) or precompile GXP. Cache
  layout: `<root>/v<SHADER_CACHE_MAGIC>/{v,f}/00..FF/`, root `ux0:data/shader_cache/<TITLEID>`
  unless `vglSetShaderCachePath` (before `vglInit*`) overrides it. The first boot creates 512
  directories. The FFP cache is always `ux0:data/shader_cache/v<FFP_SHADER_CACHE_MAGIC>/`. Bumping a
  magic invalidates old entries; tell users that deleting the folder is safe.
- **Precompiled GXP**: load a raw `.gxp` with `vglShaderGxpBinary(1, &shader, data, len)`.
  `glShaderBinary` does not take a raw GXP: it expects vitaGL's serialized form (a `uint32` count of
  matrix uniforms plus their offsets, plus one sampler-count byte when vitaGL is built with
  `HAVE_GLSL_TEXTURE_SIZE`, then the GXP), which is what `vglGetShaderBinary` writes. PCSX_AwO
  makes `glShaderBinary` work by prepending four zero bytes to each psp2cgc `.gxp` in its embed
  script. vitaWolfen moved from `glShaderBinary` to `vglShaderGxpBinary` in its 2026-09
  VitaSDK update. A shader-binary cache built with `vglGetShaderBinary` (fahrenheit-vita) reloads
  with `glShaderBinary`.
- Precompiled GXP needs Sony's `psp2cgc` (`-profile sce_vp_psp2` / `sce_fp_psp2`), which is not
  part of VitaSDK and is a legal grey area *(unverified)*; the runtime compiler is the mainstream
  path. Open replacements exist (`frangarcj/open-shacccg`, `psp2spvc`), *unverified*. Keep the Cg
  sources in the repo so others can rebuild without your binaries.
- **Writing fast fragment shaders for USSE** (from DaedalusX64's 2026-10-12 rewrite of its
  post-processing shaders): cut texture fetches first (its CRT filter went from 6 to 2); replace
  `if`/`?:` with `step`/`lerp`/`saturate`; replace `pow(x, 2.0)` with `x*x` and `pow(v, 0.25)` with
  `sqrt(sqrt(v))`; multiply by reciprocal constants instead of dividing by a resolution uniform;
  fold per-pixel colour-matrix work into uniforms computed once on the CPU (its colour-blindness
  filter became two `dot`s); use `short` for integer pixel math (`(short)floor(x) & 1`).
- Debug: build vitaGL with `HAVE_SHARK_LOG=1` and `LOG_ERRORS=1`, read `glGetShaderInfoLog`,
  dump translated source with `DEBUG_GLSL_TRANSLATOR=1`.

## 7. SDL2, GL4ES, EGL and loaders

- **Stock `sdl2` does not use vitaGL.** 2D uses its own GXM renderer
  (`src/render/vitagxm`). Its GL option (`-DVIDEO_VITA_PVR=ON`) uses gl4es4vita on Sony's PVR_PSP2
  modules, and `-DVIDEO_VITA_PIB=ON` is a separate GLES2 path.
- **SDL2 + vitaGL**: `vdpm install sdl2_vitagl` (patched SDL2 with a vitaGL backend), or Northfear's
  fork branch `vitagl` with `-DVIDEO_VITA_VGL=ON`. That backend calls `vglInitExtended(0,960,544,
  12 MiB,msaa)` once, `SDL_GL_GetProcAddress` returns `vglGetProcAddress`, and `SwapWindow` calls
  `vglSwapBuffers(GL_TRUE)`. Because it picks the init values for you, you may need to patch or
  fork it to control pool sizes. SDL 1.2 + vitaGL: `Rinnegatamante/SDL-Vita`, branch `sdl12_gl`.
- **GL4ES** (`SonicMastr/gl4es4vita`) is an alternative stack on the PVR driver, not layered on
  vitaGL. No GL4ES-over-vitaGL setup was found *(unverified)*. Do not mix both in one binary.
- **EGL** in vitaGL is a stub (`eglGetDisplay`, `eglSwapBuffers`, `eglSwapInterval` exist; context,
  surface and config calls are fakes). Fine for engines that only need those.
- **Function loaders**: vitaGL exports plain `gl*` symbols and a 380-entry proc table.
  `vglGetProcAddress` / `eglGetProcAddress` answer only names starting `gl`, `egl`, `vgl`, strip a
  trailing `EXT`/`ARB`/`OES`, and return NULL for unknown names. For glad/GLEW, generate a GLES2
  loader and point it at `vglGetProcAddress` *(inferred, not verified in a port)*; simpler still is
  to link vitaGL's symbols directly. Android so-loaders map imported `gl*`/`egl*` straight to vitaGL.

## 8. Porting a GL game: checklist

1. Decide FFP, GLES2 shaders or Cg; run `audit_source.py` for GL 3+ features.
2. Rewrite GLSL 3.x to ES 1.00 style; drop `layout`, `in/out`, `texture()`; check the fragment
   uniform budget.
3. Bind attribute locations (`glBindAttribLocation`) before link.
4. Remove or emulate 3D textures, MRT, `glTexStorage`, `glDrawBuffers`, fences, geometry shaders.
5. Split `glDrawArrays` calls over 49152 vertices. vitaGL offsets the vertex streams by `first`, so
   chunks of 0xC000 (a multiple of 2 and 3) keep `GL_TRIANGLES`/`GL_LINES` intact. Whole-map
   terrain batches and full particle buffers are the usual offenders; grep every `glDrawArrays`
   count that grows with map or effect size.
6. Choose texture formats from the native list; pre-convert assets (PVRTC/DXT) offline for speed.
7. Size memory (section 5), pick MSAA, and set the circular pool.
8. First build with `LOG_ERRORS=1`; once it renders, switch to `NO_DEBUG=1` and add speed hacks
   one at a time.
9. Put the `libshacccg.suprx` requirement in the README.

## 9. Common problems

| Symptom | Cause |
|---|---|
| Black screen after updating vitaGL (port uses `vglDrawObjects`/`vgl*Pointer`) | rebuild vitaGL with `ENABLE_LEGACY_PIPELINE=1` (yoyoloader fix, 2026-05) |
| Cg shaders fail to compile after updating vitaGL | create them with `GL_CG_VERTEX_SHADER_EXT` / `GL_CG_FRAGMENT_SHADER_EXT`; `GL_*_SHADER` now means GLSL |
| Crash or garbage in `glShaderBinary` with a psp2cgc `.gxp` | use `vglShaderGxpBinary`, or prepend the vitaGL header (section 6) |
| GLSL compile error on a variable named `s`, `t`, `matrix`, `sampler` | translator preamble macros (section 6); rename it |
| Black screen or exit | `libshacccg.suprx` missing; `vglInit*`/`vglSwapBuffers` missing; shader compile failure hidden by `NO_DEBUG`; RAM pool too big/small for the heap |
| Shader error only at link | POSTPONED mode (expected); read the shark log |
| Out of memory | big textures + MSAA in CDRAM; large `legacy_pool_size`; GC list overflow (16384); exhausted shader/program handles |
| Garbled or missing terrain / large meshes, no GL error | `glDrawArrays` count over 0xC000 reads past vitaGL's index buffer (section 2); split the draw |
| Shader using `textureSize` fails at link | vitaGL handles it only when built with `HAVE_GLSL_TEXTURE_SIZE` (the vdpm package is not: no `glsl_handle_tex_size`); pass the size as a uniform or constant |
| Slow texture upload/readback | CPU format conversion; use native formats or `vglReadPixels` |
| Broken mipmaps | NPOT mip chains (issue #24); use POT or generate mips offline |
| `GL_INVALID_ENUM` spam | unsupported state; usually harmless |
| `GL_FIXED` attributes fail | need `HAVE_FIXED_ATTRIBUTES` |
| Unused attribute locations shift | unused attributes are dropped and remapped |
| Install error `0x8010113D` | LiveArea PNGs not indexed (not a vitaGL issue) |
| Link errors on vitaGL symbols | missing `-lstdc++`, `-lmathneon`, `-lvitashark`, `-lSceShaccCgExt`, or wrong order |
