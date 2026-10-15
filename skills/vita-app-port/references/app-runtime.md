# App Runtime on the PS Vita

This reference covers the platform layer for non-game applications: Android apps ported through
the .so loader, native VitaSDK tools, and CLI utilities.

## Foreground-only

The Vita has no background services. When the app leaves the foreground (Home button, LiveArea),
suspension pauses the process. State this in the port README so the end user is not surprised:
"running in background" is not possible. Long-running jobs (downloads, caches) must be chunked so
they resume on relaunch.

## Paths

| Kind | Prefix | Note |
|---|---|---|
| Read-only app binaries | `app0:` | bundle = the installed VPK payload |
| Writable user state | `ux0:data/<app>/` | created on first run; default for saves, logs, config |
| Higher-capacity | `uma0:` / `imc0:` | external/memory-card media; use when `ux0:` is small |

Android path redirects (do these in the `io.c` wrapper):
- `/proc/cpuinfo` and `/proc/meminfo` → bundled text files (or generate at first run)
- `/dev/urandom` → Vita PRNG or a seeded pool file
- `/sdcard/` and `/storage/emulated/0/` → `ux0:data/<app>/`
- all asset paths → `ux0:data/<app>/assets/` (AAssetManager bridge)

## Input

- Front touch panel: 1920x1080 sensor → 960x544 screen. Scale as
  `x = t.x * 960 / 1920`, `y = t.y * 544 / 1088`.
- Back panel and rear touch exist on the Vita 1000 only; PS TV has none.
- Physical buttons: Cross = confirm, Circle = back (or swap to Android A/B convention as the app
  expects), PS button = LiveArea. Do not remap travel: keep the app's confirm/back on Cross/Circle.
- No L2/R2/L3/R3 on Vita. Map or drop them in the settings page.
- Sticks: add a center deadzone (~±16 counts) before scaling.

## Text entry

- Use the Vita IME (`SceIme`) for single-line/text fields: it works with the on-screen keyboard and
  hardware kbd on PS TV. Init `SceIme` and handle the result event; do not fall back to raw scan
  codes for text.
- For multi-line, keep a Vita-native text control or a simple ListBox; do not port a full Android
  EditText.

## Dialogs and permissions

- File pickers and message boxes: `SceCommonDialog` (system dialogs) is the sanctioned path.
- Permissions: Android runtime permissions (storage, location) have no Vita equivalent. Read the
  requested data from `ux0:data/<app>/` without prompting, and document that "permission" prompts
  are not part of the Vita model.
- If the app insists on a Play Services check, stub the check and log it (`stderr`) instead of
  hiding it. Do not silently fake a success the app depends on.

## Networking

- Load `SCE_SYSMODULE_NET` and init `SceNet` before any socket use.
- HTTP(S): map to `SceHttp`/`SceSsl`; certificates live in the Vita's own store.
- If the app uses sockets directly, POSIX-style wrappers over `SceNet` work for most cases.
- Test reachability on hardware: Vita3K's network does not prove on-device behavior.

## Storage and I/O limits

- Open-file limit is low (~64 simultaneous). Serve large asset sets from RAM mappings or close
  files aggressively.
- Writes to `ux0:` wear the card; cache and batch small writes.
- Memory: ~365 MiB ceiling total; budget heap (`_newlib_heap_size_user`) and VRAM (vitaGL pool)
  explicitly. For CLI tools without graphics, a 64-128 MiB heap is usually enough.

## GLES notes (apps that draw)

- ES 1.00 dialect via vitaGL; bind attribute locations before link; size memory pools.
- Document the `libshacccg.suprx` requirement in `ur0:data/` for users (same note as games).
- For text-heavy UIs, software raster + `sceDisplay` blit can be simpler and cheaper than GLES.

## Audio output and codecs (media apps)

Native audio pattern proven in Vita homebrew (joel16/ElevenMPV and GrapheneCt/ElevenMPV-A):

- Output: `sceAudioOutOutput` with a dedicated decode thread and a small ring of per-channel
  buffers; set per-channel volume with `sceAudioOutSetVolume` (flags `SCE_AUDIO_VOLUME_FLAG_L_CH |
  R_CH`, clamp with `SCE_AUDIO_OUT_MAX_VOL`).
- Codecs: for portable formats, static-link `libopus`, `libvorbis`/`libvorbisfile`, `libogg`,
  `libxmp-lite`, header-only `dr_flac.h`, `mpg123` or `libmac`; this avoids pulling FFmpeg and is
  the proven lightweight set on Vita.
- There is no Android audio HAL on Vita: no `AudioTrack`, `OpenSL ES`, or `AAudio`. The .so loader
  route must stub or bridge those APIs; a native recompile sidesteps them entirely.
- Disambiguation: "ElevenMPV" is a native Vita music player — not the `mpv` media player and not an
  Android port. It is a reference for native audio output only; it does not exercise the .so loader
  or AAsset path.
- For streaming clients, prefer the native route (mpv + FFmpeg + curl/mbedTLS) over the .so loader:
  switchfin proves the full stack works natively — mpv renders via GXM (`MPV_RENDER_API_TYPE_GXM`), FFmpeg
  uses the SCE hardware decoders (`aac_vita`/`mp3_vita`/`h264_vita`), and curl needs a large physically
  contiguous pool (`sceClibMspace`, ~20 MiB) plus `CURLOPT_NOSIGNAL` set.

## Reference apps

| App type | Example | Notes |
|---|---|---|
| .so loader tool (community request) | PKForge-style managers | AAssetManager + touch only; simplest app class |
| CLI / daemon recompiled native | grep/tar-style tools | stock VitaSDK, no GLES, console only |
| Touch manager with GLES UI | emulator frontends | .so loader + vitaGL + IME for paths |
| Native audio/media app | joel16/ElevenMPV, GrapheneCt/ElevenMPV-A | native VitaSDK music player; sceAudioOut ring buffer + bundled codec static libs; template for media apps (not an Android port) |
| Streaming/media client | dragonflylee/switchfin | native Jellyfin client: borealis + NanoVG + mpv on GXM + FFmpeg hw decoders (`aac_vita`/`mp3_vita`/`h264_vita`); prefer native over .so loader for media apps |
| Native music player (libvita2d) | Perroabuelo/Material-Eleven | libvita2d fork of ElevenMPV; BGM-port screen-off audio, IME search, Cross/Circle auto-detect |
