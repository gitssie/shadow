# Sileo source on GitHub Pages

Source: https://gitssie.github.io/shadow/

The site and flat APT indexes are deployed using a GitHub Pages artifact. The
package is served from `pool/` on the same site. No GitHub Releases or release
tags are created, and `.deb` files are never committed to Git.

With `THEOS` configured, select a CI run whose intended lane succeeded:

```sh
python3 tests/verify-github-pages.py
python3 scripts/publish-github-pages.py --run-id RUN_ID --lane rootless
python3 scripts/publish-github-pages.py --run-id RUN_ID --lane rootless --publish
```

The publisher validates the CI artifact against the generated lane control,
then updates `gh-pages` with a deployment workflow and the selected run metadata.
The workflow downloads the selected artifact, verifies its SHA-256 and source
revision, generates the indexes, and deploys the whole site through Pages.
The source publishes one selected lane at a time. Bump the package version for
updates so Sileo recognizes them. Existing package dependencies remain unchanged.
