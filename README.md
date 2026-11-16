# Shadow

A modern jailbreak detection bypass, based on [jjolano/Shadow](https://github.com/jjolano/shadow).

## Versions

`master` is the rootless TLS mainline, starting at 4.1.0. `stable` retains the
pre-TLS 4.0.6-11 code, also fixed by the annotated tag `v4.0.6-11`.
Rootful development remains on the stable history.

## Install

Install locally built rootless packages using Sileo or `dpkg`. This mainline
requires AltList, libSandy and exactly `me.jjolano.fmwk.hookkit (= 3.0.6-1)`.
Use the maintained [gitssie/HookKit](https://github.com/gitssie/HookKit) build
selected by `.github/workflows/build.yml`; an upstream build with the same
version number is not a substitute. Injection Foundation is recommended.

Finished packages may be published to this fork's `gh-pages` Sileo source.
GitHub Actions performs source and host checks; packages are built locally.

## Use

Settings app → Shadow → global defaults or per-app config. `shdw -d` keeps the
app ruleset in sync. TLS profile selection follows the saved system fingerprint
version. Versions below iOS 17 keep native TLS and HTTP/2; newer supported
profiles use the configured curl TLS engine and native HTTP/2 configuration.

## Compatibility

This mainline supports rootless (`iphoneos-arm64`) only, with the deployment
range declared in `build-support/lanes.sh`. Package compatibility checks do not
establish device behavior across every iOS release. Runtime TLS and HTTP/2
adaptation also requires compatible system interfaces.

## Building

Requires macOS/Xcode 12+, upstream [Theos](https://github.com/theos/theos),
Python 3, CMake, Ninja, `dpkg` and `ldid`. The SDK and architecture fields come
from `build-support/lanes.sh`.

```sh
export THEOS=/path/to/theos
.github/scripts/install-hookkit-theos.sh rootless
.github/scripts/build-deps.sh rootless
scripts/prepare-curl-impersonate.sh
./build.sh
```

The HookKit installer reads its exact source revision and repository from
`.github/workflows/build.yml`, applies the build adapter, installs into the
same Theos, and records the source revision and installed binary hash.
Shadow checks both this receipt and the exact package/framework version before
compiling. A missing or stale receipt requires rerunning the installer.
To use local dependency sources, provide `$DEPS_SOURCE_ROOT/HookKit`; that
checkout must contain the pinned commit. `HOOKKIT_PACKAGE_OUTPUT` can retain
the matching HookKit `.deb` produced by the installer.

Dependencies are stored under `PREBUILT_ROOT` (default `../prebuilt`). If they
already match, run `./build.sh` directly. `./build.sh rootless` is equivalent;
`./build.sh quick` compiles the rootless framework and dylibs without packaging.
Other build lanes are rejected on this mainline.

Tests: `make -C tests test` and `sh tests/MaintainerScriptTests.sh`.
See [tests/README.md](tests/README.md) for optional host and device checks.

## Troubleshooting

* Disable other tweaks per-app with Choicy.
* Downgrade the app; avoid stacking multiple bypass tweaks.
* Test in the stock jailed state to isolate jailbreak effects.

## Credits and legal

Upstream authors: [jjolano](https://github.com/jjolano),
[HookKit contributors](https://github.com/jjolano/HookKit), and the dependency
projects. Support upstream through [GitHub Sponsors](https://github.com/sponsors/jjolano).

*Copyright Act*, RSC 1985, c C-42, s 41.12.
