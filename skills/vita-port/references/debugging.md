# Debugging and failure modes

Start from the symptom table; most Vita problems repeat. Items tagged *(unverified)* need a console.

## Contents
1. Symptom table
2. Install and bubble errors
3. Link and build errors
4. Debugging with hardware
5. Debugging without hardware
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

## 5. Debugging without hardware

- **Vita3K** (vita3k.org): install firmware (both PUP packages), then `File > Install Archive` or
  `Vita3K <path.vpk>`; CLI options include `-r <TITLEID>`, `-l <0-6>` log level, `-B OpenGL|Vulkan`,
  `-Z <args>`. Logs in `Vita3K.log`. Needs x86-64 with OpenGL or Vulkan.
- Vita3K does not emulate budget limits or kernel permissions, hides some GPU behaviour, and may
  not run plugin-dependent builds (kubridge, `libshacccg.suprx`) *(unverified)*. A Vita3K pass means
  "boots and renders", not "works on a console". `vitaGL` has `HAVE_VITA3K_SUPPORT=1`.
- Android so-loader ports essentially require hardware.
- Without any console you can: build, run `check_vpk.py`, run the Linux test target of a
  two-backend project (Halo CE style), and review code for the failure causes above.

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
