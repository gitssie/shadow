"""Pin the two hook decisions that caused the app-launch crashes.

Both fixes are behavioural decisions living inside Logos-preprocessed .x
sources, so this extracts the real function bodies (and the constants they
depend on) and drives them on the host with synthetic inputs:

  * shdw_svc_site_branch_opcode  -- which branch encoding a redirected svc site
    gets. Picking BL for a frameless leaf destroys x30, turning the leaf's own
    `ret` into a self-loop (My Sun Life, 0x8BADF00D, pc == lr).
  * shdw_image_span_ex           -- the vm span recorded for one image. A union
    over all segments stretches a shared-cache image across its whole subcache,
    so every later stock image reads as restricted and dlsym returns NULL for
    stock symbols (GasBuddy/Oxford kSec*, CBC News swift_task_escalate).

The span cases below use the shapes measured on the device, including the
liblzma.5.dylib one that produced an 848 MB span before the fix.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVC = ROOT / "src/ShadowCore.dylib/hooks/Universal/svc_patch.x"
DYLD = ROOT / "src/ShadowCore.dylib/hooks/Universal/dyld.x"


def anchor_pattern(needle):
    """Regex for `needle`, tolerant of reformat spacing (see verify-svc-self-image)."""
    return r"\s*".join(
        re.escape(tok) for tok in re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", needle)
    )


def anchor(text, needle, start=0):
    match = re.search(anchor_pattern(needle), text[start:])
    if match is None:
        raise ValueError(f"anchor not found: {needle!r}")
    return start + match.start()


def body(source, signature):
    """Brace-matched body (signature included) of one function."""
    head = anchor(source, signature)
    start = anchor(source, "{", head)
    depth, end = 1, start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[head:end]


def define(source, name):
    """The full text of `#define <name> ...`, so the test uses the real value."""
    match = re.search(rf"^#define\s+{re.escape(name)}\s+(.*)$", source, re.M)
    if match is None:
        raise ValueError(f"#define {name} not found")
    return match.group(0)


svc_src = SVC.read_text()
dyld_src = DYLD.read_text()

branch_fn = body(svc_src, "static uint32_t shdw_svc_site_branch_opcode(")
leaf_fn = body(svc_src, "static long shdw_svc_leaf_sysno(")
delta_fn = body(svc_src, "static BOOL shdw_svc_next_function_offset(")
image_fn = body(svc_src, "static void shdw_svc_patch_image(")
slide_fn = body(svc_src, "static BOOL shdw_svc_slid_address(")
patch_site_fn = body(svc_src, "static void shdw_svc_try_patch_site(")
patch_memory_fn = body(svc_src, "static void shdw_svc_patch_memory(").replace('@"', '"')
span_fn = body(dyld_src, "static BOOL shdw_image_span_ex(")

# The extracted bodies reference these; take them from the sources verbatim so a
# changed constant is a test failure rather than a silently stale expectation.
svc_defines = "\n".join(
    define(svc_src, n) for n in ("SHDW_SVC_RET", "SHDW_SVC_B", "SHDW_SVC_BL")
)
span_defines = define(dyld_src, "SHDW_SPAN_MAX_BYTES")

HARNESS = """
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <pthread.h>

typedef int BOOL;
#define YES 1
#define NO 0
#define MH_MAGIC_64 0xfeedfacf
#define LC_SEGMENT_64 0x19

struct load_command { uint32_t cmd; uint32_t cmdsize; };
struct segment_command_64 {
    uint32_t cmd; uint32_t cmdsize;
    char segname[16];
    uint64_t vmaddr; uint64_t vmsize;
    uint64_t fileoff; uint64_t filesize;
    uint32_t maxprot; uint32_t initprot; uint32_t nsects; uint32_t flags;
};
/* The extracted body casts to the 64-bit header for load-command pointer
   arithmetic, so both names must exist with the same layout (32 bytes). */
struct mach_header {
    uint32_t magic; uint32_t cputype; uint32_t cpusubtype; uint32_t filetype;
    uint32_t ncmds; uint32_t sizeofcmds; uint32_t flags; uint32_t reserved;
};
struct mach_header_64 {
    uint32_t magic; uint32_t cputype; uint32_t cpusubtype; uint32_t filetype;
    uint32_t ncmds; uint32_t sizeofcmds; uint32_t flags; uint32_t reserved;
};

