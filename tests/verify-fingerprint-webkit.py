"""Exercise production UA policy and extracted WKWebView hooks with native doubles."""
from pathlib import Path
import subprocess
import re
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
policy = root / "src/ShadowCore.dylib/policy/FingerprintPolicy.m"
fingerprint = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintWebKit.x").read_text()


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


# Production keeps the native UA hooks and retains clipboard implementation dormant.
production = re.sub(r"//[^\n]*", "", fingerprint)
prepare = function(production, "void shdw_universal_fingerprint_webkit_prepare(")
assert re.findall(r"%init\(([^,]+),", prepare) == ["shadowhook_fingerprint_webkit"]
assert "shdw_fingerprint_webkit_clipboard_prepare(" not in prepare
clipboard_prepare = function(production, "static void __attribute__((unused)) shdw_fingerprint_webkit_clipboard_prepare(")
assert set(re.findall(r"%init\(([^,]+),", clipboard_prepare)) == {
    "shadowhook_fingerprint_webkit_script", "shadowhook_fingerprint_webkit_script_world",
    "shadowhook_fingerprint_webkit_clipboard_eval", "shadowhook_fingerprint_webkit_controller",
    "shadowhook_fingerprint_webkit_world",
}
assert "shdw_fingerprint_webkit_clipboard_install(" not in function(production, "static void shdw_fingerprint_webkit_apply(")
init_start = production.index("- (instancetype)initWithFrame:")
assert "shdw_fingerprint_webkit_clipboard_install(" not in function(production[init_start:], "- (instancetype)initWithFrame:")
ua_group = production[production.index("%group shadowhook_fingerprint_webkit\n"):production.index("%group shadowhook_fingerprint_webkit_clipboard_eval")]
assert "- (void)evaluateJavaScript:" not in ua_group

# Exercise preserved dormant code in doubles without enabling production injection.
fingerprint = fingerprint.replace("// if(shdw_webkit_configuration)", "if(shdw_webkit_configuration)")
fingerprint = fingerprint.replace("//     shdw_fingerprint_webkit_clipboard_install", "    shdw_fingerprint_webkit_clipboard_install")
fingerprint = fingerprint.replace("// if(applies) shdw_fingerprint_webkit_clipboard_install", "if(applies) shdw_fingerprint_webkit_clipboard_install")

