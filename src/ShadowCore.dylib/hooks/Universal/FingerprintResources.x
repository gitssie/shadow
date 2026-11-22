#import "UniversalHooks.h"
#import <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <string.h>

static NSArray *shdw_resource_languages;
static unsigned shdw_resource_ready;
static BOOL shdw_resource_applies(void) {
    return shdw_resource_languages && ![Shadow shdwIsInternalRead];
}

static NSArray *shdw_resource_choices(NSArray *available) {
    if(!available) return nil;
    return CFBridgingRelease(CFBundleCopyLocalizationsForPreferences(
        (__bridge CFArrayRef)available, (__bridge CFArrayRef)shdw_resource_languages));
}

static NSArray *shdw_resource_bundle_choices(NSBundle *bundle) {
    NSArray *available = bundle.localizations;
    NSMutableArray *preferences = [shdw_resource_languages mutableCopy];
    if(bundle.developmentLocalization) [preferences addObject:bundle.developmentLocalization];
    NSArray *choices = available ? CFBridgingRelease(CFBundleCopyLocalizationsForPreferences(
        (__bridge CFArrayRef)available, (__bridge CFArrayRef)preferences)) : nil;
    return choices;
}

static NSString *shdw_resource_localization(NSBundle *bundle) {
    return shdw_resource_bundle_choices(bundle).firstObject;
}

static NSBundle *shdw_resource_localized_bundle(NSBundle *bundle, NSString *table) {
    NSString *language = shdw_resource_localization(bundle);
    if(!language) return nil;
    NSString *name = table.length ? table : @"Localizable";
    NSURL *tableURL = [bundle URLForResource:name withExtension:@"strings" subdirectory:nil localization:language];
    if(!tableURL) tableURL = [bundle URLForResource:name withExtension:@"stringsdict" subdirectory:nil localization:language];
    NSURL *url = tableURL ? tableURL.URLByDeletingLastPathComponent :
        [bundle.resourceURL URLByAppendingPathComponent:[language stringByAppendingPathExtension:@"lproj"] isDirectory:YES];
    if([url isEqual:bundle.resourceURL]) return bundle;
    return url ? [NSBundle bundleWithURL:url] : nil;
}

static id (*shdw_resource_original_preferred)(id, SEL);
static id shdw_resource_preferred(id self, SEL command) {
    int saved = errno;
    if(!shdw_resource_applies()) { errno = saved; return shdw_resource_original_preferred(self, command); }
    NSArray *result;
    SHADOW_INTERNAL_SCOPE {
        result = shdw_resource_bundle_choices(self);
    }
    errno = saved;
    return result ?: shdw_resource_original_preferred(self, command);
}

static id (*shdw_resource_original_select)(id, SEL, id);
static id shdw_resource_select(id self, SEL command, id available) {
    int saved = errno;
    if(!shdw_resource_applies()) { errno = saved; return shdw_resource_original_select(self, command, available); }
    id result;
    SHADOW_INTERNAL_SCOPE { result = shdw_resource_choices(available); }
    errno = saved;
    return result ?: shdw_resource_original_select(self, command, available);
}

static id (*shdw_resource_original_selectPreferences)(id, SEL, id, id);
static id shdw_resource_selectPreferences(id self, SEL command, id available, id preferences) {
    int saved = errno;
    BOOL applies = !preferences && shdw_resource_applies();
    errno = saved;
    return shdw_resource_original_selectPreferences(self, command, available,
        applies ? shdw_resource_languages : preferences);
}

static id (*shdw_resource_original_string)(id, SEL, id, id, id);
static id shdw_resource_string(id self, SEL command, id key, id value, id table) {
    int saved = errno;
    if(!shdw_resource_applies()) { errno = saved; return shdw_resource_original_string(self, command, key, value, table); }
    id result;
    SHADOW_INTERNAL_SCOPE {
        NSBundle *localized = shdw_resource_localized_bundle(self, table);
        result = shdw_resource_original_string(localized ?: self, command, key, value, table);
    }
    errno = saved;
    return result;
}

