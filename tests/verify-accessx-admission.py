"""Execute production ACCESSX leaf admission and alias publication ordering."""

import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UNIVERSAL = ROOT / "src/ShadowCore.dylib/hooks/Universal"


def extract(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


svc = (UNIVERSAL / "svc_patch.x").read_text()
libc = (UNIVERSAL / "libc.x").read_text()
syscall = (UNIVERSAL / "syscall.x").read_text()
leaf = extract(svc, "static long shdw_svc_leaf_sysno(")
category = extract(syscall, "shdw_raw_syscall_category_t shdw_raw_syscall_category(")
registry = (UNIVERSAL / "RawSyscalls.def").read_text()
categories = sorted(set(re.findall(r"SHADW_RAWSYSCALL\([^,]+,\s*(\w+)", registry)))
categories = [name for name in categories if name.isupper()]
# Keep the production switch and registry intact; host numbers only stand in
# for SDK constants, which differ across hosts and are not under test here.
numbers = list(dict.fromkeys(re.findall(r"SHADW_RAWSYSCALL\((SYS_\w+),", registry)))
definitions = "\n".join(f"#define {name} {i + 1}" for i, name in enumerate(numbers))
definitions += "\ntypedef enum {" + ",".join(
    "SHADW_RAW_CAT_" + name for name in ["NONE"] + [c for c in categories if c != "NONE"]
) + "} shdw_raw_syscall_category_t;\n"

alias = extract(libc, 'if(strcmp(d->symbol, "__access_extended") == 0 &&')
# Only the Objective-C backend call is replaced. The ordering, condition,
# continuation selection, assignment, and early exit remain production code.
alias, substitutions = re.subn(
    r"\[hooks hookRebindSymbol:.*?outOldPtr:NULL\];",
    "test_rebind(d->replacement);", alias, flags=re.S,
)
assert substitutions == 1
alias = alias.replace("continue;", "return;")

prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef int BOOL;
#define NO 0
#define YES 1
'''

publication = r'''
static int (*original_accessx_np)(void);
static int (*original_access_extended)(void);
static int reentries;
static int native_accessx(void) { return 73; }
static int saved_continuation(void) { return 91; }
static int replacement(void) {
    assert(original_access_extended != NULL);
    return original_access_extended();
}
typedef struct {
    const char *symbol;
    void *replacement;
    void **original;
} descriptor;
static void test_rebind(void *entry) {
    reentries++;
    int answer = ((int (*)(void))entry)();
    assert(answer == (original_accessx_np ? 91 : 73));
}
static void install_alias(descriptor *d, void *accessx_np_target, void *target) {
__ALIAS__
}
'''.replace("__ALIAS__", alias)

main = r'''
int main(void) {
    uint32_t words[] = {
        0xD2800010U | (SYS_access_extended << 5),
        0xD4001001U, 0xD65F03C0U, 0xD503201FU
    };
    assert(shdw_raw_syscall_category(SYS_access_extended) == SHADW_RAW_CAT_ACCESSX);
    assert(shdw_svc_leaf_sysno(words, 3) == SYS_access_extended);
    words[0] = 0x52800010U | (SYS_access_extended << 5);
    assert(shdw_svc_leaf_sysno(words, 3) == SYS_access_extended);
    assert(shdw_svc_leaf_sysno(words, 4) == -1);
    assert(shdw_svc_leaf_sysno(words, 2) == -1);
    assert(shdw_svc_leaf_sysno(NULL, 3) == -1);
    words[2] = 0xD503201FU;
    assert(shdw_svc_leaf_sysno(words, 3) == -1);
    words[2] = 0xD65F03C0U;
    words[0] |= 0x00200000U;
    assert(shdw_svc_leaf_sysno(words, 3) == -1);

    descriptor d = {"__access_extended", (void *)replacement,
                    (void **)&original_access_extended};
    void *target = (void *)native_accessx;
    original_accessx_np = saved_continuation;
    install_alias(&d, target, target);
    assert(reentries == 1);
    assert(original_access_extended == saved_continuation);
    original_access_extended = NULL;
    original_accessx_np = NULL;
    install_alias(&d, target, target);
    assert(reentries == 2);
    assert(original_access_extended == native_accessx);
    original_access_extended = NULL;
    install_alias(&d, (void *)saved_continuation, target);
    assert(reentries == 2 && original_access_extended == NULL);
    puts("verify-accessx-admission: production leaf decoding and synchronous alias reentry passed");
}
'''

with tempfile.TemporaryDirectory(prefix="shadow-accessx-admission-") as tmp:
    test = Path(tmp) / "test.c"
    executable = Path(tmp) / "test"
    test.write_text(prefix + definitions + category + leaf + publication + main)
    subprocess.run([
        os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-I", str(UNIVERSAL), str(test), "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