prefix = r'''
#import <Foundation/Foundation.h>
NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    (void)bundleID;
    return @{@"MemoryDelta": @16384, @"ActivationTimestamp": @1700000000};
}

#import <objc/runtime.h>
#import <objc/message.h>
#include <assert.h>
static unsigned internalDepth;
static BOOL appCaller = YES, shdw_fingerprint_enabled = YES;
static char shdw_webkit_candidate_key, shdw_webkit_worlds_key, shdw_webkit_installing_key, shdw_webkit_script_world_key, shdw_webkit_policy_script_key;
static const void *fakeCaller = (void *)1;
static BOOL shdw_map_app_caller(const void *caller) {
    return caller && appCaller && !internalDepth;
}
static BOOL shdw_fingerprint_is_enabled(void) { return shdw_fingerprint_enabled; }
static BOOL shdw_fingerprint_app_caller(const void *caller) { return shdw_map_app_caller(caller); }
static void leave_scope(BOOL *active) { (void)active; assert(internalDepth); internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave_scope))) = (++internalDepth, YES); active; active = NO)
#define __builtin_return_address(n) fakeCaller
#define __builtin_extract_return_addr(c) (c)
@interface WKNavigation : NSObject @end
@implementation WKNavigation @end
static NSString *SHDWFingerprintWebClipboardScript(void) { return @"test-clipboard-script"; }
typedef NS_ENUM(NSInteger, WKUserScriptInjectionTime) { WKUserScriptInjectionTimeAtDocumentStart, WKUserScriptInjectionTimeAtDocumentEnd };
@interface WKContentWorld : NSObject
+ (instancetype)pageWorld;
@end
@implementation WKContentWorld
+ (instancetype)pageWorld { static id world; if(!world) world = [self new]; return world; }
@end
@interface WKFrameInfo : NSObject @end
@implementation WKFrameInfo @end
@interface WKUserScript : NSObject
@property(nonatomic, copy) NSString *source;
@property(nonatomic) WKUserScriptInjectionTime injectionTime;
@property(nonatomic) BOOL forMainFrameOnly;
@property(nonatomic) WKContentWorld *nativeWorld;
@property(nonatomic) unsigned worldReads;
- (WKContentWorld *)_contentWorld;
- (instancetype)initNativeWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)time forMainFrameOnly:(BOOL)mainFrame;
- (instancetype)initNativeWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)time forMainFrameOnly:(BOOL)mainFrame inContentWorld:(WKContentWorld *)world;
@end
@interface WKUserScript (Hooks)
- (instancetype)initWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)time forMainFrameOnly:(BOOL)mainFrame;
- (instancetype)initWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)time forMainFrameOnly:(BOOL)mainFrame inContentWorld:(WKContentWorld *)world;
@end
@implementation WKUserScript
- (WKContentWorld *)_contentWorld { self.worldReads++; return self.nativeWorld ?: [WKContentWorld pageWorld]; }
- (instancetype)initNativeWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)time forMainFrameOnly:(BOOL)mainFrame inContentWorld:(WKContentWorld *)world {
    assert(world); self = [self initNativeWithSource:source injectionTime:time forMainFrameOnly:mainFrame];
    self.nativeWorld = world; return self;
}
- (instancetype)initNativeWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)time forMainFrameOnly:(BOOL)mainFrame {
    assert(internalDepth);
    self = [super init]; if(self) { _source = source; _injectionTime = time; _forMainFrameOnly = mainFrame; } return self;
}
@end
@interface LegacyUserScript : WKUserScript @end
@implementation LegacyUserScript
- (BOOL)respondsToSelector:(SEL)selector {
    if(selector == sel_registerName("_contentWorld")) return NO;
    return [super respondsToSelector:selector];
}
@end
@interface WKUserContentController : NSObject
@property(nonatomic, copy) NSArray<WKUserScript *> *userScripts;
@property(nonatomic) NSObject *existingHandler;
- (void)nativeAddUserScript:(WKUserScript *)script;
- (void)nativeRemoveAllUserScripts;
@end
@interface WKUserContentController (Hooks)
- (void)addUserScript:(WKUserScript *)script;
- (void)removeAllUserScripts;
@end
@implementation WKUserContentController
- (instancetype)init { self = [super init]; if(self) { _userScripts = @[]; _existingHandler = [NSObject new]; } return self; }
- (void)nativeAddUserScript:(WKUserScript *)script { self.userScripts = [self.userScripts arrayByAddingObject:script]; }
- (void)nativeRemoveAllUserScripts { self.userScripts = @[]; }
@end
@interface WKWebViewConfiguration : NSObject
@property(nonatomic) WKUserContentController *userContentController;
@end
@implementation WKWebViewConfiguration
- (instancetype)init { self = [super init]; if(self) _userContentController = [WKUserContentController new]; return self; }
@end
@interface WKWebView : NSObject
@property(nonatomic, copy) NSString *nativeUA;
@property(nonatomic, copy) NSString *storedCustomUA;
@property(nonatomic) unsigned nativeReads;
@property(nonatomic) unsigned nativeWrites;
@property(nonatomic, copy) NSArray *navigationArguments;
@property(nonatomic, copy) NSString *navigationUA;
@property(nonatomic) WKNavigation *navigationResult;
@property(nonatomic) WKWebViewConfiguration *configuration;
@property(nonatomic) NSUInteger scriptsAtNativeInit;
@property(nonatomic) NSUInteger scriptsAtNavigation;
@property(nonatomic) NSMutableArray *evaluations;
@property(nonatomic) NSDictionary *lastArguments;
@property(nonatomic) id appResult;
@property(nonatomic) NSError *policyError;
- (void)nativeEvaluateJavaScript:(NSString *)source completionHandler:(void (^)(id, NSError *))completion;
- (void)nativeEvaluateJavaScript:(NSString *)source inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion;
- (void)nativeCallAsyncJavaScript:(NSString *)source arguments:(NSDictionary *)arguments inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion;
- (instancetype)initNativeWithFrame:(CGRect)frame configuration:(WKWebViewConfiguration *)configuration;
- (instancetype)initNativeWithCoder:(NSCoder *)coder;
- (NSString *)_userAgent;
- (void)nativeSetCustomUserAgent:(NSString *)value;
- (WKNavigation *)nativeReload;
- (WKNavigation *)nativeGoBack;
- (WKNavigation *)nativeJavaScriptNavigation;
- (WKNavigation *)nativeLoadRequest:(NSURLRequest *)request;
- (WKNavigation *)nativeLoadHTMLString:(NSString *)string baseURL:(NSURL *)baseURL;
- (WKNavigation *)nativeLoadFileURL:(NSURL *)URL allowingReadAccessToURL:(NSURL *)readAccessURL;
- (WKNavigation *)nativeLoadData:(NSData *)data MIMEType:(NSString *)MIMEType characterEncodingName:(NSString *)encoding baseURL:(NSURL *)baseURL;
@end
@interface WKWebView (Hooks)
- (void)evaluateJavaScript:(NSString *)source completionHandler:(void (^)(id, NSError *))completion;
- (void)evaluateJavaScript:(NSString *)source inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion;
- (void)callAsyncJavaScript:(NSString *)source arguments:(NSDictionary *)arguments inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion;
- (instancetype)initWithFrame:(CGRect)frame configuration:(WKWebViewConfiguration *)configuration;
- (instancetype)initWithCoder:(NSCoder *)coder;
- (void)setCustomUserAgent:(NSString *)value;
- (WKNavigation *)loadRequest:(NSURLRequest *)request;
- (WKNavigation *)loadHTMLString:(NSString *)string baseURL:(NSURL *)baseURL;
- (WKNavigation *)loadFileURL:(NSURL *)URL allowingReadAccessToURL:(NSURL *)readAccessURL;
- (WKNavigation *)loadData:(NSData *)data MIMEType:(NSString *)MIMEType characterEncodingName:(NSString *)encoding baseURL:(NSURL *)baseURL;
@end
static NSString *nativeUA = @"Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/20D47 Probe/4.2";
static BOOL initFails;
@implementation WKWebView
- (void)recordEvaluation:(NSString *)source arguments:(NSDictionary *)arguments frame:(WKFrameInfo *)frame world:(WKContentWorld *)world completion:(void (^)(id, NSError *))completion {
    assert(source);
    [self.evaluations addObject:@[source, frame ?: [NSNull null], world ?: [NSNull null]]];
    BOOL isPolicy = [source isEqualToString:SHDWFingerprintWebClipboardScript()];
    if(isPolicy) assert(!completion);
    if(!isPolicy) self.lastArguments = arguments;
    if(completion) completion(isPolicy ? nil : self.appResult, isPolicy ? self.policyError : nil);
}
- (void)nativeEvaluateJavaScript:(NSString *)source completionHandler:(void (^)(id, NSError *))completion {
    [self recordEvaluation:source arguments:nil frame:nil world:nil completion:completion];
}
- (void)nativeEvaluateJavaScript:(NSString *)source inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion {
    [self recordEvaluation:source arguments:nil frame:frame world:world completion:completion];
}
- (void)nativeCallAsyncJavaScript:(NSString *)source arguments:(NSDictionary *)arguments inFrame:(WKFrameInfo *)frame inContentWorld:(WKContentWorld *)world completionHandler:(void (^)(id, NSError *))completion {
    [self recordEvaluation:source arguments:arguments frame:frame world:world completion:completion];
}
- (instancetype)initNativeWithFrame:(CGRect)frame configuration:(WKWebViewConfiguration *)configuration {
    (void)frame; (void)configuration;
    if(initFails) return nil;
    self = [super init];
    if(self) {
        _nativeUA = nativeUA; _navigationResult = [WKNavigation new]; _evaluations = [NSMutableArray array]; _appResult = @42;
        _configuration = configuration ?: [WKWebViewConfiguration new];
        _scriptsAtNativeInit = _configuration.userContentController.userScripts.count;
    }
    return self;
}
- (instancetype)initNativeWithCoder:(NSCoder *)coder {
    (void)coder;
    return [self initNativeWithFrame:(CGRect){0} configuration:nil];
}
- (NSString *)_userAgent {
    assert(internalDepth);
    self.nativeReads++;
    return self.storedCustomUA.length ? self.storedCustomUA : self.nativeUA;
}
- (void)nativeSetCustomUserAgent:(NSString *)value {
    self.nativeWrites++;
    self.storedCustomUA = value;
}
- (WKNavigation *)recordNavigation:(NSArray *)arguments {
    self.scriptsAtNavigation = self.configuration.userContentController.userScripts.count;
    self.navigationArguments = arguments;
    self.navigationUA = self.storedCustomUA.length ? self.storedCustomUA : self.nativeUA;
    return self.navigationResult;
}
- (WKNavigation *)nativeReload { return [self recordNavigation:@[@"reload"]]; }
- (WKNavigation *)nativeGoBack { return [self recordNavigation:@[@"history"]]; }
- (WKNavigation *)nativeJavaScriptNavigation { return [self recordNavigation:@[@"js-navigation"]]; }
- (WKNavigation *)nativeLoadRequest:(NSURLRequest *)request { return [self recordNavigation:@[request]]; }
- (WKNavigation *)nativeLoadHTMLString:(NSString *)string baseURL:(NSURL *)baseURL { return [self recordNavigation:@[string, baseURL]]; }
- (WKNavigation *)nativeLoadFileURL:(NSURL *)URL allowingReadAccessToURL:(NSURL *)readAccessURL { return [self recordNavigation:@[URL, readAccessURL]]; }
- (WKNavigation *)nativeLoadData:(NSData *)data MIMEType:(NSString *)MIMEType characterEncodingName:(NSString *)encoding baseURL:(NSURL *)baseURL {
    return [self recordNavigation:@[data, MIMEType, encoding, baseURL]];
}
@end
static void (*shdw_webkit_evaluate)(id, SEL, NSString *, void (^)(id, NSError *));
static void (*shdw_webkit_evaluate_world)(id, SEL, NSString *, WKFrameInfo *, WKContentWorld *, void (^)(id, NSError *));
static void (*shdw_webkit_remove_scripts)(id, SEL);
static void (*shdw_webkit_add_script)(id, SEL, WKUserScript *);
static id (*shdw_webkit_configuration)(id, SEL);
static NSString *(*shdw_webkit_user_agent)(id, SEL);
static void (*shdw_webkit_set_user_agent)(id, SEL, NSString *);
@interface SubclassWebView : WKWebView
@property(nonatomic) unsigned overrideWrites;
@end
@implementation SubclassWebView
- (void)setCustomUserAgent:(NSString *)value { self.overrideWrites++; [super setCustomUserAgent:value]; }
- (NSString *)_userAgent { assert(!"must use base native getter"); return nil; }
- (WKWebViewConfiguration *)configuration { assert(!"must use base configuration getter"); return nil; }
@end
'''

