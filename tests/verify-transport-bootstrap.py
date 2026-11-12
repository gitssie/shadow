"""Exercise the production transport bootstrap codec using Foundation and XPC."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation and XPC")
root = Path(__file__).resolve().parents[1]
source = r'''
#import "Bootstrap.h"
#include <assert.h>
#include <string.h>
static const char *key = "me.jjolano.shadow.transport.v1";
static xpc_object_t event(void) {
    xpc_object_t value = xpc_dictionary_create(NULL, NULL, 0);
    xpc_dictionary_set_string(value,"message-name","bootstrap");
    xpc_dictionary_set_string(value,"service-name","com.apple.WebKit.Networking");
    xpc_dictionary_set_string(value,"client-bundle-identifier","test.Owner");
    return value;
}
static xpc_object_t bootstrap(void) {
    return SHDWTransportBootstrapMessage(xpc_dictionary_create(NULL,NULL,0),@"safari184_ios",@"test.Owner");
}
int main(void) { @autoreleasepool {
    assert(SHDWTransportIsNetworkingService("com.apple.WebKit.Networking"));
    assert(!SHDWTransportIsNetworkingService(NULL));
    for (NSString *service in @[@"",@"com.apple.WebKit.WebContent",@"com.apple.WebKit.Networking.Development",@"com.apple.WebKit.NetworkingX"])
        assert(!SHDWTransportIsNetworkingService(service.UTF8String));
    xpc_object_t original=xpc_dictionary_create(NULL,NULL,0);
    xpc_dictionary_set_string(original,"unrelated","preserved");
    xpc_dictionary_set_string(original,key,"prior");
    xpc_object_t wrong=xpc_string_create("wrong");
    assert(!SHDWTransportBootstrapMessage(NULL,@"safari184_ios",@"test.Owner"));
    assert(SHDWTransportBootstrapMessage(wrong,@"safari184_ios",@"test.Owner")==wrong);
    assert(SHDWTransportBootstrapMessage(original,nil,@"test.Owner")==original);
    assert(SHDWTransportBootstrapMessage(original,@"safari184_ios",nil)==original);
    for(id profile in @[@"native",@"auto",@"unknown",@"",@"safari184_ios\n",@1,NSNull.null])
        assert(SHDWTransportBootstrapMessage(original,profile,@"test.Owner")==original);
    NSString *longString=[@"a" stringByPaddingToLength:256 withString:@"a" startingAtIndex:0];
    NSString *nul=[[NSString alloc] initWithBytes:"test\0Owner" length:10 encoding:NSUTF8StringEncoding];
    NSString *multiByte=[@"é" stringByPaddingToLength:128 withString:@"é" startingAtIndex:0];
    for(id owner in @[@"",@1,NSNull.null,@"test\nOwner",@"test\tOwner",longString,nul,multiByte])
        assert(SHDWTransportBootstrapMessage(original,@"safari184_ios",owner)==original);
    for (NSString *profile in @[@"safari172_ios", @"safari180_ios", @"safari184_ios"]) {
        NSMutableString *mutableProfile=[profile mutableCopy];
        xpc_object_t launchMessage=SHDWTransportBootstrapMessage(original,mutableProfile,@"test.Owner");
        [mutableProfile setString:@"changed"];
        NSDictionary *selected=SHDWTransportSnapshot(launchMessage,event());
        assert([selected[@"Profile"] isEqual:profile]);
        assert(!strcmp(xpc_dictionary_get_string(original,key),"prior"));
    }
    NSMutableString *owner=[@"test.Owner" mutableCopy];
    xpc_object_t message=SHDWTransportBootstrapMessage(original,@"safari184_ios",owner);
    [owner setString:@"changed.Owner"];
    assert(message!=original && !strcmp(xpc_dictionary_get_string(original,key),"prior"));
    assert(!strcmp(xpc_dictionary_get_string(message,"unrelated"),"preserved"));
    xpc_object_t payload=xpc_dictionary_get_value(message,key);
    assert(xpc_get_type(xpc_dictionary_get_value(payload,"version"))==XPC_TYPE_UINT64);
    assert(xpc_uint64_get_value(xpc_dictionary_get_value(payload,"version"))==1);
    assert(xpc_dictionary_get_count(payload)==3);
    NSDictionary *snapshot=SHDWTransportSnapshot(message,event());
    assert([snapshot isEqual:(@{@"Profile":@"safari184_ios",@"Owner":@"test.Owner"})]);
    assert(![snapshot isKindOfClass:NSMutableDictionary.class]);
    assert([snapshot[@"Owner"] isKindOfClass:NSString.class]);
    assert([snapshot[@"Profile"] isKindOfClass:NSString.class]);
    xpc_dictionary_set_string(payload,"owner-bundle-identifier","changed.Owner");
    assert([snapshot[@"Owner"] isEqual:@"test.Owner"] && !SHDWTransportSnapshot(message,event()));
    assert(!SHDWTransportSnapshot(NULL,event()) && !SHDWTransportSnapshot(bootstrap(),NULL));
    assert(!SHDWTransportSnapshot(wrong,event()) && !SHDWTransportSnapshot(bootstrap(),wrong));
    assert(!SHDWTransportSnapshot(xpc_dictionary_create(NULL,NULL,0),event()));
    for(NSString *field in @[@"message-name",@"service-name",@"client-bundle-identifier"]) {
        for(id invalid in @[NSNull.null,@1,@"mismatch",@"",@"test\nOwner",longString]) {
            xpc_object_t launch=event();
            if(invalid==NSNull.null) xpc_dictionary_set_value(launch,field.UTF8String,NULL);
            else if([invalid isKindOfClass:NSNumber.class]) xpc_dictionary_set_uint64(launch,field.UTF8String,1);
            else xpc_dictionary_set_string(launch,field.UTF8String,[invalid UTF8String]);
            assert(!SHDWTransportSnapshot(bootstrap(),launch));
        }
    }
    for(NSString *field in @[@"version",@"profile",@"owner-bundle-identifier"]) {
        xpc_object_t bad=bootstrap();payload=xpc_dictionary_get_value(bad,key);
        xpc_dictionary_set_value(payload,field.UTF8String,NULL);assert(!SHDWTransportSnapshot(bad,event()));
        xpc_dictionary_set_bool(payload,field.UTF8String,true);assert(!SHDWTransportSnapshot(bad,event()));
    }
    uint64_t versions[]={0,2,UINT64_MAX};
    for(unsigned i=0;i<sizeof(versions)/sizeof(*versions);i++) {
        xpc_object_t bad=bootstrap();payload=xpc_dictionary_get_value(bad,key);
        xpc_dictionary_set_uint64(payload,"version",versions[i]);assert(!SHDWTransportSnapshot(bad,event()));
    }
    xpc_object_t bad=bootstrap();payload=xpc_dictionary_get_value(bad,key);
    xpc_dictionary_set_int64(payload,"version",1);assert(!SHDWTransportSnapshot(bad,event()));
    bad=bootstrap();xpc_dictionary_set_string(bad,key,"wrong");assert(!SHDWTransportSnapshot(bad,event()));
    for(NSString *profile in @[@"native",@"auto",@"unknown",@"",@"safari184_ios\n"]){
        bad=bootstrap();payload=xpc_dictionary_get_value(bad,key);
        xpc_dictionary_set_string(payload,"profile",profile.UTF8String);assert(!SHDWTransportSnapshot(bad,event()));
    }
    for(NSString *identity in @[@"",@"test\nOwner",longString,multiByte]) {
        bad=bootstrap();payload=xpc_dictionary_get_value(bad,key);xpc_object_t launch=event();
        xpc_dictionary_set_string(payload,"owner-bundle-identifier",identity.UTF8String);
        xpc_dictionary_set_string(launch,"client-bundle-identifier",identity.UTF8String);
        assert(!SHDWTransportSnapshot(bad,launch));
    }
    bad=bootstrap();payload=xpc_dictionary_get_value(bad,key);
    xpc_dictionary_set_string(payload,"owner-bundle-identifier","\xff");assert(!SHDWTransportSnapshot(bad,event()));
    NSString *limit=[@"a" stringByPaddingToLength:255 withString:@"a" startingAtIndex:0];
    xpc_object_t launch=event();xpc_dictionary_set_string(launch,"client-bundle-identifier",limit.UTF8String);
    assert(SHDWTransportSnapshot(SHDWTransportBootstrapMessage(original,@"safari184_ios",limit),launch));
    puts("transport bootstrap: typed version/profile, exact service and launch identity, immutable copies, malformed inputs and opt-in no-ops passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-transport-bootstrap-") as temporary:
    test, binary = Path(temporary) / "test.m", Path(temporary) / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(root / "src/Transport"),
                    str(test), str(root / "src/Transport/Bootstrap.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
