# Measuring a Vita port without fooling yourself

Every expensive mistake in this file was made by a confident engineer holding a real number that
answered the wrong question. The numbers below are from a real GameCube-on-Vita port, but the traps are
not engine-specific.

Read this before you optimise, and before you write down any performance or correctness claim.

## Ground rules

1. **Name the units and the conditions next to every number.** "200 ms/frame" means nothing without
   the emulator, the scene, the frame range and the draw count.
2. **An aggregate is not evidence.** A count of groups, runs, buckets or "mergeable" items only means
   something once you have written down the *complete* condition for the thing you want to do. If you
   instrument a partial condition, you will believe the partial answer.
3. **A screenshot filename is an expectation, not evidence.** `o_gameplay_3.png` is a name someone
   chose. Decode the pixels.
4. **An instrument that can silently not run is worse than none.** It produces an empty log that reads
   exactly like "nothing to report".
5. **Correct yourself in the document.** When a written claim turns out to be wrong, replace it and say
   it was wrong. A stale claim is worse than a gap, because the next person trusts it.

## 1. What Vita3K can and cannot tell you

| Question | Vita3K | Notes |
|---|---|---|
| Does it install, link and start? | yes | but hides memory-budget and permission problems |
| Is a specific draw, texture or viewport correct? | yes, well | a deterministic GL replay with pixel assertions is excellent here |
| Did the draw count change? | **yes** | this is the reliable performance signal |
| Did GPU work change? | partially | as draw count and resolve/copy counts, not as time |
| Did it get faster by 1–2 ms? | **no** | its own noise swamps it |
| Does it fit in the console's RAM? | **no** | the host has different limits |
| Will it behave the same on a Cortex-A9? | **no** | guest ARM runs roughly an order of magnitude faster on the host |

**Do not quote a Vita3K timing win.** A measured example: the same configuration produced **171–504 ms
per frame across runs**. Two "before/after" means of anything smaller than that range are noise, and a
single A/B pair cannot separate a real 20 ms gain from the emulator's variance. Emulator runs are for
*shape* — which stage dominates, how many draws, how many programs — not for elapsed time.

**What to do instead:** assert on things the emulator reproduces exactly (pixel values, draw counts,
state transitions, log order), and take anything time-based to hardware with
`references/agent-loop.md` section 2.

## 2. Instrument design: six failures worth not repeating

### 2.1 Gated on a frame number the run never reaches
A one-shot survey gated on `frame == 2760` produced **nothing**, because the input script ended at
frame ~2,400. Worse, a careless edit had nested the whole 120-frame timing window inside that gate, so
every `window @frame` line vanished too — the empty log was the only clue.

**Fix:** gate on a property of the data (`draws >= 350`), not on elapsed time or a frame index, and
latch on a counter so it fires exactly once. A frame number is a hidden dependency on how far the
driving script happens to get.

### 2.2 A threshold low enough to always fire fires on the wrong data
With the gate changed to `draws >= 100`, the survey fired at frame 240 — a **loading** frame with 163
draws — while the scene that mattered had 422–442. The measurement was internally consistent and
completely unrepresentative.

**Fix:** before trusting a sample, print what it sampled and compare it against the steady state. Take
several samples and report them all; six identical lines is evidence, one line is an anecdote.

### 2.3 Measuring an incomplete merge criterion (twice, in the same direction)
The question was "how much can draw calls be reduced". Three answers, each believed for a while:

| Criterion measured | Result | Why it was wrong |
|---|---|---|
| same pipeline only | 320 → 57 groups ("5.6×") | ignored texture bindings, which vary per draw |
| + same texture bind group | → 123 adjacent runs ("2.6×") | ignored that one draw carries **one uniform set** |
| + same uniform **content** | → **377 calls, 1.17×** | this one is the merge criterion |

The real answer was a sixth of the first claim. **Fix:** write the full legality condition down
*before* instrumenting it — here: same program, same samplers, same uniform content, contiguous
vertices — then measure exactly that. Any aggregate of a condition you have not fully stated is
fiction.

### 2.4 Comparing addresses instead of content
The frame's uniform arena reuses storage, so two draws with **different offsets** can hold **identical
bytes**. A survey comparing offsets found **0 of 441** adjacent pairs shared one; comparing content
found **69**. The first number would have closed the investigation for the wrong reason.