static id (*shdw_resource_original_url)(id, SEL, id, id, id, id);
static id shdw_resource_url(id self, SEL command, id name, id extension, id subpath, id localization) {
    int saved = errno;
    BOOL applies = !localization && shdw_resource_applies();
    if(applies) { SHADOW_INTERNAL_SCOPE { localization = shdw_resource_localization(self); } }
    errno = saved;
    return shdw_resource_original_url(self, command, name, extension, subpath, localization);
}
static id (*shdw_resource_original_urls)(id, SEL, id, id, id);
static id shdw_resource_urls(id self, SEL command, id extension, id subpath, id localization) {
    int saved = errno;
    BOOL applies = !localization && shdw_resource_applies();
    if(applies) { SHADOW_INTERNAL_SCOPE { localization = shdw_resource_localization(self); } }
    errno = saved;
    return shdw_resource_original_urls(self, command, extension, subpath, localization);
}
static id (*shdw_resource_original_path)(id, SEL, id, id, id, id);
static id shdw_resource_path(id self, SEL command, id name, id extension, id subpath, id localization) {
    int saved = errno;
    BOOL applies = !localization && shdw_resource_applies();
    if(applies) { SHADOW_INTERNAL_SCOPE { localization = shdw_resource_localization(self); } }
    errno = saved;
    return shdw_resource_original_path(self, command, name, extension, subpath, localization);
}
static id (*shdw_resource_original_paths)(id, SEL, id, id, id);
static id shdw_resource_paths(id self, SEL command, id extension, id subpath, id localization) {
    int saved = errno;
    BOOL applies = !localization && shdw_resource_applies();
    if(applies) { SHADOW_INTERNAL_SCOPE { localization = shdw_resource_localization(self); } }
    errno = saved;
    return shdw_resource_original_paths(self, command, extension, subpath, localization);
}


static id (*shdw_resource_original_shortURL)(id, SEL, id, id);
static id shdw_resource_shortURL(id self, SEL command, id name, id extension) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_shortURL(self, command, name, extension);
    return [self URLForResource:name withExtension:extension subdirectory:nil localization:nil];
}
static id (*shdw_resource_original_subURL)(id, SEL, id, id, id);
static id shdw_resource_subURL(id self, SEL command, id name, id extension, id subpath) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_subURL(self, command, name, extension, subpath);
    return [self URLForResource:name withExtension:extension subdirectory:subpath localization:nil];
}
static id (*shdw_resource_original_shortURLs)(id, SEL, id, id);
static id shdw_resource_shortURLs(id self, SEL command, id extension, id subpath) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_shortURLs(self, command, extension, subpath);
    return [self URLsForResourcesWithExtension:extension subdirectory:subpath localization:nil];
}
static id (*shdw_resource_original_shortPath)(id, SEL, id, id);
static id shdw_resource_shortPath(id self, SEL command, id name, id extension) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_shortPath(self, command, name, extension);
    return [self pathForResource:name ofType:extension inDirectory:nil forLocalization:nil];
}
static id (*shdw_resource_original_subPath)(id, SEL, id, id, id);
static id shdw_resource_subPath(id self, SEL command, id name, id extension, id subpath) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_subPath(self, command, name, extension, subpath);
    return [self pathForResource:name ofType:extension inDirectory:subpath forLocalization:nil];
}
static id (*shdw_resource_original_shortPaths)(id, SEL, id, id);
static id shdw_resource_shortPaths(id self, SEL command, id extension, id subpath) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_shortPaths(self, command, extension, subpath);
    return [self pathsForResourcesOfType:extension inDirectory:subpath forLocalization:nil];
}
static CFArrayRef (*shdw_resource_original_cfPreferred)(CFArrayRef);
static CFArrayRef shdw_resource_cfPreferred(CFArrayRef available) {
    int saved = errno;
    BOOL applies = shdw_resource_applies();
    errno = saved;
    if(!applies) return shdw_resource_original_cfPreferred(available);
    return CFBundleCopyLocalizationsForPreferences(available, (__bridge CFArrayRef)shdw_resource_languages);
}
static CFArrayRef (*shdw_resource_original_cfPreferences)(CFArrayRef, CFArrayRef);
static CFArrayRef shdw_resource_cfPreferences(CFArrayRef available, CFArrayRef preferences) {
    int saved = errno;
    BOOL applies = !preferences && shdw_resource_applies();
    errno = saved;
    return shdw_resource_original_cfPreferences(available,
        applies ? (__bridge CFArrayRef)shdw_resource_languages : preferences);
}
static CFStringRef (*shdw_resource_original_cfString)(CFBundleRef, CFStringRef, CFStringRef, CFStringRef);
static CFStringRef shdw_resource_cfString(CFBundleRef bundle, CFStringRef key, CFStringRef value, CFStringRef table) {
    int saved = errno;
    if(!bundle || !shdw_resource_applies()) { errno = saved; return shdw_resource_original_cfString(bundle, key, value, table); }
    CFStringRef result;
    SHADOW_INTERNAL_SCOPE {
        NSURL *url = CFBridgingRelease(CFBundleCopyBundleURL(bundle));
        NSBundle *localized = shdw_resource_localized_bundle([NSBundle bundleWithURL:url], (__bridge NSString *)table);
        CFBundleRef target = localized ? CFBundleCreate(NULL, (__bridge CFURLRef)localized.bundleURL) : NULL;
        result = shdw_resource_original_cfString(target ?: bundle, key, value, table);
        if(target) CFRelease(target);
    }
    errno = saved;
    return result;
}


