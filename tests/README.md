# Shadow public tests

Public tests are pure-C checks plus static contract scripts. They need make, Bash,
a host C compiler, Python 3.7+, and standard shell tools; no device, Docker, iOS SDK, or engine
build is required. The lane/package contract also requires `THEOS` to point to a
directory containing `bin/lane.sh`; a full Theos installation is not required.

| Check | Command |
| --- | --- |
| svc path-rewrite (pure C) | `make -C tests verify-path-rewrite` |
| fresh fd/DIR path policy (host doubles) | `make -C tests verify-fd-path-freshness` |
| mount filtering (pure C + static query contract) | `make -C tests verify-mount-filter` |
| rebind journal/repair (pure C) | `make -C tests verify-rebind-repair` |
| lane/package contract | `sh tests/verify-lane-contract.sh` |
| binary compatibility checker (synthetic tool output) | `make -C tests verify-binary-compat` |
| hook→engine matrix drift | `sh tests/verify-hook-matrix.sh` |
| raw syscall metadata | `sh tests/verify-syscall-meta.sh` |
| settings structure | `sh tests/verify-settings-structure.sh` |
| JB-identifier data contract | `make -C tests jb-identifiers` |
| package maintainer scripts | `sh tests/MaintainerScriptTests.sh` |

Run the public checks from the repository root:

```sh
make -C tests test
sh tests/MaintainerScriptTests.sh
```

The Makefile's `test` target does not include the maintainer-script checks.

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
double. These checks do not establish device permissions or application-level
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
verified without accessing the user's Keychain or installed apps. This target
does not verify UIKit rendering or device entitlements and is not in `test` or CI.

CI's `.github/workflows/tests.yml` runs individual checks, including maintainer
scripts, rather than the aggregate target. It omits several aggregate checks,
including mount filtering and JB-identifier data validation. Consult that workflow
for the actual CI selection.

Mount checks cover record verdict handling and static wiring to the existing
snapshot matcher, including rule precedence and absence of refresh/resolution
in the query. They do not execute Foundation predicates or test device locking;
custom predicates that perform I/O are outside the mount-query contract.

Binary compatibility checks exercise all four lanes with synthetic Mach-O tool
output, including both deployment-load-command formats. They accept matching
architecture/deployment/ABI fixtures and reject mismatches, legacy lock imports,
and invalid RootHide linking. These test the checker, not actual iOS execution.
Packaged lane builds separately run the checker against their real binaries.

The full engine/detector/adversary/fuzz/device harness is private and
not part of this repo (no URL). The engine-linked batteries were removed
from `tests/Makefile`. For local harness discovery, follow `AGENTS.md`; neither
host checks nor an old harness executable verify the installed iOS harness UI.
