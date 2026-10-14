# Java / libGDX games: TeaVM C backend

The Vita has no JVM. The working route is ahead-of-time translation: TeaVM's C backend turns the
reachable Java bytecode into C11, a hand-written libGDX backend replaces the desktop one, and VitaSDK
compiles the result into one static ELF. Reference implementation: **STSPSVITA**
(github.com/mmrmagno/stspsvita, MIT, pre-alpha; blog: marc-os.com/blog/stspsvita-building-a-slay-the-spire-vita-pipeline).
It ports Slay the Spire (libGDX 1.9.5, 2D, GL 2.0). Everything below was read from that repo at commit
`692473a` (2026-08-15); it was not built or run while writing this file.

**TeaVM versions.** STSPSVITA pins **0.15.0**. The current release is **0.16.0** (2026-10-02), whose C
backend gained full reflection: method and constructor reflection with invocation, annotations,
generic type info, `Class.forName`, `Class.newInstance`, array reflection, `java.lang.reflect.Proxy`.
It also added `synchronized` methods, `String.intern` and `ClassLoader.getResourceAsStream`, and fixed
coroutine (fiber) and vtable generation bugs plus NIO buffer/path and `RandomAccessFile`
non-conformances (release notes: github.com/konsoletyper/teavm/releases/tag/0.16.0). Start new ports
on 0.16. The STSPSVITA runtime patches (section 5) are anchored to 0.15 output: re-check every anchor
on 0.16, and drop the reflection shims that 0.16 makes unnecessary. Nobody has published a Vita build
on 0.16 yet *(as of 2026-10-06)*.

## Contents
1. When this route fits
2. Porting limitations (worked example: Warsmash)
3. Architecture
4. TeaVM setup and the classlib gaps
5. Runtime patches the generated C needs
6. The libGDX backend
7. Native side: CMake, memory, startup
8. Assets, packaging and legal model
9. Debugging
10. Effort and triage checklist

## 1. When this route fits

| Fits | Does not fit (without a large rewrite) |
|---|---|
| libGDX on GL 2.0 / GLES2, 2D or light 3D | GL 3.x (`Gdx.gl30`, GLSL 330+, texture arrays, integer textures) |
| Single-threaded game logic (async helpers can become fibers) | Real parallelism needed for performance |
| Reflection over classes known at build time (0.16+; 0.15 had fields only) | Reflection over classes chosen at run time from data (plugin systems, XStream-style deserializers) unless every candidate is kept by the reflection policy |
| Plain `java.io` file access | AWT/Swing/ImageIO (`BufferedImage`), `FileChannel`/mmap, JNI libraries without a C equivalent |
| Java heap + textures within ~365 MiB (`ATTRIBUTE2=12`) | Large 3D worlds whose live heap alone nears 200 MiB |

A libGDX game also needs every native libGDX extension it uses (FreeType, Box2D, Bullet) rebuilt for
Vita and bound through TeaVM `@Import` instead of JNI. Scan the jar or source before committing:
`audit_source.py` flags AWT, ImageIO, reflection, threads, NIO channels, JNI and `Gdx.gl30` in `.java` files.

### Choosing between the AOT routes

TeaVM is not the only ahead-of-time route. A port plan should name the route it picked **and** say
why it beat the others for this game, because the trade-offs differ on licence, threads and how much
libGDX backend already exists. *(Clearwing and SwitchGDX facts read from their GitHub READMEs and
repo metadata on 2026-10-06; neither has been built for the Vita by anyone known.)*

| | TeaVM C backend | Clearwing VM | Native rewrite |
|---|---|---|---|
| Output | C11 | C++20 | your own C/C++ |
| Licence of the tool/runtime | Apache-2.0 (STSPSVITA backend: MIT) | GPL-2.0 (SwitchGDX backend also GPL-2.0); check for a linking exception before shipping non-GPL code | whatever you choose |
| Vita precedent | STSPSVITA (Slay the Spire, pre-alpha) | none; published targets are Switch homebrew, Xbox/UWP and desktop, all 64-bit, so 32-bit ARM is untested | many C/C++ ports |
| libGDX backend | STSPSVITA's, GL 2.0 only, written for libGDX 1.9.5 | SwitchGDX: mature (Mindustry, Pixel Wheels, Shattered Pixel Dungeon on Switch), FreeType/Box2D/Bullet/Controllers, no GL30 | none: reimplement the parts you use |
| Threads | cooperative fibers on one OS thread | real threads ("basic threading") | real pthreads |
| Reflection | full in 0.16 if kept by the reflection policy | "GDX reflection" supported | n/a |
| Java class library | broad, Java 17+ bytecode works | "Java 7 runtime with Java 8 features": newer APIs may be missing | n/a |
| Native deps to build for Vita | none beyond the backend's (FreeType, OpenAL...) | zlib, zziplib, libffi (only zlib ships with VitaSDK) | yours |

