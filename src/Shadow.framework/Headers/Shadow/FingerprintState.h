#ifndef shadow_fingerprint_state_h
#define shadow_fingerprint_state_h

#import <Foundation/Foundation.h>

static inline BOOL SHDWFingerprintApplicationIsRegistered(NSDictionary *app) {
  if (![app isKindOfClass:NSDictionary.class]) return NO;
  id managed = app[@"Fingerprint_Managed"];
  id data = app[@"Fingerprint_Data"];
  return ([managed isKindOfClass:NSNumber.class] && [managed boolValue]) ||
         ([data isKindOfClass:NSDictionary.class] && [data count] > 0);
}

static inline BOOL SHDWFingerprintApplicationEnabled(NSDictionary *app) {
  id value = [app isKindOfClass:NSDictionary.class] ? app[@"Fingerprint_Enabled"] : nil;
  return [value isKindOfClass:NSNumber.class] ? [value boolValue] : YES;
}

static inline BOOL SHDWFingerprintApplicationLocked(NSDictionary *app) {
  id value = [app isKindOfClass:NSDictionary.class] ? app[@"Fingerprint_Locked"] : nil;
  return [value isKindOfClass:NSNumber.class] ? [value boolValue] : NO;
}

#endif
