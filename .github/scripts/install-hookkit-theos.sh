#!/usr/bin/env bash
# Provision the maintained rootless HookKit build into the same Theos as Shadow.
set -euo pipefail

LANE=${1:-rootless}
if [ "$#" -gt 1 ] || [ "$LANE" != rootless ]; then
    echo "usage: install-hookkit-theos.sh [rootless]" >&2
    exit 2
fi
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
: "${THEOS:?THEOS must be set}"
selected_pin=$(python3 "$ROOT/scripts/hookkit-source.py" pin)
selected_repository=$(python3 "$ROOT/scripts/hookkit-source.py" repository)
if [ "${HOOKKIT:-$selected_pin}" != "$selected_pin" ] || \
   [ "${HOOKKIT_REPOSITORY:-$selected_repository}" != "$selected_repository" ]; then
    echo "HookKit overrides must match the maintained pin in .github/workflows/build.yml" >&2
    exit 2
fi
HOOKKIT=$selected_pin
. "$ROOT/build-support/lanes.sh"
shadow_lane_field "$LANE" ARCHS >/dev/null || exit 2

WORK=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/hookkit-theos.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

src=${DEPS_SOURCE_ROOT:-}/HookKit
if [ -e "$src/.git" ]; then
    git clone --quiet "$src" "$WORK/hookkit"
else
    git clone --quiet "https://github.com/$selected_repository.git" "$WORK/hookkit"
fi
git -C "$WORK/hookkit" checkout --quiet --detach "$HOOKKIT" 2>/dev/null || {
    git -C "$WORK/hookkit" fetch --quiet origin "$HOOKKIT"
    git -C "$WORK/hookkit" checkout --quiet --detach FETCH_HEAD
}
[ "$(git -C "$WORK/hookkit" rev-parse HEAD)" = "$HOOKKIT" ] || {
    echo "HookKit checkout does not match the maintained source pin" >&2
    exit 1
}

# Validate exact package pins before allowing a checkout to replace Theos files.
python3 "$ROOT/scripts/check-hookkit-version.py" \
    "$ROOT/packaging/controls/control.$LANE.in" \
    --source-control "$WORK/hookkit/packaging/layout/DEBIAN/control"

# Adapt only the pinned release's build configuration to upstream Theos.
# A changed dependency must pass the patch check before it can replace files.
git -C "$WORK/hookkit" apply --check "$ROOT/.github/patches/hookkit-upstream-theos.patch"
git -C "$WORK/hookkit" apply "$ROOT/.github/patches/hookkit-upstream-theos.patch"
mkdir -p "$WORK/hookkit/build-support/shadow"
cp "$ROOT/build-support/lanes.sh" "$ROOT/build-support/toolchain.sh" \
    "$ROOT/build-support/hookkit-lanes.sh" "$WORK/hookkit/build-support/shadow/"

if [ -f "$src/vendor/gum/frida-gum.h" ] && [ -f "$src/vendor/gum/libfrida-gum.a" ]; then
    cp "$src/vendor/gum/frida-gum.h" "$src/vendor/gum/libfrida-gum.a" "$WORK/hookkit/vendor/gum/"
    for stamp in "$src/vendor/gum"/.devkit-*; do
        [ ! -f "$stamp" ] || cp "$stamp" "$WORK/hookkit/vendor/gum/"
    done
fi

# Build and stage just this lane's framework into $THEOS at the location
# build-support/hookkit.mk resolves. install-theos.sh owns the lane -> path layout.
bash "$WORK/hookkit/tools/release/install-theos.sh" "$LANE"
framework=$(printf 'include %s\nshdw_print:\n\t@echo $(SHADOW_HOOKKIT_DIR)/HookKit.framework\n' \
    "$ROOT/build-support/hookkit.mk" | make -f - THEOS="$THEOS" SHADOW_LANE="$LANE" shdw_print)
python3 "$ROOT/scripts/hookkit-source.py" record "$framework" "$WORK/hookkit"
python3 "$ROOT/scripts/hookkit-source.py" check "$framework"
if [ -n "${HOOKKIT_PACKAGE_OUTPUT:-}" ]; then
    cp "$WORK/hookkit/.theos/release/hookkit-$LANE.deb" "$HOOKKIT_PACKAGE_OUTPUT"
fi
echo "provisioned HookKit ($HOOKKIT) for $LANE into $THEOS"
