#import "../AppState/State.h"
#import <Shadow/Settings.h>
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintState.h>
#import <Shadow/FingerprintConfiguration.h>
#include <math.h>
#import "StateKeychain.inc"
#import "StatePreferences.inc"

static NSUInteger const StatePayloadLimit = 16 * 1024 * 1024;
static NSString *const StateStorage = @"/private/var/mobile/Library/ShadowBackups";
static pid_t stateInitiatingParent;
static void StateParent(void) { Require(stateInitiatingParent > 1 && getppid() == stateInitiatingParent, @"The application state caller exited; the operation was stopped"); }
static NSData *StateEncode(id value) {
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    Require(data && data.length <= StatePayloadLimit, @"Application state response exceeds its size limit"); return data;
}
static id StateDecode(NSData *data) {
    Require(data && data.length <= StatePayloadLimit, @"Application state request exceeds its size limit");
    id result = [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:NULL];
    Require(result != nil, @"Invalid application state request"); return result;
}
static void StateOutput(NSDictionary *value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:NULL];
    Require(data != nil, @"Cannot encode application state progress");
    Require(fwrite(data.bytes, 1, data.length, stdout) == data.length && fputc('\n', stdout) != EOF && !fflush(stdout), @"Application state output channel closed");
}
static NSDictionary *StateMobileFingerprint(NSString *mode, NSDictionary *target, NSDictionary *request) {
    Require(getuid() == 501 && geteuid() == 501, @"Fingerprint preferences require the mobile user");
    NSString *identifier = target[@"bundleID"]; ShadowSettings *settings = ShadowSettings.sharedInstance; NSUserDefaults *defaults = settings.userDefaults;
    Require([defaults synchronize], @"Cannot read current fingerprint preferences"); NSDictionary *app = [defaults dictionaryForKey:identifier];
    Require(SHDWFingerprintApplicationIsRegistered(app), @"The selected application is not registered in Shadow");
    if ([mode isEqual:@"state-registration"]) return @{@"registered":@YES};
    if ([mode isEqual:@"state-fingerprint-identity"]) {
        id data = app[@"Fingerprint_Data"]; id value = [data isKindOfClass:NSDictionary.class] ? data[@"VendorIdentifier"] : nil;
        return @{@"idfv":[value isKindOfClass:NSString.class] ? value : @""};
    }
    if ([mode isEqual:@"state-fingerprint-capture"]) {
        NSDictionary *data = app[@"Fingerprint_Data"], *configuration = app[@"Fingerprint_Config"];
        Require([data isKindOfClass:NSDictionary.class] && [configuration isKindOfClass:NSDictionary.class] &&
            [NSPropertyListSerialization propertyList:@[data, configuration] isValidForFormat:NSPropertyListBinaryFormat_v1_0], @"Fingerprint preferences cannot be archived");
        NSMutableDictionary *result = [@{@"data":data, @"configuration":configuration, @"locked":@(SHDWFingerprintApplicationLocked(app))} mutableCopy];
        NSString *digest = [SHDWFingerprintStore deviceFingerprintForData:data]; if (digest) result[@"digest"] = digest;
        return result;
    }
    NSDictionary *fingerprint = request[@"fingerprint"];
    Require([fingerprint isKindOfClass:NSDictionary.class] && [fingerprint[@"data"] isKindOfClass:NSDictionary.class] &&
        [fingerprint[@"configuration"] isKindOfClass:NSDictionary.class] &&
        [NSPropertyListSerialization propertyList:@[fingerprint[@"data"], fingerprint[@"configuration"]] isValidForFormat:NSPropertyListBinaryFormat_v1_0], @"Archived fingerprint preferences cannot be imported");
    if ([mode isEqual:@"state-fingerprint-validate"]) return @{@"validated":@YES};
    Require([mode isEqual:@"state-fingerprint-restore"] && getppid() == keychainParent && !Running(target[@"bundlePath"]).count, @"The application must remain stopped before restoring its fingerprint");
    NSMutableDictionary *updated = [app mutableCopy]; updated[@"Fingerprint_Data"] = fingerprint[@"data"]; updated[@"Fingerprint_Config"] = fingerprint[@"configuration"]; updated[@"Fingerprint_Locked"] = @YES;
    [defaults setObject:updated forKey:identifier]; Require([defaults synchronize], @"Cannot persist the restored fingerprint");
    Require([[defaults dictionaryForKey:identifier] isEqual:updated], @"Restored fingerprint preferences failed readback"); return @{@"restored":@YES, @"locked":@YES};
}
static NSDictionary *StateWorker(NSString *mode, NSDictionary *target, NSString *directory) {
    Require([@[@"state-export", @"state-validate", @"state-restore", @"state-registration", @"state-fingerprint-capture", @"state-fingerprint-identity", @"state-fingerprint-validate", @"state-fingerprint-restore", @"state-preferences-capture", @"state-preferences-validate", @"state-preferences-restore"] containsObject:mode], @"Unknown scoped application state worker");
    NSDictionary *request = @{}; NSString *path = [directory stringByAppendingPathComponent:@"request.plist"]; struct stat st;
    if (!lstat(path.fileSystemRepresentation, &st)) {
        Require(S_ISREG(st.st_mode) && st.st_uid == 0 && st.st_nlink == 1 && (st.st_mode & 0777) == 0600 && st.st_size > 0 && st.st_size <= (off_t)StatePayloadLimit, @"Unsafe scoped application state request");
        id value = StateDecode([NSData dataWithContentsOfFile:path]); Require([value isKindOfClass:NSDictionary.class], @"Invalid scoped worker request"); request = value;
    } else Require(errno == ENOENT, @"Cannot inspect scoped worker request");
    Require(!setgroups(0, NULL) && !setgid(501) && !setuid(501) && getuid() == 501 && geteuid() == 501, @"Cannot enter the mobile application state context");
    id value;
    if ([mode hasPrefix:@"state-fingerprint-"] || [mode isEqual:@"state-registration"]) value = StateMobileFingerprint(mode, target, request);
    else if ([mode hasPrefix:@"state-preferences-"]) {
        Require(getppid() == keychainParent && !Running(target[@"bundlePath"]).count, @"The application must remain stopped while preferences are accessed");
        if ([mode isEqual:@"state-preferences-capture"]) value = StateCapturePreferences(target);
        else { StateValidatePreferences(request[@"preferences"], target); if ([mode isEqual:@"state-preferences-restore"]) StateRestorePreferences(request[@"preferences"], target); value = @{@"validated":@YES}; }
    } else {
        Require(getppid() == keychainParent && !Running(target[@"bundlePath"]).count, @"The application restarted before its credentials could be accessed");
        NSArray *groups = ValidatedKeychainScope(target), *records = request[@"records"];
        if ([mode isEqual:@"state-export"]) value = StateExportRecords(groups);
        else {
            StateValidateRecords(records, groups); NSArray *current = StateExportRecords(groups); StateValidateReplacement(records, current, groups);
            if ([mode isEqual:@"state-restore"]) StateRestoreRecords(records, current, groups);
            value = @{@"validated":@YES, @"restored":@([mode isEqual:@"state-restore"])};
        }
    }
    return @{@"ok":@YES, @"result":[StateEncode(value) base64EncodedStringWithOptions:0]};
}
static id StateWorkerValue(NSDictionary *target, NSString *mode, NSDictionary *request) {
    NSDictionary *response = ScopedWorker(target, mode, request); NSString *encoded = response[@"result"];
    Require([encoded isKindOfClass:NSString.class] && encoded.length <= 24 * 1024 * 1024, @"Scoped application state response is invalid");
    return StateDecode([[NSData alloc] initWithBase64EncodedString:encoded options:0]);
}
static BOOL StateFailure(NSError **error, NSException *exception) {
    if (error) *error = [NSError errorWithDomain:SHDWAppStateErrorDomain code:40 userInfo:@{NSLocalizedDescriptionKey:exception.reason ?: @"Application state operation failed"}]; return NO;
}
@interface NativeStateBackend : NSObject <SHDWAppStateBackend>
@property(nonatomic, strong) NSMutableDictionary *queries;
@end
@implementation NativeStateBackend
- (instancetype)init { if ((self = [super init])) _queries = [NSMutableDictionary new]; return self; }
- (NSDictionary *)resolveBundle:(NSString *)bundleID error:(NSError **)error {
    @try {
        NSDictionary *scope = Resolve(bundleID), *authority = scope[@"target"];
        Require([authority[@"ownershipComplete"] boolValue] && ![authority[@"preservedSharedGroups"] count] && ![authority[@"sharedKeychainGroups"] count], @"Shared or unverifiable application resources cannot be backed up safely"); ValidatedKeychainScope(authority);
        NSDictionary *info = ReadPlist([authority[@"bundlePath"] stringByAppendingPathComponent:@"Info.plist"]); NSString *version = info[@"CFBundleShortVersionString"], *build = info[@"CFBundleVersion"];
        Require([version isKindOfClass:NSString.class] && version.length && [build isKindOfClass:NSString.class] && build.length, @"The installed application's version is unavailable");
        NSMutableDictionary *containers = [NSMutableDictionary new];
        for (NSDictionary *container in authority[@"containers"]) { NSString *identifier = container[@"identifier"], *key = [identifier isEqual:bundleID] ? @"data" : [@"scope-" stringByAppendingString:identifier]; Require(!containers[key], @"Duplicate application container identity"); containers[key] = container[@"path"]; }
        if (!self.queries[bundleID]) self.queries[bundleID] = PreferenceQueries(authority);
        return @{@"bundleID":bundleID, @"token":Hash(@{ @"authority":scope[@"token"], @"version":version, @"build":build }), @"version":version, @"build":build, @"containers":containers, @"keychainGroups":authority[@"keychainGroups"], @"authority":authority};
    } @catch (NSException *exception) { StateFailure(error, exception); return nil; }
}
- (BOOL)assertStopped:(NSDictionary *)target error:(NSError **)error {
    @try {
        NSDictionary *authority = target[@"authority"]; Require(!Running(authority[@"bundlePath"]).count, @"The application or an extension restarted during the operation");
        for (NSDictionary *container in authority[@"containers"]) {
            struct stat st; NSString *path = container[@"path"];
            Require(!lstat(path.fileSystemRepresentation, &st) && S_ISDIR(st.st_mode) && (uint64_t)st.st_dev == [container[@"device"] unsignedLongLongValue] && st.st_ino == [container[@"inode"] unsignedLongLongValue] && [Canonical(path) isEqual:path], @"An application container changed during the operation");
        }
        for (NSDictionary *executable in authority[@"executables"]) {
            struct stat st; Require(!lstat([executable[@"path"] fileSystemRepresentation], &st) && S_ISREG(st.st_mode) && st.st_ino == [executable[@"inode"] unsignedLongLongValue] && st.st_size == [executable[@"size"] longLongValue] && st.st_mtime == [executable[@"modified"] longLongValue], @"The installed application changed during the operation");
        }
        return YES;
    } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (BOOL)stopTarget:(NSDictionary *)target error:(NSError **)error {
    @try { StateParent(); Stop(target[@"authority"][@"bundlePath"]); return [self assertStopped:target error:error]; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (BOOL)flushPreferencesForTarget:(NSDictionary *)target error:(NSError **)error {
    @try {
        StateParent();
        Require([self assertStopped:target error:error], @"The application must remain stopped while preferences are synchronized");
        NSArray *before = self.queries[target[@"bundleID"]] ?: @[]; NSMutableOrderedSet *queries = [NSMutableOrderedSet orderedSetWithArray:before]; [queries addObjectsFromArray:PreferenceQueries(target[@"authority"])];
        self.queries[target[@"bundleID"]] = queries.array; PreferenceCache(queries.array, NO, YES); return [self assertStopped:target error:error];
    } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (NSString *)currentVendorIdentifierForTarget:(NSDictionary *)target error:(NSError **)error {
    @try { id value = StateWorkerValue(target[@"authority"], @"state-fingerprint-identity", nil)[@"idfv"]; Require([value isKindOfClass:NSString.class], @"Cannot read the current application IDFV."); return value; }
    @catch (NSException *exception) { StateFailure(error, exception); return nil; }
}
- (NSDictionary *)capturePreferencesForTarget:(NSDictionary *)target error:(NSError **)error {
    @try { id result = StateWorkerValue(target[@"authority"], @"state-preferences-capture", nil); Require([result isKindOfClass:NSDictionary.class], @"Invalid captured application preferences"); return result; } @catch (NSException *exception) { StateFailure(error, exception); return nil; }
}
- (BOOL)validatePreferences:(NSDictionary *)preferences target:(NSDictionary *)target error:(NSError **)error {
    @try { StateWorkerValue(target[@"authority"], @"state-preferences-validate", @{@"preferences":preferences}); return YES; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (BOOL)restorePreferences:(NSDictionary *)preferences target:(NSDictionary *)target error:(NSError **)error {
    @try { StateParent(); Require([self assertStopped:target error:error], @"The application must remain stopped before preferences are restored"); mutated = YES; StateWorkerValue(target[@"authority"], @"state-preferences-restore", @{@"preferences":preferences}); return YES; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (NSArray *)captureKeychainForTarget:(NSDictionary *)target error:(NSError **)error {
    @try { Require([self assertStopped:target error:error], @"The application must remain stopped while credentials are captured"); id records = StateWorkerValue(target[@"authority"], @"state-export", nil); Require([records isKindOfClass:NSArray.class], @"Invalid captured credentials"); return records; } @catch (NSException *exception) { StateFailure(error, exception); return nil; }
}
- (BOOL)validateKeychain:(NSArray *)records target:(NSDictionary *)target error:(NSError **)error {
    @try { Require([self assertStopped:target error:error], @"The application must remain stopped while credentials are checked"); StateWorkerValue(target[@"authority"], @"state-validate", @{@"records":records}); return YES; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (BOOL)restoreKeychain:(NSArray *)records target:(NSDictionary *)target error:(NSError **)error {
    @try { StateParent(); Require([self assertStopped:target error:error], @"The application must remain stopped before credentials are restored"); mutated = YES; StateWorkerValue(target[@"authority"], @"state-restore", @{@"records":records}); return YES; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (NSDictionary *)captureFingerprintForTarget:(NSDictionary *)target error:(NSError **)error {
    @try { id fingerprint = StateWorkerValue(target[@"authority"], @"state-fingerprint-capture", nil); Require([fingerprint isKindOfClass:NSDictionary.class], @"Invalid captured fingerprint"); return fingerprint; } @catch (NSException *exception) { StateFailure(error, exception); return nil; }
}
- (BOOL)validateFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error {
    @try { StateWorkerValue(target[@"authority"], @"state-fingerprint-validate", @{@"fingerprint":fingerprint}); return YES; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
- (BOOL)restoreFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error {
    @try { StateParent(); Require([self assertStopped:target error:error], @"The application must remain stopped before its fingerprint is restored"); mutated = YES; StateWorkerValue(target[@"authority"], @"state-fingerprint-restore", @{@"fingerprint":fingerprint}); return YES; } @catch (NSException *exception) { return StateFailure(error, exception); }
}
@end
static NSArray *StateConciseCatalog(NSArray *catalog) {
    NSMutableArray *result = [NSMutableArray new];
    for (NSDictionary *manifest in catalog) {
        NSMutableDictionary *entry = [NSMutableDictionary new];
        for (NSString *key in @[@"idfv", @"title", @"note", @"date", @"version", @"build", @"digest", @"restorePending", @"recoverySource"]) if (manifest[key]) entry[key] = manifest[key];
        NSNumber *dataSize = manifest[@"archiveInfo"][@"archiveSize"], *stateSize = manifest[@"stateArchiveInfo"][@"archiveSize"] ?: @0;
        Require([dataSize isKindOfClass:NSNumber.class] && [stateSize isKindOfClass:NSNumber.class] && [dataSize isEqual:@(dataSize.unsignedLongLongValue)] && [stateSize isEqual:@(stateSize.unsignedLongLongValue)] && dataSize.unsignedLongLongValue <= UINT64_MAX - stateSize.unsignedLongLongValue, @"Invalid backup archive size");
        entry[@"size"] = @(dataSize.unsignedLongLongValue + stateSize.unsignedLongLongValue); [result addObject:entry];
    }
    return result;
}
static NSDictionary *StateCommand(int argc, const char *argv[]) {
    stateInitiatingParent = getppid(); StateParent();
    Require(argc == 4 || argc == 5, @"Expected an application state action and an optional encoded request");
    NSString *identifier = [NSString stringWithUTF8String:argv[2]], *action = [NSString stringWithUTF8String:argv[3]];
    Require(BundleIdentifier(identifier) && [@[@"catalog", @"backup", @"restore", @"edit", @"delete", @"recheck"] containsObject:action], @"Invalid application state action");
    NSDictionary *request = @{};
    if (argc == 5) { NSString *encoded = [NSString stringWithUTF8String:argv[4]]; Require(encoded.length <= 256 * 1024, @"Application state action request is too large"); id value = StateDecode([[NSData alloc] initWithBase64EncodedString:encoded options:0]); Require([value isKindOfClass:NSDictionary.class], @"Invalid application state action request"); request = value; }
    NSArray *allowed = [action isEqual:@"catalog"] ? @[] : [action isEqual:@"backup"] ? @[@"metadata"] : [action isEqual:@"restore"] ? @[@"idfv", @"saveCurrent"] : [action isEqual:@"edit"] ? @[@"idfv", @"metadata"] : @[@"idfv"];
    for (id key in request) Require([allowed containsObject:key], @"Unknown application state action option");
    if (![action isEqual:@"catalog"] && ![action isEqual:@"backup"]) Require([request[@"idfv"] isKindOfClass:NSString.class], @"A saved fingerprint identifier is required");
    if (request[@"saveCurrent"]) Require([request[@"saveCurrent"] isKindOfClass:NSNumber.class] && [@[@NO, @YES] containsObject:request[@"saveCurrent"]], @"Invalid save-current option");
    if (request[@"metadata"]) { Require([request[@"metadata"] isKindOfClass:NSDictionary.class], @"Invalid backup metadata"); for (id key in request[@"metadata"]) Require([@[@"title", @"note"] containsObject:key] && [request[@"metadata"][key] isKindOfClass:NSString.class], @"Invalid backup metadata field"); }
    Require(geteuid() == 0, @"Cannot enter the private backup storage context");
    BOOL readOnly = [@[@"catalog", @"recheck"] containsObject:action];
    int lock = SessionLockForAccess(identifier, !readOnly);
    @try {
        Require([Canonical(StateStorage.stringByDeletingLastPathComponent) isEqual:StateStorage.stringByDeletingLastPathComponent], @"Backup storage parent is not canonical"); NativeStateBackend *backend = [NativeStateBackend new]; NSError *error = nil;
        NSDictionary *target = [backend resolveBundle:identifier error:&error]; Require(target != nil, error.localizedDescription ?: @"Cannot resolve backup target");
        StateWorkerValue(target[@"authority"], @"state-registration", nil);
        SHDWAppStateStore *store = [[SHDWAppStateStore alloc] initWithRoot:StateStorage ownerUID:501 ownerGID:501 backend:backend error:&error]; Require(store != nil, error.localizedDescription ?: @"Cannot open backup storage");
        __block double last = 0; __block NSString *lastPhase = nil, *lastStage = nil;
        store.progressHandler = ^(NSDictionary *event) {
            StateParent();
            double now = MonotonicSeconds(); NSString *phase = event[@"phase"] ?: @"", *stage = event[@"stage"] ?: @"";
            if ([phase isEqual:lastPhase] && [stage isEqual:lastStage] && now - last < 0.1) return;
            last = now; lastPhase = phase; lastStage = stage; NSMutableDictionary *progress = [NSMutableDictionary new];
            for (NSString *key in @[@"phase", @"stage", @"bytes", @"entries"]) if (event[key]) progress[key] = event[key];
            StateOutput(@{@"event":@"progress", @"progress":progress});
        };
        id result = nil;
        if ([action isEqual:@"catalog"]) { NSArray *catalog = [store catalogBundle:identifier error:&error]; if (catalog) result = StateConciseCatalog(catalog); }
        else if ([action isEqual:@"backup"]) { NSDictionary *manifest = [store backupBundle:identifier metadata:request[@"metadata"] error:&error]; if (manifest) result = StateConciseCatalog(@[manifest]).firstObject; }
        else if ([action isEqual:@"restore"]) result = [store restoreBundle:identifier idfv:request[@"idfv"] saveCurrent:[request[@"saveCurrent"] boolValue] error:&error];
        else if ([action isEqual:@"edit"]) { if ([store editBundle:identifier idfv:request[@"idfv"] metadata:request[@"metadata"] error:&error]) result = @{@"edited":@YES}; }
        else if ([action isEqual:@"delete"]) { if ([store deleteBundle:identifier idfv:request[@"idfv"] error:&error]) result = @{@"deleted":@YES}; }
        else if ([store recheckBundle:identifier idfv:request[@"idfv"] error:&error]) result = @{@"verified":@YES};
        if (!result) return @{@"ok":@NO, @"error":error.localizedDescription ?: @"Application state operation failed", @"partial":@([error.userInfo[@"stateMayBePartial"] boolValue]), @"stateMayBePartial":@([error.userInfo[@"stateMayBePartial"] boolValue])};
        return @{@"ok":@YES, @"result":[StateEncode(result) base64EncodedStringWithOptions:0]};
    } @finally { close(lock); }
}
