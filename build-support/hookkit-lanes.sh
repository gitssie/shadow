#!/usr/bin/env bash
# Build-only adapter for the pinned HookKit release; installed in its temp checkout.
_shadow_support=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
. "$_shadow_support/lanes.sh"
. "$_shadow_support/toolchain.sh"
theos_lane_field() { shadow_lane_field "$@"; }
theos_abi_require() { shadow_abi_require "$@"; }
theos_abi_args() { shadow_abi_args "$@"; }
if [ "${BASH_SOURCE[0]}" = "$0" ] && [ "${1:-}" = get ] && [ "$#" -eq 3 ]; then
    shadow_lane_field "$2" "$3"
fi