/* Constants lifted from the production sources. */
__SVC_DEFINES__
__SPAN_DEFINES__

static int failures = 0;
#define CHECK(cond, ...) do { if (!(cond)) { failures++; \\
    printf("FAIL: "); printf(__VA_ARGS__); printf("\\n"); } } while (0)

/* ---- extracted production logic ---- */
__SPAN_FN__

__BRANCH_FN__

#define SHADW_RAW_CAT_PATH 1
#define SHADW_RAW_CAT_AT 2
#define SHADW_RAW_CAT_KEVENT 3
#define SHADW_RAW_CAT_KEVENT64 4
static int shdw_raw_syscall_category(int n) {
    if(n == 5) return SHADW_RAW_CAT_PATH;
    if(n == 463) return SHADW_RAW_CAT_AT;
    if(n == 363) return SHADW_RAW_CAT_KEVENT;
    if(n == 369) return SHADW_RAW_CAT_KEVENT64;
    return 0;
}
__LEAF_FN__
__DELTA_FN__

#define CPU_TYPE_ARM64 0x100000c
#define LC_FUNCTION_STARTS 0x26
#define SECTION_TYPE 0xff
#define S_REGULAR 0
#define S_ATTR_PURE_INSTRUCTIONS 0x80000000u
#define VM_PROT_READ 1
#define VM_PROT_EXECUTE 4
#define VM_PROT_WRITE 2
#define VM_REGION_BASIC_INFO_COUNT_64 9
#define VM_REGION_BASIC_INFO_64 9
#define MACH_PORT_NULL 0
#define KERN_SUCCESS 0
typedef struct { int protection; } vm_region_basic_info_data_64_t;
typedef int mach_msg_type_number_t;
typedef uintptr_t vm_address_t;
typedef size_t vm_size_t;
#ifndef __APPLE__
typedef unsigned int mach_port_t;
#endif
typedef int kern_return_t;
typedef int vm_prot_t;
#define FALSE 0
#define VM_PROT_COPY 16
typedef int* thread_act_array_t;
typedef void* vm_region_info_t;
static unsigned region_queries;
static int query_result, query_protection = VM_PROT_READ | VM_PROT_WRITE | VM_PROT_EXECUTE;
static int mach_task_self(void) { return 1; }
static int vm_region_64(int task, vm_address_t* addr, vm_size_t* size, int flavor, vm_region_info_t info, mach_msg_type_number_t* count, mach_port_t* object) {
    region_queries++; (void)task; (void)flavor; (void)count;
    *addr &= ~(uintptr_t)4095; *size = 4096; *object = 0;
    ((vm_region_basic_info_data_64_t*)info)->protection = query_protection;
    return query_result;
}
static void shdw_svc_dispose_object(mach_port_t* object) { *object = 0; }
#define vm_page_size 4096
struct section_64 {
    char sectname[16], segname[16];
    uint64_t addr, size;
    uint32_t offset, align, reloff, nreloc, flags, reserved1, reserved2, reserved3;
};
struct linkedit_data_command { uint32_t cmd, cmdsize, dataoff, datasize; };
static unsigned admitted;
static uintptr_t admitted_address;
static int admitted_protection;
static void capture_patch_memory(uintptr_t a, size_t n, size_t p, int prot, const char* path) {
    (void)p; (void)path; admitted_protection = prot;
    CHECK(n == 12, "only complete tiny functions may be admitted");
    admitted++; admitted_address = a;
}
__SLIDE_FN__
__IMAGE_FN__

