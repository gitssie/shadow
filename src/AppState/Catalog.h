#pragma once
#import <Foundation/Foundation.h>
#include <stdint.h>

// One projection shared by legacy helper catalogs and the SQLite index.
static inline NSMutableDictionary *
SHDWAppStateCatalogEntry(NSDictionary *manifest, NSError **error) {
  NSMutableDictionary *entry = [NSMutableDictionary new];
  for (NSString *key in @[
         @"idfv", @"title", @"note", @"date", @"version", @"build", @"digest",
         @"owner", @"restorePending", @"recoverySource", @"resetPending",
         @"finalizationPending", @"unavailable", @"error", @"status"
       ])
    if (manifest[key])
      entry[key] = manifest[key];
  id deleteLocked = manifest[@"deleteLocked"];
  if (deleteLocked && CFGetTypeID((__bridge CFTypeRef)deleteLocked) != CFBooleanGetTypeID()) {
    if (error)
      *error = [NSError errorWithDomain:@"me.jjolano.shadow.app-state" code:1
                              userInfo:@{NSLocalizedDescriptionKey : @"Invalid backup deletion lock"}];
    return nil;
  }
  entry[@"deleteLocked"] = deleteLocked ?: @NO;
  if ([manifest[@"unavailable"] boolValue]) {
    entry[@"size"] = @0;
    return entry;
  }
  NSNumber *dataSize = manifest[@"archiveInfo"][@"archiveSize"],
           *stateSize = manifest[@"stateArchiveInfo"][@"archiveSize"] ?: @0;
  if (![dataSize isKindOfClass:NSNumber.class] ||
      ![stateSize isKindOfClass:NSNumber.class] ||
      ![dataSize isEqual:@(dataSize.unsignedLongLongValue)] ||
      ![stateSize isEqual:@(stateSize.unsignedLongLongValue)] ||
      dataSize.unsignedLongLongValue >
          UINT64_MAX - stateSize.unsignedLongLongValue) {
    if (error)
      *error = [NSError
          errorWithDomain:@"me.jjolano.shadow.app-state"
                     code:1
                 userInfo:@{
                   NSLocalizedDescriptionKey : @"Invalid backup archive size"
                 }];
    return nil;
  }
  entry[@"size"] =
      @(dataSize.unsignedLongLongValue + stateSize.unsignedLongLongValue);
  return entry;
}