How to choose:
- **TeaVM** when you want the only route with a Vita precedent and a permissive licence, and the game
  can live on one OS thread.
- **Clearwing** when the game depends on real parallel threads or on libGDX modules SwitchGDX already
  binds, and a GPL-2.0 build is acceptable. Budget a first spike just to get its runtime (libffi,
  zziplib, C++20 threads) working on 32-bit ARM.
- **Native rewrite** when the Java code is small, uses little of libGDX, or both AOT spikes fail.
- Whatever you pick, make the first milestone a spike on the riskiest unknown of *that* route, and
  record the alternatives you rejected and why.

## 2. Porting limitations (worked example: Warsmash)

STSPSVITA proves the pipeline for a 2D GL 2.0 game. Each row below is something it does **not**
provide, so a game that needs it costs real work on top of the pipeline. The counts come from
Warsmash (github.com/Retera/WarsmashModEngine: a Warcraft III engine in Java, libGDX 1.12, LWJGL,
AGPL-3.0, ~2,100 Java files), measured with `audit_source.py` and grep on 2026-10-06.

| Area | STSPSVITA provides | What a GL 3 / 3D game needs (Warsmash) | Remedy and cost |
|---|---|---|---|
| GL API | Generated `GL20` bindings only (`VitaGL20.java`) | ~400 `Gdx.gl30`/`GL30` references; the calls are mostly VAOs (vitaGL has them), plus `R16F`, `RGBA_INTEGER`, `SRGB8_ALPHA8` textures, `GL_TEXTURE_BASE_LEVEL`, framebuffers | Generate a `GL30` binding limited to what the installed `vitaGL.h` declares; rewrite callers of the rest. vitaGL has no `GL_TEXTURE_BASE_LEVEL`/`MAX_LEVEL` |
| Shaders | GLSL ES 1.00 | ~12 shaders at `#version 330 core` / `450 core`; terrain uses `sampler2DArray`, `glTexImage3D` and `texelFetch` (bone matrices from a texture) | Rewrite each shader to ES 1.00; replace texture arrays with atlases or per-layer textures, `texelFetch` with `texture2D` on texel centres or uniform arrays. Days to weeks |
| Image loading | PNG/JPG decoded in C (`stb_image` behind `@Import`), DDS | `BufferedImage`/`ImageIO` in ~150 places, BLP through an ImageIO plugin (`blp-iio-plugin.jar`) | AWT does not exist under TeaVM. Decode in C behind an `@Import` (STSPSVITA pattern) or in plain Java into a byte array, and return a libGDX `Pixmap` |
| Desktop-only Java | Small stub classes on the classpath (Steamworks, Discord, LWJGL, log4j) | AWT/Swing in 33 files (map/model editors, dialogs); sockets in 31; `FileChannel` in 21 | Stub or exclude the editors and networking (single player only); replace `FileChannel`/mmap archive reads with `RandomAccessFile` or whole-file `byte[]` |
| Threads | Not needed (one loop, fibers for async helpers) | `new Thread` for networking only | Fine for single player. Any CPU-parallel work runs serially on fibers |
| Libraries | gson (stubbed), libGDX core | Guava, commons-compress, ANTLR 4 runtime (JASS parser), gdx-freetype, gdx-box2d | Pure-Java libraries must pass through TeaVM: each adds code size and may hit classlib gaps. JNI-backed ones (FreeType, Box2D) need the C library built for Vita plus `@Import` bindings; STSPSVITA did this for FreeType only |
| Reflection | Field reflection fed by a manifest (0.15) | Constructor reflection in audio loading, a few `newInstance` calls | Supported in TeaVM 0.16 when the classes stay reachable; on 0.15 use factories |
| Memory | 2D card game: ~16 MiB live Java after GC, 112 MiB fixed Java heap | 3D models, terrain, unit simulation, WC3 textures | Unknown until measured. The TeaVM heap is fixed at boot inside the newlib heap, so Java heap + native + vitaGL pools must fit ~365 MiB. Measure the desktop live heap after a full GC in the largest map, then add texture memory |
| Java level | Java 8 game bytecode | Java 17 source | TeaVM translates bytecode, so the language level matters only for classlib coverage; check problems in the transpile report |
| Licence | MIT tools; commercial jar never shipped | AGPL-3.0 | A Warsmash VPK may be shipped with its corresponding source; game data stays user-supplied |

