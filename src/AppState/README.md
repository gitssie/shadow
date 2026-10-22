# App state core

This Foundation module implements snapshot storage, streaming archives, and
backup/restore coordination. Shadow Manager's middle archive tab calls the
installed privileged cleaner helper. Its native `SHDWAppStateBackend` adapter
resolves the selected application, controls its processes, and delegates scoped
credential and fingerprint operations to mobile-context workers. The archive
module itself has no UIKit or device-service dependency.

## Storage and identity

```text
/private/var/mobile/Library/ShadowBackups/<BundleID>/
  .lock
  pending.plist                  # only while a restore is incomplete
  snapshots/<canonical-IDFV>/
    manifest.plist
    data.tar.zst
```

The manifest format is `ShadowAppState1`. It records Bundle ID, IDFV, title, note,
app version/build, backup date, container identities, and archive verification
metadata. Archive members include container trees, `keychain/records.plist`, and
`identity/state.plist`. The identity payload contains complete fingerprint data
and configuration dictionaries. Restore locks the fingerprint through the backend.

A backup with the same IDFV updates that snapshot and retains title/note unless
explicitly supplied. A staged snapshot must pass full verification before
publication. Existing directories are exchanged atomically with Darwin
`renameatx_np(RENAME_SWAP)`; the old snapshot is not deleted before publication.
Per-app file locks reject overlapping operations. Storage directories are private
and links are not accepted as storage nodes.

## Archive and checks

`Archive` writes PAX tar with Zstandard level 1. Regular file contents are read in
128 KiB chunks. Every regular file has SHA-256 verification, including binary
files; the complete compressed archive also has SHA-256 and size verification.
Recheck streams the archive without extracting a temporary copy. Metadata is
proportional to the entry count; small serialized identity/Keychain payloads are
bounded at 16 MiB each. This is not constant total memory for arbitrary inventories.

Capture/restore supports regular files, directories, and symbolic links, with
POSIX mode, UID/GID, modification time, and Darwin creation time. Timestamp
seconds and nanoseconds are retained. Archived times are restored for files and
subdirectories; the system-managed container root does not receive archived
creation/modification times. Container content operations can naturally change
its modification time. An internal PAX annotation preserves creation times that
libarchive's standard creation-time field omits (including equal/later creation
times); it is archive metadata and is never installed as an app extended attribute.
The module does **not** preserve extended
attributes, filesystem ACLs, or iOS file protection classes. It is not a complete
filesystem image. Hard links are captured as independent regular files. Special
nodes are rejected. Container-manager metadata is excluded from capture and
preserved at the destination; the main app's `Library/SplashBoard` is excluded.
Internal absolute symbolic links are relocated to the current container roots.
External link text is retained without following it. Traversal, duplicate paths,
and link ancestors are rejected; extraction uses descriptor-relative operations.

## Backend and restore contract

The trusted backend must resolve only the selected installed app and authorized
containers/Keychain groups, reject unsafe shared scopes, stop the app and its
extensions, confirm they remain stopped, and flush their preference writers.
It must validate Keychain payloads before mutation and restore the exact authorized
scope. It must validate fingerprint data and restore data/configuration plus the
locked flag atomically. It must not alter system IDFV storage. Backend methods
must report failures through `NSError`; progress callbacks should not mutate
the store or application state.

Restore verifies the complete archive and payloads before clearing target files.
Optional saving of the current environment runs first. If its IDFV equals the
selected snapshot's IDFV, `saveCurrent=YES` is rejected to avoid overwriting the
restore source; callers must explicitly choose `saveCurrent=NO`.

A pending record is persisted before restore mutations. Files, Keychain, and
fingerprint state are restored, then a final combined recheck compares live file
hashes/inventory, Keychain records, and fingerprint values/lock state, with the
target still stopped. A failed restore may leave partial live data; it does not
claim rollback. Pending state blocks backing up that partial environment and
protects the restore source from editing/deletion, while permitting retry. The
core never launches an app automatically.

The device adapter currently exports generic/internet password records; nonempty
certificate, private-key, or identity classes are rejected before restore writes.
Shared/unverifiable container or Keychain ownership is rejected. Ambiguous success
with a NULL export result is an error; item-not-found and typed empty arrays are
valid empty results. Fingerprint writes run as mobile, preserve unrelated app
fields, and save data/configuration/lock in one app-dictionary write. The helper
retains its caller's real UID so the manager can stop its process group on timeout.

The app uses a single operation gate for backups, restoration, cleanup, and manual
fingerprint refresh. Existing same-IDFV backups are updated rather than duplicated.
Cleanup of an already backed-up environment offers backup-first/direct/cancel;
backup failure prevents cleanup. Restore defaults to saving the live environment,
except same-IDFV and pending-recovery cases, which cannot overwrite their source.

## Build and verification

Host checks use real archive/filesystem code and isolated doubles for device
authority, process control, Keychain, and fingerprint preferences:

```sh
make -C tests verify-app-state
make -C tests verify-backups
```

They require macOS, Xcode command-line tools, and libarchive with Zstandard support
(for example, Homebrew `libarchive` and `zstd`). `ARCHIVE_PREFIX` and `ZSTD_PREFIX`
override dependency locations. Functional checks use ASan/UBSan; a separate
unsanitized workload checks many small files and streaming memory/progress.

Optional iOS cross-compilation uses the existing lane definitions and Theos SDK
selection. One modern lane is built at a time:

```sh
scripts/build-app-state-deps.sh rootless
scripts/build-app-state-core.sh rootless
```

Set `THEOS` as for other repository builds. `PREBUILT_ROOT` and `SDKROOT` may
override dependency storage and the SDK. Dependency sources are checksum-pinned
and built outside the source tree; core outputs go under ignored `build/app-state`.
The compile/link check force-loads the core against static libarchive/Zstandard;
it does not package or install an app. Normal modern-lane dependency provisioning
also builds these libraries; packaged builds link them into the cleaner helper.
Host and compile/link checks do not verify live iOS permissions, Keychain
entitlement behavior, file protection, UIKit rendering, or app compatibility after
restore. Those require device verification before release.
