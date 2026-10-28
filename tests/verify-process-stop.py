#!/usr/bin/env python3
"""Run the production termination barrier with deterministic Darwin process fixtures."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r"""
#import <Foundation/Foundation.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <dlfcn.h>
#include <limits.h>
static double now;
static NSMutableDictionary *processes;
static NSMutableArray *signals;
static BOOL stuck, reused, lateWrite, unreadable, recycleEnvironment, hideTerminatingMain, reuseOwnedWebKit;
static BOOL exitIdentityGap, persistentIdentityGap, webIdentityGap, reuseDuringIdentityGap;
static NSUInteger unresolvedReads;
static NSUInteger registryQueries, changeRegistryAt;
static NSMutableArray *pathReads, *identityReads, *environmentReads;
@interface FixtureFBSSystemService : NSObject
+ (id)sharedService;
- (int)pidForApplication:(NSString *)identifier;
@end
@interface FixtureProcessBundle : NSObject
@property NSString *identifier;
@end
@implementation FixtureProcessBundle @end
@interface FixtureProcessIdentity : NSObject
@property id hostIdentity;
@property NSString *embeddedApplicationIdentifier;
@end
@implementation FixtureProcessIdentity @end
@interface FixtureRBSProcessHandle : NSObject
@property NSNumber *processID;
@property NSString *hostBundleID;
+ (id)handleForIdentifier:(NSNumber *)identifier error:(NSError **)error;
- (id)hostProcess;
- (id)identity;
- (id)bundle;
@end
static void Fail(NSString *message) { @throw [NSException exceptionWithName:@"failure" reason:message userInfo:nil]; }
static void Require(BOOL value, NSString *message) { if (!value) Fail(message); }
static BOOL Inside(NSString *path, NSString *root) { return [path hasPrefix:[root stringByAppendingString:@"/"]]; }
static NSString *Canonical(NSString *path) { return path; }
static double MonotonicSeconds(void) { return now; }
static int List(void *, int);
static int PathForPID(int, void *, uint32_t);
static int NameForPID(int, void *, uint32_t);
static int Info(int, int, uint64_t, void *, int);
static void *Lookup(void *, const char *);
static int Sysctl(int *, u_int, void *, size_t *, void *, size_t);
static int Kill(pid_t, int);
static int Sleep(useconds_t);
static char *Realpath(const char *, char *);
static Class ProcessClass(NSString *) __attribute__((unused));
#define NSClassFromString ProcessClass
#define dlsym Lookup
#define sysctl Sysctl
#define kill Kill
#define usleep Sleep
#define realpath Realpath
#include "__SOURCE__"
#undef NSClassFromString
#undef dlsym
#undef sysctl
#undef kill
#undef usleep
#undef realpath
static Class ProcessClass(NSString *name) {
    if([name isEqual:@"FBSSystemService"])return FixtureFBSSystemService.class;
    if([name isEqual:@"RBSProcessHandle"])return FixtureRBSProcessHandle.class;
    return NSClassFromString(name);
}
static void Tick(void) {
    for (NSNumber *pid in [processes.allKeys copy]) {
        NSDictionary *p=processes[pid];
        if (p[@"exit"] && [p[@"exit"] doubleValue] <= now) [processes removeObjectForKey:pid];
    }
    if (reused && now >= 0.2 && processes[@200]) {
        processes[@200]=[@{@"path":@"/other/tool",@"home":@"/other",@"start":@2} mutableCopy];
    }
    if(reuseDuringIdentityGap&&now>=0.2&&processes[@100]) { processes[@100]=[@{@"path":@"/other/tool",@"home":@"/other",@"start":@2,@"bundleID":@"other.app",@"identityUnknownUntil":@0.4} mutableCopy];reuseDuringIdentityGap=NO; }
    if (now >= 0.7 && processes[@200] && [processes[@200][@"home"] isEqual:@"/data/target"]) lateWrite=YES;
}
static int List(void *out,int size) { Tick();NSArray *ids=processes.allKeys;if (!out) return (int)ids.count;Require(size >= (int)(ids.count*sizeof(pid_t)),@"fixture buffer");pid_t *p=out;for (NSUInteger i=0;i<ids.count;i++)p[i]=[ids[i] intValue];return (int)ids.count; }
static int PathForPID(int pid,void *out,uint32_t size) { Tick();[pathReads addObject:@(pid)];if((unreadable&&pid==100)||[processes[@(pid)][@"unreadable"] boolValue]){errno=ENOENT;return 0;}NSString *p=processes[@(pid)][@"path"];if(!p)return 0;strlcpy(out,p.UTF8String,size);return (int)p.length; }
static int NameForPID(int pid,void *out,uint32_t size) { Tick();NSDictionary *p=processes[@(pid)];if(!p)return 0;NSString *name=p[@"name"]?:[p[@"path"] lastPathComponent];strlcpy(out,name.UTF8String,size);return (int)strlen(out); }
static int Info(int pid,int flavor,uint64_t arg,void *out,int size) { (void)arg;Tick();[identityReads addObject:@(pid)];NSDictionary *entry=processes[@(pid)];if([entry[@"identityUnknownForever"] boolValue]||[entry[@"identityUnknownUntil"] doubleValue]>now||(webIdentityGap&&pid==200&&now>=0.2&&now<0.8)){unresolvedReads++;errno=ESRCH;return 0;}if([processes[@(pid)][@"identityUnreadable"] boolValue]){errno=EPERM;return 0;}Require(flavor==3&&size==sizeof(SHDWProcessBSDInfo),@"Darwin ABI");NSDictionary *p=processes[@(pid)];if(!p){errno=ESRCH;return 0;}SHDWProcessBSDInfo *b=out;memset(b,0,size);b->pid=pid;b->startSeconds=[p[@"start"] unsignedLongLongValue];return size; }
static void *Lookup(void *handle,const char *name) { (void)handle;if(!strcmp(name,"proc_listallpids"))return List;if(!strcmp(name,"proc_pidpath"))return PathForPID;if(!strcmp(name,"proc_name"))return NameForPID;if(!strcmp(name,"proc_pidinfo"))return Info;return NULL; }
static int Sysctl(int *m,u_int count,void *out,size_t *size,void *input,size_t inputSize) {
    (void)input;(void)inputSize;
    if(count==2&&m[1]==KERN_ARGMAX){*(int*)out=4096;*size=sizeof(int);return 0;}
    Require(count==3&&m[1]==KERN_PROCARGS2,@"environment query");[environmentReads addObject:@(m[2])];NSDictionary *p=processes[@(m[2])];if([p[@"environmentUnreadable"] boolValue]){errno=EPERM;return -1;}if(!p){errno=ESRCH;return -1;}
    int argc=1;NSMutableData *d=[NSMutableData dataWithBytes:&argc length:sizeof(argc)];
    const char exec[]="/service\0\0/service\0";[d appendBytes:exec length:sizeof(exec)-1];
    for(NSString *key in @[@"HOME",@"CFFIXED_USER_HOME"]){NSString *e=[NSString stringWithFormat:@"%@=%@",key,p[@"home"]];[d appendBytes:e.UTF8String length:strlen(e.UTF8String)+1];}
    char zero=0;[d appendBytes:&zero length:1];Require(d.length<=*size,@"environment bounds");memcpy(out,d.bytes,d.length);*size=d.length;
    if(recycleEnvironment&&m[2]==200){processes[@200][@"start"]=@2;processes[@200][@"home"]=@"/data/other";recycleEnvironment=NO;}
    return 0;
}
@implementation FixtureFBSSystemService
+ (id)sharedService { static id service; if(!service)service=[self new];return service; }
- (int)pidForApplication:(NSString *)identifier {
    Tick();registryQueries++;
    if(changeRegistryAt&&registryQueries==changeRegistryAt){processes[@100]=[@{@"path":@"/other/tool",@"home":@"/other",@"start":@2,@"bundleID":@"other.app"} mutableCopy];}
    NSDictionary *p=processes[@100];
    if(!p||![identifier isEqual:@"target.app"]||[p[@"bundleID"] isEqual:@"other.app"]||(hideTerminatingMain&&p[@"exit"]))return -1;
    return 100;
}
@end
@implementation FixtureRBSProcessHandle
+ (id)handleForIdentifier:(NSNumber *)identifier error:(NSError **)error {
    (void)error;if(!processes[identifier])return nil;FixtureRBSProcessHandle *h=[self new];h.processID=identifier;return h;
}
- (id)hostProcess {
    NSDictionary *p=processes[self.processID];
    if([p[@"hostGoneWhenMainExit"] boolValue]&&(!processes[@100]||processes[@100][@"exit"]))return nil;if(!p||[p[@"unknownOwner"] boolValue])return nil;
    NSString *owner=p[@"owner"];
    if(!owner){NSString *home=p[@"home"];if([home isEqual:@"/data/target"])owner=@"target.app";else if([home isEqual:@"/plugins/extension"])owner=@"target.app.extension";else if([home isEqual:@"/data/safari"])owner=@"com.apple.mobilesafari";else if([home isEqual:@"/data/other"])owner=@"other.app";}
    if(!owner)return nil;FixtureRBSProcessHandle *host=[FixtureRBSProcessHandle new];host.hostBundleID=owner;
    if([p[@"changeOwner"] boolValue]){processes[self.processID][@"owner"]=@"other.app";processes[self.processID][@"changeOwner"]=@NO;}
    return host;
}
- (id)identity {
    NSDictionary *p=processes[self.processID];if(!p||[p[@"unknownOwner"] boolValue]||[p[@"identityOwnerUnavailable"] boolValue])return nil;
    NSString *owner=p[@"owner"];if(!owner){NSString *home=p[@"home"];if([home isEqual:@"/data/target"])owner=@"target.app";else if([home isEqual:@"/plugins/extension"])owner=@"target.app.extension";else if([home isEqual:@"/data/safari"])owner=@"com.apple.mobilesafari";else if([home isEqual:@"/data/other"])owner=@"other.app";}
    if(!owner)return nil;FixtureProcessIdentity *identity=[FixtureProcessIdentity new], *host=[FixtureProcessIdentity new];host.embeddedApplicationIdentifier=owner;identity.hostIdentity=host;
    if([p[@"changeOwner"] boolValue]){processes[self.processID][@"owner"]=@"other.app";processes[self.processID][@"changeOwner"]=@NO;}
    return identity;
}
- (id)bundle { FixtureProcessBundle *bundle=[FixtureProcessBundle new];bundle.identifier=self.hostBundleID;return bundle; }
@end
static int Kill(pid_t pid,int signal) { Tick();if(!processes[@(pid)]){errno=ESRCH;return -1;}if(!signal)return 0;Require(signal==SIGTERM,@"unsafe termination signal");[signals addObject:@(pid)];if(exitIdentityGap&&pid==100){processes[@100][@"identityUnknownUntil"]=@(now+0.4);processes[@100][@"exit"]=@(now+0.6);return 0;}if(persistentIdentityGap&&pid==100){processes[@100][@"identityUnknownForever"]=@YES;return 0;}if(reuseOwnedWebKit&&pid==200){reuseOwnedWebKit=NO;processes[@200][@"start"]=@2;return 0;}if(!(stuck&&pid==200))processes[@(pid)][@"exit"]=@(now+0.2);return 0; }
static int Sleep(useconds_t delay) { now+=delay/1000000.0;Tick();return 0; }
static char *Realpath(const char *path,char *out) { for(NSDictionary *p in processes.allValues)if([p[@"badCanonical"] boolValue]&&[p[@"path"] isEqual:@(path)]){errno=ENOENT;return NULL;}strlcpy(out,path,PATH_MAX);return out; }
static NSDictionary *Fixture(BOOL natural) {
    now=0;stuck=NO;reused=NO;lateWrite=NO;unreadable=NO;recycleEnvironment=NO;hideTerminatingMain=NO;reuseOwnedWebKit=NO;exitIdentityGap=NO;persistentIdentityGap=NO;webIdentityGap=NO;reuseDuringIdentityGap=NO;unresolvedReads=0;registryQueries=0;changeRegistryAt=0;pathReads=[NSMutableArray new];identityReads=[NSMutableArray new];environmentReads=[NSMutableArray new];signals=[NSMutableArray new];processes=[NSMutableDictionary new];
    NSString *prefix=@"/System/Library/Frameworks/WebKit.framework/XPCServices";
    NSString *(^service)(NSString*)=^NSString*(NSString *name){NSString *s=[@"com.apple.WebKit." stringByAppendingString:name];return [[prefix stringByAppendingPathComponent:[s stringByAppendingString:@".xpc"]] stringByAppendingPathComponent:s];};
    processes[@100]=[@{@"path":@"/bundle/Target.app/main",@"home":@"/data/target",@"start":@1} mutableCopy];
    processes[@200]=[@{@"path":service(@"Networking"),@"home":@"/data/target",@"start":@1} mutableCopy];
    if(natural)processes[@200][@"exit"]=@1.0;
    processes[@201]=[@{@"path":service(@"Networking"),@"home":@"/data/safari",@"start":@1} mutableCopy];
    processes[@202]=[@{@"path":service(@"WebContent"),@"home":@"/data/other",@"start":@1} mutableCopy];
    return @{@"bundleID":@"target.app",@"bundlePath":@"/bundle/Target.app",@"executables":@[@{@"path":@"/bundle/Target.app/main"}],@"containers":@[@{@"identifier":@"target.app",@"path":@"/data/target"},@{@"identifier":@"group.target",@"path":@"/shared/group"}]};
}
static void Unrelated(void) { Require(processes[@201]&&processes[@202],@"unrelated WebKit terminated");Require(![signals containsObject:@201]&&![signals containsObject:@202],@"signal escaped target"); }
int main(void) { @autoreleasepool {
    NSDictionary *target=Fixture(YES);Require(!TargetStopped(target),@"live target accepted");NSDictionary *result=Stop(target);Require(TargetStopped(target),@"stopped target rejected");
    Require(lateWrite&&now>=1.3&&[result[@"webKitProcesses"] intValue]==1,@"did not wait for late writer");
    Require([signals isEqual:@[@100]],@"natural WebKit exit interrupted");Unrelated();
    target=Fixture(NO);result=Stop(target);Require(now>=3.5&&[signals isEqual:@[@100,@200]],@"WebKit graceful fallback missing");Unrelated();
    target=Fixture(NO);stuck=YES;BOOL failed=NO;@try{Stop(target);}@catch(NSException *e){failed=[e.reason containsString:@"no application data was cleared"];}
    Require(failed&&now>=15&&processes[@200],@"timeout permitted deletion");Unrelated();
    target=Fixture(NO);reused=YES;Stop(target);Require([signals isEqual:@[@100]]&&processes[@200],@"reused PID signalled");Unrelated();
    target=Fixture(NO);processes[@200][@"home"]=@"/shared/group";Stop(target);Require([signals isEqual:@[@100]]&&processes[@200],@"shared group treated as ownership");Unrelated();
    NSMutableDictionary *extensionTarget=[Fixture(YES) mutableCopy];
    extensionTarget[@"identifiers"]=@[@"target.app",@"target.app.extension"];
    extensionTarget[@"containers"]=[extensionTarget[@"containers"] arrayByAddingObject:@{@"identifier":@"target.app.extension",@"path":@"/plugins/extension"}];
    processes[@203]=[processes[@200] mutableCopy];processes[@203][@"home"]=@"/plugins/extension";
    result=Stop(extensionTarget);Require([result[@"webKitProcesses"] intValue]==2&&!processes[@203],@"extension WebKit escaped shutdown barrier");Unrelated();
    target=Fixture(YES);Stop(target);VerifyStoppedTarget(target, ^{});
    BOOL relaunched=NO;@try{VerifyStoppedTarget(target, ^{processes[@100]=[@{@"path":@"/bundle/Target.app/main",@"home":@"/data/target",@"start":@3} mutableCopy];});}@catch(NSException *e){relaunched=[e.reason containsString:@"during final verification"];}
    Require(relaunched,@"relaunch after file verification falsely passed final check");
    target=Fixture(YES);Stop(target);
    NSString *latePath=[NSTemporaryDirectory() stringByAppendingPathComponent:[@"shadow-late-recheck-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    BOOL lateRejected=NO;@try { VerifyCleanupSteps(target,@[@"files",@"keychain"],^(NSString *step){
        if([step isEqual:@"keychain"])Require([@"late writer" writeToFile:latePath atomically:YES encoding:NSUTF8StringEncoding error:NULL],@"late writer fixture");
        else if([step isEqual:@"files"])Require(![NSFileManager.defaultManager fileExistsAtPath:latePath],@"late write remained");
    }); } @catch(NSException *e) { lateRejected=[e.reason isEqual:@"late write remained"]; }
    Require(lateRejected,@"late writer during credential check escaped final filesystem scan");
    Require([NSFileManager.defaultManager removeItemAtPath:latePath error:NULL],@"remove late write fixture");
    target=Fixture(YES);processes[@300]=[@{@"path":@"/old/ShadowManager",@"home":@"/other",@"start":@1,@"unreadable":@YES} mutableCopy];
    Stop(target);Require(processes[@300]&&![signals containsObject:@300]&&![pathReads containsObject:@300]&&![identityReads containsObject:@300],@"unrelated unreadable process inspected");
    target=Fixture(NO);unreadable=YES;hideTerminatingMain=YES;Stop(target);Require([signals containsObject:@100]&&![pathReads containsObject:@100],@"bundle-owned main PID required path inspection");
    target=Fixture(NO);processes[@100][@"identityUnreadable"]=@YES;failed=NO;@try{Stop(target);}@catch(NSException *e){failed=[e.reason containsString:@"Cannot verify application process identity"];}
    Require(failed&&!signals.count,@"unknown main identity permitted stop");
    target=Fixture(YES);[processes removeObjectForKey:@200];exitIdentityGap=YES;hideTerminatingMain=YES;Stop(target);Require(unresolvedReads>=2&&now>=0.9&&[signals isEqual:@[@100]],@"normal exit identity gap rejected or signalled again");Unrelated();
    target=Fixture(YES);[processes removeObjectForKey:@200];persistentIdentityGap=YES;hideTerminatingMain=YES;failed=NO;@try{Stop(target);}@catch(NSException *e){failed=[e.reason containsString:@"no application data was cleared"]; }Require(failed&&now>=15&&[signals isEqual:@[@100]]&&processes[@100],@"persistent unknown exit accepted or signalled again");Unrelated();
    target=Fixture(YES);webIdentityGap=YES;Stop(target);Require(unresolvedReads>=2&&[signals isEqual:@[@100]]&&now>=1.3,@"WebKit grace identity gap rejected");Unrelated();
    target=Fixture(YES);[processes removeObjectForKey:@200];exitIdentityGap=YES;reuseDuringIdentityGap=YES;Stop(target);Require(unresolvedReads>=2&&processes[@100]&&[processes[@100][@"start"] intValue]==2&&[signals isEqual:@[@100]],@"unknown reused PID signalled");Unrelated();
    target=Fixture(NO);NSDictionary *authorization=TargetProcesses(target)[@100];processes[@100][@"identityUnknownUntil"]=@0.3;Require(!SignalProcess(@100,authorization)&&!signals.count,@"unresolved PID received signal");now=0.3;Require(SignalProcess(@100,authorization)&&[signals isEqual:@[@100]],@"resolved signal authorization was not retryable");

    target=Fixture(YES);processes[@300]=[@{@"path":@"/other/main",@"home":@"/other",@"start":@1} mutableCopy];Stop(target);Require(processes[@300]&&![signals containsObject:@300]&&![identityReads containsObject:@300],@"same-name unrelated process signalled");
    target=Fixture(YES);processes[@300]=[@{@"path":@"/bundle/Target.app/main",@"name":@"main",@"home":@"/data/target",@"start":@1,@"unreadable":@YES} mutableCopy];failed=NO;@try{Stop(target);}@catch(NSException *e){failed=YES;}Require(failed&&!signals.count,@"unreadable additional target ignored");
    target=Fixture(YES);processes[@201][@"unreadable"]=@YES;processes[@201][@"environmentUnreadable"]=@YES;Stop(target);Require(![pathReads containsObject:@201]&&![identityReads containsObject:@201]&&![environmentReads containsObject:@201],@"unrelated owned WebKit inspected");Unrelated();
    target=Fixture(YES);processes[@200][@"changeOwner"]=@YES;Stop(target);Require(processes[@200]&&![signals containsObject:@200],@"changed WebKit owner signalled");
    target=Fixture(NO);reuseOwnedWebKit=YES;Stop(target);Require([signals isEqual:@[@100,@200,@200]]&&!processes[@200],@"recycled owned WebKit retained old signal marker");Unrelated();
    target=Fixture(NO);hideTerminatingMain=YES;processes[@200][@"hostGoneWhenMainExit"]=@YES;Stop(target);Require([signals isEqual:@[@100,@200]]&&![environmentReads containsObject:@200],@"host disappearance lost identity ownership");Unrelated();
    target=Fixture(YES);processes[@200][@"identityOwnerUnavailable"]=@YES;Stop(target);Require(![environmentReads containsObject:@200],@"live host ownership fallback ignored");Unrelated();

    target=Fixture(YES);processes[@300]=[@{@"path":@"/old/ShadowManager",@"home":@"/other",@"start":@1,@"badCanonical":@YES} mutableCopy];Stop(target);Require(![pathReads containsObject:@300]&&![identityReads containsObject:@300],@"unrelated canonicalization required");
    target=Fixture(YES);processes[@200][@"unreadable"]=@YES;failed=NO;@try{Stop(target);}@catch(NSException *e){failed=YES;}Require(failed&&!signals.count,@"unreadable owned WebKit ignored");
    target=Fixture(YES);processes[@200][@"unknownOwner"]=@YES;processes[@200][@"environmentUnreadable"]=@YES;failed=NO;@try{Stop(target);}@catch(NSException *e){failed=[e.reason containsString:@"Cannot identify the application owning a WebKit process"]; }Require(failed&&!signals.count,@"unknown WebKit owner treated as stopped");
    for(NSNumber *length in @[@15,@16,@31,@32]) {
        NSMutableDictionary *extended=[Fixture(YES) mutableCopy];NSString *executable=@"TargetExtensionExecutableWithLongName";NSString *path=[@"/bundle/Target.app/PlugIns/Extension.appex" stringByAppendingPathComponent:executable];
        extended[@"executables"]=[extended[@"executables"] arrayByAddingObject:@{@"path":path}];processes[@203]=[@{@"path":path,@"name":[executable substringToIndex:length.unsignedIntegerValue],@"home":@"/plugins/extension",@"start":@1} mutableCopy];
        NSDictionary *stopped=Stop(extended);Require([signals containsObject:@203]&&!processes[@203]&&[stopped[@"applicationProcesses"] intValue]==2,@"truncated extension name escaped stop");Unrelated();
    }

    target=Fixture(YES);changeRegistryAt=2;Stop(target);Require(processes[@100]&&![signals containsObject:@100],@"registration race signalled another application");
    target=Fixture(YES);[processes removeObjectForKey:@100];[processes removeObjectForKey:@200];Stop(target);Require(!signals.count,@"absent target signalled unrelated processes");

    target=Fixture(NO);processes[@200][@"unknownOwner"]=@YES;recycleEnvironment=YES;Stop(target);Require([signals isEqual:@[@100]]&&processes[@200],@"classification paired stale environment with new identity");Unrelated();
    puts("process shutdown: bundle PID scope, unrelated unreadable processes, WebKit ownership, exit identity gaps, delayed flush, SIGTERM, timeout and PID reuse passed");
}return 0;}
"""
with tempfile.TemporaryDirectory(prefix="shadow-process-stop-") as directory:
    root = Path(directory)
    source = root / "main.m"
    source.write_text(HARNESS.replace("__SOURCE__", str(ROOT / "src/ShadowCleaner/ProcessStop.inc")))
    binary = root / "check"
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-framework", "Foundation", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
