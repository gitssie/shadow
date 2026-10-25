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
    assert not list(output.rglob("*.deb"))
    assert (output / ".nojekyll").exists()
    for lane, tag, destination in (("roothide", "test", temporary / "wrong"),
                                   ("rootless", "../bad", temporary / "bad"),
                                   ("rootless", "test", output)):
        try:
            pages.render(package, lane, tag, destination)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid publication was accepted")
print("GitHub Pages source: package identity, indexes, hashes, links and invalid inputs passed")
