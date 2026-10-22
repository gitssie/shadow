#!/usr/bin/env python3
"""Exercise the production cleanup traversal against isolated host fixtures."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src/ShadowCleaner/Cleaner.m"
HARNESS = r'''
#import <Security/Security.h>
static OSStatus FakeDelete(CFDictionaryRef query);
static OSStatus FakeCopy(CFDictionaryRef query, CFTypeRef *result);
#define SecItemDelete FakeDelete
#define SecItemCopyMatching FakeCopy
#import "__SOURCE__"
#undef SecItemDelete
#undef SecItemCopyMatching
static NSMutableDictionary *fakeItems;
static NSUInteger fakeDeletes;
static NSUInteger fakeCopies;
static BOOL fakeEarlyQuery;
static BOOL fakeStuckIdentity;
static OSStatus fakeCopyError;
static BOOL fakeEmptyIdentityArray;
static BOOL fakeInvalidResult;
static BOOL fakeSuccessNull;
static OSStatus FakeDelete(CFDictionaryRef raw) {
    NSDictionary *query = (__bridge NSDictionary *)raw;
    NSString *group = query[(__bridge id)kSecAttrAccessGroup], *itemClass = query[(__bridge id)kSecClass];
    Require([group isEqual:@"TEAM.example.app"], @"keychain operation escaped target group");
    Require(query[(__bridge id)kSecAttrSynchronizable] == (__bridge id)kSecAttrSynchronizableAny, @"keychain sync coverage missing");
    fakeDeletes++;
    if (![itemClass isEqual:(__bridge id)kSecClassIdentity]) [fakeItems[group] removeObjectForKey:itemClass];
    return errSecSuccess;
}
static OSStatus FakeCopy(CFDictionaryRef raw, CFTypeRef *result) {
    fakeCopies++;
    NSDictionary *query = (__bridge NSDictionary *)raw;
    NSString *group = query[(__bridge id)kSecAttrAccessGroup], *itemClass = query[(__bridge id)kSecClass];
    if (fakeDeletes && fakeDeletes < 5) fakeEarlyQuery = YES;
    if (fakeCopyError) return fakeCopyError;
    if (fakeSuccessNull) return errSecSuccess;
    if (fakeInvalidResult) { *result = CFRetain(CFSTR("unexpected")); return errSecSuccess; }
    BOOL exists = [fakeItems[group][itemClass] boolValue];
    if ([itemClass isEqual:(__bridge id)kSecClassIdentity]) exists = fakeStuckIdentity || ([fakeItems[group][(__bridge id)kSecClassCertificate] boolValue] && [fakeItems[group][(__bridge id)kSecClassKey] boolValue]);
    if (exists) { *result = CFRetain((__bridge CFTypeRef)@[@{}]); return errSecSuccess; }
    if (fakeEmptyIdentityArray && [itemClass isEqual:(__bridge id)kSecClassIdentity]) { *result = CFRetain((__bridge CFTypeRef)@[]); return errSecSuccess; }
    return errSecItemNotFound;
}
static void Put(NSString *root, NSString *relative) {
    NSString *path = [root stringByAppendingPathComponent:relative];
    Require([NSFileManager.defaultManager createDirectoryAtPath:path.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:NULL], @"fixture directory");
    Require([@"fixture" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:NULL], @"fixture file");
}
static BOOL Exists(NSString *root, NSString *relative) { return [NSFileManager.defaultManager fileExistsAtPath:[root stringByAppendingPathComponent:relative]]; }
static NSUInteger Step(NSString *root, NSString *step, BOOL remove) {
    int fd = open(root.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    Require(fd >= 0, @"open fixture"); NSUInteger count = 0;
    @try { Walk(fd, @"", step, remove, &count); } @finally { close(fd); }
    return count;
}
static void SignatureFixture(NSString *bundle, BOOL derOnly) {
    Require([NSFileManager.defaultManager createDirectoryAtPath:bundle withIntermediateDirectories:YES attributes:nil error:NULL], @"signature fixture directory");
    Require([@{@"CFBundleExecutable":@"Example App"} writeToFile:[bundle stringByAppendingPathComponent:@"Info.plist"] atomically:YES], @"signature fixture info");
    struct mach_header_64 header = {0}; header.magic = MH_MAGIC_64; header.ncmds = 1; header.sizeofcmds = sizeof(struct linkedit_data_command);
    struct linkedit_data_command link = {0}; link.cmd = LC_CODE_SIGNATURE; link.cmdsize = sizeof(link); link.dataoff = sizeof(header) + sizeof(link); link.datasize = derOnly ? 20 : 12;
    uint32_t signature[5] = {OSSwapHostToBigInt32(0xfade0cc0), OSSwapHostToBigInt32(link.datasize), OSSwapHostToBigInt32(derOnly ? 1 : 0), OSSwapHostToBigInt32(7), OSSwapHostToBigInt32(20)};
    NSMutableData *bytes = [NSMutableData dataWithBytes:&header length:sizeof(header)];
    [bytes appendBytes:&link length:sizeof(link)]; [bytes appendBytes:signature length:link.datasize];
    Require([bytes writeToFile:[bundle stringByAppendingPathComponent:@"Example App"] atomically:YES], @"signature fixture executable");
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        (void)argc; NSString *root = [NSString stringWithUTF8String:argv[1]];
        Put(root, @"Documents/data"); Put(root, @"Library/Application Support/data");
        Put(root, @"Library/Preferences/example.plist"); Put(root, @"Library/Caches/cache");
        Put(root, @"Library/Caches/WebKit/web"); Put(root, @"Library/WebKit/web");
        Put(root, @"Library/Cookies/cookie"); Put(root, @"tmp/cache");
        Put(root, @"StoreKit/receipt"); Put(root, @"Library/Caches/StoreKit/receipt");
        Put(root, Metadata); Put(root, @".com.apple.mobile_container_manager.acl.plist");
        NSString *outside = [root stringByAppendingString:@"-outside"];
        Require([@"keep" writeToFile:outside atomically:YES encoding:NSUTF8StringEncoding error:NULL], @"outside fixture");
        Require(!symlink(outside.fileSystemRepresentation, [root stringByAppendingPathComponent:@"escape"].fileSystemRepresentation), @"symlink fixture");
        Require(Step(root, @"files", NO) > 0 && Exists(root, @"Documents/data"), @"preflight mutated data");
        Require(Step(root, @"files", YES) > 0 && Step(root, @"files", NO) == 0, @"files verification");
        Require(!Exists(root, @"Documents/data") && !Exists(root, @"Library/Application Support/data"), @"files not removed");
        Require(Exists(root, @"Library/Preferences/example.plist") && Exists(root, @"Library/WebKit/web") && Exists(root, @"StoreKit/receipt"), @"later step removed early");
        Require([NSFileManager.defaultManager fileExistsAtPath:outside], @"symlink escaped container");
        Require(Step(root, @"preferences", YES) > 0 && Step(root, @"preferences", NO) == 0, @"preferences verification");
        Require(Exists(root, @"Library/Caches/WebKit/web") && Exists(root, @"Library/Caches/StoreKit/receipt"), @"cache children crossed step boundary");
        Require(Step(root, @"web", YES) > 0 && Step(root, @"web", NO) == 0, @"web verification");
        Require(Exists(root, @"StoreKit/receipt") && Exists(root, @"Library/Caches/StoreKit/receipt"), @"receipt preservation");
        Require(Step(root, @"files", NO) == 0 && Step(root, @"preferences", NO) == 0 && Step(root, @"web", NO) == 0, @"unselected receipt blocked final scope verification");
        Put(root, @"Library/WebKit/reappeared");
        Require(Step(root, @"web", NO) > 0 && Exists(root, @"Library/WebKit/reappeared"), @"final verification missed a reappeared selected item or deleted it");
        Step(root, @"web", YES);
        Require(Step(root, @"receipts", YES) == 2 && Step(root, @"receipts", NO) == 0, @"receipts verification");
        Require(Exists(root, Metadata) && Exists(root, @".com.apple.mobile_container_manager.acl.plist"), @"registration metadata deleted");
        NSString *library = [root stringByAppendingPathComponent:@"Library"];
        Require([NSFileManager.defaultManager removeItemAtPath:library error:NULL], @"reset library");
        Require(!symlink(root.fileSystemRepresentation, library.fileSystemRepresentation), @"ancestor symlink fixture");
        BOOL rejected = NO; @try { Step(root, @"files", NO); } @catch (NSException *exception) { (void)exception; rejected = YES; }
        Require(rejected, @"symlink ancestor not rejected");
        int protectedRoot = open(root.fileSystemRepresentation, O_RDONLY | O_DIRECTORY);
        Require(protectedRoot >= 0, @"open protected fixture");
        Require(!RemoveAt(protectedRoot, ".") && !RemoveAt(protectedRoot, "..") && !RemoveAt(protectedRoot, "../outside") && !RemoveAt(protectedRoot, ""), @"unsafe deletion component accepted");
        close(protectedRoot);
        Require([NSFileManager.defaultManager fileExistsAtPath:outside], @"protected sibling deleted");
        Require(!BundleIdentifier(@"..") && !BundleIdentifier(@".") && !BundleIdentifier(@"example..app") && !BundleIdentifier(@"example.app.") && BundleIdentifier(@"local.sdkprobe.app"), @"bundle identifier validation");
        Require([ValidateBundleIdentity(@{@"CFBundleIdentifier":@"example.app.extension"}, @{@"application-identifier":@"TEAM.example.app.extension"}, @"example.app", @"TEAM") isEqual:@"TEAM"], @"valid extension identity");
        for (NSArray *pair in @[
            @[@"victim.app", @"TEAM.victim.app"],
            @[@"example.app.extension", @"OTHER.example.app.extension"],
            @[@"example.app.extension", @"TEAM.victim.app"]]) {
            BOOL identityRejected = NO;
            @try { ValidateBundleIdentity(@{@"CFBundleIdentifier":pair[0]}, @{@"application-identifier":pair[1]}, @"example.app", @"TEAM"); }
            @catch (NSException *exception) { (void)exception; identityRejected = YES; }
            Require(identityRejected, @"adversarial extension identity accepted");
        }
        Require([Hash(@{@"a":@1, @"b":@2}) isEqual:Hash(@{@"b":@2, @"a":@1})], @"unstable identity token");
        NSString *signatureBundle = [Canonical(root) stringByAppendingPathComponent:@"Signature.app"];
        SignatureFixture(signatureBundle, NO);
        Require(Entitlements(signatureBundle).count == 0, @"valid signature without entitlement slots rejected");
        SignatureFixture(signatureBundle, YES);
        BOOL unsupportedDER = NO;
        @try { Entitlements(signatureBundle); } @catch (NSException *exception) { unsupportedDER = [exception.reason containsString:@"DER-only"]; }
        Require(unsupportedDER, @"DER-only ownership silently treated as empty");
        fakeItems = [@{@"TEAM.example.app":[@{(__bridge id)kSecClassCertificate:@YES, (__bridge id)kSecClassKey:@YES, (__bridge id)kSecClassGenericPassword:@YES, (__bridge id)kSecClassInternetPassword:@YES} mutableCopy], @"TEAM.control.app":[@{(__bridge id)kSecClassGenericPassword:@YES} mutableCopy]} mutableCopy];
        Require(KeychainWork(@[@"TEAM.example.app"], NO, NO) == 0 && fakeDeletes == 0, @"keychain preflight mutated items");
        Require([keychainClassCounts[(__bridge id)kSecClassIdentity] unsignedIntegerValue] == 1 && [keychainClassCounts[(__bridge id)kSecClassGenericPassword] unsignedIntegerValue] == 1, @"keychain preflight aggregate counts incorrect");
        NSUInteger copiesBeforeClear = fakeCopies;
        Require(KeychainWork(@[@"TEAM.example.app"], YES, YES) == 0 && fakeDeletes == 5 && fakeCopies == copiesBeforeClear && !fakeEarlyQuery, @"keychain clear performed intermediate residual queries");
        Require([fakeItems[@"TEAM.control.app"] count] == 1 && [fakeItems[@"TEAM.example.app"] count] == 0, @"keychain target or control state incorrect");
        Require(KeychainWork(@[@"TEAM.example.app"], NO, YES) == 0, @"independent empty keychain recheck failed");
        for (NSNumber *count in keychainClassCounts.allValues) Require(count.unsignedIntegerValue == 0, @"final keychain aggregate count not zero");
        fakeEmptyIdentityArray = YES;
        Require(KeychainWork(@[@"TEAM.example.app"], NO, YES) == 0, @"success with an empty identity array was treated as remaining items");
        fakeStuckIdentity = YES;
        Require(KeychainWork(@[@"TEAM.example.app"], NO, YES) == 4 && keychainCount == 1 && [keychainClass isEqual:(__bridge id)kSecClassIdentity] && [keychainPhase isEqual:@"verify"], @"keychain leftover did not retain class/count diagnostics");
        fakeStuckIdentity = NO; fakeCopyError = errSecInteractionNotAllowed;
        Require(KeychainWork(@[@"TEAM.example.app"], NO, NO) == 3 && keychainStatus == errSecInteractionNotAllowed, @"keychain permission error treated as empty");
        fakeCopyError = 0; fakeInvalidResult = YES;
        Require(KeychainWork(@[@"TEAM.example.app"], NO, YES) == 3 && keychainStatus == errSecDecode, @"unexpected keychain result type treated as empty");
        fakeInvalidResult = NO; fakeSuccessNull = YES;
        Require(KeychainWork(@[@"TEAM.example.app"], NO, YES) == 3 && keychainStatus == errSecDecode, @"success with no typed keychain result treated as verified empty");
        NSDictionary *baseEntitlements = @{@"platform-application":@YES, @"keychain-access-groups":@[@"*"]};
        NSDictionary *exact = ExactEntitlements(baseEntitlements, @[@"TEAM.example.app"]);
        Require([exact[@"keychain-access-groups"] isEqual:@[@"TEAM.example.app"]] && [exact[@"platform-application"] boolValue] && [baseEntitlements[@"keychain-access-groups"] isEqual:@[@"*"]], @"exact worker entitlements changed base or scope");
        BOOL wildcardRejected = NO;
        @try { ExactEntitlements(baseEntitlements, @[@"*"]); } @catch (NSException *exception) { (void)exception; wildcardRejected = YES; }
        Require(wildcardRejected, @"worker signing accepted wildcard scope");
        Require([ValidatedKeychainScope(@{@"team":@"TEAM", @"keychainGroups":@[@"TEAM.example.app"]}) isEqual:@[@"TEAM.example.app"]], @"same-team keychain scope rejected");
        for (NSString *group in @[@"VICTIM.example.app", @"com.apple.token", @"apple.system", @"*"]) {
            BOOL scopeRejected = NO;
            @try { ValidatedKeychainScope(@{@"team":@"TEAM", @"keychainGroups":@[group]}); } @catch (NSException *exception) { (void)exception; scopeRejected = YES; }
            Require(scopeRejected, @"cross-team or system keychain group accepted before signing");
        }
        Require([KeychainGroups(@{@"application-identifier":@"TEAM.example.app"}) isEqual:@[@"TEAM.example.app"]] && KeychainGroups(@{@"keychain-access-groups":@[]}).count == 0, @"implicit default access group incorrect");
        NSDictionary *process = RunBounded(@"/usr/bin/printf", @[@"{}"], 1.0);
        Require([process[@"status"] intValue] == 0 && [process[@"output"] length] == 2, @"bounded child response incorrect");
        double started = MonotonicSeconds(); BOOL timedOut = NO;
        @try { RunBounded(@"/bin/sleep", @[@"2"], 0.05); } @catch (NSException *exception) { timedOut = [exception.reason containsString:@"timed out"]; }
        int childStatus = 0;
        Require(timedOut && MonotonicSeconds() - started < 1.0 && waitpid(-1, &childStatus, WNOHANG) == -1 && errno == ECHILD, @"bounded worker timeout left a live or unreaped child");
        if (argc > 2) Require([ExecutableEntitlements(Canonical([NSString stringWithUTF8String:argv[2]]))[@"keychain-access-groups"] isEqual:@[@"TEAM.example.app"]], @"signed exact scope readback incorrect");
        puts("cleanup engine traversal: passed");
    }
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="shadow-cleanup-test-") as temp:
    temp = Path(temp)
    harness = temp / "main.m"
    harness.write_text(HARNESS.replace("__SOURCE__", str(SOURCE)))
    binary = temp / "check"
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-framework", "Foundation", "-framework", "Security", "-framework", "LocalAuthentication", str(harness), "-o", str(binary)], check=True)
    fixture = temp / "container"
    fixture.mkdir()
    import shutil
    import plistlib
    arguments = [str(binary), str(fixture)]
    if shutil.which("ldid"):
        signed = temp / "signed-copy"
        shutil.copy2(binary, signed)
        entitlements = temp / "worker.plist"
        entitlements.write_bytes(plistlib.dumps({"keychain-access-groups": ["TEAM.example.app"]}))
        subprocess.run(["ldid", "-S" + str(entitlements), str(signed)], check=True)
        arguments.append(str(signed))
    subprocess.run(arguments, check=True)
