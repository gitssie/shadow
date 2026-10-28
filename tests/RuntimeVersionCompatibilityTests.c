#include <dlfcn.h>
#include <stdio.h>
#include <stdint.h>
#include <unistd.h>

extern int32_t NSVersionOfRunTimeLibrary(const char *);

int main(void) {
    if (chdir("/") != 0) return 3;
    void *framework = dlopen("/System/Library/Frameworks/CloudKit.framework/CloudKit", RTLD_NOW | RTLD_LOCAL);
    if (!framework) return 2;
    puts("calling direct runtime version query");
    fflush(stdout);
    int32_t direct = NSVersionOfRunTimeLibrary("CloudKit");
    printf("direct runtime version query returned: %d\n", direct);
    if (direct < 0) return 4;
    fflush(stdout);
    int32_t (*version)(const char *) = (int32_t (*)(const char *))dlsym(RTLD_DEFAULT, "NSVersionOfRunTimeLibrary");
    if (!version) {
        fprintf(stderr, "runtime version entry unavailable: %s\n", dlerror());
        return 1;
    }
    puts("calling runtime version query");
    fflush(stdout);
    int32_t result = version("CloudKit");
    printf("runtime version query returned: %d\n", result);
    if (result != direct) return 5;
    dlclose(framework);
    puts("runtime version compatibility passed");
    return 0;
}