**Reading the table.** A row is cheap when the game avoids it, and expensive when the game's core
depends on it. For Warsmash, the GL 3 and shader rows hit the renderer core, image loading hits
every texture, and memory is a risk that only hardware can settle: weeks of work, with a real chance
that the 3D working set does not fit. For a 2D GL 2.0 libGDX game, most rows are empty and the
STSPSVITA pipeline is close to reusable.

**General limits of the route** (any Java game):
- No JIT: all code is AOT C, no runtime class loading or bytecode generation (`ClassLoader.defineClass`,
  ASM/ByteBuddy, scripting engines such as Nashorn/Rhino/Groovy).
- One OS thread: Java threads are fibers, so a blocking read stalls rendering.
- The Java heap is a fixed malloc at boot; it competes with native code and vitaGL for the same RAM.
- GC pauses on a Cortex-A9 are visible; size the heap so young collections stay rare.
- JNI does not exist: every native library becomes C built with VitaSDK plus `@Import` glue.
- Only what vitaGL implements is available, whatever libGDX version the game uses.

## 3. Architecture

Four modules (STSPSVITA layout):

| Module | Role |
|---|---|
| `pipeline/` (Python) | verify the input jar by hash, extract it, convert assets (DDS, audio, fonts), generate LiveArea art |
| `backend/` (Java) | the Vita libGDX backend (`VitaApplication`, `VitaGraphics`, `VitaGL20`, `VitaInput`, `VitaAudio`, `VitaFiles`/`VitaFileHandle`, `VitaPreferences`) plus `stubs/`: replacement classes for desktop-only dependencies |
| `transpiler/` (Gradle, Java 17+) | TeaVM harness: classpath = stubs → backend → game jar, runs the C backend, then patches the generated C |
| `native/` (CMake, VitaSDK) | `main.c` (memory, clocks, vitaGL init, log redirect), `glue/*.c` implementing every `@Import`, VPK packaging |

**Classpath shadowing is the main porting tool.** Stub classes with the same fully qualified names as
the desktop-only libraries (Steamworks, Discord RPC, LWJGL, log4j, gson internals) sit earlier on the
classpath than the game jar, so TeaVM links the stubs and tree-shakes the desktop code away. No game
bytecode is edited. Stubs that are pure Java reimplementations (libGDX `Matrix4`, `BufferUtils`,
`Gdx2DPixmap`, FreeType) replace JNI-backed originals.

## 4. TeaVM setup and the classlib gaps

- **Pin the TeaVM version** (STSPSVITA: `org.teavm:teavm-{core,tooling,classlib,interop}:0.15.0`; use
  `0.16.0` for new work). The C
  backend changes quickly and the runtime patches in section 5 are anchored to that release's output.
- Driver (`BuildVita.java`): `TeaVMTool` with `setTargetType(TeaVMTargetType.C)`, `setMainClass(<launcher>)`,
  `setOptimizationLevel(ADVANCED)`, `setMinHeapSize == setMaxHeapSize` (see section 7), a custom
  `ClassHolderTransformer`, and a `URLClassLoader` that adds the game jar. Fail the build when
  `getProblemProvider().getSevereProblems()` is non-empty; print them with `TeaVMProblemRenderer`.
  The transpile JVM needs about `-Xmx4g` for ~7k classes.
- **Missing JDK methods**: add them with a `ClassHolderTransformer` that injects bodies into classlib
  classes by name (`ClasslibShims.java`): `Class.getResource → null`, `Locale.getDefault(Category)`,
  `Charset.toString`, retarget `java.util.Scanner` to a small replacement class.
- **Reflection**: on **0.16** the C backend supports method, constructor and field reflection,
  `Class.forName`, `newInstance` and `Proxy`. The classes and members must still be kept by TeaVM's
  reflection policy, or tree-shaking removes them; the policy API gained a `namedEither` predicate in
  0.16. On **0.15** (STSPSVITA) only field reflection exists: `getDeclaredMethods` and
  `getDeclaredConstructors` crash codegen if reachable, so its shims return empty arrays, and
  `Class.newInstance()` is redirected to a registry of `Type::new` factories (`NewInstanceRegistry`).
  Either way, field metadata for serializers can come from a `ReflectionSupplier` registered via
  `META-INF/services/org.teavm.classlib.ReflectionSupplier`, fed by a manifest generated from the jar
  (`pipeline/typemanifest.py` lists the classes gson touches). *(The 0.16 policy API was read from the
  release notes only; check its docs before writing one.)*
