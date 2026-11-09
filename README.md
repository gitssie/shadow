# Shadow

A modern jailbreak detection bypass.

If Shadow is useful to you, consider [sponsoring](https://github.com/sponsors/jjolano) or [buying me a coffee](https://ko-fi.com/jjolano).

## Install

Add `https://ios.jjolano.me` to your package manager and install `me.jjolano.shadow`. Or grab the [latest release](https://github.com/jjolano/shadow/releases/latest).

Needs `AltList` + `libSandy` (opa334) and `HookKit >= 3.0.4` (jjolano; `>= 2.5.0` on rootful legacy). `Injection Foundation` (PoomSmart) recommended.

## Use

Settings app → Shadow → global defaults or per-app config. `shdw -d` keeps the app ruleset in sync.

## Compatibility

| Package | iOS |
| --- | --- |
| Rootful legacy (`iphoneos-arm`) | 9–13 |
| Rootful modern (`iphoneos-arm`) | 14+ |
| Rootless (`iphoneos-arm64`) | 15+ |

No guarantee every app/detection SDK works everywhere.

These are declared package ranges, not a device-tested version matrix. CI builds
the three supported lanes and checks package metadata and Mach-O compatibility; public host
tests do not verify hook installation or behavior on each iOS version. An open-ended
range does not establish compatibility with future releases.

## Troubleshooting

* Disable other tweaks per-app (Choicy).
* Downgrade the app; don't stack multiple bypass tweaks.
* Rootless/semi-untethered: test in stock jailed state to isolate.

## Building

Requires upstream [Theos](https://github.com/theos/theos) and the SDKs selected in
`build-support/lanes.sh`. Set `THEOS` to that checkout; no Theos fork or extra
scripts in its `bin/` directory are needed. Modern lanes require macOS/Xcode 12+;
the legacy lane requires Xcode 11.7 (`OLDABI_DEVELOPER_DIR`) on macOS, or an
old-ABI cross-toolchain (`OLDABI_TOOLCHAIN`) and iOS 13.7 SDK (`OLDABI_SDKS`) on Linux.

Install the pinned HookKit into the same Theos before building dependencies:

```sh
export THEOS=/path/to/theos
export HOOKKIT=e55a3c497d3112184e9d528092eb2b341c9e8029
.github/scripts/install-hookkit-theos.sh rootful-modern
```

The installer applies a build-only adapter to the pinned HookKit checkout so
both projects use Shadow's lane configuration. Local HookKit sources can be
provided as `$DEPS_SOURCE_ROOT/HookKit`. One lane at a time:

```sh
.github/scripts/build-deps.sh rootful-modern
./build.sh rootful-modern
```

Rootless builds require the exact HookKit dependency declared in
`packaging/controls/control.rootless.in`. From the matching maintained HookKit
checkout, use `DEPS_SOURCE_ROOT` with the installer above and select `rootless`,
using the same `THEOS` as Shadow. Shadow checks the installed framework
version before compiling; the later ABI check remains a separate check.


Lanes: `rootful-legacy`, `rootful-modern`, `rootless`. RootHide builds are not supported on this branch. See `build-support/lanes.sh` for the matrix. Tests: `make -C tests test` ([details](tests/README.md)).

## Legal

*Copyright Act*, RSC 1985, c C-42, s 41.12.