suffix = r'''
static NSString *mapped(NSString *input) {
    return [input stringByReplacingOccurrencesOfString:@"OS 16_3 like" withString:@"OS 18_7_1 like"];
}
static void verify_policy(void) {
    assert(!SHDWFingerprintUserAgent(nil));
    for(NSString *unchanged in @[@"", @"Probe/4.2", @"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
        @"Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/143.0", @"CPU iPhone OS nope like Mac OS X",
        @"CPU iPhone OS 16_3 other Mac OS X", @"CPU iPhone OS 16_ like Mac OS X",
        @"CPU OS 16__3 like Mac OS X", @"CPU OS 16_3_2_1 like Mac OS X", @"CPU iPhone OS 16_3 like Mac OS XX"]) {
        assert(SHDWFingerprintUserAgent(unchanged) == unchanged);
    }
    NSString *version = [SHDWFingerprintOSVersionString() stringByReplacingOccurrencesOfString:@"." withString:@"_"];
    for(NSString *device in @[@"iPhone; CPU iPhone OS", @"iPad; CPU OS", @"iPod touch; CPU iPhone OS"])
        for(NSString *oldVersion in @[@"16", @"16_3", @"16_3_2"])
            for(NSString *tail in @[@"AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/20D47",
                @"AppleWebKit/616.1.27 Version/16.3 Mobile/20D47 Safari/604.1 Probe/4.2 Extra/18_7_1"] ) {
                NSString *input = [NSString stringWithFormat:@"Mozilla/5.0 (%@ %@ like Mac OS X) %@", device, oldVersion, tail];
                NSString *expected = [NSString stringWithFormat:@"Mozilla/5.0 (%@ %@ like Mac OS X) %@", device, version, tail];
                NSString *output = SHDWFingerprintUserAgent(input);
                assert([output isEqualToString:expected]);
                assert(SHDWFingerprintUserAgent(output) == output);
            }
    assert([SHDWFingerprintOSVersionString() isEqualToString:@"18.7.1"]);
}
static WKWebView *newView(BOOL coder) {
    return coder ? [[WKWebView alloc] initWithCoder:nil] :
        [[WKWebView alloc] initWithFrame:(CGRect){0} configuration:[WKWebViewConfiguration new]];
}
static void verify_clipboard_install(void) {
    for(unsigned coder = 0; coder < 2; coder++) {
        WKWebView *view = newView(coder);
        WKUserContentController *controller = view.configuration.userContentController;
        assert(controller.userScripts.count == 1);
        WKUserScript *script = controller.userScripts.firstObject;
        assert([script.source isEqualToString:SHDWFingerprintWebClipboardScript()]);
        assert(script.injectionTime == WKUserScriptInjectionTimeAtDocumentStart && !script.forMainFrameOnly);
        assert(view.scriptsAtNativeInit == (coder ? 0 : 1));
        NSObject *handler = controller.existingHandler;
        shdw_fingerprint_webkit_apply(view);
        assert(controller.userScripts.count == 1 && controller.userScripts.firstObject == script);
        [controller removeAllUserScripts];
        id (*configurationGetter)(id, SEL) = shdw_webkit_configuration;
        shdw_webkit_configuration = NULL;
        shdw_fingerprint_webkit_apply(view); assert(controller.userScripts.count == 1);
        shdw_webkit_configuration = configurationGetter;
        NSString *(*getter)(id, SEL) = shdw_webkit_user_agent; shdw_webkit_user_agent = NULL;
        shdw_fingerprint_webkit_apply(view);
        shdw_webkit_user_agent = getter;
        assert(controller.userScripts.count == 1 && controller.existingHandler == handler);
        assert([controller.userScripts.firstObject.source isEqualToString:SHDWFingerprintWebClipboardScript()]);
        WKUserScript *appScript;
        SHADOW_INTERNAL_SCOPE {
            appScript = [[WKUserScript alloc] initWithSource:@"application-script" injectionTime:WKUserScriptInjectionTimeAtDocumentEnd forMainFrameOnly:YES];
        }
        controller.userScripts = @[appScript];
        shdw_fingerprint_webkit_apply(view);
        assert(controller.userScripts.count == 2 && controller.userScripts[1] == appScript);
        assert(controller.existingHandler == handler);
        shdw_fingerprint_webkit_apply(view); assert(controller.userScripts.count == 2);
        [controller removeAllUserScripts];
        [view loadHTMLString:@"hello" baseURL:[NSURL URLWithString:@"https://example.test/"]];
        assert(view.scriptsAtNavigation == 1);
    }
}
static void verify_navigation(void) {
    NSURL *url = [NSURL URLWithString:@"https://example.test/"], *file = [NSURL fileURLWithPath:@"/tmp/webkit.html"];
    NSURLRequest *request = [NSURLRequest requestWithURL:url];
    NSString *html = @"<p>hello</p>", *mime = @"text/html", *encoding = @"UTF-8";
    NSData *data = [html dataUsingEncoding:NSUTF8StringEncoding];
    NSArray *expected[] = {@[request], @[html, url], @[file, file], @[data, mime, encoding, url]};
    for(unsigned gate = 0; gate < 4; gate++) for(unsigned method = 0; method < 4; method++) {
        appCaller = NO; WKWebView *view = newView(YES); appCaller = YES;
        assert(!view.storedCustomUA && !objc_getAssociatedObject(view, &shdw_webkit_candidate_key));
        if(gate == 1) appCaller = NO;
        if(gate == 2) shdw_fingerprint_enabled = NO;
        if(gate == 3) fakeCaller = NULL;
        WKNavigation *result = nil;
        switch(method) {
            case 0: result = [view loadRequest:request]; break;
            case 1: result = [view loadHTMLString:html baseURL:url]; break;
            case 2: result = [view loadFileURL:file allowingReadAccessToURL:file]; break;
            case 3: result = [view loadData:data MIMEType:mime characterEncodingName:encoding baseURL:url]; break;
        }
        assert(view.scriptsAtNavigation == (gate ? 0 : 1));
        assert(result == view.navigationResult);
        assert([view.navigationArguments isEqualToArray:expected[method]]);
        assert([view.navigationUA isEqualToString:gate ? nativeUA : mapped(nativeUA)]);
        assert((objc_getAssociatedObject(view, &shdw_webkit_candidate_key) != nil) == !gate);
        appCaller = YES; shdw_fingerprint_enabled = YES; fakeCaller = (void *)1;
    }
    SubclassWebView *subclass = [[SubclassWebView alloc] initWithCoder:nil];
    assert(!subclass.overrideWrites && [subclass.storedCustomUA isEqualToString:mapped(nativeUA)]);
    [subclass setCustomUserAgent:nil];
    assert(subclass.overrideWrites == 1 && [subclass.storedCustomUA isEqualToString:mapped(nativeUA)]);
}
static void verify_hooks(void) {
    for(unsigned coder = 0; coder < 2; coder++) {
        WKWebView *view = newView(coder);
        assert(view && [view.storedCustomUA isEqualToString:mapped(nativeUA)]);
        assert(view.nativeReads && view.nativeWrites);
        assert(objc_getAssociatedObject(view, &shdw_webkit_candidate_key));
        NSString *custom = @"Mozilla/5.0 (iPad; CPU OS 16_3 like Mac OS X) AppleWebKit/605.1.15 Version/16.3 Safari/604.1 App/7";
        [view setCustomUserAgent:custom];
        assert([view.storedCustomUA isEqualToString:mapped(custom)]);
        NSString *unrelated = @"MyApp/1.0 desktop-client";
        [view setCustomUserAgent:unrelated]; assert([view.storedCustomUA isEqualToString:unrelated]);
        [view setCustomUserAgent:nil]; assert([view.storedCustomUA isEqualToString:mapped(nativeUA)]);
        [view setCustomUserAgent:@""]; assert([view.storedCustomUA isEqualToString:mapped(nativeUA)]);
        appCaller = NO;
        [view setCustomUserAgent:custom];
        assert([view.storedCustomUA isEqualToString:mapped(custom)]);
        appCaller = YES;
        shdw_fingerprint_enabled = NO;
        [view setCustomUserAgent:custom]; assert([view.storedCustomUA isEqualToString:custom]);
        shdw_fingerprint_enabled = YES;
        [view setCustomUserAgent:nil];
        unsigned writes = view.nativeWrites;
        shdw_fingerprint_webkit_apply(view); assert(view.nativeWrites == writes);
        NSString *(*getter)(id, SEL) = shdw_webkit_user_agent;
        void (*setter)(id, SEL, NSString *) = shdw_webkit_set_user_agent;
        unsigned reads = view.nativeReads;
        shdw_webkit_user_agent = NULL;
        shdw_fingerprint_webkit_apply(view); assert(view.nativeReads == reads);
        shdw_webkit_user_agent = getter; shdw_webkit_set_user_agent = NULL;
        shdw_fingerprint_webkit_apply(view); assert(view.nativeReads == reads);
        shdw_webkit_set_user_agent = setter;
        assert(!internalDepth);
    }
    for(unsigned gate = 0; gate < 3; gate++) {
        if(gate == 0) appCaller = NO;
        if(gate == 1) shdw_fingerprint_enabled = NO;
        if(gate == 2) fakeCaller = NULL;
        for(unsigned coder = 0; coder < 2; coder++) {
            WKWebView *view = newView(coder);
            assert(!view.configuration.userContentController.userScripts.count);
            assert(!view.storedCustomUA && !view.nativeReads && !view.nativeWrites);
            assert(!objc_getAssociatedObject(view, &shdw_webkit_candidate_key));
            [view setCustomUserAgent:nativeUA]; assert([view.storedCustomUA isEqualToString:nativeUA]);
        }
        appCaller = YES; shdw_fingerprint_enabled = YES; fakeCaller = (void *)1;
    }
    NSString *savedNative = nativeUA;
    for(NSString *unrelated in @[@"Desktop App/9", @""]) {
        nativeUA = unrelated;
        WKWebView *view = newView(NO);
        assert(!view.storedCustomUA && view.nativeReads == 1 && !view.nativeWrites);
    }
    nativeUA = nil;
    WKWebView *view = newView(NO);
    assert(!view.storedCustomUA && view.nativeReads == 1 && !view.nativeWrites);
    nativeUA = savedNative;
    initFails = YES; assert(!newView(NO) && !newView(YES)); initFails = NO;
    assert(!internalDepth);
}
static void verify_script_order(void) {
    LegacyUserScript *legacy;
    SHADOW_INTERNAL_SCOPE {
        legacy = [[LegacyUserScript alloc] initNativeWithSource:@"legacy" injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO];
    }
    assert(!shdw_fingerprint_webkit_script_world(legacy) && !legacy.worldReads);
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    WKUserContentController *controller = configuration.userContentController;
    WKContentWorld *world = [WKContentWorld new], *lateWorld = [WKContentWorld new];
    WKUserScript *page, *isolated, *end, *late;
    SHADOW_INTERNAL_SCOPE {
        page = [[WKUserScript alloc] initWithSource:@"capture page clipboard" injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO];
        isolated = [[WKUserScript alloc] initNativeWithSource:@"capture isolated clipboard" injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO inContentWorld:world];
        end = [[WKUserScript alloc] initWithSource:@"application end script" injectionTime:WKUserScriptInjectionTimeAtDocumentEnd forMainFrameOnly:YES];
        late = [[WKUserScript alloc] initWithSource:@"capture late isolated clipboard" injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO inContentWorld:lateWorld];
    }
    assert(!objc_getAssociatedObject(isolated, &shdw_webkit_script_world_key));
    assert(objc_getAssociatedObject(late, &shdw_webkit_script_world_key) == lateWorld);
    [controller addUserScript:page]; [controller addUserScript:isolated]; [controller addUserScript:end];
    assert(controller.userScripts.count == 3);
    NSObject *handler = controller.existingHandler;
    WKWebView *view = [[WKWebView alloc] initWithFrame:(CGRect){0} configuration:configuration];
    NSArray *first = controller.userScripts;
    assert(first.count == 5 && first[2] == page && first[3] == isolated && first[4] == end);
    assert(isolated.worldReads == 1 && !page.worldReads && !late.worldReads);
    assert(objc_getAssociatedObject(first[0], &shdw_webkit_policy_script_key));
    assert(objc_getAssociatedObject(first[1], &shdw_webkit_script_world_key) == world);
    shdw_fingerprint_webkit_apply(view);
    assert([controller.userScripts isEqualToArray:first] && controller.existingHandler == handler);
    [controller addUserScript:late];
    NSArray *last = controller.userScripts;
    assert(last.count == 7 && last[3] == page && last[4] == isolated && last[5] == end && last[6] == late);
    assert(objc_getAssociatedObject(last[2], &shdw_webkit_script_world_key) == lateWorld);
    shdw_fingerprint_webkit_apply(view);
    assert([controller.userScripts isEqualToArray:last] && controller.existingHandler == handler);
    [controller removeAllUserScripts];
    assert(controller.userScripts.count == 3 && controller.existingHandler == handler);
    for(WKUserScript *script in controller.userScripts)
        assert(objc_getAssociatedObject(script, &shdw_webkit_policy_script_key));
}
static void verify_worlds(void) {
    WKWebViewConfiguration *shared = [WKWebViewConfiguration new];
    WKWebView *view = [[WKWebView alloc] initWithFrame:(CGRect){0} configuration:shared];
    WKWebView *other = [[WKWebView alloc] initWithFrame:(CGRect){0} configuration:shared];
    WKContentWorld *world = [WKContentWorld new], *secondWorld = [WKContentWorld new];
    WKFrameInfo *frame = [WKFrameInfo new];
    NSString *source = @"'use strict';\nthis === undefined", *body = @"'use strict';\nreturn amount + 1";
    NSDictionary *arguments = @{@"amount": @41};
    NSObject *handler = shared.userContentController.existingHandler;
    __block unsigned completions = 0;
    void (^completion)(id, NSError *) = ^(id value, NSError *error) {
        assert([value isEqual:@42] && !error); completions++;
    };
    [view evaluateJavaScript:source completionHandler:completion];
    assert(completions == 1 && view.evaluations.count == 2);
    assert([view.evaluations[0][0] isEqual:SHDWFingerprintWebClipboardScript()]);
    assert([view.evaluations[1][0] isEqual:source]);
    [view evaluateJavaScript:source inFrame:frame inContentWorld:world completionHandler:completion];
    assert(completions == 2 && view.evaluations.count == 4);
    for(unsigned index = 2; index < 4; index++) {
        assert(view.evaluations[index][1] == frame && view.evaluations[index][2] == world);
    }
    assert(shared.userContentController.userScripts.count == 2);
    [view evaluateJavaScript:source inFrame:frame inContentWorld:world completionHandler:nil];
    assert(shared.userContentController.userScripts.count == 2);
    view.policyError = [NSError errorWithDomain:@"test" code:1 userInfo:nil];
    [view callAsyncJavaScript:body arguments:arguments inFrame:frame inContentWorld:secondWorld completionHandler:completion];
    assert(completions == 3 && [view.lastArguments isEqual:arguments]);
    assert([view.evaluations.lastObject[0] isEqual:body] && view.evaluations.lastObject[2] == secondWorld);
    assert(shared.userContentController.userScripts.count == 3);
    [other evaluateJavaScript:source inFrame:nil inContentWorld:[WKContentWorld pageWorld] completionHandler:nil];
    assert(shared.userContentController.userScripts.count == 3);
    for(unsigned route = 0; route < 3; route++) {
        [shared.userContentController removeAllUserScripts];
        assert(shared.userContentController.userScripts.count == 3);
        switch(route) {
            case 0: [view nativeReload]; break;
            case 1: [view nativeGoBack]; break;
            case 2: [view nativeJavaScriptNavigation]; break;
        }
        assert(view.scriptsAtNavigation == 3);
        assert(shared.userContentController.existingHandler == handler);
    }
    appCaller = NO;
    WKWebView *unselectedView = newView(NO);
    [unselectedView evaluateJavaScript:source inFrame:frame inContentWorld:world completionHandler:completion];
    assert(unselectedView.evaluations.count == 1 && !unselectedView.configuration.userContentController.userScripts.count);
    appCaller = YES;
    WKWebView *independent = newView(NO);
    assert(independent.configuration.userContentController.userScripts.count == 1);
    [shared.userContentController removeAllUserScripts];
    assert(independent.configuration.userContentController.userScripts.count == 1);
    WKUserContentController *unselected = [WKUserContentController new];
    [unselected removeAllUserScripts]; assert(!unselected.userScripts.count);
    shdw_fingerprint_enabled = NO;
    [shared.userContentController removeAllUserScripts]; assert(!shared.userContentController.userScripts.count);
    [view evaluateJavaScript:source inFrame:frame inContentWorld:world completionHandler:completion];
    assert([view.evaluations.lastObject[0] isEqual:source]);
    assert(!shared.userContentController.userScripts.count);
    shdw_fingerprint_enabled = YES;
    assert(!internalDepth);
}
int main(void) { @autoreleasepool {
    shdw_webkit_remove_scripts = (void (*)(id, SEL))class_getMethodImplementation([WKUserContentController class], @selector(nativeRemoveAllUserScripts));
    shdw_webkit_add_script = (void (*)(id, SEL, WKUserScript *))class_getMethodImplementation([WKUserContentController class], @selector(nativeAddUserScript:));
    shdw_webkit_configuration = (id (*)(id, SEL))class_getMethodImplementation([WKWebView class], @selector(configuration));
    shdw_webkit_user_agent = (NSString *(*)(id, SEL))class_getMethodImplementation([WKWebView class], @selector(_userAgent));
    shdw_webkit_set_user_agent = (void (*)(id, SEL, NSString *))class_getMethodImplementation([WKWebView class], @selector(nativeSetCustomUserAgent:));
    shdw_webkit_evaluate = (void (*)(id, SEL, NSString *, void (^)(id, NSError *)))class_getMethodImplementation([WKWebView class], @selector(nativeEvaluateJavaScript:completionHandler:));
    shdw_webkit_evaluate_world = (void (*)(id, SEL, NSString *, WKFrameInfo *, WKContentWorld *, void (^)(id, NSError *)))class_getMethodImplementation([WKWebView class], @selector(nativeEvaluateJavaScript:inFrame:inContentWorld:completionHandler:));
    verify_policy(); verify_hooks(); verify_navigation(); verify_clipboard_install(); verify_worlds(); verify_script_order();
    puts("fingerprint WebKit: native UA active, injection calls disabled, dormant clipboard tests passed");
} }
'''

