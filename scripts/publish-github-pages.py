#!/usr/bin/env python3
"""Publish a verified CI package through Pages artifacts, without GitHub Releases."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
REPO = "gitssie/shadow"
REMOTE = "git@github.com:gitssie/shadow.git"


def run(*args, cwd=ROOT, capture=False):
    return subprocess.check_output(args, cwd=cwd, text=True) if capture else subprocess.check_call(args, cwd=cwd)


WORKFLOW = """name: Sileo source
on:
  push:
    branches: [gh-pages]
permissions:
  contents: read
  actions: read
  pages: write
  id-token: write
concurrency:
  group: sileo-pages
  cancel-in-progress: false
jobs:
  deploy:
    runs-on: ubuntu-24.04
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v5
      - name: Download and validate selected CI build
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          python3 - <<'PYCODE'
          import hashlib, json, subprocess
          from pathlib import Path
          selected = json.loads(Path('pages/deployment.json').read_text())
          revision = subprocess.check_output(['gh', 'api', 'repos/gitssie/shadow/actions/runs/' + str(selected['run_id']), '--jq', '.head_sha'], text=True).strip()
          assert revision == selected['revision']
          subprocess.check_call(['gh', 'run', 'download', str(selected['run_id']), '--repo', 'gitssie/shadow', '--name', selected['artifact'], '--dir', 'package'])
          package = Path('package') / selected['filename']
          assert hashlib.sha256(package.read_bytes()).hexdigest() == selected['sha256']
          subprocess.check_call(['python3', 'scripts/render-github-pages.py', '--package', str(package), '--lane', selected['lane'], '--tag', selected['revision'], '--control', 'pages/control', '--output', '_site'])
          PYCODE
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site
      - uses: actions/deploy-pages@v4
        id: deploy
"""


def publish(run_id, lane, enabled):
    info = json.loads(run('gh', 'api', f'repos/{REPO}/actions/runs/{run_id}', capture=True))
    jobs = json.loads(run('gh', 'api', f'repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100', capture=True))
    if info['head_repository']['full_name'] != REPO or not any(j['name'] == lane and j['conclusion'] == 'success' for j in jobs['jobs']):
        raise ValueError('selected lane must have a successful build in this repository')
    with tempfile.TemporaryDirectory(prefix='shadow-pages-') as directory:
        temporary = Path(directory)
        package_dir, repository = temporary / 'package', temporary / 'repository'
        artifact = 'shadow-' + lane
        run('gh', 'run', 'download', str(run_id), '--repo', REPO, '--name', artifact, '--dir', str(package_dir))
        control = run('bash', str(ROOT / 'scripts/gen-control.sh'), lane, capture=True)
        package_id = next(line.split(':', 1)[1].strip() for line in control.splitlines() if line.startswith('Package:'))
        packages = [p for p in package_dir.glob('*.deb') if run('dpkg-deb', '--field', str(p), 'Package', capture=True).strip() == package_id]
        if len(packages) != 1:
            raise ValueError('expected one Shadow package')
        site = temporary / 'site'
        run('python3', str(ROOT / 'scripts/render-github-pages.py'), '--package', str(packages[0]), '--lane', lane, '--tag', info['head_sha'], '--output', str(site))
        selected = json.loads((site / 'publication.json').read_text())
        selected.update(run_id=run_id, artifact=artifact, revision=info['head_sha'])
        if not enabled:
            print('Validated; no remote changes: ' + json.dumps(selected))
            return
        run('git', 'clone', '--quiet', '--single-branch', '--branch', 'gh-pages', REMOTE, str(repository))
        for item in repository.iterdir():
            if item.name != '.git':
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        for name in ('scripts/render-github-pages.py', 'pages/index.html', 'src/Shadow.app/Resources/Icon120.png'):
            destination = repository / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        (repository / 'pages/control').write_text(control)
        (repository / 'pages/deployment.json').write_text(json.dumps(selected, indent=2) + '\n')
        workflow = repository / '.github/workflows/pages.yml'
        workflow.parent.mkdir(parents=True)
        workflow.write_text(WORKFLOW)
        run('git', 'add', '--all', cwd=repository)
        name = run('git', 'config', 'user.name', capture=True).strip()
        email = run('git', 'config', 'user.email', capture=True).strip()
        run('git', '-c', 'user.name=' + name, '-c', 'user.email=' + email, 'commit', '--quiet', '-m', 'repo: deploy Sileo source without Releases', cwd=repository)
        run('gh', 'api', '--method', 'PUT', f'repos/{REPO}/pages', '-f', 'build_type=workflow')
        run('git', 'push', 'origin', 'HEAD:gh-pages', cwd=repository)
        print('Pages deployment started: https://gitssie.github.io/shadow/')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True, type=int)
    parser.add_argument('--lane', default='rootless')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    publish(args.run_id, args.lane, args.publish)
