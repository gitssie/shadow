#!/usr/bin/env python3
"""Check final .deb numeric ownership without extraction or package tools."""
import gzip
import io
import lzma
from pathlib import Path
import runpy
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = bytes(range(256)) * 17
STAMP = 1700000000.125


def archive():
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, kind, mode, link in (("usr/libexec", tarfile.DIRTYPE, 0o755, ""),
                                        ("usr/libexec/helper", tarfile.REGTYPE, 0o4755, ""),
                                        ("usr/bin/helper", tarfile.SYMTYPE, 0o777, "../libexec/helper"),
                                        ("usr/libexec/helper-hard", tarfile.LNKTYPE, 0o4755, "usr/libexec/helper")):
            item = tarfile.TarInfo(name)
            item.type, item.mode, item.linkname = kind, mode, link
            item.uid, item.gid = 501, 20
            item.uname, item.gname = "root", "wheel"
            item.mtime = STAMP
            item.pax_headers = {"uid": "1234", "gid": "5678", "uname": "original", "gname": "original-group", "SHADOW.test": "unknown metadata retained", "SCHILY.xattr.user.test": "fixture"}
            item.size = len(PAYLOAD) if item.isfile() else 0
            tar.addfile(item, io.BytesIO(PAYLOAD) if item.isfile() else None)
    return output.getvalue()


def ar(entries):
    output = bytearray(b"!<arch>\n")
    for name, data in entries:
        header = f"{name:<16}{0:<12}{501:<6}{20:<6}{'100644':<8}{len(data):<10}`\n".encode("ascii")
        assert len(header) == 60
        output.extend(header + data)
        if len(data) % 2:
            output.extend(b"\n")
    return bytes(output)


def read_ar(data):
    assert data.startswith(b"!<arch>\n")
    offset, entries = 8, []
    while offset < len(data):
        header = data[offset:offset+60]
        size = int(header[48:58])
        entries.append((header[:16].decode().strip(), data[offset+60:offset+60+size]))
        assert int(header[28:34]) == int(header[34:40]) == 0
        offset += 60 + size + size % 2
    assert offset == len(data)
    return entries


def inventory(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as tar:
        result = []
        for member in tar:
            assert member.uid == member.gid == 0, (member.name, member.uid, member.gid)
            assert member.uname == "root" and member.gname == "wheel"
            for key in ("uid", "gid", "uname", "gname"):
                assert key not in member.pax_headers
            assert member.pax_headers["SHADOW.test"] == "unknown metadata retained"
            assert member.pax_headers["SCHILY.xattr.user.test"] == "fixture"
            assert member.mtime == STAMP
            result.append((member.name, member.type, member.mode, member.linkname,
                           tar.extractfile(member).read() if member.isfile() else None))
        return result


def main():
    normalize = runpy.run_path(str(ROOT / "scripts/normalize-deb-ownership.py"))["normalize"]
    plain = archive()
    with tempfile.TemporaryDirectory(prefix="shadow-deb-ownership-") as directory:
        package = Path(directory) / "fixture.deb"
        expected = [("usr/libexec", tarfile.DIRTYPE, 0o755, "", None),
                    ("usr/libexec/helper", tarfile.REGTYPE, 0o4755, "", PAYLOAD),
                    ("usr/bin/helper", tarfile.SYMTYPE, 0o777, "../libexec/helper", None),
                    ("usr/libexec/helper-hard", tarfile.LNKTYPE, 0o4755, "usr/libexec/helper", None)]
        for suffix, encode in ((".gz", gzip.compress), (".xz", lzma.compress),
                               (".lzma", lambda data: lzma.compress(data, format=lzma.FORMAT_ALONE)),
                               ("", lambda data: data)):
            package.write_bytes(ar([("debian-binary", b"2.0\n"),
                                    ("control.tar" + suffix, encode(plain)),
                                    ("data.tar" + suffix, encode(plain))]))
            normalize(package)
            entries = read_ar(package.read_bytes())
            assert entries[0] == ("debian-binary", b"2.0\n")
            assert [name for name, _ in entries[1:]] == ["control.tar" + suffix, "data.tar" + suffix]
            for _, raw in entries[1:]:
                assert inventory(raw) == expected
            normalized = package.read_bytes()
            normalize(package)
            assert package.read_bytes() == normalized, "normalization not idempotent"
        link = Path(directory) / "linked.deb"
        link.symlink_to(package.name)
        before = package.read_bytes()
        try:
            normalize(link)
        except ValueError:
            pass
        else:
            raise AssertionError("source package symlink accepted")
        assert link.is_symlink() and package.read_bytes() == before
    print("deb ownership: gzip/xz/lzma/raw, numeric/PAX owner normalization, binary payloads, modes, links, timestamps, unknown metadata, idempotence and source symlink rejection passed")


if __name__ == "__main__":
    main()
