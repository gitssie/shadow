# Public tests: pure-C checks + static contract scripts only. The full
# engine-linked harness (detector/adversary/fuzz/device batteries) lives
# in the private repo; see tests/README.md.

# Pure-C check for the svc path-munging logic (path_rewrite.c — no
# Foundation, so it compiles and runs on any host, macOS or Linux).
verify-path-rewrite:
	$(CC) -std=c99 -Wall -Wextra -o /tmp/shadow-rewrite-test \
		verify-path-rewrite.c ../src/ShadowCore.dylib/hooks/Universal/path_rewrite.c
	/tmp/shadow-rewrite-test

# Host check of the actual fstatat/faccessat hook bodies with policy doubles.
verify-at-path-rewrite:
	python3 verify-at-path-rewrite.py

# Host check of the actual lexical path standardizer with pinned spellings.
verify-path-standardize:
	python3 verify-path-standardize.py

# Host check of the actual fresh fd/DIR path-policy bodies with mutation doubles.
verify-fd-path-freshness:
	python3 verify-fd-path-freshness.py

# Host check of the actual process-policy bodies (classification caches, pid
# list compaction, MIB classifier, boot-args answer) with kinfo doubles.
verify-proc-policy:
	python3 verify-proc-policy.py

# Host check of the actual raw-SVC add-image callback and initializer bodies.
verify-svc-self-image:
	python3 verify-svc-self-image.py

# Pure-C mount-record filter.
verify-mount-filter:
	$(CC) -std=c99 -Wall -Wextra -o /tmp/shadow-mount-filter-test \
		verify-mount-filter.c
	/tmp/shadow-mount-filter-test

# Host check of the restricted-image span and svc branch-encoding decisions:
# extracts the real bodies (and their constants) from the hook sources and
# drives them with synthetic Mach-O images.
verify-image-span:
	python3 verify-image-span.py

# Pure-C check for the anti-fishhook journal/repair core (rebind_slots.h).
verify-rebind-repair:
	$(CC) -std=c99 -Wall -Wextra -o /tmp/shadow-rebind-test \
		verify-rebind-repair.c
	/tmp/shadow-rebind-test
	$(CC) -std=c99 -Wall -Wextra -Werror verify-rebind-import-index.c -o /tmp/shadow-rebind-import-index-test
	/tmp/shadow-rebind-import-index-test

THEOS ?= /opt/theos

# Static contract checks (CWD-agnostic: every script cds to the repo root).
lane-contract:
	sh verify-lane-contract.sh

hook-matrix:
	sh verify-hook-matrix.sh

syscall-meta:
	sh verify-syscall-meta.sh

settings-structure:
	sh verify-settings-structure.sh

# Optional Foundation check; not a dependency of the portable host suite.
settings-behavior:
	python3 verify-settings-behavior.py $(if $(GNUSTEP_IMAGE),--docker $(GNUSTEP_IMAGE),)

.PHONY: settings-behavior

verify-fingerprint:
	python3 verify-manager-apps.py
	python3 verify-fingerprint-manager.py
	python3 verify-fingerprint-config-runtime.py
	python3 verify-fingerprint-digest.py
	python3 verify-fingerprint-raw-memory.py
	python3 verify-fingerprint-system-version.py
	python3 verify-fingerprint-idfv.py
	python3 verify-fingerprint-storage.py
	python3 verify-map-defaults.py
	python3 verify-fingerprint-interfaces.py
	python3 verify-receipts.py
	python3 verify-fingerprint-memory.py
	python3 verify-fingerprint-version.py
	python3 verify-fingerprint-webkit.py
	python3 verify-web-clipboard.py

.PHONY: verify-fingerprint

verify-cleanup:
	python3 verify-cleanup-engine.py
	python3 verify-cleanup-service.py

.PHONY: verify-cleanup

# Optional macOS integration check of the actual AppState archive and store.
verify-app-state:
	python3 verify-app-state.py

.PHONY: verify-app-state

# Compile the identifier arrays and check their data and consumer wiring.
jb-identifiers:
	python3 verify-jb-identifiers.py

verify-environment-storage:
	python3 verify-environment-storage.py

verify-rules-generation:
	python3 verify-rules-generation.py

verify-binary-compat:
	bash BinaryCompatTests.sh

test: verify-path-rewrite verify-at-path-rewrite verify-path-standardize verify-fd-path-freshness verify-proc-policy verify-svc-self-image verify-image-span verify-mount-filter verify-rebind-repair lane-contract hook-matrix syscall-meta settings-structure jb-identifiers verify-environment-storage verify-rules-generation verify-binary-compat

clean:
	rm -f harness harness.d

.PHONY: test verify-path-rewrite verify-at-path-rewrite verify-path-standardize verify-fd-path-freshness verify-proc-policy verify-svc-self-image verify-image-span verify-mount-filter verify-rebind-repair lane-contract hook-matrix syscall-meta settings-structure jb-identifiers verify-environment-storage verify-rules-generation verify-binary-compat clean

# Optional CoreFoundation host check of the shared image-header index.
image-header-index:
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread -framework CoreFoundation ImageHeaderIndexTests.c -o /tmp/shadow-image-header-index-test
	/tmp/shadow-image-header-index-test

.PHONY: image-header-index

rebind-image-scheduler:
	python3 verify-rebind-image-scheduler.py
	python3 verify-rebind-session.py
	python3 verify-dyld-load-order.py

.PHONY: rebind-image-scheduler

network-queries:
	python3 verify-network-queries.py

.PHONY: network-queries
