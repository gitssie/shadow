#import <Foundation/Foundation.h>
@interface SHDWLoadedImageRegistry : NSObject
- (instancetype)initWithSystemRoot:(NSString *)root;
- (BOOL)registerHeader:(const void *)header path:(const char *)path
       allowCandidate:(BOOL (^)(const char *))allowCandidate;
- (BOOL)unregisterHeader:(const void *)header;
- (const char *)canonicalPath:(const char *)path;
@end
