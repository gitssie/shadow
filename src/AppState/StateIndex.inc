// Index operations are advisory; original manifests retain operation authority.
+ (BOOL)validateCatalogQuery:(NSDictionary *)query error:(NSError **)error {
  NSString *reason = SHDWAppStateCatalogQueryError(query);
  return reason ? FailCode(error, @"invalid_request", reason) : YES;
}
- (SHDWAppStateIndex *)openIndex {
  if (self.indexOperationDirectory.index)
    return self.indexOperationDirectory.index;
  return [[SHDWAppStateIndex alloc] initWithRoot:self.root
                                        ownerUID:self.ownerUID
                                        ownerGID:self.ownerGID
                                           error:NULL];
}
- (BOOL)prepareIndexMutation:(SHDWStateDirectory *)directory
                       error:(NSError **)error {
  if (directory.indexMutationStarted)
    return YES;
  if (![directory.index markMigrationRequired:error])
    return NO;
  directory.indexMutationStarted = YES;
  return YES;
}
- (void)finishIndexDirectory:(SHDWStateDirectory *)directory
                     failure:(NSError *)failure {
  if (directory.index && directory.indexMutationStarted &&
      directory.indexWasComplete && directory.indexCanCommit &&
      !directory.indexWritesFailed && !failure)
    [directory.index markConsistent:NULL];
  [directory releaseLock];
  [directory.index close];
  directory.index = nil;
  if (self.indexOperationDirectory == directory)
    self.indexOperationDirectory = nil;
}
- (void)recordIndexStatus:(NSString *)status
                   bundle:(NSString *)bundle
                     idfv:(NSString *)idfv {
  if (!idfv.length)
    return;
  SHDWAppStateIndex *index = nil;
  @try {
    index = [self openIndex];
    if (![index setStatus:status bundle:bundle idfv:idfv error:NULL])
      self.indexOperationDirectory.indexWritesFailed = YES;
  } @catch (__unused NSException *exception) {
    self.indexOperationDirectory.indexWritesFailed = YES;
  } @finally {
    if (index != self.indexOperationDirectory.index)
      [index close];
  }
}
- (void)recordIndexManifest:(NSDictionary *)manifest
                fingerprint:(NSDictionary *)fingerprint
                     status:(NSString *)status {
  SHDWAppStateIndex *index = nil;
  @try {
    index = [self openIndex];
    if (!index)
      return;
    NSError *failure = nil;
    NSDictionary *previous = [index entryForBundle:manifest[@"bundleID"]
                                              idfv:manifest[@"idfv"]
                                             error:&failure];
    if (!previous || failure) {
      self.indexOperationDirectory.indexWritesFailed = YES;
      return;
    }
    if (!fingerprint && !previous.count) {
      if (self.indexOperationDirectory.indexWasComplete)
        self.indexOperationDirectory.indexWritesFailed = YES;
      return;
    }
    NSMutableDictionary *entry = SHDWAppStateCatalogEntry(manifest, NULL);
    entry[@"bundleID"] = manifest[@"bundleID"];
    if (fingerprint) {
      entry[@"Fingerprint_Data"] = fingerprint[@"data"];
      if ([NSJSONSerialization isValidJSONObject:fingerprint[@"configuration"]])
        entry[@"Fingerprint_Config"] = fingerprint[@"configuration"];
    } else {
      entry[@"Fingerprint_Data"] = previous[@"Fingerprint_Data"];
      entry[@"Fingerprint_Config"] = previous[@"Fingerprint_Config"];
    }
    entry[@"status"]=status ?: previous[@"status"] ?: SHDWBackupStatusBackedUp;
    if (![index upsertEntry:entry error:NULL])
      self.indexOperationDirectory.indexWritesFailed = YES;
  } @catch (__unused NSException *exception) {
    self.indexOperationDirectory.indexWritesFailed = YES;
  } @finally {
    if (index != self.indexOperationDirectory.index)
      [index close];
  }
}
- (void)removeIndexBundle:(NSString *)bundle idfv:(NSString *)idfv {
  SHDWAppStateIndex *index = nil;
  @try {
    index = [self openIndex];
    if (![index deleteBundle:bundle idfv:idfv error:NULL])
      self.indexOperationDirectory.indexWritesFailed = YES;
  } @catch (__unused NSException *exception) {
    self.indexOperationDirectory.indexWritesFailed = YES;
  } @finally {
    if (index != self.indexOperationDirectory.index)
      [index close];
  }
}
- (NSDictionary *)indexEntry:(NSString *)bundle
                        idfv:(NSString *)idfv
                   directory:(SHDWStateDirectory *)directory
                    previous:(NSDictionary *)previous {
  NSError *failure = nil;
  NSDictionary *manifest = [self manifest:bundle
                                     idfv:idfv
                                directory:directory
                                   verify:NO
                                    error:&failure];
  NSMutableDictionary *entry;
  if (manifest) {
    entry = SHDWAppStateCatalogEntry(manifest, NULL);
    entry[@"bundleID"] = manifest[@"bundleID"];
    NSString *path =
        [[directory.path stringByAppendingPathComponent:@"snapshots"]
            stringByAppendingPathComponent:
                [idfv stringByAppendingPathComponent:@"state.tar.zst"]];
    NSDictionary *payloads =
        [SHDWStateArchive readPayloadsAtPath:path
                                        info:manifest[@"stateArchiveInfo"]
                                       names:@[ IdentityPayload ]
                                       error:&failure];
    id identity = payloads[IdentityPayload]
                      ? [NSPropertyListSerialization
                            propertyListWithData:payloads[IdentityPayload]
                                         options:NSPropertyListImmutable
                                          format:NULL
                                           error:&failure]
                      : nil;
    if ([identity isKindOfClass:NSDictionary.class] &&
        [identity[@"data"] isKindOfClass:NSDictionary.class] &&
        [identity[@"configuration"] isKindOfClass:NSDictionary.class] &&
        Same(identity[@"data"][@"VendorIdentifier"], idfv)) {
      entry[@"Fingerprint_Data"] = identity[@"data"];
      if ([NSJSONSerialization isValidJSONObject:identity[@"configuration"]])
        entry[@"Fingerprint_Config"] = identity[@"configuration"];
    }
  } else {
    struct stat st;
    NSDate *date = [NSDate dateWithTimeIntervalSince1970:0];
    if (!fstatat(directory.snapshots, idfv.fileSystemRepresentation, &st,
                 AT_SYMLINK_NOFOLLOW))
      date = [NSDate dateWithTimeIntervalSince1970:st.st_mtimespec.tv_sec];
    entry = [@{
      @"bundleID" : bundle,
      @"idfv" : idfv,
      @"title" : idfv,
      @"note" : @"",
      @"date" : date,
      @"version" : @"",
      @"build" : @"",
      @"owner" : @"phone",
      @"size" : @0
    } mutableCopy];
  }
  entry[@"status"] = previous[@"status"] ?: SHDWBackupStatusBackedUp;
  return entry;
}
- (NSDictionary *)decorateIndexEntry:(NSDictionary *)entry
                             pending:(NSDictionary *)pending
                           directory:(SHDWStateDirectory *)directory {
  NSMutableDictionary *item = [entry mutableCopy];
  [item removeObjectForKey:@"Fingerprint_Data"];
  BOOL source = Same(pending[@"idfv"], item[@"idfv"]);
  item[@"restorePending"] = @(pending.count > 0);
  item[@"recoverySource"] = @(source);
  item[@"resetPending"] = @(source && [pending[@"resetRecovery"] boolValue] &&
                            !Same(pending[@"phase"], @"identity-committed"));
  item[@"finalizationPending"] =
      @(source &&
        [@[ @"identity-pending", @"identity-committed" ]
            containsObject:pending[@"phase"]] &&
        (![pending[@"resetRecovery"] boolValue] ||
         Same(pending[@"phase"], @"identity-committed")));
  BOOL safe = [item[@"version"] length] &&
              Same(item[@"idfv"], UUIDValue(item[@"idfv"]));
  int fd = safe ? openat(directory.snapshots,
                         [item[@"idfv"] fileSystemRepresentation],
                         O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
                : -1;
  struct stat info;
  safe = safe && fd >= 0 && !fstat(fd, &info) &&
         PrivateNode(info, YES, self.ownerUID, self.ownerGID);
  for (NSString *name in
       @[ @"manifest.plist", @"data.tar.zst", @"state.tar.zst" ])
    if (safe && (fstatat(fd, name.fileSystemRepresentation, &info,
                         AT_SYMLINK_NOFOLLOW) ||
                 !PrivateNode(info, NO, self.ownerUID, self.ownerGID)))
      safe = NO;
  if (fd >= 0)
    close(fd);
  if (!safe) {
    item[@"unavailable"] = @YES;
    item[@"error"] = @"Snapshot is unavailable.";
  }
  if (source && pending[@"phase"])
    item[@"status"] = pending[@"phase"];
  else if ([@[
             SHDWBackupStatusBackingUp, SHDWBackupStatusResetting,
             SHDWBackupStatusRestoring, SHDWBackupStatusIdentityPending,
             SHDWBackupStatusIdentityCommitted
           ] containsObject:item[@"status"]])
    item[@"status"] = SHDWBackupStatusBackedUp;
  return item;
}
// One upgrade transaction backfills every existing application's saved
// identities. A completed migration is never repeated by searches, pages or
// ordinary refresh.
- (BOOL)migrateIndex:(SHDWAppStateIndex *)index error:(NSError **)error {
  if (!index.requiresMigration)
    return YES;
  int root =
      openat(self.rootFD, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (root < 0)
    return POSIXFail(error, @"Cannot open backup index migration source.");
  DIR *apps = fdopendir(root);
  if (!apps) {
    close(root);
    return POSIXFail(error, @"Cannot enumerate backup index migration source.");
  }
  NSMutableArray *bundles = [NSMutableArray new];
  BOOL complete = NO;
  if (![index beginMigration:error]) {
    closedir(apps);
    return NO;
  }
  @try {
    for (;;) {
      errno = 0;
      struct dirent *record = readdir(apps);
      if (!record) {
        if (errno)
          return POSIXFail(error,
                           @"Cannot enumerate existing application backups.");
        break;
      }
      NSString *bundle = @(record->d_name);
      if ([bundle hasPrefix:@"."] || !BundleValue(bundle))
        continue;
      struct stat st;
      if (fstatat(self.rootFD, record->d_name, &st, AT_SYMLINK_NOFOLLOW))
        return POSIXFail(error,
                         @"Cannot inspect existing application backups.");
      if (S_ISDIR(st.st_mode))
        [bundles addObject:bundle];
    }
    for (NSString *bundle in
         [bundles sortedArrayUsingSelector:@selector(compare:)]) {
      SHDWStateDirectory *source = [self directory:bundle
                                            create:NO
                                         exclusive:NO
                                           missing:NULL
                                             error:error];
      if (!source)
        return NO;
      DIR *snapshots = NULL;
      @try {
        snapshots = fdopendir(dup(source.snapshots));
        if (!snapshots)
          return POSIXFail(error, @"Cannot enumerate existing snapshots.");
        NSSet *previousIDs = [index identifiersForBundle:bundle error:error];
        if (!previousIDs)
          return NO;
        NSMutableSet *found = [NSMutableSet new];
        for (;;) {
          errno = 0;
          struct dirent *record = readdir(snapshots);
          if (!record) {
            if (errno)
              return POSIXFail(error, @"Cannot enumerate existing snapshots.");
            break;
          }
          NSString *idfv = @(record->d_name);
          if (!Same(idfv, UUIDValue(idfv)))
            continue;
          [found addObject:idfv];
          NSDictionary *previous =
              [index entryForBundle:bundle idfv:idfv error:error];
          if (error && *error)
            return NO;
          NSDictionary *entry = [self indexEntry:bundle
                                            idfv:idfv
                                       directory:source
                                        previous:previous];
          if (![index upsertEntry:entry error:error])
            return NO;
        }
        for (NSString *idfv in previousIDs)
          if (![found containsObject:idfv] &&
              ![index deleteBundle:bundle idfv:idfv error:error])
            return NO;
        if (![self checkDirectory:source error:error])
          return NO;
      } @finally {
        if (snapshots)
          closedir(snapshots);
        [source releaseLock];
      }
    }
    complete = [self checkRoot:error] && [index completeMigration:error];
    return complete;
  } @finally {
    closedir(apps);
    if (!complete)
      [index cancelMigration];
  }
}
- (NSDictionary *)queryCatalogBundle:(NSString *)bundleID
                               query:(NSDictionary *)query
                               error:(NSError **)error {
  if (error)
    *error = nil;
  if (![self.class validateCatalogQuery:query error:error])
    return nil;
  SHDWStateDirectory *directory = nil;
  SHDWAppStateIndex *index = nil;
  @try {
    if (!BundleValue(bundleID) || ![self checkRoot:error]) {
      if (error && !*error)
        FailCode(error, @"invalid_request", @"Invalid application identifier.");
      return nil;
    }
    index =
        [[SHDWAppStateIndex alloc] initWithRoot:self.root
                                       ownerUID:self.ownerUID
                                       ownerGID:self.ownerGID
                               rebuildIfCorrupt:[query[@"refresh"] boolValue]
                                          error:error];
    if (!index || ![self migrateIndex:index error:error])
      return nil;
    BOOL missing = NO;
    directory = [self directory:bundleID
                         create:NO
                      exclusive:NO
                        missing:&missing
                          error:error];
    if (!directory)
      return missing ? @{
        @"items" : @[],
        @"total" : @0,
        @"nextOffset" : @0,
        @"hasMore" : @NO,
        @"currentSnapshot" : @{},
        @"restorePending" : @NO
      }
                     : nil;
    NSDictionary *pending = [self pending:directory error:error];
    if (!pending)
      return nil;
    NSString *current = self.currentIdentityProvider
                            ? UUIDValue(self.currentIdentityProvider(bundleID))
                            : nil;
    NSDictionary *page = [index queryBundle:bundleID
                                      query:query
                                currentIDFV:current
                                      error:error];
    if (!page)
      return nil;
    NSMutableArray *items = [NSMutableArray new];
    for (NSDictionary *entry in page[@"items"])
      [items addObject:[self decorateIndexEntry:entry
                                        pending:pending
                                      directory:directory]];
    NSMutableDictionary *result = [page mutableCopy];
    result[@"items"] = items;
    NSDictionary *active =
        current ? [index entryForBundle:bundleID idfv:current error:error]
                : nil;
    if (error && *error)
      return nil;
    result[@"currentSnapshot"] = active.count
                                     ? [self decorateIndexEntry:active
                                                        pending:pending
                                                      directory:directory]
                                     : @{};
    result[@"restorePending"] = @(pending.count > 0);
    return [self checkDirectory:directory error:error] ? result : nil;
  } @finally {
    [index close];
    [directory releaseLock];
  }
}
