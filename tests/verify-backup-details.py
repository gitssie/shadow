#!/usr/bin/env python3
"""Compile the saved-backup presentation against the real Foundation presets."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
code = r'''#import <Foundation/Foundation.h>
#import "BackupPresentation.h"
#import <Shadow/FingerprintConfiguration.h>
#include <assert.h>
NSString *SHDWLocalizedText(NSString *key) { return key; }
static NSString *value(NSArray *fields, NSString *label) {
 for (NSDictionary *field in fields) if ([field[@"label"] isEqual:label]) return field[@"value"];
 abort();
}
int main(void) { @autoreleasepool {
 for (NSString *region in @[@"FR",@"GB",@"US",@"DE",@"fr"]) {
  NSDictionary *entry=@{@"Fingerprint_Config":@{@"Localization":@{@"Region":region}}};
  NSDictionary *expected=@{@"FR":@"🇫🇷",@"GB":@"🇬🇧",@"US":@"🇺🇸",@"DE":@"DE",@"fr":@"🇫🇷"};
  assert([SHDWBackupRegionIndicator(entry) isEqual:expected[region]]);
 }
 assert(!SHDWBackupRegionIndicator(@{}));
 for (id region in @[@"",@"native",@"F1",@"法国",NSNull.null,@1,@[]])
  assert(!SHDWBackupRegionIndicator(@{@"Fingerprint_Config":@{@"Localization":@{@"Region":region}}}));
 for (id malformed in @[NSNull.null,@1,@[],@{@"Localization":NSNull.null}])
  assert(!SHDWBackupRegionIndicator(@{@"Fingerprint_Config":malformed}));
 NSMutableDictionary *config=[@{@"System":@{@"Mode":@"profile",@"ProfileID":@"unknown-profile"},@"Localization":[SHDWFingerprintConfiguration localizationForRegion:@"FR"],@"Network":@{@"Transport":@"native",@"RadioTechnologies":@[@"5g",@"ignored",@"4g"]}} mutableCopy];
 NSMutableDictionary *snapshot=[@{@"title":@"Saved name",@"note":@"Saved note: a complete multiline description which must remain available in full without ellipsis, including every trailing character.\nSecond line: preserved end.",@"version":@"1.2.3",@"build":@"99",@"date":[NSDate dateWithTimeIntervalSince1970:0],@"idfv":@"ABCDEF12-3456-7890-ABCD-1234567890AB",@"digest":@"saved-digest",@"owner":@"rv",@"size":@1024,@"status":@"backed_up",@"Fingerprint_Config":config} mutableCopy];
 NSDictionary *before=[NSPropertyListSerialization propertyListWithData:[NSPropertyListSerialization dataWithPropertyList:snapshot format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL] options:0 format:NULL error:NULL];
 NSArray *fields=SHDWBackupDetailFields(snapshot, nil);
 NSArray *labels=@[@"Name",@"iOS",@"Region",@"Time zone",@"Language",@"Network",@"Receipt interception",@"Advertising tracking",@"TLS fingerprint",@"Backup size",@"Backup date",@"Note"];
 assert([[fields valueForKey:@"label"] isEqual:labels]);
 for (NSDictionary *field in fields) { assert(field.count==([field[@"label"] isEqual:@"Name"] ? 5 : [@[@"Note",@"Backup date"] containsObject:field[@"label"]] ? 3 : 2)); assert([field[@"value"] isKindOfClass:NSString.class]); }
 assert([value(fields,@"Name") isEqual:@"Saved name"]);
 assert([value(fields,@"Backup date") length]==19);
 assert([fields[0][@"owner"] isEqual:@"rv"]);
 assert(![fields[0][@"current"] boolValue]);
 assert([SHDWBackupDetailFields(snapshot, @"abcdef12-3456-7890-abcd-1234567890ab")[0][@"current"] boolValue]);
 assert(![SHDWBackupDetailFields(snapshot, @"invalid")[0][@"current"] boolValue]);
 assert([value(fields,@"Region") isEqual:@"FR"]);
 assert([value(fields,@"Language") isEqual:@"fr-FR"]);
 assert([value(fields,@"Time zone") isEqual:@"Europe/Paris"]);
 assert([value(fields,@"Network") isEqual:@"4G / 5G"]);
 assert([value(fields,@"Advertising tracking") isEqual:@"Disable tracking"]);
 assert([value(fields,@"Receipt interception") isEqual:@"Disabled"]);
 assert([value(fields,@"TLS fingerprint") isEqual:@"Disabled"]);
 assert([value(fields,@"iOS") isEqual:@"unknown-profile"]);
 assert([snapshot isEqual:before]);
 config[@"System"]=@{@"Mode":@"profile",@"ProfileID":@"iphone14-5_ios18.4_22E240"};
 assert([value(SHDWBackupDetailFields(snapshot, nil),@"iOS") isEqual:@"18.4"]);
 config[@"Localization"]=@{@"Region":@"native",@"Language":@"native",@"TimeZone":@"native"};
 config[@"System"]=@{@"Mode":@"native"}; config[@"Network"]=@{};
 fields=SHDWBackupDetailFields(snapshot, nil);
 for (NSString *label in @[@"Region",@"Language",@"Time zone",@"iOS"]) assert([value(fields,label) isEqual:@"Follow system"]);
 assert([value(fields,@"TLS fingerprint") isEqual:@"Enabled"]);
 [config removeObjectForKey:@"Localization"];
 fields=SHDWBackupDetailFields(snapshot, nil);
 assert([value(fields,@"Region") isEqual:@"Not set"]);
 [snapshot removeObjectForKey:@"Fingerprint_Config"];
 snapshot[@"unavailable"]=@YES; snapshot[@"error"]=@"broken archive";
 fields=SHDWBackupDetailFields(snapshot, nil);
 assert([value(fields,@"TLS fingerprint") isEqual:@"Not set"]);
 assert([value(fields,@"Advertising tracking") isEqual:@"Not set"]);
 assert([value(fields,@"Error") isEqual:@"broken archive"]);
 assert([fields.lastObject[@"label"] isEqual:@"Note"]);
 assert([fields.lastObject[@"fullWidth"] boolValue]);
 assert([fields.lastObject[@"value"] isEqual:@"Saved note: a complete multiline description which must remain available in full without ellipsis, including every trailing character.\nSecond line: preserved end."]);
 assert([fields[fields.count-4][@"label"] isEqual:@"Error"]);
 assert(!SHDWBackupStatusTitle(@"unknown"));
 assert([SHDWBackupStatusTitle(@"backed_up") isEqual:@"Backup saved"]);
 assert([SHDWBackupStatusTitle(@"reset_failed") isEqual:@"Clean application data · Failed"]);
 for (NSString *emptyNote in @[@"", @"  ", @"\n \t"]) {
  snapshot[@"note"]=emptyNote;
  assert(![[SHDWBackupDetailFields(snapshot,nil) valueForKey:@"label"] containsObject:@"Note"]);
 }
 [snapshot removeObjectForKey:@"note"];
 assert(![[SHDWBackupDetailFields(snapshot,nil) valueForKey:@"label"] containsObject:@"Note"]);
 for (id malformed in @[NSNull.null,@1,@[],@{@"Network":NSNull.null,@"System":NSNull.null,@"Localization":NSNull.null}]) {
 snapshot[@"Fingerprint_Config"]=malformed;
 (void)SHDWBackupDetailFields(snapshot, nil);
 }
 puts("backup details: exact flat fields, saved presets, native/missing/legacy transport, immutable input and dialog toggles passed");
} return 0; }

'''
# Execute the production toggle method; the doubles model arranged and attached views
# independently so hidden views cannot satisfy the single-content-card contract.
actions = (ROOT / "src/Shadow.app/Screens/Backup/BackupActionsViewController.m").read_text()
toggle = actions[actions.index("- (void)toggleDetails {"):actions.index("- (void)selectAction:")]
doubles = r'''
static NSString *SHDWText(NSString *key) { return SHDWLocalizedText(key); }
enum { UILayoutConstraintAxisVertical = 1, UILayoutConstraintAxisHorizontal = 2, UIStackViewAlignmentTop = 3, UIStackViewDistributionFillEqually = 4 };
typedef struct { double top, left, bottom, right; } UIEdgeInsets;
static UIEdgeInsets UIEdgeInsetsMake(double top, double left, double bottom, double right) { return (UIEdgeInsets){top,left,bottom,right}; }
@interface UIColor : NSObject
+ (instancetype)whiteColor;
@end
@implementation UIColor
+ (instancetype)whiteColor { return [self new]; }
@end
@interface Constraint : NSObject
@property BOOL active;
- (Constraint *)constraintEqualToConstant:(double)value;
@end
@implementation Constraint
- (Constraint *)constraintEqualToConstant:(double)value { assert(value==0); return self; }
@end
@interface UIStackView : NSObject
@property NSInteger axis;
@property NSInteger alignment;
@property NSInteger distribution;
@property BOOL layoutMarginsRelativeArrangement;
@property UIEdgeInsets layoutMargins;
@property(strong) UIColor *backgroundColor;
@property double cornerRadius;
@property(strong) NSDictionary *field;
- (UIStackView *)layer;
- (Constraint *)heightAnchor;
@property double spacing;
@property(copy) NSString *accessibilityIdentifier;
@property(weak) UIStackView *superview;
@property(strong) NSMutableArray *arrangedSubviews;
@property(strong) NSMutableArray *subviews;
- (void)addArrangedSubview:(UIStackView *)view;
- (void)removeArrangedSubview:(UIStackView *)view;
- (void)removeFromSuperview;
@end
@compatibility_alias UIView UIStackView;
@implementation UIStackView
- (instancetype)init { if ((self=[super init])) { _arrangedSubviews=[NSMutableArray new]; _subviews=[NSMutableArray new]; } return self; }
- (UIStackView *)layer { return self; }
- (Constraint *)heightAnchor { return [Constraint new]; }
- (void)addArrangedSubview:(UIStackView *)view { assert(![self.arrangedSubviews containsObject:view]); [self.arrangedSubviews addObject:view]; if (![self.subviews containsObject:view]) [self.subviews addObject:view]; view.superview=self; }
- (void)removeArrangedSubview:(UIStackView *)view { [self.arrangedSubviews removeObject:view]; }
- (void)removeFromSuperview { [self.superview.subviews removeObject:self]; self.superview=nil; }
@end
@interface Button : NSObject
@property BOOL selected;
@property(copy) NSString *accessibilityLabel;
@end
@implementation Button
@end
@interface Application : NSObject
@property(copy) NSString *bundleIdentifier;
@end
@implementation Application
@end
@interface ToggleFixture : NSObject
@property BOOL finishing;
@property(strong) Button *detailsButton;
@property(strong) UIStackView *contentStack;
@property(strong) UIStackView *actionsCard;
@property(strong) UIStackView *detailsContent;
@property(strong) NSDictionary *snapshot;
@property(strong) Application *application;
@property(copy) NSString *currentIDFV;
@property(copy) NSString *sheetTitle;
@property NSUInteger sectionBuilds;
@property NSUInteger layoutRequests;
- (UIStackView *)detailContent;
- (void)requestSheetLayout;
- (void)toggleDetails;
@end
@implementation ToggleFixture
- (UIStackView *)detailContent { assert(SHDWBackupDetailFields(self.snapshot, self.currentIDFV).count==11); self.sectionBuilds++; return [UIStackView new]; }
- (void)requestSheetLayout { self.layoutRequests++; }
''' + toggle + r'''
@end
static void verifyToggle(void) {
 ToggleFixture *fixture=[ToggleFixture new];
 fixture.contentStack=[UIStackView new]; fixture.actionsCard=[UIStackView new];
 UIStackView *header=[UIStackView new];
 [fixture.contentStack addArrangedSubview:header]; [fixture.contentStack addArrangedSubview:fixture.actionsCard];
 fixture.detailsButton=[Button new]; fixture.application=[Application new];
 fixture.application.bundleIdentifier=@"saved.bundle"; fixture.snapshot=@{};
 fixture.sheetTitle=@"Backup actions";
 UIStackView *firstDetails=nil;
 for (NSUInteger iteration=0;iteration<3;iteration++) {
  [fixture toggleDetails];
  BOOL details=iteration!=1;
  assert(fixture.detailsButton.selected==details);
  assert([fixture.detailsButton.accessibilityLabel isEqual:details?@"Show backup actions":@"Show backup details"]);
  assert([fixture.sheetTitle isEqual:details?@"Backup details":@"Backup actions"]);
  assert(fixture.contentStack.arrangedSubviews.count==2 && fixture.contentStack.subviews.count==2);
  assert(fixture.contentStack.arrangedSubviews[0]==header);
  assert(fixture.contentStack.arrangedSubviews[1]==(details?fixture.detailsContent:fixture.actionsCard));
  assert(fixture.sectionBuilds==1);
  if (!firstDetails) firstDetails=fixture.detailsContent;
  assert(firstDetails==fixture.detailsContent);
 }
 fixture.finishing=YES;
 [fixture toggleDetails];
 assert(fixture.detailsButton.selected && fixture.layoutRequests==3 && fixture.sectionBuilds==1);
 assert([fixture.sheetTitle isEqual:@"Backup details"]);
}
'''
detail_content = actions[actions.index("- (UIStackView *)detailContent {"):actions.index("- (void)updateDeleteLock {")]
doubles += r'''
@interface ContentFixture : NSObject
@property(strong) NSDictionary *snapshot;
@property(copy) NSString *currentIDFV;
- (UIStackView *)detailContent;
- (UIView *)detailField:(NSDictionary *)field;
@end
@implementation ContentFixture
- (UIView *)detailField:(NSDictionary *)field { UIView *view=[UIView new]; view.field=field; return view; }
''' + detail_content + r'''
@end
static void verifyDetailContent(void) {
 NSString *note=@"A complete long note spanning multiple lines; the final field must preserve every character.\nSecond line and trailing text without truncation.";
 for (NSNumber *includeError in @[@NO,@YES]) {
  ContentFixture *fixture=[ContentFixture new];
  NSMutableDictionary *snapshot=[@{@"title":@"Saved title", @"note":note} mutableCopy];
  if (includeError.boolValue) snapshot[@"error"]=@"saved error";
  fixture.snapshot=snapshot;
  NSArray *fields=SHDWBackupDetailFields(snapshot,nil);
  UIStackView *content=[fixture detailContent];
  assert(content.axis==UILayoutConstraintAxisVertical);
  assert(content.arrangedSubviews.count==8);
  assert(content.subviews.count==content.arrangedSubviews.count);
  NSMutableArray *rendered=[NSMutableArray new];
  NSUInteger placeholders=0, fullWidthFields=0;
  for (NSUInteger index=0;index<content.arrangedSubviews.count-1;index++) {
   UIStackView *row=content.arrangedSubviews[index];
   if (row.field) {
    assert([row.field[@"fullWidth"] boolValue]);
    assert(([@[@"Name",@"Backup date"] containsObject:row.field[@"label"]]));
    assert(row.superview==content); fullWidthFields++; [rendered addObject:row.field]; continue;
   }
   assert(row.axis==UILayoutConstraintAxisHorizontal);
   assert(row.distribution==UIStackViewDistributionFillEqually);
   assert(row.arrangedSubviews.count==2);
   for (UIView *fieldView in row.arrangedSubviews) {
    if (fieldView.field) [rendered addObject:fieldView.field];
    else { placeholders++; assert(index==5); }
   }
  }
  UIView *noteView=content.arrangedSubviews.lastObject;
  assert([noteView.field[@"fullWidth"] boolValue]);
  assert([noteView.field[@"label"] isEqual:@"Note"]);
  assert([noteView.field[@"value"] isEqual:note]);
  assert(noteView.superview==content);
  [rendered addObject:noteView.field];
  assert(fullWidthFields==2);
  assert([[content.arrangedSubviews[0] field] isEqual:fields[0]]);
  assert([[content.arrangedSubviews[content.arrangedSubviews.count-2] field] isEqual:fields[fields.count-2]]);
  assert([fields[fields.count-3][@"label"] isEqual:@"Backup size"]);
  assert([fields[fields.count-2][@"label"] isEqual:@"Backup date"]);
  assert([rendered isEqual:fields]);
  assert(placeholders==(includeError.boolValue?0:1));
 }
}
'''
code = code.replace("int main(void)", doubles + "\nint main(void)")
code = code.replace(" NSMutableDictionary *config=", " verifyToggle(); verifyDetailContent();\n NSMutableDictionary *config=")
with tempfile.TemporaryDirectory(prefix="shadow-backup-details-") as directory:
    path = Path(directory)
    (path / "test.m").write_text(code)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation", "-I"+str(ROOT/"src/Shadow.framework/Headers"), "-I"+str(ROOT/"src/Shadow.app/Services"), str(path/"test.m"), str(ROOT/"src/Shadow.app/Services/BackupPresentation.m"), str(ROOT/"src/Shadow.app/Services/RegionPresentation.m"), str(ROOT/"src/Shadow.framework/Fingerprint/Configuration.m"), "-o", str(path/"test")], check=True)
    subprocess.run([str(path/"test")], check=True)
