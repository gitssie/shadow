#import "Sessions.h"
#import "../Transport/Profiles.h"
#import "../ShadowCore.dylib/SHDWHookSession.h"
#import "../ShadowCore.dylib/policy/CurlTransport.h"
#include <stdlib.h>

static SHDWHookSession *sessionHooks;
static NSDictionary *processSnapshot;
static BOOL installSucceeded;
static NSURLSession *(*nativeSession)(id, SEL, NSURLSessionConfiguration *, id, NSOperationQueue *);

static NSURLSession *CreateSession(id cls, SEL selector, NSURLSessionConfiguration *configuration,
                                  id delegate, NSOperationQueue *queue) {
    return nativeSession(cls, selector, SHDWCurlTransportConfiguration(configuration), delegate, queue);
}

static BOOL WebKitDelegate(id delegate) {
    if (!delegate) return NO;
    NSString *name = NSStringFromClass([delegate class]);
    return ([@[@"WKNetworkSessionDelegate", @"WKURLSessionTaskDelegate"] containsObject:name] &&
        [[NSBundle bundleForClass:[delegate class]].bundleIdentifier isEqual:@"com.apple.WebKit"]);
}

typedef struct { IMP original; SEL selector; } RequestHook;

static BOOL InstallRequests(Class cls, SEL selector, BOOL completion) {
    unsigned count = 0;
    Method *methods = class_copyMethodList(cls, &count);
    BOOL declares = NO;
    for (unsigned index = 0; index < count; index++)
        if (sel_isEqual(method_getName(methods[index]), selector)) { declares = YES; break; }
    free(methods);
    if (!declares) return NO;
    RequestHook *hook = calloc(1, sizeof(*hook));
    if (!hook) return NO;
    hook->selector = selector;
    id block;
    if (completion) block = ^id(NSURLSession *session, NSURLRequest *request, void (^callback)(NSData *, NSURLResponse *, NSError *)) {
        if (WebKitDelegate(session.delegate)) request = SHDWCurlTransportWebKitRequest(request, session);
        NSURLSessionDataTask *task = ((id (*)(id, SEL, id, id))hook->original)(session, hook->selector, request, callback);
        SHDWCurlTransportAttachTask(request, task);
        return task;
    };
    else block = ^id(NSURLSession *session, NSURLRequest *request) {
        if (WebKitDelegate(session.delegate)) request = SHDWCurlTransportWebKitRequest(request, session);
        NSURLSessionDataTask *task = ((id (*)(id, SEL, id))hook->original)(session, hook->selector, request);
        SHDWCurlTransportAttachTask(request, task);
        return task;
    };
    IMP replacement = imp_implementationWithBlock(block);
    return [sessionHooks hookMessageInClass:cls withSelector:selector withReplacement:(void *)replacement outOldPtr:(void **)&hook->original];
}

BOOL SHDWNetworkingInstall(NSDictionary *snapshot) {
    if (!SHDWTransportProfileIsSupported(snapshot[@"Profile"]) || ![snapshot[@"Owner"] length]) return NO;
    @synchronized(NSURLSession.class) {
        if (processSnapshot) return installSucceeded && [processSnapshot isEqual:snapshot];
        SHDWCurlTransportPrepareProfile(snapshot[@"Profile"]);
        if (!SHDWCurlTransportReady()) return NO;
        processSnapshot = [snapshot copy];
        sessionHooks = [SHDWHookSession new];
        BOOL constructorReady = [sessionHooks hookMessageInClass:object_getClass(NSURLSession.class)
            withSelector:@selector(sessionWithConfiguration:delegate:delegateQueue:)
            withReplacement:(void *)&CreateSession outOldPtr:(void **)&nativeSession];
        if (!constructorReady || !nativeSession) return NO;
        unsigned count = 0;
        unsigned installed = 0;
        Class *classes = objc_copyClassList(&count);
        for (unsigned index = 0; index < count; index++) {
            Class cls = classes[index], parent = cls;
            while (parent && parent != NSURLSession.class) parent = class_getSuperclass(parent);
            if (!parent) continue;
            installed += InstallRequests(cls, @selector(dataTaskWithRequest:), NO);
            installed += InstallRequests(cls, @selector(dataTaskWithRequest:completionHandler:), YES);
        }
        free(classes);
        installSucceeded = installed > 0;
        return installSucceeded;
    }
}

void SHDWRebindJournalNote(const char *name, void *replacement, void **original) {
    (void)name; (void)replacement; (void)original;
}
