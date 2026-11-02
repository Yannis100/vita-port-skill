# Debugging and failure modes

Start from the symptom table; most Vita problems repeat. Items tagged *(unverified)* need a console.

## Contents
1. Symptom table
2. Install and bubble errors
3. Link and build errors
4. Debugging with hardware
5. Debugging without hardware (incl. turning a reported fault address into a named defect)
6. Crash dumps (and logging the crash yourself)

## 1. Symptom table

| Symptom | Likely cause and fix |
|---|---|
| Crash on boot, no log | `_newlib_heap_size_user` + other memblocks exceed MAIN (heap init silently fails, every malloc returns ENOMEM); main stack too small (set `sceUserMainThreadStackSize` or run on a big thread); ELF not run through `vita-elf-create` or built without `-Wl,-q`; `UNSAFE` self without unsafe homebrew enabled; missing required plugin or `libshacccg.suprx` |
| `0x8002710B` NO_MEMORY / `0x805B0002` GXM OUT_OF_MEMORY | raise the budget with `ATTRIBUTE2=12` (reinstall the VPK), shrink the newlib heap, lower vitaGL pools (`vglInitWithCustomSizes`, `vglMemFree` to inspect), drop MSAA |
| Black screen | `vglInit*` / `vglSwapBuffers` missing; shader compile failing (no `libshacccg.suprx`); GL errors hidden by `NO_DEBUG` (rebuild with `LOG_ERRORS=1`); wrong display pitch or no swap in a custom GXM backend |
| Game runs, no assets | wrong `ux0:data/<name>/` path; case or separator issues; app expects cwd=assets but cwd is `app0:` |
| Translated data path silently finds nothing | wrong translated root — validate with a probe FILE (`scripts/qdir.txt`), not a directory-exists test (THUG) |
| Freezes 1-2 s on first use | runtime shader compilation or first-use cache build; enable a shader cache |
| Hard crash in deep code | stack overflow on a thread; unaligned access (struct packing); null from failed `sceKernelAllocMemBlock` |
| Animations frozen or fades stuck at black while the loop runs | the clock has 1 s resolution (`sceKernelLibcTime`, `time()`), so frame delta is 0; use `sceKernelGetProcessTimeWide()` (µs) or `SDL_GetTicks` |
| JIT/dynarec crashes on the first generated block, or runs stale code | missing cache flush (`kuKernelFlushCaches` / `sceKernelSyncVMDomain`) or write/exec toggle; see `references/runtime.md` section 4b |
| Eboot fails to start, or a kubridge call crashes, after adding kubridge calls | plugin missing, or the user has v0.1 (TheOfficialFloW), which lacks `MemProtect` and the exception calls; link `-lkubridge_stub_weak`, check at boot and name the version in the README (`references/runtime.md` section 4c) |
| kubridge `MemProtect`/`MemCommit` crashes only on some consoles | those calls use SceSysmem offsets known only for firmware 3.60 and 3.65 (`references/runtime.md` section 4c) |
| Rendering glitches after adding speed hacks | revert hacks one by one (`INDICES_SPEEDHACK`, `PRIMITIVES_SPEEDHACK` are common culprits) |
| Audio crackle | mixing thread starved; pin to a core; bigger grain; stream music |
| Slow | check clocks, `NO_DEBUG`, texture formats, draw calls, CPU conversion paths; profile per core (Halo CE reads per-core idle clocks via `sceKernelGetSystemInfo`) |

## 2. Install and bubble errors

| Code | Meaning |
|---|---|
| `0x8010113D` | LiveArea PNGs not indexed / wrong format. Run `scripts/check_vpk.py`; fix with pngquant or `make_placeholder_assets.py` |
| `0x8010111C` | `head.bin` missing |
| `0x80101104` | corrupt app.db entry |
| `0x80010016` | directory limit reached |
| `C2-12828-1` | generic "application aborted or hung" (also memory-card corruption); get a core dump |

Bubble missing or wrong: title ID must be exactly 9 characters and unique; `template.xml` and
images must exist; rebuilding the database in Safe Mode may be needed *(exact causes unverified)*.
VPKs install from VitaShell (`ux0:/vpk/`, Cross, confirm the extended-permissions prompt for
unsafe builds). Unsafe apps need "unsafe homebrew" enabled in HENkaku settings.

