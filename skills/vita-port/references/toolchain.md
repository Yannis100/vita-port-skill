# VitaSDK toolchain, builds and packaging

Written 2026-10 against VitaSDK series **2026.08** (GCC 15.2.0, newlib 4.1). Re-check with
`vdpm status` before relying on version-specific details. Old tutorials describe `vdpm`
with `packages.list` and `vitasdk-update`; those are gone (vdpm is now a rootless pacman frontend).

## Contents
1. Install
2. vdpm and common packages
3. CMake project
4. Makefile / manual packaging chain
5. Cross-compiling third-party libraries
6. Stub libraries and link order
7. Packaging details (SFO, LiveArea, VPK)
8. Reviving an old port on the current SDK

## 1. Install (Linux / WSL2)

```bash
sudo apt-get install make git-core cmake python3 curl
export VITASDK=/usr/local/vitasdk          # or $HOME/vitasdk to avoid sudo
export PATH=$VITASDK/bin:$PATH             # also put both lines in ~/.bashrc
git clone https://github.com/vitasdk/vdpm && cd vdpm && ./bootstrap-vitasdk.sh
vdpm status
```

- The bootstrap refuses to install into an existing directory. Use `VITASDK=$HOME/vitasdk
  ./bootstrap-vitasdk.sh` or `--install-dir`. `/usr/local` needs `sudo mv`, which the script runs.
- Reproducible CI: `./bootstrap-vitasdk.sh --url <autobuilds release tarball> --sha256 <hex>`.
- Docker (Ubuntu 24.04 base): 
  `docker run --rm -v "$PWD:/workspace" vitasdk/vitasdk:2026.08 sh -c 'cmake -B build -DCMAKE_TOOLCHAIN_FILE=$VITASDK/share/vita.toolchain.cmake && cmake --build build'`
  Tags: `2026.08`, `latest` (newest supported series), `nightly`; suffixes `-minimal` (no target
  libs) and `-non-root`. The `-minimal` image needs `vdpm install` for libraries.
