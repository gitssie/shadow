"""Validate localization choices and resolve one immutable native snapshot centrally."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
framework = root / "src/Shadow.framework"
production = (framework / "Fingerprint/Configuration.m").read_text()
production = production.replace("NSLocale.currentLocale", "fixtureLocale()")
production = production.replace("NSLocale.preferredLanguages", "fixtureLanguages()")
production = production.replace("NSTimeZone.systemTimeZone", "fixtureZone()")
source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
static NSUInteger captures;
static NSLocale *fixtureLocale(void) { captures++; return [[NSLocale alloc] initWithLocaleIdentifier:@"fr_FR@calendar=buddhist"]; }
static NSArray *fixtureLanguages(void) { return @[@"en-GB", @"fr-FR"]; }
static NSTimeZone *fixtureZone(void) { return [NSTimeZone timeZoneWithName:@"Europe/Paris"]; }
''' + production + r'''
static NSDictionary *validate(NSDictionary *base, id localization) {
  NSMutableDictionary *config = [base mutableCopy];
  if (localization) config[@"Localization"] = localization;
  else [config removeObjectForKey:@"Localization"];
  return [SHDWFingerprintConfiguration configurationByValidating:config error:nil];
}
int main(void) { @autoreleasepool {
  NSDictionary *base = SHDWFingerprintConfiguration.defaultConfiguration;
  assert([base[@"Localization"] isEqual:(@{@"Region":@"native", @"Language":@"native", @"TimeZone":@"native"})]);
  NSArray *regions = [SHDWFingerprintConfiguration supportedLocalizationRegions];
  assert([regions isEqual:(@[@"FR", @"GB", @"US"])] && ![regions isKindOfClass:NSMutableArray.class]);
  NSArray *presets = @[
    @{@"Region":@"FR", @"Language":@"fr-FR", @"TimeZone":@"Europe/Paris"},
    @{@"Region":@"GB", @"Language":@"en-GB", @"TimeZone":@"Europe/London"},
    @{@"Region":@"US", @"Language":@"en-US", @"TimeZone":@"America/New_York"},
    @{@"Region":@"native", @"Language":@"native", @"TimeZone":@"native"}
  ];
  NSDictionary *baseBeforeSelections = [base copy];
  for (NSDictionary *expected in presets) {
    NSDictionary *byRegion = [SHDWFingerprintConfiguration localizationForRegion:expected[@"Region"]];
    NSDictionary *byLanguage = [SHDWFingerprintConfiguration localizationForLanguage:expected[@"Language"]];
    assert([byRegion isEqual:expected] && [byLanguage isEqual:expected]);
    assert(![byRegion isKindOfClass:NSMutableDictionary.class] && ![byLanguage isKindOfClass:NSMutableDictionary.class]);
    assert([[SHDWFingerprintConfiguration timeZoneForRegion:expected[@"Region"]] isEqual:expected[@"TimeZone"]]);
    NSMutableDictionary *edited = [byRegion mutableCopy]; edited[@"Language"] = @"changed";
    assert([[SHDWFingerprintConfiguration localizationForRegion:expected[@"Region"]] isEqual:expected]);
  }
  assert([[SHDWFingerprintConfiguration localizationForRegion:@"gb"] isEqual:presets[1]]);
  assert([[SHDWFingerprintConfiguration localizationForLanguage:@"FR-fr"] isEqual:presets[0]]);
  assert([[SHDWFingerprintConfiguration localizationForLanguage:@"EN-us"] isEqual:presets[2]]);
  for (id unsupported in @[@"en", @"fr", @"en-AU", @"zh-Hant-TW", @"en-US-u-ca-buddhist", @"", @"Native", @1, NSNull.null])
    assert(![SHDWFingerprintConfiguration localizationForLanguage:unsupported]);
  for (id unsupported in @[@"DE", @"CA", @"", @"Native", @1, NSNull.null]) {
    assert(![SHDWFingerprintConfiguration localizationForRegion:unsupported]);
    assert(![SHDWFingerprintConfiguration timeZoneForRegion:unsupported]);
  }
  assert([base isEqual:baseBeforeSelections]);
  NSMutableDictionary *historical = [base mutableCopy];
  [historical removeObjectForKey:@"Localization"];
  historical[@"System"] = @{@"Mode":@"native"};
  historical[@"Network"] = @{@"RadioTechnologies":@[@"4g"]};
  historical[@"Receipts"] = @{@"InterceptEnabled":@NO};
  historical[@"Advertising"] = @{@"Mode":@"zero"};
  NSDictionary *historicalBefore = [historical copy];
  NSDictionary *normalized = [SHDWFingerprintConfiguration configurationByValidating:historical error:nil];
  assert(normalized);
  assert([normalized[@"Localization"] isEqual:base[@"Localization"]]);
  assert([normalized[@"Network"] isEqual:(@{@"RadioTechnologies":@[@"4g"], @"Transport":@"auto"})]);
  for (NSString *key in @[@"System",@"Receipts",@"Advertising"])
    assert([normalized[key] isEqual:historical[key]]);
  assert([historical isEqual:historicalBefore] && !historical[@"Localization"]);
  for (NSString *key in @[@"Region",@"Language",@"TimeZone"]) {
    NSMutableDictionary *incomplete = [base[@"Localization"] mutableCopy];
    [incomplete removeObjectForKey:key];
    assert(!validate(base,incomplete));
    assert(![SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:@{@"Localization":incomplete}]);
  }

  NSDictionary *native = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:base];
  assert([native[@"LocaleIdentifier"] isEqual:@"fr_FR@calendar=buddhist"]);
  assert([native[@"Languages"] isEqual:(@[@"en-GB",@"fr-FR"])]);
  assert([native[@"CountryCode"] isEqual:@"FR"] && [native[@"TimeZone"] isEqual:@"Europe/Paris"]);
  assert(![native[@"OverridesSystem"] boolValue] && captures == 1);
  assert([[SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:historical] isEqual:native]);
  assert([[SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:@{}] isEqual:native]);
  NSDictionary *us = validate(base,@{@"Region":@"us", @"Language":@"en-us", @"TimeZone":@"America/New_York"});
  assert([us[@"Localization"][@"Region"] isEqual:@"US"]);
  assert([us[@"Localization"][@"Language"] isEqual:@"en-US"]);
  NSDictionary *resolved = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:us];
  assert([resolved[@"LocaleIdentifier"] isEqual:@"en_US"]);
  assert([resolved[@"Languages"] isEqual:(@[@"en-US"])]);
  assert([resolved[@"CountryCode"] isEqual:@"US"] && [resolved[@"TimeZone"] isEqual:@"America/New_York"]);
  assert([resolved[@"OverridesSystem"] boolValue] && captures == 1);
  NSDictionary *mixed = validate(base,@{@"Region":@"US", @"Language":@"native", @"TimeZone":@"native"});
  resolved = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:mixed];
  assert([resolved[@"LocaleIdentifier"] isEqual:@"fr_US"]);
  assert([resolved[@"Languages"] isEqual:native[@"Languages"]]);
  assert([resolved[@"TimeZone"] isEqual:@"America/New_York"]);
  mixed = validate(base,@{@"Region":@"native", @"Language":@"zh-hant-tw", @"TimeZone":@"native"});
  resolved = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:mixed];
  assert([resolved[@"LocaleIdentifier"] isEqual:@"zh_Hant_FR"]);
  assert([resolved[@"Languages"] isEqual:(@[@"zh-Hant-TW"])]);
  assert([resolved[@"TimeZone"] isEqual:native[@"TimeZone"]]);
  mixed = validate(base,@{@"Region":@"native", @"Language":@"native", @"TimeZone":@"America/New_York"});
  resolved = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:mixed];
  assert([resolved[@"LocaleIdentifier"] isEqual:native[@"LocaleIdentifier"]]);
  assert(![resolved[@"OverridesSystem"] boolValue]);
  assert([resolved[@"TimeZone"] isEqual:native[@"TimeZone"]]);
  NSDictionary *extended = validate(base,@{@"Region":@"GB",@"Language":@"en-US-u-nu-arab-ca-buddhist",@"TimeZone":@"native"});
  NSDictionary *extendedResolved = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:extended];
  NSLocale *extendedLocale = [[NSLocale alloc] initWithLocaleIdentifier:extendedResolved[@"LocaleIdentifier"]];
  assert([[extendedLocale objectForKey:NSLocaleCountryCode] isEqual:@"GB"]);
  assert([[[extendedLocale objectForKey:NSLocaleCalendar] calendarIdentifier] isEqual:NSCalendarIdentifierBuddhist]);
  assert([[NSLocale componentsFromLocaleIdentifier:extendedResolved[@"LocaleIdentifier"]][@"numbers"] isEqual:@"arab"]);
  assert([extendedResolved[@"Languages"] isEqual:(@[extended[@"Localization"][@"Language"]])]);
  NSDictionary *variant = validate(base,@{@"Region":@"US",@"Language":@"de-CH-1901",@"TimeZone":@"native"});
  NSDictionary *variantResolved = [SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:variant];
  NSDictionary *variantComponents = [NSLocale componentsFromLocaleIdentifier:variantResolved[@"LocaleIdentifier"]];
  assert([variantComponents[NSLocaleCountryCode] isEqual:@"US"]);
  assert([variantComponents[NSLocaleVariantCode] isEqual:@"1901"]);
  NSDictionary *regionalZones = @{@"FR":@"Europe/Paris",@"GB":@"Europe/London",@"US":@"America/New_York"};
  for (NSString *region in regionalZones) {
    NSDictionary *automatic = validate(base,@{@"Region":region,@"Language":@"native",@"TimeZone":@"native"});
    assert([automatic[@"Localization"][@"TimeZone"] isEqual:regionalZones[region]]);
    assert([[SHDWFingerprintConfiguration resolvedLocalizationForConfiguration:automatic][@"TimeZone"] isEqual:regionalZones[region]]);
    NSDictionary *mismatched = validate(base,@{@"Region":region,@"Language":@"native",@"TimeZone":@"Europe/Paris"});
    assert([mismatched[@"Localization"][@"TimeZone"] isEqual:regionalZones[region]]);
  }
  NSDictionary *uk = validate(base,@{@"Region":@"gb",@"Language":@"native",@"TimeZone":@"native"});
  NSTimeZone *london = [NSTimeZone timeZoneWithName:uk[@"Localization"][@"TimeZone"]];
  assert([london secondsFromGMTForDate:[NSDate dateWithTimeIntervalSince1970:1736942400]] == 0);
  assert([london secondsFromGMTForDate:[NSDate dateWithTimeIntervalSince1970:1752580800]] == 3600);
  for (NSString *language in @[@"en",@"en-US-u-ca-buddhist",@"iw-IL",@"de-CH-1901"]) {
    NSDictionary *legacy = @{@"Region":@"native",@"Language":language,@"TimeZone":@"native"};
    NSDictionary *before = [legacy copy];
    NSDictionary *accepted = validate(base,legacy);
    assert(accepted && [legacy isEqual:before]);
    assert([accepted[@"Localization"][@"Language"] isEqual:SHDWConfigurationLanguage(language)]);
  }
  for (id invalid in @[NSNull.null,@YES,@[],@{},@{@"Region":@"US",@"Language":@"en",@"TimeZone":@"native",@"Extra":@1}]) assert(!validate(base,invalid));
  for (id region in @[@1,@"",@"USA",@"ZZ",@"DE",@"CN",@"CA",@"us_US",@"Native",@"ß"]) assert(!validate(base,@{@"Region":region,@"Language":@"native",@"TimeZone":@"native"}));
  for (id language in @[@1,@"",@"bogus",@"en_US",@"en--US",@"en\n",@"en@calendar=x",@"en-u-ca-gregory-u-nu-latn",@"de-1901-1901"]) assert(!validate(base,@{@"Region":@"native",@"Language":language,@"TimeZone":@"native"}));
  for (id zone in @[@1,@"",@"GMT+0100",@"Moon/Test",@"Asia/Tokyo",@"UTC",@"Etc/UTC"]) assert(!validate(base,@{@"Region":@"native",@"Language":@"native",@"TimeZone":zone}));
  NSMutableDictionary *mutable = [@{@"Region":@"US",@"Language":@"en",@"TimeZone":@"America/New_York"} mutableCopy];
  NSDictionary *pinned = validate(base,mutable);
  mutable[@"Region"] = @"GB";
  assert([pinned[@"Localization"][@"Region"] isEqual:@"US"]);
  assert(![pinned isKindOfClass:NSMutableDictionary.class]);
  assert(![pinned[@"Localization"] isKindOfClass:NSMutableDictionary.class]);
  assert(![native[@"Languages"] isKindOfClass:NSMutableArray.class]);
  puts("localization config: missing block follows native without changing saved settings, linked immutable selection presets, legacy languages, FR/GB/US automatic timezones, UK DST, strict choices, immutable native snapshot passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-localization-config-") as temporary:
    temporary = Path(temporary)
    test, binary = temporary / "test.m", temporary / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation",
                    "-I", str(framework / "Headers"), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
