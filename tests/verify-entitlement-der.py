#!/usr/bin/env python3
"""Run the production DER entitlement reader under address/undefined sanitizers."""
from pathlib import Path
import subprocess
import tempfile
import os
ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''#import <Foundation/Foundation.h>
#include <stdint.h>
static void Require(BOOL condition, NSString *reason) { if (!condition) @throw [NSException exceptionWithName:@"Fixture" reason:reason userInfo:nil]; }
#include "__SOURCE__"
int main(void) { @autoreleasepool {
    uint8_t empty[] = {0x31,0};
    Require(DEREntitlements(empty, sizeof(empty)).count == 0, @"empty dictionary");
    uint8_t duplicate[] = {0x31,0x10,0x30,0x06,0x0c,0x01,0x61,0x01,0x01,0x01,0x30,0x06,0x0c,0x01,0x61,0x01,0x01,0x00};
    BOOL rejected = NO; @try { DEREntitlements(duplicate,sizeof(duplicate)); } @catch (NSException *e) { (void)e;rejected=YES; }
    Require(rejected,@"duplicate dictionary key");
    // Every truncated prefix of a valid nested value must fail closed.
    uint8_t valid[] = {0x31,0x0a,0x30,0x08,0x0c,0x01,0x61,0x30,0x03,0x0c,0x01,0x62};
    Require([DEREntitlements(valid,sizeof(valid))[@"a"] isEqual:@[@"b"]],@"nested array");
    for (NSUInteger n=0;n<sizeof(valid);n++) { rejected=NO;@try { DEREntitlements(valid,n); } @catch (NSException *e) { (void)e;rejected=YES; } Require(rejected,@"truncated prefix"); }
    uint32_t state=7;
    for (NSUInteger i=0;i<5000;i++) { @autoreleasepool {
        uint8_t bytes[128];for (NSUInteger j=0;j<sizeof(bytes);j++) { state=state*1664525u+1013904223u;bytes[j]=(uint8_t)(state>>24); }
        @try { DEREntitlements(bytes,i%sizeof(bytes)); } @catch (NSException *e) { (void)e; }
    } }
    puts("DER entitlements: bounds, duplicate keys, truncated containers and 5000 malformed inputs passed under sanitizers");
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-der-test-") as directory:
    root=Path(directory); source=root/'main.m';binary=root/'check'
    source.write_text(HARNESS.replace('__SOURCE__',str(ROOT/'src/ShadowCleaner/EntitlementDER.inc')))
    subprocess.run(['xcrun','clang','-fobjc-arc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-framework','Foundation',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
