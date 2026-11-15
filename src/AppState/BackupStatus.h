#pragma once
#import <Foundation/Foundation.h>

// Shared values for the current workflow associated with a saved snapshot.
static NSString *const SHDWBackupStatusBackingUp = @"backing_up";
static NSString *const SHDWBackupStatusBackedUp = @"backed_up";
static NSString *const SHDWBackupStatusResetting = @"resetting";
static NSString *const SHDWBackupStatusResetCompleted = @"reset_completed";
static NSString *const SHDWBackupStatusRestoring = @"restoring";
static NSString *const SHDWBackupStatusIdentityPending = @"identity-pending";
static NSString *const SHDWBackupStatusIdentityCommitted = @"identity-committed";
static NSString *const SHDWBackupStatusRestored = @"restored";
static NSString *const SHDWBackupStatusBackupFailed = @"backup_failed";
static NSString *const SHDWBackupStatusResetFailed = @"reset_failed";
static NSString *const SHDWBackupStatusRestoreFailed = @"restore_failed";
