# App state core

This standalone Foundation module implements snapshot storage, streaming archives,
and backup/restore coordination. It is not yet linked into Shadow Manager or its
privileged helper. It does not change installed apps by itself. A device adapter
must implement `SHDWAppStateBackend` before product integration.

## Storage and identity

```text
ShadowBackups/<BundleID>/
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

## Build and verification

Host checks use real archive/filesystem code and isolated doubles for device
authority, process control, Keychain, and fingerprint preferences:

```sh
make -C tests verify-app-state
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
it does not package or install an app. Host and compile/link checks do not verify
live iOS permissions, Keychain entitlement behavior, file protection, or app
compatibility after restore. Those remain device integration work before release.