## 3. Link and build errors

| Error | Fix |
|---|---|
| undefined `sce*` | add the matching `Sce*_stub` (find the module in `vita-headers/db`) |
| undefined `__cxa_*`, `operator delete` | add `-lstdc++` (vitaGL is C++) |
| pthread symbols unresolved | use `-pthread`, not bare `-lpthread` |
| `vita-elf-create` relocation errors | link with `-Wl,-q` |
| `cannot find -lSceAppmgr_stub` (or `-lvitagl`, `-lopensles`) | library names are case-sensitive: `SceAppMgr_stub`, `vitaGL`, `OpenSLES`; see `references/toolchain.md` section 8 |
| `return-mismatch`, `incompatible-pointer-types` errors in old so-loader code | GCC 14+; fix casts, or scope `-Wno-error=...` to that file (`references/toolchain.md` section 8) |
| implicit-declaration / int-conversion errors in old C | `-std=gnu11 -Wno-error=implicit-function-declaration -Wno-error=int-conversion -Wno-error=incompatible-pointer-types` (GCC 15) |
| `configure: cannot guess build type` | refresh `config.sub`/`config.guess` *(unverified)* |
| vitaGL symbols missing | check library order; `-lmathneon -lvitashark -lSceShaccCgExt -ltaihen_stub -lSceShaccCg_stub` |
| undefined `sceGxm*` referenced from `libvitaGL.a` although `SceGxm_stub` is in the list | static stub archives are order-sensitive: `SceGxm_stub` must come **after** `vitaGL` (an early copy does not help). `SceGpuEs4_stub` / `libScePiglet_stub` are not needed for this (checked by relinking) |
| `vita-elf-create: Cannot allocate N bytes for SCE data at end of segment 0; segment 1 overlaps` | the linker script puts the data segment at the next 64 KiB boundary (`DATA_SEGMENT_ALIGN(0x10000, 0x10000)`) and vita-elf-create appends ~5 KiB of SCE metadata behind the text segment, so about 8 % of text sizes fail and any small code change can trigger it. Check with `arm-vita-eabi-readelf -lW <elf>` (gap = 2nd LOAD vaddr − 1st LOAD vaddr − memsz). Fix: add a `.rodata` filler of a few tens of KiB (`const unsigned char pad[32*1024] = {1};`) so the text ends well below a boundary, and fail the build early with a gap check after link |
| `vita-elf-create: ...<name> is not an ELF file` (file size still changing) | the ELF is half written: a long build was piped into `head`/interrupted and an orphaned `ld` is still running. Wait for `ld` to exit (`pgrep ld`), then rerun the build **without** a pipe |
| so-loader unresolved symbols or wrong struct sizes | map in `dynlib.c`/`java.c`; wrap bionic vs newlib structs; check `__stack_chk_guard` |

## 4. Debugging with hardware

- **vitacompanion** (github.com/devnoname120/vitacompanion): FTP on **1337**, command server on **1338**.
  Install `vitacompanion.suprx` (`*main`) and `vitacompanion_kernel.skprx` (`*KERNEL`) under
  `ur0:/tai/config.txt`. Upload: `curl -T game.vpk ftp://VITA_IP:1337/ux0:/data/game.vpk`. Control:
  `echo 'launch MYGM00001' | nc VITA_IP 1338`; also `destroy`, `quit <id|all>`, `reboot`,
  `screen on|off`, `press cross; wait 100ms; release cross`. For fast iteration: destroy, upload
  `eboot.bin` into `ux0:/app/<TITLEID>/`, launch.
- **Logging**: `sceClibPrintf()` works without stdio. In frozen environments `stdout` may be unavailable.
  PrincessLog captures `printf`, `sceClibPrintf` and `ksceDebugPrintf` from any app or plugin over the
  network (setup in the tools list below); `psp2shell` (Cpasjuste) is a wifi shell + log viewer
  (`./psp2shell_cli <ip> 3333`). Halo CE writes its own log file and a heartbeat file
  (`heartbeat.txt` every 2 s) to see if the game is still running.
