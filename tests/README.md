# Shadow public tests

Public tests combine pure-C checks, static contract scripts, and a macOS-only
Foundation image-registry check. They need make, Bash,
a host C compiler, Python 3.7+, and standard shell tools; no device, Docker, iOS SDK, or engine
build is required. Lane/package checks use the local `build-support/lanes.sh`
and do not require Theos or the `THEOS` environment variable.

| Check | Command |
| --- | --- |
| runtime file identity (pure C) | `make -C tests verify-runtime-image-identity` |
| loaded-image registry (macOS Foundation; skipped on other hosts) | `make -C tests verify-loaded-image-registry` |
| svc path-rewrite (pure C) | `make -C tests verify-path-rewrite` |
| fresh fd/DIR path policy (host doubles) | `make -C tests verify-fd-path-freshness` |
| mount filtering (pure C + static query contract) | `make -C tests verify-mount-filter` |
| native HTTP/2 SETTINGS and header policy | `make -C tests verify-native-http2-policy` |
| native HTTP/2 branch-stub decoding | `make -C tests verify-native-http2-stubs` |
| native TLS bounded reads, allocation failure, peek and empty I/O | `make -C tests verify-native-tls-read` |
| prepared function original and bounded retry (host lifecycle doubles) | `make -C tests verify-prepared-original` |
| rebind journal/repair (pure C) | `make -C tests verify-rebind-repair` |
| KERN_PROCARGS2 payload filter (kernel-shaped payloads) | `make -C tests verify-procargs-filter` |
| exact HookKit package/framework version consistency | `make -C tests verify-hookkit-version` |
| upstream Theos toolchain and HookKit adapter | `make -C tests verify-toolchain` |
| lane/package contract | `sh tests/verify-lane-contract.sh` |
| binary compatibility checker (synthetic tool output) | `make -C tests verify-binary-compat` |
| hook→engine matrix drift | `sh tests/verify-hook-matrix.sh` |
| raw syscall metadata | `sh tests/verify-syscall-meta.sh` |
| settings structure | `sh tests/verify-settings-structure.sh` |
| JB-identifier data contract | `make -C tests jb-identifiers` |
| Debian numeric ownership and payload preservation | `make -C tests verify-deb-ownership` |
| package maintainer scripts | `sh tests/MaintainerScriptTests.sh` |

Run the public checks from the repository root:

```sh
make -C tests test
sh tests/MaintainerScriptTests.sh
```

The optional `make -C tests verify-curl-transport` requires macOS Foundation and
the pinned headers prepared by `scripts/prepare-curl-impersonate.sh`.
The active transport replaces TLS within the native connection. CFNetwork and
WebKit retain HTTP framing, headers, request bodies, redirects, authentication,
cookies and their own caches. Curl supplies handshake and encrypted byte I/O
through the native transport; it does not open a second external TCP connection.
Curl’s TLS connection filter calls the native byte-stream callbacks directly.
TLS buffering, nonblocking retry state and shutdown use curl’s existing backend;
there is no intermediate socketpair or ciphertext pump.
The native certificate-verification callback decides trust during the handshake.

The initialization tests exercise profile freezing, nonblocking loader reentry,
readiness publication, and loader, preset, TLS and HTTP/2 refusal paths. Networking
bootstrap tests cover launch identity, selected-profile propagation and hook
session publication. Network diagnostics tests cover native task forwarding,
stable task IDs, request/upload snapshots, metrics and disabled collection.
The diagnostic harnesses explicitly compile with `SHDW_TRANSPORT_DIAGNOSTICS=1`.
The default-off check invokes all diagnostic entry points and verifies no hooks,
frame scripts, cookie observations or trace-argument evaluation occur.
Device checks cover HTTP/2, native trust acceptance/rejection, cancellation,
redirected POST bodies, cookie storage, gzip delivery and cache-only reads after
a process restart. Abrupt EOF remains handled by the native stack. Runtime
private interfaces still require validation on each supported system.
Custom ALPN/TLS settings and server-requested client certificates need additional
coverage; preconfigured client identities remain on their native implementation.

Build with `SHADOW_CURL_IMPERSONATE=1 ./build.sh rootless` after preparing the
patched arm64 and arm64e dependency. The Manager's existing TLS fingerprint
switch saves `Network.Transport=auto`; missing settings default to `auto`, while
explicit `native` disables TLS fingerprinting.
Selection uses the saved system fingerprint version: below 18.0 selects
`safari172_ios`, 18.0 through 18.3 selects `safari180_ios`, 18.4 through 18.6
selects `safari184_ios`, and 18.7 or later selects `safari187_ios`.
App and Networking processes freeze the selected preset at startup.
The `safari187_ios` profile applies the issue #450 reference overrides, using the
same `CurlReference.h` helper as the standalone probe. Its name does not prove
exact OS-version or WKWebView equivalence. Native HTTP/2 remains responsible for
framing, HPACK and flow control. For this preset, generation hooks normalize the
initial SETTINGS and connection window and reorder request pseudo headers before
encoding; legacy priority submissions are suppressed. Only newly created native
client sessions are eligible, and subsequent window replenishment remains native.
Native entry discovery validates optimized branch stubs against the selected
system library. Stub patches preserve the original function bodies and pin the
validated bytes through preparation and commit. The current ABI guard requires system libapple_nghttp2 1.47.0; unknown versions
refuse installation. These hooks activate only after TLS installation succeeds.

