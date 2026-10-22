#import "UniversalHooks.h"
#import "../../policy/FingerprintPolicy.h"
#include <dlfcn.h>

extern NSString *shdw_fingerprint_bundle_identifier_for_caller(const void *caller);
static unsigned shdw_system_version_state;

static BOOL shdw_system_version_path(id location, const void *caller) {
    if(!shdw_fingerprint_bundle_identifier_for_caller(caller)) return NO;
    NSString *path;
    if([location isKindOfClass:NSURL.class]) {
        if(![location isFileURL]) return NO;
        path = [location path];
    } else if([location isKindOfClass:NSString.class]) {
        path = location;
    } else return NO;
    return [path.stringByStandardizingPath isEqualToString:@"/System/Library/CoreServices/SystemVersion.plist"];
}

static NSDictionary *shdw_system_version_dictionary(NSDictionary *native) {
    if(![native isKindOfClass:NSDictionary.class]) return native;
    NSMutableDictionary *result = [native mutableCopy];
    const char *version = SHDWFingerprintVersionValue("kern.osproductversion");
    const char *build = SHDWFingerprintVersionValue("kern.osversion");
    if(version) result[@"ProductVersion"] = @(version);
    if(build) result[@"ProductBuildVersion"] = @(build);
    if(result[@"ProductUserVisibleVersion"]) result[@"ProductUserVisibleVersion"] = result[@"ProductVersion"];
    return [native isKindOfClass:NSMutableDictionary.class] ? result : [result copy];
}

static NSData *shdw_system_version_data(NSData *native) {
    if(!native) return nil;
    NSPropertyListFormat format;
    id object = [NSPropertyListSerialization propertyListWithData:native options:NSPropertyListImmutable
        format:&format error:NULL];
    if(![object isKindOfClass:NSDictionary.class]) return native;
    NSData *result = [NSPropertyListSerialization dataWithPropertyList:shdw_system_version_dictionary(object)
        format:format options:0 error:NULL];
    if(!result) return native;
    return [native isKindOfClass:NSMutableData.class] ? [result mutableCopy] : result;
}

static NSString *shdw_system_version_string(NSString *native) {
    if(!native) return nil;
    NSData *data = [native dataUsingEncoding:NSUTF8StringEncoding];
    NSData *updated = shdw_system_version_data(data);
    if(updated == data) return native;
    NSString *result = [[NSString alloc] initWithData:updated encoding:NSUTF8StringEncoding];
    if(!result) return native;
    return [native isKindOfClass:NSMutableString.class] ? [result mutableCopy] : result;
}

