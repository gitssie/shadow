#!/usr/bin/env python3
"""Build committed source locally and validate generated Sileo indexes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(*args, cwd=ROOT, capture=False):
    return subprocess.check_output(args, cwd=cwd, text=True) if capture else subprocess.check_call(args, cwd=cwd)


def validate_immutable_packages(repository, metadata):
    old_metadata = repository / 'publication.json'
    if old_metadata.exists():
        old = json.loads(old_metadata.read_text())
        if old['version'] == metadata['version'] and old['sha256'] != metadata['sha256']:
            raise ValueError('this version already has different bytes; bump the package version')
        for previous in old.get('packages', []):
            for entry in metadata.get('packages', []):
                if all(previous[key] == entry[key] for key in ('package', 'version', 'architecture')):
                    if previous['sha256'] != entry['sha256']:
                        raise ValueError('this dependency version already has different bytes; bump the package version')
    # Older versions remain in pool even after their metadata leaves the index.
    for entry in metadata.get('packages', [metadata]):
        existing = repository / 'pool' / entry['filename']
        if existing.is_symlink() or (existing.exists() and
                hashlib.sha256(existing.read_bytes()).hexdigest() != entry['sha256']):
            raise ValueError('published package has different bytes: ' + entry['filename'] + '; bump the package version')


def publish(lane, enabled, hookkit_package=None):
    if enabled:
        raise ValueError("Public package distribution is disabled for this fork; build locally instead.")
    if lane == 'rootless' and hookkit_package is None:
        raise ValueError('rootless publication requires --hookkit-package for the self-hosted dependency')
    if hookkit_package is not None:
        if hookkit_package.is_symlink() or not hookkit_package.is_file():
            raise ValueError('HookKit package must be a regular file')
        hookkit_package = hookkit_package.resolve()
    revision = run('git', 'rev-parse', 'HEAD', capture=True).strip()
    with tempfile.TemporaryDirectory(prefix='shadow-pages-') as directory:
        temporary = Path(directory)
        source, site = [temporary / name for name in ('source', 'site')]
        source.mkdir()
        archive = temporary / 'source.tar'
        run('git', 'archive', '--format=tar', '--output=' + str(archive), revision)
        run('tar', '-xf', str(archive), '-C', str(source))
        run('bash', './build.sh', lane, cwd=source)
        selected = (source / '.theos/last_package').read_text().strip()
        package = source / 'build' / Path(selected).name
        if not package.is_file():
            raise ValueError('the selected build package is missing')
        render_args = ['python3', str(source / 'scripts/render-github-pages.py'), '--package', str(package),
                       '--lane', lane, '--tag', revision, '--output', str(site)]
        if hookkit_package is not None:
            render_args.extend(['--hookkit-package', str(hookkit_package)])
        run(*render_args)
        metadata = json.loads((site / 'publication.json').read_text())
        print('Validated locally; public distribution is disabled: ' + json.dumps(metadata))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane', default='rootless')
    parser.add_argument('--publish', action='store_true', help='disabled: public package distribution is retired')
    parser.add_argument('--hookkit-package', type=Path, help='locally built HookKit dependency .deb')
    args = parser.parse_args()
    publish(args.lane, args.publish, args.hookkit_package)
