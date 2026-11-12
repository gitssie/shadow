#!/usr/bin/env python3
"""Exercise the WebContent host-zone adapter with the system ICU converter."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
static void Check(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static BOOL Reject, MissingHost, MissingConverter;
static unsigned HookCalls;
static void *Replacement;
static int32_t NativeHost(uint16_t *buffer, int32_t capacity, int32_t *status) {
    (void)buffer; (void)capacity; (void)status; return 77;
}
static void *Lookup(void *handle, const char *name) {
    if (!strcmp(name, "ucal_getHostTimeZone")) return MissingHost ? NULL : (void *)&NativeHost;
    Check(!strcmp(name, "u_strFromUTF8"), "unexpected lookup");
    return MissingConverter ? NULL : dlsym(handle, name);
}
static bool SHDWLocalizationHookFunction(const char *symbol, void *target, void *replacement, void **original) {
    Check(!strcmp(symbol, "ucal_getHostTimeZone"), "wrong host-zone import");
    Check(original && *original == (void *)&NativeHost, "original not published before binding");
    Check(target == (void *)&NativeHost, "wrong function entrypoint");
    HookCalls++; Replacement = replacement; return !Reject;
}
#define dlsym Lookup
#include "Zone.inc"
#undef dlsym
static NSDictionary *Zone(NSString *name) { return @{@"TimeZone":name}; }
static NSString *ReadZone(void) {
    uint16_t buffer[256]; int32_t status = 0; errno = EDOM;
    int32_t count = ((HostTimeZone)Replacement)(buffer, 256, &status);
    Check(errno == EDOM && status <= 0 && count > 0 && count < 256 && buffer[count] == 0,
          "zone output/status/errno differs");
    return [[NSString alloc] initWithCharacters:buffer length:count];
}
int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *mode = @(argv[1]);
    Check(!SHDWLocalizationInstallWebTimeZone(nil) &&
          !SHDWLocalizationInstallWebTimeZone(@{@"TimeZone":@7}) &&
          !SHDWLocalizationInstallWebTimeZone(Zone(@"invalid/zone")) && !HookCalls,
          "invalid config attempted installation");
    Reject = [mode isEqual:@"rejected"];
    MissingHost = [mode isEqual:@"missing-host"];
    MissingConverter = [mode isEqual:@"missing-converter"];
    errno = ERANGE;
    BOOL installed = SHDWLocalizationInstallWebTimeZone(Zone(@"Europe/London"));
    Check(errno == ERANGE && installed == !(Reject || MissingHost || MissingConverter),
          "installation result/errno differs");
    if (!installed) {
        Check(!SHDWLocalizationInstallWebTimeZone(Zone(@"Europe/London")), "failed install retried");
        Check(HookCalls == (Reject ? 1u : 0u), "unexpected retry after failed activation");
        return 0;
    }
    Check([ReadZone() isEqual:@"Europe/London"], "host timezone not overridden");
    uint16_t buffer[64]; int32_t status = 0;
    HostTimeZone getter = (HostTimeZone)Replacement;
    int32_t count = getter(NULL, 0, &status);
    Check(count == 13 && status == 15, "ICU size preflight differs");
    status = 0; count = getter(buffer, 13, &status);
    Check(count == 13 && status == -124, "ICU exact-capacity warning differs");
    status = 0; count = getter(buffer, 4, &status);
    Check(count == 13 && status == 15, "ICU overflow differs");
    status = 1; buffer[0] = 123; count = getter(buffer, 64, &status);
    Check(status == 1 && buffer[0] == 123 && count == 0, "failed status was not preserved");
    status = 0; count = getter(NULL, 3, &status);
    Check(status == 1 && count == 0, "invalid destination accepted");
    Check(getter(buffer, 64, NULL) == 0, "null status changed ICU behavior");
    Check(SHDWLocalizationInstallWebTimeZone(Zone(@"America/New_York")) && HookCalls == 1 &&
          [ReadZone() isEqual:@"America/New_York"], "pre-success configuration retry cannot update zone");
    puts("WebContent host timezone: ICU output, errors, preflight, retry, errno passed");
} return 0; }
'''

with tempfile.TemporaryDirectory(prefix="shadow-web-timezone-") as directory:
    temp = Path(directory)
    implementation = (ROOT / "src/Localization/WebTimeZone.m").read_text()
    (temp / "Zone.inc").write_text("\n".join(
        line for line in implementation.splitlines() if not line.startswith("#import")))
    source, binary = temp / "main.m", temp / "check"
    source.write_text(HARNESS)
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks",
                    "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "-framework", "Foundation", str(source), "-o", str(binary)], check=True)
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
    for mode in ("valid", "rejected", "missing-host", "missing-converter"):
        subprocess.run([str(binary), mode], check=True, env=environment)