The TLS preset does not select the User-Agent OS version. WebKit default UA
versions come from its native version-string generation entrypoint, before page
creation; Shadow does not call `setCustomUserAgent:`. App-provided custom UAs
keep their native priority. The matching WebContent launch snapshot covers
worker fallback generation. Host checks exercise the C++ return bridge and
bootstrap ownership; runtime entrypoints still require device verification.
The optional engine currently supports the rootless lane only.

`curl-reference-probe.c` is a standalone live experiment for the capture in
[impit issue #450](https://github.com/apify/impit/issues/450), also used by
[PR #465](https://github.com/apify/impit/pull/465). Compile it against the patched
curl-impersonate headers for the intended device architecture; it loads the
library dynamically. Invoke it as `probe library baseline|safari187_ios output.json`.
Both modes use verified HTTPS directly to Peet, with preset default headers
disabled. `safari187_ios` applies explicit TLS and HTTP/2 overrides to the
`safari184_ios` base. It does not register a Shadow profile or alter automatic
selection. The capture's actual OS version and its equivalence to WKWebView
are unverified; it is not an iOS 18.2 WKWebView reference.

Run `python3 tests/compare-curl-reference.py output.json` on the returned report.
The comparison checks hashes, raw fingerprint strings, ordered ciphers and
extension payloads, and HTTP/2 fingerprint fields. It normalizes per-connection
GREASE values and excludes the requested SNI and ephemeral key bytes; it is
not a byte-for-byte comparison of encrypted traffic. Live reports can contain
network identifiers and should remain outside the repository. This optional
live check is not part of `make test`.

The Makefile's `test` target does not include the maintainer-script checks.

The optional `make -C tests verify-fingerprint` requires macOS Foundation and
Xcode command-line tools, and HookKit headers installed under `$THEOS` as
resolved by `build-support/hookkit.mk`. It includes strict localization configuration and
central native-value resolution, process-local environment changes, calendar
consistency, and the native WebContent bootstrap, ownership checks, and function entrypoint adapter with HookKit doubles.
Localization behavior checks use AddressSanitizer and UndefinedBehaviorSanitizer.
They cover typed XPC payloads, missing and mismatched host identities, native
pass-through, prepared continuation publication, safe provider fallback, hook activation failures, and isolation from persistent system preferences. These checks do not
establish real WebContent sandbox access, iframe/Worker behavior, or UIKit
rendering; those require device verification.

The optional `make -C tests settings-behavior` compiles and executes the actual
settings customization/reset helpers, local version reader, symbol guard, release
parser, About getters, and Updates controller with Foundation and UI/network doubles.
It checks zero requests during pane construction/lifecycle, explicit checks and
retries, duplicate-click suppression, cancellation/stale callbacks, inline notes,
and release URL validation. The companion structure check covers all four locales
and removal of the old popup/action.
It requires macOS Foundation or a host GNUstep/libobjc2 toolchain. On Linux,
`make -C tests settings-behavior GNUSTEP_IMAGE=<image>` uses an existing Docker
image containing clang and GNUstep/libobjc2, with networking disabled. Tests use
an in-memory defaults double, not Shadow's domain. This check is not in `test`
or CI and does not exercise UIKit rendering, accessibility, or live networking.

The optional `make -C tests verify-cleanup` requires macOS Foundation and Xcode
command-line tools. It exercises cleanup traversal against temporary fixtures,
including category boundaries, receipt preservation, container metadata,
symlink and identity rejection, and detection of data left after cleanup.
Late application UI snapshots are removed in a scoped finalization stage before
the independent read-only recheck. Fixtures cover grouped snapshot directories,
unselected preservation, changed sessions and unsafe ancestor/leaf rejection.
Keychain doubles cover exact group scope, empty results, deletion without
intermediate readback, and final residual detection. When `ldid` is available,
it also checks signing and reading back an executable with exact access groups.
It also runs the actual application cleanup coordinator with a helper double to
check ordered execution, automatic unlock and lock restoration, fingerprint
enablement, optional fingerprint refresh,
failure propagation, and mandatory final verification. It does not delete data
from installed applications or exercise device Keychain permissions.

The optional `make -C tests verify-app-state` requires macOS Foundation, Xcode
command-line tools, and libarchive with Zstandard support. Homebrew installations
of `libarchive` and `zstd` are detected; alternate prefixes can be supplied with
`ARCHIVE_PREFIX` and `ZSTD_PREFIX`. It compiles the production archive/store code,
uses real temporary files and tar.zst archives, and runs functional checks with
AddressSanitizer and UndefinedBehaviorSanitizer. A separate unsanitized run checks
streaming progress and memory growth with many small files and a large file.
Keychain, process control, and fingerprint preferences use an isolated backend
double. A streaming regression fixture also verifies that process checks remain
bounded as file and progress-event counts grow, while backup, restore, and final
verification still succeed. These checks do not establish device permissions or application-level
restore correctness. See `src/AppState/README.md` for the core's integration scope
and optional iOS compile/link checks. This target is not part of `test` or CI.

`make -C tests verify-backups` adds production backup transport/coordinator and
native credential/fingerprint adapter checks to `verify-app-state`. These macOS
ASan/UBSan checks run a fixture child through the actual spawn/poll/NDJSON parser
(split frames, binary property lists, malformed/truncated/oversized responses,
exit failures, bounded timeout/reaping and operation exclusion). Native Security
queries/mutations, process authority, and preference persistence use test doubles:
exact group/class validation, unsupported credential classes, empty/ambiguous
results, replacement preflight, and a single fingerprint app-dictionary write are
verified without accessing the user's Keychain or installed apps. Native preference
API doubles also exercise global/container and AnyHost/CurrentHost import, unknown
configuration fields, unchanged-value no-op, stale-key removal, and synchronization
failures. Split archive checks cover missing/corrupt/swapped state packages and
pinning both archives during restore retries. The same target also runs `verify-app-state-client.py` against the shared SDK,
covering large stdin requests, private unlinked input, response bounds, malformed
frames, validation, timeout and unknown outcomes without automatic retry.
External helper fixtures check the exact mobile preference suite, absent versus
malformed identity, failed synchronization and capability negotiation. Transfer
fixtures use real archives to check manifest conflict rejection, pending-source
protection, corrupt import rejection and read-only storage opening.

This target
does not verify UIKit rendering or device entitlements and is not in `test` or CI.

CI's `.github/workflows/tests.yml` runs individual checks, including maintainer
scripts, rather than the aggregate target. It omits several aggregate checks,
including mount filtering and JB-identifier data validation. Consult that workflow
for the actual CI selection.

Mount checks cover record verdict handling and static wiring to the existing
snapshot matcher, including rule precedence and absence of refresh/resolution
in the query. They do not execute Foundation predicates or test device locking;
custom predicates that perform I/O are outside the mount-query contract.

Binary compatibility checks exercise the three supported lanes with synthetic Mach-O tool
output, including both deployment-load-command formats. They accept matching
architecture/deployment/ABI fixtures and reject mismatches and legacy lock imports. These test the checker, not actual iOS execution.
Packaged lane builds separately run the checker against their real binaries.

The full engine/detector/adversary/fuzz/device harness is private and
not part of this repo (no URL). The engine-linked batteries were removed
from `tests/Makefile`. For local harness discovery, follow `AGENTS.md`; neither
host checks nor an old harness executable verify the installed iOS harness UI.

`verify-process-stop.py` exercises the production termination barrier with deterministic process fixtures: delayed service flushes, natural exit, scoped SIGTERM, timeout before deletion, PID reuse, and unrelated/shared-container WebKit services. Device validation is still required for Darwin process inspection.
The cleanup engine fixture also covers notification extension containers and receipt removal without touching another extension.

Backup recovery regressions cover atomic tombstone deletion, per-snapshot corruption isolation, committed-IDFV verification-only finalization, added extension preference scopes, and scoped absolute symlink relocation. Installer tests ensure install does not create or change either preference store.

`make verify-fingerprint` also checks persisted IDFV reads, immutable process
snapshots, containing-app configuration for extensions, and scoped native
accessor consistency. These host checks use Foundation and runtime doubles;
private selector availability and actual hook installation require device checks.

AppState helper checks also cover stable machine error codes through the real
process transport, preserving source/POSIX codes and independent partial/unknown
flags. Core fixtures check busy locks, active/pending protection, damaged and
missing snapshots, and partial metadata updates. Native helper fixtures verify
that saved-snapshot deletion and full verification dispatch without live target
resolution. These checks do not establish live device permissions.

The optional AppState check also runs verify-state-transition-wait.py. It extracts
the production native wait method and uses real monotonic time to confirm the
three-second and one-second minimum waits, with controlled process/authority
loss during waiting. The storage fixture separately traces real archive
capture/restore/synchronization calls and injects interrupted waits, restarted
targets and data reappearing after clear. It also changes 12 shared-memory header
bytes after extraction and confirms restore and pending finalization do not
rehash live container files. New captures omit per-file digests and repeated
post-pack validation, while whole-archive digests and legacy checksum reading
remain covered. Saved archive integrity checks before restore remain enabled. No installed app or phone is touched.
