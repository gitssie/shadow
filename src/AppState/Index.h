#import <Foundation/Foundation.h>
#include <sys/types.h>
NS_ASSUME_NONNULL_BEGIN
@interface SHDWAppStateIndex : NSObject
@property(nonatomic, readonly) BOOL requiresMigration;
- (BOOL)markMigrationRequired:(NSError **)error;
- (BOOL)markConsistent:(NSError **)error;
- (BOOL)beginMigration:(NSError **)error;
- (BOOL)completeMigration:(NSError **)error;
- (void)cancelMigration;
- (void)close;
- (nullable instancetype)initWithRoot:(NSString *)root
                             ownerUID:(uid_t)uid
                             ownerGID:(gid_t)gid
                                error:(NSError **)error;
- (nullable instancetype)initWithRoot:(NSString *)root
                             ownerUID:(uid_t)uid
                             ownerGID:(gid_t)gid
                     rebuildIfCorrupt:(BOOL)recover
                                error:(NSError **)error;
- (nullable NSSet<NSString *> *)identifiersForBundle:(NSString *)bundle error:(NSError **)error;
- (BOOL)replaceEntries:(NSArray<NSDictionary *> *)entries
             forBundle:(NSString *)bundle
                 error:(NSError **)error;
- (BOOL)upsertEntry:(NSDictionary *)entry error:(NSError **)error;
- (BOOL)deleteBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error;
- (BOOL)setStatus:(NSString *)status bundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error;
- (nullable NSDictionary *)entryForBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error;
- (nullable NSDictionary *)backupOverviewForBundle:(NSString *)bundle error:(NSError **)error;
- (nullable NSDictionary *)queryBundle:(NSString *)bundle
                                 query:(NSDictionary *)query
                           currentIDFV:(nullable NSString *)idfv
                                 error:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
