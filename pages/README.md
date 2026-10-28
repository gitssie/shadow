# Sileo source on GitHub Pages

Source: https://gitssie.github.io/shadow/

Build on the local Mac and upload the finished static source to `gh-pages`, as
in TrollVNC. GitHub only hosts the site; no GitHub app build, Releases, or release
tags are used. Package files are stored only in the dedicated publication branch.

With `THEOS` and the lane's `PREBUILT_ROOT` configured, commit the intended source
changes first. The publisher builds an isolated copy of **HEAD**, excluding
uncommitted source changes.

```sh
python3 tests/verify-github-pages.py
python3 scripts/publish-github-pages.py --lane rootless            # validate only
python3 scripts/publish-github-pages.py --lane rootless --publish  # build and upload
```

The local build runs the normal package compatibility checks. The renderer
validates the package identity, then generates `Release`, compressed indexes,
the installation page and `pool/`. The publication branch is updated without
force-pushing. Previous pool files are retained for clients with older indexes.
Bump the package version for updates so Sileo recognizes them. Existing package
dependencies remain unchanged. The source currently indexes one selected lane.
