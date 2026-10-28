#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <stdbool.h>
#include <stdlib.h>
#include <objc/runtime.h>

int main(int argc, char **argv) {
    void *image = dlopen("/usr/lib/libobjc-trampolines.dylib", RTLD_NOW | RTLD_LOCAL | RTLD_FIRST);
    if (!image) {
        fprintf(stderr, "runtime image load failed: %s\n", dlerror());
        return 1;
    }
    const char *names[] = {"_objc_blockTrampolineImpl", "_objc_blockTrampolineStart"};
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        void *address = dlsym(image, names[i]);
        if (!address) {
            fprintf(stderr, "runtime symbol lookup failed: %s: %s\n", names[i], dlerror());
            return 2;
        }
        Dl_info info = {0};
        if (!dladdr(address, &info) || !info.dli_fname) {
            fprintf(stderr, "runtime image attribution failed: %s\n", names[i]);
            return 3;
        }
    }
    if (argc == 2 && access(argv[1], F_OK) == 0) {
        fprintf(stderr, "restricted path became accessible\n");
        return 4;
    }
    Class objectClass = objc_getClass("NSObject");
    const char *classImage = objectClass ? class_getImageName(objectClass) : NULL;
    if (!classImage) return 7;
    unsigned int classCount = 0;
    const char **classes = objc_copyClassNamesForImage(classImage, &classCount);
    bool found = false;
    for (unsigned int i = 0; classes && i < classCount; i++) {
        if (strcmp(classes[i], "NSObject") == 0) found = true;
    }
    free(classes);
    if (!found) return 8;
    IMP implementation = imp_implementationWithBlock(^int(id receiver) {
        (void)receiver;
        return 42;
    });
    if (!implementation || ((int (*)(id, SEL))implementation)(nil, NULL) != 42) {
        fprintf(stderr, "block implementation execution failed\n");
        return 5;
    }
    if (!imp_removeBlock(implementation)) {
        fprintf(stderr, "block implementation removal failed\n");
        return 6;
    }
    dlclose(image);
    puts("runtime image compatibility: symbol lookup, image attribution, ObjC image lookup and block implementation passed");
    return 0;
}
