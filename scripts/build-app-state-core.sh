#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
. "$ROOT/build-support/app-state.sh"
app_state_initialize "${1:-rootless}"
output=${APP_STATE_BUILD_ROOT:-$ROOT/build/app-state}/$AS_LANE
clang=$(xcrun --sdk iphoneos --find clang)
ar=$(xcrun --sdk iphoneos --find ar)
mkdir -p "$output"
for arch in $AS_ARCHS; do
    prefix="$AS_PREBUILT/$AS_LANE/$arch"
    [ -f "$prefix/lib/libarchive.a" ] && [ -f "$prefix/lib/libzstd.a" ] || {
        echo "Build dependencies first: scripts/build-app-state-deps.sh $AS_LANE" >&2; exit 1;
    }
    deploy=$(app_state_deployment "$arch")
    mkdir -p "$output/$arch"
    flags=(-arch "$arch" -isysroot "$AS_SDKROOT" "-miphoneos-version-min=$deploy"
        -fobjc-arc -fvisibility=hidden -Wall -Wextra -Werror -Wno-deprecated-declarations
        -I"$prefix/include")
    for name in Archive State; do
        "$clang" "${flags[@]}" -c "$ROOT/src/AppState/$name.m" -o "$output/$arch/$name.o"
    done
    "$ar" rcs "$output/$arch/libShadowAppState.a" "$output/$arch/Archive.o" "$output/$arch/State.o"
    printf 'int main(void) { return 0; }\n' > "$output/$arch/link-check.c"
    "$clang" -arch "$arch" -isysroot "$AS_SDKROOT" "-miphoneos-version-min=$deploy" \
        "$output/$arch/link-check.c" -Wl,-force_load,"$output/$arch/libShadowAppState.a" \
        "$prefix/lib/libarchive.a" "$prefix/lib/libzstd.a" -framework Foundation \
        -Wl,-x -o "$output/$arch/link-check"
    echo "AppState compile/link passed: $AS_LANE/$arch (iOS $deploy)"
done
