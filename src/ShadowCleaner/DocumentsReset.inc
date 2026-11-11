#import "../Shadow.framework/Headers/Shadow/FingerprintResetBaseline.h"
#include <sys/attr.h>
#include <sys/time.h>

typedef struct {
  int root, documents;
  struct stat rootStat, documentsStat;
  __unsafe_unretained NSString *path;
} StateDocumentsNode;

static void StateDocumentsPin(StateDocumentsNode *node) {
  struct stat root, namedRoot, documents, namedDocuments;
  Require(
      !fstat(node->root, &root) &&
          !lstat(node->path.fileSystemRepresentation, &namedRoot) &&
          S_ISDIR(namedRoot.st_mode) && root.st_dev == node->rootStat.st_dev &&
          root.st_ino == node->rootStat.st_ino &&
          namedRoot.st_dev == root.st_dev && namedRoot.st_ino == root.st_ino,
      @"Application container changed during Documents reset");
  Require(!fstat(node->documents, &documents) &&
              !fstatat(node->root, "Documents", &namedDocuments,
                       AT_SYMLINK_NOFOLLOW) &&
              S_ISDIR(namedDocuments.st_mode) &&
              documents.st_dev == node->documentsStat.st_dev &&
              documents.st_ino == node->documentsStat.st_ino &&
              namedDocuments.st_dev == documents.st_dev &&
              namedDocuments.st_ino == documents.st_ino &&
              documents.st_uid == node->documentsStat.st_uid &&
              documents.st_gid == node->documentsStat.st_gid &&
              documents.st_mode == node->documentsStat.st_mode,
          @"Documents identity or permissions changed during reset");
}

