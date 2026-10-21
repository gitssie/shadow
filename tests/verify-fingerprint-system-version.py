"""Compile actual metadata transforms and every Foundation hook body with native doubles."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintSystemVersion.x").read_text()
cf_start = source.index("static CFDictionaryRef (*shdw_native_system_version_dictionary)")
cf = source[cf_start:source.index("\nvoid shdw_universal_fingerprint_system_version_prepare(", cf_start)]
for line in source.splitlines():
    if "%orig" in line:
        assert "}" not in line, "Logos scope closing brace must be on its own line"
helpers = source[source.index("static BOOL shdw_system_version_path("):source.index("static id (*shdw_system_version_native_class_0)")]
installer = source[source.index("static void shdw_system_version_install_class_methods("):source.index("%group")]
assert installer.count("hookMessageInClass:object_getClass(") == 13
assert "%hook NSDictionary\n+" not in source
methods, checks = [], []
entries = []
for match in re.finditer(r"^[+-] \(id\)([^\n]+) \{", source, re.M):
    entries.append((match, match.group(1), False))
for match in re.finditer(r"^static id shdw_system_version_class_(\d+)\(([^\n]+)\) \{", source, re.M):
    # Recover selector and argument types from the concrete metaclass registration.
    number = match.group(1)
    registration = re.search(r'withSelector:sel_registerName\("([^"]+)"\)\s+withReplacement:\(void \*\)&shdw_system_version_class_' + number + r'\b', source)
    assert registration
    selector = registration.group(1)
    args = re.findall(r'([^,]+?)\s+(\w+)(?:,|$)', match.group(2))[2:]
    signature = " ".join(part + ":(" + typ.strip() + ")" + name for part, (typ, name) in zip(selector.split(":")[:-1], args))
    entries.append((match, signature, True))
assert len(entries) == 26
for index, (match, signature, is_c) in enumerate(entries):
    end = match.end()
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    body = source[match.end():end - 1]
    arguments = re.findall(r"\(([^)]+)\)(\w+)", signature)
    declaration = ", ".join(typ + " " + name for typ, name in arguments)
    names = [name for _, name in arguments]
    expected_orig = "%orig(" + ", ".join(names) + ")"
    if is_c:
        body = re.sub(r"shdw_system_version_native_class_\d+\(self, _cmd, ([^)]*)\)", r"%orig(\1)", body)
    assert expected_orig in body
    assert body.count("SHADOW_INTERNAL_SCOPE") == 2
    body = body.replace(expected_orig, "nativeRead(" + ", ".join(names) + ")")
    methods.append("static id method_%d(%s) {%s}\n" % (index, declaration, body))
    is_url = "WithContentsOfURL:" in signature
    transform = re.search(r"native = (shdw_system_version_\w+)\(native\)", body)[1]
    kind = {"shdw_system_version_dictionary": 0, "shdw_system_version_data": 1, "shdw_system_version_string": 2}[transform]
    argv = ["location"]
    for typ, name in arguments[1:]:
        argv.append({"options": "NSDataReadingMappedIfSafe", "encoding": "&encoding" if "*" in typ else "NSUTF8StringEncoding", "error": "&error"}[name])
    checks.append(r"""{
        nativeKind = %d; BOOL url = %s;
        id location = url ? (id)[NSURL fileURLWithPath:target] : (id)target;
        NSError *error = sentinel; NSStringEncoding encoding = NSUTF8StringEncoding;
        nativeFailure = NO; unsigned previous = nativeCalls;
        id result = method_%d(%s);
        assert(result && nativeCalls == previous + 1 && !depth && error == sentinel);
        NSDictionary *dictionary = decode(result);
        assert([dictionary[@"ProductVersion"] isEqual:@"18.7.1"]);
        assert([dictionary[@"ProductBuildVersion"] isEqual:@"22H31"]);
        assert([dictionary[@"Unrelated"] isEqual:@42]);
        location = url ? (id)[NSURL fileURLWithPath:@"/tmp/SystemVersion.plist"] : (id)@"/tmp/SystemVersion.plist";
        result = method_%d(%s); assert([decode(result)[@"ProductVersion"] isEqual:@"16.3"]);
        nativeFailure = YES; location = url ? (id)[NSURL fileURLWithPath:target] : (id)target;
        assert(!method_%d(%s) && !depth && error == sentinel);
        (void)encoding;
    }""" % (kind, "YES" if is_url else "NO", index, ", ".join(argv), index, ", ".join(argv), index, ", ".join(argv)))
prefix = r"""
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdarg.h>
static unsigned depth, nativeCalls, nativeKind, shdw_system_version_state;
static BOOL nativeFailure, enabled = YES;
static NSString *target = @"/System/Library/CoreServices/SystemVersion.plist";
static const void *fakeCaller = (void *)1;
#define __builtin_extract_return_addr(c) (c)
#define __builtin_return_address(n) fakeCaller
static NSString *shdw_fingerprint_bundle_identifier_for_caller(const void *caller) {
    return caller && enabled && !depth ? @"metadata.app" : nil;
}
static void leave_scope(BOOL *active) { (void)active; assert(depth); depth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave_scope))) = (++depth, YES); active; active = NO)
static const char *SHDWFingerprintVersionValue(const char *name) {
    return !strcmp(name, "kern.osproductversion") ? "18.7.1" : "22H31";
}
static NSDictionary *nativeDictionary(void) {
    return @{@"ProductVersion": @"16.3", @"ProductBuildVersion": @"20D47", @"ProductUserVisibleVersion": @"16.3", @"Unrelated": @42};
}
static id nativeRead(id location, ...) {
    (void)location; nativeCalls++;
    if(nativeFailure) return nil;
    if(!nativeKind) return nativeDictionary();
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:nativeDictionary() format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL];
    return nativeKind == 1 ? (id)data : (id)[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
}
static CFDictionaryRef nativeCFDictionary(void) {
    return (CFDictionaryRef)CFBridgingRetain(nativeDictionary());
}
static NSDictionary *decode(id object) {
    if([object isKindOfClass:NSDictionary.class]) return object;
    if([object isKindOfClass:NSString.class]) object = [object dataUsingEncoding:NSUTF8StringEncoding];
    return [NSPropertyListSerialization propertyListWithData:object options:0 format:NULL error:NULL];
}
"""
extra = r"""
    assert(!shdw_sym_policy_lookup_system_version("_CFCopySystemVersionDictionary"));
    shdw_system_version_state = 2;
    assert(!shdw_sym_policy_lookup_system_version("_CFCopySystemVersionDictionary"));
    shdw_native_system_version_dictionary = nativeCFDictionary;
    assert(shdw_sym_policy_lookup_system_version("_CFCopySystemVersionDictionary") == (void *)&shdw_copy_system_version_dictionary);
    assert(!shdw_sym_policy_lookup_system_version("CFCopySystemVersionDictionary"));
    assert(!shdw_sym_policy_lookup_system_version("_CFCopySystemVersionString"));
    assert(!shdw_sym_policy_lookup_system_version(NULL));
    shdw_system_version_state = 1;
    assert(!shdw_sym_policy_lookup_system_version("_CFCopySystemVersionDictionary"));
    shdw_system_version_state = 2;
    CFDictionaryRef cf = shdw_copy_system_version_dictionary();
    NSDictionary *cfObject = CFBridgingRelease(cf);
    assert([cfObject[@"ProductVersion"] isEqual:@"18.7.1"]);
    enabled = NO;
    cfObject = CFBridgingRelease(shdw_copy_system_version_dictionary());
    assert([cfObject[@"ProductVersion"] isEqual:@"16.3"]); enabled = YES;
    assert(!depth);

    assert(shdw_system_version_path([target stringByReplacingOccurrencesOfString:@"/CoreServices/" withString:@"/CoreServices/./"], fakeCaller));
    assert(!shdw_system_version_path(@"/System/Library/CoreServices/SystemVersion.plist.extra", fakeCaller));
    assert(!shdw_system_version_path([NSURL URLWithString:@"https://example.com/SystemVersion.plist"], fakeCaller));
    enabled = NO; assert(!shdw_system_version_path(target, fakeCaller)); enabled = YES;
    depth = 1; assert(!shdw_system_version_path(target, fakeCaller)); depth = 0;
    for(NSNumber *formatNumber in @[@(NSPropertyListXMLFormat_v1_0), @(NSPropertyListBinaryFormat_v1_0)]) {
        NSPropertyListFormat format = formatNumber.unsignedIntegerValue, actual;
        NSData *data = [NSPropertyListSerialization dataWithPropertyList:nativeDictionary() format:format options:0 error:NULL];
        NSData *result = shdw_system_version_data(data);
        NSDictionary *dictionary = [NSPropertyListSerialization propertyListWithData:result options:0 format:&actual error:NULL];
        assert(format == actual && [dictionary[@"ProductVersion"] isEqual:@"18.7.1"]);
    }
    NSData *invalid = [@"not a plist" dataUsingEncoding:NSUTF8StringEncoding];
    assert(shdw_system_version_data(invalid) == invalid);
    assert(!shdw_system_version_data(nil) && !shdw_system_version_string(nil));
    NSMutableDictionary *mutable = [nativeDictionary() mutableCopy];
    assert([shdw_system_version_dictionary(mutable) isKindOfClass:NSMutableDictionary.class]);
    puts("SystemVersion metadata: all Foundation routes, exact path, native errors, XML/binary and unrelated keys passed");
"""
with tempfile.TemporaryDirectory(prefix="shadow-metadata-") as temp:
    path = Path(temp) / "test.m"
    binary = Path(temp) / "test"
    path.write_text(prefix + helpers + cf + "\n".join(methods) + "\nint main(void) { @autoreleasepool { NSError *sentinel = [NSError errorWithDomain:@\"native\" code:1 userInfo:nil];\n" + "\n".join(checks) + extra + "} }\n")
    subprocess.run(["clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable", "-framework", "Foundation", str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
