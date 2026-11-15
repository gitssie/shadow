#!/usr/bin/env python3
"""One-time France localization backfill for phone-owned Shadow snapshots.

Requires paramiko and the zstd CLI on the host. Dry-run is the default. Original
manifest/state bytes and a journal are kept in a new private --work-dir. Publish
uses the installed helper's importState operation, never direct device writes.
"""
import argparse
import base64
import collections
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import tarfile
import uuid

FRANCE = {"Region": "FR", "Language": "fr-FR", "TimeZone": "Europe/Paris"}
PAYLOADS = {"identity/state.plist", "keychain/records.plist", "preferences/records.plist"}
MAX_STATE = 64 * 1024 * 1024
MAX_TAR = 64 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _decompress(state):
    # zstd reads a private temporary input; limit decompressed bytes before tar parsing.
    import tempfile
    with tempfile.TemporaryFile() as source:
        source.write(state)
        source.seek(0)
        with subprocess.Popen(["zstd", "-q", "-d", "-c"], stdin=source,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            raw = process.stdout.read(MAX_TAR + 1)
            if len(raw) > MAX_TAR:
                process.kill()
                process.communicate()
                raise ValueError("State archive exceeds decompressed size limit")
            message = process.stderr.read()
            if process.wait():
                raise ValueError("Cannot decompress state archive: " + message.decode(errors="replace"))
            return raw


def repair_snapshot(manifest_bytes, state_bytes):
    """Return replacement manifest/state, or None for an explicit localization."""
    manifest = plistlib.loads(manifest_bytes)
    if manifest.get("owner", "phone") != "phone":
        raise ValueError("RV-owned snapshots must be repaired by RV")
    info = manifest["stateArchiveInfo"]
    if manifest.get("format") != "ShadowAppState2" or info.get("sourceRoots") != {}:
        raise ValueError("Unsupported snapshot state format")
    if len(state_bytes) > MAX_STATE or len(state_bytes) != info["archiveSize"] or sha256(state_bytes) != info["sha256"]:
        raise ValueError("Original state archive checksum/size mismatch")
    entries = info["entries"]
    if len(entries) != len(PAYLOADS) or {e["path"] for e in entries} != PAYLOADS:
        raise ValueError("Unexpected state payload scope")
    with tarfile.open(fileobj=io.BytesIO(_decompress(state_bytes)), mode="r:") as source:
        members = source.getmembers()
        if len(members) != len(PAYLOADS) or {m.name for m in members} != PAYLOADS:
            raise ValueError("Unexpected tar members")
        payloads = {}
        for member in members:
            entry = next(e for e in entries if e["path"] == member.name)
            if not member.isfile() or entry.get("type") != "file" or entry.get("hardlink") or member.size > 16 * 1024 * 1024:
                raise ValueError("Invalid state payload")
            payload = source.extractfile(member).read()
            if len(payload) != entry["size"] or ("sha256" in entry and sha256(payload) != entry["sha256"]):
                raise ValueError("Original state payload checksum/size mismatch")
            payloads[member.name] = payload
    identity = plistlib.loads(payloads["identity/state.plist"])
    configuration = identity["configuration"]
    if not isinstance(configuration, dict) or not isinstance(identity.get("data"), dict):
        raise ValueError("Invalid saved fingerprint")
    if identity["data"].get("VendorIdentifier") != manifest["idfv"]:
        raise ValueError("Saved fingerprint identity mismatch")
    if "Localization" in configuration:
        return None
    changed = copy.deepcopy(identity)
    changed["configuration"]["Localization"] = dict(FRANCE)
    payloads["identity/state.plist"] = plistlib.dumps(changed, fmt=plistlib.FMT_BINARY, sort_keys=False)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as target:
        for member in members:
            member = copy.deepcopy(member)
            payload = payloads[member.name]
            member.size = len(payload)
            if "size" in member.pax_headers:
                member.pax_headers["size"] = str(member.size)
            target.addfile(member, io.BytesIO(payload))
    state = subprocess.run(["zstd", "-q", "-3", "-c"], input=raw.getvalue(),
                           capture_output=True, check=True).stdout
    if len(state) > MAX_STATE:
        raise ValueError("Replacement state archive exceeds size limit")
    updated = copy.deepcopy(manifest)
    info = updated["stateArchiveInfo"]
    info["sha256"] = sha256(state)
    info["archiveSize"] = len(state)
    entry = next(e for e in info["entries"] if e["path"] == "identity/state.plist")
    entry["size"] = len(payloads["identity/state.plist"])
    if "sha256" in entry:
        entry["sha256"] = sha256(payloads["identity/state.plist"])
    return plistlib.dumps(updated, fmt=plistlib.FMT_BINARY, sort_keys=False), state


class HelperError(RuntimeError):
    def __init__(self, response):
        self.response = response
        super().__init__(response.get("error", "Backup helper failed"))


class Device:
    def __init__(self, options):
        import paramiko
        self.client = paramiko.SSHClient()
        self.client.load_host_keys(str(Path(options.known_hosts).expanduser()))
        self.client.connect(options.host, port=options.port, username=options.user,
                            password=os.environ[options.password_env], look_for_keys=False,
                            allow_agent=False, timeout=15)
        self.bundle = options.bundle

    def close(self):
        self.client.close()

    def invoke(self, action, request):
        data = plistlib.dumps(request, fmt=plistlib.FMT_BINARY)
        argument = "-" if action == "importState" else base64.b64encode(data).decode()
        command = shlex.join(["/var/jb/usr/libexec/shadow-cleaner", "state", self.bundle, action, argument])
        stdin, stdout, stderr = self.client.exec_command(command, timeout=180)
        if action == "importState":
            stdin.write(data)
            stdin.flush()
        stdin.channel.shutdown_write()
        frames = [json.loads(line) for line in stdout if line.strip()]
        failure = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        if not frames or "ok" not in frames[-1]:
            raise RuntimeError("Helper result missing; do not retry a publication without checking the journal")
        terminal = frames[-1]
        if not terminal["ok"]:
            raise HelperError(terminal)
        if code:
            raise RuntimeError("Helper exited unsuccessfully: " + failure)
        return plistlib.loads(base64.b64decode(terminal["result"], validate=True))

    def catalog(self):
        items, offset = [], 0
        while True:
            page = self.invoke("queryCatalog", {"offset": offset, "limit": 200, "refresh": False})
            if page["restorePending"]:
                raise RuntimeError("Finish pending restoration before repairing snapshots")
            items.extend(page["items"])
            if not page["hasMore"]:
                break
            if page["nextOffset"] <= offset:
                raise RuntimeError("Catalog cursor did not advance")
            offset = page["nextOffset"]
        if len({item["idfv"] for item in items}) != len(items):
            raise RuntimeError("Catalog changed during scan; run again before applying")
        return items

    def export(self, identifier):
        first = self.invoke("exportState", {"idfv": identifier, "part": "manifest", "requester": "phone"})
        manifest = plistlib.loads(first["data"])
        if manifest.get("owner", "phone") != "phone":
            raise RuntimeError("Snapshot is no longer phone-owned")
        state = self.invoke("exportState", {"idfv": identifier, "part": "state",
                                          "stateSHA": manifest["stateArchiveInfo"]["sha256"], "requester": "phone"})
        if state["manifestSHA"] != first["manifestSHA"] or sha256(first["data"]) != first["manifestSHA"]:
            raise RuntimeError("Snapshot changed during export")
        return first["data"], state["data"]

    def publish(self, identifier, manifest, state, expected_sha):
        return self.invoke("importState", {"idfv": identifier, "manifest": manifest,
                                          "state": state, "expectedManifestSHA": expected_sha,
                                          "requester": "phone"})


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_journal(work, journal):
    temporary = work / "journal.next"
    write_private(temporary, json.dumps(journal, indent=2).encode())
    os.replace(temporary, work / "journal.json")
    sync_directory(work)


def run(options):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", options.bundle):
        raise ValueError("Invalid application identifier")
    if options.limit is not None and options.limit < 1:
        raise ValueError("Repair limit must be positive")
    if not shutil.which("zstd"):
        raise RuntimeError("Install the zstd CLI on the host first")
    work = Path(options.work_dir).expanduser().resolve()
    work.mkdir(mode=0o700, parents=False, exist_ok=False)
    sync_directory(work.parent)
    device = Device(options)
    journal = {"bundleID": options.bundle, "apply": options.apply, "entries": [], "counts": {}}
    counts = collections.Counter()
    try:
        items = device.catalog()
        for item in items:
            if options.apply and options.limit is not None and counts["repaired"] >= options.limit:
                break
            if item.get("owner", "phone") != "phone":
                counts["rv_skipped"] += 1
                continue
            config = item.get("Fingerprint_Config")
            if not isinstance(config, dict):
                raise ValueError("A catalog fingerprint configuration is missing")
            if "Localization" in config:
                counts["already_configured"] += 1
                continue
            identifier = item["idfv"]
            if str(uuid.UUID(identifier)).upper() != identifier:
                raise ValueError("Invalid snapshot identifier")
            counts["candidates"] += 1
            if not options.apply:
                continue
            manifest, state = device.export(identifier)
            replacement = repair_snapshot(manifest, state)
            if replacement is None:
                counts["changed_since_scan"] += 1
                continue
            new_manifest, new_state = replacement
            folder = work / identifier
            folder.mkdir(mode=0o700)
            write_private(folder / "manifest.original.plist", manifest)
            write_private(folder / "state.original.tar.zst", state)
            write_private(folder / "manifest.repaired.plist", new_manifest)
            write_private(folder / "state.repaired.tar.zst", new_state)
            sync_directory(folder)
            entry = {"idfv": identifier, "originalManifestSHA": sha256(manifest),
                     "repairedManifestSHA": sha256(new_manifest), "phase": "publishing"}
            journal["entries"].append(entry)
            journal["counts"] = dict(counts)
            save_journal(work, journal)
            device.publish(identifier, new_manifest, new_state, sha256(manifest))
            actual_manifest, actual_state = device.export(identifier)
            if actual_manifest != new_manifest or actual_state != new_state:
                raise RuntimeError("Published snapshot differs; inspect journal before continuing")
            entry["phase"] = "verified"
            counts["repaired"] += 1
            journal["counts"] = dict(counts)
            save_journal(work, journal)
            print("Verified repairs:", counts["repaired"], flush=True)
        remaining = device.catalog() if options.apply else items
        if options.apply:
            remaining_phone = [item for item in remaining if item.get("owner", "phone") == "phone"
                               and isinstance(item.get("Fingerprint_Config"), dict)
                               and "Localization" not in item["Fingerprint_Config"]]
            counts["remaining_phone_missing"] = len(remaining_phone)
            if remaining_phone and options.limit is None:
                raise RuntimeError("Some phone-owned configurations still need repair")
        journal["counts"] = dict(counts)
        journal["completed"] = True
        save_journal(work, journal)
        print(json.dumps(dict(counts), sort_keys=True), flush=True)
    except Exception:
        journal["counts"] = dict(counts)
        journal["completed"] = False
        save_journal(work, journal)
        raise
    finally:
        device.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=2222)
    parser.add_argument("--user", default="mobile")
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--password-env", default="SHADOW_DEVICE_PASSWORD")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--work-dir", required=True, help="New private host directory outside the checkout")
    parser.add_argument("--apply", action="store_true", help="Publish repairs; otherwise report candidates only")
    parser.add_argument("--limit", type=int, help="Limit repairs for an initial verified batch")
    options = parser.parse_args()
    try:
        run(options)
    except Exception as error:
        parser.exit(1, "Repair stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
