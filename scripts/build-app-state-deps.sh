#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
. "$ROOT/build-support/app-state.sh"
app_state_initialize "${1:-rootless}"

ARCHIVE_VERSION=3.8.10
ARCHIVE_SHA256=56cad765459d5ee25a3b761f90c47d99379d28297fbfb72d908880d6b875fb96
ZSTD_VERSION=1.5.7
ZSTD_SHA256=eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3
CMAKE=${CMAKE:-cmake}
command -v "$CMAKE" >/dev/null || { echo 'cmake is required' >&2; exit 1; }
mkdir -p "$AS_PREBUILT/sources"

download() {
    local url=$1 path=$2 expected=$3 actual
    if [ ! -f "$path" ]; then
        curl -fL --retry 2 "$url" -o "$path.download"
        mv -f "$path.download" "$path"
    fi
    actual=$(shasum -a 256 "$path"); actual=${actual%% *}
    [ "$actual" = "$expected" ] || { echo "Source checksum mismatch: $path" >&2; exit 1; }
}
download "https://github.com/libarchive/libarchive/releases/download/v$ARCHIVE_VERSION/libarchive-$ARCHIVE_VERSION.tar.xz" "$AS_PREBUILT/sources/libarchive.tar.xz" "$ARCHIVE_SHA256"
download "https://github.com/facebook/zstd/releases/download/v$ZSTD_VERSION/zstd-$ZSTD_VERSION.tar.gz" "$AS_PREBUILT/sources/zstd.tar.gz" "$ZSTD_SHA256"
if [ ! -d "$AS_PREBUILT/sources/libarchive-$ARCHIVE_VERSION" ]; then
    tar -xf "$AS_PREBUILT/sources/libarchive.tar.xz" -C "$AS_PREBUILT/sources"
fi
if [ ! -d "$AS_PREBUILT/sources/zstd-$ZSTD_VERSION" ]; then
    tar -xf "$AS_PREBUILT/sources/zstd.tar.gz" -C "$AS_PREBUILT/sources"
fi

for arch in $AS_ARCHS; do
    deploy=$(app_state_deployment "$arch")
    prefix="$AS_PREBUILT/$AS_LANE/$arch"
    work="$AS_PREBUILT/work/$AS_LANE/$arch"
    stamp="libarchive=$ARCHIVE_VERSION zstd=$ZSTD_VERSION arch=$arch deploy=$deploy sdk=$AS_SDKROOT"
    if [ -f "$prefix/.stamp" ] && [ "$(cat "$prefix/.stamp")" = "$stamp" ] && [ -f "$prefix/lib/libarchive.a" ] && [ -f "$prefix/lib/libzstd.a" ]; then
        echo "AppState dependencies ready: $AS_LANE/$arch"
        continue
    fi
    mkdir -p "$prefix" "$work"
    common=(-DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT="$AS_SDKROOT"
        -DCMAKE_OSX_ARCHITECTURES="$arch" -DCMAKE_OSX_DEPLOYMENT_TARGET="$deploy"
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix"
        -DCMAKE_TRY_COMPILE_TARGET_TYPE=EXECUTABLE -DCMAKE_POLICY_VERSION_MINIMUM=3.5
        -DCMAKE_C_FLAGS='-fvisibility=hidden -ffunction-sections -fdata-sections')
    "$CMAKE" -S "$AS_PREBUILT/sources/zstd-$ZSTD_VERSION/build/cmake" -B "$work/zstd" "${common[@]}" \
        -DZSTD_BUILD_PROGRAMS=OFF -DZSTD_BUILD_TESTS=OFF -DZSTD_BUILD_SHARED=OFF \
        -DZSTD_BUILD_STATIC=ON -DZSTD_MULTITHREAD_SUPPORT=OFF -DZSTD_LEGACY_SUPPORT=OFF
    "$CMAKE" --build "$work/zstd" --parallel "${APP_STATE_JOBS:-4}"
    "$CMAKE" --install "$work/zstd"
    "$CMAKE" -S "$AS_PREBUILT/sources/libarchive-$ARCHIVE_VERSION" -B "$work/archive" "${common[@]}" \
        -DBUILD_SHARED_LIBS=OFF -DENABLE_TEST=OFF -DENABLE_TAR=OFF -DENABLE_CPIO=OFF \
        -DENABLE_CAT=OFF -DENABLE_UNZIP=OFF -DENABLE_INSTALL=ON -DENABLE_ZSTD=ON -DENABLE_ACL=OFF \
        -DZSTD_INCLUDE_DIR="$prefix/include" -DZSTD_LIBRARY="$prefix/lib/libzstd.a" \
        -DENABLE_ZLIB=OFF -DENABLE_BZip2=OFF -DENABLE_LZMA=OFF -DENABLE_LZ4=OFF \
        -DENABLE_OPENSSL=OFF -DENABLE_MBEDTLS=OFF -DENABLE_NETTLE=OFF -DENABLE_LIBB2=OFF \
        -DENABLE_LIBXML2=OFF -DENABLE_EXPAT=OFF -DENABLE_ICONV=OFF -DENABLE_PCREPOSIX=OFF
    "$CMAKE" --build "$work/archive" --parallel "${APP_STATE_JOBS:-4}"
    "$CMAKE" --install "$work/archive"
    printf '%s\n' "$stamp" > "$prefix/.stamp"
done
