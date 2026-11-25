#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef void (^SHDWBackupProgress)(NSDictionary *event);
typedef void (^SHDWBackupCompletion)(id _Nullable result, NSError * _Nullable error);
@interface SHDWBackupService : NSObject
@property(atomic, readonly) BOOL running;
- (instancetype)initWithBundleIdentifier:(NSString *)bundleIdentifier;
- (void)loadCatalog:(void (^)(NSArray * _Nullable items, NSError * _Nullable error))completion;
- (void)loadCatalogWithIdentity:(void (^)(NSDictionary * _Nullable catalog, NSError * _Nullable error))completion;
- (void)loadCatalogForSearch:(NSString *)search region:(nullable NSString *)region offset:(NSUInteger)offset refresh:(BOOL)refresh ascending:(BOOL)ascending
                  completion:(void (^)(NSDictionary * _Nullable page, NSError * _Nullable error))completion;
- (void)setDeleteLocked:(BOOL)locked forIDFV:(NSString *)idfv completion:(SHDWBackupCompletion)completion;
- (void)performAction:(NSString *)action request:(NSDictionary *)request
             progress:(nullable SHDWBackupProgress)progress completion:(SHDWBackupCompletion)completion;
@end
NS_ASSUME_NONNULL_END
