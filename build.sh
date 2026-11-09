#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
: "${THEOS:?THEOS must point to Theos}"

# Lane matrix lives in one place; see build-support/lanes.sh.
. "$ROOT/build-support/lanes.sh"

PB=${PREBUILT_ROOT:-$ROOT/../prebuilt}
CONTROL_VAR=_THEOS_DEB_PACKAGE_CONTROL_PATH
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/shadow-build.XXXXXX")
LIBRARY_PATH=$STAGE/lib
INCLUDE_PATH=$STAGE/include
MAKE_PATHS=(
    "THEOS_LIBRARY_PATH=$LIBRARY_PATH"
    "THEOS_INCLUDE_PATH=$INCLUDE_PATH"
    "ADDITIONAL_CFLAGS=-fmodules-cache-path=$STAGE/module-cache"
    "ADDITIONAL_OBJCFLAGS=-fmodules-cache-path=$STAGE/module-cache"
)
trap 'rm -rf "$STAGE"' EXIT

case ${1:-all} in
    all|rootful|rootful-legacy|rootful-modern|rootless|quick) ;;
    deps) shadow_lane_field "${2:-rootful-modern}" ARCHS >/dev/null || exit 2 ;;
    *) echo "unsupported build target: $1 (use rootful-legacy, rootful-modern, rootless, rootful, all, quick, or deps PROFILE)" >&2; exit 2 ;;
esac

rm -rf "$ROOT/build"
mkdir -p "$ROOT/build"

