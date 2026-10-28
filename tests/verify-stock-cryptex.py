#!/usr/bin/env python3
"""Exercise the actual restricted-root matcher for stock Cryptex namespaces."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "src/Shadow.framework/Headers/Shadow/JBPath.h").read_text()
pure = source.split("// Jailbreak-root path seam.", 1)[0]
pure = pure.replace("#import <Foundation/Foundation.h>", "typedef int BOOL;\n#define YES 1\n#define NO 0\n#define _Nullable")
pure += "\n#endif\n"
cases = r'''
#include <assert.h>
#include <stdio.h>

int main(void) {
    const char *stock[] = {
        "/private/preboot/Cryptexes/OS",
        "/private/preboot/Cryptexes/OS/usr/lib/libobjc-trampolines.dylib",
        "/private/preboot/Cryptexes/App",
        "/private/preboot/Cryptexes/App/System/Library/Test.framework/Test",
        "/preboot/Cryptexes/OS/usr/lib/libobjc-trampolines.dylib",
        "/preboot/Cryptexes/App/System/Library/Test.framework/Test",
    };
    for(unsigned i = 0; i < sizeof(stock) / sizeof(stock[0]); i++) {
        assert(shdw_is_stock_cryptex_path(stock[i]));
        if(shdw_is_restricted_root_with_prefix(stock[i], "/private/preboot/fixture/jb")) {
            fprintf(stderr, "stock system path incorrectly restricted: %s\n", stock[i]);
            return 1;
        }
    }
    const char *restricted[] = {
        "/var/jb", "/var/jb/usr/lib/test.dylib", "/private/var/jb/test",
        "/cores/test", "/private/preboot/fixture/jb/usr/lib/test.dylib",
        "/private/preboot/Cryptexes", "/private/preboot/Cryptexes/Other/test",
        "/private/preboot/Cryptexes/OS-extra/test",
        "/private/preboot/Cryptexes/Apps/test",
        "/private/preboot/Cryptexes/OS/../test",
        "/private/preboot/Cryptexes/OS/usr/../../test",
        "/private/preboot/Cryptexes/OS/%2e%2e/test",
    };
    for(unsigned i = 0; i < sizeof(restricted) / sizeof(restricted[0]); i++) {
        assert(!shdw_is_stock_cryptex_path(restricted[i]));
        if(!shdw_is_restricted_root_with_prefix(restricted[i], NULL)) {
            fprintf(stderr, "restricted path incorrectly admitted: %s\n", restricted[i]);
            return 1;
        }
    }
    assert(!shdw_is_restricted_root_with_prefix(NULL, NULL));
    assert(!shdw_is_stock_cryptex_path(NULL));
    assert(!shdw_is_stock_cryptex_path("/private/preboot/Cryptexes/OS-other"));
    assert(!shdw_is_stock_cryptex_path("/preboot/Cryptexes/App/../../test"));
    assert(!shdw_is_stock_cryptex_path("/preboot/Cryptexes/App/usr/%2f../test"));
    assert(!shdw_is_stock_cryptex_path("/private/preboot-extra/Cryptexes/OS/test"));
    assert(!shdw_is_stock_cryptex_path("/private/preboot/Cryptexes-extra/OS/test"));
    assert(!shdw_is_restricted_root_with_prefix("", NULL));
    assert(!shdw_is_restricted_root_with_prefix("/private/preboot", NULL));
    assert(!shdw_is_restricted_root_with_prefix("/var/jb-extra/test", NULL));
    assert(shdw_is_restricted_root_with_prefix(
        "/private/preboot/Cryptexes/OS/custom/test", "/private/preboot/Cryptexes/OS/custom"));
    assert(shdw_is_restricted_root_with_prefix(
        "/private/preboot/Cryptexes/App/custom/test", "/private/preboot/Cryptexes/App/custom/"));
    assert(!shdw_is_restricted_root_with_prefix(
        "/private/preboot/Cryptexes/OS/usr/lib/test", "/private/preboot/Cryptexes/OS/custom"));
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="shadow-stock-cryptex-") as temporary:
    temporary = Path(temporary)
    fixture = temporary / "fixture.c"
    fixture.write_text(pure + cases)
    for mode in (None, "SHADOW_ROOTHIDE", "SHADOW_TEST_HARNESS"):
        binary = temporary / (mode or "rootless")
        command = ["clang", "-std=c11", "-Wall", "-Wextra", "-Werror"]
        if mode:
            command.append("-D" + mode)
        subprocess.run(command + [str(fixture), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
print("stock Cryptex namespaces: aliases, boundaries, traversal and captured roots passed")
