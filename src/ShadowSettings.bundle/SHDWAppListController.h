#import <Foundation/Foundation.h>
#import <Preferences/PSListController.h>
#import <Preferences/PSSpecifier.h>

#import <AltList/ATLApplicationListSubcontroller.h>

@interface SHDWAppListController : ATLApplicationListSubcontroller
- (id)readPreferenceValue:(PSSpecifier *)specifier;
- (void)setPreferenceValue:(id)value forSpecifier:(PSSpecifier *)specifier;
- (void)refreshFingerprintData:(id)sender;
@end
