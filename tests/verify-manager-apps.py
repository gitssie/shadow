"""Exercise the app catalog's actual path eligibility on the Foundation host."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
service = root / "src/Shadow.app/Services"
program = r'''
#import <Foundation/Foundation.h>
#import "ApplicationEligibility.h"
#include <assert.h>
int main(void) { @autoreleasepool {
    NSString *probe = @"local.sdkprobe.app";
    assert(SHDWApplicationIsEligible(probe, @"/private/var/containers/Bundle/Application/A/SDKMatchProbe.app"));
    assert(SHDWApplicationIsEligible(probe, @"/var/containers/Bundle/Application/A/SDKMatchProbe.app"));
    assert(!SHDWApplicationIsEligible(probe, @"/System/Applications/Test.app"));
    assert(!SHDWApplicationIsEligible(probe, @"/var/jb/Applications/Test.app"));
    assert(!SHDWApplicationIsEligible(probe, @"/private/preboot/Bootstrap/Applications/Test.app"));
    assert(!SHDWApplicationIsEligible(@"com.apple.mobilesafari", @"/var/containers/Bundle/Application/A/Test.app"));
    assert(!SHDWApplicationIsEligible(@"me.jjolano.shadow.manager", @"/var/containers/Bundle/Application/A/Test.app"));
    assert(!SHDWApplicationIsEligible(probe, @"/var/containers/Bundle/Application/A/../../../../System/Test.app"));
    assert(!SHDWApplicationIsEligible(nil, @"/var/containers/Bundle/Application/A/Test.app"));
    assert(!SHDWApplicationIsEligible(probe, nil));
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-manager-apps-") as directory:
    source = Path(directory) / "test.m"
    binary = Path(directory) / "test"
    source.write_text(program)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-framework", "Foundation", "-I", str(service), str(source),
                    str(service / "ApplicationEligibility.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
catalog = (service / "InstalledApplications.m").read_text()
assert "SHDWApplicationIsEligible(identifier, path)" in catalog
assert "applicationType" not in catalog
print("manager catalog: container-installed Probe eligibility, system paths, identifiers and traversal passed")