- **File logging** is the fallback: write to `ux0:data/<name>/log.txt` with `fflush` or `sceIoWrite`.
  To capture existing `printf`/`fprintf(stderr)` output, `freopen` both streams onto the log file in
  append mode (newlib on the Vita has no `dup2`), keep stdout fully buffered with a static buffer and
  stderr unbuffered, so crash traces printed right before `abort()` reach the card (STSPSVITA `native/src/main.c`).
- **TeamFAPS PSVita-RE-tools** (github.com/TeamFAPS/PSVita-RE-tools, GPL-3.0; read at commit `178948c`,
  2023-02, not tested here). Two of its tools help a port:
  - **PrincessLog**: network log of every `printf`, `sceClibPrintf` and `ksceDebugPrintf`, including
    output printed before your own file logging starts. Install `NetLoggingMgrSettings.vpk`, set the
    PC's address and port and save, add `net_logging_mgr.skprx` to `config.txt`, reboot, and listen on
    the PC with `nc -kl <port>` (default 8080). Very heavy logging can freeze it. It replaces ShipLog.
  - **PSVita-error-code-resolver**: turns a `0x80xxxxxx` code into its name, given a copy of
    `os0:kd/error_table.bin` from your own console (readable with VitaShell). For common codes the
    HENkaku wiki page `wiki.henkaku.xyz/vita/Error_codes` is quicker.

  The rest of the repo does not help a port. noASLR duplicates the per-app `NOASLR` self flag;
  PSMLogUSB needs the discontinued PSM USB driver on Windows; THGN, vitadecompiler-mod and prxtool
  analyse Vita system modules, not your code or an Android `.so`; vita-unmake-fself yields an ELF
  without symbols; unity_debug targets retail Unity builds; ioPlus is an end-user requirement of
  the Hollow Knight patch (port-types section 7), not a debugging tool; the decryption and kernel
  dump tools (FAGDec, Kdumper) must not be used on commercial games.
- **VitaShell FTP** also serves files (port 1337 by default, *unverified*).
- First milestone on any new port: a black or clear-colour screen that boots on hardware. Then a
  vertical slice. Do not wait until everything compiles to touch hardware.

### Data-path, boot presentation and on-hardware debug (THUG)

Repo: thug-vita-port.

- **Validate a data-path translation with a probe FILE, not a directory-existence test.** The first
  attempt used the wrong root and silently found nothing — no error, just missing data. Validate
  with a sentinel file (e.g. `scripts/qdir.txt`). Normalise backslash→forward and document extension
  renames (`.pre`→`.prx`) (`Code/Sys/Vita/p_filesys.cpp`).
- **Boot presentation:** draw a custom raw-RGBA boot screen into a CDRAM display buffer BEFORE
  `vglInit`'s ~2.5 s shader-compiler startup, so the user sees life immediately and stalls are
  visible. Cache compiled CG shader binaries to `ux0:data/<name>/shd/` keyed by source+type hash
  (300 ms → few ms per variant).
- **Clamped CPU overclock via the official `scePowerSet*ClockFrequency` API** (444/222/222/166 MHz).
  Document it as "Sony underclocks for battery", not a hack — these calls are the official API.
- **On-hardware complement:** `vita_dbgsrv` (TCP debug server: screenshot + log readback, driven via
  FTP on a real console) is an alternative to test-harness loops. Keep automated tests primary; use
  this only as an on-hardware complement.

### On-device runtime shader compilation (Source engine / HL2)

Repo: `LargeVegetable/source-engine` (branch `vita`).

- Shaders compile **on the device at runtime** via `libshacccg.suprx` (extracted from the console,
  ShaRKBR33D) + vitaShaRK; first-visit shader compiles cause hitches, then results are cached in
  `ux0:data/shader_cache/`. This mirrors the THUG compiled-CG disk-cache pattern above (key by
  source+type hash, seconds → few ms per variant) — cross-reference it when a first-use hitch shows
  up in the symptom table.

### Making the first run explain itself *(built and host-tested on a 2026-10 port, and run once in Vita3K, headless; not on a Vita)*

