"""Invoke production diagnostics with the default build configuration."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
# Keep production conditionals and bodies; only remove platform hook imports.
implementations = "\n".join(
    "\n".join(line for line in (root / path).read_text().splitlines()
              if not line.startswith("#import"))
    for path in ("src/Transport/NetworkDiagnostics.m",
                 "src/ShadowCore.dylib/policy/WebFrameDiagnostics.m",
                 "src/ShadowCore.dylib/policy/WebCookieDiagnostics.m"))
source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <errno.h>
#include "CurlDiagnostics.h"
@class SHDWHookSession, WKWebView, WKWebViewConfiguration;
''' + implementations + r'''
int main(void) { @autoreleasepool {
    assert(SHDW_TRANSPORT_DIAGNOSTICS == 0);
    errno = EBUSY;
    assert(!SHDWCurlDiagnosticsEnabled() && errno == EBUSY);
    unsigned evaluations = 0;
    SHDWCurlTrace((evaluations++, @"stage"), (evaluations++, nil),
                  (evaluations++, @{}));
    assert(!evaluations && errno == EBUSY);
    // An ordinary object cannot satisfy hook, WebKit, task or cookie APIs.
    // Any attempt to inspect it or register a hook/script raises an exception.
    id sentinel = [NSObject new];
    SHDWNetworkDiagnosticsInstall(sentinel);
    SHDWNetworkDiagnosticsTraceRequestOrigin(sentinel, @"origin");
    SHDWNetworkDiagnosticsTraceWebHTMLOrigin(sentinel, sentinel);
    SHDWNetworkDiagnosticsAttachUploadData(sentinel, sentinel);
    SHDWNetworkDiagnosticsAttachUploadFile(sentinel, sentinel);
    SHDWWebFrameDiagnosticsInstall(sentinel);
    SHDWWebCookieDiagnosticsInstall(sentinel);
    SHDWWebCookieDiagnosticsObserveView(sentinel, sentinel, @"phase");
    SHDWWebCookieDiagnosticsStored(sentinel, sentinel, sentinel, sentinel);
    assert(errno == EBUSY);
    puts("default diagnostics: no hooks, scripts, object inspection or trace argument evaluation passed");
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-diagnostics-disabled-") as directory:
    test, binary = Path(directory) / "test.m", Path(directory) / "check"
    test.write_text(source)
    for transport in (0, 1):
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", f"-DSHADOW_CURL_IMPERSONATE={transport}",
                        "-fsanitize=address,undefined", "-framework", "Foundation",
                        "-I", str(root / "src/Transport"), "-I", str(root / "src/ShadowCore.dylib/policy"), str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        symbols = subprocess.check_output(["nm", "-u", str(binary)], text=True)
        assert not any(name in symbols for name in ("WKWebView", "WKHTTPCookieStore", "connect", "socket")), symbols
