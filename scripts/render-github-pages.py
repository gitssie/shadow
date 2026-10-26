#!/usr/bin/env python3
"""Render Shadow's flat Sileo source; packages are included in the Pages deployment artifact."""
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


def read_package(package):
    if package.is_symlink() or not package.is_file():
        raise ValueError("package must be a regular file")
    fields = control(subprocess.check_output(["dpkg-deb", "--field", str(package)], text=True))
    filename = "{Package}_{Version}_{Architecture}.deb".format(**fields)
    if package.name != filename or not re.fullmatch(r"[A-Za-z0-9.+~_-]+", filename):
        raise ValueError("unexpected package filename")
    data = package.read_bytes()
    hashes = {name: hashlib.new(algorithm, data).hexdigest()
              for name, algorithm in (("MD5sum", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256"))}
    fields.update(Filename=f"{SOURCE}/pool/{filename}", Size=str(len(data)), **hashes)
    metadata = dict(package=fields["Package"], version=fields["Version"], architecture=fields["Architecture"],
                    filename=filename, package_url=fields["Filename"], size=len(data),
                    md5=hashes["MD5sum"], sha1=hashes["SHA1"], sha256=hashes["SHA256"])
    return fields, data, metadata


def validate_hookkit(shadow, dependency):
    package_id = "me.jjolano.fmwk.hookkit"
    if dependency["Package"] != package_id:
        raise ValueError("dependency package must be " + package_id)
    if dependency["Architecture"] != shadow["Architecture"]:
        raise ValueError("HookKit architecture must match the Shadow lane")
    requirements = [item.strip() for item in shadow.get("Depends", "").split(",")
                    if re.match(re.escape(package_id) + r"(?:\s|\(|$)", item.strip())]
    if not requirements:
        raise ValueError("Shadow must declare its HookKit dependency")
    for requirement in requirements:
        match = re.fullmatch(re.escape(package_id) + r"\s*\((>=|<=|>>|<<|=)\s*([^\s()]+)\)", requirement)
        if not match or subprocess.run(["dpkg", "--compare-versions", dependency["Version"],
                                        match[1], match[2]], check=False).returncode != 0:
            raise ValueError("HookKit version does not satisfy Shadow Depends")


def render(package, lane, tag, output, expected_control=None, hookkit_package=None):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        raise ValueError("invalid release tag")
    expected = control(expected_control.read_text() if expected_control else subprocess.check_output(
        ["bash", str(ROOT / "scripts/gen-control.sh"), lane], text=True))
    fields, data, primary = read_package(package)
    for key, value in expected.items():
        if fields.get(key) != value:
            raise ValueError("package does not match lane control: " + key)
    filename = primary["filename"]
    packages = [(package, fields, primary)]
    if hookkit_package is not None:
        dependency, _, dependency_metadata = read_package(hookkit_package)
        validate_hookkit(fields, dependency)
        packages.append((hookkit_package, dependency, dependency_metadata))
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    release_url = f"https://github.com/{REPOSITORY}"
    package_url = f"{SOURCE}/pool/{filename}"
    fields.update(Homepage=SOURCE + "/", Depiction=SOURCE + "/", SileoDepiction=SOURCE + "/depiction.json",
                  Filename=package_url)
    index = "".join("\n".join(f"{key}: {value}" for key, value in entry.items()) + "\n\n"
                    for _, entry, _ in packages).encode()
    output.mkdir(parents=True, exist_ok=True)
    (output / "pool").mkdir()
    for source_package, _, entry in packages:
        shutil.copyfile(source_package, output / "pool" / entry["filename"])
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
    metadata = dict(version=fields["Version"], lane=lane, tag=tag, sha256=primary["sha256"], filename=filename,
                    package_url=package_url, source_url=SOURCE + "/",
                    packages=[entry for _, _, entry in packages])
    (output / "publication.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--hookkit-package", type=Path, help="locally built HookKit dependency .deb")
    args = parser.parse_args()
    print(json.dumps(render(args.package, args.lane, args.tag, args.output, args.control, args.hookkit_package)))