# Compile the production helpers and Logos bodies without linking WebKit.
helper = "\n".join(function(fingerprint, signature) for signature in (
    "static id shdw_fingerprint_webkit_world(",
    "static id shdw_fingerprint_webkit_script_world(",
    "static void shdw_fingerprint_webkit_controller_install(",
    "static void __attribute__((unused)) shdw_fingerprint_webkit_clipboard_install(",
    "static void shdw_fingerprint_webkit_apply(",
    "static void shdw_fingerprint_webkit_select(",
    "static void shdw_fingerprint_webkit_register_world(",
))
if "--without-policy-ordering" in sys.argv:
    helper = helper.replace("[ordered addObjectsFromArray:appScripts];", "[ordered insertObjects:appScripts atIndexes:[NSIndexSet indexSetWithIndexesInRange:NSMakeRange(0, appScripts.count)]];")
if "--without-clipboard-install" in sys.argv:
    original = function(helper, "static void __attribute__((unused)) shdw_fingerprint_webkit_clipboard_install(")
    helper = helper.replace(original, "static void __attribute__((unused)) shdw_fingerprint_webkit_clipboard_install(WKWebViewConfiguration *configuration) { (void)configuration; }")
if "--without-navigation-selection" in sys.argv:
    original = function(helper, "static void shdw_fingerprint_webkit_select(")
    helper = helper.replace(original, "static void shdw_fingerprint_webkit_select(WKWebView *view, const void *caller) { (void)view; (void)caller; }")
