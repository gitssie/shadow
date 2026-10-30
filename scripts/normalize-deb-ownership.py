#!/usr/bin/env python3
"""Normalize numeric Debian archive owners without extracting or altering payloads."""
import gzip
import io
import lzma
import os
import pathlib
import sys
import tarfile
import tempfile


def normalize(package):
    package = pathlib.Path(package)
    if package.is_symlink() or not package.is_file():
        raise ValueError("Package must be a regular file")
    archive = package.read_bytes()
    if not archive.startswith(b"!<arch>\n"):
        raise ValueError("Invalid ar archive")
    offset, entries = 8, []
    while offset < len(archive):
        header = archive[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b"`\n":
            raise ValueError("Invalid ar header")
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58].decode("ascii"))
        offset += 60
        if size < 0 or offset + size > len(archive):
            raise ValueError("Invalid ar member size")
        entries.append((name, archive[offset:offset + size]))
        offset += size + size % 2
    names = [name for name, _ in entries]
    if (len(names) != 3 or names[0] != "debian-binary"
            or not names[1].startswith("control.tar") or not names[2].startswith("data.tar")):
        raise ValueError("Unexpected Debian archive members")
    members = []
    for name, raw in entries:
        if name.endswith((".gz", ".xz", ".lzma")) or name.endswith(".tar"):
            output = io.BytesIO()
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as source:
                with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as dest:
                    for member in source:
                        member.uid = member.gid = 0
                        member.uname, member.gname = "root", "wheel"
                        for key in ("uid", "gid", "uname", "gname"):
                            member.pax_headers.pop(key, None)
                        dest.addfile(member, source.extractfile(member) if member.isfile() else None)
            plain = output.getvalue()
            if name.endswith(".gz"):
                raw = gzip.compress(plain, compresslevel=9, mtime=0)
            elif name.endswith(".xz"):
                raw = lzma.compress(plain, format=lzma.FORMAT_XZ)
            elif name.endswith(".lzma"):
                raw = lzma.compress(plain, format=lzma.FORMAT_ALONE)
            else:
                raw = plain
        elif name != "debian-binary":
            raise ValueError("Unsupported archive compression")
        members.append((name, raw))
    descriptor, temp = tempfile.mkstemp(prefix=".ownership-", dir=package.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(b"!<arch>\n")
            for name, raw in members:
                header = f"{name:<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(raw):<10}`\n"
                if len(header) != 60:
                    raise ValueError("Unsupported ar member header")
                output.write(header.encode("ascii"))
                output.write(raw)
                if len(raw) % 2:
                    output.write(b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, package)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


if __name__ == "__main__":
    normalize(sys.argv[1])
