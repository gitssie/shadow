#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef void (^SHDWAppStateClientProgress)(NSDictionary *event);
// Synchronous transport; invoke on a worker queue. Progress uses the calling queue.
// The installed Shadow helper owns all storage and device operations.
@interface SHDWAppStateClient : NSObject
@property(nonatomic) NSTimeInterval timeout;
- (instancetype)initWithHelperPath:(NSString *)helperPath;
- (nullable id)invokeAction:(NSString *)action bundleIdentifier:(NSString *)bundleIdentifier
                   request:(NSDictionary *)request progress:(nullable SHDWAppStateClientProgress)progress
                     error:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
