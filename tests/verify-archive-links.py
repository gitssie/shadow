#!/usr/bin/env python3
"""Exercise production archive link relocation across independent container paths."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#import "__ARCHIVE_HEADER__"
#include <sys/stat.h>
#include <sys/attr.h>
#include <fcntl.h>
#include <unistd.h>
static void Check(BOOL value, NSString *message) { if (!value) { fprintf(stderr,"FAIL: %s\n",message.UTF8String);exit(1); } }
static void Mk(NSString *path) { Check([NSFileManager.defaultManager createDirectoryAtPath:path withIntermediateDirectories:YES attributes:nil error:NULL],@"make directory"); }
static void Put(NSString *path, NSString *value) { Mk(path.stringByDeletingLastPathComponent);Check([value writeToFile:path atomically:NO encoding:NSUTF8StringEncoding error:NULL],@"write file"); }
static void Link(NSString *path, NSString *target) { Check(!symlink(target.fileSystemRepresentation,path.fileSystemRepresentation),@"create link"); }
static NSString *Target(NSString *path) { return [NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:path error:NULL]; }
static NSString *Read(NSString *path) { return [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL]; }
static void Retarget(NSString *path, NSString *target) {
    struct stat st;Check(!lstat(path.fileSystemRepresentation,&st)&&!unlink(path.fileSystemRepresentation),@"replace link");Link(path,target);
    Check(!fchmodat(AT_FDCWD,path.fileSystemRepresentation,st.st_mode&07777,AT_SYMLINK_NOFOLLOW),@"restore link mode");
    struct timespec times[2]={{.tv_nsec=UTIME_OMIT},st.st_mtimespec};Check(!utimensat(AT_FDCWD,path.fileSystemRepresentation,times,AT_SYMLINK_NOFOLLOW),@"restore link mtime");
    struct attrlist attrs={.bitmapcount=ATTR_BIT_MAP_COUNT,.commonattr=ATTR_CMN_CRTIME};Check(!setattrlist(path.fileSystemRepresentation,&attrs,&st.st_birthtimespec,sizeof(st.st_birthtimespec),FSOPT_NOFOLLOW),@"restore link birthtime");
}
int main(int argc,char **argv) { @autoreleasepool {
    Check(argc==2,@"fixture argument");NSString *base=@(argv[1]);Mk(base);
    NSString *source=[base stringByAppendingPathComponent:@"source/old-application"];
    NSString *group=[base stringByAppendingPathComponent:@"source/old-group"];
    NSString *destination=[base stringByAppendingPathComponent:@"destination/new-application"];
    NSString *destinationGroup=[base stringByAppendingPathComponent:@"destination/new-group"];
    NSString *outside=[base stringByAppendingPathComponent:@"outside"];
    Mk([source stringByAppendingPathComponent:@"Library"]);Mk([source stringByAppendingPathComponent:@"Nested/Sub"]);
    Put([source stringByAppendingPathComponent:@"Documents/value"],@"documents");
    Put([source stringByAppendingPathComponent:@"Nested/Documents/value"],@"alias-parent");
    Mk([group stringByAppendingPathComponent:@"deep/sub"]);Put([group stringByAppendingPathComponent:@"deep/value"],@"group-parent");
    Put([outside stringByAppendingPathComponent:@"secret"],@"outside-data-not-archived");Mk([outside stringByAppendingPathComponent:@"sub"]);
    Link([source stringByAppendingPathComponent:@"alias"],@"Nested/Sub");
    Link([source stringByAppendingPathComponent:@"group-alias"],[group stringByAppendingPathComponent:@"deep/sub"]);
    Link([source stringByAppendingPathComponent:@"outside-alias"],[outside stringByAppendingPathComponent:@"sub"]);
    NSDictionary *suffixes=@{@"dot":@"/Library/./../Documents/value",@"parent-alias":@"/alias/../Documents/value",@"group-parent":@"/group-alias/../value",@"missing-final":@"/Library/../Documents/not-created"};
    for(NSString *name in suffixes)Link([source stringByAppendingPathComponent:name],[source stringByAppendingString:suffixes[name]]);
    NSString *outsideTarget=[outside stringByAppendingPathComponent:@"secret"];
    NSString *escaped=[source stringByAppendingString:@"/../../outside/secret"];
    NSString *outsideParent=[source stringByAppendingString:@"/outside-alias/../secret"];
    Link([source stringByAppendingPathComponent:@"outside"],outsideTarget);
    Link([source stringByAppendingPathComponent:@"escape"],escaped);
    Link([source stringByAppendingPathComponent:@"outside-parent"],outsideParent);
    Link([source stringByAppendingPathComponent:@"relative"],@"alias/../Documents/value");
    Check([source hasPrefix:@"/private/var/"],@"canonical host /var fixture");
    NSString *varTarget=[[source substringFromIndex:8] stringByAppendingString:@"/Library/../Documents/value"];
    Link([source stringByAppendingPathComponent:@"var-alias"],varTarget);
    Link([source stringByAppendingPathComponent:@"loop-a"],@"loop-b");Link([source stringByAppendingPathComponent:@"loop-b"],@"loop-a");
    Link([source stringByAppendingPathComponent:@"loop-dot"],[source stringByAppendingString:@"/loop-a/../Documents/value"]);
    NSString *archive=[base stringByAppendingPathComponent:@"backup.tar.zst"];
    NSDictionary *roots=@{@"containers/data":source,@"containers/group":group};NSError *error=nil;
    NSDictionary *info=[SHDWStateArchive captureRoots:roots payloads:@{} toPath:archive progress:nil error:&error];Check(info!=nil,error.localizedDescription);
    Check([SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],error.localizedDescription);
    for(NSDictionary *entry in info[@"entries"])Check(![entry[@"path"] containsString:@"secret"],@"external payload entered archive");
    Check([NSFileManager.defaultManager removeItemAtPath:source error:&error]&&[NSFileManager.defaultManager removeItemAtPath:group error:&error],@"remove old roots before restore");
    Mk(destination);Mk(destinationGroup);NSDictionary *restored=@{@"containers/data":destination,@"containers/group":destinationGroup};
    Check([SHDWStateArchive restorePath:archive info:info roots:restored progress:nil error:&error],error.localizedDescription);
    Check([SHDWStateArchive verifyRoots:restored info:info progress:nil error:&error],error.localizedDescription);
    for(NSString *name in suffixes)Check([Target([destination stringByAppendingPathComponent:name]) isEqual:[destination stringByAppendingString:suffixes[name]]],@"absolute link did not relocate verbatim");
    Check([Read([destination stringByAppendingPathComponent:@"dot"]) isEqual:@"documents"],@"dot link no longer resolves");
    Check([Read([destination stringByAppendingPathComponent:@"parent-alias"]) isEqual:@"alias-parent"],@"symlink parent was simplified lexically");
    Check([Read([destination stringByAppendingPathComponent:@"group-parent"]) isEqual:@"group-parent"],@"cross-container symlink parent did not relocate");
    Check([Read([destination stringByAppendingPathComponent:@"relative"]) isEqual:@"alias-parent"],@"relative link changed");
    Check([Read([destination stringByAppendingPathComponent:@"var-alias"]) isEqual:@"documents"],@"/var alias failed");
    Check([Target([destination stringByAppendingPathComponent:@"outside"]) isEqual:outsideTarget]&&[Target([destination stringByAppendingPathComponent:@"escape"]) isEqual:escaped]&&[Target([destination stringByAppendingPathComponent:@"outside-parent"]) isEqual:outsideParent],@"out-of-scope target was rewritten");
    Check([Target([destination stringByAppendingPathComponent:@"loop-dot"]) isEqual:[source stringByAppendingString:@"/loop-a/../Documents/value"]],@"unresolvable loop was rewritten");
    Check([Read(outsideTarget) isEqual:@"outside-data-not-archived"],@"outside file changed");
    Retarget([destination stringByAppendingPathComponent:@"dot"],[source stringByAppendingString:suffixes[@"dot"]]);error=nil;
    Check(![SHDWStateArchive verifyRoots:restored info:info progress:nil error:&error]&&[error.localizedDescription containsString:@"symbolic link target differs"],@"verification accepted stale link with otherwise identical metadata");
    puts("archive links: dot/dotdot, symlink-parent semantics, cross-container links, /var alias, dangling final target, escapes, cycles and stale-link rejection passed");
}return 0;}
'''


def main():
    prefix = Path(os.environ.get("ARCHIVE_PREFIX", "/opt/homebrew/opt/libarchive"))
    zstd = Path(os.environ.get("ZSTD_PREFIX", "/opt/homebrew/opt/zstd"))
    with tempfile.TemporaryDirectory(prefix="shadow-archive-links-") as directory:
        temp = Path(directory).resolve()
        source = temp / "main.m"
        source.write_text(HARNESS.replace("__ARCHIVE_HEADER__", str(ROOT / "src/AppState/Archive.h")))
        binary = temp / "check"
        command = ["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-g", "-O1", "-framework", "Foundation", "-I" + str(prefix / "include"), "-I" + str(ROOT / "src/AppState"), "-L" + str(prefix / "lib"), "-L" + str(zstd / "lib"), "-Wl,-rpath," + str(prefix / "lib"), "-Wl,-rpath," + str(zstd / "lib"), str(source), str(ROOT / "src/AppState/Archive.m"), "-larchive", "-lzstd", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-o", str(binary)]
        subprocess.run(command, check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run([str(binary), str(temp / "fixture")], env=environment, check=True)


if __name__ == "__main__":
    main()
