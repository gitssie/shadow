#!/usr/bin/env python3
"""Execute the production entrypoint adapter with HookKit lifecycle doubles."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS clang")
ROOT = Path(__file__).resolve().parents[1]
include = os.environ.get("HOOKKIT_INCLUDE")
if not include or not (Path(include) / "HookKit/HookKitPlan.h").is_file():
    raise SystemExit("Set HOOKKIT_INCLUDE to the HookKit public include directory")
SOURCE = r'''
#include "FunctionHook.h"
#include <HookKit/HookKitRuntime.h>
#include <HookKit/HookKitPlan.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int mode, phase, commits, plans, runtimes, overrides, enumerations, resultReads;
static bool provider;
static void *cell, *prior;
static int target(int n) { return n + 1; }
static int real(int n) { return n + 3; }
static int replacement(int n) { return n + 5; }
static int earlier(int n) { return n + 7; }
hk_status_t hk_runtime_create(const hk_runtime_config_t *config, hk_runtime_t **runtime) {
    assert(config->struct_version == HK_ABI_VERSION_3_0 && config->install_context == HK_INSTALL_CONTEXT_EARLY_PROCESS);
    provider = false; *runtime = (hk_runtime_t *)(uintptr_t)1; return HK_STATUS_OK;
}
hk_status_t hk_runtime_create_with_backend_override(const hk_runtime_config_t *config, const char *id, hk_runtime_t **runtime) {
    assert(config->struct_version == HK_ABI_VERSION_3_0 && !strcmp(id, "ellekit"));
    assert(cell == prior); provider = true; overrides++; *runtime = (hk_runtime_t *)(uintptr_t)2; return HK_STATUS_OK;
}
hk_status_t hk_runtime_enumerate_backends(hk_runtime_t *runtime, hk_backend_enumerator_fn callback, void *context) {
    assert(runtime); enumerations++;
    hk_string_view_t builtin = {"HookKit", 7}, external = {"ellekit", 7};
    if (!callback(context, builtin, builtin)) return HK_STATUS_OK;
    if (mode != 7) callback(context, external, external);
    return HK_STATUS_OK;
}
hk_status_t hk_plan_create(hk_runtime_t *runtime, const hk_plan_config_t *config, hk_plan_t **plan) {
    assert(runtime && !config); phase = 0; resultReads = 0; *plan = (hk_plan_t *)(uintptr_t)3; return HK_STATUS_OK;
}
hk_status_t hk_plan_add_hook(hk_plan_t *plan, const hk_hook_spec_t *spec, hk_hook_t **hook) {
    assert(plan && spec->target_kind == HK_TARGET_FUNCTION_ADDRESS);
    assert(spec->target.address.address == (uintptr_t)&target && spec->replacement == (void *)&replacement);
    assert(spec->target.address.may_strip_pac_or_thumb_state);
    assert(spec->required_reach == HK_REACH_ENTRYPOINT && spec->preferred_reach == HK_REACH_ENTRYPOINT);
    assert(spec->original_requirement == HK_ORIGINAL_CALLABLE_CONTINUATION && spec->continuation_policy == HK_CONTINUATION_ANY);
    assert(spec->role == HK_OPERATION_MANDATORY);
    *hook = (hk_hook_t *)(uintptr_t)4; return HK_STATUS_OK;
}
hk_status_t hk_plan_analyze(hk_plan_t *plan, hk_report_t **report) { assert(plan && !report); phase = 1; return HK_STATUS_OK; }
hk_status_t hk_plan_prepare(hk_plan_t *plan, hk_report_t **report) {
    assert(plan && !report && cell == prior); phase = 2;
    return !provider && (mode == 1 || mode == 7) ? HK_STATUS_UNAVAILABLE : HK_STATUS_OK;
}
hk_status_t hk_hook_copy_result(const hk_hook_t *hook, hk_hook_result_t *result) {
    assert(hook); memset(result, 0, sizeof(*result));
    if (!provider && mode == 11 && phase == 1 && resultReads++ == 0) return HK_STATUS_UNAVAILABLE;
    result->outcome = phase == 1 ? HK_OUTCOME_ANALYZED : HK_OUTCOME_PREPARED;
    result->mutation = HK_MUTATION_NONE;
    if (phase == 2 && mode == 6) result->continuation.address = (uintptr_t)&real;
    if (phase == 3) {
        if (!provider && mode == 8) return HK_STATUS_UNAVAILABLE;
        bool failed = !provider && mode >= 2 && mode <= 4;
        result->outcome = failed ? HK_OUTCOME_FAILED_SAFE : HK_OUTCOME_ACTIVE;
        result->mutation = !failed ? HK_MUTATION_COMPLETE : mode == 2 ? HK_MUTATION_NONE : mode == 3 ? HK_MUTATION_PARTIAL : HK_MUTATION_UNKNOWN;
        result->achieved_reach = failed ? 0 : HK_REACH_ENTRYPOINT;
    }
    return HK_STATUS_OK;
}
const hk_original_slot_t *hk_hook_original_slot(const hk_hook_t *hook) { return (const hk_original_slot_t *)hook; }
void *hk_original_slot_load(const hk_original_slot_t *slot) {
    assert(slot);
    if (!provider && mode == 9) return (void *)&target;
    if (!provider && mode == 10) return (void *)&replacement;
    return !provider && (mode == 5 || mode == 6) ? NULL : (void *)&real;
}
hk_status_t hk_plan_commit(hk_plan_t *plan, hk_report_t **report) {
    assert(plan && !report && cell == (void *)&real && ((int (*)(int))cell)(4) == 7);
    commits++; phase = 3;
    return !provider && mode >= 2 && mode <= 4 ? HK_STATUS_UNAVAILABLE : HK_STATUS_OK;
}
void hk_plan_release(hk_plan_t *plan) { if (plan) plans++; }
void hk_runtime_release(hk_runtime_t *runtime) { if (runtime) runtimes++; }
int main(void) {
    for (mode = 0; mode <= 11; mode++) {
        phase = commits = plans = runtimes = overrides = enumerations = 0; provider = false;
        prior = cell = (void *)&earlier;
        bool active = SHDWLocalizationHookFunction("fixture", (void *)&target, (void *)&replacement, &cell);
        bool retry = mode == 1 || mode == 2 || mode == 5 || mode == 9 || mode == 10;
        assert(active == (mode == 0 || mode == 1 || mode == 2 || mode == 5 || mode == 6 || mode == 9 || mode == 10));
        assert(overrides == retry);
        assert((enumerations > 0) == (retry || mode == 7));
        assert(plans == 1 + retry && runtimes == 1 + retry);
        assert(cell == ((mode == 7 || mode == 11) ? prior : (void *)&real));
        assert(commits == (mode == 1 || mode == 5 || mode == 9 || mode == 10 ? 1 : mode == 7 || mode == 11 ? 0 : mode == 2 ? 2 : 1));
    }
    prior = cell = (void *)&earlier; int before = runtimes;
    assert(!SHDWLocalizationHookFunction(NULL, (void *)&target, (void *)&replacement, &cell));
    assert(!SHDWLocalizationHookFunction("", (void *)&target, (void *)&replacement, &cell));
    assert(!SHDWLocalizationHookFunction("fixture", NULL, (void *)&replacement, &cell));
    assert(!SHDWLocalizationHookFunction("fixture", (void *)&target, NULL, &cell));
    assert(!SHDWLocalizationHookFunction("fixture", (void *)&target, (void *)&replacement, NULL));
    assert(cell == prior && runtimes == before);
    puts("localization entrypoint hook passed: reach, prepared original, safe provider retry, partial/unknown fail-closed, lifetime");
}
'''
with tempfile.TemporaryDirectory(prefix="shadow-function-hook-") as directory:
    temp = Path(directory)
    source, binary = temp / "main.c", temp / "check"
    source.write_text(SOURCE)
    subprocess.run(["xcrun", "clang", "-x", "c", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", include, "-I", str(ROOT / "src/Localization"),
                    str(source), str(ROOT / "src/Localization/FunctionHook.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