static BOOL StateDocumentsOpen(NSDictionary *container,
                               StateDocumentsNode *node) {
  node->root = -1;
  node->documents = -1;
  node->path = container[@"path"];
  Require([node->path isKindOfClass:NSString.class] && node->path.length,
          @"Invalid container path");
  node->root = open(node->path.fileSystemRepresentation,
                    O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  Require(node->root >= 0 && !fstat(node->root, &node->rootStat) &&
              node->rootStat.st_ino ==
                  [container[@"inode"] unsignedLongLongValue] &&
              (uint64_t)node->rootStat.st_dev ==
                  [container[@"device"] unsignedLongLongValue],
          @"Application container identity changed");
  struct stat named;
  if (fstatat(node->root, "Documents", &named, AT_SYMLINK_NOFOLLOW)) {
    Require(errno == ENOENT, @"Cannot inspect Documents directory");
    return NO;
  }
  Require(S_ISDIR(named.st_mode), @"Documents is not a directory");
  node->documents = openat(node->root, "Documents",
                           O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  Require(node->documents >= 0 &&
              !fstat(node->documents, &node->documentsStat) &&
              node->documentsStat.st_dev == named.st_dev &&
              node->documentsStat.st_ino == named.st_ino,
          @"Cannot pin Documents directory");
  StateDocumentsPin(node);
  return YES;
}

static NSString *StateDocumentsIdentity(NSDictionary *container,
                                        StateDocumentsNode *node) {
  return Hash(@[
    container[@"identifier"], node->path, @((uint64_t)node->rootStat.st_dev),
    @((uint64_t)node->rootStat.st_ino),
    @(node->rootStat.st_birthtimespec.tv_sec),
    @(node->rootStat.st_birthtimespec.tv_nsec)
  ]);
}
static struct timespec StateDocumentsNow(void) {
  struct timeval value;
  Require(!gettimeofday(&value, NULL), @"Cannot read current time");
  return (struct timespec){.tv_sec = value.tv_sec,
                           .tv_nsec = value.tv_usec * 1000};
}
static struct timespec StateDocumentsRecordTime(NSDictionary *record) {
  int64_t seconds = [record[@"Seconds"] longLongValue];
  time_t converted = (time_t)seconds;
  Require((int64_t)converted == seconds,
          @"Documents baseline exceeds this system's time range");
  return (struct timespec){.tv_sec = converted,
                           .tv_nsec = [record[@"Nanoseconds"] longValue]};
}

static NSDictionary *StateResetDocuments(NSDictionary *target, id defaults,
                                         NSDictionary *app, BOOL apply) {
  id stored = app[@"Fingerprint_ResetBaseline"];
  Require(!stored || SHDWFingerprintResetBaselineValid(stored),
          @"Invalid Documents reset baseline");
  NSArray *containers = target[@"containers"];
  Require([containers isKindOfClass:NSArray.class] && containers.count <= 64,
          @"Invalid Documents container scope");
  NSMutableDictionary *records = [NSMutableDictionary new];
  StateDocumentsNode nodes[64];
  for (NSUInteger i = 0; i < 64; i++) {
    nodes[i].root = -1;
    nodes[i].documents = -1;
  }
  NSMutableArray *active = [NSMutableArray new];
  NSMutableSet *seen = [NSMutableSet new];
  @try {
    struct timespec now = StateDocumentsNow();
    for (NSUInteger i = 0; i < containers.count; i++) {
      NSDictionary *container = containers[i];
      NSString *identifier = container[@"identifier"];
      Require([identifier isKindOfClass:NSString.class] && identifier.length &&
                  ![seen containsObject:identifier],
              @"Duplicate or invalid Documents container");
      [seen addObject:identifier];
      if (!StateDocumentsOpen(container, &nodes[i]))
        continue;
      NSString *identity = StateDocumentsIdentity(container, &nodes[i]);
      NSDictionary *record = stored[@"Containers"][identifier];
      if (![record[@"Identity"] isEqual:identity]) {
        struct timespec original = nodes[i].documentsStat.st_birthtimespec;
        record = @{
          @"Identity" : identity,
          @"Seconds" : @(original.tv_sec),
          @"Nanoseconds" : @(original.tv_nsec)
        };
      }
      records[identifier] = record;
      uint32_t upper;
      Require(SHDWFingerprintResetTimeUpperBound(
                  StateDocumentsRecordTime(record), now, &upper),
              @"Documents baseline is later than current time");
      [active addObject:@(i)];
    }
    NSDictionary *baseline = @{@"Version" : @1, @"Containers" : records};
    Require(SHDWFingerprintResetBaselineValid(baseline),
            @"Invalid Documents reset baseline");
    for (NSNumber *index in active)
      StateDocumentsPin(&nodes[index.unsignedIntegerValue]);
    {
      NSString *identifier = target[@"bundleID"];
      NSMutableDictionary *updated = [app mutableCopy];
      updated[@"Fingerprint_ResetBaseline"] = baseline;
      [defaults setObject:updated forKey:identifier];
      if (![defaults synchronize] ||
          ![[defaults dictionaryForKey:identifier] isEqual:updated]) {
        [defaults setObject:app forKey:identifier];
        [defaults synchronize];
        Fail(@"Cannot persist Documents reset baseline");
      }
    }
    if (apply)
      for (NSNumber *index in active) {
        NSUInteger i = index.unsignedIntegerValue;
        StateDocumentsNode *node = &nodes[i];
        StateDocumentsPin(node);
        struct timespec original =
            StateDocumentsRecordTime(records[containers[i][@"identifier"]]);
        struct timespec now = StateDocumentsNow(), selected;
        uint32_t upper;
        Require(SHDWFingerprintResetTimeUpperBound(original, now, &upper) &&
                    SHDWFingerprintResetTime(original, now,
                                             arc4random_uniform(upper + 1),
                                             &selected),
                @"Cannot select Documents reset time");
        struct attrlist attributes = {.bitmapcount = ATTR_BIT_MAP_COUNT,
                                      .commonattr = ATTR_CMN_CRTIME};
        Require(!fsetattrlist(node->documents, &attributes, &selected,
                              sizeof(selected), 0) &&
                    !fsync(node->documents),
                @"Cannot set Documents creation time");
        struct stat checked;
        Require(!fstat(node->documents, &checked) &&
                    checked.st_birthtimespec.tv_sec == selected.tv_sec &&
                    checked.st_birthtimespec.tv_nsec == selected.tv_nsec,
                @"Documents creation time failed readback");
        StateDocumentsPin(node);
      }
    return baseline;
  } @finally {
    for (NSUInteger i = 0; i < 64; i++) {
      if (nodes[i].documents >= 0)
        close(nodes[i].documents);
      if (nodes[i].root >= 0)
        close(nodes[i].root);
    }
  }
}

static NSDictionary *StateRebindDocumentsBaseline(NSDictionary *target,
                                                  NSDictionary *baseline) {
  Require(SHDWFingerprintResetBaselineValid(baseline),
          @"Invalid archived Documents baseline");
  Require([target[@"containers"] isKindOfClass:NSArray.class] &&
              [target[@"containers"] count] <= 64,
          @"Invalid Documents container scope");
  NSMutableDictionary *available = [NSMutableDictionary new],
                      *records = [NSMutableDictionary new];
  for (NSDictionary *container in target[@"containers"]) {
    NSString *identifier = container[@"identifier"];
    Require(identifier && !available[identifier],
            @"Duplicate Documents container");
    available[identifier] = container;
  }
  for (NSString *identifier in baseline[@"Containers"]) {
    NSDictionary *container = available[identifier];
    Require(container != nil,
            @"Archived Documents baseline is outside the application scope");
    StateDocumentsNode node = {.root = -1, .documents = -1};
    @try {
      Require(StateDocumentsOpen(container, &node),
              @"Restored Documents directory is missing");
      NSMutableDictionary *record =
          [baseline[@"Containers"][identifier] mutableCopy];
      record[@"Identity"] = StateDocumentsIdentity(container, &node);
      records[identifier] = record;
      StateDocumentsPin(&node);
    } @finally {
      if (node.documents >= 0)
        close(node.documents);
      if (node.root >= 0)
        close(node.root);
    }
  }
  NSDictionary *result = @{@"Version" : @1, @"Containers" : records};
  Require(SHDWFingerprintResetBaselineValid(result),
          @"Invalid restored Documents baseline");
  return result;
}

static NSDictionary *StateCaptureDocumentsBaseline(NSDictionary *target,
                                                   NSDictionary *baseline) {
  Require(SHDWFingerprintResetBaselineValid(baseline),
          @"Invalid Documents reset baseline");
  NSArray *containers = target[@"containers"];
  Require([containers isKindOfClass:NSArray.class] && containers.count <= 64,
          @"Invalid Documents container scope");
  NSMutableDictionary *records = [NSMutableDictionary new];
  NSMutableSet *seen = [NSMutableSet new];
  for (NSDictionary *container in containers) {
    NSString *identifier = container[@"identifier"];
    Require([identifier isKindOfClass:NSString.class] && identifier.length &&
                ![seen containsObject:identifier],
            @"Duplicate or invalid Documents container");
    [seen addObject:identifier];
    NSDictionary *record = baseline[@"Containers"][identifier];
    if (!record)
      continue;
    StateDocumentsNode node = {.root = -1, .documents = -1};
    @try {
      if (StateDocumentsOpen(container, &node) &&
          [record[@"Identity"]
              isEqual:StateDocumentsIdentity(container, &node)]) {
        StateDocumentsPin(&node);
        records[identifier] = record;
      }
    } @finally {
      if (node.documents >= 0)
        close(node.documents);
      if (node.root >= 0)
        close(node.root);
    }
  }
  NSDictionary *result = @{@"Version" : @1, @"Containers" : records};
  Require(SHDWFingerprintResetBaselineValid(result),
          @"Invalid captured Documents baseline");
  return result;
}