static NSString *shdw_resource_cf_localization(CFBundleRef bundle) {
    NSURL *url = CFBridgingRelease(CFBundleCopyBundleURL(bundle));
    return url ? shdw_resource_localization([NSBundle bundleWithURL:url]) : nil;
}
static CFURLRef (*shdw_resource_original_cfURL)(CFBundleRef, CFStringRef, CFStringRef, CFStringRef);
static CFURLRef shdw_resource_cfURL(CFBundleRef bundle, CFStringRef name, CFStringRef extension, CFStringRef subpath) {
    int saved = errno;
    if(!bundle || !shdw_resource_applies()) { errno = saved; return shdw_resource_original_cfURL(bundle, name, extension, subpath); }
    NSString *language;
    SHADOW_INTERNAL_SCOPE { language = shdw_resource_cf_localization(bundle); }
    errno = saved;
    return language ? CFBundleCopyResourceURLForLocalization(bundle, name, extension, subpath, (__bridge CFStringRef)language)
        : shdw_resource_original_cfURL(bundle, name, extension, subpath);
}
static CFArrayRef (*shdw_resource_original_cfURLs)(CFBundleRef, CFStringRef, CFStringRef);
static CFArrayRef shdw_resource_cfURLs(CFBundleRef bundle, CFStringRef extension, CFStringRef subpath) {
    int saved = errno;
    if(!bundle || !shdw_resource_applies()) { errno = saved; return shdw_resource_original_cfURLs(bundle, extension, subpath); }
    NSString *language;
    SHADOW_INTERNAL_SCOPE { language = shdw_resource_cf_localization(bundle); }
    errno = saved;
    return language ? CFBundleCopyResourceURLsOfTypeForLocalization(bundle, extension, subpath, (__bridge CFStringRef)language)
        : shdw_resource_original_cfURLs(bundle, extension, subpath);
}
static CFURLRef (*shdw_resource_original_cfLocalizedURL)(CFBundleRef, CFStringRef, CFStringRef, CFStringRef, CFStringRef);
static CFURLRef shdw_resource_cfLocalizedURL(CFBundleRef bundle, CFStringRef name, CFStringRef extension, CFStringRef subpath, CFStringRef localization) {
    int saved = errno;
    NSString *language;
    if(bundle && !localization && shdw_resource_applies()) {
        SHADOW_INTERNAL_SCOPE { language = shdw_resource_cf_localization(bundle); }
    }
    errno = saved;
    return shdw_resource_original_cfLocalizedURL(bundle, name, extension, subpath, localization ?: (__bridge CFStringRef)language);
}
static CFArrayRef (*shdw_resource_original_cfLocalizedURLs)(CFBundleRef, CFStringRef, CFStringRef, CFStringRef);
static CFArrayRef shdw_resource_cfLocalizedURLs(CFBundleRef bundle, CFStringRef extension, CFStringRef subpath, CFStringRef localization) {
    int saved = errno;
    NSString *language;
    if(bundle && !localization && shdw_resource_applies()) {
        SHADOW_INTERNAL_SCOPE { language = shdw_resource_cf_localization(bundle); }
    }
    errno = saved;
    return shdw_resource_original_cfLocalizedURLs(bundle, extension, subpath, localization ?: (__bridge CFStringRef)language);
}
void *shdw_sym_policy_lookup_resources(const char *name) {
    if(!name || !__atomic_load_n(&shdw_resource_ready, __ATOMIC_ACQUIRE)) return NULL;
#define SHDW_RESOURCE_SYMBOL(symbol, suffix) \
    if(!strcmp(name, #symbol) && shdw_resource_original_##suffix) return (void *)&shdw_resource_##suffix
    SHDW_RESOURCE_SYMBOL(CFBundleCopyPreferredLocalizationsFromArray, cfPreferred);
    SHDW_RESOURCE_SYMBOL(CFBundleCopyLocalizationsForPreferences, cfPreferences);
    SHDW_RESOURCE_SYMBOL(CFBundleCopyLocalizedString, cfString);
    SHDW_RESOURCE_SYMBOL(CFBundleCopyResourceURL, cfURL);
    SHDW_RESOURCE_SYMBOL(CFBundleCopyResourceURLsOfType, cfURLs);
    SHDW_RESOURCE_SYMBOL(CFBundleCopyResourceURLForLocalization, cfLocalizedURL);
    SHDW_RESOURCE_SYMBOL(CFBundleCopyResourceURLsOfTypeForLocalization, cfLocalizedURLs);
#undef SHDW_RESOURCE_SYMBOL
    return NULL;
}

void shdw_universal_fingerprint_resources(SHDWHookSession *hooks, NSDictionary *resolved) {
    if(!hooks || __atomic_load_n(&shdw_resource_ready, __ATOMIC_ACQUIRE) ||
       ![resolved[@"OverridesSystem"] boolValue] || ![resolved[@"Languages"] count]) return;
    shdw_resource_languages = [resolved[@"Languages"] copy];
#define SHDW_RESOURCE_MESSAGE(cls, selectorName, suffix) \
    [hooks hookMessageInClass:cls withSelector:sel_registerName(selectorName) \
        withReplacement:shdw_resource_##suffix outOldPtr:(void **)&shdw_resource_original_##suffix]
    Class bundle = NSBundle.class;
    SHDW_RESOURCE_MESSAGE(bundle, "preferredLocalizations", preferred);
    SHDW_RESOURCE_MESSAGE(bundle, "URLForResource:withExtension:", shortURL);
    SHDW_RESOURCE_MESSAGE(bundle, "URLForResource:withExtension:subdirectory:", subURL);
    SHDW_RESOURCE_MESSAGE(bundle, "URLsForResourcesWithExtension:subdirectory:", shortURLs);
    SHDW_RESOURCE_MESSAGE(bundle, "pathForResource:ofType:", shortPath);
    SHDW_RESOURCE_MESSAGE(bundle, "pathForResource:ofType:inDirectory:", subPath);
    SHDW_RESOURCE_MESSAGE(bundle, "pathsForResourcesOfType:inDirectory:", shortPaths);
    SHDW_RESOURCE_MESSAGE(object_getClass(bundle), "preferredLocalizationsFromArray:", select);
    SHDW_RESOURCE_MESSAGE(object_getClass(bundle), "preferredLocalizationsFromArray:forPreferences:", selectPreferences);
    SHDW_RESOURCE_MESSAGE(bundle, "localizedStringForKey:value:table:", string);
    SHDW_RESOURCE_MESSAGE(bundle, "URLForResource:withExtension:subdirectory:localization:", url);
    SHDW_RESOURCE_MESSAGE(bundle, "URLsForResourcesWithExtension:subdirectory:localization:", urls);
    SHDW_RESOURCE_MESSAGE(bundle, "pathForResource:ofType:inDirectory:forLocalization:", path);
    SHDW_RESOURCE_MESSAGE(bundle, "pathsForResourcesOfType:inDirectory:forLocalization:", paths);
#undef SHDW_RESOURCE_MESSAGE
    SHADOW_INTERNAL_SCOPE {
#define SHDW_RESOURCE_CAPTURE(symbol, suffix) \
        shdw_resource_original_##suffix = (__typeof__(shdw_resource_original_##suffix))dlsym(RTLD_DEFAULT, #symbol)
        SHDW_RESOURCE_CAPTURE(CFBundleCopyPreferredLocalizationsFromArray, cfPreferred);
        SHDW_RESOURCE_CAPTURE(CFBundleCopyLocalizationsForPreferences, cfPreferences);
        SHDW_RESOURCE_CAPTURE(CFBundleCopyLocalizedString, cfString);
    SHDW_RESOURCE_CAPTURE(CFBundleCopyResourceURL, cfURL);
    SHDW_RESOURCE_CAPTURE(CFBundleCopyResourceURLsOfType, cfURLs);
    SHDW_RESOURCE_CAPTURE(CFBundleCopyResourceURLForLocalization, cfLocalizedURL);
    SHDW_RESOURCE_CAPTURE(CFBundleCopyResourceURLsOfTypeForLocalization, cfLocalizedURLs);
#undef SHDW_RESOURCE_CAPTURE
    }
    __atomic_store_n(&shdw_resource_ready, 1, __ATOMIC_RELEASE);
#define SHDW_RESOURCE_REBIND(symbol, suffix) \
    if(shdw_resource_original_##suffix) [hooks hookRebindSymbol:@#symbol \
        withReplacement:shdw_resource_##suffix outOldPtr:NULL]
    SHDW_RESOURCE_REBIND(CFBundleCopyPreferredLocalizationsFromArray, cfPreferred);
    SHDW_RESOURCE_REBIND(CFBundleCopyLocalizationsForPreferences, cfPreferences);
    SHDW_RESOURCE_REBIND(CFBundleCopyLocalizedString, cfString);
    SHDW_RESOURCE_REBIND(CFBundleCopyResourceURL, cfURL);
    SHDW_RESOURCE_REBIND(CFBundleCopyResourceURLsOfType, cfURLs);
    SHDW_RESOURCE_REBIND(CFBundleCopyResourceURLForLocalization, cfLocalizedURL);
    SHDW_RESOURCE_REBIND(CFBundleCopyResourceURLsOfTypeForLocalization, cfLocalizedURLs);
#undef SHDW_RESOURCE_REBIND
}
