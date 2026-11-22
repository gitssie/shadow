#pragma once
#import <Foundation/Foundation.h>

// On success, write major/minor/patch (missing patch is zero), each saturated
// at 1000. Invalid input leaves the optional three-element output unchanged.
static inline BOOL SHDWFingerprintParseSystemVersion(id value, NSUInteger *components) {
    if (![value isKindOfClass:NSString.class] || ![value length] || [value length] > 32) return NO;
    NSArray<NSString *> *parts = [value componentsSeparatedByString:@"."];
    if (parts.count < 2 || parts.count > 3) return NO;
    NSUInteger parsed[3] = {0};
    for (NSUInteger index = 0; index < parts.count; index++) {
        NSString *part = parts[index];
        if (!part.length) return NO;
        for (NSUInteger offset = 0; offset < part.length; offset++) {
            unichar digit = [part characterAtIndex:offset];
            if (digit < '0' || digit > '9') return NO;
            parsed[index] = MIN((NSUInteger)1000, parsed[index] * 10 + digit - '0');
        }
    }
    if (components) for (NSUInteger index = 0; index < 3; index++) components[index] = parsed[index];
    return YES;
}
