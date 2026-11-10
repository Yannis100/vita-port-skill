# The agent loop: driving a real Vita from the agent

A port gets better in proportion to how fast you can go round the loop **build → deploy → look →
measure → fix**. On a desktop that loop is seconds. On a Vita it is minutes if you copy a VPK by
hand, and it is impossible if you are guessing at what the screen shows.

This file covers the three pieces that make the loop tight, in the order to adopt them. None of them
is a substitute for the discipline in `references/measurement.md` — they make the loop faster, and a
fast wrong loop is still wrong.

| Piece | What it gives you | Firmware constraint |
|---|---|---|
| `vita-agent-use` | an agent can **see and press** the console: screenshots, timed input, deploy, crash events | **3.65 only** |
| `psp2-tooling` | **profiling and debugger-grade** access: CPU/GPU profiles, breakpoints, core dumps | **3.65 only**, PCH-2000 tested |
| vitacompanion + file logging | the fallback that works on any HENkaku firmware | none |

**Read this first:** both tools are 3.65-specific and neither is tested on hardware by this skill. If
the user's console is on another firmware, say so before proposing them and plan on the fallback in
section 4 and `references/debugging.md` section 4.

## 1. `vita-agent-use` — let the agent see and press the console

[shoui520/vita-agent-use](https://github.com/shoui520/vita-agent-use) (GPL-3.0). Describes itself as
"computer use for AI agents, but for a PS Vita": the agent takes screenshots, presses buttons, moves
files, launches apps, reads crash dumps and writes code again, without a human touching the console.

**What it exposes to the agent**

| Capability | Use it for |
|---|---|
| See | screenshots of the game and LiveArea; installed apps, plugins, LiveArea layout |
| Play | precisely timed button, stick and front/rear multi-touch input, swipes, saved per-game macros |
| Deploy | verified file upload/download, VPK install, launch and close apps |
| Debug | crash-dump, error-dialog and log events **pushed** to the PC; CPU, FPS and memory metrics |
| Run | one command per test run: deploy, launch, wait for a log line or a crash, collect metrics, clean up |

**Architecture** (this matters when something does not work): three Vita-side plugins —
`vita_agent_kernel.skprx` (`*KERNEL`), `vita_agent_loader.suprx` (`*main`) and
`vita_agent_shell.suprx` (started by the loader, **not** listed in `config.txt`) — plus a Python CLI
on the PC that returns JSON. An optional `serve` process stays connected so the Vita pushes events
instead of the agent polling.

**Requirements:** Vita on 3.65, VitaShell, Python 3 with `cryptography`; to build the plugin yourself,
VitaSDK, CMake and Mbed TLS 3.6.7 source.

**Safety model — worth quoting to a user who is nervous about an agent on their console:** pairing
needs a physical OK on the Vita; **PS + SELECT stops the agent immediately**; writes to `tai/` and
`shell/` and deletion of apps/saves need on-device confirmation the agent cannot press; system
partitions are read-only and core plugins (HENkaku, YAMT, storagemgr) can never be overwritten;
`config.txt` edits require a diff review and are read back to verify; deletions go to trash and every
write is audited; transport is mutual TLS with a pinned certificate.

**Why this changes the porting workflow:** screenshots stop being a manual step. The agent can drive
the game to a specific screen, capture it, decide it is wrong, change the code and go again. That is
the difference between "I built a VPK" and "I iterated on rendering".

## 2. `psp2-tooling` — profiling and debugger access

[Grarak/psp2-tooling](https://github.com/Grarak/psp2-tooling) (GPL-3.0; read at 2026-10-30). Host
tools for a Vita **DevKit from Linux**, plus `retail-cp/`, which turns a retail Vita into a DevKit
for these tools. It ships an `AGENTS.md` written for an AI agent, which is the file to read first.

**Capabilities**, and the tool that provides each:

| Need | Tool |
|---|---|
| power on/off/cycle, console logs | `devkit/devkit_console.py` |
| serve `host0:`, launch/kill apps, input, control socket | `devkit/deci4p_host.py`, `devkit/psp2_input.py` |
| one whole boot: power up, launches, timed actions, power off | `devkit/session.sh` |
| install a VPK | `devkit/vpk_promoter/` |
| screenshots (HDMI or framebuffer) | `GRAB=` in `session.sh`, `devkit/vcp_capture.py` |
| CPU profile, whole system (all cores, kernel, syscalls) | `profile/sampler/`, `profile/psp2prof.py` |
| CPU profile, one process: flat + call stacks | `profile/vita_prof.py`, `profile/unwind_snapshots.py`, `profile/leaf_callers.py` |
| GPU: Razor live metrics, Razor frame captures (`.sgx`) | `razor/recorder/`, `razor/rzlv.py`, `razor/sgx_capture.py` |
| hardware breakpoints and watchpoints | `psp2_input.py` |
| core dumps on demand (`pdump`) with backtraces | `psp2_input.py` + `devkit/parse_core.py` |
| retail: files, resets, reports over USB (no FTP) | `devkit/retail_vita.sh` |

**Setup requirements** (state these before recommending it):

- Linux only.
- A **DevKit** on 3.65 with Ensō and taiHEN, *or* a retail Vita running `retail-cp/`; tested on a
  **PCH-2000 on 3.65**. DevKit capture needs the CP board mini-USB, the Vita's own USB (UDC) and
  HDMI into a capture card (MS2109 tested). **Target Manager must not be running.**
- Python 3 + pyusb, VitaSDK for on-device parts and profiler symbols, elfutils libdw for unwinding,
  perf or hotspot to view profiles, ffmpeg/arecord for HDMI.
- **Decrypted DevKit 3.65 (`3.650.011`) `os0:kd/` modules that the user must obtain themselves**:
  `dbgusb.elf`, `deci4p_dfmgr.elf`, `syslibtrace.elf`, `pamgr.elf`, `deci4p_ttyp.elf`, …
  The `365-TOOL` branch of [LiEnby/psvita-elfs](https://github.com/LiEnby/psvita-elfs/tree/365-TOOL/os0/kd)
  is where the community gets these (`dbgusb.skprx.elf`, `deci4p_dtracep.skprx.elf`,
  `deci4p_sdbgp.skprx.elf`, …). **These are Sony system modules.** Link them, do not redistribute
  them, and do not put them in a VPK or a repository — the same rule as `libshacccg.suprx`.
- **`retail-cp` patches 3.65 kernel code at fixed offsets**, so other firmware will most likely not
  work, and no Sony or built kernel modules are provided.

**Operating rules that will burn you if skipped** (from its `AGENTS.md`):

- **One owner.** Only one session drives the console. Two `deci4p_host.py` on the same link, or a
  second `session.sh`, break both.
- **Always power off.** Ctrl-C `session.sh` so it powers down. Do not leave the Vita on a static
  screen while you think — the OLED burns in.
- **Small register snapshots.** With `vita_prof.py --registers`, use `--stack-bytes 2048` (never above
  4096) and `--stack-depth 0`, 8 at most. Larger copies or deeper USTACK walks **overrun the stack and
  freeze the console**.
- **The exact ELF.** Profilers need the unstripped ELF of the same build that ran; another build's ELF
  gives wrong symbols silently. `unwind_snapshots.py` checks the ELF SHA-256 against the capture.
- **Absolute paths.** `RUN=` commands execute inside `OUT/launch-N/`, so a relative `HOST0` or ELF path
  points nowhere.
- **Short socket paths.** AF_UNIX is 108 bytes; `session.sh` uses `$XDG_RUNTIME_DIR`.
- **Console first.** When the app dies or a profile is empty, read `OUT/console.log` and `OUT/tty.log`
  before anything else.
- A boot costs about a minute before the app starts, so **decide what to measure, when, and for how
  long before you launch**.

**What this unlocks that Vita3K cannot:** a real per-core CPU profile, GPU job counters, and a
backtrace from a real console. That is the evidence `references/measurement.md` section 1 says Vita3K
cannot give you.

## 3. The MCP bridge, and what the guide gets wrong

The community guide that prompted this file suggests installing an MCP bridge so the agent can drive
these tools. Two corrections worth giving a user who read that guide:

- **The tools are 3.65-specific, and the guide does not say so.** `vita-agent-use` says "a PS Vita on
  3.65"; `psp2-tooling`'s retail path is tested only on a PCH-2000 on 3.65 and patches fixed kernel
  offsets. On any other firmware, neither is the answer.
- **An MCP server is optional.** Both tools are plain command-line programs that return JSON, which
  an agent can already execute. Do not make an MCP bridge a precondition for starting a port; wire it
  only if the user already runs an MCP-capable client and wants the event-push side.

## 4. Fallback: the loop without either tool

Many ports get shipped without either. This works on any HENkaku firmware:

```bash
# vitacompanion: FTP 1337, command server 1338 (references/debugging.md section 4)
curl -T game.vpk ftp://VITA_IP:1337/ux0:/data/game.vpk
echo 'launch MYGM00001' | nc VITA_IP 1338
echo 'destroy MYGM00001; screen on' | nc VITA_IP 1338   # stop cleanly
```

For the "what does the screen show" half, either take a screenshot with the console's own tool and
pull it over FTP (then analyse it numerically, `references/measurement.md` section 4), or have the app
**draw its own evidence**: a debug HUD, a boot log, and a heartbeat file. A port that writes
`ux0:data/<name>/log.txt` and a `heartbeat.txt` every couple of seconds is diagnosable with nothing
but FTP, which is why `references/debugging.md` section 4 recommends it.

## 5. Adopting the loop in the right order

1. **Before the first hardware run:** get the app to write its own log and heartbeat, and to draw
   something on screen at every stage. Without this, the first failure is indistinguishable from a
   black screen caused by any of six things (`references/debugging.md` section 1).
2. **Get the deploy path working:** upload + launch + log retrieval, by hand if necessary. Time it.
   If it is over a minute, automating it is worth the setup.
3. **Add screenshots** you can analyse numerically. Prefer this over asking the user to describe it.
4. **Only then** add `vita-agent-use` (see/press) or `psp2-tooling` (profile/debug), if the user's
   firmware supports them and the port has reached the point where the question is "why is this slow
   or wrong" rather than "does it start".
5. **Keep a scripted test harness.** An automated run that deploys, drives a fixed input script and
   captures screenshots at named moments is what turns a one-off success into a regression test. The
   tp-vita port's frame-counted input injector is the model: it lives in the app, reads a script file
   from `ux0:data/<name>/`, pushes each step through the pad API once per frame, logs every step with
   the frame it fired on, and deletes the script after reading it so it cannot leak into a manual run.

## What to tell the user

- Neither tool is required; the fallback in section 4 is what most ports use.
- Both are **3.65-only** and neither is tested on hardware by this skill.
- `psp2-tooling` needs Sony DevKit kernel modules the user must obtain themselves; do not redistribute.
- The safety model of `vita-agent-use` is the reason it is reasonable to point an agent at a console:
  pairing, kill switch, guarded config edits, read-only system partitions.
