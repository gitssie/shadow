"""Compile production IDFV hooks against native Objective-C runtime fixtures."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]


def body(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


identity = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintIdentity.x").read_text()
integration = (root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text()
init = body(integration, "void shdw_universal_fingerprint(SHDWHookSession *hooks)")
assert init.index("shdw_universal_fingerprint_identity(hooks,") < init.index("SHDWFingerprintData(")
prepare_integration = body(integration, "void shdw_universal_fingerprint_prepare(")
assert prepare_integration.index("shdw_universal_fingerprint_identity_prepare(hooks)") < prepare_integration.index("if(!shdw_fingerprint_enabled)")
assert "- (NSUUID *)identifierForVendor" not in integration
dyld = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
for signature in ["void shdw_universal_dyld_updatelibs(", "static void shdw_bulk_load_handler("]:
    callback = body(dyld, signature)
    assert callback.index("shdw_universal_fingerprint_identity_prepare(") < callback.index("shdw_detector_present")
completion = body(dyld, "static void* shdw_dlopen_completed(")
assert "shdw_universal_fingerprint_identity_prepare(" in completion
assert "shdw_detector_present" not in completion

helpers = identity[identity.index("static BOOL shdw_identity_requested;"):identity.index("%group")]
hooks = []
for group, selector in [("device", "identifierForVendor"),
                        ("workspace", "deviceIdentifierForVendor"),
                        ("proxy", "deviceIdentifierForVendor")]:
    section = identity[identity.index("%group shadowhook_fingerprint_identity_" + group):]
    method = body(section, "- (NSUUID *)" + selector)
    method = method.replace("- (NSUUID *)" + selector, f"static NSUUID *hook_{group}(id self, SEL _cmd)")
    hooks.append(method.replace("%orig", f"native_{group}(self, _cmd)"))

prepare = body(identity, "void shdw_universal_fingerprint_identity_prepare(")
for group, cls, selector, logos_cls in [
    ("device", "deviceClass", "identifierForVendor", "UIDevice"),
    ("workspace", "workspaceClass", "deviceIdentifierForVendor", "LSApplicationWorkspace"),
    ("proxy", "proxyClass", "deviceIdentifierForVendor", "LSApplicationProxy"),
]:
    prepare = prepare.replace(
        f"%init(shadowhook_fingerprint_identity_{group}, {logos_cls} = {cls});",
        f"install_hook({cls}, @selector({selector}), (IMP)hook_{group}, &native_{group});")
initializer = body(identity, "void shdw_universal_fingerprint_identity(SHDWHookSession *hooks,")

source = r"""
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <assert.h>
#define SHADOW_INTERNAL_SCOPE for(BOOL active=YES;active;active=NO)
typedef NSObject SHDWHookSession;
static SHDWHookSession *currentSession;
static SHDWHookSession *SHDWHookSessionSetCurrent(SHDWHookSession *session) {
    SHDWHookSession *previous=currentSession; currentSession=session; return previous;
}
static NSUUID *stored;
static unsigned nativeCalls, installations;
static NSString *SHDWFingerprintOwnerIdentifier(NSString *bundle) {
    return [bundle isEqualToString:@"idfv.test.extension"] ? @"idfv.test" : bundle;
}
static NSUUID *SHDWFingerprintVendorIdentifier(NSString *owner) {
    assert([owner isEqualToString:@"idfv.test"]); return stored;
}
static NSUUID *(*native_device)(id, SEL);
static NSUUID *(*native_workspace)(id, SEL);
static NSUUID *(*native_proxy)(id, SEL);
static NSUUID *native_value(id object, SEL selector) {
    (void)object; (void)selector; nativeCalls++;
    return [[NSUUID alloc] initWithUUIDString:@"00000000-0000-4000-8000-000000000001"];
}
static id proxy_bundle(id object, SEL selector) { (void)selector; return objc_getAssociatedObject(object, @selector(bundleIdentifier)); }
static void install_hook(Class cls, SEL selector, IMP replacement, NSUUID *(**original)(id, SEL)) {
    Method method=class_getInstanceMethod(cls,selector);
    *original=(NSUUID *(*)(id,SEL))method_getImplementation(method);
    class_replaceMethod(cls,selector,replacement,method_getTypeEncoding(method)); installations++;
}
static Class register_class(const char *name, BOOL getter, SEL selector) {
    Class cls=objc_allocateClassPair(NSObject.class,name,0); assert(cls);
    if(getter) assert(class_addMethod(cls,selector,(IMP)native_value,"@@:"));
    objc_registerClassPair(cls); return cls;
}
static NSUUID *read_id(id object, SEL selector) { return ((id (*)(id,SEL))objc_msgSend)(object,selector); }
@protocol DeviceIdentity
@property (readonly) NSUUID *identifierForVendor;
@end
""" + helpers + "\n" + "\n".join(hooks) + "\n" + prepare + "\n" + initializer + r"""
int main(void) { @autoreleasepool {
    SHDWHookSession *session=[NSObject new], *previous=[NSObject new]; currentSession=previous;
    Class device=register_class("UIDevice",YES,@selector(identifierForVendor));
    id instance=[device new];
    shdw_universal_fingerprint_identity_prepare(session);
    assert(currentSession==previous && installations==0);
    assert(read_id(instance,@selector(identifierForVendor)) && nativeCalls==1);
    stored=[[NSUUID alloc] initWithUUIDString:@"A17E1807-1001-4000-8000-000000000001"];
    shdw_universal_fingerprint_identity(session,@"idfv.test.extension");
    assert(currentSession==previous && installations==1);
    for(unsigned i=0;i<100;i++) {
        NSUUID *value=read_id(instance,@selector(identifierForVendor));
        assert([((id<DeviceIdentity>)instance).identifierForVendor isEqual:value]);
        uuid_t actual, expected; [value getUUIDBytes:actual]; [stored getUUIDBytes:expected];
        assert([value isKindOfClass:NSUUID.class] && !memcmp(actual,expected,sizeof(uuid_t)));
        IMP imp=class_getMethodImplementation(device,@selector(identifierForVendor));
        assert([((id (*)(id,SEL))imp)(instance,@selector(identifierForVendor)) isEqual:stored]);
    }
    assert(nativeCalls==1);
    // A missing optional class/selector remains eligible for a later image.
    Class workspace=register_class("LSApplicationWorkspace",YES,@selector(deviceIdentifierForVendor));
    Class proxy=register_class("LSApplicationProxy",NO,@selector(deviceIdentifierForVendor));
    shdw_universal_fingerprint_identity_prepare(session); assert(installations==2);
    assert(class_addMethod(proxy,@selector(deviceIdentifierForVendor),(IMP)native_value,"@@:"));
    shdw_universal_fingerprint_identity_prepare(session); assert(installations==2);
    assert(class_addMethod(proxy,@selector(bundleIdentifier),(IMP)proxy_bundle,"@@:"));
    shdw_universal_fingerprint_identity_prepare(session); assert(installations==3);
    shdw_universal_fingerprint_identity_prepare(session); assert(installations==3);
    assert(currentSession==previous);
    id workspaceObject=[workspace new], own=[proxy new], extension=[proxy new], unrelated=[proxy new];
    objc_setAssociatedObject(own,@selector(bundleIdentifier),@"idfv.test",OBJC_ASSOCIATION_COPY_NONATOMIC);
    objc_setAssociatedObject(extension,@selector(bundleIdentifier),@"idfv.test.extension",OBJC_ASSOCIATION_COPY_NONATOMIC);
    objc_setAssociatedObject(unrelated,@selector(bundleIdentifier),@"unrelated.test",OBJC_ASSOCIATION_COPY_NONATOMIC);
    assert([read_id(workspaceObject,@selector(deviceIdentifierForVendor)) isEqual:stored]);
    assert([read_id(own,@selector(deviceIdentifierForVendor)) isEqual:stored]);
    assert([read_id(extension,@selector(deviceIdentifierForVendor)) isEqual:stored]);
    assert(![read_id(unrelated,@selector(deviceIdentifierForVendor)) isEqual:stored] && nativeCalls==2);
    // Scoped failure must not expose the native identity.
    stored=nil;
    assert(!read_id(instance,@selector(identifierForVendor)));
    assert(!read_id(workspaceObject,@selector(deviceIdentifierForVendor)));
    assert(!read_id(own,@selector(deviceIdentifierForVendor)));
    assert(!read_id(extension,@selector(deviceIdentifierForVendor)));
    assert(nativeCalls==2);
    assert(read_id(unrelated,@selector(deviceIdentifierForVendor)) && nativeCalls==3);
    __atomic_store_n(&shdw_identity_requested,NO,__ATOMIC_RELEASE);
    assert(read_id(instance,@selector(identifierForVendor)));
    assert(read_id(workspaceObject,@selector(deviceIdentifierForVendor)));
    assert(read_id(own,@selector(deviceIdentifierForVendor)) && nativeCalls==6);
    puts("fingerprint IDFV: stable UUID, selector dispatch, owner scope, nil failure and late classes passed");
} }
"""
for system, fixture in [("UIDevice", "FixtureDevice"), ("LSApplicationWorkspace", "FixtureWorkspace"),
                        ("LSApplicationProxy", "FixtureProxy")]:
    source = source.replace(system, fixture)
with tempfile.TemporaryDirectory(prefix="shadow-idfv-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
