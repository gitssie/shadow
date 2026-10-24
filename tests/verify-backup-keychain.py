#!/usr/bin/env python3
"""Exercise portable backup credentials with Security API doubles, never user Keychain."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src/ShadowCleaner/StateKeychain.inc"
HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <dlfcn.h>
#include <math.h>
#include <unistd.h>
static void Fail(NSString *message) { @throw [NSException exceptionWithName:@"FixtureFailure" reason:message userInfo:nil]; }
static void Require(BOOL value, NSString *message) { if (!value) Fail(message); }
static void Check(BOOL value, NSString *message) { if (!value) { fprintf(stderr,"FAIL: %s\n", message.UTF8String); exit(1); } }
static NSString *const Group = @"TEAM.example.app";
static NSString *const Other = @"TEAM.control.app";
static NSMutableArray<NSMutableDictionary *> *items;
static NSMutableArray<NSDictionary *> *calls;
static NSUInteger mutations;
static NSInteger mode;
static id unsupportedResult;
static pid_t parentPID = 1234, keychainParent = 1234;
static BOOL loseParentAfterMutation;
static NSMutableDictionary *KeychainQuery(NSString *group, id itemClass) {
    return [@{(__bridge id)kSecClass:itemClass, (__bridge id)kSecAttrAccessGroup:group, (__bridge id)kSecAttrSynchronizable:(__bridge id)kSecAttrSynchronizableAny, (__bridge id)kSecUseAuthenticationContext:@"fixture-no-authentication"} mutableCopy];
}
static pid_t FakeGetPPID(void) { return parentPID; }
static OSStatus FakeCopy(CFDictionaryRef raw, CFTypeRef *result);
static OSStatus FakeDelete(CFDictionaryRef raw);
static OSStatus FakeAdd(CFDictionaryRef raw, CFTypeRef *result);
static OSStatus FakeUpdate(CFDictionaryRef raw, CFDictionaryRef values);
static SecAccessControlRef FakeDecodeACL(CFAllocatorRef allocator, CFDataRef bytes, CFErrorRef *error) {
    (void)allocator; (void)error; if ([(__bridge NSData *)bytes isEqual:[@"invalid" dataUsingEncoding:NSUTF8StringEncoding]]) return NULL;
    return (SecAccessControlRef)CFRetain(bytes);
}
static CFDataRef FakeCopyACL(SecAccessControlRef acl) { return (CFDataRef)CFRetain(acl); }
static void *FakeDlsym(void *handle, const char *symbol) {
    (void)handle; if (!strcmp(symbol,"SecAccessControlCreateFromData")) return (void *)FakeDecodeACL;
    if (!strcmp(symbol,"SecAccessControlCopyData")) return (void *)FakeCopyACL; return NULL;
}
#define SecItemCopyMatching FakeCopy
#define SecItemDelete FakeDelete
#define SecItemAdd FakeAdd
#define SecItemUpdate FakeUpdate
#define dlsym FakeDlsym
#define getppid FakeGetPPID
#import "__SOURCE__"
#undef SecItemCopyMatching
#undef SecItemDelete
#undef SecItemAdd
#undef SecItemUpdate
#undef dlsym
#undef getppid

static void RecordCall(NSString *kind, NSDictionary *query) {
    Check([query[(__bridge id)kSecAttrAccessGroup] isEqual:Group], @"credential operation escaped exact target group");
    [calls addObject:@{@"kind":kind,@"query":query}];
}
static BOOL Matches(NSDictionary *item, NSDictionary *query) {
    for (NSString *key in query) {
        if ([key isEqual:(__bridge id)kSecReturnAttributes] || [key isEqual:(__bridge id)kSecReturnData] || [key isEqual:(__bridge id)kSecMatchLimit] || [key isEqual:(__bridge id)kSecUseAuthenticationContext]) continue;
        if ([key isEqual:(__bridge id)kSecAttrSynchronizable] && query[key] == (__bridge id)kSecAttrSynchronizableAny) continue;
        id actual = item[key]; if ([key isEqual:(__bridge id)kSecAttrSynchronizable] && !actual) actual=@NO;
        if (!actual || ![actual isEqual:query[key]]) return NO;
    } return YES;
}
static void Mutated(void) { mutations++; if (loseParentAfterMutation) parentPID++; }
static OSStatus FakeCopy(CFDictionaryRef raw, CFTypeRef *result) {
    NSDictionary *query=(__bridge NSDictionary *)raw; RecordCall(@"copy", query);
    Check([query[(__bridge id)kSecReturnAttributes] boolValue] && [query[(__bridge id)kSecMatchLimit] isEqual:(__bridge id)kSecMatchLimitAll], @"export must request typed attributes and all records");
    Check(query[(__bridge id)kSecAttrSynchronizable] == (__bridge id)kSecAttrSynchronizableAny, @"export omitted synchronized records");
    if (mode == 1) return errSecSuccess;
    if (mode == 2) { *result = CFRetain((__bridge CFTypeRef)unsupportedResult); return errSecSuccess; }
    if (mode == 3) return errSecInteractionNotAllowed;
    NSMutableArray *found=[NSMutableArray new]; for (NSDictionary *item in items) if (Matches(item, query)) [found addObject:[item copy]];
    if (!found.count && mode != 4) return errSecItemNotFound;
    if ([found.firstObject[(__bridge id)kSecClass] isEqual:(__bridge id)kSecClassGenericPassword] || [found.firstObject[(__bridge id)kSecClass] isEqual:(__bridge id)kSecClassInternetPassword]) Check([query[(__bridge id)kSecReturnData] boolValue], @"password export omitted value bytes");
    *result=CFRetain((__bridge CFTypeRef)found); return errSecSuccess;
}
static OSStatus FakeDelete(CFDictionaryRef raw) {
    NSDictionary *query=(__bridge NSDictionary *)raw; RecordCall(@"delete", query);
    Check([query[(__bridge id)kSecAttrSynchronizable] isKindOfClass:NSNumber.class], @"delete must scope synchronization explicitly");
    if ([query[(__bridge id)kSecAttrSynchronizable] boolValue]) for (NSString *key in StateIdentityKeys(query)) Check(query[key] != nil, @"synchronized deletion omitted identity field");
    NSIndexSet *indexes=[items indexesOfObjectsPassingTest:^BOOL(NSDictionary *item, NSUInteger index, BOOL *stop) { (void)index;(void)stop;return Matches(item,query); }]; [items removeObjectsAtIndexes:indexes]; Mutated(); return errSecSuccess;
}
static OSStatus FakeAdd(CFDictionaryRef raw, CFTypeRef *result) {
    (void)result; NSDictionary *record=(__bridge NSDictionary *)raw; RecordCall(@"add", record);
    for (NSDictionary *item in items) if ([StateRecordIdentity(item) isEqual:StateRecordIdentity(record)]) return errSecDuplicateItem;
    [items addObject:[record mutableCopy]]; Mutated(); return errSecSuccess;
}
static OSStatus FakeUpdate(CFDictionaryRef raw, CFDictionaryRef rawValues) {
    NSDictionary *query=(__bridge NSDictionary *)raw, *values=(__bridge NSDictionary *)rawValues; RecordCall(@"update",query);
    Check([query[(__bridge id)kSecAttrSynchronizable] isEqual:@YES], @"update must target synchronized identity");
    for (NSString *key in StateIdentityKeys(query)) Check(query[key] != nil, @"synchronized update omitted identity field");
    for (NSString *key in query) Check(values[key] == nil, @"update attempted to rewrite identity fields");
    Check(!values[(__bridge id)kSecAttrAccessible] && !values[(__bridge id)kSecAttrAccessControl], @"update attempted to rewrite synchronized protection");
    for (NSMutableDictionary *item in items) if (Matches(item, query)) { [item addEntriesFromDictionary:values]; Mutated(); return errSecSuccess; }
    return errSecItemNotFound;
}
static NSData *Bytes(void) { static const unsigned char value[]={0,1,0xff,0,0x80}; return [NSData dataWithBytes:value length:sizeof(value)]; }
static NSMutableDictionary *Password(id itemClass, NSString *account, BOOL sync) {
    NSMutableDictionary *record=[@{(__bridge id)kSecClass:itemClass,(__bridge id)kSecAttrAccessGroup:Group,(__bridge id)kSecAttrAccount:account,(__bridge id)kSecAttrSynchronizable:@(sync),(__bridge id)kSecValueData:Bytes(),(__bridge id)kSecAttrAccessible:sync ? (__bridge id)kSecAttrAccessibleAfterFirstUnlock : (__bridge id)kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly} mutableCopy];
    if ([itemClass isEqual:(__bridge id)kSecClassGenericPassword]) record[(__bridge id)kSecAttrService]=@"fixture-service";
    else [record addEntriesFromDictionary:@{(__bridge id)kSecAttrSecurityDomain:@"fixture-domain",(__bridge id)kSecAttrServer:@"example.invalid",(__bridge id)kSecAttrProtocol:(__bridge id)kSecAttrProtocolHTTPS,(__bridge id)kSecAttrAuthenticationType:(__bridge id)kSecAttrAuthenticationTypeDefault,(__bridge id)kSecAttrPort:@443,(__bridge id)kSecAttrPath:@"/credential"}];
    return record;
}
static void Reset(NSArray *records) { items=[NSMutableArray new]; for (NSDictionary *record in records) [items addObject:[record mutableCopy]]; calls=[NSMutableArray new]; mutations=0;mode=0;unsupportedResult=nil;parentPID=1234;keychainParent=1234;loseParentAfterMutation=NO; }
static BOOL Reject(void (^work)(void)) { @try { work(); } @catch(NSException *exception) { (void)exception;return YES; }return NO; }
static void RejectedWithoutMutation(void (^work)(void), NSString *message) { NSUInteger before=mutations;Check(Reject(work),message);Check(mutations==before,@"rejected preflight mutated credentials"); }
static BOOL SameRecords(NSArray *a, NSArray *b) { return a.count==b.count && [[NSSet setWithArray:a] isEqual:[NSSet setWithArray:b]]; }
static NSData *Plist(id value) { return [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]; }
static id Unplist(NSData *data) { return [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:NULL]; }
static void PayloadBoundaryTests(NSArray *groups) { @autoreleasepool {
    NSMutableDictionary *record=Password((__bridge id)kSecClassGenericPassword,@"boundary",NO);
    record[(__bridge id)kSecValueData]=[NSMutableData dataWithLength:StatePayloadLimit];
    NSUInteger overhead=Plist(@[record]).length-StatePayloadLimit;
    record[(__bridge id)kSecValueData]=[NSMutableData dataWithLength:StatePayloadLimit-overhead-1];
    NSArray *records=@[record]; Check(Plist(records).length==StatePayloadLimit-1,@"fixture did not reach logical payload boundary");
    Reset(records); NSArray *captured=StateExportRecords(groups); NSData *payload=StatePayloadData(captured), *frame=StateRequestData(@{@"records":captured});
    Check(payload && frame.length>StatePayloadLimit && frame.length<=StateFrameLimit,@"valid boundary payload failed framing or did not cross former frame limit");
    NSString *encoded=[payload base64EncodedStringWithOptions:0]; NSData *output=[NSJSONSerialization dataWithJSONObject:@{@"ok":@YES,@"result":encoded} options:0 error:NULL];
    Check(encoded.length<=StateEncodedOutputLimit && output.length+1<=StateEncodedOutputLimit,@"encoded worker response exceeded bounded output allowance");
    NSArray *response=Unplist([[NSData alloc] initWithBase64EncodedString:encoded options:0]);
    NSDictionary *request=Unplist(StateRequestData(@{@"records":response})); Reset(@[]); StateRestoreRecords(request[@"records"],@[],groups);
    Check(SameRecords(StateExportRecords(groups),records),@"framed boundary credential roundtrip lost fields or bytes");
    record[(__bridge id)kSecValueData]=[NSMutableData dataWithLength:StatePayloadLimit-overhead+1];
    Check(Plist(records).length==StatePayloadLimit+1,@"oversized fixture missed logical boundary");
    Reset(records); RejectedWithoutMutation(^{StateExportRecords(groups);},@"oversized logical export accepted");
    Check(!StatePayloadData(records) && !StateRequestData(@{@"records":records}),@"oversized logical request accepted because frame had capacity");
    Reset(@[]); RejectedWithoutMutation(^{StateRestoreRecords(records,@[],groups);},@"oversized logical restore accepted");
    for(NSString *key in @[@"preferences",@"fingerprint"]) { @autoreleasepool {
        NSMutableDictionary *body=[@{@"data":[NSMutableData dataWithLength:StatePayloadLimit]} mutableCopy];
        NSUInteger padding=Plist(body).length-StatePayloadLimit;
        body[@"data"]=[NSMutableData dataWithLength:StatePayloadLimit-padding-1];
        NSData *wrapped=StateRequestData(@{key:body});
        Check(StatePayloadData(body).length==StatePayloadLimit-1 && wrapped.length>StatePayloadLimit && wrapped.length<=StateFrameLimit,@"preference/fingerprint framing disagreed with logical body bound");
        Check([Unplist(wrapped)[key] isEqual:body],@"preference/fingerprint wrapper lost logical fields");
        body[@"data"]=[NSMutableData dataWithLength:StatePayloadLimit-padding+1];
        Check(!StatePayloadData(body) && !StateRequestData(@{key:body}),@"preference/fingerprint oversized logical body accepted");
    }}
    Check(!StateRequestData(@{@"extra":[NSMutableData dataWithLength:StateFrameLimit]}),@"oversized frame accepted");
}}
int main(void) { @autoreleasepool {
    NSArray *groups=@[Group]; NSMutableDictionary *generic=Password((__bridge id)kSecClassGenericPassword,@"generic",NO), *internet=Password((__bridge id)kSecClassInternetPassword,@"internet",NO);
    generic[(__bridge id)kSecAttrGeneric]=Bytes(); generic[(__bridge id)kSecAttrIsInvisible]=@YES; generic[(__bridge id)kSecAttrCreator]=@42; generic[(__bridge id)kSecAttrType]=@77; generic[(__bridge id)kSecAttrLabel]=@"untouched-label";
    NSMutableDictionary *control=Password((__bridge id)kSecClassGenericPassword,@"control",NO);control[(__bridge id)kSecAttrAccessGroup]=Other;
    Reset(@[generic,internet,control]); NSArray *saved=StateExportRecords(groups);Check(saved.count==2 && !mutations,@"read-only binary export failed");
    Check(SameRecords(saved,@[generic,internet]),@"generic/internet fields or binary values changed");
    NSData *encoded=[NSPropertyListSerialization dataWithPropertyList:saved format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]; NSArray *decoded=[NSPropertyListSerialization propertyListWithData:encoded options:NSPropertyListImmutable format:NULL error:NULL];Check(SameRecords(saved,decoded),@"binary credential plist roundtrip failed");
    Reset(@[control]); StateRestoreRecords(decoded,@[],groups);Check(SameRecords(StateExportRecords(groups),saved) && [items containsObject:control],@"portable restore lost bytes or changed control group");
    Reset(@[]);Check(StateExportRecords(groups).count==0 && !mutations,@"not-found empty export failed");mode=4;Check(StateExportRecords(groups).count==0 && !mutations,@"typed empty success array rejected");
    mode=1;RejectedWithoutMutation(^{StateExportRecords(groups);},@"success NULL export accepted");
    mode=2;for(id value in @[@"unexpected",@42,@[@"invalid-row"]]){unsupportedResult=value;RejectedWithoutMutation(^{StateExportRecords(groups);},@"untyped export result accepted");}
    NSMutableDictionary *wrongReturnedGroup=[generic mutableCopy];wrongReturnedGroup[(__bridge id)kSecAttrAccessGroup]=Other;unsupportedResult=@[wrongReturnedGroup];RejectedWithoutMutation(^{StateExportRecords(groups);},@"query result from another group was relabeled as target");
    unsupportedResult=@[internet];RejectedWithoutMutation(^{StateExportRecords(groups);},@"query result from another class was relabeled as target");
    mode=3;RejectedWithoutMutation(^{StateExportRecords(groups);},@"permission error treated as empty");
    for(id itemClass in @[(__bridge id)kSecClassCertificate,(__bridge id)kSecClassKey,(__bridge id)kSecClassIdentity]){Reset(@[@{(__bridge id)kSecClass:itemClass,(__bridge id)kSecAttrAccessGroup:Group}]);RejectedWithoutMutation(^{StateExportRecords(groups);},@"nonportable certificate/key/identity export accepted");NSMutableDictionary *archived=[generic mutableCopy];archived[(__bridge id)kSecClass]=itemClass;RejectedWithoutMutation(^{StateRestoreRecords(@[archived],@[],groups);},@"nonportable certificate/key/identity restore accepted");}
    // Actual iOS evidence confirms NSString and NSData generic preserve both type and value.
    for(id value in @[@"",@"中文🔑",Bytes()]){NSMutableDictionary *record=[generic mutableCopy];record[(__bridge id)kSecAttrGeneric]=value;Reset(@[record,control]);NSArray *captured=StateExportRecords(groups);Check(SameRecords(captured,@[record]),@"generic export changed string/data type or bytes");NSData *encoded=[NSPropertyListSerialization dataWithPropertyList:captured format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];NSArray *roundtrip=[NSPropertyListSerialization propertyListWithData:encoded options:0 format:NULL error:NULL];NSMutableDictionary *current=[record mutableCopy];current[(__bridge id)kSecAttrGeneric]=@"live";Reset(@[current,control]);StateValidateReplacement(roundtrip,@[current],groups);StateRestoreRecords(roundtrip,@[current],groups);Check(SameRecords(StateExportRecords(groups),@[record])&&[items containsObject:control],@"generic restore changed archived string/data or other group");}
    Reset(@[]); for(NSString *group in @[Other,@"*",@"apple.system",@"VICTIM.example.app"]){NSMutableDictionary *bad=[generic mutableCopy];bad[(__bridge id)kSecAttrAccessGroup]=group;RejectedWithoutMutation(^{StateRestoreRecords(@[bad],@[],groups);},@"out-of-scope archive accepted");}
    for(NSDictionary *change in @[@{(__bridge id)kSecValueData:@"text"},@{(__bridge id)kSecAttrAccount:@1},@{(__bridge id)kSecAttrSynchronizable:@2},@{(__bridge id)kSecAttrPort:@65536},@{(__bridge id)kSecAttrPort:@(-1)},@{(__bridge id)kSecAttrPort:@1.5},@{(__bridge id)kSecAttrCreator:@(NAN)},@{(__bridge id)kSecAttrIsInvisible:@2},@{(__bridge id)kSecAttrGeneric:@1},@{(__bridge id)kSecAttrGeneric:@[@"invalid array"]},@{(__bridge id)kSecAttrGeneric:@{@"bad":@1}},@{(__bridge id)kSecAttrCreationDate:NSDate.date},@{(__bridge id)kSecValuePersistentRef:Bytes()},@{@"ArchivedACL":@"invalid"},@{@"ArchivedACL":[@"invalid" dataUsingEncoding:NSUTF8StringEncoding]}]){NSMutableDictionary *bad=[generic mutableCopy];[bad addEntriesFromDictionary:change];RejectedWithoutMutation(^{StateRestoreRecords(@[bad],@[],groups);},@"invalid/nonportable attribute accepted");}
    for(NSDictionary *change in @[@{(__bridge id)kSecAttrServer:@"wrong-class"},@{(__bridge id)kSecAttrAccessible:@"unknown-protection"}]) { NSMutableDictionary *bad=[generic mutableCopy];[bad addEntriesFromDictionary:change];RejectedWithoutMutation(^{StateRestoreRecords(@[bad],@[],groups);},@"invalid class/protection attribute accepted"); }
    NSMutableDictionary *wrongInternet=[internet mutableCopy];wrongInternet[(__bridge id)kSecAttrService]=@"generic-only";RejectedWithoutMutation(^{StateRestoreRecords(@[wrongInternet],@[],groups);},@"generic attribute accepted on internet record");
    NSMutableDictionary *missingProtection=[generic mutableCopy];[missingProtection removeObjectForKey:(__bridge id)kSecAttrAccessible];RejectedWithoutMutation(^{StateRestoreRecords(@[missingProtection],@[],groups);},@"missing credential protection accepted");
    RejectedWithoutMutation(^{StateRestoreRecords(@[generic,generic],@[],groups);},@"duplicate identity accepted");
    NSMutableDictionary *minimal=[generic mutableCopy];[minimal removeObjectForKey:(__bridge id)kSecAttrAccount];NSMutableDictionary *empty=[minimal mutableCopy];empty[(__bridge id)kSecAttrAccount]=@"";RejectedWithoutMutation(^{StateRestoreRecords(@[minimal,empty],@[],groups);},@"missing/empty duplicate identity accepted");
    NSMutableDictionary *synchronized=Password((__bridge id)kSecClassGenericPassword,@"same-account",YES), *local=Password((__bridge id)kSecClassGenericPassword,@"same-account",NO);Reset(@[synchronized,local,control]);Check(![StateRecordIdentity(synchronized) isEqual:StateRecordIdentity(local)],@"sync flag omitted from identity");
    NSMutableDictionary *updated=[synchronized mutableCopy];updated[(__bridge id)kSecValueData]=[@"new-secret" dataUsingEncoding:NSUTF8StringEncoding];StateRestoreRecords(@[updated,local],@[synchronized,local],groups);Check(SameRecords(StateExportRecords(groups),@[updated,local]) && [items containsObject:control],@"sync update/local replacement failed");Check([[calls valueForKey:@"kind"] containsObject:@"update"],@"synchronized identity was not updated in place");
    Reset(@[synchronized,local,control]);StateRestoreRecords(@[local],@[synchronized,local],groups);Check(SameRecords(StateExportRecords(groups),@[local]) && [items containsObject:control],@"absent synchronized identity not deleted selectively");
    NSMutableDictionary *syncInet=Password((__bridge id)kSecClassInternetPassword,@"inet-sync",YES);Reset(@[syncInet,control]);NSMutableDictionary *newInet=[syncInet mutableCopy];newInet[(__bridge id)kSecValueData]=[@"inet-new" dataUsingEncoding:NSUTF8StringEncoding];StateRestoreRecords(@[newInet],@[syncInet],groups);Check(SameRecords(StateExportRecords(groups),@[newInet]),@"internet synchronized identity update failed");
    for(id protection in @[(__bridge id)kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,(__bridge id)kSecAttrAccessibleWhenUnlockedThisDeviceOnly,(__bridge id)kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly]){NSMutableDictionary *bad=[synchronized mutableCopy];bad[(__bridge id)kSecAttrAccessible]=protection;RejectedWithoutMutation(^{StateRestoreRecords(@[bad],@[],groups);},@"device-only synchronized protection accepted");}
    Reset(@[synchronized,control]);NSMutableDictionary *differentProtection=[synchronized mutableCopy];differentProtection[(__bridge id)kSecAttrAccessible]=(__bridge id)kSecAttrAccessibleWhenUnlocked;RejectedWithoutMutation(^{StateRestoreRecords(@[differentProtection],@[synchronized],groups);},@"sync protection changed after destructive writes");
    NSMutableDictionary *labeled=[synchronized mutableCopy];labeled[(__bridge id)kSecAttrLabel]=@"label";Reset(@[labeled,control]);RejectedWithoutMutation(^{StateRestoreRecords(@[synchronized],@[labeled],groups);},@"sync attribute removal accepted before replacement");
    NSMutableDictionary *acl=[generic mutableCopy];[acl removeObjectForKey:(__bridge id)kSecAttrAccessible];acl[@"ArchivedACL"]=Bytes();Reset(@[control]);StateRestoreRecords(@[acl],@[],groups);Check(SameRecords(StateExportRecords(groups),@[acl]),@"encoded ACL bridge roundtrip failed");
    Reset(@[generic,control]);parentPID++;RejectedWithoutMutation(^{StateRestoreRecords(@[generic],@[generic],groups);},@"orphan worker mutated credentials");
    Reset(@[generic,control]);loseParentAfterMutation=YES;Check(Reject(^{StateRestoreRecords(@[generic],@[generic],groups);}) && mutations==1,@"parent loss was not rechecked before next mutation");Check([items containsObject:control],@"parent loss changed other group");
    PayloadBoundaryTests(groups);
    puts("backup keychain: passed (Security calls stubbed; no user Keychain access)");
}return 0;}
'''

with tempfile.TemporaryDirectory(prefix="shadow-backup-keychain-") as temp:
    temp = Path(temp)
    source = temp / "main.m"
    source.write_text(HARNESS.replace("__SOURCE__", str(SOURCE)))
    binary = temp / "check"
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation", "-framework", "Security", str(source), "-o", str(binary)], check=True)
    imports = subprocess.check_output(["nm", "-u", str(binary)], text=True)
    for symbol in ("_SecItemCopyMatching", "_SecItemDelete", "_SecItemAdd", "_SecItemUpdate"):
        assert symbol not in imports, f"real user Keychain API linked: {symbol}"
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
    subprocess.run([str(binary)], check=True, env=environment)
