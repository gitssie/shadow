#!/usr/bin/env bash
# Exercise ABI validation without an iOS SDK or Theos fork.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/build-support/toolchain.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export THEOS="$TMP/ordinary-theos"
mkdir -p "$THEOS" "$TMP/compiler/bin" "$TMP/sdks/iPhoneOS13.7.sdk"
export OLDABI_TOOLCHAIN="$TMP/compiler" OLDABI_SDKS="$TMP/sdks"
printf '#!/bin/sh\necho "${TEST_CLANG_VERSION:-10.0.0}"\n' > "$OLDABI_TOOLCHAIN/bin/clang"
chmod +x "$OLDABI_TOOLCHAIN/bin/clang"
uname() { echo Linux; }
shadow_abi_require old legacy
[ "$(shadow_abi_args old)" = "$(printf '%s\n' "SDKBINPATH=$OLDABI_TOOLCHAIN/bin" "THEOS_SDKS_PATH=$OLDABI_SDKS")" ]
if TEST_CLANG_VERSION=12.0.0 shadow_abi_require old legacy 2>/dev/null; then
    echo 'FAIL: new ABI compiler accepted for legacy' >&2; exit 1
fi
if shadow_abi_require new modern 2>/dev/null; then
    echo 'FAIL: modern Linux lane accepted without supported toolchain' >&2; exit 1
fi
uname() { echo Darwin; }
xcodebuild() {
    if [ "${DEVELOPER_DIR:-}" = "$TMP/Xcode11" ]; then echo 'Xcode 11.7'; else echo 'Xcode 16.0'; fi
}
export OLDABI_DEVELOPER_DIR="$TMP/Xcode11"
unset DEVELOPER_DIR
shadow_abi_require old legacy
[ -z "$(shadow_abi_args old)" ]
[ -z "${DEVELOPER_DIR:-}" ]
shadow_abi_require new modern
[ -z "$(shadow_abi_args new)" ]
# HookKit's CLI adapter must consume the same fields without Theos/bin/lane.sh.
. "$ROOT/build-support/lanes.sh"
for lane in $(shadow_lanes); do
    for field in ARCHS TARGET SCHEME DEPLOY DEPLOY_ARM64E ABI; do
        [ "$(bash "$ROOT/build-support/hookkit-lanes.sh" get "$lane" "$field")" = "$(shadow_lane_field "$lane" "$field")" ]
    done
done
if bash "$ROOT/build-support/hookkit-lanes.sh" get roothide ARCHS 2>/dev/null; then
    echo 'FAIL: unsupported RootHide lane accepted' >&2; exit 1
fi
# Invalid targets must be rejected before touching earlier build output.
mkdir -p "$TMP/project/build" "$TMP/project/build-support"
cp "$ROOT/build.sh" "$TMP/project/"
cp "$ROOT/build-support/lanes.sh" "$TMP/project/build-support/"
touch "$TMP/project/build/previous-package"
status=0
bash "$TMP/project/build.sh" roothide > "$TMP/rejected.log" 2>&1 || status=$?
[ "$status" -eq 2 ] && [ -f "$TMP/project/build/previous-package" ]
grep -q 'unsupported build target: roothide' "$TMP/rejected.log"
echo 'PASS: upstream Theos ABI checks, isolated Xcode selection, HookKit adapter and target rejection'