- **Threads**: TeaVM's C runtime gives green-thread **fibers** on one OS thread. `new Thread` and
  `synchronized` blocks work cooperatively (`synchronized` *methods* need 0.16), but a blocking read or long loop stalls every "thread", including
  the render loop. Treat the game as single-threaded.
- **Natives**: `@Import(name = "c_symbol")` on a `static native` method calls C directly; `@Include("x.h")`
  makes each calling TU include the prototype header. Pass only primitives and `org.teavm.interop.Address`.
- **NIO buffers**: stock TeaVM 0.15 cannot expose a direct buffer's malloc address, so the backend uses
  heap-array buffers and passes `Address.ofData(array)`. Arrays handed to GL calls that read later
  (client-side vertex arrays) must stay referenced until the frame ends, or the moving GC relocates them.

## 5. Runtime patches the generated C needs

STSPSVITA applies these with an idempotent, anchor-based script after every transpile
(`tools/vita_patch_runtime.py`). Port it rather than rediscovering the bugs:

| Patch | Why |
|---|---|
| Define `TEAVM_PSP=1`, `TEAVM_UNIX=0` under `TEAVM_VITA` in `definitions.h` | TeaVM's homebrew path: malloc heap (no mmap), setjmp fibers, `sceKernelLibcTime` |
| `fiber.c`: include `<psp2/kernel/threadmgr.h>` instead of `<pspkernel.h>` | PSP header does not exist in VitaSDK |
| `uchar.h`: key the shim on `TEAVM_VITA`, add `<stdint.h>` | newlib has no C11 `<uchar.h>`; without it every `u""` literal breaks |
| `file.c`: enable the POSIX branch for Vita and normalize `ux0:` / `app0:` paths | file IO is otherwise undefined with `TEAVM_UNIX=0` |
| `core.h` `TEAVM_ARRAY_DATA` and `reflection.c`: fixed data offset instead of aligning the absolute address | on 32-bit, `long[]`/`double[]` data shifts by 4 bytes after the compacting GC moves an array |
| `arrayclass.c`: 8-byte-align the dynamic class pool | class pointers are packed `>>3`; misaligned slots break array clone and `getComponentType` |
| `time.c`: `currentTimeNano` from `sceKernelGetProcessTimeWide()` | the PSP path has 1-second resolution, so frame delta is 0 and animations freeze |
| `Float.toString` via `snprintf("%.9g")` | the stock implementation overran a buffer on some values |
| GC pause timing (optional) | logs pauses ≥100 ms with heap context |

The last game-specific ones (null guards, controller glyphs) show the general rule: patch the
generated C or shadow the class; never ship modified game bytecode.

## 6. The libGDX backend

- `VitaApplication` owns the loop: input poll → `listener.render()` → audio refill → swap. Set
  `glViewport` to the full framebuffer before the first render (LWJGL does this; some games rely on it).
  Report `ApplicationType.Desktop` if the game's platform branches expect it.
- `VitaGL20` is **generated** (`tools/gen_gl.py`) from libGDX's `GL20` interface with `javap`: each
  method becomes an `@Import` of the same-named GL symbol (vitaGL on Vita, libGL in the host harness).
  The singular convenience calls (`glGenTexture`, `glDeleteBuffer`, …) are not GL entry points and go
  to C wrappers. String-returning calls are hand-written. A GL 3 game would need the same for `GL30`,
  limited to what vitaGL implements (VAOs yes; texture arrays, integer textures, `texelFetch` no).
- Input: SceCtrl and SceTouch sampled in C, exposed as polling natives; IME through `SceIme`.
- Audio: OpenAL-soft + libvorbisfile (`vdpm` packages), streamed music refilled once per frame.
- Files: `FileHandle` resolved to absolute paths up front, because the classpath branch needs
  `Class.getResource`. Assets at `app0:/assets` or, for a slim VPK, `ux0:data/<app>/assets`.
- Preferences and saves under `ux0:data/<app>/` in the desktop file formats, so PC saves copy across.

## 7. Native side: CMake, memory, startup

- Compile exactly the files listed in TeaVM's `all.txt`, not a glob: dead generated files reference
  bodies that were never emitted.
- Do not add `-I` on the generated directory: TeaVM names headers `time.h`, `string.h`, `file.h` and
  would shadow libc. Force-include `uchar.h` and `classes/java/lang/Class.h`
  (`"SHELL:-include <file>"` so CMake does not merge the repeated flags).
- GCC 15 errors on pre-C23 implicit conversions in generated code; add
  `-Wno-error=incompatible-pointer-types -Wno-error=int-conversion -Wno-error=implicit-function-declaration`
  and `-fno-strict-aliasing`.
