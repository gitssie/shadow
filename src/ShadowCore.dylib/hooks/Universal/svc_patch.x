#pragma clang diagnostic ignored "-Wdeprecated-declarations"

// Raw svc interception: inline `svc` syscalls never pass through libc
// wrappers, so the syscall(2)/__syscall(2) hooks in syscall.x cannot see
// them. This file redirects only complete, recognized constant-number leaf
// wrappers in instruction sections. Other inline sites remain untouched.
// System images are never patched (re-entrancy); Shadow's own
// images are skipped too. Arm64 only: the !__arm64__ (armv7, rootful-legacy)
// lane is an intentionally empty stub — inline svc sites on 32-bit are NOT
// intercepted, only the syscall(2)/__syscall(2) rebind lane in syscall.x
// covers them. No functional change to hooking lanes here.
//
// A kernel-side sysent hook was considered (catch every svc, JIT or not)
// but is not implementable on modern iOS: sy_call must point at
// kernel-resident code, and arm64e's PPL forbids executing injected kernel
// memory — modern jailbreaks patch kernel data only.

#import "UniversalHooks.h"
#import "../../policy/PathPolicy.h"
#import "../../policy/ProcessPolicy.h"
#import "path_rewrite.h"

#import <libkern/OSCacheControl.h>
#import <pthread.h>
#import <sys/event.h>
#import <sys/syscall.h>
#import <fcntl.h>
#import <string.h>
#import <unistd.h>

#if defined(__arm64__)

// --- Natural-ENOENT rewrite (call-time path munging) ------------------------
// Prototype: for read-only path syscalls denied by the policy, rewrite the
// caller's path buffer in place (same length, middle of the final component
// → 0x01, see path_rewrite.c) and return "allow": the original svc then
// executes against the munged path and the kernel produces a REAL ENOENT.
// The rewritten buffer stays munged in the app's memory, so every later
// lookup of the same buffer — libc, NSFileManager, a helper process via
// argv — fails naturally, even through code Shadow does not hook. Falls back
// to the synthetic ENOENT when the buffer is not writable (e.g. a __TEXT
// string constant), the syscall is not in the rewrite set, or the
// Universal_PathRewrite is off. open-family with O_CREAT keeps the synthetic deny
// — the munged path would otherwise be CREATED as a side effect.
static BOOL shdw_svc_rewriteable(int sysno, uint64_t flags) {
    switch(sysno) {
        case SYS_access: case SYS_stat: case SYS_lstat:
        case SYS_stat64: case SYS_lstat64:
        case SYS_stat_extended: case SYS_lstat_extended:
        case SYS_stat64_extended: case SYS_lstat64_extended:
        case SYS_getattrlist: case SYS_getxattr: case SYS_listxattr:
        case SYS_readlink: case SYS_pathconf:
        case SYS_fstatat: case SYS_fstatat64:
        case SYS_execve:
            return YES;
        case SYS_open: case SYS_open_extended: case SYS_openat:
            return ((int)flags & O_CREAT) == 0;
        default:
            return NO;
    }
}