The first hardware or Vita3K run of a big port usually fails before the first frame, and the user sees a
black or blank screen. Cheap things that turn that into a message:

- **Check the user-supplied inputs yourself, before the engine starts.** If the engine's own fallback (a
  launcher UI, a file picker) is stubbed out, a missing or bad game image leaves a blank screen forever. Run the
  engine's own validation function on the file, then show the reason. Keep the decision (disc found / saved path /
  nothing) in a pure function over plain inputs so every combination is unit-tested on the host.
- **A text screen needs no GXM or vitaGL**: a `SCE_KERNEL_MEMBLOCK_TYPE_USER_CDRAM_RW` block (size rounded up to
  256 KiB), `sceDisplaySetFrameBuf` with `SCE_DISPLAY_PIXELFORMAT_A8B8G8R8` (a little-endian `u32` is
  `0xAABBGGRR`), a bitmap font, then wait on `sceCtrlPeekBufferPositive`. Wait for the face buttons to be released
  first, or a button held while launching dismisses the screen at once. Render into ordinary memory and
  `memcpy` once. Do not free the block while it is on screen; exit the process instead. Keep the font, wrap and
  layout code free of Vita headers so a host test can render the screens to PPM and you can look at them.
- **A boot log written before the engine starts**, flushed after every line, with the previous run kept as
  `.1`: firmware version (`sceKernelGetSystemSwVersion`), free memory (`sceKernelGetFreeMemorySize`), argv, whether
  `ur0:data/libshacccg.suprx` exists, and each decision. The last line says how far start-up got. Treat a missing
  shader compiler as a warning, not a stop (Vita3K may not need it).
- **Know where the engine's own log goes.** SDL3's Vita pref path is `ux0:/data/<org>/<app>/` (strings in
  `libSDL3.a`), which need not be your port's data folder. Many loggers flush only warnings and above; a crash then
  loses the last information lines. Set the flush level to Info, and log breadcrumbs: the GL strings, the start
  of every shader compile, a frame counter for the first frames and then a heartbeat.
- **Save the source of a shader the translator refuses**, next to its log message, under a label shared by
  both (a hash of the config). Cap the number of files. The translator's message alone rarely shows what it
  objected to. Check the file name logic with a host test (path separators in the label must not escape the
  folder).
- Read facts from the installed libraries instead of guessing: `strings` on `libvitashark.a` and `libvitaGL.a` show
  which `libshacccg.suprx` paths they try (`ur0:/data/` and `ur0:data/external/` in the 2026-10 builds).

## 5. Debugging without hardware

- **Vita3K** (vita3k.org): install firmware (both PUP packages), then `File > Install Archive` or
  `Vita3K <path.vpk>`; CLI options include `-r <TITLEID>`, `-l <0-6>` log level, `-B OpenGL|Vulkan`,
  `-Z <args>`. Logs in `Vita3K.log`. Needs x86-64 with OpenGL or Vulkan.
### Three ways an emulator run lies to you *(each cost a session on a 2026-11 port; all measured)*

Before trusting anything a headless run tells you, close these three holes.

1. **A truncated log line is a SIGKILL, not a hang.** A driver script that ends with
   `kill $pid; sleep 2; kill -9 $pid` (the common shape) cuts the last line mid-write, because stdio
   into a pipe is block-buffered. A log ending at `compiling gx-1a49877e: vertex 1113` with no
   `ready in` after it looks exactly like a compiler hang; the same shader had compiled in 283 ms an
   hour earlier. **Before believing a hang, grep earlier runs for the same work item.** Report final
   state through stderr or a warning-level logger, which are unbuffered.
2. **A steady frame time can be an empty loop.** A 33.33 ms/frame reading that never varies is
   suspiciously exactly the sound of a simulation clock pacing a loop that draws nothing. Forcing an
   interpolation/presentation split in a port whose presentation path was never implemented produced
   precisely that: 30.0 fps equivalent and 263-byte blank PNGs. **Capture pixels in the same run as
   the timing number**, and assert on them: a blank frame is ~263 bytes, a rendered one tens to
   hundreds of KB, and the PNG header says `mode=RGB` versus a palette/index type.
