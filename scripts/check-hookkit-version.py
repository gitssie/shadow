#!/usr/bin/env python3
"""Check exact package pins against installed framework version metadata, not ABI."""
import argparse
import plistlib
import re
import sys
from pathlib import Path


def exact_package_version(control):
    text = Path(control).read_text(encoding="utf-8")
    text = re.sub(r"\n[ \t]+", " ", text)
    depends = re.search(r"^Depends:\s*(.*)$", text, re.MULTILINE)
    if not depends:
        raise ValueError("control template has no Depends field")
    requirements = re.findall(r"(?<![\w.-])me\.jjolano\.fmwk\.hookkit(?:\.legacy)?\s*\(([^)]+)\)", depends.group(1))
    if len(requirements) != 1:
        raise ValueError("control template must declare one HookKit version requirement")
    relation = re.fullmatch(r"(>=|<=|>>|<<|=)\s+([0-9][A-Za-z0-9.+:~\-]*)", requirements[0].strip())
    if not relation:
        raise ValueError("malformed HookKit version requirement")
    if relation[1] != "=":
        return None
    return relation[2]


def check(control, framework=None, source_control=None):
    package_version = exact_package_version(control)
    if package_version is None:
        return "HookKit version metadata check skipped: package dependency is not exact"
    if source_control is not None:
        source = Path(source_control).read_text(encoding="utf-8")
        versions = re.findall(r"^Version:[ \t]*(\S+)[ \t]*$", source, re.MULTILINE)
        if len(versions) != 1 or versions[0] != package_version:
            raise ValueError("HookKit source Debian Version does not match required " + package_version + "; refusing to overwrite the Theos installation")
        return "HookKit source version matches exact package dependency " + package_version + " (before installation; ABI checks remain separate)"
    expected = package_version.rsplit("-", 1)[0] if "-" in package_version else package_version
    with (Path(framework) / "Info.plist").open("rb") as stream:
        metadata = plistlib.load(stream)
    if not isinstance(metadata, dict):
        raise ValueError("HookKit Info.plist is not a dictionary")
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        actual = metadata.get(key)
        if not isinstance(actual, str) or not actual or actual != actual.strip():
            raise ValueError("missing or malformed HookKit " + key)
        if actual != expected:
            raise ValueError("HookKit " + key + " is " + repr(actual) + "; expected " + repr(expected) + " for package " + package_version)
    return "HookKit installed version matches exact package dependency " + package_version + " (metadata check only; ABI checks remain separate)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("control", help="lane control template")
    parser.add_argument("framework", nargs="?", help="resolved installed HookKit.framework")
    parser.add_argument("--source-control", help="HookKit source Debian control to validate before installation")
    args = parser.parse_args()
    if bool(args.framework) == bool(args.source_control):
        parser.error("provide either an installed framework or --source-control")
    try:
        print(check(args.control, args.framework, args.source_control))
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        print("HookKit version check failed: " + str(error) + ". Build the matching HookKit version locally and run 'make install-theos' using the same THEOS and lane before rebuilding Shadow. This version check does not establish ABI compatibility.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
