#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST=${SHADOW_CURL_ROOT:-${PREBUILT_ROOT:-$ROOT/../prebuilt}/curl-impersonate/2.3.2/ios}
ARCHIVE=$(mktemp "${TMPDIR:-/tmp}/shadow-curl.XXXXXX")
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/shadow-curl-stage.XXXXXX")
trap 'rm -f "$ARCHIVE"; rm -rf "$STAGE"' EXIT
curl -fL --retry 2 https://github.com/lexiforest/curl-impersonate/releases/download/v2.3.2/libcurl-impersonate-v2.3.2.arm64-apple-ios.tar.gz -o "$ARCHIVE"
python3 - "$ARCHIVE" <<'PY'
import hashlib, sys
from pathlib import Path
expected = "670e8d1c6c8ebd422b95bd25421ef9de3772bec4f9dfda95477a63c06c6596a5"
assert hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest() == expected, "curl-impersonate archive checksum mismatch"
PY
tar -xzf "$ARCHIVE" -C "$STAGE"
BUILD_ROOT=${SHADOW_CURL_BUILD_ROOT:-${TMPDIR:-/tmp}/shadow-curl-arm64e}
"$ROOT/scripts/build-curl-impersonate-arm64e.sh" "$BUILD_ROOT"
ARM64_BUILD_ROOT=${SHADOW_CURL_ARM64_BUILD_ROOT:-${TMPDIR:-/tmp}/shadow-curl-arm64}
"$ROOT/scripts/build-curl-impersonate-arm64e.sh" "$ARM64_BUILD_ROOT" arm64
xcrun lipo -create "$ARM64_BUILD_ROOT/install/lib/libcurl-impersonate.4.8.0.dylib" \
    "$BUILD_ROOT/install/lib/libcurl-impersonate.4.8.0.dylib" -output "$STAGE/libcurl-impersonate.4.dylib"
install_name_tool -id '@loader_path/libcurl-impersonate.4.dylib' "$STAGE/libcurl-impersonate.4.dylib"
ldid -S "$STAGE/libcurl-impersonate.4.dylib"
python3 "$ROOT/scripts/check-curl-impersonate.py" "$STAGE/libcurl-impersonate.4.dylib"
mkdir -p "$DEST"
cp -R "$STAGE/include" "$DEST/"
cp "$STAGE/libcurl-impersonate.4.dylib" "$DEST/libcurl-impersonate.4.dylib.tmp"
mv "$DEST/libcurl-impersonate.4.dylib.tmp" "$DEST/libcurl-impersonate.4.dylib"
cp "$STAGE"/LICENSE* "$DEST/"
cp "$BUILD_ROOT/install/licenses/"LICENSE* "$DEST/"
cp "$BUILD_ROOT/install/build-provenance.json" "$DEST/arm64e-build-provenance.json"
cp "$ARM64_BUILD_ROOT/install/build-provenance.json" "$DEST/arm64-build-provenance.json"
printf '%s\n' 'Prepared curl-impersonate 2.3.2 (iOS arm64 + arm64e)'
