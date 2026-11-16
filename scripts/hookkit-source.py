#!/usr/bin/env python3
"""Read the maintained HookKit pin and verify its installed build receipt."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "ShadowBuild.json"


def pins(root=ROOT):
    workflow = (root / ".github/workflows/build.yml").read_text()
    values = {}
    for key, pattern in (("HOOKKIT", r"[0-9a-f]{40}"),
                         ("HOOKKIT_REPOSITORY", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")):
        matches = re.findall(r"^  " + key + r":[ \t]*(\S+)[ \t]*$", workflow, re.MULTILINE)
        if len(matches) != 1 or not re.fullmatch(pattern, matches[0]):
            raise ValueError("workflow must declare one valid " + key)
        values[key] = matches[0]
    return values


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def version_module(root):
    spec = importlib.util.spec_from_file_location("shadow_hookkit_version", root / "scripts/check-hookkit-version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_receipt(framework, root=ROOT):
    selected = pins(root)
    control = root / "packaging/controls/control.rootless.in"
    guard = version_module(root)
    package_version = guard.exact_package_version(control)
    if package_version is None:
        raise ValueError("rootless HookKit dependency must be exact")
    guard.check(control, framework=framework)
    return {
        "schemaVersion": 1,
        "repository": selected["HOOKKIT_REPOSITORY"],
        "sourceRevision": selected["HOOKKIT"],
        "packageVersion": package_version,
        "lane": "rootless",
        "frameworkSHA256": digest(Path(framework) / "HookKit"),
        "adapterSHA256": digest(root / ".github/patches/hookkit-upstream-theos.patch"),
    }


def record(framework, source, root=ROOT):
    framework, source = Path(framework), Path(source)
    expected = expected_receipt(framework, root)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != expected["sourceRevision"]:
        raise ValueError("HookKit source revision does not match the workflow pin")
    version_module(root).check(root / "packaging/controls/control.rootless.in",
                              source_control=source / "packaging/layout/DEBIAN/control")
    package = source / ".theos/release/hookkit-rootless.deb"
    packaged_version = subprocess.check_output(["dpkg-deb", "-f", str(package), "Version"], text=True).strip()
    if packaged_version != expected["packageVersion"]:
        raise ValueError("HookKit built package version does not match the rootless dependency")
    payload = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(package)])
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        members = [item for item in archive.getmembers()
                   if item.name.lstrip("./") == "var/jb/Library/Frameworks/HookKit.framework/HookKit"]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError("HookKit package has no unique rootless framework binary")
        packaged = hashlib.sha256(archive.extractfile(members[0]).read()).hexdigest()
    if packaged != expected["frameworkSHA256"]:
        raise ValueError("installed HookKit differs from the source checkout's built package")
    descriptor, temporary = tempfile.mkstemp(prefix=".shadow-build-", dir=framework)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(expected, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, framework / RECEIPT)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return expected


def check(framework, root=ROOT):
    expected = expected_receipt(framework, root)
    actual = json.loads((Path(framework) / RECEIPT).read_text())
    if not isinstance(actual, dict):
        raise ValueError("HookKit receipt is not an object")
    for key, value in expected.items():
        if actual.get(key) != value:
            raise ValueError("HookKit receipt mismatch: " + key)
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("pin")
    subcommands.add_parser("repository")
    checker = subcommands.add_parser("check")
    checker.add_argument("framework", type=Path)
    recorder = subcommands.add_parser("record")
    recorder.add_argument("framework", type=Path)
    recorder.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        if args.command in ("pin", "repository"):
            print(pins()["HOOKKIT" if args.command == "pin" else "HOOKKIT_REPOSITORY"])
        else:
            value = record(args.framework, args.source) if args.command == "record" else check(args.framework)
            print("HookKit rootless source receipt matches " + value["repository"] + "@" + value["sourceRevision"])
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print("HookKit source check failed: " + str(error) +
              ". Run .github/scripts/install-hookkit-theos.sh rootless using the same THEOS before rebuilding Shadow.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
