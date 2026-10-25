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
    state.tar.zst
```

The manifest format is `ShadowAppState2`. Previous single-archive snapshots are
not accepted. It records Bundle ID, IDFV, title, note,
app version/build, backup date, container identities, and separate verification metadata for each archive. `data.tar.zst` contains
only application/group container trees. `state.tar.zst` contains bounded logical
exports: `keychain/records.plist`, `identity/state.plist`, and
`preferences/records.plist`. The identity payload contains complete fingerprint
data and configuration dictionaries without applying the current runtime configuration
schema; unknown fields and preference values are preserved. Container preference files remain in their
original paths in the data archive; the preferences payload also records scoped
iOS preference values for cache-coherent import and external preference domains. Restore locks the fingerprint through the backend.

A backup with the same IDFV updates that snapshot and retains title/note unless
explicitly supplied. Both staged archives must pass full verification before
publication together with their manifest. Existing directories are exchanged atomically with Darwin
`renameatx_np(RENAME_SWAP)`; the old snapshot is not deleted before publication.
Per-app file locks reject overlapping operations. Storage directories are private
and links are not accepted as storage nodes. On iOS the complete backup
storage tree belongs to `mobile:mobile` (UID/GID 501), with directories `0700`
and files `0600`, allowing mobile-context sync tools to access it. The privileged
helper retains authority over live app containers and Keychain operations; that
authority does not determine backup ownership. The store accepts explicit storage
UID/GID, while its default initializer uses the current effective UID/GID for host
fixtures. Existing root-owned backup trees are migrated once using descriptor-relative
traversal and per-app operation locks. Symlinks, hard-linked files, unexpected
owners/modes, and filesystem boundaries stop migration. Archive contents and
creation/modification timestamps are preserved. Container archive entries must match
the configured storage UID/GID and cannot carry set-user-ID or set-group-ID bits.
The store checks this before publication and again before accepting a saved
manifest, including manifests supplied by mobile-context sync tools. Unsupported
source ownership/permissions fail backup rather than creating an unusable snapshot.

## Archive and checks

`Archive` writes PAX tar with Zstandard level 3. Regular file contents are read in
128 KiB chunks. Every regular file has SHA-256 verification, including binary
files; each complete compressed archive also has SHA-256 and size verification.
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
filesystem image. Regular-file hard links within captured roots share one archived
content entry and are restored with their original inode relationship. Aliases
outside the captured roots are not enumerated or recreated; an in-scope file
remains a self-contained copy when its other aliases are outside the backup.
Special nodes are rejected. Container-manager metadata is excluded from capture and
preserved at the destination; the main app's `Library/SplashBoard` is excluded.
Internal absolute symbolic links are relocated to the current container roots.
External link text is retained without following it. Traversal, duplicate paths,
and link ancestors are rejected; extraction uses descriptor-relative operations.

## Backend and restore contract

The trusted backend must resolve only the selected installed app and authorized
containers/Keychain groups, reject unsafe shared scopes, stop the app and its
extensions, confirm they remain stopped, and flush their preference writers.
It must validate Keychain payloads before mutation and restore the exact authorized
scope. It must preserve fingerprint data/configuration dictionaries, including unknown
fields, and restore them plus the locked flag atomically. Backup/import checks
serialization and identity association rather than applying runtime configuration
field whitelists. It must not alter system IDFV storage. Backend methods
must report failures through `NSError`; progress callbacks should not mutate
the store or application state.

Restore verifies both complete archives and all payloads before clearing target files.
Before stopping or mutating the target, restore reads its current IDFV from the
backend. If it equals the selected snapshot's IDFV, restoration is rejected
regardless of `saveCurrent`, including a pending retry. A matching IDFV denotes
the active environment, whose subsequently generated data must be retained.
This comparison uses IDFV, not the displayed fingerprint digest. Optional saving
of a different current environment runs before restore mutations.

A pending record pins both archive hashes and is persisted before restore mutations. Files, Keychain, iOS preferences, and
fingerprint state are restored, then a final combined recheck compares live file
hashes/inventory, Keychain records, scoped preference values, and fingerprint values/lock state, with the
target still stopped. A failed restore may leave partial live data; it does not
claim rollback. Pending state blocks backing up that partial environment and
protects the restore source from editing/deletion, while permitting retry. The
core never launches an app automatically.

The coordinator stops the target before work and checks its state at phase
boundaries. Streaming progress only forwards progress events; it does not scan
processes for every file or data block. Final combined verification remains
mandatory.

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
backup failure prevents cleanup. Restore is unavailable when the selected backup
has the active IDFV. For a different IDFV, restore defaults to saving the live
environment; an interrupted restore retry never backs up its partial state.

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
