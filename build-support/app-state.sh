#!/usr/bin/env bash
# Standalone AppState builds consume the same lane and SDK definitions as Shadow.
app_state_initialize() {
    AS_ROOT=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
    : "${THEOS:?Set THEOS to the lane-aware Theos checkout}"
    . "$AS_ROOT/build-support/lanes.sh"
    AS_LANE=$1
    case "$AS_LANE" in
        rootful-modern|rootless|roothide) ;;
        *) echo "AppState requires a modern lane" >&2; return 1 ;;
    esac
    AS_ARCHS=$(shadow_lane_field "$AS_LANE" ARCHS)
    local target
    target=$(shadow_lane_field "$AS_LANE" TARGET)
    IFS=: read -r _ _ AS_SDK_VERSION AS_TARGET_DEPLOY <<< "$target"
    AS_SDKROOT=${SDKROOT:-${THEOS_SDKS_PATH:-$THEOS/sdks}/iPhoneOS${AS_SDK_VERSION}.sdk}
    [ -d "$AS_SDKROOT" ] || { echo "Missing lane SDK: $AS_SDKROOT" >&2; return 1; }
    AS_PREBUILT=${PREBUILT_ROOT:-$AS_ROOT/../prebuilt}/app-state
}
app_state_deployment() {
    local value
    value=$(shadow_lane_field "$AS_LANE" DEPLOY)
    if [ "$1" = arm64e ]; then
        local specific
        specific=$(shadow_lane_field "$AS_LANE" DEPLOY_ARM64E)
        value=${specific:-$value}
    fi
    printf '%s\n' "${value:-$AS_TARGET_DEPLOY}"
}
