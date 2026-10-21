#import "ReceiptPolicy.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct { char *path; char *alias; } SHDWReceiptPaths;
static _Atomic(SHDWReceiptPaths *) shdw_receipt_paths;

void SHDWReceiptCaptureURL(NSURL *url) {
    if(!url.isFileURL || atomic_load_explicit(&shdw_receipt_paths, memory_order_acquire)) return;
    __attribute__((objc_precise_lifetime)) NSString *pathString = url.path;
    const char *path = pathString.fileSystemRepresentation;
    if(!path) return;
    SHDWReceiptPaths *paths = calloc(1, sizeof(*paths));
    if(!paths) return;
    paths->path = strdup(path);
    BOOL needsAlias = !strncmp(path, "/private/var/", 13) || !strncmp(path, "/var/", 5);
    if(!strncmp(path, "/private/var/", 13)) paths->alias = strdup(path + 8);
    else if(!strncmp(path, "/var/", 5)) {
        size_t length = strlen(path) + 9;
        paths->alias = malloc(length);
        if(paths->alias) snprintf(paths->alias, length, "/private%s", path);
    }
    SHDWReceiptPaths *expected = NULL;
    if(!paths->path || (needsAlias && !paths->alias) || !atomic_compare_exchange_strong_explicit(&shdw_receipt_paths, &expected, paths,
       memory_order_acq_rel, memory_order_acquire)) {
        free(paths->path); free(paths->alias); free(paths);
    }
}

BOOL SHDWReceiptPathMatches(const char *path) {
    if(!path) return NO;
    SHDWReceiptPaths *paths = atomic_load_explicit(&shdw_receipt_paths, memory_order_acquire);
    if(!paths) return NO;
    if(!strcmp(path, paths->path) || (paths->alias && !strcmp(path, paths->alias))) return YES;
    if(strstr(path, "/./") || strstr(path, "/../") || strstr(path, "//")) {
        NSString *string = [[NSString alloc] initWithUTF8String:path];
        __attribute__((objc_precise_lifetime)) NSString *normalized = [string stringByStandardizingPath];
        const char *value = normalized.fileSystemRepresentation;
        return value && (!strcmp(value, paths->path) || (paths->alias && !strcmp(value, paths->alias)));
    }
    return NO;
}

NSError *SHDWReceiptUnavailableError(void) {
    return [NSError errorWithDomain:@"SKErrorDomain" code:0
        userInfo:@{NSLocalizedDescriptionKey: @"App receipt is unavailable."}];
}
