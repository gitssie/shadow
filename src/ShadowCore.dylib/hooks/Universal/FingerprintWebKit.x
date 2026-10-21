#import "UniversalHooks.h"
#import <WebKit/WebKit.h>
#import <objc/message.h>
#import "../../policy/FingerprintPolicy.h"

static unsigned shdw_webkit_install_state;
static char shdw_webkit_candidate_key, shdw_webkit_worlds_key, shdw_webkit_installing_key, shdw_webkit_script_world_key, shdw_webkit_policy_script_key;
static NSString *(*shdw_webkit_user_agent)(id, SEL);
static void (*shdw_webkit_set_user_agent)(id, SEL, NSString *);
static void (*shdw_webkit_remove_scripts)(id, SEL);
static void (*shdw_webkit_add_script)(id, SEL, WKUserScript *);
static id (*shdw_webkit_configuration)(id, SEL);
static void (*shdw_webkit_evaluate)(id, SEL, NSString *, void (^)(id, NSError *));
static void (*shdw_webkit_evaluate_world)(id, SEL, NSString *, WKFrameInfo *, WKContentWorld *, void (^)(id, NSError *));

%group shadowhook_fingerprint_webkit
@protocol SHDWFingerprintWebView <NSObject>
- (NSString *)_userAgent;
@end

static id shdw_fingerprint_webkit_world(id world) {
    if(!world) return [NSNull null];
    Class worldClass = objc_getClass("WKContentWorld");
    if([worldClass respondsToSelector:@selector(pageWorld)] &&
       world == [worldClass pageWorld]) return [NSNull null];
    return world;
}