// --- Trampoline helper ------------------------------------------------------
// Runs with the app's registers saved on the stack (see the trampoline
// asm). A normal C function: may clobber x0-x18/lr freely, must preserve
// x19-x28 (the compiler does). Returns 0 = allow (execute the original
// svc), otherwise the errno the trampoline synthesizes with carry set
// (ENOENT for the path shapes, ESRCH for the kevent liveness shapes).
// Plain C linkage (Logos emits ObjC .m, no mangling), so the inline-asm
// `bl _shdw_svc_should_deny` resolves.
__attribute__((used, noinline)) int shdw_svc_should_deny(uint64_t sysno, uint64_t a0, uint64_t a1, uint64_t a2, uintptr_t caller_lr) {
    // The patched site is in app/detector code by construction (system and
    // Shadow images are never scanned), but keep the same caller gate the
    // libc hooks use — the return address is passed explicitly because
    // isCallerExternal()'s builtin read would see the trampoline's own
    // (ShadowCore) address.
    if(!shdw_caller_is_external((const void*)caller_lr)) {
        return 0;
    }

    shdw_raw_syscall_category_t cat = shdw_raw_syscall_category((int)sysno);

    if(cat == SHADW_RAW_CAT_PATH) {
        const char* path = (const char*)a0;

        if(!path || !path[0]) {
            return 0;
        }

        // Same behavioral tripwire as the libc hooks (SHADOW_TRIP): touching
        // a JB-indicator path via raw svc is detector evidence — escalate.
        if(shdw_is_jb_probe(path)) {
            shdw_detector_detected("svc");
        }

        // Same predicate PAIR as the libc/syscall(2) path hooks: the ruleset
        // AND the external-hidden set. A raw svc lookup must not expose an
        // object the wrappers report absent.
        BOOL hidden = shdw_path_is_external_hidden(path);

        if(!hidden && ![_shadow isCPathRestricted:path]) {
            return 0;
        }

        // External-hidden objects always answer synthetic ENOENT (the
        // path-rewrite munge would let the real svc resolve the still-present
        // file). Only the ruleset case takes the natural-ENOENT rewrite.
        if(hidden) {
            return ENOENT;
        }

        // Natural-ENOENT rewrite: munge the buffer and let the real svc run.
        size_t moff = shdw_path_munge_offset(path);

        if(shdw_path_rewrite_enabled()
           && shdw_svc_rewriteable((int)sysno, a1)
           && moff != (size_t)-1
           && shdw_path_buf_writable(path + moff)
           && (unsigned char)path[moff] != 0x01
           && shdw_path_munge_path((char*)path)) {
            return 0;
        }

        return ENOENT;
    }

    if(cat == SHADW_RAW_CAT_AT) {
        const char* path = (const char*)a1;

        if(!path || !path[0]) {
            return 0;
        }

        if(shdw_is_jb_probe(path)) {
            shdw_detector_detected("svc");
        }

        // Same dirfd-aware policy as the syscall(2) dispatch (sets errno on
        // denial; the trampoline ignores errno and synthesizes the raw
        // return instead).
        if(!shdw_at_path_denied((int)a0, path)) {
            return 0;
        }

        // Natural-ENOENT rewrite (openat flags live in a2, now passed by the
        // trampoline; fstatat/fstatat64 are read-only and safe).
        size_t moff = shdw_path_munge_offset(path);

        if(shdw_path_is_absolute(path)
           && shdw_path_rewrite_enabled()
           && shdw_svc_rewriteable((int)sysno, a2)
           && moff != (size_t)-1
           && shdw_path_buf_writable(path + moff)
           && (unsigned char)path[moff] != 0x01
           && shdw_path_munge_path((char*)path)) {
            return 0;
        }

        return ENOENT;
    }

#ifdef SYS_freadlink
    if(cat == SHADW_RAW_CAT_FREADLINK) {
        // Raw freadlink(fd): same fd policy as the syscall(2) dispatch —
        // fresh F_GETPATH, fail open when the fd has no nameable path. The
        // trampoline ignores errno and synthesizes the raw return.
        if(shdw_fd_path_restricted((int)a0)) {
            return ENOENT;
        }
        return 0;
    }
#endif

    if(cat == SHADW_RAW_CAT_KEVENT || cat == SHADW_RAW_CAT_KEVENT64) {
        // Inline-svc kevent(363)/kevent64(369): same EVFILT_PROC-only ESRCH
        // as the libc + syscall(2) hooks. The trampoline carries only
        // (sysno, a0=kq, a1=changelist, a2=nchanges) — sufficient, the policy
        // keys on the changelist head. The 64-bit changelist is scanned with
        // its own type (struct kevent64_s layout verified against the SDK
        // sys/event.h: ident u64 @0, filter s16 @8 — 48-byte elements), never
        // as struct kevent. Self-pid and non-PROC filters pass through;
        // unclassifiable pids fail open. The trampoline synthesizes the
        // returned ESRCH with carry set (stock-dead shape).
        const void* changelist = (const void*)a1;
        long nchanges = (long)a2;

        if(changelist && nchanges > 0) {
            pid_t self = getpid();
            long limit = nchanges > SHDW_KEVENT_SCAN_MAX ? SHDW_KEVENT_SCAN_MAX : nchanges;

            for(long i = 0; i < limit; i++) {
                int16_t filter;
                uint64_t ident;

                if(cat == SHADW_RAW_CAT_KEVENT64) {
                    const struct kevent64_s* chl = (const struct kevent64_s*)changelist;
                    filter = chl[i].filter;
                    ident = chl[i].ident;
                } else {
                    const struct kevent* chl = (const struct kevent*)changelist;
                    filter = chl[i].filter;
                    ident = (uint64_t)chl[i].ident;
                }

                if(filter == EVFILT_PROC) {
                    pid_t pid = (pid_t)ident;

                    if(pid > 0 && pid != self && shdw_pid_is_restricted(pid)) {
                        return ESRCH;
                    }
                }
            }
        }

        return 0;
    }

    return 0;
}

