#!/usr/bin/env python3
"""Repair real production snapshots, then import them through the production store."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import io
import os
import plistlib
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
BID = "example.state.fixture"
IDFV = "11111111-1111-4111-8111-111111111111"
LOCALIZATION = {"Region": "FR", "Language": "fr-FR", "TimeZone": "Europe/Paris"}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAIN = r'''
int main(int argc,const char **argv){@autoreleasepool{
    Check(argc==3,@"arguments");NSString *base=@(argv[1]),*mode=@(argv[2]);
    NSString *root=[base stringByAppendingPathComponent:@"store"],*data=[base stringByAppendingPathComponent:@"data"];
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];
    backend.target=@{@"bundleID":BID,@"token":@"repair-fixture",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};
    NSMutableDictionary *fingerprint=[FP(A,@"saved",NO) mutableCopy];
    fingerprint[@"configuration"]=@{@"region":@"saved",@"enabled":@YES,@"futureSetting":@{@"opaque":@"preserved",@"values":@[@1,@2]}};
    fingerprint[@"resetBaseline"]=@{@"Version":@1,@"Containers":@{BID:@{@"Identity":[@"a" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0],@"Seconds":@999000000,@"Nanoseconds":@123456789}}};
    backend.fingerprint=fingerprint;backend.keychain=@[@{@"account":@"saved",@"data":Bytes(@"credential")}];backend.preferences=@{@"saved":Bytes(@"preferences")};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,@"create store");
    if([mode isEqual:@"create"]){Mk(data);Put(data,@"Documents/value",Bytes(@"untouched application data"));Check([store backupBundle:BID metadata:nil error:&error]!=nil,[NSString stringWithFormat:@"capture: %@",error]);}
    else {
        NSString *path=SnapshotPath(root,A,@"");NSData *old=Get(path,@"manifest.plist");
        NSData *manifest=Get(base,@"candidate-manifest.plist"),*state=Get(base,@"candidate-state.tar.zst");
        Check(![store importBundle:BID idfv:A manifest:manifest state:state expectedManifestSHA:@"0000000000000000000000000000000000000000000000000000000000000000" error:&error],@"stale CAS accepted");
        Check([old isEqual:Get(path,@"manifest.plist")],@"stale CAS changed manifest");error=nil;
        Check([store importBundle:BID idfv:A manifest:manifest state:state expectedManifestSHA:DigestData(old) error:&error],[NSString stringWithFormat:@"import repaired state: %@",error]);
        Check([store recheckBundle:BID idfv:A error:&error],@"production archive verification");
        NSDictionary *query=[store queryCatalogBundle:BID query:@{@"region":@"FR"} error:&error];
        Check([query[@"total"] unsignedIntegerValue]==1,@"region query missed imported FR configuration");
        NSDictionary *entry=[query[@"items"] firstObject];
        Check([entry[@"Fingerprint_Config"][@"Localization"] isEqual:@{@"Region":@"FR",@"Language":@"fr-FR",@"TimeZone":@"Europe/Paris"}],@"index configuration stale");
    }return 0;}}
'''


def unpack(state):
    raw = subprocess.run(["zstd", "-q", "-d", "-c"], input=state, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        return [(member, archive.extractfile(member).read() if member.isfile() else None)
                for member in archive.getmembers()]


def repack(manifest, members):
    """Build valid adversarial/legacy inputs independently of the repair implementation."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for member, payload in members:
            member = copy.copy(member)
            if payload is not None:
                member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload) if payload is not None else None)
    state = subprocess.run(["zstd", "-q", "-c"], input=raw.getvalue(), capture_output=True, check=True).stdout
    manifest = copy.deepcopy(manifest)
    info = manifest["stateArchiveInfo"]
    info["sha256"], info["archiveSize"] = hashlib.sha256(state).hexdigest(), len(state)
    for member, payload in members:
        if payload is not None:
            entry = next((e for e in info["entries"] if e["path"] == member.name), None)
            if entry is None:
                continue
            entry["size"] = len(payload)
            if "sha256" in entry:
                entry["sha256"] = hashlib.sha256(payload).hexdigest()
    return plistlib.dumps(manifest, fmt=plistlib.FMT_BINARY), state


def rejected(repair, manifest, state, label):
    try:
        repair(manifest, state)
    except (ValueError, RuntimeError):
        return
    raise AssertionError("accepted " + label)


