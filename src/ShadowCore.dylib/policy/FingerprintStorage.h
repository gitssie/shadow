#import <Foundation/Foundation.h>

NSString *SHDWFingerprintOwnerIdentifier(NSString *bundleID);
NSUUID *SHDWFingerprintStoredVendorIdentifier(NSString *bundleID);
NSDictionary *SHDWFingerprintData(NSString *bundleID);
NSDictionary *SHDWFingerprintConfig(NSString *bundleID);

NSDictionary *SHDWFingerprintSystem(NSString *bundleID);