// --- Naked trampolines ------------------------------------------------------
// XNU ignores svc's immediate, so one canonical trampoline handles every
// encoding. Save all caller-saved registers + x16 (syscall
// number) + lr, ask the helper, then either synthesize the errno return
// (x0 = helper's errno, carry set — Darwin's kernel error convention) or
// restore and execute the original svc.
#define SHADW_SVC_TRAMPOLINE(NAME, IMM) \
__attribute__((naked, used, noinline)) static void NAME(void) { \
    __asm__ volatile( \
        "stp x0, x1, [sp, #-16]!\n" \
        "stp x2, x3, [sp, #-16]!\n" \
        "stp x4, x5, [sp, #-16]!\n" \
        "stp x6, x7, [sp, #-16]!\n" \
        "stp x8, x9, [sp, #-16]!\n" \
        "stp x10, x11, [sp, #-16]!\n" \
        "stp x12, x13, [sp, #-16]!\n" \
        "stp x14, x15, [sp, #-16]!\n" \
        "stp x16, x17, [sp, #-16]!\n" \
        "stp x18, lr, [sp, #-16]!\n" \
        /* x0 = sysno (x16), x1 = a0, x2 = a1, x3 = a2, x4 = caller lr */ \
        "mov x2, x1\n" \
        "mov x1, x0\n" \
        "mov x0, x16\n" \
        /* Ten 16-byte pushes above (x0/x1 .. x18/lr): the saved x2 slot is */ \
        /* at sp+128 (saved x3 is at sp+136). a2 must be the third syscall */ \
        /* argument (openat flags, kevent nchanges), not x3. */ \
        "ldr x3, [sp, #128]\n" \
        "ldr x4, [sp, #8]\n" \
        "bl _shdw_svc_should_deny\n" \
        "cbz x0, 1f\n" \
        /* deny: x0 already holds the errno to synthesize (ENOENT for the */ \
        /* path shapes, ESRCH for kevent) — set carry (Darwin's kernel */ \
        /* error convention) and return, keeping x0 */ \
        "mov x1, #0x20000000\n" \
        "msr nzcv, x1\n" \
        "ldp x18, lr, [sp], #16\n" \
        "ldp x16, x17, [sp], #16\n" \
        "ldp x14, x15, [sp], #16\n" \
        "ldp x12, x13, [sp], #16\n" \
        "ldp x10, x11, [sp], #16\n" \
        "ldp x8, x9, [sp], #16\n" \
        "ldp x6, x7, [sp], #16\n" \
        "ldp x4, x5, [sp], #16\n" \
        "ldp x2, x3, [sp], #16\n" \
        "ldr x1, [sp, #8]\n" \
        "add sp, sp, #16\n" \
        "ret\n" \
        "1:\n" \
        /* allow: restore everything, execute the original svc */ \
        "ldp x18, lr, [sp], #16\n" \
        "ldp x16, x17, [sp], #16\n" \
        "ldp x14, x15, [sp], #16\n" \
        "ldp x12, x13, [sp], #16\n" \
        "ldp x10, x11, [sp], #16\n" \
        "ldp x8, x9, [sp], #16\n" \
        "ldp x6, x7, [sp], #16\n" \
        "ldp x4, x5, [sp], #16\n" \
        "ldp x2, x3, [sp], #16\n" \
        "ldp x0, x1, [sp], #16\n" \
        "svc #" IMM "\n" \
        "ret\n" \
    ); \
}

