#import <objc/message.h>

// The proc_pidinfo BSD record is a stable Darwin ABI, also used by libproc.
typedef struct {
    uint32_t flags, status, xstatus, pid, ppid, uid, gid, ruid, rgid, svuid, svgid, reserved;
    char comm[16], name[32];
    uint32_t files, pgid, jobc, tdev, tpgid;
    int32_t nice;
    uint64_t startSeconds, startMicroseconds;
} SHDWProcessBSDInfo;

static pid_t ApplicationProcessID(NSString *identifier) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{ dlopen("/System/Library/PrivateFrameworks/FrontBoardServices.framework/FrontBoardServices", RTLD_NOW); });
    Class cls = NSClassFromString(@"FBSSystemService");
    SEL shared = NSSelectorFromString(@"sharedService"), lookup = NSSelectorFromString(@"pidForApplication:");
    Require([cls respondsToSelector:shared], @"Application process lookup unavailable");
    id service = ((id (*)(id, SEL))objc_msgSend)(cls, shared);
    Require([service respondsToSelector:lookup], @"Application process lookup unavailable");
    int pid = ((int (*)(id, SEL, id))objc_msgSend)(service, lookup, identifier);
    return pid > 1 ? pid : 0;
}
static id ProcessObjectValue(id object, SEL selector) {
    return [object respondsToSelector:selector] ? ((id (*)(id, SEL))objc_msgSend)(object, selector) : nil;
}
static NSString *WebKitOwnerBundleID(pid_t pid) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{ dlopen("/System/Library/PrivateFrameworks/RunningBoardServices.framework/RunningBoardServices", RTLD_NOW); });
    @try {
        Class cls = NSClassFromString(@"RBSProcessHandle");
        SEL lookup = NSSelectorFromString(@"handleForIdentifier:error:");
        if (![cls respondsToSelector:lookup]) return nil;
        NSError *error = nil;
        id handle = ((id (*)(id, SEL, id, NSError **))objc_msgSend)(cls, lookup, @(pid), &error);
        if (!handle || error) return nil;
        id identity = ProcessObjectValue(handle, NSSelectorFromString(@"identity"));
        id hostIdentity = ProcessObjectValue(identity, NSSelectorFromString(@"hostIdentity"));
        id value = ProcessObjectValue(hostIdentity, NSSelectorFromString(@"embeddedApplicationIdentifier"));
        if ([value isKindOfClass:NSString.class] && [value length]) return value;
        id owner = ProcessObjectValue(handle, NSSelectorFromString(@"hostProcess"));
        id bundle = ProcessObjectValue(owner, NSSelectorFromString(@"bundle"));
        value = ProcessObjectValue(bundle, NSSelectorFromString(@"identifier"));
        return [value isKindOfClass:NSString.class] && [value length] ? value : nil;
    } @catch (NSException *exception) { (void)exception; return nil; }
}
static NSArray *WebKitProcessNames(void) {
    return @[@"com.apple.WebKit.WebContent", @"com.apple.WebKit.Networking", @"com.apple.WebKit.GPU", @"com.apple.WebKit.WebContent.CaptivePortal", @"com.apple.WebKit.WebContent.Crashy"];
}
static NSData *ProcessName(pid_t pid) {
    int (*nameForPID)(int, void *, uint32_t) = dlsym(RTLD_DEFAULT, "proc_name");
    Require(nameForPID != NULL, @"Process name lookup unavailable");
    char name[64] = {0};
    if (nameForPID(pid, name, sizeof(name)) <= 0) return nil;
    return [NSData dataWithBytes:name length:strnlen(name, sizeof(name))];
}
static BOOL ProcessNameMatches(NSData *name, NSString *expected) {
    if (!name.length || !expected.length) return NO;
    NSData *full = [expected dataUsingEncoding:NSUTF8StringEncoding];
    if ([name isEqual:full]) return YES;
    NSUInteger size = name.length;
    return (size == 15 || size == 16 || size == 31 || size == 32) && size < full.length &&
        !memcmp(name.bytes, full.bytes, size);
}
static NSArray *ProcessIDs(void) {
    int (*list)(void *, int) = dlsym(RTLD_DEFAULT, "proc_listallpids");
    Require(list != NULL, @"Process inspection unavailable");
    for (NSUInteger attempt = 0; attempt < 3; attempt++) {
        int count = list(NULL, 0);
        Require(count > 0 && count < 32768, @"Cannot enumerate application processes");
        NSMutableData *buffer = [NSMutableData dataWithLength:(count + 256) * sizeof(pid_t)];
        int actual = list(buffer.mutableBytes, (int)buffer.length);
        Require(actual >= 0, @"Cannot enumerate application processes");
        if ((NSUInteger)actual * sizeof(pid_t) >= buffer.length) continue;
        NSMutableArray *result = [NSMutableArray new]; pid_t *pids = buffer.mutableBytes;
        for (int i = 0; i < actual; i++) if (pids[i] > 1) [result addObject:@(pids[i])];
        return result;
    }
    Fail(@"Process list changed during inspection"); return nil;
}
static NSDictionary *ProcessIdentity(pid_t pid);
static NSString *ReadProcessPath(pid_t pid) {
    int (*pathForPID)(int, void *, uint32_t) = dlsym(RTLD_DEFAULT, "proc_pidpath");
    Require(pathForPID != NULL, @"Process inspection unavailable");
    char path[PATH_MAX] = {0}, canonical[PATH_MAX];
    if (pathForPID(pid, path, sizeof(path)) <= 0 || !realpath(path, canonical)) return nil;
    return [NSString stringWithUTF8String:canonical];
}
static NSString *ProcessPath(pid_t pid) {
    NSString *path = ReadProcessPath(pid);
    if (!path) {
        if (!ProcessIdentity(pid)) return nil;
        Fail([NSString stringWithFormat:@"Cannot inspect application or WebKit process %d; cleanup stopped", pid]);
    }
    return path;
}
static NSDictionary *ReadProcessIdentity(pid_t pid, BOOL *unresolved) {
    *unresolved = NO;
    int (*info)(int, int, uint64_t, void *, int) = dlsym(RTLD_DEFAULT, "proc_pidinfo");
    Require(info != NULL, @"Process identity inspection unavailable");
    SHDWProcessBSDInfo value = {0};
    int size = info(pid, 3, 0, &value, sizeof(value));
    if (size != sizeof(value)) {
        if (kill(pid, 0) && errno == ESRCH) return nil;
        *unresolved = YES;
        return nil;
    }
    if (value.status == 5) return nil; // A zombie has already released its files.
    return @{@"pid":@(pid), @"seconds":@(value.startSeconds), @"microseconds":@(value.startMicroseconds)};
}
static NSDictionary *ProcessIdentity(pid_t pid) {
    BOOL unresolved = NO;
    NSDictionary *identity = ReadProcessIdentity(pid, &unresolved);
    Require(!unresolved, @"Cannot verify application process identity");
    return identity;
}
static NSDictionary *ProcessEnvironment(pid_t pid) {
    int limit = 0; size_t limitSize = sizeof(limit); int maximum[] = {CTL_KERN, KERN_ARGMAX};
    Require(!sysctl(maximum, 2, &limit, &limitSize, NULL, 0) && limit > 0, @"Cannot inspect WebKit process environment");
    NSMutableData *buffer = [NSMutableData dataWithLength:(NSUInteger)limit];
    size_t length = buffer.length; int query[] = {CTL_KERN, KERN_PROCARGS2, pid};
    if (sysctl(query, 3, buffer.mutableBytes, &length, NULL, 0)) {
        if (kill(pid, 0) && errno == ESRCH) return nil;
        Fail(@"Cannot identify the application owning a WebKit process");
    }
    Require(length <= buffer.length && length >= sizeof(int), @"Invalid WebKit process environment");
    const char *bytes = buffer.bytes; int argc = 0; memcpy(&argc, bytes, sizeof(argc));
    Require(argc >= 0 && (NSUInteger)argc < length, @"Invalid WebKit process arguments");
    NSUInteger offset = sizeof(argc);
    while (offset < length && bytes[offset]) offset++;
    while (offset < length && !bytes[offset]) offset++;
    for (int i = 0; i < argc; i++) {
        size_t size = strnlen(bytes + offset, length - offset);
        Require(size < length - offset, @"Truncated WebKit process arguments");
        offset += size + 1;
    }
    NSMutableDictionary *result = [NSMutableDictionary new];
    while (offset < length && bytes[offset]) {
        size_t size = strnlen(bytes + offset, length - offset);
        Require(size < length - offset, @"Truncated WebKit process environment");
        NSString *entry = [[NSString alloc] initWithBytes:bytes + offset length:size encoding:NSUTF8StringEncoding];
        NSRange separator = [entry rangeOfString:@"="];
        if (entry && separator.location != NSNotFound) {
            NSString *key = [entry substringToIndex:separator.location];
            if ([key isEqual:@"HOME"] || [key isEqual:@"CFFIXED_USER_HOME"]) {
                Require(!result[key], @"Ambiguous WebKit process environment");
                result[key] = [entry substringFromIndex:separator.location + 1];
            }
        }
        offset += size + 1;
    }
    return result;
}
static BOOL IsWebKitService(NSString *path) {
    NSString *root = @"/System/Library/Frameworks/WebKit.framework/XPCServices";
    for (NSString *service in WebKitProcessNames()) {
        NSString *expected = [[root stringByAppendingPathComponent:[service stringByAppendingString:@".xpc"]] stringByAppendingPathComponent:service];
        if ([path isEqual:expected]) return YES;
    }
    return NO;
}
typedef NS_ENUM(unsigned, SHDWProcessObservation) {
    SHDWProcessGone,
    SHDWProcessSame,
    SHDWProcessUnresolved
};
static SHDWProcessObservation ObserveTrackedProcess(NSNumber *pid, NSDictionary *record) {
    BOOL unresolved = NO;
    NSDictionary *identity = ReadProcessIdentity(pid.intValue, &unresolved);
    if (unresolved) return SHDWProcessUnresolved;
    if (![identity isEqual:record[@"identity"]]) return SHDWProcessGone;
    if (!record[@"applicationBundleID"]) {
        NSString *path = ReadProcessPath(pid.intValue);
        if (!path) return SHDWProcessUnresolved;
        if (![path isEqual:record[@"path"]]) return SHDWProcessGone;
    }
    if (record[@"webKitOwner"]) {
        NSString *owner = WebKitOwnerBundleID(pid.intValue);
        if (!owner) return SHDWProcessUnresolved;
        if (![owner isEqual:record[@"webKitOwner"]]) return SHDWProcessGone;
    }
    identity = ReadProcessIdentity(pid.intValue, &unresolved);
    if (unresolved) return SHDWProcessUnresolved;
    return [identity isEqual:record[@"identity"]] ? SHDWProcessSame : SHDWProcessGone;
}
static NSDictionary *TargetProcessesWithTracked(NSDictionary *target, NSDictionary *tracked) {
    NSMutableSet *homes = [NSMutableSet new], *identifiers = [NSMutableSet setWithObject:target[@"bundleID"]];
    [identifiers addObjectsFromArray:target[@"identifiers"] ?: @[]];
    for (NSDictionary *container in target[@"containers"]) {
        // Shared app-group storage does not establish ownership of a process.
        if ([identifiers containsObject:container[@"identifier"]]) [homes addObject:Canonical(container[@"path"])];
    }
    NSMutableDictionary *result = [NSMutableDictionary new];
    for (NSNumber *pid in tracked) {
        NSDictionary *record = tracked[pid];
        if (ObserveTrackedProcess(pid, record) != SHDWProcessGone) result[pid] = record;
    }
    BOOL resolved = NO;
    for (NSUInteger attempt = 0; attempt < 3; attempt++) {
        pid_t pid = ApplicationProcessID(target[@"bundleID"]);
        if (!pid || result[@(pid)]) { resolved = YES; break; }
        NSDictionary *identity = ProcessIdentity(pid);
        if (!identity) {
            if (ApplicationProcessID(target[@"bundleID"]) == pid) { resolved = YES; break; }
            continue;
        }
        if (ApplicationProcessID(target[@"bundleID"]) != pid || ![ProcessIdentity(pid) isEqual:identity]) continue;
        result[@(pid)] = @{@"identity":identity, @"applicationBundleID":target[@"bundleID"], @"web":@NO};
        resolved = YES; break;
    }
    Require(resolved, @"Application process changed during inspection");
    for (NSNumber *number in ProcessIDs()) {
        if (result[number]) continue;
        pid_t pid = number.intValue;
        NSData *name = ProcessName(pid);
        BOOL appCandidate = NO, webCandidate = NO;
        for (NSDictionary *executable in target[@"executables"]) appCandidate |= ProcessNameMatches(name, [executable[@"path"] lastPathComponent]);
        for (NSString *service in WebKitProcessNames()) webCandidate |= ProcessNameMatches(name, service);
        if (!appCandidate && !webCandidate) continue;
        NSString *owner = webCandidate && !appCandidate ? WebKitOwnerBundleID(pid) : nil;
        if (owner && ![identifiers containsObject:owner]) continue;
        NSString *path = ProcessPath(pid);
        BOOL app = path && Inside(path, target[@"bundlePath"]), web = IsWebKitService(path);
        if (!app && !web) continue;
        if (web && !owner) owner = WebKitOwnerBundleID(pid);
        if (web && owner && ![identifiers containsObject:owner]) continue;
        NSDictionary *identity = ProcessIdentity(pid); if (!identity) continue;
        if (web && !owner) {
            NSDictionary *environment = ProcessEnvironment(pid); if (!environment) continue;
            NSString *home = environment[@"CFFIXED_USER_HOME"] ?: environment[@"HOME"];
            char canonical[PATH_MAX];
            if (!home.length || !realpath(home.fileSystemRepresentation, canonical)) Fail(@"Cannot resolve WebKit application container");
            if (![homes containsObject:[NSString stringWithUTF8String:canonical]]) continue;
            NSString *other = environment[@"HOME"];
            if (other && environment[@"CFFIXED_USER_HOME"]) {
                Require(realpath(other.fileSystemRepresentation, canonical) && [homes containsObject:[NSString stringWithUTF8String:canonical]], @"Ambiguous WebKit application container");
            }
        }
        if (![ProcessIdentity(pid) isEqual:identity] || ![ProcessPath(pid) isEqual:path]) continue;
        if (web && owner && ![WebKitOwnerBundleID(pid) isEqual:owner]) continue;
        if (![ProcessIdentity(pid) isEqual:identity]) continue;
        NSMutableDictionary *record = [@{@"identity":identity, @"path":path, @"web":@(web)} mutableCopy];
        if (web && owner) record[@"webKitOwner"] = owner;
        result[number] = record;
    }
    return result;
}
static NSDictionary *TargetProcesses(NSDictionary *target) { return TargetProcessesWithTracked(target, nil); }
static BOOL SignalProcess(NSNumber *pid, NSDictionary *record) {
    // Darwin kill(2) has no atomic start-identity argument; recheck immediately.
    SHDWProcessObservation observation = ObserveTrackedProcess(pid, record);
    if (observation != SHDWProcessSame) return observation == SHDWProcessGone;
    if (record[@"applicationBundleID"] && ApplicationProcessID(record[@"applicationBundleID"]) != pid.intValue) return NO;
    observation = ObserveTrackedProcess(pid, record);
    if (observation != SHDWProcessSame) return observation == SHDWProcessGone;
    int status = kill(pid.intValue, SIGTERM);
    Require(!status || errno == ESRCH, @"Cannot request application process termination");
    return YES;
}
static BOOL TargetStopped(NSDictionary *target) { return TargetProcesses(target).count == 0; }
static NSDictionary *Stop(NSDictionary *target) {
    NSMutableDictionary *tracked = [TargetProcesses(target) mutableCopy];
    NSUInteger apps = 0, web = 0;
    NSMutableSet *signalled = [NSMutableSet new];
    for (NSNumber *pid in tracked) {
        if ([tracked[pid][@"web"] boolValue]) web++;
        else { apps++; if (SignalProcess(pid, tracked[pid])) [signalled addObject:pid]; }
    }
    double started = MonotonicSeconds(), quietSince = 0;
    while (MonotonicSeconds() - started < 15.0) {
        NSDictionary *current = TargetProcessesWithTracked(target, tracked);
        for (NSNumber *pid in current) {
            if (![tracked[pid][@"identity"] isEqual:current[pid][@"identity"]]) {
                [signalled removeObject:pid];
                tracked[pid] = current[pid];
                if ([current[pid][@"web"] boolValue]) web++;
                else { apps++; if (SignalProcess(pid, current[pid])) [signalled addObject:pid]; }
            }
        }
        BOOL alive = NO;
        for (NSNumber *pid in tracked) {
            NSDictionary *record = tracked[pid];
            SHDWProcessObservation observation = ObserveTrackedProcess(pid, record);
            if (observation == SHDWProcessGone) continue;
            alive = YES;
            if (observation == SHDWProcessUnresolved) continue;
            // First allow connection-loss handlers to flush and close naturally.
            if ((! [record[@"web"] boolValue] || MonotonicSeconds() - started >= 3.0) && ![signalled containsObject:pid]) {
                if (SignalProcess(pid, record)) [signalled addObject:pid];
            }
        }
        if (!alive && !current.count) {
            if (!quietSince) quietSince = MonotonicSeconds();
            if (MonotonicSeconds() - quietSince >= 0.3)
                return @{@"applicationProcesses":@(apps), @"webKitProcesses":@(web), @"waitSeconds":@(MonotonicSeconds() - started)};
        } else quietSince = 0;
        usleep(100000);
    }
    Fail(@"Application or WebKit processes did not exit; no application data was cleared"); return nil;
}

static void VerifyStoppedTarget(NSDictionary *target, void (^checks)(void)) {
    Require(TargetStopped(target), @"Target application restarted before final verification");
    checks();
    Require(TargetStopped(target), @"Target application restarted during final verification");
}

static void VerifyCleanupSteps(NSDictionary *target, NSArray *steps, void (^check)(NSString *)) {
    VerifyStoppedTarget(target, ^{
        // Credential inspection can be slow. Scan filesystem/preferences after it.
        if ([steps containsObject:@"keychain"]) check(@"keychain");
        for (NSString *step in steps)
            if (![step isEqual:@"keychain"] && ![step isEqual:@"fingerprint"]) check(step);
    });
}