if "--with-dynamic-ua-dispatch" in sys.argv:
    helper = helper.replace("shdw_webkit_user_agent(view, @selector(_userAgent))", "[view _userAgent]")
start = fingerprint.index("%group shadowhook_fingerprint_webkit")
start = fingerprint.index("%hook WKWebView", start) + len("%hook WKWebView")
body = fingerprint[start:fingerprint.index("%end", start)]
eval_start = fingerprint.index("%group shadowhook_fingerprint_webkit_clipboard_eval")
eval_start = fingerprint.index("%hook WKWebView", eval_start) + len("%hook WKWebView")
body += fingerprint[eval_start:fingerprint.index("%end", eval_start)]
replacements = {
    "initWithFrame:": ("%orig(frame, configuration)", "[self initNativeWithFrame:frame configuration:configuration]"),
    "initWithCoder:": ("%orig(coder)", "[self initNativeWithCoder:coder]"),
    "setCustomUserAgent:": ("%orig(adjusted)", "[self nativeSetCustomUserAgent:adjusted]"),
    "loadRequest:": ("%orig(request)", "[self nativeLoadRequest:request]"),
    "loadHTMLString:": ("%orig(string, baseURL)", "[self nativeLoadHTMLString:string baseURL:baseURL]"),
    "loadFileURL:": ("%orig(URL, readAccessURL)", "[self nativeLoadFileURL:URL allowingReadAccessToURL:readAccessURL]"),
    "evaluateJavaScript:": ("%orig(javaScriptString, completionHandler)", "[self nativeEvaluateJavaScript:javaScriptString completionHandler:completionHandler]"),
    "loadData:": ("%orig(data, MIMEType, characterEncodingName, baseURL)", "[self nativeLoadData:data MIMEType:MIMEType characterEncodingName:characterEncodingName baseURL:baseURL]"),
}
methods = ""
for selector, (original, replacement) in replacements.items():
    signature = next(line for line in body.splitlines() if line.startswith("- (") and selector in line)
    method = function(body, signature)
    method = method.replace(original, replacement)
    method = method.replace("%orig(appSource, completionHandler)", "[self nativeEvaluateJavaScript:appSource completionHandler:completionHandler]")
    assert "%orig" not in method
    methods += method + "\n"
