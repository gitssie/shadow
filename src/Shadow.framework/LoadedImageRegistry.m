#import "LoadedImageRegistry.h"
#import <Shadow/RuntimeImageIdentity.h>
#import <mach-o/loader.h>
#import <mach-o/fat.h>
#import <libkern/OSByteOrder.h>
#import <pthread.h>

static BOOL systemPath(NSString *path) {
  if (!([path hasPrefix:@"/usr/lib/"] || [path hasPrefix:@"/System/Library/"]) ||
      [path containsString:@"//"] || [path containsString:@"%"])
    return NO;
  for (NSString *part in [path componentsSeparatedByString:@"/"])
    if ([part isEqualToString:@"."] || [part isEqualToString:@".."])
      return NO;
  return ![path hasSuffix:@"/"];
}

typedef struct {
  cpu_type_t cpu;
  cpu_subtype_t subtype;
  uint8_t uuid[16];
  BOOL hasUUID;
} ImageMetadata;

static BOOL metadata(const unsigned char *bytes, size_t length, ImageMetadata *out,
                     NSString **name) {
  if (length < sizeof(struct mach_header)) return NO;
  struct mach_header h; memcpy(&h, bytes, sizeof(h));
  size_t headerSize = h.magic == MH_MAGIC_64 ? sizeof(struct mach_header_64) : sizeof(h);
  if ((h.magic != MH_MAGIC && h.magic != MH_MAGIC_64) || length < headerSize ||
      h.filetype != MH_DYLIB || h.sizeofcmds > 1024 * 1024 ||
      h.sizeofcmds > length - headerSize || h.ncmds > h.sizeofcmds / sizeof(struct load_command))
    return NO;
  out->cpu = h.cputype; out->subtype = h.cpusubtype;
  size_t offset = headerSize, end = headerSize + h.sizeofcmds;
  for (uint32_t i = 0; i < h.ncmds; i++) {
    if (end - offset < sizeof(struct load_command)) return NO;
    struct load_command lc; memcpy(&lc, bytes + offset, sizeof(lc));
    if (lc.cmdsize < sizeof(lc) || lc.cmdsize > end - offset) return NO;
    if (lc.cmd == LC_UUID) {
      if (lc.cmdsize < sizeof(struct uuid_command) || out->hasUUID) return NO;
      memcpy(out->uuid, bytes + offset + 8, 16); out->hasUUID = YES;
    }
    if (lc.cmd == LC_ID_DYLIB) {
      struct dylib_command d;
      if (lc.cmdsize < sizeof(d) || *name) return NO;
      memcpy(&d, bytes + offset, sizeof(d));
      if (d.dylib.name.offset < sizeof(d) || d.dylib.name.offset >= lc.cmdsize) return NO;
      const char *s = (const char *)bytes + offset + d.dylib.name.offset;
      size_t capacity = lc.cmdsize - d.dylib.name.offset;
      const char *terminator = memchr(s, 0, capacity);
      if (!terminator) return NO;
      *name = [[NSString alloc] initWithBytes:s length:(NSUInteger)(terminator-s) encoding:NSUTF8StringEncoding];
      if (!*name) return NO;
    }
    offset += lc.cmdsize;
  }
  return offset == end && out->hasUUID && *name;
}

static BOOL diskMetadata(NSData *data, const ImageMetadata *loaded,
                         ImageMetadata *disk, NSString **name) {
  const unsigned char *bytes = data.bytes; size_t length = data.length;
  if (length < 4) return NO;
  uint32_t magic; memcpy(&magic, bytes, 4);
  if (magic == MH_MAGIC || magic == MH_MAGIC_64)
    return metadata(bytes, length, disk, name) && disk->cpu == loaded->cpu &&
      disk->subtype == loaded->subtype;
  if (magic != FAT_CIGAM || length < sizeof(struct fat_header)) return NO;
  struct fat_header fh; memcpy(&fh, bytes, sizeof(fh));
  uint32_t count = OSSwapBigToHostInt32(fh.nfat_arch);
  if (count > 64 || count > (length-sizeof(fh))/sizeof(struct fat_arch)) return NO;
  for (uint32_t i=0;i<count;i++) {
    struct fat_arch a; memcpy(&a, bytes+sizeof(fh)+i*sizeof(a),sizeof(a));
    if ((cpu_type_t)OSSwapBigToHostInt32(a.cputype) != loaded->cpu ||
        (cpu_subtype_t)OSSwapBigToHostInt32(a.cpusubtype) != loaded->subtype) continue;
    size_t start=OSSwapBigToHostInt32(a.offset), size=OSSwapBigToHostInt32(a.size);
    if (start > length || size > length-start) return NO;
    return metadata(bytes+start,size,disk,name) && disk->cpu==loaded->cpu && disk->subtype==loaded->subtype;
  }
  return NO;
}

