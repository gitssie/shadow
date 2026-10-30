#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef void (^SHDWAppStateClientProgress)(NSDictionary *event);
// Synchronous transport; invoke on a worker queue. Progress uses the calling queue.
// The installed Shadow helper owns all storage and device operations.
// Errors preserve errorCode (stable machine string), sourceDomain/sourceCode,
// optional posixCode, helperDetails, stateMayBePartial and outcomeUnknown.
// NSUnderlyingErrorKey reconstructs the source NSError and optional POSIX cause.
// Consumers must classify errorCode, never the localized description.
@interface SHDWAppStateClient : NSObject
@property(nonatomic) NSTimeInterval timeout;
- (instancetype)initWithHelperPath:(NSString *)helperPath;
- (nullable id)invokeAction:(NSString *)action bundleIdentifier:(NSString *)bundleIdentifier
                   request:(NSDictionary *)request progress:(nullable SHDWAppStateClientProgress)progress
                     error:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
