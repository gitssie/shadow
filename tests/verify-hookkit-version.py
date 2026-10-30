#!/usr/bin/env python3
"""Exercise the production version guard with isolated binary/XML plist fixtures."""
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
script = root / "scripts/check-hookkit-version.py"
with tempfile.TemporaryDirectory(prefix="shadow-hookkit-version-") as temporary:
    base = Path(temporary)
    framework = base / "HookKit.framework"
    framework.mkdir()
    control = base / "control.in"
    control.write_text("Depends: firmware (>= 15.0),\n me.jjolano.fmwk.hookkit (= 3.0.6-1)\n")

    def run(success, message=None):
        result = subprocess.run([sys.executable, str(script), str(control), str(framework)], capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        if message:
            assert message in result.stdout + result.stderr, result.stdout + result.stderr
        if not success:
            assert "make install-theos" in result.stderr and "ABI" in result.stderr

    def metadata(value, fmt=plistlib.FMT_BINARY):
        (framework / "Info.plist").write_bytes(plistlib.dumps(value, fmt=fmt))

    run(False, "Info.plist")
    metadata({"CFBundleShortVersionString": "3.0.4", "CFBundleVersion": "3.0.4"})
    run(False, "expected '3.0.6'")
    metadata({"CFBundleShortVersionString": "3.0.6", "CFBundleVersion": "3.0.6"})
    run(True, "3.0.6-1")
    metadata({"CFBundleShortVersionString": "3.0.6", "CFBundleVersion": "3.0.6"}, plistlib.FMT_XML)
    run(True)
    for value in ({}, {"CFBundleShortVersionString": "3.0.6"},
                  {"CFBundleShortVersionString": "3.0.6", "CFBundleVersion": 306},
                  {"CFBundleShortVersionString": "3.0.6", "CFBundleVersion": "3.0.4"},
                  {"CFBundleShortVersionString": " 3.0.6", "CFBundleVersion": "3.0.6"}, []):
        metadata(value)
        run(False)
    (framework / "Info.plist").write_bytes(b"broken plist")
    run(False)
    # Other lanes keep their existing >= dependency policy and need no plist.
    (framework / "Info.plist").unlink()
    for lane in ("rootful-legacy", "rootful-modern", "roothide"):
        control.write_bytes((root / "packaging/controls" / ("control." + lane + ".in")).read_bytes())
        run(True, "not exact")
    for requirement in ("=", "= invalid", "= 3.0.6) , me.jjolano.fmwk.hookkit (= 3.0.6"):
        control.write_text("Depends: me.jjolano.fmwk.hookkit (" + requirement + ")\n")
        run(False)

build = (root / "build.sh").read_text()
assert build.index('python3 "$ROOT/scripts/check-hookkit-version.py"') > build.index('local hookkit_theos=')
assert build.index('python3 "$ROOT/scripts/check-hookkit-version.py"') < build.index('rm -rf "$LIBRARY_PATH"')
print("HookKit version guard: exact Debian pin, stale/missing/malformed framework metadata, binary/XML plist and unchanged range lanes passed")