SHADW_SVC_TRAMPOLINE(shdw_svc_trampoline_80, "0x80")

// --- Scanner ----------------------------------------------------------------

#define SHDW_SVC_OPCODE_MASK 0xFFE0001FU
#define SHDW_SVC_OPCODE      0xD4000001U

static inline BOOL shdw_svc_is_instruction(uint32_t insn) {
    return (insn & SHDW_SVC_OPCODE_MASK) == SHDW_SVC_OPCODE;
}

// Only a complete three-instruction function has a known syscall number and
// a return path the shared trampoline can preserve without relocating code.
static long shdw_svc_leaf_sysno(const uint32_t* words, size_t nwords) {
    if(!words || nwords != 3 || words[1] != 0xD4001001U ||
       words[2] != 0xD65F03C0U) return -1;

    uint32_t insn = words[0];
    if((insn & 0xFFE0001FU) != 0x52800010U &&
       (insn & 0xFFE0001FU) != 0xD2800010U) return -1;
    int sysno = (int)((insn >> 5) & 0xFFFFU);
    switch(shdw_raw_syscall_category(sysno)) {
        case SHADW_RAW_CAT_PATH:
        case SHADW_RAW_CAT_AT:
#ifdef SYS_freadlink
        case SHADW_RAW_CAT_FREADLINK:
#endif
        case SHADW_RAW_CAT_KEVENT:
        case SHADW_RAW_CAT_KEVENT64:
            return sysno;
        default:
            return -1;
    }
}

// Images that must never be patched (see the file header: recursion safety
// and trampoline self-protection).
static BOOL shdw_svc_skip_image(const char* path) {
    if(!path || !path[0]) {
        return YES;
    }

    if(strncmp(path, "/System/", 8) == 0) {
        return YES;
    }

    if(strncmp(path, "/usr/", 5) == 0) {
        return YES;
    }

    NSString* imagePath = [NSString stringWithUTF8String:path];
    NSString* bundlePath = [NSBundle mainBundle].bundlePath;
    if([imagePath isEqualToString:bundlePath] ||
       [imagePath hasPrefix:[bundlePath stringByAppendingString:@"/"]]) {
        return NO;
    }

    // dyld reports the canonical preboot path for rootless apps while
    // NSBundle can retain /var/jb. Code inside procursus/Applications is
    // still app-owned detector code, not a bootstrap library.
    if(strstr(path, "/procursus/Applications/") != NULL) {
        return NO;
    }

    // Rootless jailbreak root: /var/jb resolves to
    // /private/preboot/<uuid>/procursus. The jailbreak's own dylibs
    // (systemhook, HKGum, libroot, ...) are NOT detector code — patching
    // their svc sites corrupts them and crashes the process.
    if(strstr(path, "/procursus/") != NULL) {
        return YES;
    }

    if(shdw_is_shadow_runtime_image(path)) {
        return YES;
    }

    return NO;
}

// Redirects one image svc site to the canonical trampoline. Idempotent: a
// patched site is a b/bl instruction, so a re-scan never matches it.
static _Atomic BOOL shdw_svc_far_site_seen = NO;

// `ret` (x30). The trampoline has no other return encoding to handle: it only
// ever restores x30 and returns, so a site whose fallthrough is this returns
// through exactly the same register.
#define SHDW_SVC_RET 0xD65F03C0U
#define SHDW_SVC_B 0x14000000U
#define SHDW_SVC_BL 0x94000000U

// An unknown continuation cannot prove x30 is dead. Never emit BL here.
static uint32_t shdw_svc_site_branch_opcode(uint32_t fallthrough) {
    return fallthrough == SHDW_SVC_RET ? SHDW_SVC_B : 0;
}

static void shdw_svc_try_patch_site(uintptr_t site, uint32_t insn,
                                    uint32_t fallthrough, const char* where) {
    (void)where;
    uintptr_t target = 0;

    uint32_t opcode = shdw_svc_site_branch_opcode(fallthrough);
    if(!shdw_svc_is_instruction(insn) || !opcode) return;
    target = (uintptr_t)shdw_svc_trampoline_80;

    // A64 B/BL immediates are relative to the branch instruction's address.
    int64_t delta = (int64_t)target - (int64_t)site;

    if(delta < -0x8000000LL || delta > 0x7FFFFFCLL) {
        // Logging while every other thread is stopped can deadlock on a
        // runtime lock held by one of those threads. The caller reports this
        // once after the stop-the-world window instead.
        atomic_store_explicit(&shdw_svc_far_site_seen, YES, memory_order_relaxed);
        return;
    }

    *(uint32_t*)site =
        opcode |
        ((uint32_t)(delta >> 2) & 0x3FFFFFF);
    sys_icache_invalidate((void*)site, 4);
}

