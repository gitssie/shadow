#!/usr/bin/env python3
"""Validate the optional iOS transport library before staging it."""
import argparse
from pathlib import Path
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("library", type=Path)
parser.add_argument("--quiet", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
floor = subprocess.check_output(["bash", "-c", '. "$1"; shadow_lane_field rootless FLOOR',
                                 "bash", str(root / "build-support/lanes.sh")], text=True).strip()
parts = [int(value) for value in floor.split(".")]
maximum = sum(value << shift for value, shift in zip((parts + [0, 0])[:3], (16, 8, 0)))

def require(condition, message):
    if not condition:
        raise SystemExit(message)

data = args.library.read_bytes()
require(len(data) >= 8 and data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"),
        "curl transport must include both arm64 and arm64e slices")
count = struct.unpack_from(">I", data, 4)[0]
require(count == 2, "curl transport must contain exactly two iOS slices")
fat64 = data[:4] == b"\xca\xfe\xba\xbf"
architectures = set()
for index in range(count):
    record = 8 + index * (32 if fat64 else 20)
    cpu, subtype, offset, length = struct.unpack_from(">IIQQ" if fat64 else ">IIII", data, record)
    require(offset + length <= len(data) and length >= 32, "invalid curl slice bounds")
    magic, inner_cpu, inner_subtype, filetype, commands, command_bytes = struct.unpack_from("<6I", data, offset)
    require(magic == 0xfeedfacf and cpu == inner_cpu == 0x100000c and filetype == 6, "invalid iOS curl dylib")
    require((subtype & 0xffffff) == (inner_subtype & 0xffffff), "inconsistent curl architecture")
    if inner_subtype == 0:
        architecture = "arm64"
    else:
        require(inner_subtype == 0x80000002, "curl arm64e requires the modern pointer-authentication ABI")
        architecture = "arm64e"
    require(architecture not in architectures, "duplicate curl architecture")
    architectures.add(architecture)
    cursor = offset + 32
    require(cursor + command_bytes <= offset + length, "invalid curl load commands")
    deployment = identity = None
    for _ in range(commands):
        command, size = struct.unpack_from("<II", data, cursor)
        require(size >= 8 and cursor + size <= offset + 32 + command_bytes, "invalid curl load command")
        if command == 0x32:
            platform, deployment = struct.unpack_from("<II", data, cursor + 8)
            require(platform == 2, "curl slice must target iOS devices")
        elif command == 0x25:
            deployment = struct.unpack_from("<I", data, cursor + 8)[0]
        elif command == 0xd:
            start = cursor + struct.unpack_from("<I", data, cursor + 8)[0]
            require(start < cursor + size, "invalid curl install name")
            identity = data[start:cursor + size].split(b"\0", 1)[0]
        cursor += size
    require(deployment is not None and deployment <= maximum, "curl minimum iOS exceeds the rootless floor")
    require(identity == b"@loader_path/libcurl-impersonate.4.dylib", "unexpected curl install name")
require(architectures == {"arm64", "arm64e"}, "missing curl architecture")
if not args.quiet:
    print("curl transport: arm64 + modern arm64e, iOS deployment targets and install names passed")
