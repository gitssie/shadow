#import "UniversalHooks.h"
#import "../HookCoordinator.h"

#include <mach-o/dyld.h>
#include <string.h>
#include <stdlib.h>
#include "rebind_import_index.h"

// Rebind-spec journal + event-driven repair (anti-fishhook).
//
// Two journals work together:
//   * the SLOT journal (SHDWHookSession.m, rebind_slots.h core) records every
//     import-slot address a rebind wrote, with the expected replacement.
//     Repair is check-then-store — no HookKit involvement, so it cannot hit
//     the "repeat request invalidates the plan" hazard and needs no session.
//   * this SPEC journal records every (symbol, replacement) pair installers
//     requested. It exists for late-loaded images: a global rebind only
//     covers imports bound at install time, so a detector framework dlopen'd
//     afterwards gets a scoped HookKit replay of the full journal.
//
// Both journals only grow on installer paths. Repair replays use the
// no-journal HookKit variant, so an image event never feeds the journal it
// is repairing (75 specs x N images would otherwise explode it).
//
#define SHDW_REBIND_SPECS_MAX 320

typedef struct {
    char* name;
    void* replacement;
    // Caller-owned original cell, or NULL. Must be process-lifetime: replay
    // dereferences it on later image loads, after the installer returned.
    void** originalCell;
    BOOL cacheScopeUnavailable;
} shdw_rebind_spec_t;

static shdw_rebind_spec_t gSHDWRebindSpecs[SHDW_REBIND_SPECS_MAX];
static uint32_t gSHDWRebindSpecCount;
static uint32_t gSHDWRebindSpecOverflowed;

void SHDWRebindJournalNote(const char* symbolName, void* replacement, void** originalCell) {
    if(!symbolName || !symbolName[0] || !replacement) {
        return;
    }
    uint32_t count = __atomic_load_n(&gSHDWRebindSpecCount, __ATOMIC_ACQUIRE);
    for(uint32_t i = 0; i < count; i++) {
        if(gSHDWRebindSpecs[i].replacement == replacement &&
           strcmp(gSHDWRebindSpecs[i].name, symbolName) == 0) {
            return;
        }
    }
    if(count >= SHDW_REBIND_SPECS_MAX) {
        if(!__atomic_exchange_n(&gSHDWRebindSpecOverflowed, 1, __ATOMIC_ACQ_REL)) {
            NSLog(@"[Shadow] rebind spec journal full (%u) — new-image replay will miss %s",
                  count, symbolName);
        }
        return;
    }
    char* copy = strdup(symbolName);
    if(!copy) {
        return;
    }
    gSHDWRebindSpecs[count] = (shdw_rebind_spec_t){ .name = copy,
        .replacement = replacement, .originalCell = originalCell };
    __atomic_store_n(&gSHDWRebindSpecCount, count + 1, __ATOMIC_RELEASE);
}

extern const void *_dyld_get_shared_cache_range(size_t *length)
    __attribute__((weak_import));

static BOOL shdw_rebind_replay_images(SHDWHookSession *session,
    const void *const *headers, size_t imageCount, uint32_t count) {
    const char *names[SHDW_REBIND_SPECS_MAX];
    uint64_t imported[64][(SHDW_REBIND_SPECS_MAX + 63) / 64];
    for(uint32_t i = 0; i < count; i++) names[i] = gSHDWRebindSpecs[i].name;
    size_t cacheSize = 0;
    const void *cacheBase = _dyld_get_shared_cache_range
        ? _dyld_get_shared_cache_range(&cacheSize) : NULL;
    uint64_t cached = 0;
    for(size_t j = 0; j < imageCount; j++) {
        if(cacheBase && (uintptr_t)headers[j] >= (uintptr_t)cacheBase &&
           (uintptr_t)headers[j] - (uintptr_t)cacheBase < cacheSize)
            cached |= UINT64_C(1) << j;
        if(!shdw_rebind_import_mask(headers[j], names, count, imported[j]))
            for(size_t w = 0; w < (count + 63) / 64; w++) imported[j][w] = UINT64_MAX;
    }
    SHDWRebindEntry entries[SHDW_REBIND_SPECS_MAX];
    size_t selected = 0;
    for(uint32_t pass = 0; pass < 2; pass++) {
        for(uint32_t i = 0; i < count; i++) {
            shdw_rebind_spec_t *spec = &gSHDWRebindSpecs[i];
            if((pass == 0) != (strcmp(spec->name, "vm_protect") == 0)) continue;
            uint64_t mask = 0;
            for(size_t j = 0; j < imageCount; j++)
                if(imported[j][i / 64] & (UINT64_C(1) << (i % 64))) mask |= UINT64_C(1) << j;
            if(__atomic_load_n(&spec->cacheScopeUnavailable, __ATOMIC_ACQUIRE)) mask &= ~cached;
            if(mask) entries[selected++] = (SHDWRebindEntry){spec->name, spec->replacement,
                spec->originalCell, &spec->cacheScopeUnavailable, mask};
        }
    }
    return !selected || [session replayRebindEntries:entries count:selected
        inCallerImages:headers imageCount:imageCount cachedMask:cached];
}

__attribute__((visibility("default")))
void SHDWRebindRepairImage(SHDWHookSession* session, const void* imageHeader) {
    if(!session || !imageHeader) return;
    uint32_t count = __atomic_load_n(&gSHDWRebindSpecCount, __ATOMIC_ACQUIRE);
    shdw_rebind_replay_images(session, &imageHeader, 1, count);
}

void SHDWRebindRepairImages(SHDWHookSession *session,
    const struct mach_header *const *images, size_t imageCount) {
    if(!session || !images || !imageCount) return;
    uint32_t rules = __atomic_load_n(&gSHDWRebindSpecCount, __ATOMIC_ACQUIRE);
    const void *headers[64];
    size_t count = 0;
    for(size_t i = 0; i < imageCount; i++) {
        if(images[i]) headers[count++] = images[i];
        if(count == 64) {
            shdw_rebind_replay_images(session, headers, count, rules);
            count = 0;
        }
    }
    if(count) shdw_rebind_replay_images(session, headers, count, rules);
}

static uint32_t gSHDWRepairPending;

void SHDWRequestRebindRepair(void) {
    // Coalesced: at most one repair block queued. Runs on main, like the
    // detector escalation, so it never executes on a hook's stack or inside
    // the coordinator's lifecycle queue (whose re-entrancy guard would eat
    // a nested install).
    if(__atomic_exchange_n(&gSHDWRepairPending, 1, __ATOMIC_ACQ_REL)) {
        return;
    }
    dispatch_async(dispatch_get_main_queue(), ^{
        __atomic_store_n(&gSHDWRepairPending, 0, __ATOMIC_RELEASE);
        SHDWRebindRepairSlots();
    });
}
