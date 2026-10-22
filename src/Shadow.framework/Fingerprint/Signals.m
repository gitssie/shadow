#import "Signals.h"
#import <Shadow/FingerprintMemory.h>
#import <UIKit/UIKit.h>
#import <LocalAuthentication/LocalAuthentication.h>
#include <sys/sysctl.h>

static NSString *SHDWDecimal(CGFloat value) {
    NSString *text = @(value).stringValue;
    return [text rangeOfString:@"."].location == NSNotFound &&
           [text rangeOfString:@"e" options:NSCaseInsensitiveSearch].location == NSNotFound
        ? [text stringByAppendingString:@".0"] : text;
}

NSDictionary<NSString *, NSString *> *SHDWFingerprintInputsForData(NSDictionary *data) {
    if (![data[@"MemoryDelta"] isKindOfClass:NSNumber.class]) return nil;
    char model[256] = {0}; size_t length = sizeof(model);
    NSString *board = @"Undefined";
    if (sysctlbyname("hw.model", model, &length, NULL, 0) == 0 &&
        length > 0 && length <= sizeof(model) && model[length - 1] == '\0')
        board = [NSString stringWithUTF8String:model] ?: @"Undefined";
    uint64_t memory = 0; length = sizeof(memory);
    NSString *memorySize = @"Undefined";
    if (sysctlbyname("hw.memsize", &memory, &length, NULL, 0) == 0 && length == sizeof(memory))
        memorySize = @(SHDWFingerprintProjectedMemory(memory, [data[@"MemoryDelta"] longLongValue])).stringValue;
    LAContext *context = [LAContext new];
    BOOL canAuthenticate = [context canEvaluatePolicy:LAPolicyDeviceOwnerAuthenticationWithBiometrics error:NULL];
    NSString *biometry = @"<none>";
    if (@available(iOS 11.0, *)) {
        switch ((NSInteger)context.biometryType) {
            case 0: break;
            case 1: biometry = @"Touch ID"; break;
            case 2: biometry = @"Face ID"; break;
            case 3: biometry = @"Optic ID"; break;
            default: biometry = @"<unknown>"; break;
        }
    } else if (canAuthenticate) biometry = @"Touch ID";
    CGSize resolution = UIScreen.mainScreen.nativeBounds.size;
    return @{
        @"deviceType": UIDevice.currentDevice.model,
        @"deviceModel": board,
        @"displayResolution": [NSString stringWithFormat:@"%@x%@", SHDWDecimal(resolution.width), SHDWDecimal(resolution.height)],
        @"displayScale": SHDWDecimal(UIScreen.mainScreen.nativeScale),
        @"memorySize": memorySize,
        @"processorCount": @(NSProcessInfo.processInfo.processorCount).stringValue,
        @"biometryType": biometry
    };
}
