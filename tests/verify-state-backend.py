#!/usr/bin/env python3
"""Native state tests: Security/preferences, temp UID metadata and privilege-drop doubles."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <dlfcn.h>
#include <sys/stat.h>
#include <grp.h>
#include <xlocale.h>
static int FixtureSetGroups(int count,const gid_t *groups);
static int FixtureSetGID(gid_t group);
#define setgroups(count,groups) FixtureSetGroups(count,groups)
#define setgid(group) FixtureSetGID(group)
static int FixtureLstat(const char *path,struct stat *value);
#define lstat(path,value) FixtureLstat(path,value)
static OSStatus FixtureCopy(CFDictionaryRef query,CFTypeRef *result);
static OSStatus FixtureDelete(CFDictionaryRef query);
static OSStatus FixtureAdd(CFDictionaryRef attributes,CFTypeRef *result);
static OSStatus FixtureUpdate(CFDictionaryRef query,CFDictionaryRef attributes);
static void *FixtureSymbol(void *handle,const char *name);
static CFDictionaryRef FixturePreferencesCopy(CFArrayRef,CFStringRef,CFStringRef,CFStringRef,CFStringRef);
static void FixturePreferencesSet(CFStringRef,CFPropertyListRef,CFStringRef,CFStringRef,CFStringRef,CFStringRef);
static Boolean FixturePreferencesSync(CFStringRef,CFStringRef,CFStringRef,CFStringRef);
static void FixturePreferencesFlush(CFStringRef,CFStringRef);
#define SecItemCopyMatching FixtureCopy
#define SecItemDelete FixtureDelete
#define SecItemAdd FixtureAdd
#define SecItemUpdate FixtureUpdate
#define dlsym FixtureSymbol
static CFPropertyListRef FixtureExternalCopy(CFStringRef,CFStringRef,CFStringRef,CFStringRef);
static Boolean FixtureExternalSync(CFStringRef,CFStringRef,CFStringRef);
static CFDictionaryRef FixtureExternalMultiple(CFArrayRef,CFStringRef,CFStringRef,CFStringRef);
#define CFPreferencesCopyValue FixtureExternalCopy
#define CFPreferencesSynchronize FixtureExternalSync
#define CFPreferencesCopyMultiple FixtureExternalMultiple
static NSArray *FixtureExternalPaths(void);
#define SHDW_STATE_IDENTITY_PATHS() FixtureExternalPaths()
#define SHADOW_STATE_SUPPORT 1
#import "__CLEANER__"
#undef dlsym
#undef lstat
#undef setgroups
#undef setgid
static int FixtureSetGID(gid_t group){if(group!=501||getuid()!=501||geteuid()!=501)abort();return 0;}
static int FixtureSetGroups(int count,const gid_t *groups){if(count!=0||groups!=NULL||getuid()!=501||geteuid()!=501)abort();return 0;}
static NSDictionary *fixtureOwners;
static NSString *fixtureRoot;
static int FixtureLstat(const char *path,struct stat *value){int result=lstat(path,value);if(!result){NSString *name=[NSString stringWithUTF8String:path];NSNumber *owner=fixtureOwners[name];if(owner){if(![name hasPrefix:[fixtureRoot stringByAppendingString:@"/"]])abort();value->st_uid=(uid_t)owner.unsignedIntValue;}}return result;}

static NSMutableArray *database;
static NSUInteger deletes,adds,updates;
static BOOL wrongGroup,wrongClass,nullSuccess,invalidCopyType,emptySuccess;
static OSStatus forcedStatus;
static NSString *const Group=@"TEAM.local.fixture.app";
static NSString *const Other=@"OTHER.local.untouched";
static void Check(BOOL value,NSString *message){if(!value){fprintf(stderr,"FAIL: %s\n",message.UTF8String);exit(1);}}
static BOOL Reject(void (^block)(void)){@try{block();return NO;}@catch(NSException *exception){(void)exception;return YES;}}
static void Reset(void){deletes=adds=updates=0;wrongGroup=wrongClass=nullSuccess=invalidCopyType=emptySuccess=NO;forcedStatus=0;keychainParent=getppid();}
static NSDictionary *Record(id itemClass,NSString *group,NSString *account,NSString *service,NSString *data,BOOL sync){NSMutableDictionary *record=[@{(__bridge id)kSecClass:itemClass,(__bridge id)kSecAttrAccessGroup:group,(__bridge id)kSecAttrAccount:account,(__bridge id)kSecValueData:[data dataUsingEncoding:NSUTF8StringEncoding],(__bridge id)kSecAttrSynchronizable:@(sync),(__bridge id)kSecAttrAccessible:(__bridge id)kSecAttrAccessibleAfterFirstUnlock} mutableCopy];if([itemClass isEqual:(__bridge id)kSecClassGenericPassword])record[(__bridge id)kSecAttrService]=service;else{record[(__bridge id)kSecAttrServer]=service;record[(__bridge id)kSecAttrProtocol]=(__bridge id)kSecAttrProtocolHTTPS;record[(__bridge id)kSecAttrPort]=@443;}return record;}
static BOOL Matches(NSDictionary *record,NSDictionary *query){for(NSString *key in query){if([key isEqual:(__bridge id)kSecUseAuthenticationContext]||[key isEqual:(__bridge id)kSecReturnAttributes]||[key isEqual:(__bridge id)kSecReturnData]||[key isEqual:(__bridge id)kSecMatchLimit])continue;id wanted=query[key],actual=record[key];if([key isEqual:(__bridge id)kSecAttrSynchronizable]&&[wanted isEqual:(__bridge id)kSecAttrSynchronizableAny])continue;if(!actual)actual=[key isEqual:(__bridge id)kSecAttrPort]?@0:@"";if(![wanted isEqual:actual])return NO;}return YES;}
static OSStatus FixtureCopy(CFDictionaryRef raw,CFTypeRef *result){NSDictionary *query=(__bridge NSDictionary *)raw;Check(query[(__bridge id)kSecAttrAccessGroup]!=nil,@"credential query lost exact group");if(result)*result=NULL;if(forcedStatus)return forcedStatus;if(nullSuccess)return errSecSuccess;if(invalidCopyType){if(result)*result=CFBridgingRetain(@"wrong type");return errSecSuccess;}NSMutableArray *found=[NSMutableArray new];for(NSDictionary *record in database)if(Matches(record,query)){NSMutableDictionary *item=[record mutableCopy];if(wrongGroup)item[(__bridge id)kSecAttrAccessGroup]=Other;if(wrongClass)item[(__bridge id)kSecClass]=(__bridge id)kSecClassCertificate;if(item[@"ArchivedACL"]){item[(__bridge id)kSecAttrAccessControl]=item[@"ArchivedACL"];[item removeObjectForKey:@"ArchivedACL"];}[found addObject:item];}if(!found.count&&!emptySuccess)return errSecItemNotFound;if(result)*result=CFBridgingRetain(found);return errSecSuccess;}
static OSStatus FixtureDelete(CFDictionaryRef raw){deletes++;NSDictionary *query=(__bridge NSDictionary *)raw;Check(query[(__bridge id)kSecAttrAccessGroup]!=nil,@"delete lost exact group");NSMutableArray *remaining=[NSMutableArray new];BOOL found=NO;for(NSDictionary *record in database){if(Matches(record,query))found=YES;else[remaining addObject:record];}database=remaining;return found?errSecSuccess:errSecItemNotFound;}
static OSStatus FixtureAdd(CFDictionaryRef raw,CFTypeRef *result){(void)result;adds++;NSMutableDictionary *record=[(__bridge NSDictionary *)raw mutableCopy];if(record[(__bridge id)kSecAttrAccessControl]){record[@"ArchivedACL"]=record[(__bridge id)kSecAttrAccessControl];[record removeObjectForKey:(__bridge id)kSecAttrAccessControl];}for(NSDictionary *old in database)if([StateRecordIdentity(old)isEqual:StateRecordIdentity(record)])return errSecDuplicateItem;[database addObject:record];return errSecSuccess;}
static OSStatus FixtureUpdate(CFDictionaryRef raw,CFDictionaryRef changes){updates++;NSDictionary *query=(__bridge NSDictionary *)raw;for(NSUInteger i=0;i<database.count;i++)if(Matches(database[i],query)){NSMutableDictionary *value=[database[i] mutableCopy];[value addEntriesFromDictionary:(__bridge NSDictionary *)changes];database[i]=value;return errSecSuccess;}return errSecItemNotFound;}
static CFDataRef FixtureCopyACL(SecAccessControlRef value){return value?CFRetain((CFDataRef)value):NULL;}
static SecAccessControlRef FixtureDecodeACL(CFAllocatorRef allocator,CFDataRef value,CFErrorRef *error){(void)allocator;(void)error;NSData *data=(__bridge NSData *)value;return [data isEqual:[@"valid-acl" dataUsingEncoding:NSUTF8StringEncoding]]?(SecAccessControlRef)CFRetain(value):NULL;}
// Host credential fixtures inspect only their own process; process lifecycle is
// covered separately by verify-process-stop.py and the iOS device run.
static int FixtureProcessList(void *buffer,int size){if(!buffer)return 1;if(size<(int)sizeof(pid_t))abort();*(pid_t *)buffer=getpid();return 1;}
static void *FixtureSymbol(void *handle,const char *name){if(!strcmp(name,"proc_listallpids"))return (void *)FixtureProcessList;if(!strcmp(name,"_CFPreferencesCopyMultipleWithContainer"))return (void *)FixturePreferencesCopy;if(!strcmp(name,"_CFPreferencesSetValueWithContainer"))return (void *)FixturePreferencesSet;if(!strcmp(name,"_CFPreferencesSynchronizeWithContainer"))return (void *)FixturePreferencesSync;if(!strcmp(name,"_CFPreferencesFlushCachesForIdentifier"))return (void *)FixturePreferencesFlush;if(!strcmp(name,"SecAccessControlCopyData"))return (void *)FixtureCopyACL;if(!strcmp(name,"SecAccessControlCreateFromData"))return (void *)FixtureDecodeACL;return dlsym(handle,name);}

static NSMutableDictionary *nativePreferences;
static NSUInteger nativePreferenceWrites;
static BOOL nativePreferenceSyncFailure, nativePreferenceNullEmpty;
static NSArray *PreferenceKey(CFStringRef domain,CFStringRef user,CFStringRef host,CFStringRef container){Check(CFEqual(user,CFSTR("mobile")),@"preferences did not use mobile domain");Check(container!=NULL,@"preference scope lost explicit container");Check(!PreferenceDomainAlias((__bridge NSString *)domain),@"reserved domain reached native preference API");return @[(__bridge NSString *)container,(__bridge NSString *)domain,CFEqual(host,kCFPreferencesCurrentHost)?@"current":@"any"];}
static CFDictionaryRef FixturePreferencesCopy(CFArrayRef keys,CFStringRef domain,CFStringRef user,CFStringRef host,CFStringRef container){Check(keys==NULL,@"partial preference capture");NSDictionary *values=nativePreferences[PreferenceKey(domain,user,host,container)];if(!values.count&&nativePreferenceNullEmpty)return NULL;return CFBridgingRetain(values?:@{});}
static void FixturePreferencesSet(CFStringRef key,CFPropertyListRef value,CFStringRef domain,CFStringRef user,CFStringRef host,CFStringRef container){nativePreferenceWrites++;NSArray *identity=PreferenceKey(domain,user,host,container);NSMutableDictionary *values=[nativePreferences[identity]mutableCopy]?:[NSMutableDictionary new];if(value)values[(__bridge NSString *)key]=(__bridge id)value;else[values removeObjectForKey:(__bridge NSString *)key];nativePreferences[identity]=values;}
static Boolean FixturePreferencesSync(CFStringRef domain,CFStringRef user,CFStringRef host,CFStringRef container){PreferenceKey(domain,user,host,container);return !nativePreferenceSyncFailure;}
static void FixturePreferencesFlush(CFStringRef domain,CFStringRef user){Check(domain&&CFEqual(user,CFSTR("mobile"))&&!PreferenceDomainAlias((__bridge NSString *)domain),@"invalid preference cache scope");}
static void NativePreferenceTests(NSString *root){
    NSString *identifier=@"local.fixture.app",*extension=@"local.fixture.app.extension",*path=[root stringByAppendingPathComponent:@"preference-container"];
    Check([NSFileManager.defaultManager createDirectoryAtPath:[path stringByAppendingPathComponent:@"Library/Preferences"] withIntermediateDirectories:YES attributes:nil error:NULL],@"create preference container");
    NSString *custom=[path stringByAppendingPathComponent:@"Library/Preferences/custom.domain.plist"];
    Check([@{} writeToFile:custom atomically:YES],@"create custom preference domain");
    NSArray *names=@[@"My Settings",@"偏好设置",@"kCFPreferencesCustom",@"Back\\Slash"];
    for(NSString *name in [names arrayByAddingObjectsFromArray:@[@"NSGlobalDomain",@".GlobalPreferences",@"kCFPreferencesAnyApplication",@"kCFPreferencesCurrentApplication"]]) Check([@{@"physical":name} writeToFile:[path stringByAppendingPathComponent:[@"Library/Preferences/" stringByAppendingFormat:@"%@.plist",name]] atomically:YES],@"create named preference fixture");
    NSString *byHost=@"Library/Preferences/ByHost/主机 设置.11111111-1111-4111-8111-111111111111.plist";
    Check([NSFileManager.defaultManager createDirectoryAtPath:[[path stringByAppendingPathComponent:byHost]stringByDeletingLastPathComponent] withIntermediateDirectories:YES attributes:nil error:NULL]&&[@{} writeToFile:[path stringByAppendingPathComponent:byHost] atomically:YES],@"create Unicode ByHost domain");
    NSDictionary *target=@{@"bundleID":identifier,@"identifiers":@[identifier,extension],@"containers":@[@{@"identifier":identifier,@"path":path}]};
    NSArray *globalAny=@[@"kCFPreferencesNoContainer",identifier,@"any"],*globalHost=@[@"kCFPreferencesNoContainer",identifier,@"current"],*contained=@[path,@"custom.domain",@"any"],*other=@[@"kCFPreferencesNoContainer",@"other.app",@"any"];
    nativePreferences=[@{globalAny:@{@"binary":[NSData dataWithBytes:"\0\xff" length:2],@"date":[NSDate dateWithTimeIntervalSince1970:100],@"nested":@[@{@"enabled":@YES}]},globalHost:@{@"host":@42},contained:@{@"unicode":@"中文"},other:@{@"preserve":@YES}} mutableCopy]; nativePreferenceWrites=0;
    for(NSString *name in names)nativePreferences[@[path,name,@"any"]]=@{@"saved":name};
    nativePreferences[@[path,@"主机 设置",@"current"]]=@{@"host":@YES};
    NSArray *queries=PreferenceQueries(target);
    for(NSString *name in [names arrayByAddingObject:@"主机 设置"])Check([queries containsObject:@{@"domain":name,@"container":path}],@"production discovery omitted a valid domain basename");
    NSDictionary *saved=StateCapturePreferences(target);Check([saved[@"records"]count]==10&&nativePreferenceWrites==0,@"native capture omitted exact global/host or container domain");
    nativePreferenceNullEmpty=YES;Check([StateCapturePreferences(target)isEqual:saved],@"NULL empty native domain not supported");nativePreferenceNullEmpty=NO;
    StateRestorePreferences(saved,target);Check(nativePreferenceWrites==0,@"equal preferences were rewritten, changing original plist timestamps");
    nativePreferences[globalAny]=@{@"new":@"delete"};nativePreferences[globalHost]=@{};nativePreferences[contained]=@{@"stale":@YES};
    for(NSString *name in names)nativePreferences[@[path,name,@"any"]]=@{@"stale":@YES};
    nativePreferences[@[path,@"主机 设置",@"current"]]=@{};
    StateRestorePreferences(saved,target);Check([StateCapturePreferences(target)isEqual:saved]&&[nativePreferences[other]isEqual:@{@"preserve":@YES}],@"native preferences failed roundtrip or changed another application");
    NSMutableDictionary *forged=[saved mutableCopy];NSMutableArray *records=[saved[@"records"]mutableCopy];NSMutableDictionary *record=[records.firstObject mutableCopy];record[@"domain"]=@"other.app";records[0]=record;forged[@"records"]=records;NSUInteger before=nativePreferenceWrites;Check(Reject(^{StateRestorePreferences(forged,target);})&&nativePreferenceWrites==before,@"arbitrary global preference domain accepted");
    record=[records[0]mutableCopy];record[@"container"]=@"/private/var/mobile";records[0]=record;Check(Reject(^{StateRestorePreferences(forged,target);})&&nativePreferenceWrites==before,@"arbitrary archived container path accepted");
    records=[saved[@"records"]mutableCopy];[records addObject:records.firstObject];forged[@"records"]=records;Check(Reject(^{StateValidatePreferences(forged,target);}),@"duplicate preference domain accepted");
    forged=[saved mutableCopy];forged[@"records"]=@[];Check(Reject(^{StateValidatePreferences(forged,target);}),@"missing main application preference domains accepted");
    unichar nulCharacters[]={ 'a',0,'b' };NSString *nul=[NSString stringWithCharacters:nulCharacters length:3];
    unichar invalidCharacter=0xd800;NSString *invalidUTF8=[NSString stringWithCharacters:&invalidCharacter length:1];
    NSArray *invalidNames=@[@"",@".",@"..",@"../escape",@"a/b",nul,invalidUTF8,@"NSGlobalDomain",@".GlobalPreferences",@"kCFPreferencesAnyApplication",@"kCFPreferencesCurrentApplication"];
    for(NSString *name in invalidNames){
        NSMutableDictionary *invalid=[saved mutableCopy];NSMutableArray *items=[saved[@"records"]mutableCopy];[items addObject:@{@"container":@"data",@"domain":name,@"host":@"any",@"values":@{@"bad":@YES}}];invalid[@"records"]=items;NSUInteger writes=nativePreferenceWrites;
        Check(Reject(^{StateRestorePreferences(invalid,target);})&&nativePreferenceWrites==writes,@"unsafe or reserved archived container domain reached import");
    }
    for(NSString *name in @[@"My Settings",@"偏好设置",@"NSGlobalDomain",@".GlobalPreferences",@"kCFPreferencesAnyApplication"]){
        NSMutableDictionary *invalid=[saved mutableCopy];NSMutableArray *items=[saved[@"records"]mutableCopy];[items addObject:@{@"container":@"",@"domain":name,@"host":@"any",@"values":@{@"bad":@YES}}];invalid[@"records"]=items;NSUInteger writes=nativePreferenceWrites;
        Check(Reject(^{StateRestorePreferences(invalid,target);})&&nativePreferenceWrites==writes,@"unauthorized global domain reached import");
    }
    Check(PreferenceDomainName([@"x" stringByPaddingToLength:300 withString:@"x" startingAtIndex:0]),@"domain validator imposed arbitrary identifier length limit");
    for(NSString *name in @[@"NSGlobalDomain",@".GlobalPreferences",@"kCFPreferencesAnyApplication",@"kCFPreferencesCurrentApplication"])Check([[NSDictionary dictionaryWithContentsOfFile:[path stringByAppendingPathComponent:[@"Library/Preferences/" stringByAppendingFormat:@"%@.plist",name]]][@"physical"]isEqual:name],@"logical preference handling changed physical reserved-name file");
    nativePreferenceSyncFailure=YES;Check(Reject(^{StateCapturePreferences(target);}),@"failed cfprefsd synchronization ignored");nativePreferenceSyncFailure=NO;
    // A new current-only domain is cleared even when it was absent from the snapshot.
    NSString *extra=[path stringByAppendingPathComponent:@"Library/Preferences/新增 Settings.plist"];Check([@{} writeToFile:extra atomically:YES],@"create extra preference domain");nativePreferences[@[path,@"新增 Settings",@"any"]]=@{@"remove":@YES};StateRestorePreferences(saved,target);Check([StateCapturePreferences(target)isEqual:saved],@"newly created preference domain was not cleared");
    // An app update can add an extension absent from the original snapshot.
    NSString *addedExtension=@"local.fixture.app.added-extension",*extensionPath=[root stringByAppendingPathComponent:@"added-extension-container"];
    NSString *extensionPreferences=[extensionPath stringByAppendingPathComponent:@"Library/Preferences"];
    Check([NSFileManager.defaultManager createDirectoryAtPath:extensionPreferences withIntermediateDirectories:YES attributes:nil error:NULL]&&[@{} writeToFile:[extensionPreferences stringByAppendingPathComponent:@"extension-sdk.plist"] atomically:YES],@"create added extension domain");
    NSDictionary *upgradedTarget=@{@"bundleID":identifier,@"identifiers":@[identifier,extension,addedExtension],@"containers":[target[@"containers"] arrayByAddingObject:@{@"identifier":addedExtension,@"path":extensionPath}]};
    NSArray *addedGlobalAny=@[@"kCFPreferencesNoContainer",addedExtension,@"any"],*addedGlobalHost=@[@"kCFPreferencesNoContainer",addedExtension,@"current"],*addedContainer=@[extensionPath,addedExtension,@"any"],*addedSDK=@[extensionPath,@"extension-sdk",@"current"];
    for(NSArray *scope in @[addedGlobalAny,addedGlobalHost,addedContainer,addedSDK])nativePreferences[scope]=@{@"stale":@YES,@"future-field":@{@"opaque":@[@1,@2]}};
    NSDictionary *unrelatedBefore=[nativePreferences[other]copy];
    StateValidatePreferences(saved,upgradedTarget);
    StateRestorePreferences(saved,upgradedTarget);
    for(NSArray *scope in @[addedGlobalAny,addedGlobalHost,addedContainer,addedSDK])Check([nativePreferences[scope]count]==0,@"new extension preferences survived old snapshot restoration");
    Check([StateCapturePreferences(target)isEqual:saved]&&[nativePreferences[other]isEqual:unrelatedBefore],@"upgrade restoration changed archived or unrelated preferences");
    NSDictionary *upgradedCapture=StateCapturePreferences(upgradedTarget);
    for(NSDictionary *item in upgradedCapture[@"records"])if([item[@"domain"]isEqual:addedExtension])Check([item[@"values"]count]==0,@"new extension capture is not empty");
    NSUInteger upgradeWrites=nativePreferenceWrites;StateRestorePreferences(saved,upgradedTarget);Check(nativePreferenceWrites==upgradeWrites,@"empty newly added extension was rewritten on retry");
    NSString *archivePath=[root stringByAppendingPathComponent:@"named-preferences.tar.zst"],*restoredPath=[root stringByAppendingPathComponent:@"restored-preferences"];
    locale_t cLocale=newlocale(LC_CTYPE_MASK,"C",NULL);Check(cLocale!=NULL,@"create C locale regression fixture");locale_t callerLocale=uselocale(cLocale);Check(callerLocale!=NULL,@"select C locale regression fixture");
    NSError *archiveError=nil;NSDictionary *archiveInfo=[SHDWStateArchive captureRoots:@{@"containers/data":path} payloads:@{} toPath:archivePath progress:nil error:&archiveError];
    Check(archiveInfo!=nil,@"physical preference archive capture failed");
    Check([NSFileManager.defaultManager createDirectoryAtPath:restoredPath withIntermediateDirectories:NO attributes:nil error:NULL]&&[SHDWStateArchive restorePath:archivePath info:archiveInfo roots:@{@"containers/data":restoredPath} progress:nil error:&archiveError],@"physical preference archive restore failed");
    Check([SHDWStateArchive verifyRoots:@{@"containers/data":restoredPath} info:archiveInfo progress:nil error:&archiveError],@"physical named/Unicode/reserved preference files failed archive verification");
    Check(uselocale(NULL)==cLocale,@"archive success changed caller thread locale");
    Check([SHDWStateArchive captureRoots:@{@"containers/data":path} payloads:@{} toPath:archivePath progress:nil error:&archiveError]==nil&&uselocale(NULL)==cLocale,@"archive failure changed caller thread locale");
    uselocale(callerLocale);freelocale(cLocale);
    puts("native preferences: UTF-8/spaced/container/ByHost roundtrip; reserved aliases remain physical-only; unsafe scopes rejected before writes; exact global scope, added-extension upgrade and stale key removal passed");
}

@interface FixtureDefaults:NSObject
@property(nonatomic,strong) NSMutableDictionary *values;
@property(nonatomic) NSUInteger writes;
- (BOOL)synchronize;
- (NSDictionary *)dictionaryForKey:(NSString *)key;
- (void)setObject:(id)object forKey:(NSString *)key;
@end
@implementation FixtureDefaults
- (BOOL)synchronize{return YES;}
- (NSDictionary *)dictionaryForKey:(NSString *)key{return self.values[key];}
- (void)setObject:(id)object forKey:(NSString *)key{self.writes++;self.values[key]=object;}
@end
static FixtureDefaults *preferences;
static BOOL fingerprintRefreshFails;
static NSUInteger settingsInitializations;
@implementation ShadowSettings
+ (instancetype)sharedInstance{settingsInitializations++;static id value;if(!value)value=[self new];return value;}
- (NSUserDefaults *)userDefaults{return (NSUserDefaults *)preferences;}
- (BOOL)isValidFingerprintData:(NSDictionary *)data{return [data isKindOfClass:NSDictionary.class]&&[data[@"VendorIdentifier"] isKindOfClass:NSString.class];}
+ (BOOL)isValidFingerprintData:(NSDictionary *)data{return [data isKindOfClass:NSDictionary.class]&&[data[@"VendorIdentifier"] isKindOfClass:NSString.class];}
@end
@implementation SHDWFingerprintConfiguration
+ (NSDictionary *)configurationByValidating:(id)value error:(NSError **)error{(void)error;return [value isKindOfClass:NSDictionary.class]&&[value[@"valid"] boolValue]?value:nil;}
@end
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore{static id value;if(!value)value=[self new];return value;}
+ (NSString *)deviceFingerprintForData:(NSDictionary *)data{return data[@"VendorIdentifier"];}
- (BOOL)lockedForApplication:(NSString *)identifier{return [preferences.values[identifier][@"Fingerprint_Locked"]boolValue];}
- (BOOL)setLocked:(BOOL)value forApplication:(NSString *)identifier error:(NSError **)error{(void)error;NSMutableDictionary *app=[preferences.values[identifier] mutableCopy];app[@"Fingerprint_Locked"]=@(value);[preferences setObject:app forKey:identifier];return YES;}
- (BOOL)refreshApplication:(NSString *)identifier error:(NSError **)error{(void)error;if(fingerprintRefreshFails)return NO;NSMutableDictionary *app=[preferences.values[identifier] mutableCopy];app[@"Fingerprint_Data"]=@{@"VendorIdentifier":@"44444444-4444-4444-8444-444444444444"};app[@"Fingerprint_Locked"]=@YES;[preferences setObject:app forKey:identifier];return YES;}
- (NSDictionary *)configurationForApplication:(NSString *)identifier{(void)identifier;return @{@"valid":@YES,@"region":@"fallback"};}
@end

static NSArray *externalPaths;
static NSArray *FixtureExternalPaths(void){return externalPaths?:@[];}
static id externalSettings;
static NSDictionary *externalRoot;
static BOOL externalSyncFailure;
static NSUInteger externalReads;
static void ExternalScope(CFStringRef domain,CFStringRef user,CFStringRef host){Check(CFEqual(domain,CFSTR(SHADOW_PREFS_PLIST))&&CFEqual(user,CFSTR("mobile"))&&CFEqual(host,kCFPreferencesAnyHost),@"external identity must read Shadow absolute suite in mobile context");}
static Boolean FixtureExternalSync(CFStringRef domain,CFStringRef user,CFStringRef host){ExternalScope(domain,user,host);return !externalSyncFailure;}
static CFPropertyListRef FixtureExternalCopy(CFStringRef key,CFStringRef domain,CFStringRef user,CFStringRef host){ExternalScope(domain,user,host);Check(CFEqual(key,CFSTR("local.fixture.app")),@"unexpected identity bundle");externalReads++;return externalSettings?CFBridgingRetain(externalSettings):NULL;}
static CFDictionaryRef FixtureExternalMultiple(CFArrayRef keys,CFStringRef domain,CFStringRef user,CFStringRef host){ExternalScope(domain,user,host);Check([(__bridge NSArray *)keys count]==3,@"active query did not scope preference keys");return externalRoot?CFBridgingRetain(externalRoot):NULL;}
@interface SavedOnlyFixture : NSObject
@property(nonatomic)NSUInteger deletes,verifications;
@end
@implementation SavedOnlyFixture
- (NSDictionary *)claimBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error{(void)bundle;(void)error;return @{@"idfv":idfv,@"owner":@"rv"};}
- (NSDictionary *)releaseBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error{(void)bundle;(void)error;return @{@"idfv":idfv,@"owner":@"phone"};}
- (NSDictionary *)ownershipBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error{(void)bundle;(void)error;return @{@"idfv":idfv,@"owner":@"phone"};}
- (BOOL)deleteBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error{(void)error;Check([bundle isEqual:@"local.fixture.app"]&&idfv.length==36,@"delete mapping changed identity");self.deletes++;return YES;}
- (BOOL)recheckBundle:(NSString *)bundle idfv:(NSString *)idfv error:(NSError **)error{(void)error;Check([bundle isEqual:@"local.fixture.app"]&&idfv.length==36,@"verify mapping changed identity");self.verifications++;return YES;}
@end
static void ExternalTests(NSString *base){
    Check([StateExternalIdentityPaths(@"/var/jb",@SHADOW_PREFS_PLIST)isEqual:@[@"/var/jb/var/mobile/Library/Preferences/me.jjolano.shadow.plist",@SHADOW_PREFS_PLIST]],@"production persisted identity builder lost bootstrap prefix");
    Check([StateExternalIdentityPaths(@"",@SHADOW_PREFS_PLIST)isEqual:@[@SHADOW_PREFS_PLIST]],@"rootful identity builder duplicated raw path");
    Check([StateExternalIdentityPaths(@"/",@SHADOW_PREFS_PLIST)isEqual:@[@SHADOW_PREFS_PLIST]],@"root slash identity builder duplicated raw path");

    NSString *bundle=@"local.fixture.app",*uuid=@"11111111-2222-3333-4444-555555555555";externalSettings=nil;externalReads=0;Check([StateReadExternalIdentity(bundle)isEqual:@""],@"missing identity is explicit empty wire value");
    externalSettings=@{@"Fingerprint_Data":@{@"VendorIdentifier":uuid}};Check([StateReadExternalIdentity(bundle)isEqual:uuid]&&externalReads==2,@"token-independent identity query");
    for(id malformed in @[@"bad",@{@"Fingerprint_Data":@"bad"},@{@"Fingerprint_Data":@{@"VendorIdentifier":@"bad"}},@{@"Fingerprint_Data":@{@"VendorIdentifier":@1}}]){externalSettings=malformed;Check(Reject(^{StateReadExternalIdentity(bundle);}),@"malformed identity accepted as absent");}
    externalSettings=nil;NSString *rooted=[base stringByAppendingPathComponent:@"rooted-identity.plist"],*stale=[base stringByAppendingPathComponent:@"stale-identity.plist"];
    NSDictionary *persisted=@{bundle:@{@"Fingerprint_Data":@{@"VendorIdentifier":uuid}}};Check([persisted writeToFile:rooted atomically:YES]&&[[NSData data]writeToFile:stale atomically:YES],@"persisted identity fixture");
    externalPaths=@[rooted,stale];NSData *rootedBefore=[NSData dataWithContentsOfFile:rooted],*staleBefore=[NSData dataWithContentsOfFile:stale];NSDictionary *rootedAttributes=[NSFileManager.defaultManager attributesOfItemAtPath:rooted error:NULL];
    Check([StateReadExternalIdentity(bundle)isEqual:uuid],@"CF-missing identity did not read persisted Shadow selection");
    Check([[NSData dataWithContentsOfFile:rooted]isEqual:rootedBefore]&&[[NSData dataWithContentsOfFile:stale]isEqual:staleBefore]&&[[NSFileManager.defaultManager attributesOfItemAtPath:rooted error:NULL][NSFileModificationDate]isEqual:rootedAttributes[NSFileModificationDate]],@"persisted identity query wrote preferences");
    Check([@{}writeToFile:rooted atomically:YES],@"absent selected-app fixture");Check([StateReadExternalIdentity(bundle)isEqual:@""],@"absent persisted app rejected empty stale placeholder");
    Check([[@"invalid secondary plist" dataUsingEncoding:NSUTF8StringEncoding]writeToFile:stale atomically:NO],@"malformed secondary fixture");Check(Reject(^{StateReadExternalIdentity(bundle);}),@"nonempty malformed secondary source ignored");
    Check([[NSData data]writeToFile:stale atomically:NO],@"restore empty secondary fixture");externalPaths=@[stale];Check(Reject(^{StateReadExternalIdentity(bundle);}),@"empty sole source accepted as absent");externalPaths=@[rooted,stale];
    Check([@{bundle:@{@"Fingerprint_Data":@{@"VendorIdentifier":@"invalid"}}}writeToFile:rooted atomically:YES],@"malformed persisted fixture");Check(Reject(^{StateReadExternalIdentity(bundle);}),@"malformed persisted identity became missing");
    externalSettings=@{@"Fingerprint_Data":@{@"VendorIdentifier":uuid}};Check([StateReadExternalIdentity(bundle)isEqual:uuid],@"valid preference cache lost precedence over persisted data");
    externalSettings=nil;Check([[@"invalid plist" dataUsingEncoding:NSUTF8StringEncoding]writeToFile:rooted atomically:NO],@"malformed persisted plist fixture");Check(Reject(^{StateReadExternalIdentity(bundle);}),@"malformed persisted plist became missing");
    externalPaths=@[];
    externalSyncFailure=YES;Check(Reject(^{StateReadExternalIdentity(bundle);}),@"failed preference sync reported absent identity");externalSyncFailure=NO;
    NSDictionary *capabilities=StateExternalCommand(bundle,@"capabilities",@{});Check([capabilities[@"ok"]boolValue],@"capabilities needs installed app or storage");
    NSData *capData=[[NSData alloc]initWithBase64EncodedString:capabilities[@"result"] options:0];NSDictionary *caps=[NSPropertyListSerialization propertyListWithData:capData options:NSPropertyListImmutable format:NULL error:NULL];for(NSString *operation in @[@"backup",@"restore",@"externalDelete",@"externalVerify",@"externalClaim",@"externalRelease",@"externalOwnership"])Check([caps[@"operations"]containsObject:operation],@"missing public operation capability");
    for(NSString *code in @[@"busy",@"invalid_request",@"restore_pending",@"active_environment",@"ownership_conflict",@"snapshot_unavailable",@"invalid_archive",@"permission_denied",@"operation_failed",@"outcome_unknown"]){NSError *source=[NSError errorWithDomain:@"fixture.source" code:41 userInfo:@{NSLocalizedDescriptionKey:@"arbitrary localized message",@"errorCode":code,NSUnderlyingErrorKey:[NSError errorWithDomain:NSPOSIXErrorDomain code:13 userInfo:nil]}];NSDictionary *terminal=StateErrorTerminal(source);Check([terminal[@"errorCode"]isEqual:code]&&[terminal[@"sourceDomain"]isEqual:@"fixture.source"]&&[terminal[@"sourceCode"]integerValue]==41&&[terminal[@"posixCode"]integerValue]==13,@"typed terminal classification changed");}
    Check(StateExternalAction(@"externalDelete")&&StateExternalAction(@"externalVerify"),@"store-only external operations unavailable");
Check(Reject(^{StateExternalCommand(bundle,@"capabilities",@{@"unexpected":@1});}),@"unknown external key accepted");
    SavedOnlyFixture *saved=[SavedOnlyFixture new];NSError *savedError=nil;
    Check([StateSavedAction((SHDWAppStateStore *)saved,bundle,@"externalDelete",@{@"idfv":uuid},&savedError)[@"deleted"]boolValue]&&[StateSavedAction((SHDWAppStateStore *)saved,bundle,@"externalVerify",@{@"idfv":uuid},&savedError)[@"verified"]boolValue]&&saved.deletes==1&&saved.verifications==1,@"saved operations require live device backend");
    NSDictionary *deleted=StateSavedAction((SHDWAppStateStore *)saved,bundle,@"externalDelete",@{@"idfv":uuid.lowercaseString},&savedError);
    Check([deleted[@"deleted"]isEqual:@YES]&&[deleted[@"idfv"]isEqual:uuid],@"delete terminal omitted canonical snapshot identity");
    Check([StateSavedAction((SHDWAppStateStore *)saved,bundle,@"externalClaim",@{@"idfv":uuid},&savedError)[@"owner"]isEqual:@"rv"]&&[StateSavedAction((SHDWAppStateStore *)saved,bundle,@"externalRelease",@{@"idfv":uuid},&savedError)[@"owner"]isEqual:@"phone"]&&[StateSavedAction((SHDWAppStateStore *)saved,bundle,@"externalOwnership",@{@"idfv":uuid},&savedError)[@"owner"]isEqual:@"phone"],@"ownership helper action mapping failed");
    Check(Reject(^{StateExternalCommand(bundle,@"exportState",@{@"idfv":uuid,@"part":@"manifest",@"requester":@"invalid"});}),@"invalid requester reached storage");
    stateInitiatingParent=getppid();NSMutableArray *frames=[NSMutableArray new];SHDWStateProgress progress=StateProgressHandler(^(NSDictionary *frame){[frames addObject:frame];});
    progress(@{@"phase":@"verify",@"stage":@"data",@"bytes":@1,@"secret":@"hidden"});progress(@{@"phase":@"verify",@"stage":@"data",@"bytes":@2});progress(@{@"phase":@"verify",@"stage":@"state",@"entries":@3});
    Check(frames.count==2&&[frames[0][@"event"]isEqual:@"progress"]&&[frames[0][@"progress"][@"bytes"]isEqual:@1]&&frames[0][@"progress"][@"secret"]==nil&&[frames[1][@"progress"][@"stage"]isEqual:@"state"],@"shared verify progress framing/throttling/filtering changed");
    puts("external helper: same mobile suite, token-independent identity, missing/malformed distinction and capabilities passed");
}
static void ActiveFingerprintTests(NSString *base){
    NSUInteger initializations=settingsInitializations;
    NSString *bundle=@"local.fixture.app",*uuid=@"11111111-2222-3333-4444-555555555555",*path=[base stringByAppendingPathComponent:@"active-fingerprint.plist"];
    externalPaths=@[path];externalSyncFailure=NO;externalRoot=@{};
    NSDictionary *empty=StateActiveFingerprint(bundle);Check(![empty[@"available"]boolValue]&&![empty[@"enabled"]boolValue]&&[empty[@"current_idfv"]isEqual:@""],@"absent profile generated an identity");
    NSDictionary *data=@{@"VendorIdentifier":uuid,@"AdvertisingIdentifier":@"AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",@"nested":@{@"date":[NSDate dateWithTimeIntervalSince1970:123],@"bytes":[NSData dataWithBytes:"\0\xff" length:2]}};
    NSMutableDictionary *app=[@{@"Fingerprint_Data":data,@"Fingerprint_Config":@{@"valid":@YES},@"Fingerprint_Locked":@YES,@"App_Enabled":@YES,@"privateField":@"must not escape"}mutableCopy];
    NSMutableDictionary *root=[@{bundle:app,@"SingleToggleMigrated":@YES,@"other.app":@{@"secret":@"must not escape"}}mutableCopy];
    Check([root writeToFile:path atomically:YES],@"active fixture write");NSData *before=[NSData dataWithContentsOfFile:path];
    NSDictionary *reply=StateActiveFingerprint(bundle);
    Check([reply[@"available"]boolValue]&&[reply[@"enabled"]boolValue]&&[reply[@"locked"]boolValue]&&[reply[@"current_idfv"]isEqual:uuid]&&[reply[@"source"]isEqual:@"stored_settings"],@"active profile state missing");
    Check([reply[@"fingerprint_data"][@"nested"][@"date"]isEqual:@123]&&[reply[@"fingerprint_data"][@"nested"][@"bytes"]isEqual:@"AP8="]&&[NSJSONSerialization isValidJSONObject:reply],@"active profile is not JSON safe");
    Check(!reply[@"privateField"]&&!reply[@"other.app"]&&[before isEqual:[NSData dataWithContentsOfFile:path]],@"active query leaked or wrote settings");
    for(NSString *key in @[@"App_Disabled",@"Fingerprint_Enabled",@"App_Enabled"]){app[@"App_Enabled"]=@YES;app[key]=[key isEqual:@"App_Disabled"]?@YES:@NO;Check([root writeToFile:path atomically:YES],@"disable fixture");reply=StateActiveFingerprint(bundle);Check(![reply[@"enabled"]boolValue]&&[reply[@"available"]boolValue],@"disabled fingerprint lost saved data or stayed enabled");[app removeObjectForKey:key];}
    root[@"Global_Enabled"]=@YES;root[@"SingleToggleMigrated"]=@NO;Check([root writeToFile:path atomically:YES],@"legacy global fixture");Check([StateActiveFingerprint(bundle)[@"enabled"]boolValue],@"legacy global enable ignored");
    app[@"Fingerprint_Data"]=@{@"VendorIdentifier":@"invalid"};Check([root writeToFile:path atomically:YES],@"bad identity fixture");Check(Reject(^{StateActiveFingerprint(bundle);}),@"bad current identity treated as missing");
    app[@"Fingerprint_Data"]=data;app[@"Fingerprint_Config"]=@{@"valid":@NO};Check([root writeToFile:path atomically:YES],@"bad config fixture");Check(Reject(^{StateActiveFingerprint(bundle);}),@"bad configuration accepted");
    [app removeObjectForKey:@"Fingerprint_Config"];Check([root writeToFile:path atomically:YES],@"legacy config fixture");reply=StateActiveFingerprint(bundle);Check([reply[@"available"]boolValue]&&!reply[@"fingerprint_config"],@"legacy profile manufactured configuration");
    externalSyncFailure=YES;Check(Reject(^{StateActiveFingerprint(bundle);}),@"failed sync returned active data");externalSyncFailure=NO;
    Check([@{}writeToFile:path atomically:YES],@"deleted profile fixture");externalRoot=@{bundle:app};Check(![StateActiveFingerprint(bundle)[@"available"]boolValue],@"stale preference cache resurrected deleted profile");
    Check(!unlink(path.fileSystemRepresentation),@"remove active fixture");Check([StateActiveFingerprint(bundle)[@"available"]boolValue],@"CF-only selected profile unavailable");
    Check(StateExternalAction(@"externalActiveFingerprint")&&Reject(^{StateExternalCommand(bundle,@"externalActiveFingerprint",@{@"path":@"/tmp/other"});}),@"active query action or request boundary missing");
    externalRoot=nil;externalPaths=@[];
    Check(settingsInitializations==initializations,@"read-only active query initialized migrating settings singleton");
    puts("active fingerprint: saved-only query, JSON conversion, effective switches, missing/legacy/invalid profiles, no writes and app isolation passed");
}
static void KeychainTests(void){
    NSDictionary *local=Record((__bridge id)kSecClassGenericPassword,Group,@"local",@"service",@"local-data",NO),*internet=Record((__bridge id)kSecClassInternetPassword,Group,@"web",@"example.test",@"web-data",NO),*synced=Record((__bridge id)kSecClassGenericPassword,Group,@"cloud",@"service",@"cloud-old",YES),*other=Record((__bridge id)kSecClassGenericPassword,Other,@"other",@"service",@"untouched",NO);
    database=[@[local,internet,synced,other] mutableCopy];Reset();NSArray *captured=StateExportRecords(@[Group]);Check(captured.count==3&&deletes==0&&adds==0&&updates==0,@"read-only portable credential capture");
    wrongGroup=YES;Check(Reject(^{StateExportRecords(@[Group]);}),@"export silently relabeled another access group");Reset();wrongClass=YES;Check(Reject(^{StateExportRecords(@[Group]);}),@"export silently relabeled returned credential class");Reset();nullSuccess=YES;Check(Reject(^{StateExportRecords(@[Group]);}),@"Security success with NULL silently accepted as empty");Reset();invalidCopyType=YES;Check(Reject(^{StateExportRecords(@[Group]);}),@"invalid Security return type accepted");Reset();forcedStatus=errSecInteractionNotAllowed;Check(Reject(^{StateExportRecords(@[Group]);}),@"locked credential capture accepted");Reset();database=[NSMutableArray new];emptySuccess=YES;Check(StateExportRecords(@[Group]).count==0,@"empty successful credential arrays rejected");
    for(id type in @[(__bridge id)kSecClassCertificate,(__bridge id)kSecClassKey,(__bridge id)kSecClassIdentity]){database=[@[local,@{(__bridge id)kSecClass:type,(__bridge id)kSecAttrAccessGroup:Group,(__bridge id)kSecAttrSynchronizable:@NO}] mutableCopy];Reset();Check(Reject(^{StateExportRecords(@[Group]);})&&deletes==0&&adds==0&&updates==0,@"nonportable certificate/key/identity capture did not fail before writes");}
    NSMutableDictionary *invalid=[local mutableCopy];invalid[(__bridge id)kSecAttrServer]=@"inet-only";Reset();Check(Reject(^{StateValidateRecords(@[invalid],@[Group]);})&&deletes==0,@"genp accepted inet-only archive attributes");invalid=[internet mutableCopy];invalid[(__bridge id)kSecAttrService]=@"genp-only";Check(Reject(^{StateValidateRecords(@[invalid],@[Group]);}),@"inet accepted genp-only archive attributes");
    for(NSString *bad in @[@"scope",@"duplicate",@"persistent",@"fractional",@"acl",@"generic",@"missing-protection",@"unsupported-protection",@"sync-device-only"]){NSMutableDictionary *record=[local mutableCopy];NSArray *records=@[record];if([bad isEqual:@"scope"])record[(__bridge id)kSecAttrAccessGroup]=Other;if([bad isEqual:@"duplicate"])records=@[record,record];if([bad isEqual:@"persistent"])record[(__bridge id)kSecValuePersistentRef]=[NSData data];if([bad isEqual:@"fractional"])record[(__bridge id)kSecAttrCreator]=@1.5;if([bad isEqual:@"acl"])record[@"ArchivedACL"]=[@"invalid" dataUsingEncoding:NSUTF8StringEncoding];if([bad isEqual:@"generic"])record[(__bridge id)kSecAttrGeneric]=@42;if([bad isEqual:@"missing-protection"])[record removeObjectForKey:(__bridge id)kSecAttrAccessible];if([bad isEqual:@"unsupported-protection"])record[(__bridge id)kSecAttrAccessible]=@"not-an-accessibility";if([bad isEqual:@"sync-device-only"]){record[(__bridge id)kSecAttrSynchronizable]=@YES;record[(__bridge id)kSecAttrAccessible]=(__bridge id)kSecAttrAccessibleWhenUnlockedThisDeviceOnly;}Reset();Check(Reject(^{StateValidateRecords(records,@[Group]);})&&deletes==0&&adds==0&&updates==0,[NSString stringWithFormat:@"invalid credential %@ accepted",bad]);}
    database=[@[local,internet,synced,other,Record((__bridge id)kSecClassGenericPassword,Group,@"extra-cloud",@"service",@"remove",YES)] mutableCopy];NSMutableDictionary *desiredCloud=[synced mutableCopy];desiredCloud[(__bridge id)kSecValueData]=[@"cloud-new" dataUsingEncoding:NSUTF8StringEncoding];NSArray *desired=@[local,desiredCloud];Reset();NSArray *current=StateExportRecords(@[Group]);StateRestoreRecords(desired,current,@[Group]);Check(deletes==3&&adds==1&&updates==1,@"local replacement/synchronized exact update behavior");Check([database containsObject:other]&&database.count==3,@"credential restore touched another app or retained extras");NSArray *readback=StateExportRecords(@[Group]);Check(readback.count==2&&[[NSSet setWithArray:readback] isEqual:[NSSet setWithArray:desired]],@"restored credential readback differs");
    NSMutableDictionary *conflict=[desiredCloud mutableCopy];conflict[(__bridge id)kSecAttrAccessible]=(__bridge id)kSecAttrAccessibleWhenUnlocked;Reset();Check(Reject(^{StateRestoreRecords(@[conflict],@[desiredCloud],@[Group]);})&&deletes==0&&adds==0&&updates==0,@"synchronized protection conflict mutated credentials");
    puts("native state backend: portable genp/inet, exact scope, nonportable fail-closed, synchronized replacement and credential validation passed");
}
static void FingerprintTests(void){
    Check(getuid()==501&&geteuid()==501,@"native preference worker host fixture requires mobile-equivalent UID501");preferences=[FixtureDefaults new];NSDictionary *oldData=@{@"VendorIdentifier":@"11111111-1111-4111-8111-111111111111",@"tag":@"old"},*newData=@{@"VendorIdentifier":@"22222222-2222-4222-8222-222222222222",@"tag":@"new"},*config=@{@"Localization":@{@"Region":@"native"},@"FutureFeature":@{@"enabled":@YES,@"opaque":[NSData dataWithBytes:"\0\1" length:2]}},*other=@{@"sentinel":@"unchanged"};NSString *bundle=@"local.fixture.app";preferences.values=[@{bundle:@{@"Fingerprint_Managed":@YES,@"Fingerprint_Data":oldData,@"Fingerprint_Config":@{@"valid":@YES},@"Fingerprint_Locked":@NO,@"Fingerprint_Enabled":@NO,@"unrelated":@"preserve"},@"other.app":other} mutableCopy];NSDictionary *target=@{@"bundleID":bundle,@"bundlePath":@"/nonexistent/shadow-state-fixture.app"};keychainParent=getppid();NSDictionary *request=@{@"fingerprint":@{@"data":newData,@"configuration":config,@"locked":@NO}};Check([StateMobileFingerprint(@"state-fingerprint-validate",target,request)[@"validated"] boolValue]&&preferences.writes==0,@"fingerprint preflight wrote preferences");StateMobileFingerprint(@"state-fingerprint-restore",target,request);NSDictionary *app=preferences.values[bundle];Check(preferences.writes==1&&[app[@"Fingerprint_Data"]isEqual:newData]&&[app[@"Fingerprint_Config"]isEqual:config]&&[app[@"Fingerprint_Locked"]boolValue],@"fingerprint data/configuration/lock were not restored atomically");Check([app[@"unrelated"]isEqual:@"preserve"]&&![app[@"Fingerprint_Enabled"]boolValue]&&[preferences.values[@"other.app"]isEqual:other],@"fingerprint restore changed unrelated application preferences");NSDictionary *captured=StateMobileFingerprint(@"state-fingerprint-capture",target,@{});Check([captured[@"data"]isEqual:newData]&&[captured[@"configuration"]isEqual:config]&&[captured[@"locked"]boolValue],@"fingerprint readback differs");NSUInteger identityWrites=preferences.writes;Check([StateMobileFingerprint(@"state-fingerprint-identity",target,@{})[@"idfv"] isEqual:newData[@"VendorIdentifier"]]&&preferences.writes==identityWrites,@"current IDFV read changed preferences or returned a different identity");NSMutableDictionary *identityOnly=[app mutableCopy];[identityOnly removeObjectForKey:@"Fingerprint_Config"];preferences.values[bundle]=identityOnly;Check([StateMobileFingerprint(@"state-fingerprint-identity",target,@{})[@"idfv"] isEqual:newData[@"VendorIdentifier"]]&&preferences.writes==identityWrites,@"identity read unnecessarily required a valid full fingerprint configuration");[identityOnly removeObjectForKey:@"Fingerprint_Data"];Check([StateMobileFingerprint(@"state-fingerprint-identity",target,@{})[@"idfv"] isEqual:@""]&&preferences.writes==identityWrites,@"missing IDFV did not return an empty read-only identity");identityOnly[@"Fingerprint_Data"]=@{@"VendorIdentifier":@42};Check([StateMobileFingerprint(@"state-fingerprint-identity",target,@{})[@"idfv"] isEqual:@""]&&preferences.writes==identityWrites,@"non-string IDFV escaped native identity reader");preferences.values[bundle]=app;NSUInteger writes=preferences.writes;Check(Reject(^{StateMobileFingerprint(@"state-fingerprint-restore",target,@{@"fingerprint":@{@"data":newData,@"configuration":@[@"not a dictionary"]}});})&&preferences.writes==writes,@"non-dictionary fingerprint configuration wrote preferences");NSMutableDictionary *enabled=[app mutableCopy];enabled[@"Fingerprint_Enabled"]=@YES;enabled[@"Fingerprint_Locked"]=@YES;preferences.values[bundle]=enabled;
    NSUInteger beforeReset=preferences.writes;
    Check([StateMobileFingerprint(@"state-fingerprint-reset-check",target,@{})[@"ready"]boolValue]&&preferences.writes==beforeReset,@"reset readiness check wrote preferences");
    Check(Reject(^{StateMobileFingerprint(@"state-fingerprint-reset",target,@{@"idfv":@"33333333-3333-4333-8333-333333333333"});})&&preferences.writes==beforeReset,@"mismatched fingerprint reset wrote preferences");
    fingerprintRefreshFails=YES;
    Check(Reject(^{StateMobileFingerprint(@"state-fingerprint-reset",target,@{@"idfv":newData[@"VendorIdentifier"]});})&&[preferences.values[bundle][@"Fingerprint_Locked"]boolValue]&&[preferences.values[bundle][@"Fingerprint_Data"]isEqual:newData],@"failed reset lost its original fingerprint lock/data");
    fingerprintRefreshFails=NO;
    NSDictionary *reset=StateMobileFingerprint(@"state-fingerprint-reset",target,@{@"idfv":newData[@"VendorIdentifier"]});
    Check([reset[@"idfv"]isEqual:@"44444444-4444-4444-8444-444444444444"]&&[preferences.values[bundle][@"Fingerprint_Locked"]boolValue]&&[preferences.values[bundle][@"unrelated"]isEqual:@"preserve"],@"fingerprint reset did not relock/preserve settings");
    puts("native state backend: in-memory mobile preferences restore data/config/lock atomically and preserve unrelated fields/apps");
}


static void ResetBaselineFingerprintTests(NSString *base) {
    NSString *bundle=@"local.fixture.app",*root=[base stringByAppendingPathComponent:@"documents-baseline"];
    NSString *documents=[root stringByAppendingPathComponent:@"Documents"];
    Check([NSFileManager.defaultManager createDirectoryAtPath:documents withIntermediateDirectories:YES attributes:nil error:NULL],@"baseline documents fixture");
    struct attrlist attrs={.bitmapcount=ATTR_BIT_MAP_COUNT,.commonattr=ATTR_CMN_CRTIME};struct timespec original={.tv_sec=1000000000,.tv_nsec=123456789};
    Check(!setattrlist(documents.fileSystemRepresentation,&attrs,&original,sizeof(original),FSOPT_NOFOLLOW),@"historical baseline fixture");
    struct stat st;Check(!stat(root.fileSystemRepresentation,&st),@"baseline container identity");
    NSDictionary *target=@{@"bundleID":bundle,@"bundlePath":@"/nonexistent/shadow-state-fixture.app",@"containers":@[@{@"identifier":bundle,@"path":root,@"device":@((uint64_t)st.st_dev),@"inode":@(st.st_ino)}]};
    NSDictionary *data=@{@"VendorIdentifier":@"11111111-1111-4111-8111-111111111111"};
    preferences=[FixtureDefaults new];preferences.values=[@{bundle:@{@"Fingerprint_Managed":@YES,@"Fingerprint_Enabled":@YES,@"Fingerprint_Locked":@YES,@"Fingerprint_Data":data,@"Fingerprint_Config":@{@"valid":@YES},@"unrelated":@"keep"}}mutableCopy];keychainParent=getppid();
    StateMobileFingerprint(@"state-fingerprint-reset-baseline",target,@{@"apply":@NO});
    NSDictionary *baseline=preferences.values[bundle][@"Fingerprint_ResetBaseline"];
    Check(SHDWFingerprintResetBaselineValid(baseline),@"baseline not stored in Shadow profile");
    NSDictionary *captured=StateMobileFingerprint(@"state-fingerprint-capture",target,@{});
    Check([captured[@"resetBaseline"]isEqual:baseline],@"fingerprint capture omitted baseline");
    StateMobileFingerprint(@"state-fingerprint-reset-baseline",target,@{@"apply":@YES});
    StateMobileFingerprint(@"state-fingerprint-reset",target,@{@"idfv":data[@"VendorIdentifier"]});
    Check([preferences.values[bundle][@"Fingerprint_ResetBaseline"]isEqual:baseline],@"fingerprint refresh overwrote original baseline");
    Check([preferences.values[bundle][@"unrelated"]isEqual:@"keep"],@"baseline reset lost unrelated profile fields");
    struct stat before,after;Check(!stat(documents.fileSystemRepresentation,&before),@"read post-reset metadata");
    StateMobileFingerprint(@"state-fingerprint-restore",target,@{@"fingerprint":captured});
    Check(!stat(documents.fileSystemRepresentation,&after)&&before.st_birthtimespec.tv_sec==after.st_birthtimespec.tv_sec&&before.st_birthtimespec.tv_nsec==after.st_birthtimespec.tv_nsec,@"fingerprint restore randomized live Documents time");
    Check(SHDWFingerprintResetBaselineTimesEqual(preferences.values[bundle][@"Fingerprint_ResetBaseline"],baseline),@"fingerprint restore lost original baseline");
    NSMutableDictionary *legacy=[captured mutableCopy];[legacy removeObjectForKey:@"resetBaseline"];
    StateMobileFingerprint(@"state-fingerprint-restore",target,@{@"fingerprint":legacy});
    Check([preferences.values[bundle][@"Fingerprint_ResetBaseline"]isEqual:baseline],@"legacy fingerprint restore discarded cached original baseline");
    NSUInteger writes=preferences.writes;NSMutableDictionary *bad=[captured mutableCopy];bad[@"resetBaseline"]=@{@"Version":@YES,@"Containers":@{}};
    Check(Reject(^{StateMobileFingerprint(@"state-fingerprint-validate",target,@{@"fingerprint":bad});})&&writes==preferences.writes,@"malformed baseline passed readonly preflight");
    NSMutableDictionary *outOfScope=[captured mutableCopy];
    NSDictionary *record=[baseline[@"Containers"] allValues].firstObject;
    outOfScope[@"resetBaseline"]=@{@"Version":@1,@"Containers":@{@"other.container":record}};
    Check(Reject(^{StateMobileFingerprint(@"state-fingerprint-validate",target,@{@"fingerprint":outOfScope});})&&writes==preferences.writes,@"out-of-scope baseline passed readonly restore preflight");
    puts("native reset baseline: mobile profile persistence, fingerprint refresh preservation, capture/restore roundtrip and legacy compatibility passed");
}
static NSDictionary *RequiredWorker(NSString *mode,NSDictionary *target,NSString *directory){@try{return StateWorker(mode,target,directory);}@catch(NSException *exception){Check(NO,[NSString stringWithFormat:@"%@ failed: %@",mode,exception.reason]);return nil;}}
static void WorkerReplacementTests(NSString *root){
    fixtureRoot=root;
    NSString *directory=[root stringByAppendingPathComponent:@"replacement-worker"],*requestPath=[directory stringByAppendingPathComponent:@"request.plist"];
    NSError *error=nil;
    Check([NSFileManager.defaultManager createDirectoryAtPath:directory withIntermediateDirectories:NO attributes:nil error:&error],@"create replacement worker fixture");
    fixtureOwners=@{requestPath:@0};
    NSDictionary *target=@{@"bundleID":@"local.fixture.app",@"bundlePath":@"/nonexistent/shadow-state-fixture.app",@"team":@"TEAM",@"keychainGroups":@[Group]};
    NSDictionary *base=Record((__bridge id)kSecClassGenericPassword,Group,@"saved",@"service",@"archived bytes",NO),*control=Record((__bridge id)kSecClassGenericPassword,Other,@"control",@"service",@"unchanged",NO);
    for(id invalid in @[@42,@[@"not a string"],@{@"bad":@"dictionary"}]){
        NSMutableDictionary *bad=[base mutableCopy];bad[(__bridge id)kSecAttrGeneric]=invalid;
        Check([StateEncode(@{@"records":@[bad]}) writeToFile:requestPath atomically:YES]&&!chmod(requestPath.fileSystemRepresentation,0600),@"write invalid archive preflight");
        database=[@[base,control]mutableCopy];Reset();
        for(NSString *mode in @[@"state-validate",@"state-restore"])Check(Reject(^{StateWorker(mode,target,directory);})&&deletes==0&&adds==0&&updates==0,@"worker accepted unsupported archived generic type or wrote during invalid preflight");
    }
    NSData *binary=[NSData dataWithBytes:(const unsigned char[]){0,255,128,1} length:4];
    for(id archivedGeneric in @[NSNull.null,@"",@"中文🔑",binary]){
        NSMutableDictionary *saved=[base mutableCopy];if(archivedGeneric!=NSNull.null)saved[(__bridge id)kSecAttrGeneric]=archivedGeneric;
        NSData *payload=StateEncode(@{@"records":@[saved]});
        Check([payload writeToFile:requestPath atomically:YES]&&!chmod(requestPath.fileSystemRepresentation,0600),@"write valid worker request");
        for(NSString *currentGeneric in @[@"",@"live"]){
            NSMutableDictionary *current=[base mutableCopy];current[(__bridge id)kSecAttrGeneric]=currentGeneric;
            database=[@[current,control]mutableCopy];Reset();
            NSDictionary *response=RequiredWorker(@"state-validate",target,directory);
            Check([response[@"ok"]boolValue]&&deletes==0&&adds==0&&updates==0&&[database containsObject:current],@"valid archive failed read-only worker preflight on current string generic");
            NSDictionary *exportResponse=RequiredWorker(@"state-export",target,directory);
            NSArray *before=StateDecode([[NSData alloc]initWithBase64EncodedString:exportResponse[@"result"] options:0]);
            Check([before isEqual:@[current]],@"worker export changed live string generic type/value");
            RequiredWorker(@"state-restore",target,directory);
            Check([database containsObject:saved]&&[database containsObject:control]&&database.count==2,@"worker replacement changed archived generic type/value or another group");
            exportResponse=RequiredWorker(@"state-export",target,directory);
            NSArray *after=StateDecode([[NSData alloc]initWithBase64EncodedString:exportResponse[@"result"] options:0]);
            Check([after isEqual:@[saved]]&&[[NSData dataWithContentsOfFile:requestPath]isEqual:payload],@"worker export/archive changed restored string or binary bytes");
        }
    }
    fixtureOwners=nil;
    puts("native worker: absent/empty/unicode/binary generic roundtrip, current string replacement, unsupported types rejected and other groups preserved");
}

// Only lstat UID metadata is doubled, for exact paths inside this temporary root.
// All links, modes, canonical resolution, sentinels and cleanup use the real filesystem.
static void AnchorTests(NSString *root){
    fixtureRoot=root;NSFileManager *fm=NSFileManager.defaultManager;NSError *error=nil;
    NSString *installed=[root stringByAppendingPathComponent:@"installed"],*bootstrap=[root stringByAppendingPathComponent:@"bootstrap"],*worker=[root stringByAppendingPathComponent:@"worker"],*outside=[root stringByAppendingPathComponent:@"untouched"];
    for(NSString *path in @[installed,bootstrap,worker,outside])Check([fm createDirectoryAtPath:path withIntermediateDirectories:NO attributes:nil error:&error],@"create anchor fixture");
    Check(!chmod(bootstrap.fileSystemRepresentation,0755),@"set trusted fixture mode");
    NSString *original=[installed stringByAppendingPathComponent:@".jbroot"],*copy=[worker stringByAppendingPathComponent:@".jbroot"],*parent=[installed stringByAppendingPathComponent:@"helper"],*sentinel=[bootstrap stringByAppendingPathComponent:@"sentinel"],*other=[outside stringByAppendingPathComponent:@"sentinel"];
    NSData *bytes=[@"unchanged trusted target" dataUsingEncoding:NSUTF8StringEncoding];Check([bytes writeToFile:sentinel atomically:YES]&&[bytes writeToFile:other atomically:YES],@"write anchor sentinels");
    fixtureOwners=@{original:@0,bootstrap:@0};
#if defined(SHADOW_ROOTHIDE)
    Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"roothide accepted missing required loader anchor");
#else
    PreserveWorkerLoaderAnchor(parent,worker);Check(![fm fileExistsAtPath:copy],@"ordinary lane invented missing loader anchor");
#endif
    Check(!symlink(bootstrap.fileSystemRepresentation,original.fileSystemRepresentation),@"create original anchor");
    PreserveWorkerLoaderAnchor(parent,worker);struct stat link;Check(!lstat(copy.fileSystemRepresentation,&link)&&S_ISLNK(link.st_mode)&&[Canonical(copy)isEqual:Canonical(original)],@"trusted anchor not copied to identical canonical target");
    Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"existing destination anchor overwritten");Check(!unlink(copy.fileSystemRepresentation),@"remove private anchor");
    fixtureOwners=@{bootstrap:@0};Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"host-owned source anchor accepted");fixtureOwners=@{original:@0};Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"host-owned destination accepted");fixtureOwners=@{original:@0,bootstrap:@0};
    Check(!chmod(bootstrap.fileSystemRepresentation,0775),@"set unsafe target mode");Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"group-writable target accepted");Check(!chmod(bootstrap.fileSystemRepresentation,0755),@"restore target mode");
    Check(!unlink(original.fileSystemRepresentation)&&!symlink(other.fileSystemRepresentation,original.fileSystemRepresentation),@"make non-directory target");fixtureOwners=@{original:@0,other:@0};Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"regular-file target accepted");
    Check(!unlink(original.fileSystemRepresentation)&&!symlink([[root stringByAppendingPathComponent:@"absent"]fileSystemRepresentation],original.fileSystemRepresentation),@"make dangling anchor");Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"dangling anchor accepted");
    Check(!unlink(original.fileSystemRepresentation)&&[bytes writeToFile:original atomically:YES],@"make nonlink anchor");Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);}),@"nonlink installed anchor accepted");Check(!unlink(original.fileSystemRepresentation)&&!symlink(bootstrap.fileSystemRepresentation,original.fileSystemRepresentation),@"restore original anchor");fixtureOwners=@{original:@0,bootstrap:@0};
    Check(!symlink(outside.fileSystemRepresentation,copy.fileSystemRepresentation),@"create conflicting destination");Check(Reject(^{PreserveWorkerLoaderAnchor(parent,worker);})&&[Canonical(copy)isEqual:outside],@"existing destination followed or replaced");Check(!unlink(copy.fileSystemRepresentation),@"remove conflicting destination");
    PreserveWorkerLoaderAnchor(parent,worker);Check([fm removeItemAtPath:worker error:&error],@"private directory cleanup");Check([[NSData dataWithContentsOfFile:sentinel]isEqual:bytes]&&[[NSData dataWithContentsOfFile:other]isEqual:bytes]&&[Canonical(original)isEqual:bootstrap],@"private cleanup changed anchor target or unrelated sentinel");fixtureOwners=nil;
    puts("native loader anchor: temp-only UID authority double; real symlink trust/mode/dangling/conflict/cleanup checks passed");
}

static void CatalogProjectionTests(void) {
    NSDictionary *bad=@{@"idfv":@"11111111-1111-4111-8111-111111111111",@"unavailable":@YES,@"error":@"corrupt",@"date":NSDate.date,@"recoverySource":@NO};
    NSDictionary *good=@{@"idfv":@"22222222-2222-4222-8222-222222222222",@"finalizationPending":@YES,@"recoverySource":@YES,@"archiveInfo":@{@"archiveSize":@42},@"stateArchiveInfo":@{@"archiveSize":@8}};
    NSArray *catalog=StateConciseCatalog(@[bad,good]);
    Check(catalog.count==2&&[catalog[0][@"unavailable"]boolValue]&&[catalog[0][@"error"]isEqual:@"corrupt"]&&[catalog[0][@"size"]isEqual:@0],@"corrupt snapshot status lost in catalog transport");
    Check([catalog[1][@"finalizationPending"]boolValue]&&[catalog[1][@"size"]isEqual:@50],@"pending finalization status lost in catalog transport");
}
int main(int argc,const char **argv){@autoreleasepool{CatalogProjectionTests();Check(argc==2,@"fixture directory argument");ExternalTests([NSString stringWithUTF8String:argv[1]]);ActiveFingerprintTests([NSString stringWithUTF8String:argv[1]]);KeychainTests();NativePreferenceTests([NSString stringWithUTF8String:argv[1]]);FingerprintTests();ResetBaselineFingerprintTests([NSString stringWithUTF8String:argv[1]]);WorkerReplacementTests([NSString stringWithUTF8String:argv[1]]);AnchorTests([NSString stringWithUTF8String:argv[1]]);return 0;}}
'''


def main():
    if sys.platform != "darwin":
        raise SystemExit("This optional check requires macOS Foundation/Security")
    archive = Path(os.environ.get("ARCHIVE_PREFIX", "/opt/homebrew/opt/libarchive"))
    zstd = Path(os.environ.get("ZSTD_PREFIX", "/opt/homebrew/opt/zstd"))
    with tempfile.TemporaryDirectory(prefix="shadow-state-backend-") as directory:
        temp = Path(directory).resolve()
        source = temp / "main.m"
        source.write_text(HARNESS.replace("__CLEANER__", str(ROOT / "src/ShadowCleaner/Cleaner.m")))
        binary = temp / "check"
        command = ["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-Wno-incomplete-implementation", "-Wno-unused-function", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g", "-O1", "-framework", "Foundation", "-framework", "Security", "-framework", "LocalAuthentication", "-I" + str(archive / "include"), "-I" + str(ROOT / "src/Shadow.framework/Headers"), "-L" + str(archive / "lib"), "-L" + str(zstd / "lib"), "-Wl,-rpath," + str(archive / "lib"), "-Wl,-rpath," + str(zstd / "lib"), str(source), str(ROOT / "src/AppState/Archive.m"), str(ROOT / "src/AppState/State.m"), "-larchive", "-lzstd", "-o", str(binary)]
        subprocess.run(command, check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        fixture = temp / "fixture"
        fixture.mkdir()
        subprocess.run([str(binary), str(fixture)], env=environment, check=True, timeout=30)
        subprocess.run(command[:-2] + ["-DSHADOW_ROOTHIDE", "-o", str(binary)], check=True)
        roothide_fixture = temp / "roothide-fixture"
        roothide_fixture.mkdir()
        subprocess.run([str(binary), str(roothide_fixture)], env=environment, check=True, timeout=30)


if __name__ == "__main__":
    main()
