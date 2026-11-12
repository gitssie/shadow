#!/usr/bin/env bash
# Provision the pinned HookKit into $THEOS for one Shadow lane. HookKit is
# consumed from the Theos install (see build-support/hookkit.mk), not vendored, so CI runs
# this before build-deps.sh/build.sh. Local developers manage their own Theos
# HookKit (HookKit repo: make install-theos) and do not need this.
set -euo pipefail

LANE=${1:?usage: install-hookkit-theos.sh <rootful-legacy|rootful-modern|rootless>}
: "${THEOS:?THEOS must be set}"
: "${HOOKKIT:?HOOKKIT pin must be set}"
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
. "$ROOT/build-support/lanes.sh"
shadow_lane_field "$LANE" ARCHS >/dev/null || exit 2

WORK=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/hookkit-theos.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# Prefer a local co-dev checkout (DEPS_SOURCE_ROOT/HookKit) so an unpushed pin
# resolves; otherwise clone the public repo. A pinned SHA can be unreachable
# from any ref (rewritten history), so fall back to fetch-by-SHA.
src=${DEPS_SOURCE_ROOT:-}/HookKit
if [ -d "$src/.git" ]; then
    git clone --quiet "$src" "$WORK/hookkit"
else
    git clone --quiet https://github.com/jjolano/HookKit "$WORK/hookkit"
fi
git -C "$WORK/hookkit" checkout --quiet --detach "$HOOKKIT" 2>/dev/null || {
    git -C "$WORK/hookkit" fetch --quiet origin "$HOOKKIT"
    git -C "$WORK/hookkit" checkout --quiet --detach FETCH_HEAD
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
if [ -n "${HOOKKIT_PACKAGE_OUTPUT:-}" ]; then
    cp "$WORK/hookkit/.theos/release/hookkit-$LANE.deb" "$HOOKKIT_PACKAGE_OUTPUT"
fi
echo "provisioned HookKit ($HOOKKIT) for $LANE into $THEOS"