world_start = fingerprint.index("%group shadowhook_fingerprint_webkit_world")
world_body = fingerprint[world_start:]
for selector in ("evaluateJavaScript:", "callAsyncJavaScript:"):
    signature = next(line for line in world_body.splitlines() if line.startswith("- (") and selector in line)
    method = function(world_body, signature)
    method = method.replace("%orig(javaScriptString, frame, contentWorld, completionHandler)", "[self nativeEvaluateJavaScript:javaScriptString inFrame:frame inContentWorld:contentWorld completionHandler:completionHandler]")
    method = method.replace("%orig(appSource, frame, contentWorld, completionHandler)", "[self nativeEvaluateJavaScript:appSource inFrame:frame inContentWorld:contentWorld completionHandler:completionHandler]")
    method = method.replace("%orig(functionBody, arguments, frame, contentWorld, completionHandler)", "[self nativeCallAsyncJavaScript:functionBody arguments:arguments inFrame:frame inContentWorld:contentWorld completionHandler:completionHandler]")
    method = method.replace("%orig(appSource, appArguments, frame, contentWorld, completionHandler)", "[self nativeCallAsyncJavaScript:appSource arguments:appArguments inFrame:frame inContentWorld:contentWorld completionHandler:completionHandler]")
    assert "%orig" not in method
    methods += method + "\n"
