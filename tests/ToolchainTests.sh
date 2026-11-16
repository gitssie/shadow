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
[ "$(shadow_lanes)" = rootless ]
for lane in $(shadow_lanes); do
    for field in ARCHS TARGET SCHEME DEPLOY DEPLOY_ARM64E ABI; do
        [ "$(bash "$ROOT/build-support/hookkit-lanes.sh" get "$lane" "$field")" = "$(shadow_lane_field "$lane" "$field")" ]
    done
done
if bash "$ROOT/build-support/hookkit-lanes.sh" get roothide ARCHS 2>/dev/null; then
    echo 'FAIL: unsupported RootHide lane accepted' >&2; exit 1
fi
# Rejected selectors must preserve output and fail before toolchain lookup.
mkdir -p "$TMP/project/build" "$TMP/project/build-support"
cp "$ROOT/build.sh" "$ROOT/Makefile" "$TMP/project/"
cp "$ROOT/build-support/lanes.sh" "$TMP/project/build-support/"
touch "$TMP/project/build/previous-package"
reject_build() {
    local expected=$1
    shift
    local status=0
    env -u THEOS bash "$TMP/project/build.sh" "$@" > "$TMP/rejected.log" 2>&1 || status=$?
    [ "$status" -eq 2 ] && [ -f "$TMP/project/build/previous-package" ]
    grep -q "$expected" "$TMP/rejected.log"
}
for target in all rootful rootful-legacy rootful-modern roothide unknown; do
    reject_build "unsupported build target: $target" "$target"
    reject_build "unsupported dependency target: $target" deps "$target"
done
reject_build 'unexpected build arguments' rootless extra
reject_build 'unexpected build arguments' quick extra
reject_build 'unsupported dependency target' deps rootless extra
# Accepted forms reach the environment check without deleting earlier output.
for target in default rootless quick deps; do
    args=()
    [ "$target" = default ] || args=("$target")
    status=0
    env -u THEOS bash "$TMP/project/build.sh" "${args[@]}" > "$TMP/accepted.log" 2>&1 || status=$?
    [ "$status" -eq 1 ] && [ -f "$TMP/project/build/previous-package" ]
    grep -q 'THEOS must point to Theos' "$TMP/accepted.log"
done
status=0
env -u THEOS bash "$TMP/project/build.sh" deps rootless > "$TMP/accepted.log" 2>&1 || status=$?
[ "$status" -eq 1 ] && grep -q 'THEOS must point to Theos' "$TMP/accepted.log"
for target in rootful-legacy rootful-modern rootful roothide all unknown; do
    status=0
    make -C "$TMP/project" "SHADOW_LANE=$target" SHADOW_CURL_IMPERSONATE=0 THEOS=absent > "$TMP/make-rejected.log" 2>&1 || status=$?
    [ "$status" -eq 2 ] && [ -f "$TMP/project/build/previous-package" ]
    grep -q "unsupported SHADOW_LANE '$target'" "$TMP/make-rejected.log"
    status=0
    WORK="$TMP/absent-work" PREBUILT_ROOT="$TMP/prebuilt" bash "$ROOT/.github/scripts/build-deps.sh" "$target" > "$TMP/deps-rejected.log" 2>&1 || status=$?
    [ "$status" -eq 2 ] && [ ! -e "$TMP/absent-work" ] && [ ! -e "$TMP/prebuilt" ]
    grep -q "unsupported dependency target: $target" "$TMP/deps-rejected.log"
done
echo 'PASS: upstream Theos ABI checks, isolated Xcode selection, HookKit adapter and rootless-only entrypoints'
