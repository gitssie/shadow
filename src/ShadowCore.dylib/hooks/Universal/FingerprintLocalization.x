#import "UniversalHooks.h"
#import "../../policy/FingerprintLocalization.h"
#import "../../policy/WebLocalization.h"
#import "../../../Localization/Environment.h"
#import <CoreFoundation/CoreFoundation.h>

static NSLocale *shdw_localization_locale;
static NSTimeZone *shdw_localization_zone;
static NSArray *shdw_localization_preferred_languages;

static BOOL shdw_localization_applies(void) {
    return shdw_localization_locale && ![Shadow shdwIsInternalRead];
}

static id (*shdw_original_currentLocale)(id, SEL);
static id (*shdw_original_autoupdatingLocale)(id, SEL);
static id (*shdw_original_languages)(id, SEL);
static id (*shdw_original_systemZone)(id, SEL);
static id (*shdw_original_localZone)(id, SEL);
static id (*shdw_original_defaultZone)(id, SEL);
static id (*shdw_original_currentCalendar)(id, SEL);
static id (*shdw_original_autoupdatingCalendar)(id, SEL);

#define SHDW_LOCALIZATION_METHOD(name, value) \
static id shdw_localization_##name(id self, SEL command) { \
    int saved = errno; \
    BOOL applies = shdw_localization_applies(); \
    errno = saved; \
    if(!applies) return shdw_original_##name(self, command); \
    return value; \
}

SHDW_LOCALIZATION_METHOD(currentLocale, shdw_localization_locale)
SHDW_LOCALIZATION_METHOD(autoupdatingLocale, shdw_localization_locale)
SHDW_LOCALIZATION_METHOD(languages, shdw_localization_preferred_languages)
SHDW_LOCALIZATION_METHOD(systemZone, shdw_localization_zone)
SHDW_LOCALIZATION_METHOD(localZone, shdw_localization_zone)
SHDW_LOCALIZATION_METHOD(defaultZone, shdw_localization_zone)

static id shdw_localization_calendar(id self, SEL command, id (*original)(id, SEL)) {
    int saved = errno;
    BOOL applies = shdw_localization_applies();
    errno = saved;
    NSCalendar *calendar = original(self, command);
    if(!applies) return calendar;
    saved = errno;
    // The locale owns the default calendar choice as well as formatting rules.
    // Copying the native calendar would retain e.g. Buddhist under en_US.
    calendar = [[shdw_localization_locale objectForKey:NSLocaleCalendar] copy];
    calendar.locale = shdw_localization_locale;
    calendar.timeZone = shdw_localization_zone;
    errno = saved;
    return calendar;
}

static id shdw_localization_currentCalendar(id self, SEL command) {
    return shdw_localization_calendar(self, command, shdw_original_currentCalendar);
}
static id shdw_localization_autoupdatingCalendar(id self, SEL command) {
    return shdw_localization_calendar(self, command, shdw_original_autoupdatingCalendar);
}

static CFLocaleRef (*shdw_original_copyLocale)(void);
static CFArrayRef (*shdw_original_copyLanguages)(void);
static CFTimeZoneRef (*shdw_original_copySystemZone)(void);
static CFTimeZoneRef (*shdw_original_copyDefaultZone)(void);
static unsigned shdw_localization_cf_ready;

#define SHDW_LOCALIZATION_COPY(name, type, value) \
static type shdw_localization_##name(void) { \
    int saved = errno; \
    BOOL applies = shdw_localization_applies(); \
    errno = saved; \
    if(!applies) return shdw_original_##name(); \
    type result = (type)CFRetain((__bridge CFTypeRef)value); \
    errno = saved; \
    return result; \
}

SHDW_LOCALIZATION_COPY(copyLocale, CFLocaleRef, shdw_localization_locale)
SHDW_LOCALIZATION_COPY(copyLanguages, CFArrayRef, shdw_localization_preferred_languages)
SHDW_LOCALIZATION_COPY(copySystemZone, CFTimeZoneRef, shdw_localization_zone)
SHDW_LOCALIZATION_COPY(copyDefaultZone, CFTimeZoneRef, shdw_localization_zone)

