/*
 * vita_runtime.c - startup settings most Vita ports forget.
 *
 * Copy into <project>/vita/ and call vita_runtime_init() first thing in main().
 * Numbers are starting points. Budget the SUM of everything that lives in MAIN memory:
 *   newlib heap + thread stacks + sceLibc heap + vitaGL RAM pool + any AllocMemBlock arenas
 * against 256 MiB (default) or 365 MiB (param.sfo ATTRIBUTE2=12). See references/runtime.md.
 */
#include <psp2/kernel/clib.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/kernel/threadmgr.h>
#include <psp2/io/stat.h>
#include <psp2/power.h>

#include <stdio.h>
#include <string.h>

/* malloc() is backed by ONE memblock of this size taken at startup. If it exceeds free MAIN memory,
 * newlib silently ends up with an empty heap and every malloc fails (boot crash with no log). */
unsigned int _newlib_heap_size_user = 192 * 1024 * 1024;

/* Sony libc heap, used by Sony libraries (not by newlib malloc). */
unsigned int sceLibcHeapSize = 4 * 1024 * 1024;

/* Main-thread stack. The default is small and undocumented; deep recursion crashes silently. */
const unsigned int sceUserMainThreadStackSize = 8 * 1024 * 1024;

/* Lower = higher priority. 0x60 (96) is a common choice for game threads. */
const int sceUserMainThreadPriority = 0x60;

#define VITA_DATA_DIR "ux0:data/mygame"   /* <- change to your app's folder */

/* Create the writable data directory. app0: (the bundle and default cwd) is read-only. */
static void ensure_data_dir(void)
{
	sceIoMkdir("ux0:data", 0777);
	sceIoMkdir(VITA_DATA_DIR, 0777);
}

/* Common port clocks (Halo CE, Quake II, GTA SA, fheroes2). Return values are ignored on purpose:
 * whether a safe eboot may set these, and whether 500 MHz works, is unverified: test on hardware. */
static void set_clocks(void)
{
	scePowerSetArmClockFrequency(444);
	scePowerSetBusClockFrequency(222);
	scePowerSetGpuClockFrequency(222);
	scePowerSetGpuXbarClockFrequency(166);
}

/* Pin the calling thread to user core 0..2 (masks verified in a shipping port). */
void vita_pin_thread_to_core(int core)
{
	static const int masks[3] = { 0x10000, 0x20000, 0x40000 };
	if (core >= 0 && core < 3)
		sceKernelChangeThreadCpuAffinityMask(sceKernelGetThreadId(), masks[core]);
}

void vita_runtime_init(void)
{
	set_clocks();
	ensure_data_dir();
	sceClibPrintf("vita_runtime: heap=%u MiB stack=%u MiB\n",
	              _newlib_heap_size_user >> 20, sceUserMainThreadStackSize >> 20);
}
