// Thread census and CPU placement for a Vita port. Copy this pair into vita/src/ (or wherever the
// port keeps its platform glue) and call the hooks below from the entry point.
//
// Why this exists, in one paragraph: a Vita is a QUAD-core Cortex-A9 and a game may use THREE of the
// cores (SCE_KERNEL_CPU_MASK_USER_0/1/2 = 0x10000/0x20000/0x40000, _ALL = 0x70000). The 4th is
// reserved for system tasks; a kernel plugin (CapUnlocker) can release it. A port that never calls
// sceKernelChangeThreadCpuAffinityMask therefore does not "use one core" -- it uses all three by
// accident, with the scheduler deciding, and cannot answer "which core is the render thread on?"
// when that is the question that matters. This module makes placement explicit and observable, at
// the cost of one log line per thread.
//
// Three parts, deliberately separate because they have different costs:
//
//   1. CENSUS. Threads register themselves (name, role, preferred core); a report prints each one's
//      thread id and the mask it actually has. FREE, no plugin. It is a REGISTRY, not a kernel walk:
//      see the note on threads you did not create, below.
//   2. AFFINITY. sceKernelChangeThreadCpuAffinityMask, off by default and toggled at runtime so one
//      console session can A/B the layout. No plugin.
//   3. FOURTH CORE. Probed by TRYING SCE_KERNEL_CPU_MASK_SYSTEM and reading the mask back, never by
//      assuming a plugin is installed. No userland API for this exists.
//
// OPTIONAL kubridge clock control lives here too, but is COMPILED OUT unless TPV_HAVE_KUBRIDGE is
// defined. If you enable it, link -lkubridge_stub_weak (see references/runtime.md 4c).
//
// WHAT THIS CANNOT DO: enumerate threads it did not create. VitaSDK DECLARES SceKernelThreadInfo and
// never defines it, has no thread-enumeration function, and kubridge exposes no thread-list or
// affinity call (its exports are mem-block, cache-flush, unrestricted-memcpy, memprotect, exception
// handlers, and the two sysclock calls). So threads created inside SDL, vitaGL or a third-party
// library are invisible here. Register what you own, and let report() SAY it only sees registered
// threads -- a blank census that looks authoritative is worse than no census.
#pragma once

#include <cstdint>

namespace tpv::cpu {

enum class Core : uint8_t { User0 = 0, User1 = 1, User2 = 2, System = 3 };

// Roles the layout knows how to place. "Other" threads are counted but not pinned by default.
enum class Role : uint8_t { Main, Decode, Audio, Stream, Other };

const char* role_name(Role role) noexcept;

// Call once, before any thread that wants to be counted (typically at the top of main(), before the
// log opens). Probes the 4th core and reads the clocks. Safe to call twice.
void init() noexcept;

// Register the CALLING thread. Returns a handle for pinning, or -1 if the registry is full (32).
int register_thread(const char* name, Role role, Core preferred) noexcept;
// Register a thread by id, for a worker you created and can name.
int register_thread_id(int thid, const char* name, Role role, Core preferred) noexcept;

int wanted_mask(int handle) noexcept;

// Pin every registered thread to its preferred core / restore the user-core mask. pin_all returns how
// many masks the kernel accepted -- check it, because a refusal is silent otherwise. No-ops on failure.
int pin_all() noexcept;
int unpin_all() noexcept;
bool pinned() noexcept;
void set_pinned(bool on) noexcept;

// The 4th-core answer, measured. `accepted` is true only if the kernel both accepted the call AND the
// read-back still contains the system bit.
struct FourthCore {
  bool attempted = false;
  int set_result = 0; // 0 = accepted; on a plugin-less console this is 0x80000025 (ILLEGAL_CPU_MASK)
  int readback = 0;
  bool accepted = false;
  const char* verdict = "not probed";
};
const FourthCore& fourth_core() noexcept;

struct Clocks {
  int arm_mhz = 0;
  int kubridge_ok = 0; // 0 = kubridge's sysclock call unavailable
  int sys_mhz = 0;
};
Clocks read_clocks() noexcept;

#ifdef TPV_HAVE_KUBRIDGE
// Raises the system clock. Returns the frequency reported afterwards, or 0. Never call this in a
// shipping default: overclocking is a hardware-tuning step, and it raises power draw.
int try_kubridge_sysclock(int mhz) noexcept;
#endif

// printf-style sink the caller owns, so this file needs no logging dependency.
using LineSink = void (*)(const char* fmt, ...);
void report(LineSink sink) noexcept;

} // namespace tpv::cpu