3. **Startup can consume the whole run.** Shader compilation at 200-700 ms per program, built lazily
   up to ~70 programs, can eat a 60 s budget so a 300-frame sampling window never fires. Size the
   window to the run (<=120 frames), report **deltas over a fixed window** rather than a cumulative
   average, and check that the window actually appeared before quoting anything.

- **Vita3K headless, from a script** *(verified once, 2026-10, Vita3K v0.2.1 on a WSL2 host; the app was a port that stops at a
  text screen, so only boot, loading and that screen were exercised)*: `Vita3K --firmware <PSVUPDAT.PUP>` installs the
  user's own firmware; `Vita3K <app.vpk>` installs and starts the app; `--frontend sdl` gives a plain window that
  can be screenshotted (Xvfb, `LIBGL_ALWAYS_SOFTWARE=1`, ImageMagick `import -window root`); `-c <config.yml>` needs
  `initial-setup: true` and a `pref-path` that already exists (an empty or missing one aborts with "cannot create
  directories: Invalid argument []"). The official Linux builds can need a newer glibc and Qt6 than an LTS distro
  has: run them in a rootless container (a current Arch image worked) instead of installing anything on the host.
  The app's files appear under the pref path (`ux0/data/<app>/`), so a boot log can be read after the run, and
  `xdotool key x` presses Cross in the default keyboard map. Firmware is not needed for a bare-metal text screen
  (Vita3K only logs missing kernel modules). Quirks: `sceKernelGetSystemSwVersion` is unimplemented (empty
  string, success code) and no argv is passed. The firmware and the Vita3K binary are the user's; never ship them.
- **The host's C library is not the Vita's.** The VitaSDK's newlib has no `%z` length modifier (`%zu` printed
  `zu` and swallowed the argument); `%ll` works. Every host test uses glibc, which accepts both, so only running
  on Vita3K showed it. Cast to `unsigned` / `unsigned long long`, and add a grep-level lint for `%z`, `%j`, `%t`,
  `%hh` in the port's sources (make sure it fails on the bad line before you fix it).
- Vita3K does not emulate budget limits or kernel permissions, hides some GPU behaviour, and may
  not run plugin-dependent builds (kubridge, `libshacccg.suprx`) *(unverified)*. A Vita3K pass means
  "boots and renders", not "works on a console". `vitaGL` has `HAVE_VITA3K_SUPPORT=1`.
- Android so-loader ports essentially require hardware.
- Without any console you can: build, run `check_vpk.py`, run the Linux test target of a
  two-backend project (Halo CE style), and review code for the failure causes above.
- **Host GLES2 harness for a vitaGL renderer** *(verified on a 2026-10 port; nothing reached hardware)*:
  Mesa llvmpipe through EGL *surfaceless* gives a headless GLES2 context
  (`eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, ...)`, `EGL_OPENGL_ES2_BIT`, pbuffer or FBO only,
  `libEGL`/`libGLESv2` from `libegl-dev libgles-dev`). Compile the renderer's shader generator and
  decoders for x86 against the VitaSDK headers (symlink `$VITASDK/arm-vita-eabi/include/vitaGL.h` etc. into
  an include dir) and feed the generated GLSL ES 1.00 to Mesa to check it compiles and links. That catches
  GLSL errors, uniform-count blowups and decode bugs. It does **not** check vitaGL's Cg translator, the
  128-vec4 vertex / 16-vec4 fragment uniform caps, FBO row order or speed; run those on hardware.
- **Test hygiene for such harnesses**: (1) fuzz only inside the input domain the real API allows. Invalid
  inputs hit the engine's own fatal-error path and abort, which is correct and tells you nothing. A stub
  logger that swallows `Log.fatal` turns this into a silent `rc=134`; make test stubs print to stderr.
  (2) Where upstream has a reference implementation (texture decoders, vertex formats), run the port's code
  and the upstream code on the same inputs through a thin shim and compare byte for byte. (3) Add a
  **negative control**: corrupt one byte or one rule on purpose and confirm the test fails. A test that
  cannot fail is not evidence. (4) Run under ASan/UBSan (`-fsanitize=address,undefined
  -fno-sanitize-recover=undefined`).