- Native Windows works through `bootstrap-vitasdk.ps1`; WSL2 is easier.
- Softfp builds (only for Android so-loader ports) need a separate softfp SDK and every library
  built softfp, including vitaGL (`SOFTFP_ABI=1`). Do not mix. A softfp Docker image exists:
  `vitasdk/vitasdk-softfp` (used, pinned by digest, in Rinnegatamante's 2026-09 so-loader rebuilds).

Key repos: `vita-toolchain` (host tools, `share/vita.toolchain.cmake`, `share/vita.cmake`),
`vita-headers` (`psp2/` user headers, `psp2kern/`, NID database), `newlib` (Vita layer in
`newlib/libc/sys/vita/`), `pthread-embedded`, `packages` (VITABUILD recipes), `samples`.

## VitaSDK-softfp (Required for Android .so Loader Ports)

**Stock VitaSDK uses hard-float ABI.** Android .so loader ports require **soft-float ABI** to match Android's
calling convention and avoid ABI mismatch crashes.

### Installation

```bash
git clone https://github.com/vitasdk-softfp/vdpm ~/vdpm-softfp
cd ~/vdpm-softfp
./bootstrap-vitasdk.sh
./install-all.sh
```

### Usage

For .so loader projects, set `VITASDK` to the softfp toolchain:

```bash
export VITASDK=~/vdpm-softfp/arm-vita-eabi
```

The `soloader-boilerplate` CMakeLists.txt handles this automatically when `VITASDK` is set correctly.

### Verification

```bash
arm-vita-eabi-gcc -v  # Should show the softfp installation path
```

### Note

- VitaSDK-softfp is separate from the main VitaSDK — install to a different prefix
- Only .so loader ports need softfp; native VitaSDK ports (C/C++ with VitaSDK build) work fine with stock
- See [soloader-boilerplate](https://github.com/v-atamanenko/soloader-boilerplate) and [vitasoguide](https://github.com/Rocroverss/vitasoguide)

## 2. vdpm and common packages

Subcommands: `install remove upgrade list search info files refresh [series] status channels
pacman -- <args>`. `vdpm upgrade` takes fixes inside the release; `vdpm refresh 2026.08` changes
release. Dependencies resolve automatically. Names are case-sensitive.

| Need | Packages |
|---|---|
| SDL | `sdl2`, `sdl2_image`, `sdl2_mixer`, `sdl2_mixer_ext`, `sdl2_ttf`, `sdl2_net`, `sdl2_gfx`, `sdl3`, `sdl`, `sdl_image`, `sdl_mixer` |
| SDL2 on vitaGL | `sdl2_vitagl` (`provides=sdl2`, `conflicts=sdl2`: choose one) |
| GL stack | `vitaGL`, `vitaShaRK`, `SceShaccCgExt`, `libmathneon`, `pib` (GLES2), `libvita2d` |
| Compression | `zlib zstd bzip2 xz libzip minizip libarchive` |
| Images / fonts | `libpng libjpeg-turbo libwebp libtiff freetype harfbuzz fribidi` |
| Audio / video | `openal-soft libogg libvorbis libtremor flac opus opusfile mpg123 libmad libsndfile libmodplug libxmp libopenmpt fluidsynth-lite soloud ffmpeg libtheora` |
| Network / crypto | `curl curl-mbedtls openssl mbedtls libsodium enet libsmb2` |
| Misc libs | `boost glm fmt jsoncpp yaml-cpp libxml2 expat physfs luajit quickjs-ng box2d bullet assimp imgui` |
| Vita-specific | `taihen kubridge kuio vita-libdl libftpvita libdebugnet` |

Not packaged: plain Lua, `gl4es4vita`, SDL_sound. `vitaGL` from vdpm is built with `NO_DEBUG=1`,
so GL errors are silent; rebuild from source with `LOG_ERRORS=1` when debugging.

## 3. CMake project

Template: `assets/CMakeLists.vita.txt`. The canonical shape (from `vitasdk/samples`):

```cmake
cmake_minimum_required(VERSION 3.16)
if(NOT DEFINED CMAKE_TOOLCHAIN_FILE)
  if(DEFINED ENV{VITASDK})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VITASDK}/share/vita.toolchain.cmake" CACHE PATH "toolchain file")
  else()
    message(FATAL_ERROR "Please define VITASDK to point to your SDK path!")
  endif()
endif()
project(mygame C CXX)
include("${VITASDK}/share/vita.cmake" REQUIRED)   # must come after project()
set(VITA_APP_NAME "My Game")
set(VITA_TITLEID  "MYGM00001")                    # exactly 9 characters
set(VITA_VERSION  "01.00")                        # must match ^[0-9][0-9]\.[0-9][0-9]$
...
vita_create_self(${PROJECT_NAME}.self ${PROJECT_NAME})
vita_create_vpk(${PROJECT_NAME}.vpk ${VITA_TITLEID} ${PROJECT_NAME}.self
  VERSION ${VITA_VERSION} NAME ${VITA_APP_NAME}
  FILE sce_sys/icon0.png sce_sys/icon0.png
  FILE sce_sys/livearea/contents/bg.png sce_sys/livearea/contents/bg.png
  FILE sce_sys/livearea/contents/startup.png sce_sys/livearea/contents/startup.png
  FILE sce_sys/livearea/contents/template.xml sce_sys/livearea/contents/template.xml)
```

Facts that save time:

- The toolchain file sets `CMAKE_SYSTEM_NAME Generic`, `-Wl,-q` (the relocation table the
  packaging step needs; never remove it), `-Wl,-z,nocopyreloc`, the install prefix
  `$VITASDK/arm-vita-eabi`, `PKG_CONFIG_EXECUTABLE`, and find-root mode ONLY. It defines `VITA` and
  `BUILD_VITA`, so `if(VITA)` selects Vita-only code in a shared CMake file.
- `find_package(SDL2 REQUIRED)` + `SDL2::SDL2` works; whether it pulls every needed stub
  transitively is *(unverified)*, so add `SceDisplay_stub SceCtrl_stub SceTouch_stub SceAudio_stub
  SceGxm_stub` explicitly if linking fails.
- `vita_create_self(target source [UNCOMPRESSED] [UNSAFE] [SECRETSAFE] [STRIPPED] [NOASLR]
  [REL_OPTIMIZE] [MEMSIZE kib] [ATTRIBUTE n] [CONFIG exports.yml | GEN_EXPORTS f])`. Without
  `UNSAFE` the eboot is "safe" (`vita-make-fself -s`); without `UNCOMPRESSED` it is compressed
  (`-c`). Default to safe. Use `UNSAFE` only when the port needs it (so-loaders, kubridge, some
  memory modes) and tell the user they must enable unsafe homebrew.
- Extra SFO fields: `set(VITA_MKSFOEX_FLAGS "${VITA_MKSFOEX_FLAGS} -d ATTRIBUTE2=12")`. Hooks also
  exist for `VITA_PACK_VPK_FLAGS`, `VITA_ELF_CREATE_FLAGS`, `VITA_MAKE_FSELF_FLAGS`.
- `FILE <src> <dst>` accepts a directory (`FILE sce_sys sce_sys`).
- Release build: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release` (adds `-O3 -DNDEBUG`). VPK lands at
  `build/<proj>.vpk`; the unstripped ELF for crash symbolication is `build/<proj>` (no extension).
- Add `-g` to keep symbols for `vita-parse-core`; do not `strip` the file you will symbolicate.
- Link `-pthread` (or `Threads::Threads`), not bare `-lpthread`: the GCC driver maps `-pthread`
  to `--whole-archive -lpthread`, and without it pthread symbols can stay unresolved.
- C++ works (`samples/hello_cpp_world`). vitaGL needs `-lstdc++` to link.

## 4. Makefile / manual packaging chain

Pipeline used by Makefile ports and by projects with their own build system:

```bash
arm-vita-eabi-gcc -Wl,-q ... -o app.elf          # keep -g for dumps
arm-vita-eabi-strip -g app.elf -o app.stripped.elf   # optional, keep the unstripped one
vita-elf-create app.stripped.elf app.velf
vita-make-fself -s -c app.velf eboot.bin             # -s safe, -c compress; -ss secret-safe
vita-mksfoex -s TITLE_ID=MYGM00001 -s APP_VER=01.00 -d ATTRIBUTE2=12 "My Game" param.sfo
vita-pack-vpk -s param.sfo -b eboot.bin \
  -a sce_sys/icon0.png=sce_sys/icon0.png \
  -a sce_sys/livearea/contents/bg.png=sce_sys/livearea/contents/bg.png \
  -a sce_sys/livearea/contents/startup.png=sce_sys/livearea/contents/startup.png \
  -a sce_sys/livearea/contents/template.xml=sce_sys/livearea/contents/template.xml app.vpk
```

`vita-pack-vpk` also accepts `--add src=dst`. Other tools: `vita-libs-gen`, `vita-elf-export`,
`vita-nid-check`, `psp2rela`. `vita-make-fself -na` (CMake `NOASLR`) disables ASLR, so code addresses
stay the same between runs; PCSX_AwO builds with `-c -s -na`. Stable addresses help when matching
crash dumps or JIT logs across runs (reason inferred, not stated by the project). Ninja-driven example: see `references/port-types.md` (Halo CE).

## 5. Cross-compiling third-party libraries

Install prefix is `$VITASDK/arm-vita-eabi`. Static libraries only (no shared objects).

Autotools:
```bash
export PKG_CONFIG=arm-vita-eabi-pkg-config     # wrapper sets PKG_CONFIG_LIBDIR, --static, --define-prefix
./configure --host=arm-vita-eabi --prefix=$VITASDK/arm-vita-eabi \
  --disable-shared --enable-static --without-pic
```
Some libs also need `--disable-pie`, or `sed -i 's/fPIC=yes/fPIC=no/' configure`. Old `config.sub`
files may not recognise `arm-vita-eabi` *(unverified)*; refresh them from the SDK's automake if so.

CMake:
```bash
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=$VITASDK/share/vita.toolchain.cmake \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$VITASDK/arm-vita-eabi -DBUILD_SHARED_LIBS=OFF \
  -DCMAKE_C_FLAGS="-std=gnu11 -Wno-error=implicit-function-declaration -Wno-error=int-conversion -Wno-error=incompatible-pointer-types"
cmake --build build && cmake --install build
```
The `-std=gnu11` and `-Wno-error=...` flags appear in nearly every official recipe because GCC 15
rejects old C that earlier compilers accepted. Newer CMake may need `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`.

Vita-specific tweaks seen in official recipes: curl `-DENABLE_IPV6=OFF -DCURL_DISABLE_SOCKETPAIR=ON
-DHAVE_FCNTL_O_NONBLOCK=OFF -DENABLE_THREADED_RESOLVER=OFF -DCURL_CA_BUNDLE="vs0:data/external/cert/CA_LIST.cer"`;
expat `-DXML_POOR_ENTROPY`; ffmpeg `--enable-pthreads`.

To make a reusable package, write a `VITABUILD` (`build()` / `package()` with `$prefix`, `$pkgdir`,
`$VITASDK`), run `vita-makepkg` (refuses root), install with `vdpm ./name-version-vita.pkg.tar.xz`.

## 6. Stub libraries and link order

The GCC driver auto-links `-lc` and the stubs for SceRtc, SceSysmem, SceKernelThreadMgr,
SceKernelModulemgr, SceIofilemgr, SceProcessmgr, SceLibKernel, SceNet, SceNetCtl and SceSysmodule.
Everything else must be listed. `-nostdlib` drops the automatic ones.

| Feature | Stub |
|---|---|
| video output / input | `SceDisplay_stub SceCtrl_stub SceTouch_stub SceMotion_stub` |
| GPU | `SceGxm_stub SceShaccCg_stub` (runtime Cg) |
| audio | `SceAudio_stub SceAudioIn_stub` |
| dialogs / app | `SceCommonDialog_stub SceIme_stub SceAppUtil_stub SceAppMgr_stub` |
| network | `SceHttp_stub SceSsl_stub` (SceNet is automatic) |
| power / DMA | `ScePower_stub SceKernelDmacMgr_stub` |
| video playback | `SceAvPlayer_stub` |
| kubridge plugin | `kubridge_stub`, or `kubridge_stub_weak` so the eboot starts without it (then check at boot; `runtime.md` section 4c) |
| module search (`_vshKernelSearchModuleByName`) | `SceVshBridge_stub` |

An "undefined reference to `sceFoo`" means the stub for the module exporting it is missing; find the
module in `vita-headers/db/*/*.yml`. Order matters: list dependents before their dependencies
(`-lvitaGL` before the stubs). "Undefined `__cxa_*` / operator delete" means `-lstdc++` is missing.
A `vita-elf-create` error about relocations means `-Wl,-q` is missing.

## 7. Packaging details

- **Title ID**: 9 characters, `XXXXYYYYY` (4 letters of author, 5 digits). Also the install
  folder `ux0:app/<TITLEID>`. Must be unique on a device.
- **LiveArea images** (indexed PNG-8; non-indexed gives install error `0x8010113D`):
  `sce_sys/icon0.png` 128x128 (no alpha), `livearea/contents/bg.png` 840x500 (some tools name it
  `bg0.png`), `livearea/contents/startup.png` 280x158 (alpha OK), optional `sce_sys/pic0.png`
  960x544 (256 colours). `template.xml` is UTF-8, small (limit around 32 KB, *unverified*).
  Minimal template: `assets/template.xml`. Style `a1` centres the startup image; `psmobile` puts it right.
- **param.sfo `ATTRIBUTE2` is 0 unless you set it.** Verified on the released SDK 2026.08
  (`vita-mksfoex -s TITLE_ID=X "x" out.sfo` writes `ATTRIBUTE2=0x0`; with `-d ATTRIBUTE2=12` it
  writes `0xC`). An unreleased `vita-toolchain` master was seen to default it to `0x0C`, so do not
  rely on the default either way: pass `-d ATTRIBUTE2=12` when the port needs more than 256 MiB and
  check the result with `scripts/check_vpk.py`, which prints the value. Other defaults: `CATEGORY=gd`,
  `ATTRIBUTE=0x8000`. Meaning of the bits is in `references/runtime.md`.
- A VPK is a zip: `eboot.bin`, `sce_sys/param.sfo`, `sce_sys/icon0.png`, `sce_sys/livearea/contents/*`
  and any extra `FILE` entries. Install with VitaShell from `ux0:/vpk/` or by FTP.
- Files the app reads at run time (a loading image, data) go outside `sce_sys/livearea/contents`: the
  installer treats that folder as LiveArea metadata and may drop files `template.xml` does not reference.
- For large asset sets, build a *slim* VPK too (same eboot, no assets) that falls back to
  `ux0:data/<name>/assets` when `app0:/assets` is absent; code iterations then reinstall in seconds
  (STSPSVITA: ~7 MB slim vs ~335 MB full).
- Run `scripts/check_vpk.py` on every build.

## 8. Reviving an old port on the current SDK

On 2026-09-30 Rinnegatamante merged "audited current-vitasdk compilation compatibility" commits into
eight older ports (fahrenheit-vita, partia-vita, Aerofoil-Vita, vitaVoyager, AbbayeDesMorts-Vita,
rinCheat, vitaWolfen, zikzak-vita). Each one names its SDK image by digest (`vitasdk/vitasdk` for
hardfp, `vitasdk/vitasdk-softfp` for so-loaders), lists the vitaGL/SDL variants it needs, and says
"Device runtime testing was not performed". Copy that habit: state the SDK image and that the
revived build was not run. What the commits had to change, most common first:

1. **Library names are case-sensitive on Linux.** Old Windows-built Makefiles used
   `SceAppmgr_stub`, `SceKernelDmacmgr_stub`, `opensles`, `vitagl`, `Mikmod`; the files are
   `SceAppMgr_stub`, `SceKernelDmacMgr_stub`, `OpenSLES`, `vitaGL`, `mikmod` (checked in a local
   2026.08 SDK). Check with `ls $VITASDK/arm-vita-eabi/lib | grep -i <name>`.
2. **Transitive dependencies** come from pkg-config now:
   `arm-vita-eabi-pkg-config --static --libs SDL2_mixer` (current SDL_mixer pulls FLAC, mikmod,
   webp, sharpyuv and more). CMake: `pkg_check_modules(MEDIA REQUIRED SDL2_mixer SDL2_image)` and
   link `${MEDIA_STATIC_LDFLAGS}`.
3. **Wrap the libraries in `-Wl,--start-group ... -Wl,--end-group`** to end order failures. Keep
   `-Wl,--whole-archive -lSceSysmodule_stub -Wl,--no-whole-archive` where the old build had it.
   Replace `--whole-archive -lpthread` with `-pthread`.
4. **vitaGL needs more libraries than old ports list**: `-lvitaGL -lvitashark -lSceShaccCgExt
   -ltaihen_stub -lSceShaccCg_stub -lSceKernelDmacMgr_stub -lSceAppUtil_stub -lmathneon`.
5. **vitaGL API drift**: two-argument `vglDrawObjects`, `vglVertexPointerMapped(size, ptr)`,
   `vglSwapBuffers` instead of `vglStartRendering`/`vglStopRendering`, `vglUseVram` removed,
   `vglShaderGxpBinary` for raw GXP. Build vitaGL with the flags the port relies on
   (`ENABLE_LEGACY_PIPELINE=1`, `HAVE_DISPLAY_LISTS=1`); see `references/vitagl.md` section 1.
6. **SDL 1.2 Vita calls were renamed**: `SDL_SetVideoModeScaling` → `SDL_VITA_SetVideoModeScaling`,
   `SDL_SetVideoModeBilinear` → `SDL_VITA_SetVideoModeBilinear`.
7. **GCC 14/15 turn old C warnings into errors**: implicit `main()` (write `int main(void)`);
   missing includes (`<string.h>`, `<fcntl.h>`, `<psp2/kernel/clib.h>`, `<psp2/io/stat.h>`);
   globals defined in headers (make them `extern` and define once; `-fno-common` is the default
   since GCC 10); `NULL` stored in integers; pointer/integer conversions without `(uintptr_t)`;
   function-pointer types that differ (`snprintf` with `int` instead of `size_t`); passing
   `char **` to `glShaderSource` (needs `const GLchar **`); declarations newlib hides without
   `_GNU_SOURCE` or `-D_POSIX_C_SOURCE=200809L`. Fix the source where you can. Where you cannot
   (so-loader internals), scope the escape to that file, as the commits do:
   `set_property(SOURCE loader/so_util.c APPEND PROPERTY COMPILE_OPTIONS
   -Wno-error=return-mismatch -Wno-error=incompatible-pointer-types)`.
8. **Packaging**: replace `7z a` rules and backslash paths with `vita-pack-vpk -s param.sfo -b
   eboot.bin -a src=dst` (section 4).
9. **A stub the SDK no longer ships** (`SceLibcBridge_stub` for so-loaders is absent from the
   2026.08 SDK) can be generated from a NID list: `vita-libs-gen -c nids.yml <outdir>` writes a
   CMake project you `add_subdirectory` (fahrenheit-vita runs it at configure time).

**Verified active projects (2026-10):** `Rinnegatamante/vitaQuake` (142 stars, active 2026-10-03) and
`Rocroverss/vitasoguide` (updated 2026-10-08) are both alive. No DOSBox-vita, GZDoom-vita, OpenMW-vita or
ECWolf-vita repos exist as of 2026-10 — use these for reference, not as starting points.
