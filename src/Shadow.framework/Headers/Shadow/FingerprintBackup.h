#pragma once
#import <Foundation/Foundation.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef SHDW_FINGERPRINT_BACKUP_ROOT
#define SHDW_FINGERPRINT_BACKUP_ROOT "/private/var/mobile/Library/ShadowBackups"
#endif

static inline BOOL SHDWFingerprintDataIsReadOnly(NSString *bundle, id data) {
    if (![data isKindOfClass:NSDictionary.class]) return NO;
    id value = data[@"VendorIdentifier"];
    if (!value) return NO;
    NSString *identity = [value isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:value].UUIDString : nil;
    if (!identity) return NO;
    if (![bundle isKindOfClass:NSString.class] || !bundle.length ||
        [bundle containsString:@"/"] || [bundle isEqual:@"."] || [bundle isEqual:@".."]) return YES;
    int saved = errno;
    int directory = open(SHDW_FINGERPRINT_BACKUP_ROOT, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (directory < 0) { BOOL readOnly = errno != ENOENT; errno = saved; return readOnly; }
    for (NSString *component in @[bundle, @"snapshots"]) {
        int next = openat(directory, component.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        int failure = errno;
        close(directory);
        if (next < 0) { errno = saved; return failure != ENOENT; }
        directory = next;
    }
    struct stat info;
    BOOL readOnly = fstatat(directory, identity.fileSystemRepresentation, &info, AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT;
    close(directory);
    errno = saved;
    return readOnly;
}
