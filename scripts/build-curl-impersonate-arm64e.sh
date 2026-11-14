#!/usr/bin/env bash
# Build one rootless iOS slice. All sources/dependencies/outputs stay in BUILD_ROOT.
set -euo pipefail
revision=5b1c3542fc7fc0e9fe623a6c9a848d16f92fe99a
project_root=$(cd "$(dirname "$0")/.." && pwd)
. "$project_root/build-support/lanes.sh"
deployment_target=$(shadow_lane_field rootless FLOOR)
architecture=${2:-arm64e}
case " $(shadow_lane_field rootless ARCHS) " in
    *" $architecture "*) ;;
    *) echo "Unsupported rootless architecture: $architecture" >&2; exit 1 ;;
esac
build_root=${1:-${TMPDIR:-/tmp}/shadow-curl-arm64e}
mkdir -p "$build_root"
build_root=$(cd "$build_root" && pwd -P)
jobs=${JOBS:-8}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo 'JOBS must be positive' >&2; exit 1; }
for tool in git cmake ninja python3 xcrun; do command -v "$tool" >/dev/null; done
source_dir="$build_root/upstream"
if [[ ! -d "$source_dir/.git" ]]; then
    if [[ -n "${CURL_IMPERSONATE_SOURCE:-}" ]]; then
        git clone --no-hardlinks "$CURL_IMPERSONATE_SOURCE" "$source_dir"
        git -C "$source_dir" checkout --detach "$revision"
    else
        git clone --depth 1 --branch v2.3.2 https://github.com/lexiforest/curl-impersonate.git "$source_dir"
    fi
fi
[[ $(git -C "$source_dir" rev-parse HEAD) == "$revision" ]] || { echo 'Unexpected upstream revision' >&2; exit 1; }
# Upstream forwards the SDK but omits architecture/flags for dependency builds.
# Adjust build wiring only; preserve every upstream impersonation patch.
python3 - "$source_dir" <<'PY'
from pathlib import Path
import hashlib
import subprocess
import sys
source = Path(sys.argv[1])
for name, digest in {
    'curl.patch': '34c92d564b8d348d655191b65b46c1c3f3bf74d2530f69920083e93a8cdf2662',
    'boringssl.patch': 'c8852fe2814b8f75d150af9c5c2edc6e2fc42b53b6329e2c01699377fe44c795',
}.items():
    if hashlib.sha256((source / 'patches' / name).read_bytes()).hexdigest() != digest:
        raise SystemExit('Unexpected upstream patch: ' + name)
path = source / 'CMakeLists.txt'
original = subprocess.check_output(['git', '-C', str(source), 'show', 'HEAD:CMakeLists.txt'], text=True)
needle = 'set(_toolchain_cmake_args)'
addition = '''
foreach(_arm64e_setting CMAKE_OSX_ARCHITECTURES CMAKE_C_FLAGS CMAKE_CXX_FLAGS CMAKE_ASM_FLAGS)
  if(DEFINED ${_arm64e_setting})
    list(APPEND _toolchain_cmake_args "-D${_arm64e_setting}=${${_arm64e_setting}}")
  endif()
endforeach()'''
expected = original.replace(needle, needle + addition)
if path.read_text() not in (original, expected):
    raise SystemExit('Refusing to overwrite unrelated upstream CMake edits')
path.write_text(expected)
PY
sdk=$(xcrun --sdk iphoneos --show-sdk-path)
cmake -S "$source_dir" -B "$build_root/build" -G Ninja \
    -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_SYSTEM_PROCESSOR="$architecture" \
    -DCMAKE_OSX_ARCHITECTURES="$architecture" -DCMAKE_OSX_SYSROOT="$sdk" \
    -DCMAKE_OSX_DEPLOYMENT_TARGET="$deployment_target" \
    -DCMAKE_C_COMPILER="$(xcrun --find clang)" \
    -DCMAKE_CXX_COMPILER="$(xcrun --find clang++)" \
    "-DCMAKE_C_FLAGS=-target $architecture-apple-ios$deployment_target -fPIC" \
    "-DCMAKE_CXX_FLAGS=-target $architecture-apple-ios$deployment_target -fPIC" \
    -DDISABLE_BORINGSSL_ASM=ON -DUSE_LIBIDN2=OFF \
    -DCURL_IMPERSONATE_VERSION=2.3.2 -DSUBJOBS="$jobs" \
    -DCMAKE_INSTALL_PREFIX="$build_root/install"
