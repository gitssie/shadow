#!/usr/bin/env python3
"""Render Shadow's flat Sileo source; packages are hosted on GitHub Releases."""
import argparse
import gzip
import hashlib
import html
import json
import lzma
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "https://gitssie.github.io/shadow"
REPOSITORY = "gitssie/shadow"


def control(text):
    result = {}
    key = None
    for line in text.splitlines():
        if not line:
            continue
        if line[0].isspace() and key:
            result[key] += "\n" + line
        else:
            key, value = line.split(":", 1)
            if key in result:
                raise ValueError("duplicate control field")
            result[key] = value.strip()
    return result


def render(package, lane, tag, output):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        raise ValueError("invalid release tag")
    if package.is_symlink() or not package.is_file():
        raise ValueError("package must be a regular file")
    expected = control(subprocess.check_output(
        ["bash", str(ROOT / "scripts/gen-control.sh"), lane], text=True))
    fields = control(subprocess.check_output(["dpkg-deb", "--field", str(package)], text=True))
    for key, value in expected.items():
        if fields.get(key) != value:
            raise ValueError("package does not match lane control: " + key)
    filename = "{Package}_{Version}_{Architecture}.deb".format(**fields)
    if package.name != filename or not re.fullmatch(r"[A-Za-z0-9.+~_-]+", filename):
        raise ValueError("unexpected package filename")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    data = package.read_bytes()
    hashes = {name: hashlib.new(algorithm, data).hexdigest()
              for name, algorithm in (("MD5sum", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256"))}
    release_url = f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
    package_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}"
    fields.update(Homepage=SOURCE + "/", Depiction=SOURCE + "/", SileoDepiction=SOURCE + "/depiction.json",
                  Filename=package_url, Size=str(len(data)), **hashes)
    index = ("\n".join(f"{key}: {value}" for key, value in fields.items()) + "\n\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    indexes = {"Packages": index, "Packages.gz": gzip.compress(index, mtime=0),
               "Packages.xz": lzma.compress(index)}
    for name, content in indexes.items():
        (output / name).write_bytes(content)
    lines = ["Origin: Shadow", "Label: Shadow", "Suite: stable", "Codename: shadow",
             "Architectures: " + fields["Architecture"], "Components: main", "Description: Shadow Sileo repository",
             "Date: " + datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"), "Acquire-By-Hash: no"]
    for section, algorithm in (("MD5Sum", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256")):
        lines.append(section + ":")
        for name, content in indexes.items():
            lines.append(f" {hashlib.new(algorithm, content).hexdigest()} {len(content):16d} {name}")
    (output / "Release").write_text("\n".join(lines) + "\n")
    tokens = dict(VERSION=fields["Version"], LANE=lane, SIZE=f"{len(data)/1024/1024:.2f} MB",
                  SOURCE_URL=SOURCE + "/", PACKAGE_URL=package_url, RELEASE_URL=release_url,
                  COMPATIBILITY=fields["Depends"].split(", ldid")[0])
    page = (ROOT / "pages/index.html").read_text()
    for key, value in tokens.items():
        page = page.replace("{{" + key + "}}", html.escape(value, quote=True))
    if re.search(r"\{\{[A-Z_]+\}\}", page):
        raise ValueError("unresolved page token")
    (output / "index.html").write_text(page)
    depiction = {"class": "DepictionTabView", "tintColor": "#287f78", "tabs": [{"tabname": "Shadow",
        "class": "DepictionStackView", "views": [{"class": "DepictionHeaderView", "title": "Shadow"},
        {"class": "DepictionMarkdownView", "markdown": f"**{fields['Version']}** · {lane}\n\n" + fields['Description']},
        {"class": "DepictionButtonView", "text": "GitHub", "action": release_url}]}]}
    (output / "depiction.json").write_text(json.dumps(depiction, ensure_ascii=False, indent=2) + "\n")
    for name in ("icon.png", "CydiaIcon.png"):
        shutil.copyfile(ROOT / "src/Shadow.app/Resources/Icon120.png", output / name)
    (output / ".nojekyll").touch()
    metadata = dict(version=fields["Version"], lane=lane, tag=tag, sha256=hashes["SHA256"], filename=filename,
                    package_url=package_url, source_url=SOURCE + "/")
    (output / "publication.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.package, args.lane, args.tag, args.output)))