static _Atomic BOOL shdw_svc_far_site_seen;
static BOOL shdw_svc_is_instruction(uint32_t insn) { return (insn & 0xffe0001fu) == 0xd4000001u; }
static int mach_port_deallocate(int task, mach_port_t port) { (void)task; (void)port; return 0; }
static void shdw_svc_trampoline_80(void) {}
static unsigned cache_invalidations;
static void sys_icache_invalidate(void* p, size_t n) { (void)p; CHECK(n == 4, "only svc word cache must be invalidated"); cache_invalidations++; }
__PATCH_SITE_FN__
static pthread_mutex_t shdw_svc_patch_lock = PTHREAD_MUTEX_INITIALIZER;
static int suspend_ok = 1;
static unsigned suspensions, resumes, disposals, protect_calls;
static int protect_fail_first, protect_fail_all;
static vm_prot_t protections[8];
static BOOL shdw_svc_suspend_others(thread_act_array_t* t, mach_msg_type_number_t* c, mach_port_t* p) {
    suspensions++; *t = (int*)1; *c = 1; *p = 1; return suspend_ok;
}
static void shdw_svc_resume_others(thread_act_array_t t, mach_msg_type_number_t c, mach_port_t p) {
    (void)t; (void)c; (void)p; resumes++;
}
static void shdw_svc_dispose_thread_list(thread_act_array_t t, mach_msg_type_number_t c, mach_port_t p) {
    (void)t; (void)c; (void)p; disposals++;
}
static int vm_protect(int task, uintptr_t address, size_t size, int maximum, vm_prot_t protection) {
    (void)task; (void)address; CHECK(size == 12, "only candidate's write range must be protected");
    CHECK(!maximum, "maximum protection must not change");
    if(protect_calls < 8) protections[protect_calls] = protection;
    protect_calls++;
    return protect_fail_all || (protect_fail_first && protect_calls == 1);
}
static void NSLog(const char* format, ...) { (void)format; }
__PATCH_MEMORY_FN__
static uint32_t patch_fixture[3];
static void reset_patch_fixture(void) {
    patch_fixture[0] = 0xd28000b0u; patch_fixture[1] = 0xd4001001u; patch_fixture[2] = 0xd65f03c0u;
    cache_invalidations = protect_calls = suspensions = resumes = disposals = region_queries = 0;
    protect_fail_first = protect_fail_all = query_result = 0; suspend_ok = 1;
    query_protection = VM_PROT_READ | VM_PROT_WRITE | VM_PROT_EXECUTE;
    atomic_store(&shdw_svc_far_site_seen, NO);
}

typedef struct { const char* name; uint64_t vmaddr; uint64_t vmsize; } seg_spec_t;

static struct mach_header* make_image(const seg_spec_t* segs, int n) {
    size_t need = sizeof(struct mach_header) +
                  (size_t)n * sizeof(struct segment_command_64);
    char* buf = (char*)calloc(1, need);
    struct mach_header* mh = (struct mach_header*)buf;
    mh->magic = MH_MAGIC_64;
    mh->ncmds = (uint32_t)n;
    mh->sizeofcmds = (uint32_t)(n * sizeof(struct segment_command_64));
    struct segment_command_64* sc =
        (struct segment_command_64*)(buf + sizeof(struct mach_header));
    for (int i = 0; i < n; i++) {
        size_t len = strlen(segs[i].name);
        if (len > 15) len = 15;
        sc[i].cmd = LC_SEGMENT_64;
        sc[i].cmdsize = sizeof(struct segment_command_64);
        memcpy(sc[i].segname, segs[i].name, len);
        sc[i].vmaddr = segs[i].vmaddr;
        sc[i].vmsize = segs[i].vmsize;
    }
    return mh;
}