static id shdw_fingerprint_webkit_script_world(WKUserScript *script) {
    id world = objc_getAssociatedObject(script, &shdw_webkit_script_world_key);
    if(world) return world;
    SEL selector = sel_registerName("_contentWorld");
    if([script respondsToSelector:selector]) {
        world = ((id (*)(id, SEL))objc_msgSend)(script, selector);
        if(world) {
            world = shdw_fingerprint_webkit_world(world);
            objc_setAssociatedObject(script, &shdw_webkit_script_world_key, world, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        }
    }
    return world;
}

static void shdw_fingerprint_webkit_controller_install(WKUserContentController *controller, id world) {
    if(!controller || !shdw_fingerprint_is_enabled() || !shdw_webkit_remove_scripts || !shdw_webkit_add_script) return;
    SHADOW_INTERNAL_SCOPE {
        NSMutableArray *worlds = objc_getAssociatedObject(controller, &shdw_webkit_worlds_key);
        if(!worlds) {
            worlds = [NSMutableArray array];
            objc_setAssociatedObject(controller, &shdw_webkit_worlds_key, worlds, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        }
        world = shdw_fingerprint_webkit_world(world);
        if(![worlds containsObject:world]) [worlds addObject:world];
        if(objc_getAssociatedObject(controller, &shdw_webkit_installing_key)) return;
        objc_setAssociatedObject(controller, &shdw_webkit_installing_key, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        @try {
            Class scriptClass = objc_getClass("WKUserScript");
            if(!scriptClass) return;
            NSString *source = SHDWFingerprintWebClipboardScript();
            NSArray *existing = [controller.userScripts copy];
            NSMutableArray *appScripts = [NSMutableArray array];
            for(WKUserScript *script in existing) {
                if(objc_getAssociatedObject(script, &shdw_webkit_policy_script_key)) continue;
                [appScripts addObject:script];
                if(script.injectionTime == WKUserScriptInjectionTimeAtDocumentStart) {
                    id scriptWorld = shdw_fingerprint_webkit_world(shdw_fingerprint_webkit_script_world(script));
                    if(![worlds containsObject:scriptWorld]) [worlds addObject:scriptWorld];
                }
            }
            NSMutableArray *ordered = [NSMutableArray array];
            for(id item in [worlds copy]) {
                WKUserScript *policy = nil;
                for(WKUserScript *candidate in existing) {
                    if(objc_getAssociatedObject(candidate, &shdw_webkit_policy_script_key) &&
                       [candidate.source isEqualToString:source] &&
                       shdw_fingerprint_webkit_world(objc_getAssociatedObject(candidate, &shdw_webkit_script_world_key)) == item) {
                        policy = candidate;
                        break;
                    }
                }
                if(!policy) {
                    if(item == [NSNull null]) {
                        policy = [[scriptClass alloc] initWithSource:source
                            injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO];
                    } else if([scriptClass instancesRespondToSelector:@selector(initWithSource:injectionTime:forMainFrameOnly:inContentWorld:)]) {
                        policy = [[scriptClass alloc] initWithSource:source
                            injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO inContentWorld:item];
                    }
                    if(policy) {
                        objc_setAssociatedObject(policy, &shdw_webkit_script_world_key, item, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
                        objc_setAssociatedObject(policy, &shdw_webkit_policy_script_key, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
                    }
                }
                if(policy) [ordered addObject:policy];
            }
            [ordered addObjectsFromArray:appScripts];
            if(![existing isEqualToArray:ordered]) {
                shdw_webkit_remove_scripts(controller, @selector(removeAllUserScripts));
                for(WKUserScript *script in ordered)
                    shdw_webkit_add_script(controller, @selector(addUserScript:), script);
            }
        } @finally {
            objc_setAssociatedObject(controller, &shdw_webkit_installing_key, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        }
    }
}

static void __attribute__((unused)) shdw_fingerprint_webkit_clipboard_install(WKWebViewConfiguration *configuration) {
    if(configuration) shdw_fingerprint_webkit_controller_install(configuration.userContentController, nil);
}

static void shdw_fingerprint_webkit_apply(WKWebView *view) {
    if(!view || !shdw_fingerprint_is_enabled() || !objc_getAssociatedObject(view, &shdw_webkit_candidate_key)) return;
    SHADOW_INTERNAL_SCOPE {
        // if(shdw_webkit_configuration)
        //     shdw_fingerprint_webkit_clipboard_install(shdw_webkit_configuration(view, @selector(configuration)));
        if(!shdw_webkit_user_agent || !shdw_webkit_set_user_agent) return;
        NSString *native = shdw_webkit_user_agent(view, @selector(_userAgent));
        NSString *adjusted = SHDWFingerprintUserAgent(native);
        if(adjusted && ![adjusted isEqualToString:native])
            shdw_webkit_set_user_agent(view, @selector(setCustomUserAgent:), adjusted);
    }
}

static void shdw_fingerprint_webkit_select(WKWebView *view, const void *caller) {
    if(!view || !shdw_fingerprint_is_enabled() || !shdw_fingerprint_app_caller(caller)) return;
    objc_setAssociatedObject(view, &shdw_webkit_candidate_key, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    shdw_fingerprint_webkit_apply(view);
}

%hook WKWebView
- (instancetype)initWithFrame:(CGRect)frame configuration:(WKWebViewConfiguration *)configuration {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_fingerprint_is_enabled() && shdw_fingerprint_app_caller(caller);
    // if(applies) shdw_fingerprint_webkit_clipboard_install(configuration);
    WKWebView *view = %orig(frame, configuration);
    if(view && applies) {
        objc_setAssociatedObject(view, &shdw_webkit_candidate_key, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        shdw_fingerprint_webkit_apply(view);
    }
    return view;
}
- (instancetype)initWithCoder:(NSCoder *)coder {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_fingerprint_is_enabled() && shdw_fingerprint_app_caller(caller);
    WKWebView *view = %orig(coder);
    if(view && applies) {
        objc_setAssociatedObject(view, &shdw_webkit_candidate_key, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        shdw_fingerprint_webkit_apply(view);
    }
    return view;
}
- (void)setCustomUserAgent:(NSString *)userAgent {
    BOOL applies = shdw_fingerprint_is_enabled() && objc_getAssociatedObject(self, &shdw_webkit_candidate_key);
    NSString *adjusted = userAgent;
    if(applies) {
        SHADOW_INTERNAL_SCOPE { adjusted = SHDWFingerprintUserAgent(userAgent); }
    }
    %orig(adjusted);
    if(applies && !userAgent.length) shdw_fingerprint_webkit_apply(self);
}
- (WKNavigation *)loadRequest:(NSURLRequest *)request {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    return %orig(request);
}
- (WKNavigation *)loadHTMLString:(NSString *)string baseURL:(NSURL *)baseURL {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    return %orig(string, baseURL);
}
- (WKNavigation *)loadFileURL:(NSURL *)URL allowingReadAccessToURL:(NSURL *)readAccessURL {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    return %orig(URL, readAccessURL);
}
- (WKNavigation *)loadData:(NSData *)data MIMEType:(NSString *)MIMEType
    characterEncodingName:(NSString *)characterEncodingName baseURL:(NSURL *)baseURL {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    return %orig(data, MIMEType, characterEncodingName, baseURL);
}
%end
%end

%group shadowhook_fingerprint_webkit_clipboard_eval
%hook WKWebView
- (void)evaluateJavaScript:(NSString *)javaScriptString completionHandler:(void (^)(id, NSError *))completionHandler {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    if(!shdw_fingerprint_is_enabled() || !objc_getAssociatedObject(self, &shdw_webkit_candidate_key) ||
       !javaScriptString || !shdw_webkit_evaluate) {
        %orig(javaScriptString, completionHandler);
        return;
    }
    NSString *policy = SHDWFingerprintWebClipboardScript();
    shdw_webkit_evaluate(self, @selector(evaluateJavaScript:completionHandler:), policy, nil);
    %orig(javaScriptString, completionHandler);
}
%end
%end


%group shadowhook_fingerprint_webkit_controller
%hook WKUserContentController
- (void)addUserScript:(WKUserScript *)script {
    if(shdw_fingerprint_is_enabled() && objc_getAssociatedObject(self, &shdw_webkit_worlds_key) &&
       !objc_getAssociatedObject(self, &shdw_webkit_installing_key) &&
       script.injectionTime == WKUserScriptInjectionTimeAtDocumentStart) {
        id world = shdw_fingerprint_webkit_script_world(script);
        shdw_fingerprint_webkit_controller_install(self, world == [NSNull null] ? nil : world);
    }
    %orig(script);
}
- (void)removeAllUserScripts {
    %orig;
    if(!shdw_fingerprint_is_enabled()) return;
    NSArray *worlds = [objc_getAssociatedObject(self, &shdw_webkit_worlds_key) copy];
    for(id world in worlds)
        shdw_fingerprint_webkit_controller_install(self, world == [NSNull null] ? nil : world);
}
%end
%end

%group shadowhook_fingerprint_webkit_script
%hook WKUserScript
- (instancetype)initWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)injectionTime forMainFrameOnly:(BOOL)mainFrameOnly {
    WKUserScript *script = %orig(source, injectionTime, mainFrameOnly);
    if(script) objc_setAssociatedObject(script, &shdw_webkit_script_world_key, [NSNull null], OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    return script;
}
%end
%end

%group shadowhook_fingerprint_webkit_script_world
%hook WKUserScript
- (instancetype)initWithSource:(NSString *)source injectionTime:(WKUserScriptInjectionTime)injectionTime forMainFrameOnly:(BOOL)mainFrameOnly inContentWorld:(WKContentWorld *)contentWorld {
    WKUserScript *script = %orig(source, injectionTime, mainFrameOnly, contentWorld);
    if(script) objc_setAssociatedObject(script, &shdw_webkit_script_world_key,
        shdw_fingerprint_webkit_world(contentWorld), OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    return script;
}
%end
%end

static void shdw_fingerprint_webkit_register_world(WKWebView *view, WKContentWorld *world) {
    if(shdw_webkit_configuration) {
        SHADOW_INTERNAL_SCOPE {
            WKWebViewConfiguration *configuration = shdw_webkit_configuration(view, @selector(configuration));
            shdw_fingerprint_webkit_controller_install(configuration.userContentController, world);
        }
    }
}

%group shadowhook_fingerprint_webkit_world
%hook WKWebView
- (void)evaluateJavaScript:(NSString *)javaScriptString inFrame:(WKFrameInfo *)frame
    inContentWorld:(WKContentWorld *)contentWorld completionHandler:(void (^)(id, NSError *))completionHandler {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    if(!shdw_fingerprint_is_enabled() || !objc_getAssociatedObject(self, &shdw_webkit_candidate_key) ||
       !javaScriptString || !contentWorld || !shdw_webkit_evaluate_world) {
        %orig(javaScriptString, frame, contentWorld, completionHandler);
        return;
    }
    shdw_fingerprint_webkit_register_world(self, contentWorld);
    NSString *policy = SHDWFingerprintWebClipboardScript();
    shdw_webkit_evaluate_world(self, @selector(evaluateJavaScript:inFrame:inContentWorld:completionHandler:),
        policy, frame, contentWorld, nil);
    %orig(javaScriptString, frame, contentWorld, completionHandler);
}
- (void)callAsyncJavaScript:(NSString *)functionBody arguments:(NSDictionary *)arguments inFrame:(WKFrameInfo *)frame
    inContentWorld:(WKContentWorld *)contentWorld completionHandler:(void (^)(id, NSError *))completionHandler {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    shdw_fingerprint_webkit_select(self, caller);
    if(!shdw_fingerprint_is_enabled() || !objc_getAssociatedObject(self, &shdw_webkit_candidate_key) ||
       !functionBody || !contentWorld || !shdw_webkit_evaluate_world) {
        %orig(functionBody, arguments, frame, contentWorld, completionHandler);
        return;
    }
    shdw_fingerprint_webkit_register_world(self, contentWorld);
    NSString *policy = SHDWFingerprintWebClipboardScript();
    shdw_webkit_evaluate_world(self, @selector(evaluateJavaScript:inFrame:inContentWorld:completionHandler:),
        policy, frame, contentWorld, nil);
    %orig(functionBody, arguments, frame, contentWorld, completionHandler);
}
%end
%end

static void __attribute__((unused)) shdw_fingerprint_webkit_clipboard_prepare(Class webViewClass, Class controllerClass, Class scriptClass) {
    %init(shadowhook_fingerprint_webkit_script, WKUserScript = scriptClass);
    if(class_getInstanceMethod(scriptClass, @selector(initWithSource:injectionTime:forMainFrameOnly:inContentWorld:))) {
        %init(shadowhook_fingerprint_webkit_script_world, WKUserScript = scriptClass);
    }
    %init(shadowhook_fingerprint_webkit_clipboard_eval, WKWebView = webViewClass);
    %init(shadowhook_fingerprint_webkit_controller, WKUserContentController = controllerClass);
    if(shdw_webkit_evaluate_world && class_getInstanceMethod(webViewClass, @selector(callAsyncJavaScript:arguments:inFrame:inContentWorld:completionHandler:))) {
        %init(shadowhook_fingerprint_webkit_world, WKWebView = webViewClass);
    }
}

void shdw_universal_fingerprint_webkit_prepare(SHDWHookSession *hooks) {
    if(!shdw_fingerprint_is_enabled() || !hooks) return;
    Class webViewClass = objc_getClass("WKWebView");
    Class controllerClass = objc_getClass("WKUserContentController");
    Class scriptClass = objc_getClass("WKUserScript");
    if(!webViewClass || !controllerClass || !scriptClass ||
       !class_getInstanceMethod(controllerClass, @selector(removeAllUserScripts)) ||
       !class_getInstanceMethod(controllerClass, @selector(addUserScript:)) ||
       !class_getInstanceMethod(webViewClass, @selector(_userAgent)) ||
       !class_getInstanceMethod(webViewClass, @selector(setCustomUserAgent:))) return;
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_webkit_install_state, &expected, 1, NO,
       __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    SHDWHookSession *previous = SHDWHookSessionSetCurrent(hooks);
    @try {
        shdw_webkit_user_agent = (NSString *(*)(id, SEL))method_getImplementation(
            class_getInstanceMethod(webViewClass, @selector(_userAgent)));
        shdw_webkit_set_user_agent = (void (*)(id, SEL, NSString *))method_getImplementation(
            class_getInstanceMethod(webViewClass, @selector(setCustomUserAgent:)));
        Method configurationMethod = class_getInstanceMethod(webViewClass, @selector(configuration));
        if(configurationMethod)
            shdw_webkit_configuration = (id (*)(id, SEL))method_getImplementation(configurationMethod);
        Method evaluateMethod = class_getInstanceMethod(webViewClass, @selector(evaluateJavaScript:completionHandler:));
        if(evaluateMethod)
            shdw_webkit_evaluate = (void (*)(id, SEL, NSString *, void (^)(id, NSError *)))method_getImplementation(evaluateMethod);
        Method worldMethod = class_getInstanceMethod(webViewClass, @selector(evaluateJavaScript:inFrame:inContentWorld:completionHandler:));
        if(worldMethod)
            shdw_webkit_evaluate_world = (void (*)(id, SEL, NSString *, WKFrameInfo *, WKContentWorld *, void (^)(id, NSError *)))method_getImplementation(worldMethod);
        shdw_webkit_remove_scripts = (void (*)(id, SEL))method_getImplementation(
            class_getInstanceMethod(controllerClass, @selector(removeAllUserScripts)));
        shdw_webkit_add_script = (void (*)(id, SEL, WKUserScript *))method_getImplementation(
            class_getInstanceMethod(controllerClass, @selector(addUserScript:)));
        %init(shadowhook_fingerprint_webkit, WKWebView = webViewClass);
        // shdw_fingerprint_webkit_clipboard_prepare(webViewClass, controllerClass, scriptClass);
        __atomic_store_n(&shdw_webkit_install_state, 2, __ATOMIC_RELEASE);
    } @finally {
        SHDWHookSessionSetCurrent(previous);
    }
}
