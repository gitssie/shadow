#import "Index.h"
#import "../../sdk/AppState/SHDWAppStateCatalogQuery.h"
#include <fcntl.h>
#include <math.h>
#include <sqlite3.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

static BOOL IndexError(NSError **error, NSString *message) {
    if (error)
        *error = [NSError errorWithDomain:@"me.jjolano.shadow.app-state.index"
                                     code:1
                                 userInfo:@{NSLocalizedDescriptionKey : message}];
    return NO;
}
static BOOL PrivateFile(int fd, uid_t uid, gid_t gid, BOOL directory) {
    struct stat st;
    return fd >= 0 && !fstat(fd, &st) && st.st_uid == uid && st.st_gid == gid && !(st.st_mode & 0077) &&
           (directory ? S_ISDIR(st.st_mode) : (S_ISREG(st.st_mode) && st.st_nlink == 1));
}
static void Contains(sqlite3_context *context, int argc, sqlite3_value **values) {
    (void)argc;
    const char *a = (const char *)sqlite3_value_text(values[0]),
               *b = (const char *)sqlite3_value_text(values[1]);
    @autoreleasepool {
        NSString *text = a ? [[NSString alloc] initWithBytes:a
                                                      length:sqlite3_value_bytes(values[0])
                                                    encoding:NSUTF8StringEncoding]
                           : @"";
        NSString *query = b ? [[NSString alloc] initWithBytes:b
                                                       length:sqlite3_value_bytes(values[1])
                                                     encoding:NSUTF8StringEncoding]
                            : @"";
        sqlite3_result_int(context, [text localizedCaseInsensitiveContainsString:query]);
    }
}
static NSString *ColumnText(sqlite3_stmt *statement, int column) {
    const unsigned char *text = sqlite3_column_text(statement, column);
    return text ? [[NSString alloc] initWithBytes:text
                                           length:sqlite3_column_bytes(statement, column)
                                         encoding:NSUTF8StringEncoding]
                : nil;
}
static int Bind(sqlite3_stmt *statement, int column, id value) {
    if ([value isKindOfClass:NSString.class])
        return sqlite3_bind_text64(statement, column, [value UTF8String],
                                   [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding], SQLITE_TRANSIENT,
                                   SQLITE_UTF8);
    else if ([value isKindOfClass:NSData.class])
        return sqlite3_bind_blob64(statement, column, [value bytes], [value length], SQLITE_TRANSIENT);
    else if ([value isKindOfClass:NSNumber.class])
        return sqlite3_bind_int64(statement, column, [value longLongValue]);
    else
        return sqlite3_bind_null(statement, column);
}
@interface SHDWAppStateIndex () {
    sqlite3 *_database;
    int _lockFD;
    int _directoryFD;
    BOOL _migrationActive;
    BOOL _requiresMigration;
}
@end
@implementation SHDWAppStateIndex
- (instancetype)initWithRoot:(NSString *)root
                    ownerUID:(uid_t)uid
                    ownerGID:(gid_t)gid
                       error:(NSError **)error {
    return [self initWithRoot:root ownerUID:uid ownerGID:gid rebuildIfCorrupt:NO error:error];
}
- (instancetype)initWithRoot:(NSString *)root
                    ownerUID:(uid_t)uid
                    ownerGID:(gid_t)gid
            rebuildIfCorrupt:(BOOL)recover
                       error:(NSError **)error {
    if (!(self = [super init]))
        return nil;
    _lockFD = -1;
    _directoryFD = -1;
    int parent = open(root.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (!PrivateFile(parent, uid, gid, YES)) {
        if (parent >= 0)
            close(parent);
        IndexError(error, @"Backup index parent is unsafe.");
        return nil;
    }
    BOOL made = mkdirat(parent, ".index", 0700) == 0;
    int directory = openat(parent, ".index", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    close(parent);
    if (made && directory >= 0 && fchown(directory, uid, gid)) {
        close(directory);
        IndexError(error, @"Cannot own backup index directory.");
        return nil;
    }
    if (!PrivateFile(directory, uid, gid, YES)) {
        if (directory >= 0)
            close(directory);
        IndexError(error, @"Backup index directory is unsafe.");
        return nil;
    }
    _lockFD = openat(directory, ".lock", O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (_lockFD >= 0) {
        if (fchown(_lockFD, uid, gid)) {
            close(directory);
            return nil;
        }
    } else
        _lockFD = openat(directory, ".lock", O_RDWR | O_NOFOLLOW | O_CLOEXEC);
    if (!PrivateFile(_lockFD, uid, gid, NO)) {
        close(directory);
        IndexError(error, @"Backup index lock is unsafe.");
        return nil;
    }
    NSTimeInterval deadline = NSProcessInfo.processInfo.systemUptime + 2.0;
    while (flock(_lockFD, LOCK_EX | LOCK_NB)) {
        if (errno != EWOULDBLOCK && errno != EAGAIN && errno != EINTR) {
            close(directory);
            IndexError(error, @"Cannot lock backup index.");
            return nil;
        }
        if (NSProcessInfo.processInfo.systemUptime >= deadline) {
            close(directory);
            if (error)
                *error = [NSError errorWithDomain:@"me.jjolano.shadow.app-state.index"
                                             code:2
                                         userInfo:@{
                                             NSLocalizedDescriptionKey : @"Backup index is busy.",
                                             @"errorCode" : @"busy"
                                         }];
            return nil;
        }
        [NSThread sleepForTimeInterval:0.01];
    }
    int fd =
        openat(directory, "backup-index.sqlite", O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd >= 0) {
        if (fchown(fd, uid, gid)) {
            close(fd);
            close(directory);
            return nil;
        }
    } else
        fd = openat(directory, "backup-index.sqlite", O_RDWR | O_NOFOLLOW | O_CLOEXEC);
    BOOL safe = PrivateFile(fd, uid, gid, NO);
    if (fd >= 0)
        close(fd);
    BOOL journalSafe = YES;
    for (NSString *name in
         @[ @"backup-index.sqlite-journal", @"backup-index.sqlite-wal", @"backup-index.sqlite-shm" ]) {
        struct stat st;
        if (fstatat(directory, name.fileSystemRepresentation, &st, AT_SYMLINK_NOFOLLOW)) {
            if (errno != ENOENT)
                journalSafe = NO;
            continue;
        }
        BOOL owner = (st.st_uid == uid && st.st_gid == gid) || (geteuid() == 0 && st.st_uid == 0);
        if (!owner || !S_ISREG(st.st_mode) || st.st_nlink != 1 || (st.st_mode & 0077))
            journalSafe = NO;
    }
    _directoryFD = directory;
    if (!safe || !journalSafe) {
        IndexError(error, @"Backup index database is unsafe.");
        return nil;
    }
    char *canonical = realpath(root.fileSystemRepresentation, NULL);
    if (!canonical) {
        IndexError(error, @"Cannot resolve backup index root.");
        return nil;
    }
    NSString *path = [@(canonical) stringByAppendingPathComponent:@".index/backup-index.sqlite"];
    free(canonical);
    int result = SQLITE_OK;
    if (![self openDatabaseAtPath:path verify:recover result:&result error:error]) {
        if (!recover || (result != SQLITE_CORRUPT && result != SQLITE_NOTADB))
            return nil;
        if (_database) {
            sqlite3_close_v2(_database);
            _database = NULL;
        }
        if (![self removeCorruptDatabaseWithUID:uid gid:gid error:error])
            return nil;
        if (![self openDatabaseAtPath:path verify:recover result:&result error:error])
            return nil;
    }
    if (error)
        *error = nil;
    return self;
}
- (BOOL)removeCorruptDatabaseWithUID:(uid_t)uid gid:(gid_t)gid error:(NSError **)error {
    NSArray *names = @[
        @"backup-index.sqlite", @"backup-index.sqlite-journal", @"backup-index.sqlite-wal",
        @"backup-index.sqlite-shm"
    ];
    for (NSString *name in names) {
        struct stat st;
        if (fstatat(_directoryFD, name.fileSystemRepresentation, &st, AT_SYMLINK_NOFOLLOW)) {
            if (errno == ENOENT)
                continue;
            return IndexError(error, @"Cannot inspect corrupt backup index.");
        }
        BOOL owner = st.st_uid == uid && st.st_gid == gid;
        if (![name isEqual:@"backup-index.sqlite"] && geteuid() == 0 && st.st_uid == 0)
            owner = YES;
        if (!owner || !S_ISREG(st.st_mode) || st.st_nlink != 1 || (st.st_mode & 0077))
            return IndexError(error, @"Corrupt backup index has unsafe files.");
    }
    for (NSString *name in names)
        if (unlinkat(_directoryFD, name.fileSystemRepresentation, 0) && errno != ENOENT)
            return IndexError(error, @"Cannot remove corrupt backup index.");
    int fd =
        openat(_directoryFD, "backup-index.sqlite", O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0)
        return IndexError(error, @"Cannot recreate backup index.");
    BOOL owned = fchown(fd, uid, gid) == 0;
    close(fd);
    return (owned && !fsync(_directoryFD)) || IndexError(error, @"Cannot synchronize rebuilt backup index.");
}
- (BOOL)openDatabaseAtPath:(NSString *)path verify:(BOOL)verify result:(int *)result error:(NSError **)error {
    int flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX;
#ifdef SQLITE_OPEN_NOFOLLOW
    flags |= SQLITE_OPEN_NOFOLLOW;
#endif
    if (sqlite3_open_v2(path.fileSystemRepresentation, &_database, flags, NULL) != SQLITE_OK) {
        IndexError(error, @"Cannot open backup index.");
        *result = sqlite3_errcode(_database);
        return NO;
    }
    sqlite3_busy_timeout(_database, 1000);
    sqlite3_create_function_v2(_database, "shadow_contains", 2, SQLITE_UTF8, NULL, Contains, NULL, NULL,
                               NULL);
    sqlite3_stmt *version = NULL;
    int code = sqlite3_prepare_v2(_database, "PRAGMA user_version", -1, &version, NULL);
    if (code == SQLITE_OK)
        code = sqlite3_step(version);
    int schemaVersion = code == SQLITE_ROW ? sqlite3_column_int(version, 0) : 0;
    sqlite3_finalize(version);
    if (code != SQLITE_ROW) {
        *result = code;
        return IndexError(error, @"Cannot read backup index version.");
    }
    if (schemaVersion > 1) {
        *result = SQLITE_ERROR;
        return IndexError(error, @"Backup index schema is newer than this version.");
    }
    if (verify) {
        sqlite3_stmt *check = NULL;
        code = sqlite3_prepare_v2(_database, "PRAGMA quick_check", -1, &check, NULL);
        if (code == SQLITE_OK)
            code = sqlite3_step(check);
        BOOL valid = code == SQLITE_ROW && [ColumnText(check, 0) isEqual:@"ok"];
        sqlite3_finalize(check);
        if (!valid) {
            *result = code == SQLITE_ROW ? SQLITE_CORRUPT : code;
            return IndexError(error, @"Backup index is corrupt.");
        }
    }
    // Older iOS JSON1 requires trusted schema for CHECKs and expression indexes.
    if (![self
            execute:
                @"PRAGMA journal_mode=DELETE; "
                @"PRAGMA synchronous=FULL; "
                @"PRAGMA trusted_schema=ON; "
                @"CREATE TABLE IF NOT EXISTS backup_entries(bundleID TEXT NOT NULL,idfv TEXT NOT NULL,title "
                @"TEXT NOT NULL,note TEXT NOT NULL,date REAL NOT NULL,version TEXT NOT NULL,build TEXT NOT "
                @"NULL,digest TEXT,owner TEXT NOT NULL CHECK(owner IN ('phone','rv')),size INTEGER NOT NULL "
                @"CHECK(size>=0),Fingerprint_Data BLOB,Fingerprint_Config TEXT CHECK(Fingerprint_Config IS "
                @"NULL OR json_valid(Fingerprint_Config)),status TEXT NOT NULL,"
                @"deleteLocked INTEGER NOT NULL DEFAULT 0 CHECK(deleteLocked IN(0,1)),PRIMARY KEY(bundleID,idfv)); "
                @"CREATE INDEX IF NOT EXISTS backup_entries_date ON backup_entries(bundleID,date DESC,idfv); "
                @"CREATE INDEX IF NOT EXISTS backup_entries_region ON "
                @"backup_entries(bundleID,json_extract(Fingerprint_Config,'$.Localization.Region')); "
              error:error]) {
        *result = sqlite3_errcode(_database);
        return NO;
    }
    _requiresMigration = schemaVersion == 0;
    *result = SQLITE_OK;
    return YES;
}
- (BOOL)requiresMigration {
    return _requiresMigration;
}
- (BOOL)markMigrationRequired:(NSError **)error {
    if (_migrationActive)
        return IndexError(error, @"Cannot invalidate an active backup index migration.");
    if (![self execute:@"PRAGMA user_version=0" error:error])
        return NO;
    _requiresMigration = YES;
    return YES;
}
- (BOOL)markConsistent:(NSError **)error {
    if (_migrationActive)
        return IndexError(error, @"Cannot finalize an active backup index migration.");
    if (![self execute:@"PRAGMA user_version=1" error:error])
        return NO;
    _requiresMigration = NO;
    return YES;
}
- (BOOL)beginMigration:(NSError **)error {
    if (_migrationActive)
        return IndexError(error, @"Backup index migration is already running.");
    if (![self execute:@"BEGIN IMMEDIATE" error:error])
        return NO;
    _migrationActive = YES;
    return YES;
}
- (BOOL)completeMigration:(NSError **)error {
    if (!_migrationActive)
        return IndexError(error, @"Backup index migration has not started.");
    if (![self execute:@"PRAGMA user_version=1; COMMIT" error:error]) {
        [self cancelMigration];
        return NO;
    }
    _migrationActive = NO;
    _requiresMigration = NO;
    return YES;
}
- (void)cancelMigration {
    if (_migrationActive) {
        [self execute:@"ROLLBACK" error:NULL];
        _migrationActive = NO;
    }
}
- (void)dealloc {
    [self close];
}
- (void)close {
    [self cancelMigration];
    if (_database) {
        sqlite3_close_v2(_database);
        _database = NULL;
    }
    if (_lockFD >= 0) {
        flock(_lockFD, LOCK_UN);
        close(_lockFD);
        _lockFD = -1;
    }
    if (_directoryFD >= 0) {
        close(_directoryFD);
        _directoryFD = -1;
    }
}
- (BOOL)execute:(NSString *)sql error:(NSError **)error {
    if (!_database)
        return IndexError(error, @"Backup index is closed.");
    return sqlite3_exec(_database, sql.UTF8String, NULL, NULL, NULL) == SQLITE_OK ||
           IndexError(error, [NSString stringWithFormat:@"Cannot update backup index: %s",
                                                        sqlite3_errmsg(_database)]);
}
- (sqlite3_stmt *)prepare:(NSString *)sql values:(NSArray *)values error:(NSError **)error {
    sqlite3_stmt *statement = NULL;
    if (!_database) {
        IndexError(error, @"Backup index is closed.");
        return NULL;
    }
    if (sqlite3_prepare_v2(_database, sql.UTF8String, -1, &statement, NULL) != SQLITE_OK) {
        IndexError(error, @"Cannot query backup index.");
        return NULL;
    }
    for (NSUInteger i = 0; i < values.count; i++) {
        if (Bind(statement, (int)i + 1, values[i]) != SQLITE_OK) {
            sqlite3_finalize(statement);
            IndexError(error, @"Cannot bind backup query.");
            return NULL;
        }
    }
    return statement;
}
- (BOOL)change:(NSString *)sql values:(NSArray *)values error:(NSError **)error {
    sqlite3_stmt *s = [self prepare:sql values:values error:error];
    if (!s)
        return NO;
    BOOL ok = sqlite3_step(s) == SQLITE_DONE;
    sqlite3_finalize(s);
    return ok || IndexError(error, @"Cannot update backup index record.");
}
- (NSSet *)identifiersForBundle:(NSString *)bundle error:(NSError **)error {
    sqlite3_stmt *s = [self prepare:@"SELECT idfv FROM backup_entries WHERE bundleID=?"
                             values:@[ bundle ]
                              error:error];
    if (!s)
        return nil;
    NSMutableSet *ids = [NSMutableSet new];
    int result;
    while ((result = sqlite3_step(s)) == SQLITE_ROW) {
        NSString *v = ColumnText(s, 0);
        if (v)
            [ids addObject:v];
    }
    sqlite3_finalize(s);
    if (result != SQLITE_DONE) {
        IndexError(error, @"Cannot enumerate backup index.");
        return nil;
    }
    return ids;
}
- (BOOL)upsertEntry:(NSDictionary *)entry error:(NSError **)error {
    if (![entry isKindOfClass:NSDictionary.class])
        return IndexError(error, @"Invalid backup index entry.");
    if (entry[@"digest"] && ![entry[@"digest"] isKindOfClass:NSString.class])
        return IndexError(error, @"Invalid indexed fingerprint identifier.");
    for (NSString *key in @[ @"bundleID", @"idfv", @"title", @"note", @"version", @"build", @"status" ])
        if (![entry[key] isKindOfClass:NSString.class])
            return IndexError(error, @"Invalid backup index entry.");
    id deleteLocked = entry[@"deleteLocked"];
    if (deleteLocked && CFGetTypeID((__bridge CFTypeRef)deleteLocked) != CFBooleanGetTypeID())
        return IndexError(error, @"Invalid indexed deletion lock.");
    id size = entry[@"size"];
    if (![entry[@"date"] isKindOfClass:NSDate.class] || !isfinite([entry[@"date"] timeIntervalSince1970]) ||
        ![size isKindOfClass:NSNumber.class] || !isfinite([size doubleValue]) ||
        [size compare:@0] == NSOrderedAscending || [size compare:@(LLONG_MAX)] == NSOrderedDescending ||
        [size doubleValue] != [size longLongValue]) {
        return IndexError(error, @"Invalid backup index date or size.");
    }
    id fingerprint = entry[@"Fingerprint_Data"], config = entry[@"Fingerprint_Config"];
    NSData *data = nil, *json = nil;
    if (fingerprint) {
        if (![fingerprint isKindOfClass:NSDictionary.class])
            return IndexError(error, @"Invalid indexed fingerprint.");
        data = [NSPropertyListSerialization dataWithPropertyList:fingerprint
                                                          format:NSPropertyListBinaryFormat_v1_0
                                                         options:0
                                                           error:error];
        if (!data)
            return NO;
    }
    if (config) {
        if (![config isKindOfClass:NSDictionary.class] || ![NSJSONSerialization isValidJSONObject:config])
            return IndexError(error, @"Invalid indexed configuration.");
        json = [NSJSONSerialization dataWithJSONObject:config options:0 error:error];
        if (!json)
            return NO;
    }
    sqlite3_stmt *s =
        [self prepare:@"INSERT OR REPLACE INTO "
                      @"backup_entries(bundleID,idfv,title,note,date,version,build,digest,owner,size,"
                      @"Fingerprint_Data,Fingerprint_Config,status,deleteLocked) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
               values:@[]
                error:error];
    if (!s)
        return NO;
    NSArray *values = @[
        entry[@"bundleID"], entry[@"idfv"], entry[@"title"], entry[@"note"], NSNull.null, entry[@"version"],
        entry[@"build"], entry[@"digest"] ?: NSNull.null, entry[@"owner"] ?: @"phone", entry[@"size"],
        data ?: NSNull.null,
        json ? [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] : NSNull.null,
        entry[@"status"], deleteLocked ?: @NO
    ];
    for (NSUInteger i = 0; i < values.count; i++) {
        if (Bind(s, (int)i + 1, values[i]) != SQLITE_OK) {
            sqlite3_finalize(s);
            return IndexError(error, @"Cannot bind backup index entry.");
        }
    }
    sqlite3_bind_double(s, 5, [entry[@"date"] timeIntervalSince1970]);
    BOOL ok = sqlite3_step(s) == SQLITE_DONE;
    sqlite3_finalize(s);
    return ok || IndexError(error, @"Cannot save backup index entry.");
}
- (BOOL)replaceEntries:(NSArray *)entries forBundle:(NSString *)bundle error:(NSError **)error {
    if (![self execute:@"SAVEPOINT replace_bundle" error:error])
        return NO;
    BOOL ok = NO;
    @try {
        if (![self change:@"DELETE FROM backup_entries WHERE bundleID=?" values:@[ bundle ] error:error])
            return NO;
        for (NSDictionary *entry in entries)
            if (![entry[@"bundleID"] isEqual:bundle] || ![self upsertEntry:entry error:error])
                return NO;
        ok = [self execute:@"RELEASE replace_bundle" error:error];
        return ok;
    } @finally {
        if (!ok)
            [self execute:@"ROLLBACK TO replace_bundle; RELEASE replace_bundle" error:NULL];
    }
}
- (BOOL)deleteBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error {
    return [self change:@"DELETE FROM backup_entries WHERE bundleID=? AND idfv=?"
                 values:@[ bundle, idfv ]
                  error:error];
}
- (BOOL)setStatus:(NSString *)status bundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error {
    return [self change:@"UPDATE backup_entries SET status=? WHERE bundleID=? AND idfv=?"
                 values:@[ status, bundle, idfv ]
                  error:error];
}
- (NSDictionary *)readEntry:(sqlite3_stmt *)s includeData:(BOOL)includeData {
    NSMutableDictionary *entry = [NSMutableDictionary new];
    NSArray *keys = @[
        @"bundleID", @"idfv", @"title", @"note", @"date", @"version", @"build", @"digest", @"owner", @"size",
        @"Fingerprint_Data", @"Fingerprint_Config", @"status", @"deleteLocked"
    ];
    for (int i = 0; i < 14; i++) {
        if (sqlite3_column_type(s, i) == SQLITE_NULL)
            continue;
        id value = nil;
        if (i == 4)
            value = [NSDate dateWithTimeIntervalSince1970:sqlite3_column_double(s, i)];
        else if (i == 9)
            value = @(sqlite3_column_int64(s, i));
        else if (i == 13)
            value = sqlite3_column_int(s, i) ? @YES : @NO;
        else if (i == 10) {
            if (includeData) {
                NSData *d = [NSData dataWithBytes:sqlite3_column_blob(s, i)
                                           length:sqlite3_column_bytes(s, i)];
                value = [NSPropertyListSerialization propertyListWithData:d
                                                                  options:NSPropertyListImmutable
                                                                   format:NULL
                                                                    error:NULL];
            }
        } else if (i == 11) {
            NSData *d = [ColumnText(s, i) dataUsingEncoding:NSUTF8StringEncoding];
            if (d)
                value = [NSJSONSerialization JSONObjectWithData:d options:0 error:NULL];
        } else
            value = ColumnText(s, i);
        if (value)
            entry[keys[i]] = value;
    }
    return entry;
}
- (NSDictionary *)entryForBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error {
    sqlite3_stmt *s = [self prepare:@"SELECT * FROM backup_entries WHERE bundleID=? AND idfv=?"
                             values:@[ bundle, idfv ]
                              error:error];
    if (!s)
        return nil;
    int result = sqlite3_step(s);
    NSDictionary *entry = result == SQLITE_ROW ? [self readEntry:s includeData:YES] : @{};
    sqlite3_finalize(s);
    if (result != SQLITE_ROW && result != SQLITE_DONE) {
        IndexError(error, @"Cannot read indexed backup.");
        return nil;
    }
    return entry;
}
- (NSDictionary *)backupOverviewForBundle:(NSString *)bundle error:(NSError **)error {
    sqlite3_stmt *statement = [self prepare:
        @"SELECT COUNT(*),COALESCE(SUM(owner='phone'),0),COALESCE(SUM(owner='rv'),0),"
         "COALESCE(SUM(size),0),MAX(date) FROM backup_entries WHERE bundleID=?"
        values:@[bundle] error:error];
    if (!statement) return nil;
    if (sqlite3_step(statement) != SQLITE_ROW) {
        sqlite3_finalize(statement);
        IndexError(error, @"Cannot read backup overview.");
        return nil;
    }
    NSString *latest = @"";
    if (sqlite3_column_type(statement, 4) != SQLITE_NULL) {
        NSISO8601DateFormatter *formatter = [NSISO8601DateFormatter new];
        formatter.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
        latest = [formatter stringFromDate:[NSDate dateWithTimeIntervalSince1970:sqlite3_column_double(statement, 4)]];
    }
    NSDictionary *result = @{
        @"format": @"ShadowBackupOverview1", @"bundle_id": bundle,
        @"backup_count": @(sqlite3_column_int64(statement, 0)),
        @"phone_count": @(sqlite3_column_int64(statement, 1)),
        @"rv_count": @(sqlite3_column_int64(statement, 2)),
        @"total_size_bytes": @(sqlite3_column_int64(statement, 3)),
        @"latest_backup_at": latest
    };
    sqlite3_finalize(statement);
    return result;
}
- (NSDictionary *)queryBundle:(NSString *)bundle
                        query:(NSDictionary *)query
                  currentIDFV:(NSString *)idfv
                        error:(NSError **)error {
    NSString *reason=SHDWAppStateCatalogQueryError(query);
    if(reason){IndexError(error,reason);return nil;}
    NSString *search = [query[@"search"] isKindOfClass:NSString.class] ? query[@"search"] : @"";
    NSString *region = [query[@"region"] isKindOfClass:NSString.class] ? query[@"region"] : nil;
    search = [search stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSInteger offset = [query[@"offset"] integerValue],
              limit = query[@"limit"] ? [query[@"limit"] integerValue] : SHDWAppStateCatalogPageSize;
    NSMutableString *where = [@" WHERE bundleID=?" mutableCopy];
    NSMutableArray *values = [NSMutableArray arrayWithObject:bundle];
    if (search.length) {
        [where appendString:@" AND (shadow_contains(title,?) OR shadow_contains(note,?))"];
        [values addObjectsFromArray:@[ search, search ]];
    }
    if (region) {
        [where appendString:@" AND json_extract(Fingerprint_Config,'$.Localization.Region')=?"];
        [values addObject:region];
    }
    sqlite3_stmt *count = [self prepare:[@"SELECT count(*) FROM backup_entries" stringByAppendingString:where]
                                 values:values
                                  error:error];
    if (!count)
        return nil;
    int result = sqlite3_step(count);
    sqlite3_int64 total = result == SQLITE_ROW ? sqlite3_column_int64(count, 0) : 0;
    sqlite3_finalize(count);
    if (result != SQLITE_ROW) {
        IndexError(error, @"Cannot count indexed backups.");
        return nil;
    }
    NSString *sql = [NSString
        stringWithFormat:
            @"SELECT * FROM backup_entries%@ ORDER BY (idfv=?) DESC,date DESC,idfv ASC LIMIT ? OFFSET ?",
            where];
    [values addObjectsFromArray:@[ idfv ?: @"", @(limit), @(offset) ]];
    sqlite3_stmt *s = [self prepare:sql values:values error:error];
    if (!s)
        return nil;
    NSMutableArray *items = [NSMutableArray new];
    while ((result = sqlite3_step(s)) == SQLITE_ROW)
        [items addObject:[self readEntry:s includeData:NO]];
    sqlite3_finalize(s);
    if (result != SQLITE_DONE) {
        IndexError(error, @"Cannot read backup page.");
        return nil;
    }
    NSUInteger next = (NSUInteger)offset + items.count;
    return @{
        @"items" : items,
        @"total" : @(total),
        @"nextOffset" : @(next),
        @"hasMore" : @(next < (uint64_t)total)
    };
}
@end
