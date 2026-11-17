#pragma once
#import <CoreFoundation/CoreFoundation.h>
#import <Foundation/Foundation.h>
#include <math.h>

static const NSUInteger SHDWAppStateCatalogPageSize = 100;
static const NSUInteger SHDWAppStateCatalogMaximumPageSize = 200;

static inline NSArray<NSString *> *SHDWAppStateCatalogQueryKeys(void) {
  return @[ @"search", @"region", @"offset", @"limit", @"refresh", @"dateOrder" ];
}

// Wire keys and boolean encoding are shared by Manager, SDK and storage.
static inline NSDictionary *
SHDWAppStateCatalogQuery(NSString *search, NSString *region, NSUInteger offset,
                         NSUInteger limit, BOOL refresh) {
  NSMutableDictionary *query = [@{
    @"search" : search ?: @"",
    @"offset" : @(offset),
    @"limit" : @(limit),
    @"refresh" : refresh ? @YES : @NO
  } mutableCopy];
  if (region)
    query[@"region"] = region;
  return query;
}
static inline NSString *SHDWAppStateCatalogQueryError(id query) {
  if (![query isKindOfClass:NSDictionary.class])
    return @"Invalid backup query.";
  NSArray *keys = SHDWAppStateCatalogQueryKeys();
  for (id key in query)
    if (![keys containsObject:key])
      return @"Unknown backup query option.";
  for (NSString *key in @[ @"search", @"region" ]) {
    id value = query[key];
    if (value &&
        (![value isKindOfClass:NSString.class] || [value length] > 1000))
      return @"Invalid backup search text.";
  }
  for (NSString *key in @[ @"offset", @"limit" ]) {
    id value = query[key];
    if (value &&
        (![value isKindOfClass:NSNumber.class] ||
         CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID() ||
         !isfinite([value doubleValue]) ||
         [value compare:@(NSIntegerMax)] == NSOrderedDescending ||
         [value doubleValue] != [value longLongValue] ||
         [value longLongValue] < 0 ||
         ([key isEqual:@"limit"] &&(
             [value longLongValue] < 1 ||
             [value longLongValue] >
                 (long long)SHDWAppStateCatalogMaximumPageSize))))
      return @"Invalid backup page bounds.";
  }
  id dateOrder = query[@"dateOrder"];
  if (dateOrder && ![@[@"asc", @"desc"] containsObject:dateOrder])
    return @"Invalid backup date order.";
  id refresh = query[@"refresh"];
  if (refresh &&
      (![refresh isKindOfClass:NSNumber.class] ||
       CFGetTypeID((__bridge CFTypeRef)refresh) != CFBooleanGetTypeID()))
    return @"Invalid backup refresh option.";
  return nil;
}
