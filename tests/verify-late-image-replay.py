"""Exercise production image-event replay scheduling with host doubles."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()


def function_body(signature):
    start = source.index("{", source.index(signature)) + 1
    depth, end = 1, start
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end - 1]


bulk = function_body("static void shdw_bulk_load_handler(")
bulk = bulk[:bulk.index("shdw_dyld_deliver_external(")]
single = function_body("void shdw_universal_dyld_updatelibs(")
single = single[single.rindex("    if(!_shdw_dyld_replay_in_progress) {"):]
single = single[:single.index("    shdw_dyld_deliver_external(")]
prefix = r"""
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#define SHADOW_INTERNAL_SCOPE for(int scope = 1; scope; scope = 0)
static int _shdw_dyld_bulk_registration_replay, _shdw_dyld_replay_in_progress;
static int _shdw_dyld_bulk_repair_available, shdw_detector_present;
static void *_shdw_dyld_rebind_session;
static unsigned repairs, prepared;
static void SHDWRebindRepairSlots(void) {}
static void shdw_universal_fingerprint_identity_prepare(void *s) {(void)s;}
static void shdw_universal_fingerprint_environment_prepare(void *s) {(void)s;}
static void shdw_universal_fingerprint_prepare(void *s) {(void)s; prepared++;}
static void SHDWRebindRepairImage(void *s, const void *h) {(void)s; assert(h); repairs++;}
static void SHDWRebindRepairImages(void *s, const void *h, unsigned n) {(void)s; assert(h); repairs += n;}
"""
main = r"""
int main(void) {
    for(int detector = 0; detector < 2; detector++)
    for(int replay = 0; replay < 2; replay++) {
        shdw_detector_present = detector;
        _shdw_dyld_replay_in_progress = replay;
        for(int bulk = 0; bulk < 2; bulk++) {
            _shdw_dyld_bulk_repair_available = bulk;
            repairs = prepared = 0;
            single_event((void *)1);
            assert(repairs == (unsigned)(!bulk && !replay));
            assert(prepared == (unsigned)(detector && !bulk && !replay));
        }
        for(int registration = 0; registration < 2; registration++) {
            _shdw_dyld_bulk_registration_replay = registration;
            repairs = prepared = 0;
            bulk_event(2, (void *)1);
            assert(repairs == (unsigned)(registration || replay ? 0 : 2));
            assert(prepared == (unsigned)(!registration && !replay && detector));
        }
    }
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="shadow-image-replay-") as tmp:
    path = Path(tmp)
    (path / "test.c").write_text(prefix + "\nstatic void bulk_event(unsigned imageCount, const void *mhs) {" + bulk + "}\nstatic void single_event(const void *mh) {" + single + "}\n" + main)
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", str(path / "test.c"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
print("late-image replay scheduling: PASS")
