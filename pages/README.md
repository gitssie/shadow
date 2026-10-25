# Sileo source on GitHub Pages

Source URL: https://gitssie.github.io/shadow/

The `gh-pages` branch contains a flat APT source (`Release`, `Packages`,
`Packages.gz`, `Packages.xz`) and a small installation page. Package downloads
use GitHub Releases assets; no `.deb` files are committed to Git.

## Publish

With the lane's normal build dependencies installed, set `THEOS` and, if needed,
`PREBUILT_ROOT`. Commit and push the source changes first. The publisher builds
an isolated copy of **HEAD**; uncommitted changes are excluded.

```sh
python3 tests/verify-github-pages.py
python3 scripts/publish-github-pages.py --lane rootless            # validate only
python3 scripts/publish-github-pages.py --lane rootless --publish  # publish
```

Publication creates a draft release, checks the uploaded package's SHA-256,
publishes the release, and pushes `gh-pages` without forcing. The release tag
contains the package version and source commit. Bump the package version before
publishing changed package bytes, so Sileo can recognize the update. A failed
publication may leave a draft or published release; inspect it before retrying.

For the first publication, enable GitHub Pages with `gh-pages` and `/` as its
source. This flat repository currently publishes one selected lane at a time;
select the lane matching the intended device. It preserves package control
metadata and dependencies from the built package. Users also need the existing
sources supplying those dependencies.