- Rename TeaVM's `main` on the generated sources only (`COMPILE_DEFINITIONS main=<app>_java_main`) so
  `main.c` runs clocks, vitaGL init, input and audio init before the Java world starts.
- **Memory** (STSPSVITA after device tuning): `ATTRIBUTE2=12`; `_newlib_heap_size_user = 240 MiB`; TeaVM
  heap min = max = 112 MiB, which the PSP path mallocs from newlib at boot, leaving ~128 MiB native
  (FreeType, image decode, vitaGL per-draw buffers); `vglInitExtended(8 MiB, 960, 544, 16 MiB, NONE)`
  carves a RAM texture pool (~77 MiB) from what remains. Min = max because the heap is reserved up
  front anyway; a smaller min only makes the GC run more often. Measured live Java was ~16 MiB after
  full GC for a 2D card game, so size from logs, not from desktop `-Xmx`.
- Startup also: clocks 444/222/222/166, `chdir("ux0:data/<app>")` (games use cwd-relative save
  paths), and stdout/stderr redirected to a log file in append mode (no `dup2`), stdout buffered and
  stderr unbuffered so TeaVM's uncaught-exception trace survives `abort()`.
- vitaGL's splash can be suppressed with `-Wl,--wrap=invoke_splashscreen` and a no-op
  `__wrap_invoke_splashscreen`; draw your own loading frame instead.
- STSPSVITA links `vita_create_self(... UNSAFE)`.

## 8. Assets, packaging and legal model

- Texture memory is the binding limit: convert PNG/JPG to DXT1/DXT5 DDS offline (`stb_dxt`), optionally
  at half data size while keeping the header's original dimensions so UVs and layout are unchanged.
  Never rescale textures the game measures. Prune unused-language fonts (CJK fonts were ~160 MB) and
  re-encode OGGs (32 kbps / 24 kHz). Put runtime art outside `sce_sys/livearea/contents`: the
  installer may drop unreferenced files there.
- Ship two VPKs from one eboot: a full one with assets in `app0:/assets` and a slim code-only one
  (~7 MB) that reads `ux0:data/<app>/assets`, so code iterations reinstall in seconds.
- Record a build manifest (input hash, options, tool versions, output hashes) and validate that both
  VPKs carry identical executables.
- **Commercial games**: the generated C is a transformation of the game's code, so the VPK is a
  derivative of a copyrighted work. The STSPSVITA model is a **local build pipeline**: the repo ships
  only tools and backend; the user supplies their own purchased jar; the pipeline refuses unknown jar
  hashes; no prebuilt VPK is published. Follow that model, or decline.
- **Open-source Java games**: respect the licence of the Java code (an AGPL game stays AGPL, and its
  corresponding source must accompany the VPK).

## 9. Debugging

- **Host harness first** (`tools/host_harness.sh`): compile the same generated C with host gcc against
  SDL2 + libGL + a host glue file, with `app0:` and `ux0:data/<app>` as literal directories. This
  catches fiber, GC, serializer and file-path bugs before hardware. To match the Vita's 32-bit layout,
  also test a `-m32` build: the array-offset bug in section 5 only appears on 32-bit.
- Per-frame counters exported from C (FreeType, image decode, uploads, IO) attributed the hitches.
  Log vitaGL pool totals at boot (`vglMemTotal`) and texture-pool exhaustion; out-of-pool textures
  otherwise turn blank or crash the allocator.
- A blank/black screen with a running loop often means time is not advancing (section 5, `time.c`) or a
  0×0 viewport.

## 10. Effort and triage checklist

STSPSVITA reached a playable pre-alpha for a 2D GL 2.0 game, with months of device tuning visible in
its comments. Before quoting a schedule, answer:

1. Pick the route with the comparison in section 1 (TeaVM, Clearwing or a rewrite) and write down why
   the others lost.
2. Go through the section 2 table row by row and mark each one empty, cheap or core.
3. Does the game need `Gdx.gl30` or GLSL 330+? If yes, add a GL 3 subset backend and rewrite shaders, or decline.
4. Which libraries does it ship (Guava, ANTLR, commons-compress, XStream, Kryo)? Run a TeaVM transpile
   with stub classes for desktop-only code; the severe-problem list is the real work list.
5. How much reflection (fine on 0.16 if reachable), AWT/ImageIO and NIO channel use does `audit_source.py` find?
6. What is the live heap on desktop after a full GC in the heaviest scene? Add texture memory, which
   the desktop driver hid.
7. Is the code open source (ship it) or commercial (local pipeline only)?
