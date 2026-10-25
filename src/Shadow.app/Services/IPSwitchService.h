#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
typedef NS_ENUM(NSUInteger, SHDWIPSwitchPhase) {
    SHDWIPSwitchPhaseChecking,
    SHDWIPSwitchPhaseRequesting,
    SHDWIPSwitchPhaseWaitingForNetwork,
    SHDWIPSwitchPhaseWaitingForChange
};
typedef NS_ENUM(NSInteger, SHDWIPSwitchError) {
    SHDWIPSwitchErrorUnconfirmed = 7
};
@interface SHDWIPSnapshot : NSObject
@property (nonatomic, copy, readonly, nullable) NSString *ip;
@property (nonatomic, copy, readonly, nullable) NSString *region;
@property (nonatomic, copy, readonly, nullable) NSString *ipv4;
@property (nonatomic, copy, readonly) NSDate *checkedAt;
- (instancetype)initWithIP:(nullable NSString *)ip region:(nullable NSString *)region
                     ipv4:(nullable NSString *)ipv4 checkedAt:(NSDate *)checkedAt;
@end
@interface SHDWIPSwitchService : NSObject
+ (instancetype)sharedService;
+ (BOOL)hasIPChangeFrom:(SHDWIPSnapshot *)before to:(SHDWIPSnapshot *)after;
@property (nonatomic, readonly, getter=isRunning) BOOL running;
- (void)startWithURL:(NSURL *)URL
           progress:(void (^ _Nullable)(SHDWIPSwitchPhase phase, SHDWIPSnapshot * _Nullable snapshot))progress
         completion:(void (^)(SHDWIPSnapshot * _Nullable before, SHDWIPSnapshot * _Nullable current, NSError * _Nullable error))completion;
- (void)queryWithProgress:(void (^ _Nullable)(SHDWIPSwitchPhase phase, SHDWIPSnapshot * _Nullable snapshot))progress
              completion:(void (^)(SHDWIPSnapshot * _Nullable snapshot, NSError * _Nullable error))completion;
- (void)cancel;
@end
NS_ASSUME_NONNULL_END
