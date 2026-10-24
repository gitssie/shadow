#!/usr/bin/env python3
"""Exercise the production cleanup traversal against isolated host fixtures."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src/ShadowCleaner/Cleaner.m"
HARNESS = r'''
#import <Security/Security.h>
#include <mach/mach.h>
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
    @try { if ([step isEqual:@"files"]) Walk(fd, @"", remove, &count); } @finally { close(fd); }
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
static mach_vm_size_t VirtualSize(void) {
    struct mach_task_basic_info info;mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;
    Require(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,(task_info_t)&info,&count)==KERN_SUCCESS,@"read task virtual size");return info.virtual_size;
}
static void EntitlementReadLifetime(NSString *source, NSString *path) {
    Require([NSFileManager.defaultManager copyItemAtPath:source toPath:path error:NULL],@"copy entitlement lifetime fixture");
    const off_t extent=80LL*1024*1024;int fd=open(path.fileSystemRepresentation,O_WRONLY|O_NOFOLLOW);
    Require(fd>=0&&!ftruncate(fd,extent),@"pad sparse entitlement lifetime fixture");close(fd);
    NSDictionary *expected;
    @autoreleasepool { expected=ExecutableEntitlements(path);Require(expected!=nil,@"read padded signature"); }
    // Warm caches outside the measured outer operation pool. The loop below must
    // bound executable data lifetime without relying on its caller draining it.
    for(NSUInteger i=0;i<2;i++) { @autoreleasepool { Require([ExecutableEntitlements(path) isEqual:expected],@"warm entitlement read"); } }
    mach_vm_size_t before=VirtualSize();
    for(NSUInteger i=0;i<8;i++)Require([ExecutableEntitlements(path) isEqual:expected],@"repeated entitlement content changed");
    mach_vm_size_t after=VirtualSize(),growth=after>before?after-before:0;
    Require(growth<(mach_vm_size_t)extent*2,[NSString stringWithFormat:@"repeated entitlement reads retained executable mappings: %.1f MiB",growth/1048576.0]);
    printf("cleanup entitlement lifetime: 8 x 80 MiB executable reads, virtual growth %.1f MiB passed\n",growth/1048576.0);
}
static void ExtensionContainers(NSString *root) {
    NSString *base = [root stringByAppendingPathComponent:@"plugin-containers"];
    NSString *selected = [base stringByAppendingPathComponent:@"11111111-1111-4111-8111-111111111111"];
    NSString *other = [base stringByAppendingPathComponent:@"22222222-2222-4222-8222-222222222222"];
    Put(selected, @"StoreKit/receipt"); Put(other, @"StoreKit/receipt");
    Require([@{@"MCMMetadataIdentifier":@"fixture.app.extension"} writeToFile:[selected stringByAppendingPathComponent:Metadata] atomically:YES], @"extension metadata");
    Require([@{@"MCMMetadataIdentifier":@"other.app.extension"} writeToFile:[other stringByAppendingPathComponent:Metadata] atomically:YES], @"unrelated extension metadata");
    NSArray *containers = @[RegisteredContainer([NSURL fileURLWithPath:selected], Canonical(base), @"fixture.app.extension")];
    Require(containers.count == 1, @"extension container not discovered");
    NSUInteger count = 0;
    ContainerStep(@{@"bundleID":@"fixture.app", @"containers":containers}, @"files", YES, &count);
    Require(count == 1 && !Exists(selected, @"StoreKit/receipt") && Exists(selected, Metadata) && Exists(other, @"StoreKit/receipt"), @"extension cleanup escaped scope or left receipt");
    Put(selected, @"StoreKit/receipt");
    Require([NSFileManager.defaultManager removeItemAtPath:[selected stringByAppendingPathComponent:Metadata] error:NULL], @"remove optional metadata fixture");
    Put([base stringByAppendingPathComponent:@"33333333-3333-4333-8333-333333333333"], @"Library/Preferences/orphan");
    containers = @[RegisteredContainer([NSURL fileURLWithPath:selected], Canonical(base), @"fixture.app.extension")];
    count = 0; ContainerStep(@{@"bundleID":@"fixture.app", @"containers":containers}, @"files", YES, &count);
    Require(count == 1 && !Exists(selected, @"StoreKit/receipt") && Exists(other, @"StoreKit/receipt"), @"registered container still depends on disk metadata");
    Require([NSFileManager.defaultManager removeItemAtPath:base error:NULL], @"remove extension fixture");
    puts("cleanup extension containers: exact metadata ownership, receipt removal and unrelated container preservation passed");
}
static void FullContainerFixture(NSString *base) {
    NSString *root = [base stringByAppendingPathComponent:@"full-container"];
    for (NSString *name in @[@"Documents/nested/data", @"Library/Preferences/custom.plist",
             @"Library/WebKit/website", @"Library/Caches/StoreKit/receipt", @"StoreKit/receipt", @"tmp/session"])
        Put(root, name);
    Put(root, Metadata); Put(root, @".com.apple.mobile_container_manager.acl.plist");
    NSString *outside = [base stringByAppendingPathComponent:@"full-outside"];
    Put(outside, @"keep");
    Require(!symlink(outside.fileSystemRepresentation, [root stringByAppendingPathComponent:@"Library/escape"].fileSystemRepresentation), @"full-container symlink fixture");
    NSDictionary *queryTarget = @{@"identifiers":@[@"fixture.full"], @"containers":@[@{@"identifier":@"fixture.full", @"path":root}]};
    NSArray *localQueries = CleanupPreferenceQueries(queryTarget, @[@"files"]);
    Require(localQueries.count >= 2 && PreferenceQueriesForStep(localQueries, @"files").count == localQueries.count && !PreferenceQueriesForStep(localQueries, @"preferences").count, @"container cleanup preference scopes leaked globally");
    NSArray *externalQueries = CleanupPreferenceQueries(@{@"identifiers":@[@"fixture.full"], @"containers":@[@{@"path":@"/nonexistent-container"}]}, @[@"preferences"]);
    Require(externalQueries.count == 1 && ![externalQueries[0][@"container"] length] && !PreferenceQueriesForStep(externalQueries, @"files").count, @"external cleanup scanned container preferences");
    struct stat st; Require(!stat(root.fileSystemRepresentation, &st), @"full-container identity");
    NSDictionary *container = @{@"identifier":@"fixture.full", @"path":root, @"inode":@(st.st_ino), @"device":@((uint64_t)st.st_dev)};
    NSDictionary *target = @{@"bundleID":@"fixture.full", @"containers":@[container]};
    NSUInteger count = 0;
    ContainerStep(target, @"files", NO, &count);
    Require(count > 0 && Exists(root, @"Library/WebKit/website"), @"full-container preflight mutated data");
    count = 0; ContainerStep(target, @"files", YES, &count);
    Require(count > 0 && Exists(outside, @"keep"), @"full-container cleanup missed data or followed symlink");
    Require(Exists(root, Metadata) && Exists(root, @".com.apple.mobile_container_manager.acl.plist"), @"full-container metadata removed");
    for (NSString *name in @[@"Documents", @"Library", @"tmp"])
        Require(Exists(root, name), @"full-container required directory missing");
    count = 0; ContainerStep(target, @"files", NO, &count);
    Require(!count, @"full-container cleanup left application data");
    // A late file must survive later category stages and be reported by the
    // final full-container check, rather than silently triggering another pass.
    Put(root, @"Library/WebKit/late");
    for (NSString *step in @[@"preferences", @"web", @"receipts"])
        ContainerStep(target, step, YES, &count);
    Require(!count && Exists(root, @"Library/WebKit/late"), @"later category repeated container deletion");
    ContainerStep(target, @"files", NO, &count);
    Require(count > 0 && Exists(root, @"Library/WebKit/late"), @"full-container recheck missed or deleted late data");
    NSMutableDictionary *changed = [container mutableCopy]; changed[@"inode"] = @0;
    BOOL rejected = NO;
    @try { ContainerStep(@{@"bundleID":@"fixture.full", @"containers":@[changed]}, @"files", YES, &count); }
    @catch (NSException *exception) { (void)exception; rejected = YES; }
    Require(rejected && Exists(root, @"Library/WebKit/late"), @"full-container identity check bypassed");
    Require([NSFileManager.defaultManager removeItemAtPath:root error:NULL], @"remove full-container fixture");
    Require([NSFileManager.defaultManager removeItemAtPath:outside error:NULL], @"remove outside fixture");
    puts("cleanup full-container: single deletion stage, metadata, directories, symlinks, late writes and identity checks passed");
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        (void)argc; NSString *root = [NSString stringWithUTF8String:argv[1]];
        ExtensionContainers(root);
        FullContainerFixture(root);
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
        Require(!Exists(root, @"Library/Preferences/example.plist") && !Exists(root, @"Library/WebKit/web") && !Exists(root, @"StoreKit/receipt"), @"container data split across unrelated steps");
        Require([NSFileManager.defaultManager fileExistsAtPath:outside], @"symlink escaped container");
        Put(root, @"Library/Preferences/new.plist"); Put(root, @"Library/WebKit/reappeared"); Put(root, @"StoreKit/new-receipt");
        for (NSString *step in @[@"preferences", @"web", @"receipts"]) {
            NSUInteger untouched = 0;
            // Invalid container identity proves external steps do not even open it.
            ContainerStep(@{@"containers":@[@{@"path":@"/nonexistent-container"}]}, step, YES, &untouched);
            Require(!untouched && Step(root, step, YES) == 0, @"external step accessed container data");
        }
        Require(Exists(root, @"Library/Preferences/new.plist") && Exists(root, @"Library/WebKit/reappeared") && Exists(root, @"StoreKit/new-receipt"), @"external step changed container data");
        Require(Step(root, @"files", NO) > 0, @"final container verification missed late data");
        Step(root, @"files", YES);
        Require(Exists(root, Metadata) && Exists(root, @".com.apple.mobile_container_manager.acl.plist"), @"registration metadata deleted");
        NSDictionary *registration = @{@"MCMMetadataIdentifier":@"example.app"};
        Require([registration writeToFile:[root stringByAppendingPathComponent:Metadata] atomically:YES], @"snapshot registration fixture");
        struct stat containerStat; Require(!stat(root.fileSystemRepresentation, &containerStat), @"snapshot container identity");
        NSDictionary *snapshotContainer = @{@"identifier":@"example.app", @"path":root, @"inode":@(containerStat.st_ino), @"device":@((uint64_t)containerStat.st_dev)};
        NSDictionary *snapshotTarget = @{@"bundleID":@"example.app", @"identifiers":@[@"example.app"], @"containers":@[snapshotContainer]};
        NSString *snapshot = @"Library/SplashBoard/Snapshots/example.app - {DEFAULT GROUP}/late.ktx";
        Put(root, snapshot);
        Require(Step(root, @"files", NO) > 0 && Exists(root, snapshot), @"pure recheck missed or removed a late UI snapshot");
        FinalizeSnapshots(snapshotTarget, @[@"web"]);
        Require(Exists(root, snapshot), @"unselected files snapshots were removed");
        FinalizeSnapshots(snapshotTarget, @[@"files"]);
        Require(!Exists(root, snapshot) && Step(root, @"files", NO) == 0, @"late UI snapshots were not finalized before pure recheck");
        Put(root, snapshot);
        NSMutableDictionary *changedContainer = [snapshotContainer mutableCopy]; changedContainer[@"inode"] = @0;
        NSMutableDictionary *changedTarget = [snapshotTarget mutableCopy]; changedTarget[@"containers"] = @[changedContainer];
        BOOL changedRejected = NO;
        @try { FinalizeSnapshots(changedTarget, @[@"files"]); } @catch (NSException *exception) { (void)exception; changedRejected = YES; }
        Require(changedRejected && Exists(root, snapshot), @"changed container identity allowed snapshot deletion");
        FinalizeSnapshots(snapshotTarget, @[@"files"]);
        NSString *snapshotParent = [root stringByAppendingPathComponent:@"Library/SplashBoard"];
        Require(!symlink(root.fileSystemRepresentation, snapshotParent.fileSystemRepresentation), @"snapshot parent symlink fixture");
        BOOL snapshotRejected = NO;
        @try { FinalizeSnapshots(snapshotTarget, @[@"files"]); } @catch (NSException *exception) { (void)exception; snapshotRejected = YES; }
        Require(snapshotRejected && [NSFileManager.defaultManager fileExistsAtPath:outside], @"snapshot finalization followed a symlink ancestor");
        Require(!unlink(snapshotParent.fileSystemRepresentation), @"remove snapshot symlink fixture");
        Put(root, @"Library/SplashBoard/Snapshots/keep.app/keep.ktx");
        NSString *snapshotLeaf = [root stringByAppendingPathComponent:@"Library/SplashBoard/Snapshots/example.app"];
        Require(!symlink(outside.fileSystemRepresentation, snapshotLeaf.fileSystemRepresentation), @"snapshot leaf symlink fixture");
        snapshotRejected = NO;
        @try { FinalizeSnapshots(snapshotTarget, @[@"files"]); } @catch (NSException *exception) { (void)exception; snapshotRejected = YES; }
        Require(snapshotRejected && Exists(root, @"Library/SplashBoard/Snapshots/keep.app/keep.ktx"), @"unsafe snapshot leaf accepted or unrelated snapshot removed");
        Require(!unlink(snapshotLeaf.fileSystemRepresentation), @"remove snapshot leaf fixture");
        FinalizeSnapshots(snapshotTarget, @[@"files"]);
        Require(Exists(root, @"Library/SplashBoard/Snapshots/keep.app/keep.ktx"), @"finalization removed another application's snapshots");
        NSArray *cleanupOrder = @[@"files", @"preferences", @"web", @"keychain", @"receipts", @"fingerprint"];
        NSDictionary *completed = @{@"token":@"authorized", @"created":@(NSDate.date.timeIntervalSince1970), @"steps":@[@"files", @"fingerprint"], @"next":@1};
        ValidateCompletedSession(completed, @"authorized", @[@"files", @"fingerprint"], cleanupOrder);
        for (NSDictionary *invalid in @[
            @{@"token":@"changed", @"created":completed[@"created"], @"steps":completed[@"steps"], @"next":@1},
            @{@"token":@"authorized", @"created":completed[@"created"], @"steps":completed[@"steps"], @"next":@0},
            @{@"token":@"authorized", @"created":@0, @"steps":completed[@"steps"], @"next":@1}]) {
            BOOL sessionRejected = NO;
            @try { ValidateCompletedSession(invalid, @"authorized", @[@"files", @"fingerprint"], cleanupOrder); }
            @catch (NSException *exception) { (void)exception; sessionRejected = YES; }
            Require(sessionRejected, @"unauthorized, unfinished or expired finalization accepted");
        }
        BOOL scopeRejected = NO;
        @try { ValidateCompletedSession(completed, @"authorized", @[@"files"], cleanupOrder); }
        @catch (NSException *exception) { (void)exception; scopeRejected = YES; }
        Require(scopeRejected, @"changed finalization selection accepted");
        puts("cleanup snapshot finalization: late writes, pure recheck, selected scope, symlinks and authorization passed");
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
        EntitlementReadLifetime(argc>2 ? Canonical([NSString stringWithUTF8String:argv[2]]) : [signatureBundle stringByAppendingPathComponent:@"Example App"], [Canonical(root) stringByAppendingPathComponent:@"large-signed-copy"]);
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

LOCK_HARNESS = r'''#import <Foundation/Foundation.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
static NSString *SessionRoot;
static void Fail(NSString *reason) { @throw [NSException exceptionWithName:@"LockFixture" reason:reason userInfo:nil]; }
static void Require(BOOL value, NSString *reason) { if(!value) Fail(reason); }
static NSString *Hash(NSArray *values) { return values.firstObject; }
__LOCK_SOURCE__
static void Blocked(BOOL exclusive) {
    BOOL blocked=NO;
    @try { int fd=SessionLockForAccess(@"fixture.app",exclusive);close(fd); }
    @catch(NSException *exception) { blocked=[exception.reason isEqual:@"An operation is already running."]; }
    Require(blocked,exclusive ? @"writer escaped an active session lock" : @"reader escaped an active writer");
}
int main(int argc,const char **argv) { @autoreleasepool {
    Require(argc==2,@"lock fixture arguments");SessionRoot=@(argv[1]);
    int first=SessionLockForAccess(@"fixture.app",NO),second=SessionLockForAccess(@"fixture.app",NO);
    Require(first>=0&&second>=0,@"independent readers cannot share the session lock");close(second);
    Blocked(YES);close(first);
    int writer=SessionLockForAccess(@"fixture.app",YES);Blocked(NO);Blocked(YES);close(writer);
    int cleanup=SessionLock(@"fixture.app");Blocked(NO);Blocked(YES);close(cleanup);
    int released=SessionLockForAccess(@"fixture.app",NO);close(released);
    puts("cleanup session locking: shared readers, exclusive writers, cleanup exclusion and close release passed");
}return 0;}
'''


def verify_session_locks(temp):
    source = SOURCE.read_text()
    begin = source.index("static int SessionLock")
    end = source.index("static NSString *SessionPath", begin)
    lock = source[begin:end]
    # Only adapt the root-only storage owner to the host user's private fixture.
    # mkdir/open/flock/close remain the production implementation and real syscalls.
    lock = lock.replace("st.st_uid == 0", "st.st_uid == geteuid()").replace("st.st_uid != 0", "st.st_uid != geteuid()")
    source_path = temp / "locks.m"
    source_path.write_text(LOCK_HARNESS.replace("__LOCK_SOURCE__", lock))
    binary = temp / "locks"
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation", str(source_path), "-o", str(binary)], check=True)
    subprocess.run([str(binary), str(temp / "sessions")], check=True)


with tempfile.TemporaryDirectory(prefix="shadow-cleanup-test-") as temp:
    temp = Path(temp)
    verify_session_locks(temp)
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
