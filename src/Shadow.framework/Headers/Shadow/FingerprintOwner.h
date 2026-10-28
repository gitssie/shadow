#ifndef shadow_fingerprint_owner_h
#define shadow_fingerprint_owner_h

#import <Foundation/Foundation.h>

static inline NSString *SHDWFingerprintOwnerForBundle(NSString *identifier,
                                              NSBundle *bundle) {
  if (!identifier.length || ![identifier isEqual:bundle.bundleIdentifier] ||
      ![bundle.infoDictionary[@"NSExtension"] isKindOfClass:NSDictionary.class]) {
    return identifier;
  }
  NSString *extensionPath =
      bundle.bundlePath.stringByStandardizingPath.stringByResolvingSymlinksInPath;
  NSString *pluginsPath = extensionPath.stringByDeletingLastPathComponent;
  NSString *appPath = pluginsPath.stringByDeletingLastPathComponent;
  if (![extensionPath.pathExtension isEqual:@"appex"] ||
      ![pluginsPath.lastPathComponent isEqual:@"PlugIns"] ||
      ![appPath.pathExtension isEqual:@"app"]) {
    return identifier;
  }
  NSBundle *owner = [NSBundle bundleWithPath:appPath];
  NSString *ownerID = owner.bundleIdentifier;
  return ownerID.length ? ownerID : identifier;
}

#endif
