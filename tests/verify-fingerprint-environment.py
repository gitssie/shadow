"""Execute production environment hooks with native Objective-C runtime fixtures."""
from pathlib import Path
import subprocess
import struct
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
environment = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintEnvironment.x").read_text()


def body(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


integration = (root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text()
prepare_integration = body(integration, "void shdw_universal_fingerprint_prepare(")
assert prepare_integration.index("if(!shdw_fingerprint_enabled)") < prepare_integration.index(
    "shdw_universal_fingerprint_environment_prepare(hooks)")
dyld = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
for signature in ("static void* shdw_dlopen_completed(",
                  "void shdw_universal_dyld_updatelibs(", "static void shdw_bulk_load_handler("):
    callback = body(dyld, signature)
    retry = callback.index("shdw_universal_fingerprint_environment_prepare(")
    if "shdw_detector_present" in callback:
        assert retry < callback.index("shdw_detector_present")


production = environment[environment.index("static unsigned"):]
production = production.replace('objc_getClass("UIScreen")', 'fixture_get_class("FixtureScreen")')
production = production.replace('objc_getClass("UIDevice")', 'fixture_get_class("FixtureDevice")')
production = production.replace("object_getClass(NSProcessInfo.processInfo)", 'fixture_get_class("FixtureProcessInfo")')
assert "%hook" not in environment and "%init" not in environment
assert "[hooks hookMessageInClass:cls withSelector:selector" in environment

source = r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import "FingerprintEnvironment.h"
#include <assert.h>
#include <math.h>
#include <stdlib.h>
typedef NS_ENUM(NSInteger, UIDeviceBatteryState) {
    UIDeviceBatteryStateUnknown, UIDeviceBatteryStateUnplugged,
    UIDeviceBatteryStateCharging, UIDeviceBatteryStateFull
};
@interface SHDWHookSession : NSObject
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector
    withReplacement:(void *)replacement outOldPtr:(void **)original;
@end
static BOOL enabled, appCaller=YES;
static unsigned internalDepth, installations, nativeCalls;
static const void *fakeCaller=(void *)1;
static uint32_t brightnessDraw, batteryDraw;
static unsigned randomCalls;
static uint32_t test_random_uniform(uint32_t bound) {
    unsigned call=__atomic_fetch_add(&randomCalls,1,__ATOMIC_RELAXED);
    assert(call<2);
    assert(bound == (call==0 ? 450001 : 81));
    return call==0 ? brightnessDraw : batteryDraw;
}
#define arc4random_uniform test_random_uniform
#define __builtin_return_address(n) fakeCaller
#define __builtin_extract_return_addr(c) (c)
static BOOL shdw_fingerprint_is_enabled(void) { return enabled; }
static BOOL shdw_fingerprint_app_caller(const void *caller) {
    assert(caller==fakeCaller);
    return enabled && appCaller && !internalDepth;
}
static SHDWHookSession *currentSession;
static SHDWHookSession *SHDWHookSessionSetCurrent(SHDWHookSession *session) {
    SHDWHookSession *previous=currentSession; currentSession=session; return previous;
}
static CGFloat value_brightness(id self,SEL cmd) { (void)self;(void)cmd; nativeCalls++;return 0.99; }
static float value_batteryLevel(id self,SEL cmd) { (void)self;(void)cmd; nativeCalls++;return -1; }
static UIDeviceBatteryState value_batteryState(id self,SEL cmd) { (void)self;(void)cmd; nativeCalls++;return UIDeviceBatteryStateFull; }
static BOOL value_isLowPowerModeEnabled(id self,SEL cmd) { (void)self;(void)cmd; nativeCalls++;return YES; }
static NSProcessInfoThermalState value_thermalState(id self,SEL cmd) { (void)self;(void)cmd; nativeCalls++;return NSProcessInfoThermalStateCritical; }
static Class register_class(const char *name) {
    Class cls=objc_allocateClassPair(NSObject.class,name,0);assert(cls);
    objc_registerClassPair(cls);return cls;
}
static void add_getter(Class cls,SEL selector,IMP implementation,const char *resultType) {
    char encoding[16];snprintf(encoding,sizeof encoding,"%s@:",resultType);
    assert(class_addMethod(cls,selector,implementation,encoding));
}
static SEL failSelector, retainedFailSelector;
static unsigned failuresRemaining, refused, registryWrites, attempts;
static dispatch_block_t pendingBlock;
static unsigned enqueues, classLookups;
static BOOL delivering, directInstallation, loadScreenOnInstall;
static Class lateScreenClass;
void shdw_universal_fingerprint_environment_prepare(SHDWHookSession *hooks);
static void test_dispatch_async(dispatch_queue_t queue,dispatch_block_t block) {
    assert(queue==dispatch_get_main_queue() && !pendingBlock);
    pendingBlock=[block copy];enqueues++;
}
#define dispatch_async test_dispatch_async
static void deliver_pending(void) {
    assert(pendingBlock && !delivering);
    dispatch_block_t block=pendingBlock;pendingBlock=nil;
    delivering=YES;block();delivering=NO;
}
static Class fixture_get_class(const char *name) {
    assert(delivering);classLookups++;return objc_getClass(name);
}
@implementation SHDWHookSession
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector
    withReplacement:(void *)replacement outOldPtr:(void **)original {
    assert(currentSession==self && original && !*original);
    assert(delivering || directInstallation);
    if(loadScreenOnInstall && selector==@selector(isLowPowerModeEnabled)) {
        unsigned queued=enqueues;
        lateScreenClass=register_class("FixtureScreen");
        add_getter(lateScreenClass,@selector(brightness),(IMP)value_brightness,@encode(CGFloat));
        loadScreenOnInstall=NO;
        shdw_universal_fingerprint_environment_prepare(self);
        shdw_universal_fingerprint_environment_prepare(self);
        assert(enqueues==queued && installations==0);
    }
    attempts++;
    if(selector==failSelector && failuresRemaining) {failuresRemaining--;refused++;return NO;}
    Method method=class_getInstanceMethod(cls,selector);assert(method);
    *original=(void *)method_getImplementation(method);
    if(selector==retainedFailSelector) return NO;
    class_replaceMethod(cls,selector,(IMP)replacement,method_getTypeEncoding(method));
    registryWrites++;installations++;return YES;
}
@end
''' + production + r'''
static CGFloat brightness(id object) {return ((CGFloat(*)(id,SEL))objc_msgSend)(object,@selector(brightness));}
static float battery(id object) {return ((float(*)(id,SEL))objc_msgSend)(object,@selector(batteryLevel));}
static NSInteger state(id object) {return ((NSInteger(*)(id,SEL))objc_msgSend)(object,@selector(batteryState));}
static BOOL lowPower(id object) {return ((BOOL(*)(id,SEL))objc_msgSend)(object,@selector(isLowPowerModeEnabled));}
static NSInteger thermal(id object) {return ((NSInteger(*)(id,SEL))objc_msgSend)(object,@selector(thermalState));}
static void verify_native(id screen,id device,id process) {
    unsigned before=nativeCalls;
    assert(fabs(brightness(screen)-0.99)<1e-8);
    assert(battery(device)==-1 && state(device)==UIDeviceBatteryStateFull);
    assert(lowPower(process)==YES && thermal(process)==NSProcessInfoThermalStateCritical);
    assert(nativeCalls==before+5);
}
int main(int argc,char **argv) {@autoreleasepool {
    assert(argc==3);brightnessDraw=(uint32_t)strtoul(argv[1],NULL,10);batteryDraw=(uint32_t)strtoul(argv[2],NULL,10);
    for(unsigned b=0;b<450001;b++) {
        unsigned p=b%81;
        SHDWFingerprintEnvironment sample=SHDWFingerprintEnvironmentSample(b,p);
        assert(sample.brightness==(350000u+b)/1000000.0f && sample.batteryPercent==10+p);
        assert(sample.brightness>=0.35f && sample.brightness<=0.80f);
        assert(SHDWFingerprintEnvironmentLowPower(sample)==(p<20));
    }
    SHDWFingerprintEnvironment precise=SHDWFingerprintEnvironmentSample(271947,19);
    assert(precise.brightness==0.621947f);
    assert(fabs((double)precise.brightness*100-round((double)precise.brightness*100))>0.001);
    char wireBrightness[16];snprintf(wireBrightness,sizeof wireBrightness,"%.2f",(double)precise.brightness);
    assert(!strcmp(wireBrightness,"0.62") && fabs((double)precise.brightness-0.62)>0.001);
    assert(SHDWFingerprintEnvironmentLowPower((SHDWFingerprintEnvironment){0.5f,29}));
    assert(!SHDWFingerprintEnvironmentLowPower((SHDWFingerprintEnvironment){0.5f,30}));
    Class processBase=register_class("FixtureProcessInfoBase");
    Class processClass=objc_allocateClassPair(processBase,"FixtureProcessInfo",0);assert(processClass);
    objc_registerClassPair(processClass);
    add_getter(processBase,@selector(isLowPowerModeEnabled),(IMP)value_isLowPowerModeEnabled,@encode(BOOL));
    SHDWHookSession *session=[SHDWHookSession new],*previous=[SHDWHookSession new];currentSession=previous;
    shdw_universal_fingerprint_environment_prepare(session);
    assert(installations==0 && currentSession==previous && !pendingBlock && !enqueues);
    enabled=YES;
    shdw_universal_fingerprint_environment_prepare(nil);assert(installations==0 && !pendingBlock);
    shdw_universal_fingerprint_environment_prepare(session);
    assert(installations==0 && pendingBlock && enqueues==1 && classLookups==0);
    shdw_universal_fingerprint_environment_prepare(session);
    assert(installations==0 && enqueues==1 && classLookups==0);
    enabled=NO;deliver_pending();
    assert(installations==0 && shdw_environment_scheduled==0 && classLookups==0);
    enabled=YES;
    shdw_universal_fingerprint_environment_prepare(session);
    assert(installations==0 && enqueues==2 && classLookups==0);
    loadScreenOnInstall=YES;
    deliver_pending();
    assert(installations==1 && currentSession==previous && pendingBlock && shdw_environment_scheduled==1);
    assert(lateScreenClass && shdw_environment_brightness_state==0 && !shdw_environment_native_brightness);
    unsigned afterDirtyPass=enqueues;
    deliver_pending();
    assert(installations==2 && !pendingBlock && shdw_environment_scheduled==0 && enqueues==afterDirtyPass);
    assert(shdw_environment_brightness_state==2 && shdw_environment_requested==0);
    add_getter(processBase,@selector(thermalState),(IMP)value_thermalState,@encode(NSProcessInfoThermalState));
    Class screenClass=lateScreenClass,deviceClass=register_class("FixtureDevice");
    add_getter(deviceClass,@selector(batteryLevel),(IMP)value_batteryLevel,@encode(float));
    failSelector=@selector(batteryLevel);failuresRemaining=1;
    shdw_universal_fingerprint_environment_prepare(session);
    assert(installations==2 && pendingBlock);
    deliver_pending();assert(installations==3 && refused==1 && !pendingBlock && shdw_environment_scheduled==0);
    assert(shdw_environment_brightness_state==2 && shdw_environment_native_brightness);
    assert(shdw_environment_batteryLevel_state==0 && !shdw_environment_native_batteryLevel);
    assert(shdw_environment_batteryState_state==0);
    add_getter(deviceClass,@selector(batteryState),(IMP)value_batteryState,@encode(UIDeviceBatteryState));
    shdw_universal_fingerprint_environment_prepare(session);assert(installations==3 && pendingBlock);
    deliver_pending();assert(installations==5 && !pendingBlock && shdw_environment_scheduled==0);
    unsigned completeEnqueues=enqueues;
    shdw_universal_fingerprint_environment_prepare(session);
    assert(installations==5 && currentSession==previous && !pendingBlock && enqueues==completeEnqueues);
    assert(randomCalls==0 && registryWrites==5);
    assert(shdw_environment_brightness_state==2 && shdw_environment_batteryLevel_state==2);
    assert(shdw_environment_batteryState_state==2 && shdw_environment_isLowPowerModeEnabled_state==2);
    assert(shdw_environment_thermalState_state==2);
    Class failureClass=register_class("FixtureRetainedFailure");
    retainedFailSelector=NSSelectorFromString(@"retainedFailure");
    add_getter(failureClass,retainedFailSelector,(IMP)value_isLowPowerModeEnabled,@encode(BOOL));
    IMP failedOriginal=NULL;
    unsigned failedState=0,beforeAttempts=attempts;
    SHDWHookSessionSetCurrent(session);directInstallation=YES;
    shdw_environment_install(session,failureClass,retainedFailSelector,@encode(BOOL),
        (IMP)shdw_environment_isLowPowerModeEnabled,&failedOriginal,&failedState);
    assert(failedState==3 && failedOriginal==(IMP)value_isLowPowerModeEnabled);
    assert(attempts==beforeAttempts+1 && registryWrites==5 && installations==5);
    assert(class_getMethodImplementation(failureClass,retainedFailSelector)==failedOriginal);
    shdw_environment_install(session,failureClass,retainedFailSelector,@encode(BOOL),
        (IMP)shdw_environment_isLowPowerModeEnabled,&failedOriginal,&failedState);
    assert(failedState==3 && attempts==beforeAttempts+1 && registryWrites==5);
    SHDWHookSessionSetCurrent(previous);directInstallation=NO;
    id base=[processBase new];
    assert(((BOOL(*)(id,SEL))objc_msgSend)(base,@selector(isLowPowerModeEnabled))==YES);
    assert(((NSInteger(*)(id,SEL))objc_msgSend)(base,@selector(thermalState))==NSProcessInfoThermalStateCritical);
    nativeCalls=0;
    assert(!shdw_environment_has_getter(screenClass,@selector(brightness),@encode(float)));
    id screen=[screenClass new],device=[deviceClass new],process=[processClass new];
    SHDWFingerprintEnvironment expected=SHDWFingerprintEnvironmentSample(brightnessDraw,batteryDraw);
    dispatch_apply(256,dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^(size_t index){
        (void)index;
        @autoreleasepool {
            assert(brightness(screen)==(CGFloat)expected.brightness);
            assert(fabsf(battery(device)-expected.batteryPercent/100.0f)<1e-6f);
            assert(state(device)==UIDeviceBatteryStateUnplugged);
            assert(lowPower(process)==(expected.batteryPercent<30));
            assert(thermal(process)==NSProcessInfoThermalStateNominal);
        }
    });
    assert(randomCalls==2 && nativeCalls==0);
    appCaller=NO;verify_native(screen,device,process);appCaller=YES;
    internalDepth=1;verify_native(screen,device,process);internalDepth=0;
    enabled=NO;verify_native(screen,device,process);enabled=YES;
    assert(randomCalls==2);
    printf("%.9g %u\n",(double)expected.brightness,expected.batteryPercent);
}}
'''

with tempfile.TemporaryDirectory(prefix="shadow-environment-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(source)
    subprocess.run([
        "xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation",
        "-I", str(root / "src/ShadowCore.dylib/policy"), str(src), "-o", str(binary),
    ], check=True)
    for draws in [(0, 0), (450000, 80), (271947, 19), (271948, 20), (0xFFFFFFFF, 0xFFFFFFFF)]:
        result = subprocess.check_output([str(binary), *(str(value) for value in draws)], text=True)
        brightness = struct.unpack("f", struct.pack("f", (350000 + draws[0] % 450001) / 1000000))[0]
        expected = f"{brightness:.9g} {10 + draws[1] % 81}"
        assert result.strip() == expected

print("fingerprint environment: float32 brightness precision/ranges, 29/30 threshold, concurrent process snapshot, native scope, inherited methods, clean refusal retry, retained-failure terminal state, deferred coalescing, dirty reentrant availability, disabled delivery and late classes passed")