stage_deps() { # rootful-legacy|rootful-modern|rootless
    local profile=$1 scheme= target sdk
    scheme=$(shadow_lane_field "$profile" SCHEME 2>/dev/null) || { echo "unknown dependency profile: $profile" >&2; return 2; }

    # HookKit is resolved from the Theos install (HookKit repo: make
    # install-theos), not staged here — see build-support/hookkit.mk. AltList and libSandy are
    # still built from source into prebuilt and staged into the lane sandbox.
    local altlist="$PB/altlist/$profile/AltList.framework"
    local sandy="$PB/sandy/$profile/libsandy.dylib"
    [ -f "$altlist/AltList" ] && [ -f "$sandy" ] || {
        echo "missing $profile dependencies; run .github/scripts/build-deps.sh $profile" >&2
        return 1
    }
    if [ "$profile" != rootful-legacy ] && [ "${2:-manager}" != core ]; then
        local arch
        for arch in $(shadow_lane_field "$profile" ARCHS); do
            [ -f "$PB/app-state/$profile/$arch/lib/libarchive.a" ] && [ -f "$PB/app-state/$profile/$arch/lib/libzstd.a" ] || {
                echo "missing $profile AppState dependencies; run scripts/build-app-state-deps.sh $profile" >&2
                return 1
            }
        done
    fi
    # HookKit framework dir is owned by build-support/hookkit.mk; consume its mapping.
    local hookkit_dir
    hookkit_dir=$(printf 'include %s\nshdw_print:\n\t@echo $(SHADOW_HOOKKIT_DIR)\n' \
        "$ROOT/build-support/hookkit.mk" | make -f - THEOS="$THEOS" SHADOW_LANE="$profile" shdw_print)
    local hookkit_theos="$hookkit_dir/HookKit.framework"
    [ -f "$hookkit_theos/HookKit" ] || {
        echo "missing Theos HookKit for $profile ($hookkit_theos); run 'make install-theos' in the HookKit repo" >&2
        return 1
    }

    python3 "$ROOT/scripts/check-hookkit-version.py" \
        "$ROOT/packaging/controls/control.$profile.in" "$hookkit_theos"

    rm -rf "$LIBRARY_PATH" "$INCLUDE_PATH"
    mkdir -p "$LIBRARY_PATH" "$INCLUDE_PATH"
    cp -R "$altlist" "$LIBRARY_PATH/AltList.framework"
    cp "$sandy" "$LIBRARY_PATH/libsandy.dylib"
    if [ -f "$PB/sandy/$profile/libSandy.h" ]; then
        cp "$PB/sandy/$profile/libSandy.h" "$INCLUDE_PATH/libSandy.h"
    elif [ -f "$THEOS/include/libSandy.h" ]; then
        cp "$THEOS/include/libSandy.h" "$INCLUDE_PATH/libSandy.h"
    elif [ -f "$THEOS/vendor/include/libSandy.h" ]; then
        cp "$THEOS/vendor/include/libSandy.h" "$INCLUDE_PATH/libSandy.h"
    fi
    # libSandy imports <xpc/xpc.h>. Older SDKs need the vendored module;
    # modern SDKs already provide it and reject a duplicate definition.
    target=$(shadow_lane_field "$profile" TARGET)
    sdk=${target#iphone:clang:}
    sdk=${sdk%%:*}
    if [ -n "${XPC_HEADERS:-}" ] || [ ! -f "$THEOS/sdks/iPhoneOS$sdk.sdk/usr/include/xpc/xpc.h" ]; then
        local xpc=${XPC_HEADERS:-$ROOT/.github/vendor/xpc}
        [ -d "$xpc" ] || { echo "set XPC_HEADERS to an xpc headers directory" >&2; return 1; }
        cp -R "$xpc" "$INCLUDE_PATH/"
    fi

    if [ -n "$scheme" ]; then
        mkdir -p "$LIBRARY_PATH/iphone/$scheme"
        cp -R "$altlist" "$LIBRARY_PATH/iphone/$scheme/AltList.framework"
        cp "$sandy" "$LIBRARY_PATH/iphone/$scheme/libsandy.dylib"
    fi
}

. "$ROOT/build-support/toolchain.sh"

legacy_args() {
    shadow_abi_require old rootful-legacy
    LEGACY_ENV=()
    if [ "$(uname -s)" = Darwin ]; then
        LEGACY_ENV=("DEVELOPER_DIR=$OLDABI_DEVELOPER_DIR")
    fi
    LEGACY_ARGS=()
    while IFS= read -r arg; do LEGACY_ARGS+=("$arg"); done < <(shadow_abi_args old)
}

modern_args() {
    MODERN_ARGS=()
    shadow_abi_require new "${1:-modern lane}"
}

prepare_scheme_framework() { # rootless
    local lane=$1
    # src/Shadow.framework/Makefile includes build-support/build-lanes.mk, which
    # derives ARCHS/TARGET/THEOS_PACKAGE_SCHEME from SHADOW_LANE -- so the scheme
    # matches the main build.
    make -C src/Shadow.framework "SHADOW_LANE=$lane" "${MAKE_PATHS[@]}" ${MODERN_ARGS[@]+"${MODERN_ARGS[@]}"}
    rm -rf "$LIBRARY_PATH/iphone/$lane/Shadow.framework"
    mkdir -p "$LIBRARY_PATH/iphone/$lane"
    cp -R src/Shadow.framework/.theos/obj/debug/Shadow.framework "$LIBRARY_PATH/iphone/$lane/"
}

last_package() {
    local package
    package=$(<.theos/last_package)
    case "$package" in
        /*) printf '%s\n' "$package" ;;
        *) printf '%s/%s\n' "$ROOT" "$package" ;;
    esac
}

copy_dependency_packages() { # profile
    local package
    [ -d "$PB/packages/$1" ] || return 0
    for package in "$PB/packages/$1"/*.deb; do
        [ -f "$package" ] && cp -p "$package" "$ROOT/build/"
    done
}

build_lane() { # profile
    local lane=$1 control="$STAGE/control.$1" package destination
    scripts/gen-control.sh "$lane" > "$control"
    [ "$lane" = rootful-legacy ] || modern_args
    stage_deps "$lane"
    make clean "SHADOW_LANE=$lane" "${MAKE_PATHS[@]}"

    case "$lane" in
        rootful-legacy)
            legacy_args
            env ${LEGACY_ENV[@]+"${LEGACY_ENV[@]}"} make package FINALPACKAGE=1 "SHADOW_LANE=$lane" "$CONTROL_VAR=$control" "${MAKE_PATHS[@]}" ${LEGACY_ARGS[@]+"${LEGACY_ARGS[@]}"}
            ;;
        rootful-modern)
            make package FINALPACKAGE=1 "SHADOW_LANE=$lane" "$CONTROL_VAR=$control" "${MAKE_PATHS[@]}" ${MODERN_ARGS[@]+"${MODERN_ARGS[@]}"}
            ;;
        rootless)
            prepare_scheme_framework "$lane"
            make package FINALPACKAGE=1 "SHADOW_LANE=$lane" "$CONTROL_VAR=$control" "${MAKE_PATHS[@]}" ${MODERN_ARGS[@]+"${MODERN_ARGS[@]}"}
            ;;
    esac

    package=$(last_package)
    destination="$ROOT/build/$(basename "$package")"
    cp -p "$package" "$destination"
    scripts/check-compat.sh "$lane" "$destination"
    # HookKit ABI drift advisory: Shadow links the Theos-installed HookKit
    # (build-support/hookkit.mk). This surfaces — but does not fail the build on
    # — a HookKit update that adds/removes/renames the ABI surface Shadow's
    # binding layer depends on, so it can be reviewed and adopted. Set
    # SHADOW_HOOKKIT_ABI_STRICT=1 to make drift fatal.
    if ! "$ROOT/scripts/check-hookkit-abi.sh" "$lane"; then
        if [ "${SHADOW_HOOKKIT_ABI_STRICT:-0}" = 1 ]; then
            echo "HookKit ABI drift is fatal (SHADOW_HOOKKIT_ABI_STRICT=1)" >&2
            return 1
        fi
        echo "WARNING: HookKit ABI drift detected for $lane (advisory; build continues)" >&2
    fi
    copy_dependency_packages "$lane"
}

build_quick() {
    stage_deps rootful-modern core
    modern_args
    make -C src/Shadow.framework SHADOW_LANE=rootful-modern "${MAKE_PATHS[@]}" ${MODERN_ARGS[@]+"${MODERN_ARGS[@]}"}
    make -C src/Shadow.dylib SHADOW_LANE=rootful-modern "${MAKE_PATHS[@]}" ${MODERN_ARGS[@]+"${MODERN_ARGS[@]}"}
    make -C src/ShadowCore.dylib SHADOW_LANE=rootful-modern "${MAKE_PATHS[@]}" ${MODERN_ARGS[@]+"${MODERN_ARGS[@]}"}
}

case ${1:-all} in
    rootful-legacy) build_lane rootful-legacy ;;
    rootful-modern) build_lane rootful-modern ;;
    rootful) build_lane rootful-legacy; build_lane rootful-modern ;;
    rootless) build_lane rootless ;;
    quick) build_quick ;;
    deps) stage_deps "${2:-rootful-modern}" ;;
    all) build_lane rootless; build_lane rootful-legacy; build_lane rootful-modern ;;
    *) echo "usage: $0 [all|rootful|rootful-legacy|rootful-modern|rootless|quick|deps PROFILE]" >&2; exit 2 ;;
esac
