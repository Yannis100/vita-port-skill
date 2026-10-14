#!/usr/bin/env bash
# Report whether a VitaSDK build environment is usable and print what to install.
# Usage: check_env.sh [pkg ...]   (extra vdpm package names to check)
set -u
ok()   { printf '  [ok]   %s\n' "$*"; }
miss() { printf '  [MISS] %s\n' "$*"; MISSING=1; }
MISSING=0

echo "VitaSDK environment"
if [ -n "${VITASDK:-}" ] && [ -d "$VITASDK" ]; then ok "VITASDK=$VITASDK"; else
  for d in "$HOME/vitasdk" /usr/local/vitasdk; do
    [ -x "$d/bin/arm-vita-eabi-gcc" ] && { export VITASDK="$d"; ok "VITASDK not set, found $d (export VITASDK=$d)"; break; }
  done
  [ -z "${VITASDK:-}" ] && miss "VITASDK not set and no SDK in ~/vitasdk or /usr/local/vitasdk"
fi
if [ -n "${VITASDK:-}" ]; then
  [ -x "$VITASDK/bin/arm-vita-eabi-gcc" ] && ok "arm-vita-eabi-gcc: $("$VITASDK/bin/arm-vita-eabi-gcc" -dumpversion)" || miss "arm-vita-eabi-gcc under \$VITASDK/bin"
  for t in vita-elf-create vita-make-fself vita-mksfoex vita-pack-vpk; do
    [ -x "$VITASDK/bin/$t" ] && ok "$t" || miss "$t"
  done
  [ -f "$VITASDK/share/vita.toolchain.cmake" ] && ok "vita.toolchain.cmake" || miss "share/vita.toolchain.cmake"
  [ -f "$VITASDK/share/vita.cmake" ] && ok "vita.cmake" || miss "share/vita.cmake"
  case ":$PATH:" in *":$VITASDK/bin:"*) ok "\$VITASDK/bin on PATH";; *) miss "\$VITASDK/bin not on PATH (export PATH=\$VITASDK/bin:\$PATH)";; esac
fi
for t in cmake make git python3; do command -v "$t" >/dev/null && ok "$t" || miss "$t"; done
command -v vdpm >/dev/null && ok "vdpm ($(vdpm status 2>/dev/null | head -1))" || miss "vdpm (git clone https://github.com/vitasdk/vdpm)"
command -v ninja >/dev/null && ok "ninja (optional)" || echo "  [info] ninja not found (only needed by Ninja-based ports)"

if [ -n "${VITASDK:-}" ] && [ -d "$VITASDK/arm-vita-eabi" ]; then
  echo "Libraries in \$VITASDK/arm-vita-eabi"
  for p in "$@"; do :; done
  for l in libSDL2.a libvitaGL.a libvitashark.a libmathneon.a libz.a libpng.a libfreetype.a libopenal.a; do
    [ -f "$VITASDK/arm-vita-eabi/lib/$l" ] && ok "$l" || echo "  [none] $l"
  done
fi

if [ "$MISSING" -ne 0 ]; then
  cat <<'MSG'

Install (Linux / WSL2):
  sudo apt-get install make git-core cmake python3 curl
  export VITASDK=$HOME/vitasdk; export PATH=$VITASDK/bin:$PATH
  git clone https://github.com/vitasdk/vdpm && cd vdpm && ./bootstrap-vitasdk.sh
  vdpm install sdl2 vitaGL vitaShaRK SceShaccCgExt libmathneon taihen zlib libpng
Or use docker:  docker run --rm -v "$PWD:/workspace" vitasdk/vitasdk:2026.08 ...
If no SDK can be installed here, write the CMake and platform code anyway and report the build as NOT run.
MSG
  exit 1
fi
echo "Environment OK"