// All image callbacks converge here. The recursive lock handles an unusual
// same-thread callback without deadlocking; nested stop/resume pairs preserve
// the outer suspension counts.
static pthread_mutex_t shdw_svc_patch_lock = PTHREAD_RECURSIVE_MUTEX_INITIALIZER;

static void shdw_svc_dispose_thread_list(thread_act_array_t threads,
                                         mach_msg_type_number_t count,
                                         mach_port_t current) {
    for(mach_msg_type_number_t i = 0; i < count; i++) {
        mach_port_deallocate(mach_task_self(), threads[i]);
    }

    vm_deallocate(mach_task_self(), (vm_address_t)threads,
                  (vm_size_t)count * sizeof(thread_t));

    if(current != MACH_PORT_NULL) {
        mach_port_deallocate(mach_task_self(), current);
    }
}

static void shdw_svc_dispose_object(mach_port_t* object_name) {
    if(object_name && *object_name != MACH_PORT_NULL) {
        mach_port_deallocate(mach_task_self(), *object_name);
        *object_name = MACH_PORT_NULL;
    }
}

// Suspend exactly the threads whose thread_suspend call succeeded. This
// avoids accidentally decrementing a pre-existing suspend count if a thread
// exits between task_threads() and the loop.
static BOOL shdw_svc_suspend_others(thread_act_array_t* threads_out,
                                    mach_msg_type_number_t* count_out,
                                    mach_port_t* current_out) {
    thread_act_array_t threads = NULL;
    mach_msg_type_number_t count = 0;
    mach_port_t current = mach_thread_self();

    if(current == MACH_PORT_NULL) {
        return NO;
    }

    kern_return_t kr = task_threads(mach_task_self(), &threads, &count);

    if(kr != KERN_SUCCESS || !threads) {
        if(threads) {
            shdw_svc_dispose_thread_list(threads, count, current);
        } else {
            mach_port_deallocate(mach_task_self(), current);
        }

        return NO;
    }

    mach_msg_type_number_t suspended_through = 0;

    for(; suspended_through < count; suspended_through++) {
        if(threads[suspended_through] == current) {
            continue;
        }

        if(thread_suspend(threads[suspended_through]) != KERN_SUCCESS) {
            for(mach_msg_type_number_t i = 0; i < suspended_through; i++) {
                if(threads[i] != current) {
                    thread_resume(threads[i]);
                }
            }

            shdw_svc_dispose_thread_list(threads, count, current);
            return NO;
        }
    }

    *threads_out = threads;
    *count_out = count;
    *current_out = current;
    return YES;
}

static void shdw_svc_resume_others(thread_act_array_t threads,
                                   mach_msg_type_number_t count,
                                   mach_port_t current) {
    for(mach_msg_type_number_t i = 0; i < count; i++) {
        if(threads[i] != current) {
            thread_resume(threads[i]);
        }
    }
}

