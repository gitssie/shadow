#!/usr/bin/env python3
"""Run production IDFA and ATT hooks through the native Objective-C runtime."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
hook = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintAdvertising.x").read_text()
hook = "\n".join(line for line in hook.splitlines() if not line.startswith("#import"))
source = r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <Shadow/FingerprintAdvertising.h>
#include <assert.h>
#include <dispatch/dispatch.h>
static BOOL enabled=YES, reject;
static unsigned depth, nativeCalls, nativeRequests;
static NSUInteger nativeStatus;
static NSString *mode=@"perApp";
static NSString *saved=@"22222222-2222-4222-8222-222222222222";
static NSUUID *nativeUUID;
static id currentManager;
static BOOL shdw_fingerprint_is_enabled(void) { return enabled; }
@interface Shadow:NSObject
+ (BOOL)shdwIsInternalRead;
@end
@implementation Shadow
+ (BOOL)shdwIsInternalRead { errno=EINTR;return depth!=0; }
@end
static void Leave(BOOL *active) { (void)active;depth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(Leave)))=(++depth,YES);active;active=NO)
static NSDictionary *SHDWFingerprintConfig(NSString *bundle) {
    assert(depth && [bundle isEqual:@"advertising.fixture"]);
    return mode ? @{@"Advertising":@{@"Mode":mode}} : @{};
}
static NSDictionary *SHDWFingerprintData(NSString *bundle) {
    assert(depth && [bundle isEqual:@"advertising.fixture"]);
    return saved ? @{@"AdvertisingIdentifier":saved} : @{};
}
@interface SHDWHookSession:NSObject
@property(strong) NSMutableArray *pending;
@property NSUInteger attempts;
- (BOOL)performWhenTargetAvailable:(BOOL (^)(SHDWHookSession *))attempt;
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original;
- (void)drain;
@end
@implementation SHDWHookSession
- (instancetype)init { if((self=[super init])) _pending=[NSMutableArray new];return self; }
- (BOOL)performWhenTargetAvailable:(BOOL (^)(SHDWHookSession *))attempt {
    BOOL done=attempt(self);if(!done)[self.pending addObject:[attempt copy]];return done;
}
- (void)drain { for(BOOL (^attempt)(SHDWHookSession *) in self.pending.copy) if(attempt(self))[self.pending removeObjectIdenticalTo:attempt]; }
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original {
    self.attempts++;if(reject){*original=NULL;return NO;}
    Method method=class_getInstanceMethod(cls,selector);assert(method);
    *original=(void *)method_getImplementation(method);
    if(!class_addMethod(cls,selector,(IMP)replacement,method_getTypeEncoding(method)))
        method_setImplementation(class_getInstanceMethod(cls,selector),(IMP)replacement);
    return YES;
}
@end
''' + hook + r'''
static id NativeIdentifier(id self,SEL selector){(void)self;(void)selector;nativeCalls++;errno=EIO;return nativeUUID;}
static BOOL NativeTracking(id self,SEL selector){(void)self;(void)selector;errno=EBUSY;return nativeStatus==3;}
static id NativeShared(id self,SEL selector){(void)self;(void)selector;errno=ERANGE;return currentManager;}
static NSUInteger NativeStatus(id self,SEL selector){(void)self;(void)selector;errno=EIO;return nativeStatus;}
static void NativeRequest(id self,SEL selector,void (^completion)(NSUInteger)) {
    (void)self;(void)selector;nativeRequests++;if(completion)completion(nativeStatus);errno=EBUSY;
}
static Class RegisterManager(const char *name,Class parent,BOOL override) {
    Class cls=objc_allocateClassPair(parent,name,0);assert(cls);
    if(override) {
        assert(class_addMethod(cls,sel_registerName("advertisingIdentifier"),(IMP)NativeIdentifier,"@@:"));
        assert(class_addMethod(cls,sel_registerName("isAdvertisingTrackingEnabled"),(IMP)NativeTracking,@encode(BOOL)[0]=='B'?"B@:":"c@:"));
    }
    objc_registerClassPair(cls);return cls;
}
static Class RegisterBase(void) {
    Class cls=RegisterManager("ASIdentifierManager",NSObject.class,YES);
    assert(class_addMethod(object_getClass(cls),sel_registerName("sharedManager"),(IMP)NativeShared,"@@:"));return cls;
}
static Class RegisterATT(void) {
    Class cls=objc_allocateClassPair(NSObject.class,"ATTrackingManager",0);assert(cls);
    NSString *encoding=[NSString stringWithFormat:@"%s@:",@encode(NSUInteger)];
    assert(class_addMethod(object_getClass(cls),sel_registerName("trackingAuthorizationStatus"),(IMP)NativeStatus,encoding.UTF8String));
    assert(class_addMethod(object_getClass(cls),sel_registerName("requestTrackingAuthorizationWithCompletionHandler:"),(IMP)NativeRequest,"v@:@?"));
    objc_registerClassPair(cls);return cls;
}
static id Shared(Class cls){return ((id (*)(id,SEL))objc_msgSend)(cls,sel_registerName("sharedManager"));}
static NSUUID *Read(id object){return ((id (*)(id,SEL))objc_msgSend)(object,sel_registerName("advertisingIdentifier"));}
static BOOL Tracking(id object){return ((BOOL (*)(id,SEL))objc_msgSend)(object,sel_registerName("isAdvertisingTrackingEnabled"));}
static NSUInteger Status(Class cls){return ((NSUInteger (*)(id,SEL))objc_msgSend)(cls,sel_registerName("trackingAuthorizationStatus"));}
static void Request(Class cls,void (^callback)(NSUInteger)){((void (*)(id,SEL,id))objc_msgSend)(cls,sel_registerName("requestTrackingAuthorizationWithCompletionHandler:"),callback);}
static void VerifyUUID(id object,NSString *expected) {
    NSUUID *uuid=Read(object);assert([uuid.UUIDString isEqual:expected]);
    uuid_t actual,wanted;[uuid getUUIDBytes:actual];[[[NSUUID alloc]initWithUUIDString:expected] getUUIDBytes:wanted];assert(!memcmp(actual,wanted,16));
}
void AdvertisingSwiftSetup(void) {
    SHDWHookSession *session=[SHDWHookSession new];
    nativeUUID=[[NSUUID alloc]initWithUUIDString:@"11111111-1111-4111-8111-111111111111"];
    Class base=RegisterBase();currentManager=[base new];RegisterATT();
    shdw_universal_fingerprint_advertising(session,@"advertising.fixture");
}
NSUUID *AdvertisingFixtureUUID(void){return Read(currentManager);}
int main(int argc,const char *argv[]) { @autoreleasepool {
    reject=argc>1 && !strcmp(argv[1],"reject");
    nativeUUID=[[NSUUID alloc]initWithUUIDString:@"11111111-1111-4111-8111-111111111111"];
    SHDWHookSession *session=[SHDWHookSession new];
    enabled=NO;shdw_universal_fingerprint_advertising(session,@"advertising.fixture");assert(!session.pending.count);
    enabled=YES;shdw_universal_fingerprint_advertising(session,@"advertising.fixture");assert(session.pending.count==3);
    Class base=RegisterBase();Class middle=RegisterManager("AdvertisingMiddle",base,YES);Class concrete=RegisterManager("AdvertisingConcrete",middle,NO);
    currentManager=[concrete new];[session drain];assert(session.pending.count==2);
    if(!reject) VerifyUUID(Shared(base),saved);
    Class att=objc_allocateClassPair(NSObject.class,"ATTrackingManager",0);assert(att);objc_registerClassPair(att);
    [session drain];assert(session.pending.count==2);
    NSString *statusEncoding=[NSString stringWithFormat:@"%s@:",@encode(NSUInteger)];
    assert(class_addMethod(object_getClass(att),sel_registerName("trackingAuthorizationStatus"),(IMP)NativeStatus,statusEncoding.UTF8String));
    [session drain];assert(session.pending.count==1);
    NSUInteger statusAttempts=session.attempts;
    [session drain];assert(session.attempts==statusAttempts);
    assert(class_addMethod(object_getClass(att),sel_registerName("requestTrackingAuthorizationWithCompletionHandler:"),(IMP)NativeRequest,"v@:@?"));
    [session drain];assert(!session.pending.count);
    NSUInteger attempts=session.attempts;
    [session drain];shdw_universal_fingerprint_advertising(session,@"advertising.fixture");assert(session.attempts==attempts);
    if(reject){assert(Read(currentManager)==nativeUUID && Status(att)==nativeStatus);puts("advertising: clean refusal remains native");return 0;}
    for(NSString *selected in @[@"perApp",@"zero",@"system"]) {
        mode=selected;
        for(NSUInteger status=0;status<4;status++) {
            nativeStatus=status;
            NSString *expected=[mode isEqual:@"perApp"]?saved:[mode isEqual:@"zero"]?@"00000000-0000-0000-0000-000000000000":nativeUUID.UUIDString;
            VerifyUUID([base new],expected);VerifyUUID(Shared(base),expected);
            errno=EDOM;assert(Status(att)==([mode isEqual:@"perApp"]?3:[mode isEqual:@"zero"]?2:status));
            assert(errno==([mode isEqual:@"system"]?EIO:EDOM));
            assert(Tracking(currentManager)==([mode isEqual:@"system"]?status==3:[mode isEqual:@"perApp"]));
        }
    }
    mode=@"perApp";nativeStatus=0;enabled=NO;assert(Read(currentManager)==nativeUUID && Status(att)==0);enabled=YES;
    depth++;assert(Read(currentManager)==nativeUUID && Status(att)==0 && !Tracking(currentManager));depth--;
    nativeUUID=[[NSUUID alloc]initWithUUIDString:@"00000000-0000-0000-0000-000000000000"];VerifyUUID(currentManager,saved);
    nativeUUID=nil;VerifyUUID(currentManager,saved);
    saved=@"bad";VerifyUUID(currentManager,@"00000000-0000-0000-0000-000000000000");saved=@"22222222-2222-4222-8222-222222222222";
    Class late=RegisterManager("AdvertisingLate",base,YES);currentManager=[late new];VerifyUUID(Shared(base),saved);
    NSInvocation *call=[NSInvocation invocationWithMethodSignature:[currentManager methodSignatureForSelector:sel_registerName("advertisingIdentifier")]];
    call.target=currentManager;call.selector=sel_registerName("advertisingIdentifier");[call invoke];__unsafe_unretained NSUUID *invoked=nil;[call getReturnValue:&invoked];assert([invoked.UUIDString isEqual:saved]);
    mode=@"system";nativeStatus=1;__block NSUInteger seen=99;Request(att,^(NSUInteger value){seen=value;});assert(seen==1 && nativeRequests==1);
    depth++;Request(att,^(NSUInteger value){seen=value;});depth--;assert(nativeRequests==2);
    __block unsigned callbacks=0;
    mode=@"perApp";Request(att,^(NSUInteger value){assert(value==3);callbacks++;});
    mode=@"zero";Request(att,^(NSUInteger value){assert(value==2);callbacks++;});
    assert(!callbacks && nativeRequests==2);
    dispatch_async(dispatch_get_main_queue(),^{assert(callbacks==2 && !depth);puts("advertising runtime: config IDFA/ATT/legacy/request callbacks, UUID bytes, late/concrete/inherited classes, native/internal/refusal and errno passed");exit(0);});
} dispatch_main(); }
'''
with tempfile.TemporaryDirectory(prefix="shadow-advertising-runtime-") as directory:
    temporary=Path(directory)
    test,binary=temporary/"test.m",temporary/"test"
    test.write_text(source)
    flags=["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-fno-omit-frame-pointer","-framework","Foundation","-I",str(root/"src/Shadow.framework/Headers")]
    subprocess.run(flags+[str(test),"-o",str(binary)],check=True)
    env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0",UBSAN_OPTIONS="halt_on_error=1")
    for mode in ["normal","reject"]:
        subprocess.run([str(binary),mode],check=True,env=env,timeout=30)
    header=temporary/"Bridge.h"
    header.write_text('#import <Foundation/Foundation.h>\nvoid AdvertisingSwiftSetup(void);\nNSUUID * _Nonnull AdvertisingFixtureUUID(void);\n')
    swift=temporary/"main.swift"
    swift.write_text('import Foundation\nAdvertisingSwiftSetup()\nlet value = AdvertisingFixtureUUID() as UUID\nprecondition(value.uuidString == "22222222-2222-4222-8222-222222222222")\nprecondition(value == UUID(uuidString: "22222222-2222-4222-8222-222222222222")!)\nprint("advertising Swift UUID bridge: passed")\n')
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Dmain=AdvertisingFixtureMain","-I",str(root/"src/Shadow.framework/Headers"),"-c",str(test),"-o",str(temporary/"fixture.o")],check=True)
    subprocess.run(["xcrun","swiftc","-import-objc-header",str(header),str(swift),str(temporary/"fixture.o"),"-o",str(temporary/"swift-check")],check=True)
    subprocess.run([str(temporary/"swift-check")],check=True,timeout=30)
