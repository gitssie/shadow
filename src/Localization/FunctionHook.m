#include "FunctionHook.h"
#include <HookKit/HookKitRuntime.h>
#include <HookKit/HookKitPlan.h>
#include <string.h>

typedef struct {
    const char *ids[4];
    size_t count;
} ProviderList;

static bool DiscoverProvider(void *context, hk_string_view_t identifier,
                             hk_string_view_t displayName) {
    (void)displayName;
    ProviderList *providers = context;
    static const char *const supported[] = {"ellekit", "gum", "substitute", "dobby"};
    for (size_t i = 0; i < sizeof(supported) / sizeof(supported[0]); i++) {
        if (!identifier.data || identifier.length != strlen(supported[i]) ||
            memcmp(identifier.data, supported[i], identifier.length)) continue;
        for (size_t j = 0; j < providers->count; j++) {
            if (providers->ids[j] == supported[i]) return true;
        }
        if (providers->count < sizeof(providers->ids) / sizeof(providers->ids[0]))
            providers->ids[providers->count++] = supported[i];
        break;
    }
    return true;
}

static bool Install(hk_runtime_t *runtime, const hk_hook_spec_t *spec,
                     void **original, bool *safeToRetry) {
    hk_plan_t *plan = NULL;
    hk_hook_t *hook = NULL;
    hk_hook_result_t result;
    bool active = false;
    bool published = false;
    bool unreadable = false;
    void *previous = __atomic_load_n(original, __ATOMIC_ACQUIRE);
    *safeToRetry = false;
    if (hk_plan_create(runtime, NULL, &plan) != HK_STATUS_OK || !plan ||
        hk_plan_add_hook(plan, spec, &hook) != HK_STATUS_OK || !hook) goto done;
    if (hk_plan_analyze(plan, NULL) != HK_STATUS_OK) goto done;
    if (hk_hook_copy_result(hook, &result) != HK_STATUS_OK) { unreadable = true; goto done; }
    if (result.outcome != HK_OUTCOME_ANALYZED) goto done;
    if (hk_plan_prepare(plan, NULL) != HK_STATUS_OK) goto done;
    if (hk_hook_copy_result(hook, &result) != HK_STATUS_OK) { unreadable = true; goto done; }
    if (result.outcome != HK_OUTCOME_PREPARED) goto done;
    void *continuation;
    continuation = hk_original_slot_load(hk_hook_original_slot(hook));
    if (!continuation) continuation = (void *)result.continuation.address;
    if (!continuation || continuation == spec->replacement || continuation == (void *)spec->target.address.address) goto done;
    __atomic_store_n(original, continuation, __ATOMIC_RELEASE);
    published = true;
    hk_status_t status;
    status = hk_plan_commit(plan, NULL);
    if (hk_hook_copy_result(hook, &result) == HK_STATUS_OK) {
        active = status == HK_STATUS_OK && result.outcome == HK_OUTCOME_ACTIVE &&
            (result.achieved_reach & HK_REACH_ENTRYPOINT);
    } else unreadable = true;
done:
    if (!unreadable && hook && hk_hook_copy_result(hook, &result) == HK_STATUS_OK) {
        *safeToRetry = !active && result.mutation == HK_MUTATION_NONE &&
            result.outcome != HK_OUTCOME_FAILED_PARTIAL && result.outcome != HK_OUTCOME_FAILED_UNKNOWN;
        if (*safeToRetry && published) __atomic_store_n(original, previous, __ATOMIC_RELEASE);
    }
    // Wrapper release preserves installed hooks and their callable continuations.
    hk_plan_release(plan);
    return active;
}

bool SHDWLocalizationHookFunction(const char *symbol, void *target,
                                  void *replacement, void **original) {
    if (!symbol || !*symbol || !target || !replacement || target == replacement || !original) return false;
    hk_runtime_config_t config = {0};
    config.struct_size = sizeof(config);
    config.struct_version = HK_ABI_VERSION_3_0;
    config.install_context = HK_INSTALL_CONTEXT_EARLY_PROCESS;
    hk_hook_spec_t spec = {0};
    spec.struct_size = sizeof(spec);
    spec.struct_version = HK_ABI_VERSION_3_0;
    spec.stable_hook_id = symbol;
    spec.target_kind = HK_TARGET_FUNCTION_ADDRESS;
    spec.target.address.struct_size = sizeof(spec.target.address);
    spec.target.address.struct_version = HK_ABI_VERSION_3_0;
    spec.target.address.address = (uintptr_t)target;
    spec.replacement = replacement;
    spec.required_reach = HK_REACH_ENTRYPOINT;
    spec.preferred_reach = HK_REACH_ENTRYPOINT;
    spec.original_requirement = HK_ORIGINAL_CALLABLE_CONTINUATION;
    spec.continuation_policy = HK_CONTINUATION_ANY;
    spec.availability = HK_AVAILABILITY_REQUIRED_NOW;
    spec.role = HK_OPERATION_MANDATORY;

    hk_runtime_t *runtime = NULL;
    if (hk_runtime_create(&config, &runtime) != HK_STATUS_OK || !runtime) {
        hk_runtime_release(runtime);
        return false;
    }
    bool safeToRetry = false;
    bool active = Install(runtime, &spec, original, &safeToRetry);
    ProviderList providers = {0};
    if (safeToRetry && hk_runtime_enumerate_backends(runtime, DiscoverProvider, &providers) != HK_STATUS_OK)
        providers.count = 0;
    hk_runtime_release(runtime);
    for (size_t index = 0; !active && safeToRetry && index < providers.count; index++) {
        runtime = NULL;
        if (hk_runtime_create_with_backend_override(&config, providers.ids[index], &runtime) != HK_STATUS_OK || !runtime) {
            hk_runtime_release(runtime);
            break;
        }
        active = Install(runtime, &spec, original, &safeToRetry);
        hk_runtime_release(runtime);
    }
    return active;
}
