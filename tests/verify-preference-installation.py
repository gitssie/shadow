#!/usr/bin/env python3
"""Exercise production preference descriptors and libc installer with a fake backend."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
ROOT = Path(__file__).resolve().parents[1]
libc = (ROOT / "src/ShadowCore.dylib/hooks/Universal/libc.x").read_text()
headers = (ROOT / "src/ShadowCore.dylib/hooks/hooks.h").read_text()
start = headers.index("typedef enum {", headers.index("SHADW_HOOK_GROUP_LIBC") - 30)
groups = headers[start:headers.index("} shdw_hook_group_t;", start) + len("} shdw_hook_group_t;")]
start = libc.index("typedef struct {", libc.index("// Shared descriptor metadata"))
metadata = libc[start:libc.index("static const shdw_hook_desc_t shdw_libc_hooks[]", start)]
rows = re.findall(r'^    \{ "CFPreferences[^\n]+', libc, re.M)
assert len(rows) == 5, "Update fixture for changed preference descriptor surface"
symbols = [re.search(r'"([^"]+)"', row).group(1) for row in rows]
start = libc.index("void shdw_libc_install_group(")
installer = libc[start:libc.index("\nvoid shdw_universal_filesystem_c(", start)]
source = r'''#import <Foundation/Foundation.h>
#include <assert.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned depth;
@interface Shadow : NSObject
+ (void)shdwEnterInternalRead;
+ (void)shdwExitInternalRead;
@end
@implementation Shadow
+ (void)shdwEnterInternalRead { depth++; }
+ (void)shdwExitInternalRead { assert(depth); depth--; }
@end
@interface SHDWHookSession : NSObject
- (BOOL)hookFunction:(void *)target withReplacement:(void *)replacement outOldPtr:(void **)slot;
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)slot;
@end
static const char *names[] = {''' + ",".join('"' + symbol + '"' for symbol in symbols) + r'''};
static unsigned char nativeTokens[5];
static void *liveTargets[5];
static unsigned attempts[5], rebindAttempts[5];
static BOOL refuse, rebindRefuse, missing;
static void *fixture_dlsym(void *handle, const char *symbol) {
    (void)handle; assert(depth);
    for(unsigned i=0;i<5;i++) if(!strcmp(symbol,names[i]))
        return missing && i==0 ? NULL : liveTargets[i];
    assert(!"Unexpected descriptor"); return NULL;
}
static int fixture_dladdr(const void *target, Dl_info *info) {
    for(unsigned i=0;i<5;i++) if(target==liveTargets[i]) {
        memset(info,0,sizeof(*info)); info->dli_sname=names[i]; info->dli_saddr=(void *)target; return 1;
    }
    assert(!"Unexpected address lookup"); return 0;
}
@implementation SHDWHookSession
- (BOOL)hookFunction:(void *)target withReplacement:(void *)replacement outOldPtr:(void **)slot {
    assert(depth && slot);
    for(unsigned i=0;i<5;i++) if(target==liveTargets[i]) {
        attempts[i]++;
        if(refuse && i==0) return NO;
        *slot=target; liveTargets[i]=replacement; return YES;
    }
    assert(!"Unexpected hook target"); return NO;
}
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)slot {
    assert(depth && slot);
    for(unsigned i=0;i<4;i++) if([symbol isEqualToString:[NSString stringWithUTF8String:names[i]]]) {
        assert(refuse && i==0 && attempts[i]==1);
        rebindAttempts[i]++;
        if(rebindRefuse) return NO;
        *slot=&nativeTokens[i];
        liveTargets[i]=replacement;
        return YES;
    }
    assert(!"Unexpected import fallback"); return NO;
}
@end
''' + groups + "\n" + metadata + "\n"
for symbol in symbols:
    source += f"static void *original_{symbol};\nstatic void replaced_{symbol}(void) {{}}\n"
source += "static const shdw_hook_desc_t shdw_libc_hooks[] = {\n" + "\n".join(rows) + "\n};\n"
source += r'''#define SHDW_HOOK_FALLBACK_REBIND 1
static void *original_accessx_np;
static void *realpathCell;
static void **original_realpath=&realpathCell;
static void shdw_libc_resolve_null_original(const shdw_hook_desc_t *d, void *target) {
    (void)d; (void)target; assert(!"Unexpected NULL-original row");
}
static BOOL shdw_libc_realpath_alias_duplicate(const shdw_hook_desc_t *d, void *target) {
    (void)d; (void)target; return NO;
}
static void shdw_libc_rebind_proclist(SHDWHookSession *hooks, const shdw_hook_desc_t *d, uint32_t group, void *target) {
    (void)hooks; (void)d; (void)group; (void)target;
}
#define dlsym fixture_dlsym
#define dladdr fixture_dladdr
''' + installer + r'''int main(int argc, const char **argv) { @autoreleasepool {
    assert(argc==2);
    rebindRefuse=!strcmp(argv[1],"refused");
    refuse=rebindRefuse || !strcmp(argv[1],"fallback");
    missing=!strcmp(argv[1],"missing");
    for(unsigned i=0;i<5;i++) liveTargets[i]=&nativeTokens[i];
    SHDWHookSession *hooks=[SHDWHookSession new];
    BOOL libcFirst=!strcmp(argv[1],"libc-first");
    shdw_libc_install_group(hooks,libcFirst ? SHADW_HOOK_GROUP_LIBC : SHADW_HOOK_GROUP_PREFERENCES);
    for(unsigned i=0;i<4;i++) assert(attempts[i]==(missing && i==0 ? 0u : 1u));
    assert(attempts[4]==(libcFirst ? 1u : 0u));
    missing=NO;
    shdw_libc_install_group(hooks,libcFirst ? SHADW_HOOK_GROUP_PREFERENCES : SHADW_HOOK_GROUP_LIBC);
    shdw_libc_install_group(hooks,SHADW_HOOK_GROUP_PREFERENCES);
    for(unsigned i=0;i<5;i++) {
        assert(attempts[i]==1);
        assert(rebindAttempts[i]==(refuse && i==0 ? 1u : 0u));
        assert(*shdw_libc_hooks[i].original==(rebindRefuse && i==0 ? NULL : &nativeTokens[i]));
    }
    assert(!depth);
    puts(argv[1]);
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-preference-installation-") as directory:
    source_path, binary = Path(directory) / "test.m", Path(directory) / "test"
    source_path.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-Wno-missing-field-initializers", "-fsanitize=address,undefined",
                    "-framework", "Foundation", str(source_path), "-o", str(binary)], check=True)
    for mode in ["libc-first", "preferences-first", "fallback", "refused", "missing"]:
        subprocess.run([str(binary), mode], check=True,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
print("preference installation: both orders, import fallback, terminal refusal deduplication, late symbol and native continuations passed")
