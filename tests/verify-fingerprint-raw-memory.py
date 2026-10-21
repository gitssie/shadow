"""Exercise the production raw sysctl memory forwarding seam and shared value policy."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
raw = (root / "src/ShadowCore.dylib/hooks/Universal/syscall.x").read_text()
fingerprint = (root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text()


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


helper = function(raw, "static long shdw_raw_sysctl_fingerprint_forward(")
lookup = function(raw, "void *shdw_sym_policy_lookup_syscall(")
value = function(fingerprint, "void shdw_fingerprint_sysctl_value(")
dispatch = function(raw, "static long shdw_syscall_dispatch(")
assert "ext && cat == SHADW_RAW_CAT_SYSCTL" in dispatch
assert "shdw_raw_sysctl_fingerprint_forward(number, args, sysctl_mib, sysctl_miblen," in dispatch
assert "sysctl_oldp, sysctl_oldlenp, sysctl_newp, sysctl_newlen, caller)" in dispatch
for name in ("replaced_syscall", "replaced___syscall"):
    assert "shdw_syscall_dispatch(number, ext, args, caller)" in function(raw, "static long " + name + "(")

prefix = r"""
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <sys/sysctl.h>
typedef int BOOL;
#define YES 1
#define NO 0
static unsigned depth, calls, adjustments;
static BOOL enabledCaller = YES, shdw_fingerprint_enabled = YES;
static const char *shdw_fingerprint_bundle_id = "raw.memory";
static const uint64_t nativeMemory = 3824435200;
static int status;
static size_t returnedLength = sizeof(uint64_t);
static BOOL nestedForward;
static BOOL shdw_map_app_caller(const void *caller) { return caller && enabledCaller && !depth; }
static BOOL shdw_fingerprint_resource_caller(const void *caller) { (void)caller; return NO; }
static uint64_t SHDWFingerprintMemorySize(const char *bundle, uint64_t size) {
    assert(bundle && depth); adjustments++; return size - 622592;
}
static void SHDWFingerprintSysctlValue(const char *name, void *value, size_t length) {
    (void)name; (void)value; (void)length; assert(0);
}
static void leave_scope(BOOL *active) { (void)active; assert(depth); depth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave_scope))) = (++depth, YES); active; active = NO)
static long shdw_syscall_forward(int number, va_list args);
"""
lookup_prefix = r"""
static long (*original_syscall)(int, ...), (*original___syscall)(int, ...);
static void *shdw_syscall_c_aliases[2];
static void (*original_sysctlbyname)(void);
static void replaced_syscall(void) {}
static void replaced___syscall(void) {}
static void replaced_sysctlbyname(void) {}
"""
suffix = r"""
static long invoke(int number, const int *mib, u_int count, void *out, size_t *length,
                   void *newp, size_t newlen, const void *caller, ...) {
    va_list args; va_start(args, caller);
    long result = shdw_raw_sysctl_fingerprint_forward(number, args, mib, count, out, length, newp, newlen, caller);
    va_end(args); return result;
}
static long shdw_syscall_forward(int number, va_list args) {
    assert(number == 202); calls++;
    void *out = va_arg(args, void *);
    size_t *length = va_arg(args, size_t *);
    if(nestedForward) {
        assert(depth);
        nestedForward = NO;
        int mib[] = {CTL_HW, HW_MEMSIZE};
        long result = invoke(number, mib, 2, out, length, NULL, 0, (void *)1, out, length);
        nestedForward = YES;
        return result;
    }
    if(out && length && *length >= sizeof(nativeMemory)) memcpy(out, &nativeMemory, sizeof(nativeMemory));
    if(length) *length = returnedLength;
    errno = EBUSY;
    return status;
}
int main(void) {
    assert(!shdw_sym_policy_lookup_syscall("syscall"));
    original_syscall = (long (*)(int, ...))&replaced_syscall;
    assert(shdw_sym_policy_lookup_syscall("syscall") == (void *)&replaced_syscall);
    assert(!shdw_sym_policy_lookup_syscall("__syscall"));
    assert(!shdw_sym_policy_lookup_syscall("___syscall"));
    shdw_syscall_c_aliases[0] = (void *)original_syscall;
    assert(shdw_sym_policy_lookup_syscall("__syscall") == (void *)&replaced_syscall);
    assert(!shdw_sym_policy_lookup_syscall("___syscall"));
    shdw_syscall_c_aliases[1] = (void *)original_syscall;
    assert(shdw_sym_policy_lookup_syscall("___syscall") == (void *)&replaced_syscall);
    original___syscall = (long (*)(int, ...))&replaced___syscall;
    shdw_syscall_c_aliases[0] = shdw_syscall_c_aliases[1] = (void *)original___syscall;
    assert(shdw_sym_policy_lookup_syscall("__syscall") == (void *)&replaced___syscall);
    assert(shdw_sym_policy_lookup_syscall("___syscall") == (void *)&replaced___syscall);
    assert(!shdw_sym_policy_lookup_syscall(NULL));
    assert(!shdw_sym_policy_lookup_syscall("unknown"));
    assert(!shdw_sym_policy_lookup_syscall("sysctlbyname"));
    original_sysctlbyname = replaced_sysctlbyname;
    assert(shdw_sym_policy_lookup_syscall("sysctlbyname") == (void *)&replaced_sysctlbyname);
    int mib[] = {CTL_HW, HW_MEMSIZE, 0};
    for(unsigned mode = 0; mode < 14; mode++) {
        uint64_t out = 0; size_t length = sizeof(out);
        const int *query = mib; u_int count = 2;
        void *output = &out, *newp = NULL; size_t *lenp = &length, newlen = 0;
        const void *caller = (void *)1;
        status = 0; returnedLength = sizeof(out);
        enabledCaller = YES; shdw_fingerprint_enabled = YES; nestedForward = NO;
        switch(mode) {
            case 1: status = -1; break;
            case 2: output = NULL; break;
            case 3: lenp = NULL; break;
            case 4: returnedLength = sizeof(out) - 1; break;
            case 5: newp = &out; break;
            case 6: newlen = 1; break;
            case 7: count = 3; break;
            case 8: query = NULL; break;
            case 9: enabledCaller = NO; break;
            case 10: shdw_fingerprint_enabled = NO; break;
            case 11: caller = NULL; break;
            case 12: nestedForward = YES; break;
            case 13: depth = 1; break;
        }
        unsigned previous = adjustments, previousCalls = calls;
        assert(invoke(202, query, count, output, lenp, newp, newlen, caller, output, lenp) == status);
        BOOL adjusted = mode == 0 || mode == 12;
        assert(adjustments == previous + adjusted);
        assert(calls == previousCalls + (mode == 12 ? 2 : 1));
        if(output && lenp) assert(out == nativeMemory - (adjusted ? 622592 : 0));
        assert(errno == EBUSY);
        assert(depth == (mode == 13 ? 1 : 0)); depth = 0;
        if(lenp) assert(length == returnedLength);
    }
    puts("raw memory: shared forwarding, nested calls, scope, lengths, errors and errno passed");
}
"""
with tempfile.TemporaryDirectory(prefix="shadow-raw-memory-") as temp:
    source = Path(temp) / "check.c"
    binary = Path(temp) / "check"
    source.write_text(prefix + value + "\n" + helper + lookup_prefix + lookup + suffix)
    subprocess.run(["clang", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