**Fix:** when the question is "are these two things the same", compare values, not identifiers,
pointers or offsets. And check what is baked per-item upstream before assuming a per-item field blocks
a merge — a per-vertex baked matrix does not.

### 2.5 Reading a `tail` as if it were the end of the story
A log printed a heartbeat at frames 0–9 and then every 300. A `tail` showed `frame=1800`, which looked
like the last one; counting found 39 occurrences running to frame 8,700. The false conclusion was "the
loop stopped".

**Fix:** count occurrences before concluding anything stopped. Print the maximum, not the last.

### 2.6 Concluding from "the screenshot did not change"
Two screenshots showing identical pixels is evidence about **when they were taken**, not about what the
game can do. A real example: three screenshots taken at 6–9 minutes showed a "frozen" menu, and the
state machine had in fact been advancing all along; it simply had no reason to change the pixels until
minute ~10.

**Fix:** add a state probe that logs transitions, and read it. A menu is a state machine; print
`(state, submenu)` on every change, once per distinct tuple, and the last line tells you where it
stopped. This settled in one run what several rounds of staring at images got wrong.

## 3. Reading a screenshot numerically

Do not ask a human "does this look right?" for a question a diff can answer, and do not read images into
a prompt when you need a number. This is cheap and answers most questions:

```python
from PIL import Image
import numpy as np

def compare(paths):
    prev = None
    for p in paths:
        a = np.asarray(Image.open(p).convert('RGB')).astype(np.int16)
        uniq = len(np.unique(a.reshape(-1, 3), axis=0))
        line = f'{p}: {uniq} distinct colours'
        if prev is not None and prev.shape == a.shape:
            changed = 100.0 * (np.abs(a - prev).max(axis=2) > 8).mean()
            line += f', {changed:.2f}% pixels changed vs previous'
        print(line)
        prev = a
```

What the numbers mean in practice:

| Observation | Interpretation |
|---|---|
| a few hundred bytes, one distinct colour | the capture is **blank** — not a dark game frame |
| thousands of distinct colours | untextured / flat-shaded output |
| tens of thousands of distinct colours | textured output |
| consecutive frames differ by **< 1 %** | a **frozen** screen: same screen, later in time |
| consecutive frames differ by **30–40 %** | a live scene with motion |

The blank-file signature is worth memorising: a 263-byte PNG is a failure, and an image that "looks
black" in a report that only lists file sizes is indistinguishable from a real dark scene.

**Caveat:** none of this tells you the picture is *correct*, only that it changed, is textured, or is
blank. Correctness needs an eye, a reference image, or a pixel assertion against a known-good render.

## 4. Turning a symptom into a named state

The general recipe that worked repeatedly:

1. **Find the state variable** the engine uses for the thing that is wrong (a phase index, a process
   id, a menu cursor) — not the thing you *think* is wrong.
2. **Log transitions, not levels.** One line per *distinct* `(a, b, c)` tuple. A 9,000-frame run then
   costs a handful of lines, and the last line is the state it ended in.
3. **Gate the probe on a change**, and keep it in the tree if it earns its place: ~15 lines that answer
   "which phase is it in" without a debugger are worth more than a paragraph of theory.
4. **Read the state before the handler runs**, not after, so "never entered" cannot be mistaken for
   "succeeded".
5. **Remove probes from a hot path** once the question is answered. Instrumentation in a per-draw or
   per-frame path is not free, and a survey left enabled for months becomes folklore.

## 5. Reporting what you measured

State, for every number: **what** was measured, **where** (emulator, hardware, host test), **under what
conditions** (scene, frame range, draw count), and **whether it reproduced**. Mark unproven gains as
unproven:

- "Removed ~440 heap allocations per frame. Correctness verified by the host suite (87 scenes, 14,242
  checks, 0 failed). **The timing gain is unproven**: the emulator's own noise is larger than the
  effect, and it has not been run on hardware."
- "Draw batching is **not** worth doing: 442 draws reach 377 calls, 1.17×, measured six times on real
  play-scene frames. The earlier 2.6× figure in this document was wrong; it ignored per-draw uniforms."

That last sentence is the kind of correction a reader needs more than a success story.
