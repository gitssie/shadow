#ifndef shdw_universal_hooks_h
#define shdw_universal_hooks_h

#import "../HookAdapterBridge.h"
#import "hooks.h"

void shdw_universal_dyld(SHDWHookSession *hooks);
void shdw_universal_filesystem_c(SHDWHookSession *hooks);
void shdw_universal_url_resources(SHDWHookSession *hooks);
void shdw_universal_file_attributes(SHDWHookSession *hooks);
void shdw_fingerprint_sysctl_value(const char *name, void *value, size_t length, const void *caller);
struct utsname;
void shdw_fingerprint_uname_value(struct utsname *value, const void *caller);
BOOL shdw_fingerprint_sysctl_query(const char *name, void *value, size_t *length,
    void *newp, size_t newlen, const void *caller, int *result);
BOOL shdw_fingerprint_sysctl_mib_query(const int *mib, u_int count, void *value, size_t *length,
    void *newp, size_t newlen, const void *caller, int *result);
void shdw_universal_fingerprint(SHDWHookSession *hooks);
void shdw_universal_fingerprint_identity(SHDWHookSession *hooks, NSString *bundleID);
void shdw_universal_fingerprint_identity_prepare(SHDWHookSession *hooks);
void shdw_universal_fingerprint_receipts(SHDWHookSession *hooks);
void shdw_universal_fingerprint_receipts_prepare(SHDWHookSession *hooks);
void shdw_universal_fingerprint_interfaces(SHDWHookSession *hooks);
NSString *shdw_fingerprint_bundle_identifier_for_caller(const void *caller);
void shdw_universal_fingerprint_prepare(SHDWHookSession *hooks);
BOOL shdw_fingerprint_is_enabled(void);
BOOL shdw_fingerprint_app_caller(const void *caller);
void shdw_universal_fingerprint_webkit_prepare(SHDWHookSession *hooks);
void shdw_universal_fingerprint_system_version_prepare(SHDWHookSession *hooks);
void shdw_universal_fingerprint_environment_prepare(SHDWHookSession *hooks);
void *shdw_sym_policy_lookup_system_version(const char *name);
void shdw_universal_network_queries(SHDWHookSession *hooks);
void shdw_universal_envvars_c(SHDWHookSession *hooks);
void shdw_universal_envpolicy(SHDWHookSession *hooks);
void shdw_universal_nsprocessinfo(SHDWHookSession *hooks);
void shdw_universal_passcode_status(SHDWHookSession *hooks);
void shdw_universal_mach_bootstrap(SHDWHookSession *hooks);
void shdw_universal_iokit(SHDWHookSession *hooks);
void shdw_universal_low_level_c(SHDWHookSession *hooks);
void shdw_universal_antidebugging(SHDWHookSession *hooks);
void shdw_universal_codesigning(SHDWHookSession *hooks);
void shdw_universal_objc(SHDWHookSession *hooks);
void shdw_universal_objc_methodimpl(SHDWHookSession *hooks);
void shdw_universal_objc_methodimpl_detector(SHDWHookSession *hooks);
void shdw_universal_syscall(SHDWHookSession *hooks);
void shdw_universal_memory(SHDWHookSession *hooks);
void shdw_universal_sandbox(SHDWHookSession *hooks);
// Rewrite suspicious LC_LOAD_DYLIB names in the main executable's load commands
// (e.g. a link-time @rpath/Shadow.framework/Shadow) so a raw memory walk of the
// Mach-O header reads nothing suspicious. Injected Shadow adds no load command.
void shdw_hide_main_image_loadcmd_names(void);
void shdw_universal_hide_classes(SHDWHookSession *hooks);
void shdw_universal_symlookup(SHDWHookSession *hooks);
void shdw_universal_symaddrlookup(SHDWHookSession *hooks);
void shdw_universal_dynamic_libraries_extra(SHDWHookSession *hooks);
void shdw_universal_import_slot_protection(SHDWHookSession *hooks);
void shdw_universal_filesystem_objc(SHDWHookSession *hooks);
void shdw_universal_foundation_objc(SHDWHookSession *hooks);
void shdw_universal_hide_apps(SHDWHookSession *hooks);
void shdw_universal_url_scheme(SHDWHookSession *hooks);
void shdw_universal_foundation_uikit(SHDWHookSession *hooks);
void shdw_universal_nsarray(SHDWHookSession *hooks);
void shdw_universal_nsdictionary(SHDWHookSession *hooks);
void shdw_universal_nsdata(SHDWHookSession *hooks);
void shdw_universal_nsbundle(SHDWHookSession *hooks);
void shdw_universal_nsfilehandle(SHDWHookSession *hooks);
void shdw_universal_nsfileversion(SHDWHookSession *hooks);
void shdw_universal_nsfilewrapper(SHDWHookSession *hooks);
void shdw_universal_nsstring(SHDWHookSession *hooks);
void shdw_universal_nsurl(SHDWHookSession *hooks);
void shdw_universal_nsthread(SHDWHookSession *hooks);
void shdw_universal_nstask(SHDWHookSession *hooks);
void shdw_universal_user_defaults(SHDWHookSession *hooks);

void shdw_universal_rebind_image(SHDWHookSession *hooks,
                                 const void *imageHeader);
void shdw_universal_antidebugging_rebind_image(SHDWHookSession *hooks,
                                               const void *imageHeader);
// Image-scoped ObjC-introspection rebinds for late-loaded detector frameworks.
void shdw_universal_objc_rebind_image(SHDWHookSession *hooks,
                                      const void *imageHeader);
void shdw_universal_objc_methodimpl_rebind_image(SHDWHookSession *hooks,
                                                 const void *imageHeader);
void shdw_universal_feature_filesystem_metadata(SHDWHookSession *hooks);
void shdw_universal_feature_symbolic_links(SHDWHookSession *hooks);
void shdw_universal_feature_launchservices_url_filtering(
    SHDWHookSession *hooks);
void *shdw_universal_file_exists_original(void);
void *shdw_universal_file_exists_replacement(void);
void *shdw_universal_readable_file_original(void);

#endif
