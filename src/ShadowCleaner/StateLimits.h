#import <Foundation/Foundation.h>

#ifndef SHDW_STATE_LIMITS_H
#define SHDW_STATE_LIMITS_H

static NSUInteger const StatePayloadLimit = 16 * 1024 * 1024;
static NSUInteger const StateFrameLimit = 17 * 1024 * 1024;
static NSUInteger const StateEncodedOutputLimit = 24 * 1024 * 1024;

static inline NSData *StatePayloadData(id value) {
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    return data && data.length <= StatePayloadLimit ? data : nil;
}
static inline NSData *StateRequestData(NSDictionary *request) {
    for (NSString *key in @[@"records", @"preferences", @"fingerprint"]) if (request[key] && !StatePayloadData(request[key])) return nil;
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:request format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    return data && data.length <= StateFrameLimit ? data : nil;
}

#endif
