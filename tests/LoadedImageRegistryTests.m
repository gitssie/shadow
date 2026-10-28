#import <Foundation/Foundation.h>
#import <mach-o/loader.h>
#import <mach-o/fat.h>
#import <mach/machine.h>
#import <libkern/OSByteOrder.h>
#import <assert.h>
#import "../src/Shadow.framework/LoadedImageRegistry.h"

static NSMutableData *image(NSString *name, unsigned char uuid) {
  size_t idSize=(sizeof(struct dylib_command)+name.length+1+7)&~(size_t)7;
  struct mach_header_64 h={.magic=MH_MAGIC_64,.cputype=CPU_TYPE_ARM64,.cpusubtype=CPU_SUBTYPE_ARM64_ALL,
    .filetype=MH_DYLIB,.ncmds=2,.sizeofcmds=(uint32_t)(sizeof(struct uuid_command)+idSize)};
  NSMutableData *data=[NSMutableData dataWithBytes:&h length:sizeof(h)];
  struct uuid_command u={.cmd=LC_UUID,.cmdsize=sizeof(u)};u.uuid[0]=uuid;
  [data appendBytes:&u length:sizeof(u)];
  NSMutableData *idData=[NSMutableData dataWithLength:idSize];
  struct dylib_command d={.cmd=LC_ID_DYLIB,.cmdsize=(uint32_t)idSize};d.dylib.name.offset=sizeof(d);
  memcpy(idData.mutableBytes,&d,sizeof(d));strcpy((char *)idData.mutableBytes+sizeof(d),name.UTF8String);
  [data appendData:idData];return data;
}
static void writeData(NSData *data, NSString *path) {
  assert([[NSFileManager defaultManager] createDirectoryAtPath:path.stringByDeletingLastPathComponent
    withIntermediateDirectories:YES attributes:nil error:nil]);
  assert([data writeToFile:path atomically:YES]);
}
int main(void) { @autoreleasepool {
  NSString *root=[NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
  NSString *logical=@"/usr/lib/RegistryTest.dylib";
  NSString *reference=[root stringByAppendingString:logical];
  NSString *actual=[root stringByAppendingPathComponent:@"actual.dylib"];
  NSMutableData *loaded=image(logical,7);writeData(loaded,reference);writeData(loaded,actual);
  SHDWLoadedImageRegistry *registry=[[SHDWLoadedImageRegistry alloc] initWithSystemRoot:root];
  BOOL (^allow)(const char *)=^BOOL(const char *p){return strcmp(p,logical.UTF8String)==0;};
  errno=EDOM;
  assert([registry registerHeader:loaded.bytes path:actual.fileSystemRepresentation allowCandidate:allow]);
  assert(errno==EDOM);
  const char *saved=[registry canonicalPath:actual.UTF8String];assert(strcmp(saved,logical.UTF8String)==0);
  assert([[NSFileManager defaultManager] removeItemAtPath:actual error:nil]);
  assert(strcmp([registry canonicalPath:actual.UTF8String],logical.UTF8String)==0);
  assert(![registry registerHeader:loaded.bytes path:actual.fileSystemRepresentation allowCandidate:allow]);
  [registry unregisterHeader:loaded.bytes];
  assert(strcmp([registry canonicalPath:actual.UTF8String],actual.UTF8String)==0);
  assert(strcmp(saved,logical.UTF8String)==0);
  writeData(loaded,actual);
  assert(![registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:^BOOL(const char *p){(void)p;return NO;}]);
  [registry unregisterHeader:loaded.bytes];
  NSMutableData *wrong=image(logical,8);
  assert(![registry registerHeader:wrong.bytes path:actual.UTF8String allowCandidate:allow]);
  [registry unregisterHeader:wrong.bytes];
  NSMutableData *bad=image(@"/usr/lib/../Bad.dylib",7);
  assert(![registry registerHeader:bad.bytes path:actual.UTF8String allowCandidate:allow]);
  NSMutableData *relative=image(@"@rpath/RegistryTest.dylib",7);
  assert(![registry registerHeader:relative.bytes path:actual.UTF8String allowCandidate:allow]);
  NSMutableData *malformed=[loaded mutableCopy];
  ((struct uuid_command *)((char *)malformed.mutableBytes+sizeof(struct mach_header_64)))->cmdsize=0;
  assert(![registry registerHeader:malformed.bytes path:actual.UTF8String allowCandidate:allow]);
  [registry unregisterHeader:bad.bytes];
  [registry unregisterHeader:relative.bytes];
  [registry unregisterHeader:malformed.bytes];
  assert([registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:allow]);
  ((struct uuid_command *)((char *)loaded.mutableBytes+sizeof(struct mach_header_64)))->uuid[0]=9;
  assert([registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:allow]);
  assert(strcmp([registry canonicalPath:actual.UTF8String],actual.UTF8String)==0);
  [registry unregisterHeader:loaded.bytes];
  loaded=image(logical,7);
  struct fat_header fh={.magic=OSSwapHostToBigInt32(FAT_MAGIC),.nfat_arch=OSSwapHostToBigInt32(1)};
  struct fat_arch fa={.cputype=(cpu_type_t)OSSwapHostToBigInt32(CPU_TYPE_ARM64),
    .cpusubtype=(cpu_subtype_t)OSSwapHostToBigInt32(CPU_SUBTYPE_ARM64_ALL),
    .offset=OSSwapHostToBigInt32(4096),.size=OSSwapHostToBigInt32((uint32_t)loaded.length)};
  NSMutableData *fat=[NSMutableData dataWithLength:4096];memcpy(fat.mutableBytes,&fh,sizeof(fh));
  memcpy((char *)fat.mutableBytes+sizeof(fh),&fa,sizeof(fa));[fat appendData:loaded];
  writeData(fat,reference);writeData(fat,actual);
  assert([registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:allow]);
  [registry unregisterHeader:loaded.bytes];
  NSMutableData *duplicate=[loaded mutableCopy];
  assert([registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:allow]);
  assert([registry registerHeader:duplicate.bytes path:actual.UTF8String allowCandidate:allow]);
  [registry unregisterHeader:loaded.bytes];
  assert(strcmp([registry canonicalPath:actual.UTF8String],logical.UTF8String)==0);
  ((struct uuid_command *)((char *)duplicate.mutableBytes+sizeof(struct mach_header_64)))->uuid[0]=10;
  assert([registry registerHeader:duplicate.bytes path:actual.UTF8String allowCandidate:allow]);
  assert(strcmp([registry canonicalPath:actual.UTF8String],actual.UTF8String)==0);
  [registry unregisterHeader:duplicate.bytes];
  char invalidUTF8[]={(char)0xff,0};
  errno=EDOM;assert([registry canonicalPath:invalidUTF8]==invalidUTF8);assert(errno==EDOM);
  assert([registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:allow]);
  size_t nameOffset=sizeof(struct mach_header_64)+sizeof(struct uuid_command)+sizeof(struct dylib_command);
  char *installName=(char *)loaded.mutableBytes+nameOffset;
  char previousName=installName[strlen(installName)-7];
  installName[strlen(installName)-7]^=1;
  assert([registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:allow]);
  assert(strcmp([registry canonicalPath:actual.UTF8String],actual.UTF8String)==0);
  installName[strlen(installName)-7]=previousName;
  [registry unregisterHeader:loaded.bytes];
  dispatch_semaphore_t entered=dispatch_semaphore_create(0),release=dispatch_semaphore_create(0),done=dispatch_semaphore_create(0);
  dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^{
    assert(![registry registerHeader:loaded.bytes path:actual.UTF8String allowCandidate:^BOOL(const char *p){
      (void)p;dispatch_semaphore_signal(entered);dispatch_semaphore_wait(release,DISPATCH_TIME_FOREVER);return YES;
    }]);dispatch_semaphore_signal(done);
  });
  assert(dispatch_semaphore_wait(entered,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC))==0);
  [registry unregisterHeader:loaded.bytes];dispatch_semaphore_signal(release);
  assert(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC))==0);
  assert(strcmp([registry canonicalPath:actual.UTF8String],actual.UTF8String)==0);
  assert([[NSFileManager defaultManager] removeItemAtPath:root error:nil]);
  puts("loaded image registry: verified mapping, rejected inputs, readonly lookup and lifecycle tests passed");
}return 0;}
