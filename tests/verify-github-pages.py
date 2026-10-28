#!/usr/bin/env python3
"""Host checks for generated Sileo indexes, package identity and download links."""
import gzip
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts/render-github-pages.py")
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)
spec = importlib.util.spec_from_file_location("publisher", ROOT / "scripts/publish-github-pages.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def build_package(directory, fields, payload="fixture"):
    root = directory / "root"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN/control").write_text("\n".join(f"{key}: {value}" for key, value in fields.items()) + "\n")
    (root / "payload").write_text(payload)
    package = directory / "{Package}_{Version}_{Architecture}.deb".format(**fields)
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(package)],
                   check=True, capture_output=True)
    return package


def rejected(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("invalid publication was accepted")


with tempfile.TemporaryDirectory(prefix="shadow-pages-test-") as temporary:
    temporary = Path(temporary)
    package_root = temporary / "package"
    (package_root / "DEBIAN").mkdir(parents=True)
    control = subprocess.check_output(["bash", str(ROOT / "scripts/gen-control.sh"), "rootless"], text=True)
    (package_root / "DEBIAN/control").write_text(control)
    fields = pages.control(control)
    package = temporary / "{Package}_{Version}_{Architecture}.deb".format(**fields)
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(package_root), str(package)], check=True, capture_output=True)
    output = temporary / "site"
    metadata = pages.render(package, "rootless", "test-release", output)
    index = (output / "Packages").read_bytes()
    assert gzip.decompress((output / "Packages.gz").read_bytes()) == index
    assert lzma.decompress((output / "Packages.xz").read_bytes()) == index
    published = pages.control(index.decode())
    assert published["Filename"] == metadata["package_url"]
    assert published["SHA256"] == hashlib.sha256(package.read_bytes()).hexdigest()
    assert int(published["Size"]) == package.stat().st_size
    release = (output / "Release").read_text()
    for name in ("Packages", "Packages.gz", "Packages.xz"):
        data = (output / name).read_bytes()
        for algorithm in ("md5", "sha1", "sha256"):
            assert f" {hashlib.new(algorithm, data).hexdigest()} {len(data):16d} {name}" in release
    assert "Architectures: " + fields["Architecture"] in release
    page = (output / "index.html").read_text()
    assert "{{" not in page and "sileo://source/https://gitssie.github.io/shadow/" in page
    assert metadata["package_url"] in page
    assert json.loads((output / "depiction.json").read_text())["class"] == "DepictionTabView"
    assert (output / "pool" / package.name).read_bytes() == package.read_bytes()
    assert (output / ".nojekyll").exists()
    assert metadata["packages"][0]["sha256"] == metadata["sha256"]
    for lane, tag, destination in (("roothide", "test", temporary / "wrong"),
                                   ("rootless", "../bad", temporary / "bad"),
                                   ("rootless", "test", output)):
        rejected(lambda: pages.render(package, lane, tag, destination))

    hookkit_fields = dict(Package="me.jjolano.fmwk.hookkit", Version="3.0.5+shadow.1-1",
                          Architecture=fields["Architecture"], Maintainer="Shadow",
                          Description="HookKit framework")
    hookkit = build_package(temporary / "hookkit", hookkit_fields)
    combined = temporary / "combined"
    combined_metadata = pages.render(package, "rootless", "test-release", combined, hookkit_package=hookkit)
    combined_index = (combined / "Packages").read_bytes()
    entries = [pages.control(stanza) for stanza in combined_index.decode().strip().split("\n\n")]
    assert len(entries) == 2
    for entry, source_package, details in zip(entries, (package, hookkit), combined_metadata["packages"]):
        data = source_package.read_bytes()
        assert entry["Package"] == details["package"]
        assert entry["Version"] == details["version"]
        assert entry["Architecture"] == details["architecture"] == fields["Architecture"]
        assert int(entry["Size"]) == details["size"] == len(data)
        for key, algorithm in (("MD5sum", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256")):
            assert entry[key] == hashlib.new(algorithm, data).hexdigest() == details[algorithm]
        assert entry["Filename"] == details["package_url"]
        assert (combined / "pool" / source_package.name).read_bytes() == data
    assert combined_metadata["version"] == metadata["version"]
    assert combined_metadata["sha256"] == metadata["sha256"]
    assert gzip.decompress((combined / "Packages.gz").read_bytes()) == combined_index
    assert lzma.decompress((combined / "Packages.xz").read_bytes()) == combined_index
    for name in ("Packages", "Packages.gz", "Packages.xz"):
        data = (combined / name).read_bytes()
        assert f" {hashlib.sha256(data).hexdigest()} {len(data):16d} {name}" in (combined / "Release").read_text()

    for label, changes in (("identity", {"Package": "other.framework"}),
                           ("architecture", {"Architecture": "iphoneos-arm"}),
                           ("old-version", {"Version": "3.0.5"}),
                           ("unpatched-newer-version", {"Version": "3.0.6"})):
        invalid = build_package(temporary / label, dict(hookkit_fields, **changes))
        rejected(lambda: pages.render(package, "rootless", "test", temporary / (label + "-site"),
                                      hookkit_package=invalid))
    symlink = temporary / "symlink.deb"
    symlink.symlink_to(hookkit)
    rejected(lambda: pages.render(package, "rootless", "test", temporary / "symlink-site",
                                  hookkit_package=symlink))

    publisher.validate_immutable_packages(combined, combined_metadata)
    changed = json.loads(json.dumps(combined_metadata))
    changed["packages"][1]["sha256"] = "0" * 64
    rejected(lambda: publisher.validate_immutable_packages(combined, changed))
    # Retained pool files still prevent replacement after leaving publication.json.
    (combined / "publication.json").unlink()
    rejected(lambda: publisher.validate_immutable_packages(combined, changed))
    publisher.validate_immutable_packages(combined, combined_metadata)
    (combined / "publication.json").write_text(json.dumps(metadata))
    changed_primary = dict(metadata, sha256="0" * 64)
    rejected(lambda: publisher.validate_immutable_packages(combined, changed_primary))
    # The previous single-package metadata format remains accepted.
    legacy = {key: value for key, value in metadata.items() if key != "packages"}
    (combined / "publication.json").write_text(json.dumps(legacy))
    publisher.validate_immutable_packages(combined, combined_metadata)
    rejected(lambda: publisher.publish("rootless", False))
print("GitHub Pages source: package/dependency identity, versions, indexes, hashes and immutable publication passed")
