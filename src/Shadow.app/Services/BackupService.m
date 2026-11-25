#import "BackupService.h"
#import "OperationCoordinator.h"
#import "Language.h"
#import "OwnershipDiagnostics.h"
#import <Shadow/JBPath.h>
#import "../../../sdk/AppState/SHDWAppStateClient.h"

static NSError *BackupError(NSInteger code, NSString *message, BOOL partial) {
    return [NSError errorWithDomain:@"me.jjolano.shadow.backup" code:code userInfo:@{NSLocalizedDescriptionKey:SHDWLocalizedText(message), @"stateMayBePartial":@(partial)}];
}
static BOOL ValidCurrentIDFV(id value) {
    return [value isKindOfClass:NSString.class] && (![value length] || [[NSUUID alloc] initWithUUIDString:value] != nil);
}
@interface SHDWBackupService ()
- (void)queryCatalog:(NSDictionary *)query completion:(void (^)(NSDictionary * _Nullable page, NSError * _Nullable error))completion;
@property(atomic, readwrite) BOOL running;
@property(nonatomic, copy) NSString *bundleIdentifier;
- (NSString *)helperPath;
- (SHDWAppStateClient *)appStateClient;
- (NSTimeInterval)operationTimeout;
@end
@implementation SHDWBackupService
- (instancetype)initWithBundleIdentifier:(NSString *)bundleIdentifier {
    if ((self = [super init])) _bundleIdentifier = [bundleIdentifier copy];
    return self;
}
- (NSString *)helperPath { return JBPath(@"/usr/libexec/shadow-cleaner"); }
- (NSTimeInterval)operationTimeout { return 30 * 60; }
- (SHDWAppStateClient *)appStateClient {
    SHDWAppStateClient *client = [[SHDWAppStateClient alloc] initWithHelperPath:[self helperPath]];
    client.timeout = [self operationTimeout]; return client;
}
- (id)invokeAction:(NSString *)action request:(NSDictionary *)request progress:(SHDWBackupProgress)progress error:(NSError **)error {
    SHDWAppStateClient *client = [self appStateClient];
    id result = [client invokeAction:action bundleIdentifier:self.bundleIdentifier request:request progress:^(NSDictionary *event) {
        if (progress) dispatch_sync(dispatch_get_main_queue(), ^{ progress(event); });
    } error:error];
    if (error && *error) {
        NSMutableDictionary *info = [(*error).userInfo mutableCopy];
        info[NSLocalizedDescriptionKey] = SHDWOwnershipErrorDescription(SHDWLocalizedText((*error).localizedDescription), info[@"helperDetails"] ?: @{});
        *error = [NSError errorWithDomain:(*error).domain code:(*error).code userInfo:info];
    }
    return result;
}
- (void)loadCatalog:(void (^)(NSArray *, NSError *))completion {
    [self performAction:@"catalog" request:@{} progress:nil completion:^(id result, NSError *error) {
        if (result && ![result isKindOfClass:NSArray.class]) { error = BackupError(6, @"The backup helper returned an invalid result.", NO); result = nil; }
        completion(result, error);
    }];
}
- (void)loadCatalogWithIdentity:(void (^)(NSDictionary *, NSError *))completion {
    [self performAction:@"catalog" request:@{@"includeCurrentIDFV":@YES} progress:nil completion:^(id result, NSError *error) {
        if (result && (![result isKindOfClass:NSDictionary.class] || ![result[@"items"] isKindOfClass:NSArray.class] ||
                       !ValidCurrentIDFV(result[@"currentIDFV"]))) {
            error = BackupError(6, @"The backup helper returned an invalid result.", NO);
            result = nil;
        }
        completion(result, error);
    }];
}
- (void)loadCatalogForSearch:(NSString *)search region:(NSString *)region offset:(NSUInteger)offset refresh:(BOOL)refresh ascending:(BOOL)ascending
                  completion:(void (^)(NSDictionary *, NSError *))completion {
    NSMutableDictionary *query = [SHDWAppStateCatalogQuery(search, region, offset, SHDWAppStateCatalogPageSize, refresh) mutableCopy];
    query[@"dateOrder"] = ascending ? @"asc" : @"desc";
    [self queryCatalog:query completion:completion];
}
- (void)queryCatalog:(NSDictionary *)query completion:(void (^)(NSDictionary *, NSError *))completion {
    [self performAction:@"queryCatalog" request:query progress:nil completion:^(id result, NSError *error) {
        BOOL valid = [result isKindOfClass:NSDictionary.class] && [result[@"items"] isKindOfClass:NSArray.class] &&
            [result[@"currentSnapshot"] isKindOfClass:NSDictionary.class] && [result[@"restorePending"] isKindOfClass:NSNumber.class] &&
            [result[@"total"] isKindOfClass:NSNumber.class] && [result[@"nextOffset"] isKindOfClass:NSNumber.class] && [result[@"hasMore"] isKindOfClass:NSNumber.class];
        if (valid) {
            NSDictionary *snapshot = result[@"currentSnapshot"];
            valid = ValidCurrentIDFV(result[@"currentIDFV"]) &&
                (!snapshot.count || [snapshot[@"idfv"] isEqual:result[@"currentIDFV"]]);
        }
        if (result && !valid) { error = BackupError(6, @"The backup helper returned an invalid result.", NO); result = nil; }
        completion(result, error);
    }];
}
- (void)setDeleteLocked:(BOOL)locked forIDFV:(NSString *)idfv completion:(SHDWBackupCompletion)completion {
    [self performAction:@"setDeleteLocked" request:@{@"idfv":idfv, @"deleteLocked":locked ? @YES : @NO} progress:nil completion:^(id result, NSError *error) {
        if (result && (![result isKindOfClass:NSDictionary.class] || ![result[@"idfv"] isEqual:idfv] || ![result[@"deleteLocked"] isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)result[@"deleteLocked"]) != CFBooleanGetTypeID())) {
            result = nil; error = BackupError(6, @"The backup helper returned an invalid result.", NO);
        }
        completion(result, error);
    }];
}
- (void)performAction:(NSString *)action request:(NSDictionary *)request progress:(SHDWBackupProgress)progress completion:(SHDWBackupCompletion)completion {
    BOOL readOnly = [@[@"catalog", @"queryCatalog", @"recheck"] containsObject:action]; NSError *failure = nil;
    NSSet *allowed = [NSSet setWithArray:@[@"catalog", @"queryCatalog", @"backup", @"restore", @"edit", @"setDeleteLocked", @"delete", @"recheck"]];
    if (![allowed containsObject:action] || !self.bundleIdentifier.length || ![request isKindOfClass:NSDictionary.class]) failure = BackupError(2, @"Invalid backup request.", NO);
    @synchronized(self) {
        if (!failure && self.running) failure = BackupError(7, @"An operation is already running.", NO);
        if (!failure && !readOnly && ![SHDWOperationCoordinator beginOperation:&failure]) {}
        if (!failure) self.running = YES;
    }
    if (failure) { dispatch_async(dispatch_get_main_queue(), ^{ completion(nil, failure); }); return; }
    NSDictionary *copied = [request copy]; NSString *operation = [action copy];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil; id result = nil;
        @try { result = [self invokeAction:operation request:copied progress:progress error:&error]; }
        @catch (NSException *exception) { error = BackupError(8, @"Unable to complete backup operation.", [operation isEqual:@"restore"]); }
        dispatch_async(dispatch_get_main_queue(), ^{
            self.running = NO; if (!readOnly) [SHDWOperationCoordinator endOperation];
            completion(result, error);
        });
    });
}
@end