void *shdw_sym_policy_lookup_localization(const char *name) {
    if(!name || !__atomic_load_n(&shdw_localization_cf_ready, __ATOMIC_ACQUIRE)) return NULL;
#define SHDW_LOCALIZATION_SYMBOL(symbol, function) \
    if(!strcmp(name, #symbol) && shdw_original_##function) \
        return (void *)&shdw_localization_##function
    SHDW_LOCALIZATION_SYMBOL(CFLocaleCopyCurrent, copyLocale);
    SHDW_LOCALIZATION_SYMBOL(CFLocaleCopyPreferredLanguages, copyLanguages);
    SHDW_LOCALIZATION_SYMBOL(CFTimeZoneCopySystem, copySystemZone);
    SHDW_LOCALIZATION_SYMBOL(CFTimeZoneCopyDefault, copyDefaultZone);
#undef SHDW_LOCALIZATION_SYMBOL
    return NULL;
}

void shdw_universal_fingerprint_localization(SHDWHookSession *hooks) {
    NSDictionary *resolved = SHDWFingerprintLocalization();
    if(![resolved[@"OverridesSystem"] boolValue]) return;
    BOOL applied = NO;
    SHADOW_INTERNAL_SCOPE {
        applied = SHDWLocalizationApplyEnvironment(resolved);
        if(applied) {
            shdw_localization_locale = [[NSLocale alloc] initWithLocaleIdentifier:resolved[@"LocaleIdentifier"]];
            shdw_localization_zone = [NSTimeZone timeZoneWithName:resolved[@"TimeZone"]];
            shdw_localization_preferred_languages = [resolved[@"Languages"] copy];
        }
    }
    if(!applied) return;

#define SHDW_LOCALIZATION_HOOK(cls, selname, name) \
    [hooks hookMessageInClass:object_getClass(cls.class) withSelector:@selector(selname) \
        withReplacement:shdw_localization_##name outOldPtr:(void **)&shdw_original_##name]
    SHDW_LOCALIZATION_HOOK(NSLocale, currentLocale, currentLocale);
    SHDW_LOCALIZATION_HOOK(NSLocale, autoupdatingCurrentLocale, autoupdatingLocale);
    SHDW_LOCALIZATION_HOOK(NSLocale, preferredLanguages, languages);
    SHDW_LOCALIZATION_HOOK(NSTimeZone, systemTimeZone, systemZone);
    SHDW_LOCALIZATION_HOOK(NSTimeZone, localTimeZone, localZone);
    SHDW_LOCALIZATION_HOOK(NSTimeZone, defaultTimeZone, defaultZone);
    SHDW_LOCALIZATION_HOOK(NSCalendar, currentCalendar, currentCalendar);
    SHDW_LOCALIZATION_HOOK(NSCalendar, autoupdatingCurrentCalendar, autoupdatingCalendar);
#undef SHDW_LOCALIZATION_HOOK

    SHADOW_INTERNAL_SCOPE {
#define SHDW_LOCALIZATION_ORIGINAL(symbol, name) \
        shdw_original_##name = (__typeof__(shdw_original_##name))dlsym(RTLD_DEFAULT, #symbol)
        SHDW_LOCALIZATION_ORIGINAL(CFLocaleCopyCurrent, copyLocale);
        SHDW_LOCALIZATION_ORIGINAL(CFLocaleCopyPreferredLanguages, copyLanguages);
        SHDW_LOCALIZATION_ORIGINAL(CFTimeZoneCopySystem, copySystemZone);
        SHDW_LOCALIZATION_ORIGINAL(CFTimeZoneCopyDefault, copyDefaultZone);
#undef SHDW_LOCALIZATION_ORIGINAL
    }
    __atomic_store_n(&shdw_localization_cf_ready, 1, __ATOMIC_RELEASE);
#define SHDW_LOCALIZATION_FUNCTION(symbol, name) \
    if(shdw_original_##name) \
        [hooks hookRebindSymbol:@#symbol withReplacement:shdw_localization_##name outOldPtr:NULL]
    SHDW_LOCALIZATION_FUNCTION(CFLocaleCopyCurrent, copyLocale);
    SHDW_LOCALIZATION_FUNCTION(CFLocaleCopyPreferredLanguages, copyLanguages);
    SHDW_LOCALIZATION_FUNCTION(CFTimeZoneCopySystem, copySystemZone);
    SHDW_LOCALIZATION_FUNCTION(CFTimeZoneCopyDefault, copyDefaultZone);
#undef SHDW_LOCALIZATION_FUNCTION
    SHDWFingerprintInstallWebLocalization();
}