cmake --build "$build_root/build" --parallel 4
python3 - "$build_root" "$project_root/build-support/patches/curl-connect-only-raw-http2.patch" <<'PATCH_PY'
from pathlib import Path
import subprocess
import sys
source = Path(sys.argv[1]) / 'build/deps/src/curl'
patch = str(Path(sys.argv[2]).resolve())
reverse = subprocess.run(['patch', '-p1', '--batch', '--force', '--fuzz=0', '--dry-run', '-R', '-i', patch],
                         cwd=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if reverse.returncode:
    previous = Path(sys.argv[1]) / 'applied-native-tls.patch'
    if previous.exists() and previous.read_bytes() != Path(patch).read_bytes():
        can_revert = subprocess.run(['patch', '-p1', '--batch', '--force', '--fuzz=0',
                                     '--dry-run', '-R', '-i', str(previous)], cwd=source,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if can_revert.returncode == 0:
            subprocess.run(['patch', '-p1', '--batch', '--force', '--fuzz=0', '-R',
                            '-i', str(previous)], cwd=source, check=True)
    subprocess.run(['patch', '-p1', '--batch', '--forward', '--fuzz=0', '-i', patch], cwd=source, check=True)
(Path(sys.argv[1]) / 'applied-native-tls.patch').write_bytes(Path(patch).read_bytes())
PATCH_PY
cmake --build "$build_root/build/deps/build/curl" --parallel 4
cmake --install "$build_root/build/deps/build/curl"
cmake --install "$build_root/build"
cmake -P "$build_root/build/CollectLicenses.cmake"
mkdir -p "$build_root/install/licenses"
cp "$build_root/build/licenses/"* "$build_root/install/licenses/"
python3 - "$build_root" "$revision" "$sdk" "$deployment_target" "$architecture" "$project_root/build-support/patches/curl-connect-only-raw-http2.patch" <<'PY'
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
root = Path(sys.argv[1])
library = root / 'install/lib/libcurl-impersonate.4.8.0.dylib'
magic, cpu, subtype = struct.unpack_from('<III', library.read_bytes())
architecture = sys.argv[5]
expected_subtype = 0x80000002 if architecture == 'arm64e' else 0
assert magic == 0xfeedfacf and cpu == 0x100000c and subtype == expected_subtype, 'Wrong iOS Mach-O architecture'
exports = subprocess.check_output(['xcrun', 'nm', '-gU', str(library)], text=True)
for name in ['curl_easy_impersonate', 'curl_easy_init', 'curl_easy_setopt', 'curl_easy_perform',
             'curl_easy_getinfo', 'curl_easy_cleanup', 'curl_global_init', 'curl_slist_append',
             'curl_slist_free_all', 'curl_easy_strerror',
             'curl_shadow_connect_only_get_alpn', 'curl_shadow_connect_only_get_tls_snapshot',
             'curl_shadow_connect_only_shutdown_write', 'curl_shadow_connect_only_enable_external_io',
             'curl_shadow_connect_only_set_native_verify', 'curl_shadow_connect_only_get_verification_snapshot',
             'curl_shadow_connect_only_get_io_state', 'curl_shadow_connect_only_set_transport',
             'curl_shadow_connect_only_shutdown']:
    assert '_' + name in exports, 'Missing export: ' + name
identity = subprocess.check_output(['xcrun', 'otool', '-D', str(library)], text=True)
assert '@rpath/libcurl-impersonate.4.dylib' in identity, 'Unexpected install name'
for name in ['cares', 'zlib', 'zstd', 'brotli', 'nghttp2', 'boringssl', 'nghttp3', 'ngtcp2', 'curl']:
    cache = (root / 'build/deps/build' / name / 'CMakeCache.txt').read_text()
    assert 'CMAKE_OSX_ARCHITECTURES:STRING=' + architecture in cache, 'Wrong dependency architecture: ' + name
    assert architecture + '-apple-ios' + sys.argv[4] in cache, 'Wrong dependency target: ' + name
manifest = {'upstreamRevision': sys.argv[2], 'sdk': sys.argv[3], 'architecture': architecture,
            'deploymentTarget': sys.argv[4], 'boringSSLAssembly': False,
            'nativeTLSPatchSHA256': hashlib.sha256(Path(sys.argv[6]).read_bytes()).hexdigest(),
            'library': library.name, 'sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
            'requestHeaders': 'Use curl_easy_impersonate default_headers=0 to preserve request headers'}
(root / 'install/build-provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(library)
print(json.dumps(manifest, indent=2))
PY