- **Host end-to-end render harness** *(verified on the 2026-10 Twilight Princess port: 87 scenes, 14,242 pixel
  checks, plain and ASan, Mesa llvmpipe, 133 scripted negative controls)*: a link-only shader fuzz does not check pixels, so a renderer can pass it and still draw
  wrong. Compile the *real* front end (here: GX API -> command processor -> frame -> replay -> FBO -> present) for
  x86 and render tiny synthetic scenes, each with an analytic expectation (flat colour, barycentric colour, a
  texel centre, Lambert `N.L`, depth order, blend, cull, alpha test, line width). Lessons:
  1. It found a bug that the link-only fuzz and a code review both missed: integer bit fields (light masks, a
     texcoord bit set) travel as raw `u32` in the uniform blob, the shader read them as `float` (a small integer
     is a denormal = 0), and every light was skipped. GLSL ES 1.00 has no `floatBitsToUint`; convert integer
     lanes to float on upload and flag them in the segment table, then assert that flag contract on every fuzzed
     config.
  2. When a scene fails, check the scene first, then the harness's assumptions, then the code. Of the first
     failures: one was a scene bug (a GX light with a direction but no position), one a harness assumption
     (GL row 0 is the bottom, not the top; pin it with an `orientation` scene), one a real renderer bug.
  3. A scene that passes on the first try is unproven. Break the code under test on purpose (comment out the
     fix) and confirm exactly the scenes that depend on it fail. Make sure the break reaches the build: a host
     Makefile without header dependencies (`-MMD -MP`) silently ignored an edited header and the control
     "passed" for the wrong reason. Pick probes that the break can change: a mirror bug cannot fail a symmetric
     glyph ('T'), nor a red/blue swap a blend of blue over red; use 'L' and green over red.
  4. Clear colour is captured at `begin_frame` in Aurora-style frame recorders, so the first frame after init
     shows the previous colour; render a warm-up frame. Scenes share GPU/API state: reset line width, point size
     and other sticky state in the baseline.
  5. Say what a pass cannot show. Mesa accepts GLSL that vitaGL's Cg translator rejects, has no uniform caps, and
     has `highp` everywhere; row order, `gl_FragCoord` and texture-unit assumptions still need hardware.
  6. **Run the whole harness under ASan** (`-fsanitize=address`, `detect_leaks=0`) as its own mode, not just the
     unit tests: it found a per-texture-unit state array one entry too small for the unit used by a fog-range
     table, and a use-after-free at exit.
  7. **Hooks that are declared but never called.** Grep for callers of every `init`/`shutdown`/`prepare` function a
     renderer defines. Here a texture "prepare for sampling" step (the GPU palette pass) and the texture and GX
     `shutdown` functions had no caller, so palette textures sampled empty data and GL-handle caches were
     destroyed after the context. Caches of GL handles that live in statics need an explicit teardown before the
     context goes, and a teardown check in the harness (live texture bytes return to zero).
  8. **Per-frame storage must not outlive the frame.** A cached offset into a frame's upload buffer (an array
     "cached range") survived into the next frame and pointed at the previous frame's data: reset per-frame
     caches in `begin_frame`.
  9. **State caches in the front end** (a viewport or scissor that is only re-emitted when it changes) mean that
     leaving an offscreen pass must explicitly restore both, and that a stale one leaks into whichever scene runs
     next. Targets cached per size leak the same way: analyse "extra" failures in a negative control before
     adjusting the expectation, they are often true.
  10. **Clamp-to-edge hides small targets.** A copy larger than its source repeats the source's edge texels, so a
     render target that is too small looks right behind uniform edges. Give the last rows and columns their own
     colours. A fresh GL texture is zero-filled on Mesa, so "a new target is cleared" can only be proven on re-use.
  11. A negative control must fail **exactly** the scenes it is meant to: run each against the whole suite and
     compare the failing set (a script with an expected list per control). "Fails something" is not enough; a
     control that fails nothing never reached the build.
  12. Before writing a scene for a code path, check that the game build reaches it (here a destination-alpha clear
     function was stubbed out under the PC target, so it needed no scene) and that nothing was claimed "live"
     from a function name alone.
  13. In GLSL ES 1.00 `gl_FragCoord` is `mediump` by definition, but Mesa computes it in fp32, so a host test cannot
     see the precision loss that depth-based maths (perspective fog divides by `B - z`) may have on the GPU. Pin the
     formula on the host, and treat `gl_FragCoord.z` precision as hardware-unverified.

