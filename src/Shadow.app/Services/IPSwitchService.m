#import "IPSwitchService.h"
#import "Language.h"
#include <arpa/inet.h>
#include <string.h>

static NSString *const IPFields = @"fields=ip,success,type,country,region,city";
static NSString *const UnconfirmedText = @"IP change has not been confirmed yet. Query again later.";
static NSError *IPError(NSInteger code, NSString *key) {
    return [NSError errorWithDomain:@"me.jjolano.shadow.ip-switch" code:code
                          userInfo:@{NSLocalizedDescriptionKey:SHDWLocalizedText(key)}];
}
static NSURL *ActionURL(NSURL *URL) {
    if (![URL isKindOfClass:NSURL.class]) return nil;
    NSString *value = URL.absoluteString;
    if ([value rangeOfCharacterFromSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].location != NSNotFound) return nil;
    NSURLComponents *parts = [NSURLComponents componentsWithString:value];
    if (!([parts.scheme.lowercaseString isEqual:@"https"] || [parts.scheme.lowercaseString isEqual:@"http"]) ||
        !parts.host.length || parts.user || parts.password || parts.fragment) return nil;
    return parts.URL;
}
static BOOL PermanentTransportError(NSError *error) {
    if (![error.domain isEqual:NSURLErrorDomain]) return NO;
    switch (error.code) {
        case NSURLErrorBadURL:
        case NSURLErrorUnsupportedURL:
        case NSURLErrorUserAuthenticationRequired:
        case NSURLErrorAppTransportSecurityRequiresSecureConnection:
        case NSURLErrorSecureConnectionFailed:
        case NSURLErrorServerCertificateHasBadDate:
        case NSURLErrorServerCertificateUntrusted:
        case NSURLErrorServerCertificateHasUnknownRoot:
        case NSURLErrorServerCertificateNotYetValid:
        case NSURLErrorClientCertificateRejected:
        case NSURLErrorClientCertificateRequired: return YES;
        default: return NO;
    }
}
static NSString *NormalizedIP(id value, int *family) {
    if (![value isKindOfClass:NSString.class]) return nil;
    const char *raw = [value UTF8String];
    if (!raw || strlen(raw) != [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding]) return nil;
    unsigned char address[sizeof(struct in6_addr)]; char output[INET6_ADDRSTRLEN];
    for (NSUInteger i = 0; i < 2; i++) {
        int candidate = i ? AF_INET6 : AF_INET;
        if (inet_pton(candidate, raw, address) == 1 && inet_ntop(candidate, address, output, sizeof(output))) {
            *family = candidate; return [NSString stringWithUTF8String:output];
        }
    }
    return nil;
}
static NSString *Region(NSDictionary *json) {
    NSMutableArray *parts = [NSMutableArray new];
    for (NSString *key in @[@"country", @"region", @"city"]) {
        id value = json[key];
        if (![value isKindOfClass:NSString.class]) continue;
        NSString *part = value;
        if (![part stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].length) continue;
        BOOL repeated = NO;
        for (NSString *previous in parts) if ([previous caseInsensitiveCompare:part] == NSOrderedSame) repeated = YES;
        if (!repeated) [parts addObject:part];
    }
    return parts.count ? [parts componentsJoinedByString:@", "] : nil;
}
static NSDictionary *IPJSON(NSData *data) {
    id json = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![json isKindOfClass:NSDictionary.class]) return nil;
    id success = json[@"success"];
    if (![success isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)success) != CFBooleanGetTypeID() || ![success boolValue]) return nil;
    int family = 0;
    return NormalizedIP(json[@"ip"], &family) ? json : nil;
}
@implementation SHDWIPSnapshot
- (instancetype)initWithIP:(NSString *)ip region:(NSString *)region ipv4:(NSString *)ipv4 checkedAt:(NSDate *)checkedAt {
    if ((self = [super init])) {
        _ip = [ip copy]; _region = [region copy]; _ipv4 = [ipv4 copy]; _checkedAt = [checkedAt copy];
    }
    return self;
}
@end
@interface SHDWIPSwitchService () <NSURLSessionTaskDelegate>
@property (nonatomic, readwrite, getter=isRunning) BOOL running;
@property (nonatomic) NSURLSession *session;
@property (nonatomic) NSMutableSet<NSURLSessionDataTask *> *tasks;
@property (nonatomic) dispatch_source_t deadlineTimer;
@property (nonatomic) dispatch_source_t pollTimer;
@property (nonatomic) NSUInteger generation;
@property (nonatomic) NSUInteger roundGeneration;
@property (nonatomic) SHDWIPSnapshot *before;
@property (nonatomic) NSURL *actionURL;
@property (nonatomic) BOOL queryOnly;
@property (nonatomic) SHDWIPSnapshot *current;
@property (nonatomic, copy) void (^progress)(SHDWIPSwitchPhase, SHDWIPSnapshot *);
@property (nonatomic, copy) void (^completion)(SHDWIPSnapshot *, SHDWIPSnapshot *, NSError *);
@end
@implementation SHDWIPSwitchService
+ (instancetype)sharedService { static id service; static dispatch_once_t once; dispatch_once(&once, ^{ service = [self new]; }); return service; }
+ (BOOL)hasIPChangeFrom:(SHDWIPSnapshot *)before to:(SHDWIPSnapshot *)after {
    int family = 0;
    NSString *oldIP = NormalizedIP(before.ip, &family), *newIP = NormalizedIP(after.ip, &family);
    NSString *old4 = NormalizedIP(before.ipv4, &family), *new4 = NormalizedIP(after.ipv4, &family);
    return (oldIP && newIP && ![oldIP isEqual:newIP]) || (old4 && new4 && ![old4 isEqual:new4]);
}
- (NSURLSessionConfiguration *)sessionConfiguration { return NSURLSessionConfiguration.ephemeralSessionConfiguration; }
- (NSTimeInterval)pollInterval { return 15; }
- (NSTimeInterval)operationTimeout { return 120; }
- (NSTimeInterval)queryTimeout { return 120; }
- (NSTimeInterval)requestTimeout { return 8; }
- (void)finish:(NSError *)error {
    if (!self.running) return;
    self.running = NO; self.generation++; self.roundGeneration++;
    if (self.deadlineTimer) { dispatch_source_cancel(self.deadlineTimer); self.deadlineTimer = nil; }
    if (self.pollTimer) { dispatch_source_cancel(self.pollTimer); self.pollTimer = nil; }
    for (NSURLSessionDataTask *task in self.tasks) [task cancel]; self.tasks = nil;
    [self.session invalidateAndCancel]; self.session = nil;
    void (^done)(SHDWIPSnapshot *, SHDWIPSnapshot *, NSError *) = self.completion;
    SHDWIPSnapshot *before = self.before, *current = self.current;
    self.completion = nil; self.progress = nil; self.before = nil; self.current = nil; self.actionURL = nil;
    if (done) done(before, current, error);
}
- (void)cancel {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ [self cancel]; }); return; }
    [self finish:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorCancelled userInfo:nil]];
}
- (void)phase:(SHDWIPSwitchPhase)phase snapshot:(SHDWIPSnapshot *)snapshot { if (self.progress) self.progress(phase, snapshot); }
- (void)request:(NSURL *)url isAction:(BOOL)isAction completion:(void (^)(NSData *, NSHTTPURLResponse *, NSError *))completion {
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:self.requestTimeout];
    [request setValue:@"no-cache, no-store" forHTTPHeaderField:@"Cache-Control"];
    NSUInteger generation = self.generation;
    __block NSURLSessionDataTask *task;
    task = [self.session dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!self.running || generation != self.generation) { task = nil; return; }
            [self.tasks removeObject:task]; task = nil;
            completion(data, [response isKindOfClass:NSHTTPURLResponse.class] ? (id)response : nil, error);
        });
    }];
    task.taskDescription = isAction ? @"action" : @"lookup";
    [self.tasks addObject:task]; [task resume];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completionHandler {
    // Lookup redirects stay within the two explicitly selected providers.
    NSString *host = request.URL.host.lowercaseString;
    BOOL lookup = ![task.taskDescription isEqual:@"action"] &&
        [request.URL.scheme.lowercaseString isEqual:@"https"] &&
        ([host isEqual:@"ipwho.is"] || [host isEqual:@"ipv4.is"]);
    completionHandler(lookup ? request : nil);
}
- (void)lookupRound:(void (^)(SHDWIPSnapshot *, NSError *))completion {
    NSUInteger round = ++self.roundGeneration;
    __block NSUInteger pending = 2;
    __block NSDictionary *who;
    __block NSString *ipv4;
    __block NSError *roundError;
    void (^receiveError)(NSHTTPURLResponse *, NSError *) = ^(NSHTTPURLResponse *response, NSError *error) {
        if (response.statusCode == 429) roundError = IPError(5, @"IP lookup is rate limited. Try again later.");
        else if (PermanentTransportError(error) && roundError.code != 5) roundError = IPError(8, @"The network request could not be completed. Check the URL and connection security.");
    };
    void (^gather)(void) = ^{
        if (!self.running || round != self.roundGeneration || --pending) return;
        NSString *ip = who[@"ip"];
        if (!ip && !ipv4) { completion(nil, roundError ?: IPError(3, @"Could not query the current public IP.")); return; }
        SHDWIPSnapshot *snapshot = [[SHDWIPSnapshot alloc] initWithIP:ip region:ip ? Region(who) : nil ipv4:ipv4 checkedAt:NSDate.date];
        completion(snapshot, roundError);
    };
    [self request:[NSURL URLWithString:[@"https://ipwho.is/?" stringByAppendingString:IPFields]] isAction:NO completion:^(NSData *data, NSHTTPURLResponse *response, NSError *error) {
        if (round != self.roundGeneration) return;
        receiveError(response, error);
        if (!error && response.statusCode >= 200 && response.statusCode < 300) who = IPJSON(data);
        gather();
    }];
    [self request:[NSURL URLWithString:@"https://ipv4.is/"] isAction:NO completion:^(NSData *data, NSHTTPURLResponse *response, NSError *error) {
        if (round != self.roundGeneration) return;
        receiveError(response, error);
        NSString *text = !error && response.statusCode >= 200 && response.statusCode < 300 ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : nil;
        NSString *trimmed = [text stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        int family = 0; NSString *parsed = NormalizedIP(trimmed, &family);
        if (parsed && family == AF_INET) ipv4 = trimmed;
        gather();
    }];
}
- (BOOL)baselineProvidersAvailable:(SHDWIPSnapshot *)snapshot {
    return snapshot && (!self.before.ip || snapshot.ip) && (!self.before.ipv4 || snapshot.ipv4);
}
- (void)scheduleProbe {
    if (!self.running) return;
    self.pollTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(self.pollTimer, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(self.pollInterval * NSEC_PER_SEC)), DISPATCH_TIME_FOREVER, 0);
    __weak typeof(self) weakSelf = self;
    dispatch_source_set_event_handler(self.pollTimer, ^{
        typeof(self) self = weakSelf; if (!self || !self.running) return;
        dispatch_source_cancel(self.pollTimer); self.pollTimer = nil;
        [self performLookup];
    });
    dispatch_resume(self.pollTimer);
}
- (void)performLookup {
    [self lookupRound:^(SHDWIPSnapshot *snapshot, NSError *error) {
        if (snapshot) self.current = snapshot;
        if (self.queryOnly && snapshot) { [self finish:nil]; return; }
        if (!self.queryOnly && !self.before && snapshot) {
            self.before = snapshot;
            NSUInteger generation = self.generation;
            [self phase:SHDWIPSwitchPhaseRequesting snapshot:snapshot];
            if (!self.running || generation != self.generation) return;
            [self request:self.actionURL isAction:YES completion:^(NSData *data, NSHTTPURLResponse *response, NSError *actionError) {
                // A response or transport error cannot establish the external network outcome.
                NSUInteger actionGeneration = self.generation;
                [self phase:SHDWIPSwitchPhaseWaitingForNetwork snapshot:self.current];
                if (self.running && actionGeneration == self.generation) [self scheduleProbe];
            }];
            return;
        }
        BOOL available = self.before ? [self baselineProvidersAvailable:snapshot] : snapshot != nil;
        if (self.before && available && [self.class hasIPChangeFrom:self.before to:snapshot]) { [self finish:nil]; return; }
        NSUInteger generation = self.generation;
        [self phase:available ? SHDWIPSwitchPhaseWaitingForChange : SHDWIPSwitchPhaseWaitingForNetwork snapshot:self.current];
        if (self.running && generation == self.generation) [self scheduleProbe];
    }];
}
- (BOOL)beginWithProgress:(void (^)(SHDWIPSwitchPhase, SHDWIPSnapshot *))progress completion:(void (^)(SHDWIPSnapshot *, SHDWIPSnapshot *, NSError *))completion timeout:(NSTimeInterval)timeout query:(BOOL)query {
    if (self.running) { completion(nil, nil, IPError(6, @"An IP switch is already running.")); return NO; }
    self.running = YES; self.generation++; self.progress = progress; self.completion = completion; self.queryOnly = query;
    self.tasks = [NSMutableSet new];
    NSURLSessionConfiguration *configuration = self.sessionConfiguration;
    configuration.URLCache = nil; configuration.HTTPCookieStorage = nil; configuration.HTTPShouldSetCookies = NO;
    configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
    self.session = [NSURLSession sessionWithConfiguration:configuration delegate:self delegateQueue:nil];
    self.deadlineTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(self.deadlineTimer, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(timeout * NSEC_PER_SEC)), DISPATCH_TIME_FOREVER, 0);
    __weak typeof(self) weakSelf = self;
    dispatch_source_set_event_handler(self.deadlineTimer, ^{ [weakSelf finish:IPError(SHDWIPSwitchErrorUnconfirmed, UnconfirmedText)]; });
    dispatch_resume(self.deadlineTimer);
    NSUInteger generation = self.generation;
    [self phase:SHDWIPSwitchPhaseChecking snapshot:nil];
    return self.running && generation == self.generation;
}
- (void)startWithURL:(NSURL *)URL progress:(void (^)(SHDWIPSwitchPhase, SHDWIPSnapshot *))progress completion:(void (^)(SHDWIPSnapshot *, SHDWIPSnapshot *, NSError *))completion {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ [self startWithURL:URL progress:progress completion:completion]; }); return; }
    if (self.running) { completion(nil, nil, IPError(6, @"An IP switch is already running.")); return; }
    NSURL *url = ActionURL(URL);
    if (!url) { completion(nil, nil, IPError(2, @"Enter a valid HTTP or HTTPS URL without credentials or spaces.")); return; }
    if (![self beginWithProgress:progress completion:completion timeout:self.operationTimeout query:NO]) return;
    self.actionURL = url;
    [self performLookup];
}

- (void)queryWithProgress:(void (^)(SHDWIPSwitchPhase, SHDWIPSnapshot *))progress completion:(void (^)(SHDWIPSnapshot *, NSError *))completion {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ [self queryWithProgress:progress completion:completion]; }); return; }
    if (![self beginWithProgress:progress completion:^(SHDWIPSnapshot *before, SHDWIPSnapshot *current, NSError *error) { completion(current, error); } timeout:self.queryTimeout query:YES]) return;
    [self performLookup];
}
@end