// Patch one executable range. The read-only preflight happens while other
// threads run; only the final vm_protect/write/reprotect sequence stops them.
// scan_size may be smaller than protect_size for a Mach-O __TEXT segment.
static void shdw_svc_patch_memory(uintptr_t addr, size_t scan_size,
                                  size_t protect_size, vm_prot_t original_prot,
                                  const char* where) {
    if(shdw_svc_leaf_sysno((const uint32_t*)addr, scan_size / 4) < 0) {
        return;
    }

    pthread_mutex_lock(&shdw_svc_patch_lock);

    // Another scanner may have patched the site while this caller waited.
    if(shdw_svc_leaf_sysno((const uint32_t*)addr, scan_size / 4) < 0) {
        pthread_mutex_unlock(&shdw_svc_patch_lock);
        return;
    }

    thread_act_array_t threads = NULL;
    mach_msg_type_number_t thread_count = 0;
    mach_port_t current = MACH_PORT_NULL;

    if(!shdw_svc_suspend_others(&threads, &thread_count, &current)) {
        pthread_mutex_unlock(&shdw_svc_patch_lock);
        return;
    }

    vm_prot_t restore_prot = original_prot;
    vm_region_basic_info_data_64_t current_info;
    mach_msg_type_number_t current_info_count = VM_REGION_BASIC_INFO_COUNT_64;
    vm_address_t current_region = addr;
    vm_size_t current_region_size = 0;
    mach_port_t current_object = MACH_PORT_NULL;

    kern_return_t current_kr = vm_region_64(mach_task_self(), &current_region,
                                            &current_region_size,
                                            VM_REGION_BASIC_INFO_64,
                                            (vm_region_info_t)&current_info,
                                            &current_info_count, &current_object);

    if(current_object != MACH_PORT_NULL) {
        mach_port_deallocate(mach_task_self(), current_object);
    }

    if(current_kr != KERN_SUCCESS ||
       current_info_count < VM_REGION_BASIC_INFO_COUNT_64 ||
       current_region > addr || addr - current_region > current_region_size ||
       scan_size > current_region_size - (addr - current_region)) {
        shdw_svc_resume_others(threads, thread_count, current);
        shdw_svc_dispose_thread_list(threads, thread_count, current);
        pthread_mutex_unlock(&shdw_svc_patch_lock);
        return;
    }
    if(current_kr == KERN_SUCCESS) {
        if(!(current_info.protection & VM_PROT_EXECUTE)) {
            shdw_svc_resume_others(threads, thread_count, current);
            shdw_svc_dispose_thread_list(threads, thread_count, current);
            pthread_mutex_unlock(&shdw_svc_patch_lock);
            return;
        }

        // Re-read protection after stopping the world so a racing mprotect
        // cannot be undone by restoring stale preflight state.
        restore_prot = current_info.protection;
    }

    // Code-signed __TEXT's max_protection is r-x, so a plain vm_protect
    // READ|WRITE is denied (KERN_PROTECTION_FAILURE) — the same wall dyld.x's
    // load-command rewrite hits. Request VM_PROT_COPY, which forces a private
    // copy-on-write mapping and raises max_protection to include WRITE; only
    // the written site pages materialize, the rest stay shared. Falls back
    // to plain RW on kernels that reject COPY here; fail-soft either way.
    // Code-signed __TEXT's max_protection is r-x, so a plain vm_protect
    // READ|WRITE is denied (KERN_PROTECTION_FAILURE) — the same wall dyld.x's
    // load-command rewrite hits. Request VM_PROT_COPY, which forces a private
    // copy-on-write mapping and raises max_protection to include WRITE; only
    // the written site pages materialize, the rest stay shared. Falls back
    // to plain RW on kernels that reject COPY here; fail-soft either way.
    BOOL protected_for_write = vm_protect(mach_task_self(), addr, protect_size,
                                          FALSE, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY) == KERN_SUCCESS;

    if(!protected_for_write) {
        protected_for_write = vm_protect(mach_task_self(), addr, protect_size,
                                         FALSE, VM_PROT_READ | VM_PROT_WRITE) == KERN_SUCCESS;
    }

    BOOL restore_failed = NO;

    if(protected_for_write) {
        uint32_t* words = (uint32_t*)addr;
        // Revalidate after stopping the other threads; only the svc word changes.
        if(shdw_svc_leaf_sysno(words, scan_size / 4) >= 0) {
            shdw_svc_try_patch_site(addr + 4, words[1], words[2], where);
        }

        // Restore execute permission before any other thread can run again.
        if(vm_protect(mach_task_self(), addr, protect_size, FALSE, restore_prot) != KERN_SUCCESS) {
            restore_failed = YES;
            // Keep a failed exact restore from leaving an executable page
            // permanently non-executable. The fallback intentionally favors
            // liveness over preserving an unusual extra protection bit.
            vm_protect(mach_task_self(), addr, protect_size, FALSE,
                       VM_PROT_READ | VM_PROT_EXECUTE);
        }
    }

    shdw_svc_resume_others(threads, thread_count, current);
    shdw_svc_dispose_thread_list(threads, thread_count, current);
    pthread_mutex_unlock(&shdw_svc_patch_lock);

    if(restore_failed) {
        NSLog(@"[Shadow][svc] protection restore failed in %s (fallback RX)", where);
    }

    if(atomic_exchange_explicit(&shdw_svc_far_site_seen, NO, memory_order_relaxed)) {
        NSLog(@"[Shadow][svc] svc site skipped in %s", where);
    }
}