def main():
    production = load("state_fixture", ROOT / "tests/verify-app-state.py")
    repair = load("localization_repair", ROOT / "scripts/repair-backup-localization.py").repair_snapshot
    prefix = production.archive_prefix()
    with tempfile.TemporaryDirectory(prefix="shadow-localization-repair-") as directory:
        base = Path(directory)
        harness = base / "main.m"
        harness.write_text(production.HARNESS[:production.HARNESS.rindex("int main(")] + MAIN)
        binary = base / "fixture"
        command = ["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-deprecated-declarations", "-O1", "-framework", "Foundation", "-I" + str(prefix / "include"), "-I" + str(ROOT / "src/AppState"), "-L" + str(prefix / "lib"), "-Wl,-rpath," + str(prefix / "lib"), str(harness)]
        command += [str(ROOT / "src/AppState" / name) for name in ("Archive.m", "State.m", "Index.m")]
        zstd = os.environ.get("ZSTD_PREFIX") or next((p for p in ("/opt/homebrew/opt/zstd", "/usr/local/opt/zstd") if Path(p, "lib").is_dir()), None)
        if zstd:
            command += ["-L" + str(Path(zstd) / "lib"), "-Wl,-rpath," + str(Path(zstd) / "lib")]
        subprocess.run(command + ["-larchive", "-lzstd", "-lsqlite3", "-o", str(binary)], check=True)
        subprocess.run([str(binary), str(base), "create"], check=True)
        snapshot = base / "store" / BID / "snapshots" / IDFV
        manifest_bytes = (snapshot / "manifest.plist").read_bytes()
        state = (snapshot / "state.tar.zst").read_bytes()
        data = (snapshot / "data.tar.zst").read_bytes()
        manifest = plistlib.loads(manifest_bytes)
        members = unpack(state)
        payloads = {m.name: p for m, p in members if p is not None}
        original_identity = plistlib.loads(payloads["identity/state.plist"])
        fixed_manifest, fixed_state = repair(manifest_bytes, state)
        fixed = plistlib.loads(fixed_manifest)
        unchanged = copy.deepcopy(fixed)
        unchanged["stateArchiveInfo"] = manifest["stateArchiveInfo"]
        assert unchanged == manifest, "changed manifest outside state archive info"
        after = {m.name: p for m, p in unpack(fixed_state) if p is not None}
        identity = plistlib.loads(after["identity/state.plist"])
        assert identity["configuration"].pop("Localization") == LOCALIZATION
        assert identity == original_identity, "changed identity/data or other configuration"
        assert set(after) == set(payloads)
        for name in payloads:
            if name != "identity/state.plist":
                assert after[name] == payloads[name], name + " payload changed"
        assert repair(fixed_manifest, fixed_state) is None, "repair is not idempotent"
        for localization in ({}, {"Region": "native"}, LOCALIZATION, {"Region": "US"}):
            identity = copy.deepcopy(original_identity)
            identity["configuration"]["Localization"] = localization
            changed = [(m, plistlib.dumps(identity) if m.name == "identity/state.plist" else p) for m, p in members]
            candidate = repack(manifest, changed)
            assert repair(*candidate) is None, "overwrote existing Localization"
        legacy = copy.deepcopy(manifest)
        next(e for e in legacy["stateArchiveInfo"]["entries"] if e["path"] == "identity/state.plist")["sha256"] = hashlib.sha256(payloads["identity/state.plist"]).hexdigest()
        legacy_manifest, legacy_state = repair(plistlib.dumps(legacy), state)
        legacy_payload = dict((m.name, p) for m, p in unpack(legacy_state))["identity/state.plist"]
        assert next(e for e in plistlib.loads(legacy_manifest)["stateArchiveInfo"]["entries"] if e["path"] == "identity/state.plist")["sha256"] == hashlib.sha256(legacy_payload).hexdigest()
        bad = copy.deepcopy(manifest)
        bad["owner"] = "rv"
        rejected(repair, plistlib.dumps(bad), state, "RV-owned snapshot")
        bad = copy.deepcopy(manifest)
        bad["stateArchiveInfo"]["sha256"] = "0" * 64
        rejected(repair, plistlib.dumps(bad), state, "wrong archive SHA")
        bad = copy.deepcopy(manifest)
        next(e for e in bad["stateArchiveInfo"]["entries"] if e["path"] == "identity/state.plist")["sha256"] = "0" * 64
        rejected(repair, plistlib.dumps(bad), state, "wrong identity SHA")
        malicious = copy.deepcopy(members)
        malicious[0][0].name = "../escape"
        rejected(repair, *repack(manifest, malicious), "archive traversal")
        (base / "candidate-manifest.plist").write_bytes(fixed_manifest)
        (base / "candidate-state.tar.zst").write_bytes(fixed_state)
        subprocess.run([str(binary), str(base), "import"], check=True)
        assert (snapshot / "data.tar.zst").read_bytes() == data, "data archive changed"
        assert (snapshot / "manifest.plist").read_bytes() == fixed_manifest
        print("backup localization repair: production capture/import, CAS, FR index search, payload preservation, existing values, legacy hashes and invalid archives passed")


if __name__ == "__main__":
    main()