int main(void) {
    uintptr_t base = 0, end = 0;
    BOOL oversized = NO, ok = NO;

    /* ---- svc branch encoding ---- */
    CHECK(shdw_svc_site_branch_opcode(SHDW_SVC_RET) == SHDW_SVC_B,
          "frameless leaf (fallthrough == ret) must encode B, got %#x",
          shdw_svc_site_branch_opcode(SHDW_SVC_RET));
    CHECK(shdw_svc_site_branch_opcode(0x91000000U) == 0,
          "unknown continuation must refuse a branch, got %#x",
          shdw_svc_site_branch_opcode(0x91000000U));

    /* Idempotence: a patched site must never re-match the svc scan, or the
       scanner rewrites its own output on the next image event. */
    uint32_t svc_mask = 0xFFE0001FU, svc_opcode = 0xD4000001U;
    uint32_t enc[2] = { shdw_svc_site_branch_opcode(SHDW_SVC_RET),
                        shdw_svc_site_branch_opcode(0x91000000U) };
    for (int i = 0; i < 2; i++)
        CHECK((enc[i] & svc_mask) != svc_opcode,
              "emitted encoding %#x would re-match the svc pattern", enc[i]);

    /* Real frameless-wrapper and branch-over-constant instruction shapes. */
    uint32_t safe[] = {0xd28000b0u, 0xd4001001u, 0xd65f03c0u};
    uint32_t dynamic[] = {0xaa0003e8u, 0xaa0003f0u, 0xd4001001u,
                          0x9a9f37e9u, 0xf100053fu, 0xfa400904u,
                          0xda9fd000u, 0xd65f03c0u, 0xd65f03c0u};
    uint32_t skipped[] = {0x14000002u, 0xd2800030u, 0xd4001001u, 0x14000001u};
    CHECK(shdw_svc_leaf_sysno(safe, 3) == 5, "known supported leaf must remain supported");
    safe[0] = 0x528000b0u;
    CHECK(shdw_svc_leaf_sysno(safe, 3) == 5, "w16 constant leaf must remain supported");
    safe[0] = 0xd2800030u;
    CHECK(shdw_svc_leaf_sysno(safe, 3) < 0, "unsupported syscall must not change");
    safe[0] = 0xaa0003f0u;
    CHECK(shdw_svc_leaf_sysno(safe, 3) < 0, "register sysno must not change");
    safe[0] = 0xd2a000b0u;
    CHECK(shdw_svc_leaf_sysno(safe, 3) < 0, "shifted constant must not be misread");
    CHECK(shdw_svc_leaf_sysno(dynamic, 9) < 0, "frameless cset continuation must stay untouched");
    CHECK(shdw_svc_leaf_sysno(skipped, 4) < 0, "branch-skipped constant must stay untouched");
    CHECK(shdw_svc_leaf_sysno(NULL, 3) < 0, "missing function must be refused");
    safe[0] = 0xd28000b0u;
    safe[1] = 0xd4000001u;
    CHECK(shdw_svc_leaf_sysno(safe, 3) < 0, "unknown svc convention must not change");
    safe[1] = 0xd4001001u;
    safe[2] = 0x9a9f37e9u;
    CHECK(shdw_svc_leaf_sysno(safe, 3) < 0, "non-ret continuation must not change");
    safe[2] = 0xd65f03c0u;

    const uint8_t valid_delta[] = {0x80, 0x04, 12, 0};
    const uint8_t truncated_delta[] = {0x80};
    const uint8_t overflow_delta[] = {0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,2};
    const uint8_t* cursor = valid_delta;
    uint64_t function_offset = 0;
    CHECK(shdw_svc_next_function_offset(&cursor, valid_delta+4, &function_offset) && function_offset == 512,
          "function delta must decode its full ULEB");
    CHECK(shdw_svc_next_function_offset(&cursor, valid_delta+4, &function_offset) && function_offset == 524,
          "function end must use next boundary");
    CHECK(!shdw_svc_next_function_offset(&cursor, valid_delta+4, &function_offset), "zero terminates table");
    cursor = truncated_delta; function_offset = 0;
    CHECK(!shdw_svc_next_function_offset(&cursor, truncated_delta+1, &function_offset), "truncated ULEB must fail");
    cursor = overflow_delta;
    CHECK(!shdw_svc_next_function_offset(&cursor, overflow_delta+10, &function_offset), "overflowing ULEB must fail");
    cursor = valid_delta; function_offset = UINT64_MAX;
    CHECK(!shdw_svc_next_function_offset(&cursor, valid_delta+4, &function_offset), "offset sum overflow must fail");

    char* code = calloc(1, 4096);
    struct mach_header* cmh = (struct mach_header*)code;
    cmh->magic = MH_MAGIC_64; cmh->cputype = CPU_TYPE_ARM64; cmh->ncmds = 3;
    struct segment_command_64* ct = (void*)(cmh+1);
    ct->cmd = LC_SEGMENT_64; ct->cmdsize = sizeof(*ct) + sizeof(struct section_64);
    memcpy(ct->segname, "__TEXT", 6); ct->vmaddr = (uintptr_t)code; ct->vmsize = 2048; ct->nsects = 1;
    struct section_64* cs = (void*)(ct+1);
    cs->addr = (uintptr_t)(code+512); cs->size = 12; cs->flags = S_ATTR_PURE_INSTRUCTIONS;
    struct segment_command_64* cl = (void*)((char*)ct+ct->cmdsize);
    cl->cmd = LC_SEGMENT_64; cl->cmdsize = sizeof(*cl); memcpy(cl->segname, "__LINKEDIT", 10);
    cl->vmaddr = (uintptr_t)(code+2048); cl->fileoff = 2048; cl->filesize = 256;
    struct linkedit_data_command* cf = (void*)(cl+1);
    cf->cmd = LC_FUNCTION_STARTS; cf->cmdsize = sizeof(*cf); cf->dataoff = 2048; cf->datasize = 4;
    cmh->sizeofcmds = ct->cmdsize+cl->cmdsize+cf->cmdsize;
    memcpy(code+2048, valid_delta, 4); memcpy(code+512, safe, 12);
    admitted = 0; shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 1 && admitted_address == (uintptr_t)(code+512), "valid metadata must admit exact function");
    CHECK(admitted_protection == query_protection, "original RWX protection must reach the exact restore");
    query_result = 1; admitted = 0; shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "failed native protection query must leave code untouched");
    query_result = 0; query_protection = VM_PROT_READ; admitted = 0;
    shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "nonexecutable region must remain untouched");
    query_protection = VM_PROT_READ | VM_PROT_EXECUTE;
    uintptr_t slid = 0;
    CHECK(!shdw_svc_slid_address(UINTPTR_MAX, 1, &slid), "positive slide overflow must fail");
    CHECK(!shdw_svc_slid_address(0, -1, &slid), "negative slide underflow must fail");
    CHECK(shdw_svc_slid_address(16, -8, &slid) && slid == 8, "negative slide must preserve valid address");
    ct->vmaddr++; cs->addr++; admitted = 0;
    shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "unaligned instruction address must not be dereferenced");
    ct->vmaddr--; cs->addr--;
    cs->flags = 0; admitted = 0; shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "identical opcode bytes in non-instruction data must not change");
    cs->flags = S_ATTR_PURE_INSTRUCTIONS; cf->cmd = 0; admitted = 0;
    shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "missing function metadata must not change code");
    cf->cmd = LC_FUNCTION_STARTS; cf->dataoff = 2305; admitted = 0;
    shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "function table outside linkedit must be refused");
    cf->dataoff = 2048; ct->nsects = 100; admitted = 0;
    shdw_svc_patch_image(cmh, 0, "fixture");
    CHECK(admitted == 0, "section array outside command must be refused");
    free(code);

    /* Execute the real writer with host memory, Mach and thread doubles. */
    reset_patch_fixture();
    shdw_svc_try_patch_site((uintptr_t)&patch_fixture[1], patch_fixture[1], patch_fixture[2], "fixture");
    intptr_t branch_delta = (intptr_t)(uintptr_t)shdw_svc_trampoline_80 - (intptr_t)(uintptr_t)&patch_fixture[1];
    uint32_t expected_branch = SHDW_SVC_B | ((uint32_t)(branch_delta >> 2) & 0x3ffffffu);
    CHECK(patch_fixture[1] == expected_branch && cache_invalidations == 1,
          "real writer must encode B relative to svc address and invalidate cache");
    reset_patch_fixture();
    shdw_svc_try_patch_site((uintptr_t)&patch_fixture[1], patch_fixture[1], 0x9a9f37e9u, "fixture");
    CHECK(patch_fixture[1] == 0xd4001001u && !cache_invalidations,
          "real writer must not overwrite unknown leaf continuation");
    reset_patch_fixture();
    shdw_svc_try_patch_site(1, 0xd4001001u, SHDW_SVC_RET, "fixture");
    CHECK(atomic_load(&shdw_svc_far_site_seen) && !cache_invalidations,
          "far refusal must happen without touching unmapped site memory");
    reset_patch_fixture();
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_READ, "fixture");
    CHECK(patch_fixture[1] == expected_branch && cache_invalidations == 1,
          "real patch transaction must reach instruction write");
    CHECK(protect_calls == 2 && protections[0] == (VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY) &&
          protections[1] == query_protection,
          "real transaction must restore the stopped-world query's exact RWX protection");
    CHECK(suspensions == 1 && resumes == 1 && disposals == 1 && region_queries == 1,
          "successful transaction must balance suspension and query native protection");
    reset_patch_fixture(); query_result = 1;
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_READ, "fixture");
    CHECK(patch_fixture[1] == 0xd4001001u && !protect_calls && !cache_invalidations && resumes == 1 && disposals == 1,
          "failed stopped-world protection query must leave code untouched and resume threads");
    reset_patch_fixture(); query_protection = VM_PROT_READ;
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_EXECUTE, "fixture");
    CHECK(patch_fixture[1] == 0xd4001001u && !protect_calls && resumes == 1,
          "stopped-world query must refuse a nonexecutable mapping despite stale caller protection");
    reset_patch_fixture(); suspend_ok = 0;
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_EXECUTE, "fixture");
    CHECK(!region_queries && !protect_calls && !cache_invalidations && !resumes,
          "failed suspension must not query, write, or decrement suspension counts");
    reset_patch_fixture(); protect_fail_all = 1;
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_EXECUTE, "fixture");
    CHECK(protect_calls == 2 && patch_fixture[1] == 0xd4001001u && !cache_invalidations && resumes == 1,
          "failed COPY and RW transitions must not patch instructions");
    reset_patch_fixture(); protect_fail_first = 1;
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_READ, "fixture");
    CHECK(protect_calls == 3 && protections[1] == (VM_PROT_READ | VM_PROT_WRITE) &&
          protections[2] == query_protection && patch_fixture[1] == expected_branch,
          "RW fallback must still restore current native protection");
    reset_patch_fixture(); patch_fixture[0] = 0xaa0003f0u;
    shdw_svc_patch_memory((uintptr_t)patch_fixture, 12, 12, VM_PROT_EXECUTE, "fixture");
    CHECK(!suspensions && !protect_calls && !cache_invalidations,
          "unknown dynamic sysno must not enter a write transaction");

    /* ---- image span ---- */

    /* Ordinary image: page-adjacent segments, span covers the whole run. */
    const seg_spec_t normal[] = {
        { "__TEXT",     0x100000000ULL, 0x8000 },
        { "__DATA",     0x100008000ULL, 0x4000 },
        { "__LINKEDIT", 0x10000c000ULL, 0x2000 },
    };
    struct mach_header* mh = make_image(normal, 3);
    oversized = NO;
    CHECK(shdw_image_span_ex(mh, 0, &base, &end, &oversized) == YES,
          "ordinary image must yield a span");
    CHECK(base == 0x100000000ULL && end == 0x10000e000ULL,
          "ordinary span must cover the contiguous run, got %#llx-%#llx",
          (unsigned long long)base, (unsigned long long)end);
    CHECK(oversized == NO, "ordinary image must not be flagged oversized");
    free(mh);

    /* __PAGEZERO is not mapped and must not seed the run. */
    const seg_spec_t pagezero[] = {
        { "__PAGEZERO", 0x0ULL,         0x100000000ULL },
        { "__TEXT",     0x100000000ULL, 0x8000 },
    };
    mh = make_image(pagezero, 2);
    oversized = NO;
    CHECK(shdw_image_span_ex(mh, 0, &base, &end, &oversized) == YES,
          "__PAGEZERO must not suppress the span");
    CHECK(base == 0x100000000ULL && end == 0x100008000ULL,
          "__PAGEZERO must be excluded, got %#llx-%#llx",
          (unsigned long long)base, (unsigned long long)end);
    free(mh);

    /* The regression: a shared-cache image whose segments sit in different
       subcache regions. Measured on device as /usr/lib/liblzma.5.dylib with
       __TEXT 0x19000, a far __DATA_CONST, and __LINKEDIT reporting the whole
       subcache's link-edit region. A union over these produced an 848 MB span
       covering Security.framework and libswift_Concurrency. */
    const seg_spec_t cached[] = {
        { "__TEXT",       0x1db26c000ULL, 0x19000 },
        { "__DATA_CONST", 0x1f36b2fc8ULL, 0x368 },
        { "__LINKEDIT",   0x1ff644000ULL, 0xb9e0be3 },
    };
    mh = make_image(cached, 3);
    oversized = NO;
    ok = shdw_image_span_ex(mh, 0, &base, &end, &oversized);
    CHECK(!(ok == YES && (end - base) > 0x10000000ULL),
          "shared-cache image must not span the subcache, got %#llx-%#llx (%llu bytes)",
          (unsigned long long)base, (unsigned long long)end,
          (unsigned long long)(end - base));
    CHECK(ok == YES && base == 0x1db26c000ULL && end == 0x1db285000ULL,
          "shared-cache span must be just the __TEXT run, got %#llx-%#llx",
          (unsigned long long)base, (unsigned long long)end);
    free(mh);

    /* A span past the bound must be refused AND reported, so the caller marks
       the table unanswerable instead of recording a range that may cover
       unrelated images. */
    const seg_spec_t huge[] = {
        { "__TEXT",     0x100000000ULL, 0x1000 },
        { "__LINKEDIT", 0x100001000ULL, (uint64_t)SHDW_SPAN_MAX_BYTES },
    };
    mh = make_image(huge, 2);
    oversized = NO;
    ok = shdw_image_span_ex(mh, 0, &base, &end, &oversized);
    CHECK(ok == NO && oversized == YES,
          "oversized span must be refused and reported (ok=%d oversized=%d)",
          ok, oversized);
    free(mh);

    /* Malformed image: refused, not guessed. */
    const seg_spec_t one[] = { { "__TEXT", 0x1000ULL, 0x1000 } };
    mh = make_image(one, 1);
    mh->magic = 0;
    oversized = NO;
    CHECK(shdw_image_span_ex(mh, 0, &base, &end, &oversized) == NO,
          "wrong magic must be refused");
    free(mh);

    /* More segments than the run buffer holds: refused and reported, never
       silently truncated. A dropped segment would shorten the span, which
       reads as "not restricted" -- the unsafe direction. */
    {
        enum { MANY = 40 };
        seg_spec_t many[MANY];
        char names[MANY][16];
        for (int i = 0; i < MANY; i++) {
            snprintf(names[i], sizeof(names[i]), "__SEG%d", i);
            many[i].name = names[i];
            many[i].vmaddr = 0x200000000ULL + (uint64_t)i * 0x1000;
            many[i].vmsize = 0x1000;
        }
        mh = make_image(many, MANY);
        oversized = NO;
        ok = shdw_image_span_ex(mh, 0, &base, &end, &oversized);
        CHECK(ok == NO && oversized == YES,
              "over-long segment list must be refused and reported (ok=%d oversized=%d)",
              ok, oversized);
        free(mh);
    }

    if (failures) { printf("%d assertion(s) failed\\n", failures); return 1; }
    printf("image span + svc branch: all assertions passed\\n");
    return 0;
}
"""


def build_source():
    source = HARNESS.replace("__SPAN_FN__", span_fn)
    source = source.replace("__BRANCH_FN__", branch_fn)
    source = source.replace("__LEAF_FN__", leaf_fn)
    source = source.replace("__DELTA_FN__", delta_fn)
    source = source.replace("__IMAGE_FN__", image_fn.replace("shdw_svc_patch_memory(", "capture_patch_memory("))
    source = source.replace("__SLIDE_FN__", slide_fn)
    source = source.replace("__PATCH_SITE_FN__", patch_site_fn)
    source = source.replace("__PATCH_MEMORY_FN__", patch_memory_fn)
    source = source.replace("__SVC_DEFINES__", svc_defines)
    source = source.replace("__SPAN_DEFINES__", span_defines)
    return source


def run():
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / "span_branch.c"
        exe = Path(tmp) / "span_branch"
        c.write_text(build_source())
        compiled = subprocess.run(
            [os.environ.get("CC", "cc"), "-std=c99", "-Wall", "-Wextra",
             "-Werror", "-pthread", "-o", str(exe), str(c)],
            capture_output=True, text=True)
        if compiled.returncode != 0:
            sys.stderr.write(compiled.stderr)
            return 1
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode


if __name__ == "__main__":
    sys.exit(run())
