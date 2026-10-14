#!/usr/bin/env python3
"""Scan a source tree for code that does not map cleanly onto the PS Vita.

Prints findings grouped by category with the usual remedy, plus a feasibility hint.
It is a grep, not a compiler: expect false positives (comments, ifdef'd-out code) and read the hits.

Usage: audit_source.py <dir> [--max-hits N] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".glsl", ".vert", ".frag", ".vs", ".fs", ".m", ".mm", ".java", ".kt"}
JVM_EXTS = {".java", ".kt"}
SKIP_DIRS = {".git", "build", "third_party", "thirdparty", "extern", "external", "vendor", "node_modules", ".svn"}

# category: (severity, remedy, [regexes])
RULES: dict[str, tuple[str, str, list[str]]] = {
    "process/posix gaps": (
        "high",
        "fork/exec return ENOSYS; no file-backed mmap (read files instead); anonymous mmap/mprotect "
        "can be emulated on kubridge (runtime.md section 4c); otherwise remove or stub",
        [r"\bfork\s*\(", r"\bexecv?[lpe]*\s*\(", r"\bmmap\s*\(", r"<sys/mman\.h>", r"\bposix_spawn\b", r"\bpopen\s*\("],
    ),
    "dynamic loading / JIT": (
        "high",
        "no dlopen without vita-libdl; link statically (e.g. XASH_STATIC style). An ARM JIT works with Vita "
        "executable memory (runtime.md section 4b); an x86/x64 JIT backend must fall back to its interpreter",
        [r"\bdlopen\s*\(", r"\bLoadLibrary[AW]?\s*\(", r"\bmprotect\s*\(", r"\bVirtualAlloc\b", r"PROT_EXEC"],
    ),
    "x86 specifics": (
        "high",
        "port intrinsics to NEON or scalar; Vita is ARMv7 Cortex-A9 little-endian",
        [r"<[a-z]*mmintrin\.h>", r"<immintrin\.h>", r"\b__m128", r"\b_mm_\w+\("],
    ),
    "inline assembly (check the target ISA)": (
        "medium",
        "x86 asm must become NEON or scalar C; ARMv7/NEON asm (mcr/mrc, ldr/str, v* ops, ARM dynarecs) can stay if it is guarded for __arm__",
        [r"\b__asm__\b|\basm\s+volatile\b|\b__asm\b"],
    ),
    "64-bit assumptions": (
        "medium",
        "long, size_t and pointers are 32-bit on Vita; use int64_t/intptr_t and fixed-width types",
        [r"sizeof\s*\(\s*long\s*\)\s*==\s*8", r"\(\s*(?:u?int|unsigned)\s*\)\s*\w*ptr\b", r"\buint64_t\s*\)\s*\w*\s*&\s*0x"],
    ),
    "threading / cores": (
        "medium",
        "Vita has 3 user cores; pthreads work with -pthread; set explicit stack sizes; no std::thread::hardware_concurrency guarantee",
        [r"hardware_concurrency", r"_SC_NPROCESSORS", r"sched_setaffinity|pthread_setaffinity_np", r"\bstd::(thread|async)\b"],
    ),
    "filesystem / paths": (
        "medium",
        "write only to ux0:data/<app>/; app0: is read-only and is the cwd; avoid getenv(HOME), XDG paths, std::filesystem tricks",
        [r"\bgetenv\s*\(\s*\"(HOME|XDG_\w+|APPDATA|USERPROFILE)\"", r"\bstd::filesystem\b", r"\bgetpwuid\b", r"\brealpath\s*\(", r"\bsymlink\s*\("],
    ),
    "OpenGL beyond vitaGL (GL 3+ / desktop)": (
        "high",
        "vitaGL is ES 2.0-class: no 3D textures, MRT, glTexStorage, fences, geometry/compute shaders, transform feedback; rewrite or drop the feature",
        [
            r"glTexImage3D|glTexStorage[123]D|glTexSubImage3D", r"glDrawBuffers\b", r"glFenceSync|glClientWaitSync",
            r"GL_GEOMETRY_SHADER|GL_COMPUTE_SHADER|GL_TESS_", r"glDispatchCompute", r"glBeginTransformFeedback",
            r"glBindFragDataLocation", r"glVertexAttribIPointer", r"glPrimitiveRestartIndex|GL_PRIMITIVE_RESTART",
            r"glLogicOp\b", r"glGetTexImage\b", r"glDrawArraysIndirect|glMultiDraw\w*Indirect",
        ],
    ),
    "GLSL needing a rewrite for GLSL ES 1.00": (
        "medium",
        "vitaGL translates ES-1.00-style GLSL; rewrite #version 130+ shaders: attribute/varying, texture2D, gl_FragColor, no layout()",
        [r"#\s*version\s+(1[3-9]\d|[2-4]\d\d)", r"\blayout\s*\(", r"\btexelFetch\b", r"\btextureSize\b", r"\bflat\s+(in|out)\b", r"\buniform\s+\w*Block\b|\bstd140\b"],
    ),
    "fixed-function / legacy GL (works in vitaGL, check flags)": (
        "info",
        "supported; display lists need HAVE_DISPLAY_LISTS=1, >2 texture units need HAVE_HIGH_FFP_TEXUNITS=1; needs libshacccg.suprx at runtime",
        [r"\bglBegin\s*\(", r"glNewList|glCallList", r"glMatrixMode|glLoadIdentity", r"GL_TEXTURE[2-7]\b"],
    ),
    "Vulkan / DirectX / Metal": (
        "high",
        "no direct path: needs a new GXM backend (see port-types.md, Halo CE) or an existing GL/GLES renderer in the engine",
        [r"<vulkan/", r"\bvk[A-Z]\w+\(", r"<d3d(9|1[0-2])\.h>", r"<d3d8\.h>", r"<Metal/"],
    ),
    "char signedness / enums": (
        "info",
        "plain char is unsigned on ARM: compile x86-written code with -fsigned-char; some code needs -fno-short-enums",
        [r"\bchar\s+\w+\s*=\s*-\d", r"\bchar\s*\*?\s*\w+\s*;\s*//.*signed"],
    ),
    "networking": (
        "info",
        "BSD sockets work after SceNet load; avoid fcntl(O_NONBLOCK) tricks, socketpair, pipe2, IPv6",
        [r"\bsocketpair\s*\(", r"\bpipe2?\s*\(", r"AF_INET6", r"\bepoll_\w+\("],
    ),
    "Java: no JVM on Vita (TeaVM C backend route)": (
        "medium",
        "translate with TeaVM's C backend and a Vita libGDX backend; see references/java-teavm.md",
        [r"^\s*import\s+com\.badlogic\.gdx\.", r"^\s*public\s+static\s+void\s+main\s*\(\s*String"],
    ),
    "Java: desktop-only APIs TeaVM cannot translate": (
        "high",
        "replace or stub (classpath shadowing): AWT/Swing/ImageIO (write a plain-Java image decoder), NIO channels/mmap, JNI/System.loadLibrary",
        [r"\bjava\.awt\.|\bjavax\.swing\.|\bjavax\.imageio\.", r"\bBufferedImage\b|\bImageIO\.", r"\bFileChannel\b|\bMappedByteBuffer\b|\bjava\.nio\.channels\.", r"\bSystem\.loadLibrary\s*\("],
    ),
    "Java: reflection (needs TeaVM 0.16 + reflection policy)": (
        "medium",
        "TeaVM 0.16 C supports method/constructor reflection, forName, newInstance, Proxy if the reflection policy keeps the classes; 0.15 had fields only (use factories)",
        [r"\bClass\.forName\s*\(", r"\.newInstance\s*\(", r"\.getDeclared(Method|Constructor)s?\s*\(|\.getMethods?\s*\(", r"\bjava\.lang\.reflect\.(Method|Constructor|Proxy)\b", r"\bcom\.thoughtworks\.xstream\b|\bcom\.esotericsoftware\.kryo\b"],
    ),
    "Java: runtime class loading / bytecode generation": (
        "high",
        "no JIT and no class loading under AOT: remove ASM/ByteBuddy/cglib, defineClass, script engines (Nashorn, Rhino, Groovy, LuaJ JSE compiler)",
        [r"\bdefineClass\s*\(", r"\bnew\s+URLClassLoader\b", r"\borg\.objectweb\.asm\b|\bnet\.bytebuddy\b|\bnet\.sf\.cglib\b|\bjavassist\b", r"\bjavax\.script\.|\borg\.mozilla\.javascript\b|\bgroovy\.lang\b"],
    ),
    "Java: GL 3 through libGDX": (
        "high",
        "Gdx.gl30 needs a GL30 backend over vitaGL's subset; texture arrays/integer textures/GLSL 330 need a renderer rewrite",
        [r"\bGdx\.gl30\b|\bGL30\.", r"\buseGL30\s*=\s*true"],
    ),
    "Java: threads become cooperative fibers": (
        "info",
        "TeaVM's C runtime runs Java threads as fibers on one OS thread; blocking IO or busy loops stall the render loop",
        [r"\bnew\s+Thread\s*\(", r"\bExecutors\.\w+\(", r"\bCompletableFuture\b"],
    ),
    "windowing libs": (
        "info",
        "SDL2 is the easiest path; GLFW/SFML/X11/Win32 need replacing",
        [r"<GLFW/", r"<SFML/", r"<X11/", r"<windows\.h>", r"<Cocoa/"],
    ),
}


def scan(root: Path, max_hits: int):
    findings: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    files = 0
    compiled = {cat: [re.compile(p) for p in pats] for cat, (_s, _r, pats) in RULES.items()}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files += 1
        # "Java:" rules only make sense on JVM sources; other rules apply everywhere.
        is_jvm = path.suffix.lower() in JVM_EXTS
        active = {cat: regs for cat, regs in compiled.items() if is_jvm or not cat.startswith("Java:")}
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("//", "*", "/*", "#pragma")) and "#version" not in line:
                continue
            for cat, regs in active.items():
                if any(r.search(line) for r in regs):
                    counts[cat] += 1
                    if len(findings[cat]) < max_hits:
                        findings[cat].append((str(path.relative_to(root)), lineno, line.strip()[:140]))
    return files, findings, counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", type=Path)
    ap.add_argument("--max-hits", type=int, default=5, help="examples shown per category")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not args.dir.is_dir():
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 2
    files, findings, counts = scan(args.dir, args.max_hits)

    if args.json:
        print(json.dumps({"files": files, "counts": counts, "findings": findings}, indent=2))
        return 0

    print(f"Scanned {files} source files under {args.dir}\n")
    order = {"high": 0, "medium": 1, "info": 2}
    shown = False
    for cat in sorted(findings, key=lambda c: (order[RULES[c][0]], c)):
        sev, remedy, _ = RULES[cat]
        shown = True
        print(f"[{sev.upper()}] {cat}: {counts[cat]} hit(s)")
        print(f"    remedy: {remedy}")
        for f, n, l in findings[cat]:
            print(f"    {f}:{n}: {l}")
        print()
    if not shown:
        print("No known Vita blockers found. Still check memory use, GL level and assets by hand.")
    high = [c for c in findings if RULES[c][0] == "high"]
    print("Feasibility hint:")
    if not high:
        print("  Looks tractable. Next: pick SDL2 or vitaGL, build a skeleton VPK, then port the platform layer.")
    else:
        print("  High-severity categories present: " + "; ".join(high))
        print("  Decide per category whether to patch, stub, or decline the port (see SKILL.md step 1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
