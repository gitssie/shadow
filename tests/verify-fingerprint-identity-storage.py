"""Execute production IDFV storage/policy against mutable persisted-source doubles."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
policy = root / "src/ShadowCore.dylib/policy"


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
static NSMutableDictionary *owners, *persisted, *reads, *dataReads;
@interface ShadowSettings : NSObject
+ (instancetype)sharedInstance;
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier vendorIdentifier:(NSUUID *__autoreleasing *)vendor;
@end
@implementation ShadowSettings
+ (instancetype)sharedInstance { static id value; if(!value) value = [self new]; return value; }
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier {
    id owner = owners[identifier]; return owner == NSNull.null ? nil : (owner ?: identifier);
}
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier vendorIdentifier:(NSUUID *__autoreleasing *)vendor {
    reads[identifier] = @([reads[identifier] unsignedIntValue] + 1);
    dataReads[identifier] = @([dataReads[identifier] unsignedIntValue] + 1);
    NSDictionary *data = persisted[identifier];
    id value = data[@"VendorIdentifier"];
    *vendor = [value isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:value] : nil;
    return [data[@"InvalidData"] boolValue] ? nil : [data copy];
}
@end
'''
storage = (policy / "FingerprintStorage.m").read_text()
for signature in ["NSString *SHDWFingerprintOwnerIdentifier(",
                  "static NSDictionary *SHDWFingerprintProcessSnapshot(",
                  "NSUUID *SHDWFingerprintStoredVendorIdentifier(",
                  "NSDictionary *SHDWFingerprintData("]:
    source += "\n" + function(storage, signature)
source += "\n" + function((policy / "FingerprintPolicy.m").read_text(),
                            "NSUUID *SHDWFingerprintVendorIdentifier(")
source += r'''
int main(void) { @autoreleasepool {
    owners = [NSMutableDictionary new]; persisted = [NSMutableDictionary new];
    reads = [NSMutableDictionary new]; dataReads = [NSMutableDictionary new];
    NSString *first = @"A17E1807-1001-4000-8000-000000000001";
    NSString *second = @"A17E1807-1001-4000-8000-000000000002";
    owners[@"app.extension"] = @"app";
    persisted[@"app"] = @{@"VendorIdentifier":first, @"MemoryDelta":@16384};
    for(unsigned i = 0; i < 100; ++i) {
        assert([SHDWFingerprintVendorIdentifier(@"app").UUIDString isEqual:first]);
        assert([SHDWFingerprintVendorIdentifier(@"app.extension").UUIDString isEqual:first]);
    }
    assert([reads[@"app"] unsignedIntValue] == 1 && !reads[@"app.extension"]);
    NSDictionary *snapshot = SHDWFingerprintData(@"app.extension");
    assert([snapshot[@"VendorIdentifier"] isEqual:first]);
    assert(snapshot == SHDWFingerprintData(@"app") && [dataReads[@"app"] unsignedIntValue] == 1);
    persisted[@"app"] = @{@"VendorIdentifier":second};
    owners[@"app.extension"] = @"other";
    assert([SHDWFingerprintOwnerIdentifier(@"app.extension") isEqual:@"app"]);
    assert([SHDWFingerprintVendorIdentifier(@"app.extension").UUIDString isEqual:first]);
    assert(SHDWFingerprintData(@"app.extension") == snapshot);

    // Reading other fingerprint fields first must pin the same identity.
    persisted[@"reverse"] = @{@"VendorIdentifier":first};
    NSDictionary *reverse = SHDWFingerprintData(@"reverse");
    persisted[@"reverse"] = @{@"VendorIdentifier":second};
    assert([SHDWFingerprintVendorIdentifier(@"reverse").UUIDString isEqual:reverse[@"VendorIdentifier"]]);
    assert([reads[@"reverse"] unsignedIntValue] == 1);
    persisted[@"damaged"] = @{@"VendorIdentifier":first, @"InvalidData":@YES};
    assert(SHDWFingerprintData(@"damaged").count == 0);
    assert([SHDWFingerprintVendorIdentifier(@"damaged").UUIDString isEqual:first]);

    // No bundle-prefix guessing and no cross-app identity reuse.
    persisted[@"app.extension.other"] = @{@"VendorIdentifier":second};
    assert([SHDWFingerprintVendorIdentifier(@"app.extension.other").UUIDString isEqual:second]);
    assert([reads[@"app.extension.other"] unsignedIntValue] == 1);

    for(id invalid in @[@{}, @{@"VendorIdentifier":@123}, @{@"VendorIdentifier":@"invalid"}]) {
        NSString *key = NSUUID.UUID.UUIDString;
        persisted[key] = invalid;
        assert(!SHDWFingerprintVendorIdentifier(key));
        persisted[key] = @{@"VendorIdentifier":first};
        assert(!SHDWFingerprintVendorIdentifier(key));
        assert([reads[key] unsignedIntValue] == 1);
    }
    assert(!SHDWFingerprintVendorIdentifier(@"missing"));
    assert(SHDWFingerprintData(@"missing").count == 0);
    persisted[@"missing"] = @{@"VendorIdentifier":first};
    assert(!SHDWFingerprintVendorIdentifier(@"missing"));
    assert(SHDWFingerprintData(@"missing").count == 0);
    owners[@"unresolved"] = NSNull.null;
    assert(!SHDWFingerprintVendorIdentifier(@"unresolved") && !reads[@"unresolved"]);
    assert(!SHDWFingerprintData(@"unresolved"));
    assert(!SHDWFingerprintVendorIdentifier(nil) && !SHDWFingerprintVendorIdentifier(@""));
    puts("fingerprint identity storage: host/extension source, stable UUID, failure pinning and isolation passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-identity-storage-") as tmp:
    src, binary = Path(tmp) / "test.m", Path(tmp) / "test"
    src.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation",
                    str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
