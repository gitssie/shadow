#!/usr/bin/env python3
"""Build committed source and publish a GitHub Releases package plus gh-pages source."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
REPO = "gitssie/shadow"
REMOTE = "git@github.com:gitssie/shadow.git"


def run(*args, cwd=ROOT, capture=False, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, **kwargs).stdout


def publish(lane, dry_run):
    revision = run("git", "rev-parse", "HEAD", capture=True).strip()
    with tempfile.TemporaryDirectory(prefix="shadow-pages-") as temporary:
        temporary = Path(temporary)
        source, site, repository = [temporary / name for name in ("source", "site", "repository")]
        source.mkdir()
        archive = temporary / "source.tar"
        run("git", "archive", "--format=tar", "--output=" + str(archive), revision)
        run("tar", "-xf", str(archive), "-C", str(source))
        run("bash", "./build.sh", lane, cwd=source)
        # build.sh also stages dependency packages; publish its selected Shadow package.
        selected = (source / ".theos/last_package").read_text().strip()
        package = source / "build" / Path(selected).name
        if not package.is_file():
            raise ValueError("the selected build package is missing")
        version = run("dpkg-deb", "--field", str(package), "Version", capture=True).strip()
        tag = "shadow-" + version + "-" + revision[:7]
        run("python3", str(source / "scripts/render-github-pages.py"), "--package", str(package),
            "--lane", lane, "--tag", tag, "--output", str(site))
        metadata = json.loads((site / "publication.json").read_text())
        repository.mkdir()
        run("git", "init", "--quiet", cwd=repository)
        run("git", "remote", "add", "publish", REMOTE, cwd=repository)
        existing = run("git", "ls-remote", "--heads", REMOTE, "refs/heads/gh-pages", capture=True)
        if existing:
            run("git", "fetch", "--quiet", "--depth=1", "publish", "gh-pages", cwd=repository)
            run("git", "checkout", "--quiet", "-B", "gh-pages", "FETCH_HEAD", cwd=repository)
            old = json.loads((repository / "publication.json").read_text())
            if old["version"] == version and old["sha256"] != metadata["sha256"]:
                raise ValueError("this version already has different package bytes; bump the package version")
        else:
            run("git", "checkout", "--quiet", "--orphan", "gh-pages", cwd=repository)
        if dry_run:
            print("Validated publication (no remote changes): " + json.dumps(metadata))
            return
        # Prepare all repository files before uploading or publishing anything.
        for item in repository.iterdir():
            if item.name == ".git":
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        shutil.copytree(site, repository, dirs_exist_ok=True)
        run("git", "add", "--all", cwd=repository)
        name = run("git", "config", "user.name", capture=True).strip()
        email = run("git", "config", "user.email", capture=True).strip()
        run("git", "-c", "user.name=" + name, "-c", "user.email=" + email,
            "commit", "--quiet", "-m", "repo: publish Shadow " + version, cwd=repository)
        notes = temporary / "release.md"
        notes.write_text(f"Shadow {version} ({lane})\n\nSource commit: `{revision}`\n\n"
                         f"Sileo source: https://gitssie.github.io/shadow/\n\nSHA-256: `{metadata['sha256']}`\n")
        run("gh", "release", "create", tag, str(package), "--repo", REPO, "--target", revision,
            "--title", f"Shadow {version} ({lane})", "--notes-file", str(notes), "--draft")
        downloaded = temporary / "download"
        run("gh", "release", "download", tag, "--repo", REPO, "--pattern", package.name, "--dir", str(downloaded))
        if hashlib.sha256((downloaded / package.name).read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError("uploaded asset hash differs from the built package")
        run("gh", "release", "edit", tag, "--repo", REPO, "--draft=false")
        run("git", "push", "publish", "HEAD:refs/heads/gh-pages", cwd=repository)
        print("Published: " + metadata["source_url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", default="rootless")
    parser.add_argument("--publish", action="store_true", help="upload release and push gh-pages; default is a dry run")
    args = parser.parse_args()
    publish(args.lane, not args.publish)
