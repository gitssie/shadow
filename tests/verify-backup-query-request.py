#!/usr/bin/env python3
"""Exercise the shared Manager/SDK query factory and helper validator across plist IPC."""
from pathlib import Path
import subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'src/AppState/StateIndex.inc').read_text()
start=source.index('+ (BOOL)validateCatalogQuery:');end=source.index('- (SHDWAppStateIndex *)openIndex',start)
validator=source[start:end]
code=r'''#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import "SHDWAppStateCatalogQuery.h"
#include <math.h>
#include <assert.h>
static BOOL FailCode(NSError **error, NSString *code, NSString *message) {
 if(error)*error=[NSError errorWithDomain:@"fixture" code:1 userInfo:@{NSLocalizedDescriptionKey:message,@"errorCode":code}];return NO;
}
@interface SHDWAppStateStore:NSObject
+ (BOOL)validateCatalogQuery:(NSDictionary *)query error:(NSError **)error;
@end
@implementation SHDWAppStateStore
'''+validator+r'''
@end
int main(void){@autoreleasepool{
 NSString *search=@"été";NSUInteger nextOffset=100;
 for(int appendValue=0;appendValue<2;appendValue++)for(int refreshValue=0;refreshValue<2;refreshValue++){
 BOOL append=(BOOL)appendValue,refreshCatalog=(BOOL)refreshValue;
 NSDictionary *request=SHDWAppStateCatalogQuery(search,@"FR",append?nextOffset:0,SHDWAppStateCatalogPageSize,!append && refreshCatalog);

 NSData *data=[NSPropertyListSerialization dataWithPropertyList:request format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
 NSDictionary *decoded=[NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:NULL];
 NSError *error=nil;
 if(![SHDWAppStateStore validateCatalogQuery:decoded error:&error]){fprintf(stderr,"FAIL: Manager query append=%d refresh=%d: %s\n",append,refreshCatalog,error.localizedDescription.UTF8String);return 1;}
 assert(CFGetTypeID((__bridge CFTypeRef)decoded[@"refresh"])==CFBooleanGetTypeID());
 }
 NSDictionary *invalid=@{@"refresh":@1};
 assert(![SHDWAppStateStore validateCatalogQuery:invalid error:NULL]);
 puts("shared catalog query: initial/search/refresh/paging factory survives plist IPC and helper validation; integer boolean rejected");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix='shadow-manager-query-') as d:
 p=Path(d);(p/'test.m').write_text(code)
 subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-framework','Foundation','-I'+str(ROOT/'sdk/AppState'),str(p/'test.m'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