### Turning a reported fault address into a named defect (static, no console needed)

A crash report often survives only as a symbolised line ("`Foo::bar` +838") or as a raw guest address. You usually
do not need to reproduce it: the unstripped ELF still contains the defect. This route found a real null dereference
in a 2026-11 port after a previous session had recorded the wrong addresses and given up.

1. **Re-symbolise the address against the ELF you are actually running.** Never trust a recorded address.
   `arm-vita-eabi-addr2line -f -C -e build/<proj> 0x...`, then check it against the symbols:
   `arm-vita-eabi-nm -C -S --defined-only build/<proj> | grep '<function>'`. The `-S` size matters: an offset
   larger than the function's size is not in that function. In that port `makeHierarchy`+432 was past the end of a
   `0x1e6`-byte function and resolved to a completely different symbol.
2. **Check the arithmetic and check that it is code.** `0x810e4cb0 + 838` is `0x810e4ff6`, not `0x810e506e`.
   The recorded value happened to fall inside a literal pool (`.word 0x8240c400`), i.e. data, so it could never
   have been a faulting instruction. `objdump` the surrounding bytes before believing any offset.
3. **Disassemble the whole function, not just the reported instruction.** A symbolised "invalid read" is often a
   compiler-folded consequence, not the source line you expect:
   ```
   arm-vita-eabi-objdump -d -C --start-address=<fn> --stop-address=<fn+size> build/<proj>
   ```
4. **Recognise the constant-offset-through-a-null pattern.** `movs r0, #0` followed by `ldr r0, [r0, #N]` is a
   literal dereference of address `N`. It is not a corrupted pointer at run time: it is the compiler proving a
   pointer is NULL and still emitting the access. Find `N` in the class's member list (`/* 0x58 */ J3DMaterial* mMesh;`)
   to name the field, then search the source for the member access.
5. **Check whether the "null test" actually reads the pointer.** The root cause in that port was an accessor that
   returns a constant and never reads `this`:
   ```cpp
   u32 getType() const { return 'NJNT'; }                 // never dereferences
   ... else if (pJoint->getType() == 'NJNT') {            // "null check" that always passes
           J3DMaterial* m = pJoint->getMesh();            // folds to ldr r0, [r0, #0x58]
   ```
   Any method of that shape is not a null check. Test `p != NULL` explicitly.
6. **Distinguish inherited from introduced before you "fix" upstream code.** Compare against the reference
   decomp or the pristine dependency: here `git diff HEAD -- <file>` was empty and the reference tree had
   identical code, so the bug was inherited and the fix belongs in a documented local patch.
7. **Verify the fix in the codegen, not just the source.** Rebuild, then re-disassemble and confirm the
   `movs r0, #0` / `ldr r0, [r0, #N]` pair is gone and every access to that field now goes through a live register.
   A grep of the source cannot prove the optimiser stopped folding.
8. **Say what the fix does not prove.** The original log had lost the faulting instruction, so the honest claim is
   "the one reachable null dereference in this area is closed", not "the reported crash is explained". Record both.

## 6. Crash dumps

A crash writes `ux0:data/psp2core-<timestamp>-...-eboot.bin.psp2dmp`. Some firmware writes an
encrypted `spsp2dmp` *(unverified)*. Parse with `vita-parse-core` (github.com/xyzz/vita-parse-core):

```bash
python2 main.py core.psp2dmp build/mygame      # the UNSTRIPPED .elf, built with -g
```

- Use the `.elf` from `add_executable` (CMake: `build/<proj>`), not `.velf` or `eboot.bin`.
- Needs `arm-vita-eabi-objdump` and `addr2line` on PATH. README says Python 2; a Python 3 status is
  *unverified*.
