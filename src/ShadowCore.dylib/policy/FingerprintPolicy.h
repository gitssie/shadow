#import <Foundation/Foundation.h>
#include <stdint.h>

typedef struct { double latitude, longitude; } SHDWFingerprintCoordinate;
NSOperatingSystemVersion SHDWFingerprintOSVersion(void);
BOOL SHDWFingerprintInterceptsReceipts(void);
BOOL SHDWFingerprintOSVersionAtLeast(NSOperatingSystemVersion requested);
NSString *SHDWFingerprintOSVersionString(void);
NSUUID *SHDWFingerprintVendorIdentifier(NSString *bundleID);
NSString *SHDWFingerprintUserAgent(NSString *userAgent);
NSString *SHDWFingerprintWebClipboardScript(void);
const char *SHDWFingerprintVersionValue(const char *name);
struct utsname;
BOOL SHDWFingerprintUnameValue(struct utsname *value);
BOOL SHDWFingerprintVersionQuery(const char *name, void *value, size_t *length, int *result);
BOOL SHDWFingerprintBootName(const char *name);
BOOL SHDWFingerprintBootQuery(const char *name, void *value, size_t *length, int *result);
SHDWFingerprintCoordinate SHDWFingerprintCountryCenter(void);
SHDWFingerprintCoordinate SHDWFingerprintCountryCenterForCode(NSString *country);
uint64_t SHDWFingerprintMemorySize(NSString *bundleID, uint64_t nativeSize);
NSDictionary<NSString *, NSString *> *SHDWFingerprintRadioTechnologies(NSDictionary<NSString *, NSString *> *services);
void SHDWFingerprintSysctlValue(const char *name, void *value, size_t length);
NSDictionary<NSString *, NSNumber *> *SHDWFingerprintSIMState(void);
