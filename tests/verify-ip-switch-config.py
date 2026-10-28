#!/usr/bin/env python3
"""Check saved switch labels/URLs without accessing the user's preferences."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#import <Foundation/Foundation.h>
static NSMutableDictionary *values;
@interface FixtureDefaults : NSObject
+ (instancetype)standardUserDefaults;
- (id)objectForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
@end
@implementation FixtureDefaults
+ (instancetype)standardUserDefaults { static id instance; if(!instance)instance=[self new];return instance; }
- (id)objectForKey:(NSString *)key { return values[key]; }
- (void)setObject:(id)value forKey:(NSString *)key { values[key]=value; }
@end
NSString *SHDWLocalizedText(NSString *key) { return key; }
#define NSUserDefaults FixtureDefaults
#import "__SOURCE__"
#undef NSUserDefaults
static void Check(BOOL ok) { if(!ok)abort(); }
int main(void) { @autoreleasepool {
    values=[NSMutableDictionary new]; NSError *error=nil;
    Check(!SHDWIPSwitchConfiguration.configurations.count);
    NSArray *entries=@[@{@"name":@" Line one ",@"url":@" https://one.example/switch?token=fixture "},@{@"name":@"线路二",@"url":@"http://two.example/action"}];
    Check([SHDWIPSwitchConfiguration saveConfigurations:entries error:&error]);
    NSArray *saved=SHDWIPSwitchConfiguration.configurations;
    Check(saved.count==2&&[saved[0][@"name"]isEqual:@"Line one"]&&[saved[0][@"url"]isEqual:@"https://one.example/switch?token=fixture"]&&[saved[1][@"name"]isEqual:@"线路二"]);
    for(NSArray *bad in @[@[@{@"name":@"",@"url":@"https://one.example"}],@[@{@"name":@"line ONE",@"url":@"https://one.example"},saved[0]],@[@{@"name":@"Bad",@"url":@"file:///tmp/action"}],@[@{@"name":@"Bad",@"url":@"https://user:password@one.example"}],@[@{@"name":@"Bad",@"url":@"https://one.example/has space"}],@[@{@"name":@"Bad",@"url":@"https://one.example/#fragment"}],@[@42],@[@{@"name":@[],@"url":@[]}]] ) {
        error=nil; Check(![SHDWIPSwitchConfiguration saveConfigurations:bad error:&error]&&error&&[SHDWIPSwitchConfiguration.configurations isEqual:saved]);
    }
    values[@"IPSwitchConfigurations"]=@[@42,@{},saved[1],@{@"name":@"Bad",@"url":@"javascript:alert(1)"}];
    Check([SHDWIPSwitchConfiguration.configurations isEqual:@[saved[1]]]);
    Check([SHDWIPSwitchConfiguration saveConfigurations:@[] error:&error]&&!SHDWIPSwitchConfiguration.configurations.count);
    puts("IP switch configuration: multiple labels/URLs, normalization, invalid-save preservation, malformed storage and clearing passed");
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-ip-config-test-") as directory:
    temp = Path(directory).resolve()
    source = temp / "main.m"
    source.write_text(HARNESS.replace("__SOURCE__", str(ROOT / "src/Shadow.app/Services/IPSwitchConfiguration.m")))
    binary = temp / "test"
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
