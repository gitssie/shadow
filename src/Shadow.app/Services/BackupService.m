#import "BackupService.h"
#import "OperationCoordinator.h"
#import "Language.h"
#import "OwnershipDiagnostics.h"
#import <Shadow/JBPath.h>
#import "../../../sdk/AppState/SHDWAppStateClient.h"

static NSError *BackupError(NSInteger code, NSString *message, BOOL partial) {
    return [NSError errorWithDomain:@"me.jjolano.shadow.backup" code:code userInfo:@{NSLocalizedDescriptionKey:SHDWLocalizedText(message), @"stateMayBePartial":@(partial)}];
}
@interface SHDWBackupService ()
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
- (void)performAction:(NSString *)action request:(NSDictionary *)request progress:(SHDWBackupProgress)progress completion:(SHDWBackupCompletion)completion {
    BOOL readOnly = [@[@"catalog", @"recheck"] containsObject:action]; NSError *failure = nil;
    NSSet *allowed = [NSSet setWithArray:@[@"catalog", @"backup", @"restore", @"edit", @"delete", @"recheck"]];
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