@interface SHDWLoadedImageRegistry () {
  pthread_mutex_t _lock;
  NSMutableDictionary *_records;
  NSMutableDictionary *_strings;
  NSMutableDictionary *_paths;
  NSMutableDictionary *_canonical;
  NSString *_root;
  uint64_t _sequence;
  uint64_t _identityGeneration;
}
@end
@implementation SHDWLoadedImageRegistry
- (instancetype)initWithSystemRoot:(NSString *)root {
  if ((self=[super init])) {
    pthread_mutex_init(&_lock,NULL); _records=[NSMutableDictionary new];
    _strings=[NSMutableDictionary new]; _paths=[NSMutableDictionary new];
    _canonical=[NSMutableDictionary new]; _root=[root copy];
  }
  return self;
}
- (void)dealloc { pthread_mutex_destroy(&_lock); }
- (void)refreshPath:(NSString *)raw {
  NSDictionary *entries=_paths[raw]; NSValue *value=nil;
  for (NSDictionary *entry in entries.objectEnumerator) {
    NSValue *next=entry[@"canonical"];
    if (!next || (value && value.pointerValue!=next.pointerValue)) { value=nil; break; }
    value=next;
  }
  if ([_canonical[raw] pointerValue] != value.pointerValue) ++_identityGeneration;
  if (value) _canonical[raw]=value; else [_canonical removeObjectForKey:raw];
  if (!entries.count) [_paths removeObjectForKey:raw];
}
- (void)replaceRecord:(NSDictionary *)record key:(NSValue *)key {
  NSString *previous=_records[key][@"raw"];
  if (previous) {
    [_paths[previous] removeObjectForKey:key];
    [self refreshPath:previous];
  }
  if (record) {
    _records[key]=record;
    NSString *raw=record[@"raw"];
    if (!_paths[raw]) _paths[raw]=[NSMutableDictionary new];
    _paths[raw][key]=record;
    [self refreshPath:raw];
  } else [_records removeObjectForKey:key];
}
- (BOOL)unregisterHeader:(const void *)header {
  pthread_mutex_lock(&_lock);
  uint64_t before=_identityGeneration;
  [self replaceRecord:nil key:[NSValue valueWithPointer:header]];
  BOOL changed=before!=_identityGeneration;
  pthread_mutex_unlock(&_lock);
  return changed;
}
- (BOOL)registerHeader:(const void *)header path:(const char *)path
       allowCandidate:(BOOL (^)(const char *))allowCandidate {
  int saved=errno;
  if (!header || !path) return NO;
  NSString *raw=[[NSString alloc] initWithUTF8String:path];
  if (!raw) { errno=saved; return NO; }
  NSValue *key=[NSValue valueWithPointer:header];
  ImageMetadata initial={0}; NSString *initialName=nil;
  struct mach_header initialHeader; memcpy(&initialHeader,header,sizeof(initialHeader));
  size_t initialSize=initialHeader.magic==MH_MAGIC_64?sizeof(struct mach_header_64):sizeof(initialHeader);
  id stamp=nil;
  if ((initialHeader.magic==MH_MAGIC || initialHeader.magic==MH_MAGIC_64) && initialHeader.sizeofcmds<=1024*1024 &&
      metadata(header,initialSize+initialHeader.sizeofcmds,&initial,&initialName))
    stamp=@{ @"uuid":[NSData dataWithBytes:initial.uuid length:16], @"cpu":@(initial.cpu), @"subtype":@(initial.subtype), @"name":initialName };
  pthread_mutex_lock(&_lock);
  NSDictionary *previous=_records[key];
  if (stamp && [previous[@"raw"] isEqualToString:raw] && [previous[@"stamp"] isEqual:stamp]) {
    pthread_mutex_unlock(&_lock); errno=saved; return NO;
  }
  uint64_t beforeGeneration=_identityGeneration;
  uint64_t token=++_sequence;
  [self replaceRecord:@{@"token":@(token),@"raw":raw,@"stamp":stamp ?: [NSData data]} key:key];
  pthread_mutex_unlock(&_lock);
  NSString *candidate=nil;
  if (!systemPath(raw)) {
    struct mach_header h; memcpy(&h,header,sizeof(h));
    size_t hs=h.magic==MH_MAGIC_64?sizeof(struct mach_header_64):sizeof(h);
    if ((h.magic==MH_MAGIC || h.magic==MH_MAGIC_64) && h.sizeofcmds<=1024*1024) {
      ImageMetadata loaded={0};
      if (metadata(header,hs+h.sizeofcmds,&loaded,&candidate) && systemPath(candidate) &&
          (!allowCandidate || allowCandidate(candidate.UTF8String))) {
        NSString *reference=[_root stringByAppendingPathComponent:[candidate substringFromIndex:1]];
        int actual=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC);
        int stock=open(reference.fileSystemRepresentation,O_RDONLY|O_NONBLOCK|O_CLOEXEC);
        BOOL valid=NO;
        struct stat a,b;
        if (actual>=0 && stock>=0 && fstat(actual,&a)==0 && fstat(stock,&b)==0 &&
            S_ISREG(a.st_mode) && S_ISREG(b.st_mode) && a.st_size>0 && a.st_size<=4*1024*1024 &&
            a.st_size==b.st_size && shdw_runtime_image_contents_match(actual,stock)) {
          NSMutableData *contents=[NSMutableData dataWithLength:(NSUInteger)a.st_size];
          ImageMetadata disk={0}; NSString *diskName=nil;
          valid=shdw_runtime_image_pread_exact(actual,contents.mutableBytes,contents.length,0) &&
            diskMetadata(contents,&loaded,&disk,&diskName) &&
            memcmp(loaded.uuid,disk.uuid,16)==0 && [candidate isEqualToString:diskName];
          struct stat afterA,afterB;
          valid=valid && fstat(actual,&afterA)==0 && fstat(stock,&afterB)==0 &&
            shdw_runtime_image_stat_unchanged(&a,&afterA) && shdw_runtime_image_stat_unchanged(&b,&afterB);
        }
        if (actual>=0) close(actual); if (stock>=0) close(stock);
        if (!valid) candidate=nil;
      } else candidate=nil;
    }
  }
  pthread_mutex_lock(&_lock);
  NSDictionary *current=_records[key];
  BOOL changed=NO;
  if ([current[@"token"] unsignedLongLongValue]==token && candidate) {
    NSValue *value=_strings[candidate];
    if (!value && _strings.count<4096) {
      char *copy=strdup(candidate.UTF8String);
      if (copy) { value=[NSValue valueWithPointer:copy]; _strings[candidate]=value; }
    }
    if (value) { [self replaceRecord:@{@"token":@(token),@"raw":raw,@"canonical":value,@"stamp":stamp ?: [NSData data]} key:key]; changed=YES; }
  }
  changed=beforeGeneration!=_identityGeneration;
  pthread_mutex_unlock(&_lock);
  errno=saved;
  return changed;
}
- (const char *)canonicalPath:(const char *)path {
  if (!path) return path;
  int saved=errno; NSString *raw=[[NSString alloc] initWithUTF8String:path];
  if (!raw) { errno=saved; return path; }
  const char *result=path;
  pthread_mutex_lock(&_lock);
  NSValue *value=_canonical[raw];
  if (value) result=value.pointerValue;
  pthread_mutex_unlock(&_lock); errno=saved; return result;
}
@end
