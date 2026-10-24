#import "CleanupService.h"
#import "Language.h"
#import "OperationCoordinator.h"
#import <Shadow/Fingerprint.h>
#import <Shadow/JBPath.h>
#include <spawn.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <poll.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>

static BOOL SHDWCleanupActive;
static NSArray<NSString *> *SHDWCleanupOrder(void) {
    return @[@"files", @"preferences", @"web", @"keychain", @"receipts", @"fingerprint"];
}
static NSError *SHDWCleanupError(NSInteger code, NSString *message, NSString *step, BOOL partial) {
    NSMutableDictionary *info = [@{NSLocalizedDescriptionKey: SHDWLocalizedText(message), @"stateMayBePartial": @(partial)} mutableCopy];
    if (step) info[@"step"] = step;
    return [NSError errorWithDomain:@"me.jjolano.shadow.cleanup" code:code userInfo:info];
}
@interface SHDWCleanupService ()
@property(atomic, readwrite) BOOL running;
@property(nonatomic, copy) NSString *bundleIdentifier;
- (nullable NSDictionary *)invokeHelper:(NSArray<NSString *> *)arguments error:(NSError **)error;
@end

@implementation SHDWCleanupService
- (instancetype)initWithBundleIdentifier:(NSString *)bundleIdentifier {
    if ((self = [super init])) _bundleIdentifier = [bundleIdentifier copy];
    return self;
}
- (NSDictionary *)invokeHelper:(NSArray<NSString *> *)arguments error:(NSError **)error {
    NSString *path = JBPath(@"/usr/libexec/shadow-cleaner");
    struct stat metadata;
    if (!path || lstat(path.fileSystemRepresentation, &metadata) || !S_ISREG(metadata.st_mode) ||
        metadata.st_uid != 0 || (metadata.st_mode & 022) || !(metadata.st_mode & S_ISUID)) {
        if (error) *error = SHDWCleanupError(10, @"The cleanup helper is unavailable. Reinstall Shadow.", nil, NO);
        return nil;
    }
    int pipefd[2];
    if (pipe(pipefd)) {
        if (error) *error = SHDWCleanupError(11, @"Unable to start cleanup.", nil, NO);
        return nil;
    }
    fcntl(pipefd[0], F_SETFD, FD_CLOEXEC); fcntl(pipefd[1], F_SETFD, FD_CLOEXEC);
    NSMutableArray<NSString *> *strings = [NSMutableArray arrayWithObject:path];
    [strings addObjectsFromArray:arguments];
    char **argv = calloc(strings.count + 1, sizeof(char *));
    if (!argv) { close(pipefd[0]); close(pipefd[1]); if (error) *error = SHDWCleanupError(11, @"Unable to start cleanup.", nil, NO); return nil; }
    for (NSUInteger i = 0; i < strings.count; i++) argv[i] = (char *)strings[i].UTF8String;
    char *environment[] = {"PATH=/usr/bin:/bin:/usr/sbin:/sbin", "HOME=/var/mobile", "LANG=C", NULL};
    posix_spawn_file_actions_t actions;
    int setup = posix_spawn_file_actions_init(&actions);
    BOOL initialized = setup == 0;
    if (!setup) setup = posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDOUT_FILENO);
    if (!setup) setup = posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
    if (!setup) setup = posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    if (!setup) setup = posix_spawn_file_actions_addclose(&actions, pipefd[0]);
    if (!setup) setup = posix_spawn_file_actions_addclose(&actions, pipefd[1]);
    posix_spawnattr_t attributes;
    BOOL attributesInitialized = NO;
    if (!setup) { setup = posix_spawnattr_init(&attributes); attributesInitialized = setup == 0; }
    if (!setup) setup = posix_spawnattr_setpgroup(&attributes, 0);
    if (!setup) setup = posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
    pid_t child = -1;
    int spawned = setup ?: posix_spawn(&child, path.fileSystemRepresentation, &actions, &attributes, argv, environment);
    if (attributesInitialized) posix_spawnattr_destroy(&attributes);
    if (initialized) posix_spawn_file_actions_destroy(&actions);
    free(argv); close(pipefd[1]);
    if (spawned) {
        close(pipefd[0]);
        if (error) *error = SHDWCleanupError(11, @"Unable to start cleanup.", nil, NO);
        return nil;
    }
    fcntl(pipefd[0], F_SETFL, O_NONBLOCK);
    NSMutableData *output = [NSMutableData new];
    NSTimeInterval deadline = NSProcessInfo.processInfo.systemUptime + 300;
    int status = 0; BOOL exited = NO, ended = NO, invalid = NO;
    while (!exited || !ended) {
        if (NSProcessInfo.processInfo.systemUptime >= deadline || output.length > 1024 * 1024) { invalid = YES; break; }
        struct pollfd item = {pipefd[0], POLLIN | POLLHUP, 0};
        int ready = poll(&item, 1, 50);
        if (ready < 0 && errno != EINTR) { invalid = YES; break; }
        if (ready > 0 && !ended) {
            char bytes[8192]; ssize_t count;
            while ((count = read(pipefd[0], bytes, sizeof(bytes))) > 0) {
                [output appendBytes:bytes length:(NSUInteger)count];
                if (output.length > 1024 * 1024) { invalid = YES; break; }
            }
            if (count == 0) ended = YES;
            else if (count < 0 && errno != EAGAIN && errno != EINTR) invalid = YES;
        }
        if (invalid) break;
        if (!exited) {
            pid_t result = waitpid(child, &status, WNOHANG);
            if (result == child) exited = YES;
            else if (result < 0 && errno != EINTR) { invalid = YES; break; }
        }
    }
    close(pipefd[0]);
    if (invalid || !exited) kill(-child, SIGKILL);
    if (!exited) {
        kill(child, SIGKILL);
        while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    }
    id reply = invalid ? nil : [NSJSONSerialization JSONObjectWithData:output options:0 error:nil];
    if (![reply isKindOfClass:NSDictionary.class] || ![reply[@"ok"] isKindOfClass:NSNumber.class]) {
        if (error) *error = SHDWCleanupError(12, @"Cleanup did not finish. Check the current step before trying again.", nil, ![arguments.firstObject isEqual:@"inspect"]);
        return nil;
    }
    if (![reply[@"ok"] boolValue] || !WIFEXITED(status) || WEXITSTATUS(status)) {
        NSString *message = [reply[@"error"] isKindOfClass:NSString.class] ? reply[@"error"] : @"Unable to complete cleanup.";
        NSString *step = [reply[@"step"] isKindOfClass:NSString.class] ? reply[@"step"] : nil;
        if (error) {
            NSError *failure = SHDWCleanupError(13, message, step, [reply[@"partial"] boolValue] || [reply[@"stateMayBePartial"] boolValue]);
            if ([reply[@"details"] isKindOfClass:NSDictionary.class]) {
                NSMutableDictionary *info = [failure.userInfo mutableCopy]; info[@"helperDetails"] = reply[@"details"];
                failure = [NSError errorWithDomain:failure.domain code:failure.code userInfo:info];
            }
            *error = failure;
        }
        return nil;
    }
    return reply;
}
- (void)startWithSteps:(NSArray<NSString *> *)steps progress:(SHDWCleanupProgress)progress completion:(void (^)(BOOL, NSError *))completion {
    @synchronized(SHDWCleanupService.class) {
        if (SHDWCleanupActive) {
            dispatch_async(dispatch_get_main_queue(), ^{ completion(NO, SHDWCleanupError(1, @"Cleanup is already running.", nil, NO)); });
            return;
        }
        NSError *busyError = nil;
        if (![SHDWOperationCoordinator beginOperation:&busyError]) {
            dispatch_async(dispatch_get_main_queue(), ^{ completion(NO, busyError); });
            return;
        }
        SHDWCleanupActive = YES; self.running = YES;
    }
    NSArray *requested = [steps copy];
    NSString *identifier = [self.bundleIdentifier copy];
    SHDWCleanupProgress update = ^(NSString *step, NSString *state, NSString *message) {
        dispatch_sync(dispatch_get_main_queue(), ^{ progress(step, state, message); });
    };
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil; BOOL mutated = NO;
        NSString *activeStep = requested.firstObject;
        @try {
            NSSet *selection = [NSSet setWithArray:requested];
            NSArray *order = SHDWCleanupOrder();
            if (!identifier.length || !requested.count || requested.count != selection.count || ![selection isSubsetOfSet:[NSSet setWithArray:order]])
                error = SHDWCleanupError(2, @"Select at least one cleanup item.", nil, NO);
            SHDWFingerprintStore *store = SHDWFingerprintStore.sharedStore;
            NSDictionary *originalProfile = [store profileForBundleIdentifier:identifier];
            NSDictionary *refreshedProfile = nil;
            if (!error && ![store.registeredBundleIdentifiers containsObject:identifier]) error = SHDWCleanupError(3, @"Application is not registered.", nil, NO);
            if (!error && [selection containsObject:@"fingerprint"] && ![store enabledForApplication:identifier])
                error = SHDWCleanupError(4, @"Enable the fingerprint, or deselect Refresh fingerprint.", @"fingerprint", NO);
            for (NSString *step in order) update(step, [selection containsObject:step] ? @"pending" : @"skipped", nil);
            update(@"recheck", @"pending", nil);
            NSDictionary *plan = error ? nil : [self invokeHelper:@[@"inspect", identifier] error:&error];
            NSString *token = [plan[@"token"] isKindOfClass:NSString.class] ? plan[@"token"] : nil;
            if (!error && !token.length) error = SHDWCleanupError(5, @"Unable to verify the selected application.", nil, NO);
            NSMutableArray *ordered = [NSMutableArray new];
            for (NSString *step in order) if ([selection containsObject:step]) [ordered addObject:step];
            if (!error) {
                activeStep = ordered.firstObject;
                update(activeStep, @"running", nil);
                [self invokeHelper:@[@"prepare", identifier, token, [ordered componentsJoinedByString:@","]] error:&error];
            }
            for (NSString *step in ordered) {
                if (error) break;
                activeStep = step;
                update(step, @"running", nil);
                NSTimeInterval started = NSProcessInfo.processInfo.systemUptime;
                if ([step isEqual:@"fingerprint"]) {
                    BOOL wasLocked = [store lockedForApplication:identifier];
                    BOOL refreshed = NO;
                    @try {
                        if (wasLocked && ![store setLocked:NO forApplication:identifier error:&error] && !error)
                            error = SHDWCleanupError(6, @"Unable to refresh the fingerprint.", step, mutated);
                        if (!error) {
                            refreshed = [store refreshApplication:identifier error:&error];
                            if (!refreshed && !error) error = SHDWCleanupError(6, @"Unable to refresh the fingerprint.", step, mutated);
                        }
                    } @finally {
                        if (!refreshed && wasLocked && ![store lockedForApplication:identifier]) {
                            NSError *lockError = nil;
                            if (![store setLocked:YES forApplication:identifier error:&lockError]) {
                                mutated = YES;
                                error = lockError ?: SHDWCleanupError(6, @"Unable to restore the fingerprint lock.", step, YES);
                            }
                        }
                    }
                    if (refreshed && !error) { mutated = YES; refreshedProfile = [store profileForBundleIdentifier:identifier]; }
                } else {
                    [self invokeHelper:@[@"run", identifier, token, step] error:&error];
                    if (!error) mutated = YES;
                }
                NSTimeInterval remaining = 0.25 - (NSProcessInfo.processInfo.systemUptime - started);
                if (remaining > 0) [NSThread sleepForTimeInterval:remaining];
                if (!error) update(step, @"completed", nil);
            }
            if (!error) {
                activeStep = @"recheck";
                update(activeStep, @"running", nil);
                NSTimeInterval started = NSProcessInfo.processInfo.systemUptime;
                [self invokeHelper:@[@"finalize", identifier, token, [ordered componentsJoinedByString:@","]] error:&error];
                NSDictionary *verified = error ? nil : [self invokeHelper:@[@"recheck", identifier, token, [ordered componentsJoinedByString:@","]] error:&error];
                if (!error && ![verified[@"recheckVerified"] boolValue]) error = SHDWCleanupError(8, @"Cleanup verification did not pass.", activeStep, mutated);
                NSDictionary *current = [store profileForBundleIdentifier:identifier];
                BOOL same = originalProfile == current || [originalProfile isEqual:current];
                if (!error && [selection containsObject:@"fingerprint"]) {
                    if (!refreshedProfile.count || same || ![current isEqual:refreshedProfile] || ![store lockedForApplication:identifier])
                        error = SHDWCleanupError(9, @"Fingerprint verification did not pass.", activeStep, mutated);
                } else if (!error && !same) error = SHDWCleanupError(9, @"Fingerprint verification did not pass.", activeStep, mutated);
                NSTimeInterval remaining = 0.25 - (NSProcessInfo.processInfo.systemUptime - started);
                if (remaining > 0) [NSThread sleepForTimeInterval:remaining];
                if (!error) update(activeStep, @"completed", nil);
            }
        } @catch (NSException *exception) {
            error = SHDWCleanupError(7, @"Unable to complete cleanup.", activeStep, mutated);
        }
        if (error) {
            if (mutated && ![error.userInfo[@"stateMayBePartial"] boolValue]) {
                NSMutableDictionary *info = [error.userInfo mutableCopy]; info[@"stateMayBePartial"] = @YES;
                error = [NSError errorWithDomain:error.domain code:error.code userInfo:info];
            }
            NSString *step = error.userInfo[@"step"];
            if (!step.length) step = activeStep;
            if (step) update(step, @"failed", error.localizedDescription);
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            @synchronized(SHDWCleanupService.class) { SHDWCleanupActive = NO; self.running = NO; }
            [SHDWOperationCoordinator endOperation];
            completion(error == nil, error);
        });
    });
}
@end