controller_body = fingerprint[fingerprint.index("%group shadowhook_fingerprint_webkit_controller"):]
controller_method = function(controller_body, "- (void)removeAllUserScripts").replace("%orig;", "[self nativeRemoveAllUserScripts];")
controller_add = function(controller_body, "- (void)addUserScript:").replace("%orig(script)", "[self nativeAddUserScript:script]")
if "--without-late-world-registration" in sys.argv:
    controller_add = controller_add.replace("id world = shdw_fingerprint_webkit_script_world(script);", "id world = nil;")
controller_implementation = "\n@implementation WKUserContentController (Hooks)\n" + controller_method + controller_add + "\n@end\n"
for name in ("shadowhook_fingerprint_webkit_script", "shadowhook_fingerprint_webkit_script_world"):
    script_body = fingerprint[fingerprint.index("%group " + name + "\n"):]
    method = function(script_body, "- (instancetype)initWithSource:")
    method = method.replace("%orig(source, injectionTime, mainFrameOnly, contentWorld)", "[self initNativeWithSource:source injectionTime:injectionTime forMainFrameOnly:mainFrameOnly inContentWorld:contentWorld]")
    method = method.replace("%orig(source, injectionTime, mainFrameOnly)", "[self initNativeWithSource:source injectionTime:injectionTime forMainFrameOnly:mainFrameOnly]")
    assert "%orig" not in method
    controller_implementation += "\n@implementation WKUserScript (" + name + ")\n" + method + "\n@end\n"
policy_source = policy.read_text()
if "--without-ua-rewrite" in sys.argv:
    original = function(policy_source, "NSString *SHDWFingerprintUserAgent(")
    policy_source = policy_source.replace(original, "NSString *SHDWFingerprintUserAgent(NSString *userAgent) { return userAgent; }")
with tempfile.TemporaryDirectory(prefix="shadow-fingerprint-webkit-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + policy_source + "\n" + helper + "\n@implementation WKWebView (Hooks)\n" + methods + "\n@end\n" + controller_implementation + suffix)
    subprocess.run([
        "xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(policy.parent),
        str(src), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)
