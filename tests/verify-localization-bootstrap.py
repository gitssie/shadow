"""Exercise the production bootstrap codec using macOS XPC and Foundation."""
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
static const char *key = "me.jjolano.shadow.localization.v1";
static NSDictionary *resolved(void) {
    return @{@"LocaleIdentifier":@"en_US", @"Languages":@[@"en-US", @"fr-FR"],
             @"TimeZone":@"America/New_York", @"OverridesSystem":@YES, @"CountryCode":@"US"};
}
static xpc_object_t event(void) {
    xpc_object_t object = xpc_dictionary_create(NULL, NULL, 0);
    xpc_dictionary_set_string(object, "message-name", "bootstrap");
    xpc_dictionary_set_string(object, "service-name", "com.apple.WebKit.WebContent");
    xpc_dictionary_set_string(object, "client-bundle-identifier", "test.SDKProbe");
    return object;
}
static xpc_object_t bootstrap(void) {
    return SHDWLocalizationBootstrapMessage(xpc_dictionary_create(NULL, NULL, 0), resolved(), @"test.SDKProbe");
}
int main(void) { @autoreleasepool {
    NSDictionary *persistentBefore = [NSUserDefaults.standardUserDefaults persistentDomainForName:@"test.SDKProbe"];
    NSDictionary *volatileBefore = [NSUserDefaults.standardUserDefaults volatileDomainForName:NSArgumentDomain];
    NSDictionary *globalBefore = [NSUserDefaults.standardUserDefaults persistentDomainForName:NSGlobalDomain];
    assert(SHDWLocalizationIsWebContentService("com.apple.WebKit.WebContent"));
    assert(!SHDWLocalizationIsWebContentService(NULL));
    for (const char *name : (const char *[]){"com.apple.WebKit.WebContent.Development", "com.apple.WebKit.Networking", "com.apple.WebKit.WebContentX", ""}) {
        assert(!SHDWLocalizationIsWebContentService(name));
    }
    assert(!SHDWLocalizationBootstrapHasPayload(NULL));
    assert(!SHDWLocalizationBootstrapHasPayload(xpc_string_create("wrong")));
    assert(!SHDWLocalizationBootstrapHasPayload(xpc_dictionary_create(NULL, NULL, 0)));
    xpc_object_t gate = bootstrap(); assert(SHDWLocalizationBootstrapHasPayload(gate));
    xpc_dictionary_set_string(gate, key, "wrong"); assert(!SHDWLocalizationBootstrapHasPayload(gate));
    gate = bootstrap(); xpc_dictionary_set_value(xpc_dictionary_get_value(gate, key), "version", NULL);
    assert(!SHDWLocalizationBootstrapHasPayload(gate));
    for (uint64_t version : (uint64_t []){0, 2, UINT64_MAX}) {
        gate = bootstrap(); xpc_dictionary_set_uint64(xpc_dictionary_get_value(gate, key), "version", version);
        assert(!SHDWLocalizationBootstrapHasPayload(gate));
    }
    gate = bootstrap(); xpc_dictionary_set_int64(xpc_dictionary_get_value(gate, key), "version", 1);
    assert(!SHDWLocalizationBootstrapHasPayload(gate));
    gate = bootstrap(); xpc_dictionary_set_string(xpc_dictionary_get_value(gate, key), "owner-bundle-identifier", "another.app");
    assert(SHDWLocalizationBootstrapHasPayload(gate) && !SHDWLocalizationSnapshot(gate, event()));
    xpc_object_t original = xpc_dictionary_create(NULL, NULL, 0);
    xpc_dictionary_set_string(original, "unrelated", "preserved");
    xpc_object_t oldLanguages = xpc_array_create(NULL, 0);
    xpc_array_set_string(oldLanguages, XPC_ARRAY_APPEND, "de-DE");
    xpc_dictionary_set_value(original, "OverrideLanguages", oldLanguages);
    assert(SHDWLocalizationBootstrapMessage(original, nil, @"test.SDKProbe") == original);
    assert(SHDWLocalizationBootstrapMessage(NULL, resolved(), @"test.SDKProbe") == NULL);
    xpc_object_t nonDictionary = xpc_string_create("wrong");
    assert(SHDWLocalizationBootstrapMessage(nonDictionary, resolved(), @"test.SDKProbe") == nonDictionary);
    for (id flag in @[@NO, @1, @"true", NSNull.null]) {
        NSMutableDictionary *config = [resolved() mutableCopy]; config[@"OverridesSystem"] = flag;
        assert(SHDWLocalizationBootstrapMessage(original, config, @"test.SDKProbe") == original);
    }
    for (NSString *field in @[@"LocaleIdentifier", @"Languages", @"TimeZone", @"OverridesSystem"]) {
        NSMutableDictionary *config = [resolved() mutableCopy]; [config removeObjectForKey:field];
        assert(SHDWLocalizationBootstrapMessage(original, config, @"test.SDKProbe") == original);
    }
    NSString *longString = [@"a" stringByPaddingToLength:256 withString:@"a" startingAtIndex:0];
    NSString *nul = [[NSString alloc] initWithBytes:"en\0US" length:5 encoding:NSUTF8StringEncoding];
    for (id invalid in @[@1, @"", @"bogus", @"en\n", longString, nul]) {
        NSMutableDictionary *config = [resolved() mutableCopy]; config[@"LocaleIdentifier"] = invalid;
        assert(SHDWLocalizationBootstrapMessage(original, config, @"test.SDKProbe") == original);
    }
    for (id invalid in @[@1, @"", @"Moon/Test", longString]) {
        NSMutableDictionary *config = [resolved() mutableCopy]; config[@"TimeZone"] = invalid;
        assert(SHDWLocalizationBootstrapMessage(original, config, @"test.SDKProbe") == original);
    }
    NSMutableArray *tooMany = [NSMutableArray array]; for (int i = 0; i < 33; i++) [tooMany addObject:@"en-US"];
    for (id invalid in @[@1, @[], @[@1], @[@""], @[@"bogus"], @[longString], tooMany]) {
        NSMutableDictionary *config = [resolved() mutableCopy]; config[@"Languages"] = invalid;
        assert(SHDWLocalizationBootstrapMessage(original, config, @"test.SDKProbe") == original);
    }
    for (id owner in @[@1, @"", longString, nul]) assert(SHDWLocalizationBootstrapMessage(original, resolved(), owner) == original);
    xpc_object_t message = SHDWLocalizationBootstrapMessage(original, resolved(), @"test.SDKProbe");
    assert(message != original && !xpc_dictionary_get_value(original, key));
    assert(!strcmp(xpc_dictionary_get_string(message, "unrelated"), "preserved"));
    assert(!strcmp(xpc_array_get_string(xpc_dictionary_get_value(original, "OverrideLanguages"), 0), "de-DE"));
    xpc_object_t override = xpc_dictionary_get_value(message, "OverrideLanguages");
    assert(xpc_array_get_count(override) == 2 && !strcmp(xpc_array_get_string(override, 0), "en-US"));
    NSDictionary *snapshot = SHDWLocalizationSnapshot(message, event());
    assert(snapshot.count == 3 && [snapshot[@"LocaleIdentifier"] isEqual:@"en_US"]);
    assert([snapshot[@"Languages"] isEqual:(@[@"en-US", @"fr-FR"])]);
    assert([snapshot[@"TimeZone"] isEqual:@"America/New_York"]);
    assert(![snapshot isKindOfClass:NSMutableDictionary.class]);
    assert(![snapshot[@"Languages"] isKindOfClass:NSMutableArray.class]);
    for (NSString *language in snapshot[@"Languages"]) assert(![language isKindOfClass:NSMutableString.class]);
    assert(![snapshot[@"LocaleIdentifier"] isKindOfClass:NSMutableString.class]);
    xpc_dictionary_set_string(xpc_dictionary_get_value(message, key), "locale-identifier", "fr_FR");
    xpc_array_set_string(xpc_dictionary_get_value(xpc_dictionary_get_value(message, key), "languages"), 0, "de-DE");
    assert([snapshot[@"LocaleIdentifier"] isEqual:@"en_US"]);
    assert([snapshot[@"Languages"][0] isEqual:@"en-US"]);
    NSMutableString *mutableLanguage = [@"en-US" mutableCopy];
    NSMutableArray *mutableLanguages = [@[mutableLanguage] mutableCopy];
    NSMutableDictionary *mutableResolved = [resolved() mutableCopy]; mutableResolved[@"Languages"] = mutableLanguages;
    xpc_object_t fromMutable = SHDWLocalizationBootstrapMessage(original, mutableResolved, @"test.SDKProbe");
    [mutableLanguage setString:@"fr-FR"]; [mutableLanguages addObject:@"de-DE"];
    assert([SHDWLocalizationSnapshot(fromMutable, event())[@"Languages"] isEqual:(@[@"en-US"])]);
    NSMutableArray *limit = [NSMutableArray array]; for (int i = 0; i < 32; i++) [limit addObject:@"en-US"];
    mutableResolved[@"Languages"] = limit;
    assert([SHDWLocalizationSnapshot(SHDWLocalizationBootstrapMessage(original, mutableResolved, @"test.SDKProbe"), event())[@"Languages"] count] == 32);
    assert(!SHDWLocalizationSnapshot(NULL, event()) && !SHDWLocalizationSnapshot(bootstrap(), NULL));
    assert(!SHDWLocalizationSnapshot(nonDictionary, event()) && !SHDWLocalizationSnapshot(bootstrap(), nonDictionary));
    for (const char *field : (const char *[]){"message-name", "service-name", "client-bundle-identifier"}) {
        xpc_object_t launch = event(); xpc_dictionary_set_value(launch, field, NULL);
        assert(!SHDWLocalizationSnapshot(bootstrap(), launch));
        xpc_dictionary_set_uint64(launch, field, 1); assert(!SHDWLocalizationSnapshot(bootstrap(), launch));
        xpc_dictionary_set_string(launch, field, "mismatch"); assert(!SHDWLocalizationSnapshot(bootstrap(), launch));
    }
    for (const char *field : (const char *[]){"version", "owner-bundle-identifier", "locale-identifier", "languages", "time-zone"}) {
        xpc_object_t bad = bootstrap(), payload = xpc_dictionary_get_value(bad, key);
        xpc_dictionary_set_value(payload, field, NULL); assert(!SHDWLocalizationSnapshot(bad, event()));
        xpc_dictionary_set_bool(payload, field, true); assert(!SHDWLocalizationSnapshot(bad, event()));
    }
    for (uint64_t version : (uint64_t []){0, 2, UINT64_MAX}) {
        xpc_object_t bad = bootstrap(); xpc_dictionary_set_uint64(xpc_dictionary_get_value(bad, key), "version", version);
        assert(!SHDWLocalizationSnapshot(bad, event()));
    }
    xpc_object_t bad = bootstrap(), payload = xpc_dictionary_get_value(bad, key);
    xpc_dictionary_set_int64(payload, "version", 1); assert(!SHDWLocalizationSnapshot(bad, event()));
    bad = bootstrap(); xpc_dictionary_set_string(bad, key, "wrong"); assert(!SHDWLocalizationSnapshot(bad, event()));
    bad = bootstrap(); xpc_dictionary_set_value(bad, key, NULL); assert(!SHDWLocalizationSnapshot(bad, event()));
    for (const char *invalid : (const char *[]){"", "bogus", "en\n", "\xff"}) {
        bad = bootstrap(); payload = xpc_dictionary_get_value(bad, key);
        xpc_dictionary_set_string(payload, "locale-identifier", invalid); assert(!SHDWLocalizationSnapshot(bad, event()));
    }
    for (const char *field : (const char *[]){"owner-bundle-identifier", "locale-identifier", "time-zone"}) {
        bad = bootstrap(); payload = xpc_dictionary_get_value(bad, key);
        xpc_dictionary_set_string(payload, field, longString.UTF8String); assert(!SHDWLocalizationSnapshot(bad, event()));
    }
    bad = bootstrap(); payload = xpc_dictionary_get_value(bad, key);
    xpc_dictionary_set_string(payload, "time-zone", "Moon/Test"); assert(!SHDWLocalizationSnapshot(bad, event()));
    for (NSString *invalid in @[@"", @"bogus", @"en\n", longString]) {
        bad = bootstrap(); payload = xpc_dictionary_get_value(bad, key);
        xpc_object_t languages = xpc_array_create(NULL, 0);
        xpc_array_set_string(languages, XPC_ARRAY_APPEND, invalid.UTF8String);
        xpc_dictionary_set_value(payload, "languages", languages); assert(!SHDWLocalizationSnapshot(bad, event()));
    }
    for (int count : (int []){0, 1, 33}) {
        bad = bootstrap(); payload = xpc_dictionary_get_value(bad, key);
        xpc_object_t languages = xpc_array_create(NULL, 0);
        for (int i = 0; i < count; i++) xpc_array_set_uint64(languages, XPC_ARRAY_APPEND, 1);
        xpc_dictionary_set_value(payload, "languages", languages); assert(!SHDWLocalizationSnapshot(bad, event()));
    }
    assert([[NSUserDefaults.standardUserDefaults volatileDomainForName:NSArgumentDomain] isEqual:volatileBefore]);
    NSDictionary *persistentAfter = [NSUserDefaults.standardUserDefaults persistentDomainForName:@"test.SDKProbe"];
    assert(persistentAfter == persistentBefore || [persistentAfter isEqual:persistentBefore]);
    NSDictionary *globalAfter = [NSUserDefaults.standardUserDefaults persistentDomainForName:NSGlobalDomain];
    assert(globalAfter == globalBefore || [globalAfter isEqual:globalBefore]);
    puts("localization bootstrap: typed roundtrip, ownership, malformed payloads, immutable values, no preference changes passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-localization-bootstrap-") as temporary:
    temporary = Path(temporary)
    test, binary = temporary / "test.mm", temporary / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang++", "-x", "objective-c++", "-std=c++17", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(root / "src/Localization"),
                    str(test), str(root / "src/Localization/Bootstrap.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
