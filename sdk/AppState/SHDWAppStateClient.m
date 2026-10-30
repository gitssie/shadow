#import "SHDWAppStateClient.h"
#include <spawn.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <stdio.h>
#include <poll.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <math.h>

static const NSUInteger MaximumFrame = 8 * 1024 * 1024;
static NSError *UnknownError(NSError *error) {
    NSMutableDictionary *info = [error.userInfo mutableCopy]; info[@"outcomeUnknown"] = @YES;
    return [NSError errorWithDomain:error.domain code:error.code userInfo:info];
}
static NSError *BackupError(NSInteger code, NSString *message, BOOL partial) {
    return [NSError errorWithDomain:@"me.jjolano.shadow.backup" code:code userInfo:@{NSLocalizedDescriptionKey:message, @"stateMayBePartial":@(partial)}];
}
@interface SHDWAppStateClient ()
@property(nonatomic, copy) NSString *helperPath;
- (BOOL)validateHelperAtPath:(NSString *)path error:(NSError **)error;
@end
@implementation SHDWAppStateClient
- (instancetype)initWithHelperPath:(NSString *)helperPath {
    if ((self = [super init])) { _helperPath = [helperPath copy]; _timeout = 30 * 60; }
    return self;
}
- (BOOL)validateHelperAtPath:(NSString *)path error:(NSError **)error {
    struct stat info;
    if (!path.length || lstat(path.fileSystemRepresentation, &info) || !S_ISREG(info.st_mode) || info.st_uid != 0 || (info.st_mode & 022) || !(info.st_mode & S_ISUID) || info.st_nlink != 1) {
        if (error) *error = BackupError(1, @"The backup helper is unavailable. Reinstall Shadow.", NO);
        return NO;
    }
    return YES;
}
- (id)invokeAction:(NSString *)action bundleIdentifier:(NSString *)bundleIdentifier request:(NSDictionary *)request progress:(SHDWAppStateClientProgress)progress error:(NSError **)error {
    if (error) *error = nil;
    BOOL external = [@[@"capabilities", @"externalCatalog", @"externalEdit", @"exportState", @"importState"] containsObject:action];
    NSArray *allowed = @[@"catalog", @"backup", @"restore", @"edit", @"delete", @"recheck", @"capabilities", @"externalCatalog", @"externalEdit", @"exportState", @"importState"];
    if (![allowed containsObject:action] || ![bundleIdentifier isKindOfClass:NSString.class] || !bundleIdentifier.length ||
        [bundleIdentifier rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"] invertedSet]].location != NSNotFound ||
        ![request isKindOfClass:NSDictionary.class] || !isfinite(self.timeout) || self.timeout <= 0) {
        if (error) *error = BackupError(2, @"Invalid backup request.", NO); return nil;
    }
    NSUInteger frameLimit = external ? 130 * 1024 * 1024 : MaximumFrame;
    BOOL useInput = [action isEqual:@"importState"];
    NSString *path = [self helperPath];
    if (![self validateHelperAtPath:path error:error]) return nil;
    if (![NSPropertyListSerialization propertyList:request isValidForFormat:NSPropertyListBinaryFormat_v1_0]) {
        if (error) *error = BackupError(2, @"Invalid backup request.", NO); return nil;
    }
    NSData *encoded = [NSPropertyListSerialization dataWithPropertyList:request format:NSPropertyListBinaryFormat_v1_0 options:0 error:error];
    if (!encoded || encoded.length > (useInput ? 96 * 1024 * 1024 : 8192)) { if (error && !*error) *error = BackupError(2, @"Invalid backup request.", NO); return nil; }
    FILE *input = NULL;
    if (useInput) {
        input = tmpfile();
        if (!input || fchmod(fileno(input), 0600) || fcntl(fileno(input), F_SETFD, FD_CLOEXEC) ||
            fwrite(encoded.bytes, 1, encoded.length, input) != encoded.length || fflush(input) || fseek(input, 0, SEEK_SET)) {
            if (input) fclose(input);
            if (error) *error = BackupError(3, @"Unable to prepare backup request.", NO); return nil;
        }
    }
    NSArray *strings = @[path, @"state", bundleIdentifier, action, useInput ? @"-" : [encoded base64EncodedStringWithOptions:0]];
    char *argv[6] = {0}; for (NSUInteger i = 0; i < strings.count; i++) argv[i] = (char *)[strings[i] UTF8String];
    char *environment[] = {"PATH=/usr/bin:/bin:/usr/sbin:/sbin", "HOME=/var/mobile", "LANG=C", NULL};
    int channel[2]; if (pipe(channel)) { if (input) fclose(input); if (error) *error = BackupError(3, @"Unable to start backup operation.", NO); return nil; }
    fcntl(channel[0], F_SETFD, FD_CLOEXEC); fcntl(channel[1], F_SETFD, FD_CLOEXEC);
    posix_spawn_file_actions_t actions; posix_spawnattr_t attributes;
    int setup = posix_spawn_file_actions_init(&actions); BOOL actionsReady = setup == 0, attributesReady = NO;
    if (!setup) setup = posix_spawn_file_actions_adddup2(&actions, channel[1], STDOUT_FILENO);
    if (!setup) setup = posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
    if (!setup) setup = input ? posix_spawn_file_actions_adddup2(&actions, fileno(input), STDIN_FILENO) : posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    if (!setup) setup = posix_spawn_file_actions_addclose(&actions, channel[0]);
    if (!setup) setup = posix_spawn_file_actions_addclose(&actions, channel[1]);
    if (!setup) { setup = posix_spawnattr_init(&attributes); attributesReady = setup == 0; }
    if (!setup) setup = posix_spawnattr_setpgroup(&attributes, 0);
    if (!setup) setup = posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
    pid_t child = -1;
    int spawned = setup ?: posix_spawn(&child, path.fileSystemRepresentation, &actions, &attributes, argv, environment);
    if (attributesReady) posix_spawnattr_destroy(&attributes);
    if (actionsReady) posix_spawn_file_actions_destroy(&actions);
    close(channel[1]);
    if (input) fclose(input);
    if (spawned) { close(channel[0]); if (error) *error = BackupError(3, @"Unable to start backup operation.", NO); return nil; }
    int flags = fcntl(channel[0], F_GETFL); BOOL invalid = flags < 0 || fcntl(channel[0], F_SETFL, flags | O_NONBLOCK) != 0;
    BOOL ended = NO, exited = NO; int status = 0; NSDictionary *terminal = nil;
    NSMutableData *buffer = [NSMutableData new];
    NSTimeInterval deadline = NSProcessInfo.processInfo.systemUptime + self.timeout;
    while (!invalid && (!ended || !exited)) {
        @autoreleasepool {
            if (NSProcessInfo.processInfo.systemUptime >= deadline) { invalid = YES; break; }
            struct pollfd item = {channel[0], POLLIN | POLLHUP, 0};
            int ready = poll(&item, 1, 50);
            if (ready < 0 && errno != EINTR) { invalid = YES; break; }
            if (ready > 0 && !ended) {
                if (item.revents & (POLLERR | POLLNVAL)) { invalid = YES; break; }
                char bytes[8192]; ssize_t count;
                while ((count = read(channel[0], bytes, sizeof(bytes))) > 0) {
                    if (NSProcessInfo.processInfo.systemUptime >= deadline) { invalid = YES; break; }
                    if ((NSUInteger)count > frameLimit - MIN(buffer.length, frameLimit)) { invalid = YES; break; }
                    [buffer appendBytes:bytes length:(NSUInteger)count];
                    for (;;) {
                        @autoreleasepool {
                        const unsigned char *raw = buffer.bytes;
                        const unsigned char *newline = memchr(raw, '\n', buffer.length);
                        if (!newline) break;
                        NSUInteger length = (NSUInteger)(newline - raw);
                        if (!length || length > frameLimit || terminal) { invalid = YES; break; }
                        NSData *line = [buffer subdataWithRange:NSMakeRange(0, length)];
                        [buffer replaceBytesInRange:NSMakeRange(0, length + 1) withBytes:NULL length:0];
                        id frame = [NSJSONSerialization JSONObjectWithData:line options:0 error:NULL];
                        if (![frame isKindOfClass:NSDictionary.class]) { invalid = YES; break; }
                        if ([frame[@"event"] isEqual:@"progress"]) {
                            NSDictionary *event = frame[@"progress"];
                            if (![event isKindOfClass:NSDictionary.class] || event.count > 16) { invalid = YES; break; }
                            if (progress) progress(event);
                        } else if ([frame[@"ok"] isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)frame[@"ok"]) == CFBooleanGetTypeID()) terminal = frame;
                        else { invalid = YES; break; }
                        }
                    }
                    if (invalid || buffer.length > frameLimit) { invalid = YES; break; }
                }
                if (count == 0) ended = YES;
                else if (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) invalid = YES;
            }
            if (!exited) {
                pid_t result = waitpid(child, &status, WNOHANG);
                if (result == child) exited = YES;
                else if (result < 0 && errno != EINTR) invalid = YES;
            }
        }
    }
    close(channel[0]);
    if (invalid || !exited) { kill(-child, SIGKILL); kill(child, SIGKILL); }
    if (!exited) while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    BOOL partial = [action isEqual:@"restore"];
    if (invalid || buffer.length || !terminal) {
        if (error) { *error = BackupError(4, @"The backup operation was interrupted. Check its status before trying again.", partial); if (useInput) *error = UnknownError(*error); }
        return nil;
    }
    if (![terminal[@"ok"] boolValue] || !WIFEXITED(status) || WEXITSTATUS(status)) {
        NSString *message = [terminal[@"error"] isKindOfClass:NSString.class] ? terminal[@"error"] : @"Unable to complete backup operation.";
        BOOL uncertainRestore = partial && ([terminal[@"ok"] boolValue] || !WIFEXITED(status));
        if (error) {
            NSError *failure = BackupError(5, message, uncertainRestore || [terminal[@"partial"] boolValue] || [terminal[@"stateMayBePartial"] boolValue]);
            NSMutableDictionary *info = [failure.userInfo mutableCopy];
            NSDictionary *details = [terminal[@"details"] isKindOfClass:NSDictionary.class] ? terminal[@"details"] : @{};
            info[@"helperDetails"] = details;
            info[NSLocalizedDescriptionKey] = message;
            *error = [NSError errorWithDomain:failure.domain code:failure.code userInfo:info];
            if ([terminal[@"outcomeUnknown"] boolValue] || (useInput && ([terminal[@"ok"] boolValue] || !WIFEXITED(status)))) *error = UnknownError(*error);
        }
        return nil;
    }
    NSString *payload = terminal[@"result"];
    NSData *data = [payload isKindOfClass:NSString.class] ? [[NSData alloc] initWithBase64EncodedString:payload options:0] : nil;
    id result = data ? [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:NULL] : nil;
    if (![result isKindOfClass:NSDictionary.class] && ![result isKindOfClass:NSArray.class]) {
        if (error) { *error = BackupError(6, @"The backup helper returned an invalid result.", partial); if (useInput) *error = UnknownError(*error); }
        return nil;
    }
    return result;
}
@end
