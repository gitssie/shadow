#import "UniversalHooks.h"
#import "../../policy/FingerprintEnvironment.h"
#import <UIKit/UIKit.h>
#include <stdlib.h>

static unsigned shdw_environment_scheduled;
static unsigned shdw_environment_requested;
static unsigned shdw_environment_brightness_state;
static CGFloat (*shdw_environment_native_brightness)(id, SEL);
static unsigned shdw_environment_batteryLevel_state;
static float (*shdw_environment_native_batteryLevel)(id, SEL);
static unsigned shdw_environment_batteryState_state;
static UIDeviceBatteryState (*shdw_environment_native_batteryState)(id, SEL);
static unsigned shdw_environment_isLowPowerModeEnabled_state;
static BOOL (*shdw_environment_native_isLowPowerModeEnabled)(id, SEL);
static unsigned shdw_environment_thermalState_state;
static NSProcessInfoThermalState (*shdw_environment_native_thermalState)(id, SEL);

static SHDWFingerprintEnvironment shdw_environment_snapshot(void) {
    static SHDWFingerprintEnvironment value;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        value = SHDWFingerprintEnvironmentSample(arc4random_uniform(450001), arc4random_uniform(81));
    });
    return value;
}

static BOOL shdw_environment_has_getter(Class cls, SEL selector, const char *type) {
    Method method = cls ? class_getInstanceMethod(cls, selector) : NULL;
    if(!method || method_getNumberOfArguments(method) != 2) return NO;
    char actual[8] = {0};
    method_getReturnType(method, actual, sizeof(actual));
    return actual[0] == type[0];
}

static CGFloat shdw_environment_brightness(id self, SEL selector) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_app_caller(caller)) return (CGFloat)shdw_environment_snapshot().brightness;
    return shdw_environment_native_brightness(self, selector);
}

static float shdw_environment_batteryLevel(id self, SEL selector) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_app_caller(caller)) return shdw_environment_snapshot().batteryPercent / 100.0f;
    return shdw_environment_native_batteryLevel(self, selector);
}

static UIDeviceBatteryState shdw_environment_batteryState(id self, SEL selector) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_app_caller(caller)) return UIDeviceBatteryStateUnplugged;
    return shdw_environment_native_batteryState(self, selector);
}

static BOOL shdw_environment_isLowPowerModeEnabled(id self, SEL selector) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_app_caller(caller)) return SHDWFingerprintEnvironmentLowPower(shdw_environment_snapshot());
    return shdw_environment_native_isLowPowerModeEnabled(self, selector);
}

static NSProcessInfoThermalState shdw_environment_thermalState(id self, SEL selector) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_app_caller(caller)) return NSProcessInfoThermalStateNominal;
    return shdw_environment_native_thermalState(self, selector);
}

static void shdw_environment_install(SHDWHookSession *hooks, Class cls, SEL selector, const char *type,
    IMP replacement, IMP *original, unsigned *state) {
    if(!shdw_environment_has_getter(cls, selector, type)) return;
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(state, &expected, 1, NO,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    BOOL installed = [hooks hookMessageInClass:cls withSelector:selector
        withReplacement:(void *)replacement outOldPtr:(void **)original];
    __atomic_store_n(state, installed ? 2 : (*original ? 3 : 0), __ATOMIC_RELEASE);
}

static void shdw_environment_install_ready(SHDWHookSession *hooks) {
    SHDWHookSession *previous = SHDWHookSessionSetCurrent(hooks);
    @try {
        Class screenClass = objc_getClass("UIScreen");
        Class deviceClass = objc_getClass("UIDevice");
        Class processClass = object_getClass(NSProcessInfo.processInfo);
        shdw_environment_install(hooks, screenClass, @selector(brightness), @encode(CGFloat),
            (IMP)shdw_environment_brightness, (IMP *)&shdw_environment_native_brightness,
            &shdw_environment_brightness_state);
        shdw_environment_install(hooks, deviceClass, @selector(batteryLevel), @encode(float),
            (IMP)shdw_environment_batteryLevel, (IMP *)&shdw_environment_native_batteryLevel,
            &shdw_environment_batteryLevel_state);
        shdw_environment_install(hooks, deviceClass, @selector(batteryState), @encode(UIDeviceBatteryState),
            (IMP)shdw_environment_batteryState, (IMP *)&shdw_environment_native_batteryState,
            &shdw_environment_batteryState_state);
        shdw_environment_install(hooks, processClass, @selector(isLowPowerModeEnabled), @encode(BOOL),
            (IMP)shdw_environment_isLowPowerModeEnabled, (IMP *)&shdw_environment_native_isLowPowerModeEnabled,
            &shdw_environment_isLowPowerModeEnabled_state);
        shdw_environment_install(hooks, processClass, @selector(thermalState), @encode(NSProcessInfoThermalState),
            (IMP)shdw_environment_thermalState, (IMP *)&shdw_environment_native_thermalState,
            &shdw_environment_thermalState_state);
    } @finally {
        SHDWHookSessionSetCurrent(previous);
    }
}

static BOOL shdw_environment_is_complete(void) {
    return __atomic_load_n(&shdw_environment_brightness_state, __ATOMIC_ACQUIRE) >= 2 &&
        __atomic_load_n(&shdw_environment_batteryLevel_state, __ATOMIC_ACQUIRE) >= 2 &&
        __atomic_load_n(&shdw_environment_batteryState_state, __ATOMIC_ACQUIRE) >= 2 &&
        __atomic_load_n(&shdw_environment_isLowPowerModeEnabled_state, __ATOMIC_ACQUIRE) >= 2 &&
        __atomic_load_n(&shdw_environment_thermalState_state, __ATOMIC_ACQUIRE) >= 2;
}

void shdw_universal_fingerprint_environment_prepare(SHDWHookSession *hooks) {
    if(!hooks || !shdw_fingerprint_is_enabled() || shdw_environment_is_complete()) return;
    __atomic_store_n(&shdw_environment_requested, 1, __ATOMIC_RELEASE);
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_environment_scheduled, &expected, 1, NO,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    dispatch_async(dispatch_get_main_queue(), ^{
        __atomic_store_n(&shdw_environment_requested, 0, __ATOMIC_RELEASE);
        @try {
            if(shdw_fingerprint_is_enabled()) shdw_environment_install_ready(hooks);
        } @finally {
            __atomic_store_n(&shdw_environment_scheduled, 0, __ATOMIC_RELEASE);
            if(__atomic_load_n(&shdw_environment_requested, __ATOMIC_ACQUIRE))
                shdw_universal_fingerprint_environment_prepare(hooks);
        }
    });
}