- Keep a `*.unstripped.elf` for every release build you ship. The solobop template has a `dump`
  target that pulls and parses dumps.

### Logging the crash yourself (kubridge exception handlers)

Core dumps need a round trip through `vita-parse-core`. A kubridge exception handler (kubridge
v0.3+, section 4c of `references/runtime.md`) can write the registers to your own log at the moment
of the fault instead. VitaKotor (`loader/crash.c`, 2026-10) does this for a so-loader port:

```c
static void crash_handler(KuKernelExceptionContext *c) {
  /* pc, lr, sp, r0-r12, FAR (fault address), FSR, exceptionType */
  log_unbuffered("fault type=%u pc=%08x lr=%08x far=%08x", c->exceptionType, c->pc, c->lr, c->FAR);
  sceKernelExitProcess(0);          /* do not return: that re-runs the faulting instruction */
}
for (SceUInt32 t = KU_KERNEL_EXCEPTION_TYPE_DATA_ABORT; t <= KU_KERNEL_EXCEPTION_TYPE_UNDEFINED_INSTRUCTION; t++)
  kuKernelRegisterExceptionHandler(t, crash_handler, NULL, NULL);
```

- The handler runs in user mode **on the faulting thread's stack**. kubridge needs about 1.4 KiB
  free there (0x160 for the context plus 0x400); with less, or a corrupt `sp`, it skips your handler
  and the normal crash (and core dump) happens. Keep locals small and use static buffers.
- Do not take locks: the faulting thread may hold your log mutex. VitaKotor flushes its buffer and
  switches to unbuffered, lock-free writes first.
- Turn addresses into something `addr2line` can use: subtract the base of the module that holds
  them. For so-loaded libraries use the loader's `text_base`; for system modules and the eboot,
  walk `sceKernelGetModuleList` + `sceKernelGetModuleInfo` segments. A PC near `0xE0000000` is
  inside a Sony module, and its name is usually the diagnosis.
- Returning *is* useful when you fix the context first; kubridge restores the edited registers.
  DSVita's fastmem handler passes `FAR` and `pc` to the JIT, which patches the access, sets
  `pc` and returns; faults it does not own go to the previous handler.
- One handler per exception type per process. Pass `&old` as `pOldHandler` and call it for faults
  you do not handle (DSVita does), so two subsystems can share the hook.
- The snippet's kubridge calls built here (VitaSDK 2026.08, 2026-10-14); never run on a console.

## So-Loader Specific Debugging

### Unresolved Symbols
- Enable `DEBUG_SOLOADER` in Debug CMake build
- Watch for "symbol not found" warnings in vitaLog (port 1338)
- Use `arm-vita-eabi-nm -u your_game.so | grep "U "` to list unresolved symbols
- Add missing entries to `source/dynlib.c` mapping to Vita SDK functions
- Common additions: C++ RTTI (`_ZdlPv`, `_Znaj`), math (`sincosf`), GLES (`glCreateShader`)

### kubridge Not Loaded
- Error at startup: `"kubridge is not loaded"`
- Fix: Install `kubridge.skprx` via taihen on target Vita (firmware 3.60+)
- Error code: `0x80101051`
- Verify with: `taihen --list` to confirm plugin loaded

### Shader Compilation Failures
- Enable `DEBUG_OPENGL` in CMake build
- Check GLSL version compatibility (vitaGL targets ES 1.00)
- Use `DUMP_COMPILED_SHADERS` to cache compiled shaders to `ux0:data/<app>/shaders/`
- Bypass cache: create empty `no-shader-cache.txt` in `ux0:data/<app>/`

### Asset Path Issues
- App can't find files: verify `ux0:data/<app>/assets/` layout matches APK
- Check `/proc/cpuinfo` → `app0:/cpuinfo` mapping in `reimpl/io.c`
- Check `/dev/urandom` → `app0:/urandom` mapping

### Memory and Crash Debugging
- Enable `SO_UTIL_VERBOSE=1` for detailed so_util logging
- Check heap usage: vitaLog should show memory block allocation
- Black screen after load: usually shader compilation or GLES context issue
- Use vitacompanion FTP (port 1337) to inspect files and logs
