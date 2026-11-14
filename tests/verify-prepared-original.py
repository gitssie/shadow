"""Exercise production hook installation with portable HookKit lifecycle doubles."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/SHDWHookSession.m").read_text()
start = source.index("static BOOL shdw_apply_hook_spec_once(")
end = source.index("static BOOL shdw_apply_hook_spec_with_subsets", start)
body = source[start:end]
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef bool BOOL;
#define YES true
#define NO false
typedef int hk_status_t;
enum { HK_STATUS_OK, HK_ABI_VERSION_3_0, HK_INSTALL_CONTEXT_EARLY_PROCESS,
    HK_OUTCOME_ANALYZED, HK_OUTCOME_PREPARED, HK_OUTCOME_ACTIVE,
    HK_MUTATION_NONE, HK_MUTATION_CHANGED, HK_ORIGINAL_NONE,
    HK_ORIGINAL_REQUIRED, HK_TARGET_FUNCTION_SYMBOL, HK_REACH_EXISTING_IMPORTS = 128 };
typedef struct { size_t struct_size; int struct_version, install_context; } hk_runtime_config_t;
typedef struct { int original_requirement, target_kind, required_reach; void *replacement; const char *stable_hook_id; } hk_hook_spec_t;
typedef struct { int backend; } hk_runtime_t;
typedef struct { int outcome, mutation; bool original_available;
    struct { const char *data; size_t length; } error_message;
    struct { uintptr_t address; } continuation; } hk_hook_result_t;
typedef struct { hk_hook_result_t result; int backend; void *original; } hk_hook_t;
typedef struct { hk_hook_t hook; } hk_plan_t;
typedef struct { int unused; } hk_report_t;
typedef hk_status_t (*SHDWHKRuntimeCreateWithBackendOverride)(const hk_runtime_config_t *, const char *, hk_runtime_t **);
static hk_runtime_t runtimes[2];
static hk_plan_t plans[2];
static hk_report_t report;
static int creates, releases, planReleases, commits, prepareCalls, livePlans;
static int scenario;
static void **callerCell;
static void **publishedCell;
static void *publishedValue;
static void *continuation = (void *)(uintptr_t)0x1234;
static bool shdw_cell_holds_live_original(void **p) {
    return p && p == publishedCell && *p && *p == publishedValue;
}
static void shdw_note_published_cell(void **p) { publishedCell = p; publishedValue = *p; }
static bool hk_hook_result_refused_cleanly(const hk_hook_result_t *r) {
    return r->mutation == HK_MUTATION_NONE && r->outcome != HK_OUTCOME_ACTIVE;
}
static int hk_hook_copy_result(hk_hook_t *h, hk_hook_result_t *r) { *r = h->result; return 0; }
static void shdw_finish_uninstalled_hook(hk_hook_t *h, void **p, BOOL entryLive, BOOL *clean) {
    if (p && !entryLive && h->result.mutation == HK_MUTATION_NONE) *p = NULL;
    if (clean) *clean = hk_hook_result_refused_cleanly(&h->result);
}
static void *shdw_prepared_original(hk_hook_t *h, const hk_hook_spec_t *s, const hk_hook_result_t *r) {
    (void)s; (void)r; return h->original;
}
static int hk_runtime_create(const hk_runtime_config_t *c, hk_runtime_t **r) {
    assert(c->struct_size == sizeof(*c)); assert(creates < 2);
    *r = &runtimes[creates++]; (*r)->backend = 0; return 0;
}
static int override_create(const hk_runtime_config_t *c, const char *b, hk_runtime_t **r) {
    assert(!strcmp(b, "provider-ellekit"));
    /* The first uncommitted plan and owned runtime must be gone before retry. */
    assert(!livePlans && planReleases == creates && releases == creates);
    int status = hk_runtime_create(c, r); (*r)->backend = 1; return status;
}
static void hk_runtime_release(hk_runtime_t *r) { if (r) releases++; }
static int hk_plan_create(hk_runtime_t *r, const void *unused, hk_plan_t **p) {
    (void)unused; assert(livePlans == 0); livePlans++;
    *p = &plans[r->backend]; memset(*p, 0, sizeof(**p)); (*p)->hook.backend = r->backend; return 0;
}
static int hk_plan_add_hook(hk_plan_t *p, const hk_hook_spec_t *s, hk_hook_t **h) {
    (void)s; *h = &p->hook; return 0;
}
static int hk_plan_analyze(hk_plan_t *p, void *unused) {
    (void)unused; p->hook.result.outcome = HK_OUTCOME_ANALYZED;
    p->hook.result.mutation = HK_MUTATION_NONE; return 0;
}
static int hk_plan_prepare(hk_plan_t *p, void *unused) {
    (void)unused; prepareCalls++;
    p->hook.result.outcome = HK_OUTCOME_PREPARED;
    if (scenario == 1) p->hook.result.mutation = HK_MUTATION_CHANGED;
    if ((p->hook.backend && scenario != 2) || scenario == 4 || scenario == 5)
        p->hook.original = continuation;
    if (scenario == 3) { p->hook.result.mutation = HK_MUTATION_CHANGED; return -1; }
    return 0;
}
static int hk_plan_commit(hk_plan_t *p, hk_report_t **r) {
    commits++;
    /* Simulate entering the replacement at the first mutation. */
    assert(!callerCell || *callerCell == continuation);
    p->hook.result.mutation = HK_MUTATION_CHANGED;
    if (scenario == 5) return -1;
    p->hook.result.outcome = HK_OUTCOME_ACTIVE;
    p->hook.result.original_available = true; *r = &report; return 0;
}
static void hk_report_release(hk_report_t *r) { (void)r; }
static void hk_plan_release(hk_plan_t *p) { if (p) { livePlans--; planReleases++; } }
static void **hk_hook_original_slot(hk_hook_t *h) { return &h->original; }
static void *hk_original_slot_load(void **slot) { return *slot; }
static void SHDWRememberImportSlots(hk_report_t *r, uintptr_t p) { (void)r; (void)p; }
'''
suffix = r'''
static void reset(int mode, void **cell) {
    creates = releases = planReleases = commits = prepareCalls = livePlans = 0;
    scenario = mode; callerCell = cell; publishedCell = NULL; publishedValue = NULL;
    if (cell) *cell = (void *)(uintptr_t)0xdead;
}
int main(void) {
    hk_hook_spec_t spec = { .original_requirement = HK_ORIGINAL_REQUIRED,
        .stable_hook_id = "shadow.native-tls" };
    void *cell;
    BOOL clean, subsets, cache;
#define APPLY(override, create, borrowed) shdw_apply_hook_spec_once(&spec, &cell, override, create, &clean, &subsets, &cache, borrowed)
    reset(0, &cell);
    spec.stable_hook_id = "shadow.function";
    assert(!APPLY(NULL, override_create, NULL));
    assert(creates == 1 && releases == 1 && !commits && !cell);
    reset(0, &cell);
    spec.stable_hook_id = "shadow.native-tls";
    assert(APPLY(NULL, override_create, NULL));
    assert(creates == 2 && releases == 2 && planReleases == 2 && commits == 1);
    assert(cell == continuation && !clean && !subsets && !cache && !livePlans);
    reset(1, &cell); /* A prepared result reporting mutation is never retried. */
    assert(!APPLY(NULL, override_create, NULL));
    assert(creates == 1 && releases == 1 && !commits && !cell);
    reset(2, &cell); /* Neither backend publishes early: retry is bounded. */
    assert(!APPLY(NULL, override_create, NULL));
    assert(creates == 2 && releases == 2 && !commits && !cell);
    reset(3, &cell); /* Unsafe prepare failure cannot enter fallback. */
    assert(!APPLY(NULL, override_create, NULL));
    assert(creates == 1 && releases == 1 && !commits && !cell);
    reset(0, &cell); /* Optional override constructor absent. */
    assert(!APPLY(NULL, NULL, NULL));
    assert(creates == 1 && releases == 1 && !commits && !cell);
    reset(0, &cell); /* Already on fallback backend. */
    assert(APPLY("provider-ellekit", override_create, NULL));
    assert(creates == 1 && releases == 1 && commits == 1);
    reset(0, &cell); /* Borrowed replay runtimes keep caller ownership. */
    hk_runtime_t borrowed = {0};
    assert(!APPLY(NULL, override_create, &borrowed));
    assert(!creates && !releases && planReleases == 1 && !commits);
    reset(4, &cell); /* A normal prepared continuation needs no retry. */
    assert(APPLY(NULL, override_create, NULL));
    assert(creates == 1 && releases == 1 && commits == 1);
    reset(5, &cell); /* A commit failure after mutation is never retried. */
    assert(!APPLY(NULL, override_create, NULL));
    assert(creates == 1 && releases == 1 && commits == 1 && cell == continuation);
    reset(2, &cell); /* Existing live cells survive both missing-continuation attempts. */
    cell = continuation; shdw_note_published_cell(&cell);
    assert(!APPLY(NULL, override_create, NULL));
    assert(creates == 2 && cell == continuation && !commits);
    puts("prepared original: publication, bounded fallback and cleanup passed");
}
'''
with tempfile.TemporaryDirectory(prefix="shadow-prepared-original-") as tmp:
    src = Path(tmp) / "test.c"
    binary = Path(tmp) / "test"
    src.write_text(prefix + body + suffix)
    subprocess.run(shlex.split(os.environ.get("CC", "cc")) +
                   ["-std=c11", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
