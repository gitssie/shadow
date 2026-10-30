#!/usr/bin/env python3
"""Check exact package pins against installed framework version metadata, not ABI."""
import argparse
import plistlib
import re
import sys
from pathlib import Path


def check(control, framework):
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
        return "HookKit version metadata check skipped: package dependency is not exact"
    package_version = relation[2]
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
    parser.add_argument("framework", help="resolved installed HookKit.framework")
    args = parser.parse_args()
    try:
        print(check(args.control, args.framework))
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        print("HookKit version check failed: " + str(error) + ". Build the matching HookKit version locally and run 'make install-theos' using the same THEOS and lane before rebuilding Shadow. This version check does not establish ABI compatibility.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