// Decode one nonzero LC_FUNCTION_STARTS delta. Truncated, overflowing or
// unterminated tables are not evidence of a safe function boundary.
static BOOL shdw_svc_next_function_offset(const uint8_t** cursor,
                                           const uint8_t* end,
                                           uint64_t* offset) {
    uint64_t delta = 0;
    unsigned shift = 0;
    while(*cursor < end) {
        uint8_t byte = *(*cursor)++;
        if(shift >= 64 || (shift == 63 && (byte & 0x7E))) return NO;
        delta |= (uint64_t)(byte & 0x7F) << shift;
        if(!(byte & 0x80)) {
            if(!delta || delta > UINT64_MAX - *offset) return NO;
            *offset += delta;
            return YES;
        }
        shift += 7;
    }
    return NO;
}

static BOOL shdw_svc_slid_address(uint64_t vmaddr, intptr_t slide, uintptr_t* out) {
    if(vmaddr > UINTPTR_MAX) return NO;
    if(slide >= 0) {
        if(vmaddr > UINTPTR_MAX - (uintptr_t)slide) return NO;
        *out = (uintptr_t)vmaddr + (uintptr_t)slide;
    } else {
        uintptr_t magnitude = (uintptr_t)(-(slide + 1)) + 1;
        if(vmaddr < magnitude) return NO;
        *out = (uintptr_t)vmaddr - magnitude;
    }
    return YES;
}

