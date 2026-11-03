#!/usr/bin/env python3
"""Exercise archive recovery despite source changes after capture completion."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#import "__ARCHIVE_HEADER__"
#include <sys/stat.h>
#include <unistd.h>
static void Require(BOOL value,NSString *message) {if(!value){fprintf(stderr,"FAIL: %s\n",message.UTF8String);exit(1);}}
static void Mk(NSString *path) {Require([NSFileManager.defaultManager createDirectoryAtPath:path withIntermediateDirectories:YES attributes:nil error:NULL],@"create fixture directory");}
static void Put(NSString *path,NSString *value) {Require([value writeToFile:path atomically:NO encoding:NSUTF8StringEncoding error:NULL],@"write fixture file");}
static NSString *Text(NSString *path) {return [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL];}
int main(int argc,char **argv){@autoreleasepool{
    Require(argc==3,@"fixture arguments");NSString *base=@(argv[1]),*scenario=@(argv[2]);Mk(base);
    NSString *source=[base stringByAppendingPathComponent:@"source"],*destination=[base stringByAppendingPathComponent:@"destination"],*archive=[base stringByAppendingPathComponent:@"backup.tar.zst"];
    Mk(source);Mk(destination);Mk([source stringByAppendingPathComponent:@"nested"]);
    NSString *value=[source stringByAppendingPathComponent:@"value"];
    Put(value,@"original");Require(!chmod(value.fileSystemRepresentation,0644),@"set capture mode");
    Put([source stringByAppendingPathComponent:@"nested/shared"],@"shared-content");
    Require(!link([source stringByAppendingPathComponent:@"nested/shared"].fileSystemRepresentation,[source stringByAppendingPathComponent:@"shared-copy"].fileSystemRepresentation),@"create hardlink");
    Require(!symlink("value",[source stringByAppendingPathComponent:@"alias"].fileSystemRepresentation),@"create symbolic link");
    NSDictionary *expected=@{@".hidden":@"hidden-data",@"empty":@"",@"Library/Caches/cache":@"cached-data",@"tmp/temporary":@"temporary-data"};
    for(NSString *name in expected){NSString *path=[source stringByAppendingPathComponent:name];Mk(path.stringByDeletingLastPathComponent);Put(path,expected[name]);}
    Require(!chmod([source stringByAppendingPathComponent:@".hidden"].fileSystemRepresentation,0644),@"set hidden file mode");
    Mk([source stringByAppendingPathComponent:@"empty-directory"]);
    NSString *group=[base stringByAppendingPathComponent:@"group"],*restoredGroup=[base stringByAppendingPathComponent:@"restored-group"];
    Mk(group);Mk(restoredGroup);Put([group stringByAppendingPathComponent:@"shared-data"],@"group-content");
    __block BOOL mutated=NO;NSError *error=nil;
    NSDictionary *info=[SHDWStateArchive captureRoots:@{@"containers/data":source,@"containers/group":group} payloads:@{} toPath:archive progress:^(NSDictionary *event){
        BOOL during=[scenario isEqual:@"during-read"];
        if(!mutated && ((during && [event[@"phase"]isEqual:@"capture"] && [event[@"bytes"]unsignedLongLongValue]>0) || (!during && [event[@"phase"]isEqual:@"verify_archive"]))){
            mutated=YES;
            if([scenario isEqual:@"content"])Put(value,@"changed-after-capture");
            else if([scenario isEqual:@"entries"]){Require([NSFileManager.defaultManager removeItemAtPath:[source stringByAppendingPathComponent:@"nested"] error:NULL],@"remove captured entries");Put([source stringByAppendingPathComponent:@"new-entry"],@"new");}
            else if([scenario isEqual:@"remove-root"])Require([NSFileManager.defaultManager removeItemAtPath:source error:NULL],@"remove completed capture root");
            else Require(!chmod((during?[source stringByAppendingPathComponent:@".hidden"]:value).fileSystemRepresentation,0600),@"simulate source metadata drift");
        }
    } error:&error];
    Require(mutated,@"source mutation injection reached selected capture stage");
    if([scenario isEqual:@"during-read"]){Require(!info && error,@"source mutation while reading remains rejected");puts("archive recovery during-read rejection passed");return 0;}
    Require(info!=nil,[NSString stringWithFormat:@"completed archive survives source mutation: %@",error]);
    Require([SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],@"captured archive independently verifies");
    NSData *originalArchive=[NSData dataWithContentsOfFile:archive];Require(originalArchive.length>0,@"archive remains available");
    NSDictionary *roots=@{@"containers/data":destination,@"containers/group":restoredGroup};
    Require([SHDWStateArchive restorePath:archive info:info roots:roots progress:nil error:&error],[NSString stringWithFormat:@"restore completed archive: %@",error]);
    Require([Text([destination stringByAppendingPathComponent:@"value"])isEqual:@"original"] && [Text([destination stringByAppendingPathComponent:@"alias"])isEqual:@"original"],@"original captured content and symbolic link restored");
    for(NSString *name in expected)Require([Text([destination stringByAppendingPathComponent:name])isEqual:expected[name]],[@"restore every original entry: "stringByAppendingString:name]);
    BOOL directory=NO;Require([NSFileManager.defaultManager fileExistsAtPath:[destination stringByAppendingPathComponent:@"empty-directory"] isDirectory:&directory] && directory,@"restore empty directory");
    Require([Text([restoredGroup stringByAppendingPathComponent:@"shared-data"])isEqual:@"group-content"],@"restore shared container content");
    Require([Text([destination stringByAppendingPathComponent:@"nested/shared"])isEqual:@"shared-content"],@"restore captured file even after source entry was removed");
    struct stat shared,copy;Require(!stat([destination stringByAppendingPathComponent:@"nested/shared"].fileSystemRepresentation,&shared)&&!stat([destination stringByAppendingPathComponent:@"shared-copy"].fileSystemRepresentation,&copy)&&shared.st_ino==copy.st_ino,@"hardlink identity preserved");
    error=nil;Require([SHDWStateArchive verifyRoots:roots info:info progress:nil error:&error],[NSString stringWithFormat:@"restored entries retain full validation: %@",error]);
    NSMutableData *damaged=[originalArchive mutableCopy];((unsigned char *)damaged.mutableBytes)[damaged.length/2]^=0xff;
    NSString *corrupt=[base stringByAppendingPathComponent:@"corrupt.tar.zst"];Require([damaged writeToFile:corrupt atomically:NO],@"create independently corrupted copy");error=nil;
    Require(![SHDWStateArchive verifyPath:corrupt info:info progress:nil error:&error]&&error,@"damaged archive still rejected");
    Require([[NSData dataWithContentsOfFile:archive]isEqual:originalArchive],@"validation failure leaves original archive unchanged");error=nil;
    Require([SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],@"original archive remains usable after failed validation");
    printf("archive recovery %s passed\n",scenario.UTF8String);
}return 0;}
'''


def main():
    prefix = Path(os.environ.get("ARCHIVE_PREFIX", "/opt/homebrew/opt/libarchive"))
    zstd = Path(os.environ.get("ZSTD_PREFIX", "/opt/homebrew/opt/zstd"))
    with tempfile.TemporaryDirectory(prefix="shadow-archive-recovery-") as directory:
        temp = Path(directory).resolve()
        source = temp / "main.m"
        source.write_text(HARNESS.replace("__ARCHIVE_HEADER__", str(ROOT / "src/AppState/Archive.h"))
                         )
        binary = temp / "check"
        command = ["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-g", "-O1", "-framework", "Foundation", "-I" + str(prefix / "include"), "-L" + str(prefix / "lib"), "-L" + str(zstd / "lib"), "-Wl,-rpath," + str(prefix / "lib"), "-Wl,-rpath," + str(zstd / "lib"), str(source), str(ROOT / "src/AppState/Archive.m"), "-larchive", "-lzstd", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-o", str(binary)]
        subprocess.run(command, check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        failed = []
        for scenario in ("content", "metadata", "entries", "remove-root", "during-read"):
            result = subprocess.run([str(binary), str(temp / scenario), scenario], env=environment)
            if result.returncode:
                failed.append(scenario)
        if failed:
            raise SystemExit("Archive recovery scenarios failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
