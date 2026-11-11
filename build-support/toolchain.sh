#!/usr/bin/env bash
# Toolchain checks for upstream Theos. Modern dependencies require macOS/Xcode.
shadow_abi_require() { # <old|new> [context]
    local abi=$1 ctx=${2:-$1} version major
    case "$abi" in
        new)
            [ "$(uname -s)" = Darwin ] || {
                echo "error: $ctx requires macOS/Xcode 12 or newer" >&2; return 1;
            }
            version=$(xcodebuild -version) || return 1
            major=$(printf '%s\n' "$version" | awk 'NR == 1 { split($2, v, "."); print v[1] }')
            [ "${major:-0}" -ge 12 ] || {
                echo "error: $ctx requires Xcode 12 or newer" >&2; return 1;
            }
            ;;
        old)
            if [ "$(uname -s)" = Darwin ]; then
                : "${OLDABI_DEVELOPER_DIR:?set OLDABI_DEVELOPER_DIR to Xcode 11.7/Contents/Developer}"
                DEVELOPER_DIR="$OLDABI_DEVELOPER_DIR" xcodebuild -version | grep -q '^Xcode 11\.7$' || {
                    echo "error: OLDABI_DEVELOPER_DIR must select Xcode 11.7" >&2; return 1;
                }
                return 0
            fi
            local toolchain=${OLDABI_TOOLCHAIN:-$THEOS/toolchain/oldabi/linux/iphone}
            local sdks=${OLDABI_SDKS:-$THEOS/sdks}
            [ -x "$toolchain/bin/clang" ] && [ -d "$sdks/iPhoneOS13.7.sdk" ] || {
                echo "error: $ctx requires OLDABI_TOOLCHAIN and OLDABI_SDKS (iPhoneOS13.7.sdk)" >&2; return 1;
            }
            version=$("$toolchain/bin/clang" -dumpversion) || return 1
            major=${version%%.*}
            [ "$major" -lt 12 ] || {
                echo "error: $ctx requires Clang older than 12 for the old arm64e ABI" >&2; return 1;
            }
            ;;
        *) echo "unknown ABI '$abi'" >&2; return 1 ;;
    esac
}

shadow_abi_args() { # <old|new>; one make assignment per line
    case "$1" in
        new) ;;
        old)
            [ "$(uname -s)" != Darwin ] || return 0
            printf '%s\n' "SDKBINPATH=${OLDABI_TOOLCHAIN:-$THEOS/toolchain/oldabi/linux/iphone}/bin" \
                "THEOS_SDKS_PATH=${OLDABI_SDKS:-$THEOS/sdks}"
            ;;
        *) echo "unknown ABI '$1'" >&2; return 1 ;;
    esac
}