// Admit only whole functions identified by the image's own boundary table,
// contained in an instruction section. Missing metadata leaves code untouched.
static void shdw_svc_patch_image(const struct mach_header* mh, intptr_t slide, const char* path) {
    if(mh->magic != MH_MAGIC_64 || mh->cputype != CPU_TYPE_ARM64) return;
    const struct mach_header_64* header = (const struct mach_header_64*)mh;
    const uint8_t* command = (const uint8_t*)(header + 1);
    size_t remaining = header->sizeofcmds;
    const struct segment_command_64* text = NULL;
    const struct segment_command_64* linkedit = NULL;
    const struct linkedit_data_command* starts = NULL;

    for(uint32_t i = 0; i < header->ncmds; i++) {
        if(remaining < sizeof(struct load_command)) return;
        const struct load_command* lc = (const struct load_command*)command;
        if(lc->cmdsize < sizeof(*lc) || lc->cmdsize > remaining) return;
        if(lc->cmd == LC_SEGMENT_64) {
            if(lc->cmdsize < sizeof(struct segment_command_64)) return;
            const struct segment_command_64* seg = (const struct segment_command_64*)lc;
            if(seg->nsects > (lc->cmdsize - sizeof(*seg)) / sizeof(struct section_64)) return;
            if(strncmp(seg->segname, "__TEXT", 16) == 0) text = seg;
            if(strncmp(seg->segname, "__LINKEDIT", 16) == 0) linkedit = seg;
        } else if(lc->cmd == LC_FUNCTION_STARTS) {
            if(lc->cmdsize < sizeof(struct linkedit_data_command)) return;
            starts = (const struct linkedit_data_command*)lc;
        }
        remaining -= lc->cmdsize;
        command += lc->cmdsize;
    }
    if(!text || !linkedit || !starts || !starts->datasize ||
       starts->dataoff < linkedit->fileoff) return;
    uint64_t dataDelta = starts->dataoff - linkedit->fileoff;
    if(dataDelta > linkedit->filesize || starts->datasize > linkedit->filesize - dataDelta) return;
    uintptr_t dataBase = 0;
    if(!shdw_svc_slid_address(linkedit->vmaddr, slide, &dataBase) ||
       dataDelta > UINTPTR_MAX - dataBase) return;
    dataBase += dataDelta;
    if(starts->datasize > UINTPTR_MAX - dataBase) return;
    const uint8_t* cursor = (const uint8_t*)dataBase;
    const uint8_t* end = cursor + starts->datasize;
    uint64_t offset = 0;
    if(!shdw_svc_next_function_offset(&cursor, end, &offset)) return;
    uint64_t previous = offset;

    while(shdw_svc_next_function_offset(&cursor, end, &offset)) {
        if(offset - previous == 3 * sizeof(uint32_t) &&
           previous <= text->vmsize && offset <= text->vmsize) {
            uint64_t vmaddr = text->vmaddr + previous;
            if(vmaddr < text->vmaddr) return;
            const struct section_64* sections = (const struct section_64*)(text + 1);
            BOOL instructions = NO;
            for(uint32_t i = 0; i < text->nsects; i++) {
                const struct section_64* section = &sections[i];
                if((section->flags & SECTION_TYPE) == S_REGULAR &&
                   (section->flags & S_ATTR_PURE_INSTRUCTIONS) &&
                   vmaddr >= section->addr && vmaddr - section->addr <= section->size &&
                   12 <= section->size - (vmaddr - section->addr)) {
                    instructions = YES;
                    break;
                }
            }
            uintptr_t address = 0;
            // One protection query/restore must describe the entire write page.
            if(instructions && shdw_svc_slid_address(vmaddr, slide, &address) &&
               address % 4 == 0 && vm_page_size >= 12 &&
               address % vm_page_size <= vm_page_size - 12 &&
               shdw_svc_leaf_sysno((const uint32_t*)address, 3) >= 0) {
                vm_region_basic_info_data_64_t info;
                mach_msg_type_number_t infoCount = VM_REGION_BASIC_INFO_COUNT_64;
                vm_address_t region = address;
                vm_size_t regionSize = 0;
                mach_port_t object = MACH_PORT_NULL;
                kern_return_t result = vm_region_64(mach_task_self(), &region,
                    &regionSize, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info,
                    &infoCount, &object);
                shdw_svc_dispose_object(&object);
                if(result == KERN_SUCCESS && infoCount >= VM_REGION_BASIC_INFO_COUNT_64 &&
                   region <= address && address - region <= regionSize &&
                   12 <= regionSize - (address - region) &&
                   (info.protection & VM_PROT_EXECUTE)) {
                    shdw_svc_patch_memory(address, 12, 12, info.protection, path);
                }
            }
        }
        previous = offset;
    }
}

// Add-image callback: resolve the image path (the callback only carries the
// header), apply the skip rule, scan. Registered through the REAL dyld
// registration (the dyld.x hook passes Shadow-internal callers through), so
// the registration replay covers every already-loaded image — including the
// app binary — before the app runs.
static const struct mach_header* shdw_svc_own_image = NULL;

static void shdw_svc_image_add(const struct mach_header* mh, intptr_t slide) {
    if(!shdw_svc_own_image || mh == shdw_svc_own_image) {
        return;
    }

    for(uint32_t i = 0; i < _dyld_image_count(); i++) {
        if(_dyld_get_image_header(i) == mh) {
            const char* path = _dyld_get_image_name(i);

            if(path && path[0] && !shdw_svc_skip_image(path)) {
                shdw_svc_patch_image(mh, slide, path);
            }

            return;
        }
    }
}

// Installed from the universal syscall installer, so its preference gates it (the
// unit only installs when the pref is on). Idempotent.
void shdw_svc_patch_install(void) {
    static BOOL installed = NO;

    if(installed) {
        return;
    }

    Dl_info info = {0};
    if(!dladdr((const void*)shdw_svc_patch_install, &info) || !info.dli_fbase) {
        return;
    }

    shdw_svc_own_image = (const struct mach_header*)info.dli_fbase;
    installed = YES;
    _dyld_register_func_for_add_image(shdw_svc_image_add);
}

#else   // !__arm64__

// Rootful-legacy armv7 lane: no ARM64 svc interception (arm64-only
// encoding scan; see the file header). The stub keeps syscall.x linkable.
void shdw_svc_patch_install(void) {
}

#endif  // __arm64__