static id (*shdw_system_version_native_class_0)(id, SEL, NSString *);
static id shdw_system_version_class_0(id self, SEL _cmd, NSString * location) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_0(self, _cmd, location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_0(self, _cmd, location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_dictionary(native); }
    return native;
}
static id (*shdw_system_version_native_class_1)(id, SEL, NSURL *);
static id shdw_system_version_class_1(id self, SEL _cmd, NSURL * location) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_1(self, _cmd, location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_1(self, _cmd, location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_dictionary(native); }
    return native;
}
static id (*shdw_system_version_native_class_2)(id, SEL, NSString *);
static id shdw_system_version_class_2(id self, SEL _cmd, NSString * location) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_2(self, _cmd, location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_2(self, _cmd, location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}
static id (*shdw_system_version_native_class_3)(id, SEL, NSString *, NSDataReadingOptions, NSError **);
static id shdw_system_version_class_3(id self, SEL _cmd, NSString * location, NSDataReadingOptions options, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_3(self, _cmd, location, options, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_3(self, _cmd, location, options, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}
static id (*shdw_system_version_native_class_4)(id, SEL, NSURL *);
static id shdw_system_version_class_4(id self, SEL _cmd, NSURL * location) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_4(self, _cmd, location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_4(self, _cmd, location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}
static id (*shdw_system_version_native_class_5)(id, SEL, NSURL *, NSDataReadingOptions, NSError **);
static id shdw_system_version_class_5(id self, SEL _cmd, NSURL * location, NSDataReadingOptions options, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_5(self, _cmd, location, options, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_5(self, _cmd, location, options, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}
static id (*shdw_system_version_native_class_6)(id, SEL, NSString *);
static id shdw_system_version_class_6(id self, SEL _cmd, NSString * location) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_system_version_path(location, caller)) return shdw_system_version_native_class_6(self, _cmd, location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_6(self, _cmd, location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
static id (*shdw_system_version_native_class_7)(id, SEL, NSURL *);
static id shdw_system_version_class_7(id self, SEL _cmd, NSURL * location) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_system_version_path(location, caller)) return shdw_system_version_native_class_7(self, _cmd, location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_7(self, _cmd, location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
static id (*shdw_system_version_native_class_8)(id, SEL, NSString *, NSStringEncoding, NSError **);
static id shdw_system_version_class_8(id self, SEL _cmd, NSString * location, NSStringEncoding encoding, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_8(self, _cmd, location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_8(self, _cmd, location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
static id (*shdw_system_version_native_class_9)(id, SEL, NSString *, NSStringEncoding *, NSError **);
static id shdw_system_version_class_9(id self, SEL _cmd, NSString * location, NSStringEncoding * encoding, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_9(self, _cmd, location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_9(self, _cmd, location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
static id (*shdw_system_version_native_class_10)(id, SEL, NSURL *, NSStringEncoding, NSError **);
static id shdw_system_version_class_10(id self, SEL _cmd, NSURL * location, NSStringEncoding encoding, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_10(self, _cmd, location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_10(self, _cmd, location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
static id (*shdw_system_version_native_class_11)(id, SEL, NSURL *, NSStringEncoding *, NSError **);
static id shdw_system_version_class_11(id self, SEL _cmd, NSURL * location, NSStringEncoding * encoding, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return shdw_system_version_native_class_11(self, _cmd, location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_11(self, _cmd, location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
static id (*shdw_system_version_native_class_12)(id, SEL, NSURL *, NSError **);
static id shdw_system_version_class_12(id self, SEL _cmd, NSURL * location, NSError ** error) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_system_version_path(location, caller)) return shdw_system_version_native_class_12(self, _cmd, location, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = shdw_system_version_native_class_12(self, _cmd, location, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_dictionary(native); }
    return native;
}
static void shdw_system_version_install_class_methods(SHDWHookSession *hooks) {
    if(class_getClassMethod(NSDictionary.class, sel_registerName("dictionaryWithContentsOfFile:"))) {
        [hooks hookMessageInClass:object_getClass(NSDictionary.class)
            withSelector:sel_registerName("dictionaryWithContentsOfFile:")
            withReplacement:(void *)&shdw_system_version_class_0 outOldPtr:(void **)&shdw_system_version_native_class_0];
    }
    if(class_getClassMethod(NSDictionary.class, sel_registerName("dictionaryWithContentsOfURL:"))) {
        [hooks hookMessageInClass:object_getClass(NSDictionary.class)
            withSelector:sel_registerName("dictionaryWithContentsOfURL:")
            withReplacement:(void *)&shdw_system_version_class_1 outOldPtr:(void **)&shdw_system_version_native_class_1];
    }
    if(class_getClassMethod(NSData.class, sel_registerName("dataWithContentsOfFile:"))) {
        [hooks hookMessageInClass:object_getClass(NSData.class)
            withSelector:sel_registerName("dataWithContentsOfFile:")
            withReplacement:(void *)&shdw_system_version_class_2 outOldPtr:(void **)&shdw_system_version_native_class_2];
    }
    if(class_getClassMethod(NSData.class, sel_registerName("dataWithContentsOfFile:options:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSData.class)
            withSelector:sel_registerName("dataWithContentsOfFile:options:error:")
            withReplacement:(void *)&shdw_system_version_class_3 outOldPtr:(void **)&shdw_system_version_native_class_3];
    }
    if(class_getClassMethod(NSData.class, sel_registerName("dataWithContentsOfURL:"))) {
        [hooks hookMessageInClass:object_getClass(NSData.class)
            withSelector:sel_registerName("dataWithContentsOfURL:")
            withReplacement:(void *)&shdw_system_version_class_4 outOldPtr:(void **)&shdw_system_version_native_class_4];
    }
    if(class_getClassMethod(NSData.class, sel_registerName("dataWithContentsOfURL:options:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSData.class)
            withSelector:sel_registerName("dataWithContentsOfURL:options:error:")
            withReplacement:(void *)&shdw_system_version_class_5 outOldPtr:(void **)&shdw_system_version_native_class_5];
    }
    if(class_getClassMethod(NSString.class, sel_registerName("stringWithContentsOfFile:"))) {
        [hooks hookMessageInClass:object_getClass(NSString.class)
            withSelector:sel_registerName("stringWithContentsOfFile:")
            withReplacement:(void *)&shdw_system_version_class_6 outOldPtr:(void **)&shdw_system_version_native_class_6];
    }
    if(class_getClassMethod(NSString.class, sel_registerName("stringWithContentsOfURL:"))) {
        [hooks hookMessageInClass:object_getClass(NSString.class)
            withSelector:sel_registerName("stringWithContentsOfURL:")
            withReplacement:(void *)&shdw_system_version_class_7 outOldPtr:(void **)&shdw_system_version_native_class_7];
    }
    if(class_getClassMethod(NSString.class, sel_registerName("stringWithContentsOfFile:encoding:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSString.class)
            withSelector:sel_registerName("stringWithContentsOfFile:encoding:error:")
            withReplacement:(void *)&shdw_system_version_class_8 outOldPtr:(void **)&shdw_system_version_native_class_8];
    }
    if(class_getClassMethod(NSString.class, sel_registerName("stringWithContentsOfFile:usedEncoding:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSString.class)
            withSelector:sel_registerName("stringWithContentsOfFile:usedEncoding:error:")
            withReplacement:(void *)&shdw_system_version_class_9 outOldPtr:(void **)&shdw_system_version_native_class_9];
    }
    if(class_getClassMethod(NSString.class, sel_registerName("stringWithContentsOfURL:encoding:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSString.class)
            withSelector:sel_registerName("stringWithContentsOfURL:encoding:error:")
            withReplacement:(void *)&shdw_system_version_class_10 outOldPtr:(void **)&shdw_system_version_native_class_10];
    }
    if(class_getClassMethod(NSString.class, sel_registerName("stringWithContentsOfURL:usedEncoding:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSString.class)
            withSelector:sel_registerName("stringWithContentsOfURL:usedEncoding:error:")
            withReplacement:(void *)&shdw_system_version_class_11 outOldPtr:(void **)&shdw_system_version_native_class_11];
    }
    if(class_getClassMethod(NSDictionary.class, sel_registerName("dictionaryWithContentsOfURL:error:"))) {
        [hooks hookMessageInClass:object_getClass(NSDictionary.class)
            withSelector:sel_registerName("dictionaryWithContentsOfURL:error:")
            withReplacement:(void *)&shdw_system_version_class_12 outOldPtr:(void **)&shdw_system_version_native_class_12];
    }
}

%group shadowhook_fingerprint_system_version
%hook NSDictionary

- (id)initWithContentsOfFile:(NSString *)location {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_dictionary(native); }
    return native;
}

- (id)initWithContentsOfURL:(NSURL *)location {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_dictionary(native); }
    return native;
}
%end
%hook NSData

- (id)initWithContentsOfFile:(NSString *)location {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}

- (id)initWithContentsOfFile:(NSString *)location options:(NSDataReadingOptions)options error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location, options, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, options, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}

- (id)initWithContentsOfURL:(NSURL *)location {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}

- (id)initWithContentsOfURL:(NSURL *)location options:(NSDataReadingOptions)options error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location, options, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, options, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_data(native); }
    return native;
}
%end
%hook NSString

- (id)initWithContentsOfFile:(NSString *)location {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_system_version_path(location, caller)) return %orig(location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}

- (id)initWithContentsOfURL:(NSURL *)location {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_system_version_path(location, caller)) return %orig(location);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}

- (id)initWithContentsOfFile:(NSString *)location encoding:(NSStringEncoding)encoding error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}

- (id)initWithContentsOfFile:(NSString *)location usedEncoding:(NSStringEncoding *)encoding error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}

- (id)initWithContentsOfURL:(NSURL *)location encoding:(NSStringEncoding)encoding error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}

- (id)initWithContentsOfURL:(NSURL *)location usedEncoding:(NSStringEncoding *)encoding error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_system_version_path(location, caller);
    if(!applies) return %orig(location, encoding, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, encoding, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_string(native); }
    return native;
}
%end
%end

%group shadowhook_fingerprint_system_version_dictionary_errors
%hook NSDictionary

- (id)initWithContentsOfURL:(NSURL *)location error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_system_version_path(location, caller)) return %orig(location, error);
    id native;
    SHADOW_INTERNAL_SCOPE {
        native = %orig(location, error);
    }
    if(!native) return native;
    SHADOW_INTERNAL_SCOPE { native = shdw_system_version_dictionary(native); }
    return native;
}
%end
%end

static CFDictionaryRef (*shdw_native_system_version_dictionary)(void);
static CFDictionaryRef shdw_copy_system_version_dictionary(void) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_fingerprint_bundle_identifier_for_caller(caller) != nil;
    if(!applies) return shdw_native_system_version_dictionary();
    CFDictionaryRef native;
    SHADOW_INTERNAL_SCOPE { native = shdw_native_system_version_dictionary(); }
    if(!native) return NULL;
    NSDictionary *object = CFBridgingRelease(native);
    NSDictionary *updated;
    SHADOW_INTERNAL_SCOPE { updated = shdw_system_version_dictionary(object); }
    return (CFDictionaryRef)CFBridgingRetain(updated);
}

void *shdw_sym_policy_lookup_system_version(const char *name) {
    if(name && !strcmp(name, "_CFCopySystemVersionDictionary") &&
       __atomic_load_n(&shdw_system_version_state, __ATOMIC_ACQUIRE) == 2 &&
       shdw_native_system_version_dictionary)
        return (void *)&shdw_copy_system_version_dictionary;
    return NULL;
}

void shdw_universal_fingerprint_system_version_prepare(SHDWHookSession *hooks) {
    if(!hooks) return;
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_system_version_state, &expected, 1, NO,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    SHDWHookSession *previous = SHDWHookSessionSetCurrent(hooks);
    @try {
        shdw_system_version_install_class_methods(hooks);
        %init(shadowhook_fingerprint_system_version);
        shdw_native_system_version_dictionary = (CFDictionaryRef (*)(void))
            dlsym(RTLD_DEFAULT, "_CFCopySystemVersionDictionary");
        if(shdw_native_system_version_dictionary) {
            [hooks hookRebindSymbol:@"_CFCopySystemVersionDictionary"
                withReplacement:shdw_copy_system_version_dictionary
                outOldPtr:NULL];
        }
        if(class_getInstanceMethod(NSDictionary.class, @selector(initWithContentsOfURL:error:))) {
            %init(shadowhook_fingerprint_system_version_dictionary_errors);
        }
        __atomic_store_n(&shdw_system_version_state, 2, __ATOMIC_RELEASE);
    } @finally { SHDWHookSessionSetCurrent(previous); }
}
