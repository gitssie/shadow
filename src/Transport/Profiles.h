#pragma once
#import <Foundation/Foundation.h>

static inline BOOL SHDWTransportProfileIsSupported(id profile) {
    return [@[@"safari172_ios", @"safari180_ios", @"safari184_ios", @"impit465"] containsObject:profile ?: NSNull.null];
}
