#!/usr/bin/env python3
"""Check maintained HookKit source receipts with isolated source/package fixtures."""
import gzip
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hookkit_source", root / "scripts/hookkit-source.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def rejects(function, *args, contains=None):
    try:
        function(*args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if contains:
            assert contains in str(error), str(error)
    else:
        raise AssertionError("unexpectedly accepted invalid source receipt")


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as output:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            output.addfile(info, io.BytesIO(content))
    return gzip.compress(buffer.getvalue())


def package(path, binary):
    payload = archive([("./var/jb/Library/Frameworks/HookKit.framework/HookKit", binary)])
    control = archive([("./control", b"Package: me.jjolano.fmwk.hookkit\nVersion: 3.0.6-1\nArchitecture: iphoneos-arm64\nMaintainer: Test\nDescription: Test\n")])
    content = b"!<arch>\n"
    for name, data in (("debian-binary", b"2.0\n"), ("control.tar.gz", control), ("data.tar.gz", payload)):
        header = (name + "/").ljust(16) + "0".ljust(12) + "0".ljust(6) + "0".ljust(6) + "100644".ljust(8) + str(len(data)).ljust(10) + "`\n"
        content += header.encode() + data + (b"\n" if len(data) % 2 else b"")
    path.write_bytes(content)


with tempfile.TemporaryDirectory(prefix="shadow-hookkit-source-") as temporary:
    base = Path(temporary)
    project = base / "shadow"
    for directory in ("scripts", ".github/workflows", ".github/patches", "packaging/controls"):
        (project / directory).mkdir(parents=True)
    shutil.copy(root / "scripts/check-hookkit-version.py", project / "scripts")
    workflow = project / ".github/workflows/build.yml"
    adapter = project / ".github/patches/hookkit-upstream-theos.patch"
    adapter.write_text("test adapter\n")
    control = project / "packaging/controls/control.rootless.in"
    control.write_text("Depends: me.jjolano.fmwk.hookkit (= 3.0.6-1)\n")
    source = base / "HookKit"
    source.mkdir()
    source_control = source / "packaging/layout/DEBIAN/control"
    source_control.parent.mkdir(parents=True)
    source_control.write_text("Package: me.jjolano.fmwk.hookkit\nVersion: 3.0.6-1\n")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-q", "-m", "Fixture"], check=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    workflow.write_text("env:\n  HOOKKIT: " + revision + "\n  HOOKKIT_REPOSITORY: gitssie/HookKit\n")
    framework = base / "HookKit.framework"
    framework.mkdir()
    (framework / "HookKit").write_bytes(b"fixture HookKit binary")
    metadata = {"CFBundleShortVersionString": "3.0.6", "CFBundleVersion": "3.0.6"}
    (framework / "Info.plist").write_bytes(plistlib.dumps(metadata))
    artifact = source / ".theos/release/hookkit-rootless.deb"
    artifact.parent.mkdir(parents=True)
    package(artifact, (framework / "HookKit").read_bytes())

    assert module.pins(project) == {"HOOKKIT": revision, "HOOKKIT_REPOSITORY": "gitssie/HookKit"}
    rejects(module.check, framework, project)
    value = module.record(framework, source, project)
    assert value == module.check(framework, project)
    receipt = framework / module.RECEIPT
    original_receipt = receipt.read_bytes()

    for key, invalid in (("sourceRevision", "0" * 40), ("repository", "wrong/HookKit"),
                         ("lane", "rootful-modern"), ("schemaVersion", 2),
                         ("packageVersion", "3.0.5-1"), ("frameworkSHA256", "0" * 64),
                         ("adapterSHA256", "0" * 64)):
        altered = dict(value)
        altered[key] = invalid
        receipt.write_text(json.dumps(altered))
        rejects(module.check, framework, project, contains=key)
    receipt.write_bytes(original_receipt)
    (framework / "HookKit").write_bytes(b"same version but stale binary")
    rejects(module.check, framework, project, contains="frameworkSHA256")
    rejects(module.record, framework, source, project, contains="built package")
    assert receipt.read_bytes() == original_receipt
    (framework / "HookKit").write_bytes(b"fixture HookKit binary")
    adapter.write_text("changed adapter\n")
    rejects(module.check, framework, project, contains="adapterSHA256")
    adapter.write_text("test adapter\n")
    metadata["CFBundleVersion"] = "3.0.5"
    (framework / "Info.plist").write_bytes(plistlib.dumps(metadata))
    rejects(module.check, framework, project, contains="expected '3.0.6'")
    metadata["CFBundleVersion"] = "3.0.6"
    (framework / "Info.plist").write_bytes(plistlib.dumps(metadata))
    source_control.write_text("Version: 3.0.5-1\n")
    rejects(module.record, framework, source, project, contains="source Debian Version")
    source_control.write_text("Package: me.jjolano.fmwk.hookkit\nVersion: 3.0.6-1\n")

    valid_workflow = workflow.read_text()
    workflow.write_text(valid_workflow.replace(revision, "f" * 40))
    rejects(module.check, framework, project, contains="sourceRevision")
    rejects(module.record, framework, source, project, contains="source revision")
    for invalid_workflow in (valid_workflow.replace(revision, "short"),
                             valid_workflow + "  HOOKKIT: " + revision + "\n",
                             valid_workflow.replace("gitssie/HookKit", "https://example.com/HookKit"), "env:\n"):
        workflow.write_text(invalid_workflow)
        rejects(module.pins, project)
    workflow.write_text(valid_workflow)
    assert module.check(framework, project) == value
    receipt.write_text("not JSON")
    rejects(module.check, framework, project)
    receipt.write_text("[]")
    rejects(module.check, framework, project, contains="not an object")
    assert not list(framework.glob(".shadow-build-*"))

installer = root / ".github/scripts/install-hookkit-theos.sh"
for arguments in (["rootful-legacy"], ["rootful-modern"], ["all"], ["rootless", "extra"]):
    result = subprocess.run(["bash", str(installer)] + arguments, text=True, capture_output=True)
    assert result.returncode == 2 and "usage:" in result.stderr, result.stderr
print("HookKit source pairing: exact revision/package, installed binary, adapter receipt and refusal checks passed")
