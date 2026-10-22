#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef void (^SHDWBackupProgress)(NSDictionary *event);
typedef void (^SHDWBackupCompletion)(id _Nullable result, NSError * _Nullable error);
@interface SHDWBackupService : NSObject
@property(atomic, readonly) BOOL running;
- (instancetype)initWithBundleIdentifier:(NSString *)bundleIdentifier;
- (void)loadCatalog:(void (^)(NSArray * _Nullable items, NSError * _Nullable error))completion;
- (void)performAction:(NSString *)action request:(NSDictionary *)request
             progress:(nullable SHDWBackupProgress)progress completion:(SHDWBackupCompletion)completion;
@end
NS_ASSUME_NONNULL_END
