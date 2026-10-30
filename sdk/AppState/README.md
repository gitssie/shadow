# Shadow AppState client

This Foundation-only SDK invokes the installed Shadow helper on demand. It does
not start a daemon or access backup files. Shadow Manager and external adapters
compile `SHDWAppStateClient.m`; all storage rules remain in Shadow AppState.

Call `invokeAction:bundleIdentifier:request:progress:error:` on a worker queue.
Progress executes on that queue. UI callers dispatch progress/completion to their
UI queue. Resolve the package-owned helper path using the consuming product's
bootstrap path API. The client checks the installed helper's file authority;
missing or incompatible Shadow is an error, without a legacy implementation fallback.

External adapters first request `capabilities` and require API version 1, format
`ShadowAppState2`, and the requested operation in `operations`.

| Action | Request | Result |
| --- | --- | --- |
| capabilities | empty dictionary | apiVersion, format, operations |
| externalCatalog | empty dictionary | bundle_id, current_idfv, backups |
| externalEdit | idfv, metadata containing title/note | edited |
| exportState | idfv, part (manifest/state), stateSHA for state | data (NSData), manifestSHA, stateSHA, dataSHA |
| importState | idfv, manifest/state (NSData), expectedManifestSHA | imported |

The current_idfv empty string represents absent identity in the property-list
transport. JSON adapters translate it to null. Malformed identity is an error.
Catalog entries retain Shadow's unavailable and recovery flags. A catalog does
not perform full archive verification.

Exports are bounded to 16 MiB for the manifest and 64 MiB for state. Imports are
sent through a private unlinked stdin file rather than process arguments. The
complete import must fit the 96 MiB encoded request bound. Import compares the
original manifest hash under the app lock, protects pending recovery sources,
validates both archives and payloads, then publishes the complete snapshot with
an atomic directory exchange. Application data is copied locally, not uploaded.
No live application state is restored by import.

No mutation is automatically retried. `outcomeUnknown` means the caller must
inspect the snapshot before deciding on another explicit operation. HTTP chunk
staging belongs to the network adapter; partial chunks never publish files.

Consumers pin a Shadow revision, compile only this SDK, and call the installed
Shadow execution entry. A pinned SDK revision does not imply the installed helper
supports it; capability negotiation remains required. Public HTTP field names,
authentication, operation IDs, and streaming remain in the consuming product.

Verification: `make -C tests verify-backups` exercises real archive/store code,
SDK process transport, Manager coordination and native adapter doubles. Device
permissions and real application restore behavior require separate device checks.
