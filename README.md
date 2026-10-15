# Vita Port Agent Skills

Agent skills for porting software to the Sony PS Vita (PSVita / PS TV) as VPK homebrew.

## Skills

This repository publishes two skills:

- **vita-port** — porting games to the PS Vita (VitaSDK, vitaGL, Android .so loader, static
  recomp, API emulation).
- **vita-app-port** — porting Android applications and non-game tools to the PS Vita (.so loader
  or native VitaSDK builds).

Install both:

```bash
npx skills add yannis100/vita-port-skill
```

## What it covers

- Feasibility triage: six port routes (native VitaSDK, vitaGL, cross-platform API emulation,
  Android .so loading, Java/TeaVM, static recompilation)
- Toolchain and CMake setup (including VitaSDK-softfp for Android .so ports)
- Memory budget, thread/core mapping, and platform-layer patterns
- OpenGL → vitaGL shader conversion and shader caching
- Input mapping (dual sticks, touch, gyro, PS TV pads)
- LiveArea packaging and VPK validation
- Debugging crashes (Vita3K, vitacompanion, vita-parse-core)

## Install

```bash
npx skills add yannis100/vita-port-skill
```

Install for a specific agent:

```bash
npx skills add yannis100/vita-port-skill --skill vita-port --agent amp
```

Install globally:

```bash
npx skills add yannis100/vita-port-skill -g
```

## Using the skill

Trigger it by mentioning the PS Vita, a Vita port, VPK, VitaSDK, vitaGL, HENkaku, Vita3K, or asking
to "port X to Vita". Or load it directly:

```
Use the vita-port skill. <your request>
```

## Contents

- `skills/vita-port/SKILL.md` — game porting workflow (triage → toolchain → skeleton → dependencies →
  platform layer → graphics → package → test → hand-off)
- `skills/vita-port/references/` — 9 reference docs: toolchain, runtime, vitagl, port-types,
  api-emulation, so-loader, static-recomp, java-teavm, debugging
- `skills/vita-port/scripts/` — audit_source.py, check_env.sh, check_vpk.py, make_placeholder_assets.py
- `skills/vita-port/assets/` — CMakeLists.vita.txt, template.xml, vita_runtime.c
- `skills/vita-port/evals/` — evaluation scenarios
- `skills/vita-app-port/SKILL.md` — app porting workflow for Android apps and non-game tools
  (triage → toolchain → skeleton → platform layer → graphics → package → test → hand-off)
- `skills/vita-app-port/references/` — app-runtime.md (IME, dialogs, permissions, paths, input)

## License

MIT — see [LICENSE](LICENSE).
