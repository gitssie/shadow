"""Run the production stable digest against normalized fixtures and independent vectors."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
profile = root / "src/Shadow.framework/Fingerprint"
keys = ["deviceType", "deviceModel", "displayResolution", "displayScale",
        "memorySize", "processorCount", "biometryType"]
sample = dict(zip(keys, ["iPhone", "D17AP", "1170.0x2532.0", "3.0",
                         "3824435200", "6", "Face ID"]))
expected_sample = "bd670022eea922cd69ce70db4ffdfaa520d0bb6c2c7c1f2b57b886922253bd95"


def hash_text(value):
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        encoded = b""
    return hashlib.sha256(encoded).hexdigest()


def expected(inputs):
    if not isinstance(inputs, dict) or any(not isinstance(inputs.get(key), str) for key in keys):
        return "<nil>"
    empty = hash_text("")
    hardware = hash_text("".join(hash_text(inputs[key]) for key in keys[:6]))
    authentication = hash_text(hash_text(inputs["biometryType"]))
    return hash_text("".join([empty, hardware, empty, empty, empty, authentication]))


assert expected(sample) == expected_sample
cases = [sample, dict(reversed(list(sample.items()))), {**sample, "ignored": "anything"}]
for key in keys:
    for value in ["", "Undefined", "aéz", "设备", "Face ID\n", "x\0y", " ", "[]"]:
        cases.append({**sample, key: value})
    for invalid in [None, 0, True, [], {}]:
        cases.append({**sample, key: invalid})
    missing = dict(sample)
    missing.pop(key)
    cases.append(missing)
cases += [None, [], "wrong", {key: "" for key in keys}]
# These adversarial roots distinguish omitted groups, raw digest bytes and a
# single authentication hash from the required tree structure.
empty = hash_text("")
hardware = hash_text("".join(hash_text(sample[key]) for key in keys[:6]))
biometry_leaf = hash_text(sample["biometryType"])
wrong_roots = [hash_text(hardware + hash_text(biometry_leaf)),
               hash_text(empty + hardware + empty * 3 + biometry_leaf),
               hashlib.sha256(bytes.fromhex(empty + hardware + empty * 3 + hash_text(biometry_leaf))).hexdigest()]
assert expected_sample not in wrong_roots
source = r'''
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#include <assert.h>
#include <stdio.h>
NSDictionary *SHDWFingerprintInputsForData(NSDictionary *data) { (void)data; return nil; }
'''
source += (profile / "Profile.h").read_text()
source += "\n" + "\n".join(line for line in (profile / "Profile.m").read_text().splitlines()
                            if not line.startswith("#import"))
source += r'''
int main(void) { @autoreleasepool {
  NSData *input = [NSFileHandle.fileHandleWithStandardInput readDataToEndOfFile];
  NSArray *cases = [NSJSONSerialization JSONObjectWithData:input options:0 error:NULL];
  assert([cases isKindOfClass:NSArray.class]);
  NSMutableArray *results = [NSMutableArray new];
  for (id value in cases) {
    NSString *result = [SHDWFingerprintProfile stableFingerprintForInputs:value];
    [results addObject:result ?: @"<nil>"];
  }
  NSData *output = [NSJSONSerialization dataWithJSONObject:results options:0 error:NULL];
  assert(output);
  fwrite(output.bytes, 1, output.length, stdout);
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-digest-tests-") as tmp:
    tmp = Path(tmp)
    src, binary = tmp / "test.m", tmp / "test"
    src.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-Wno-deprecated-declarations", "-fsanitize=address,undefined",
                    "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    result = subprocess.run([str(binary)], input=json.dumps(cases).encode(), stdout=subprocess.PIPE, check=True)
    actual = json.loads(result.stdout)
    assert len(actual) == len(cases)
    for index, (value, observed) in enumerate(zip(cases, actual)):
        assert observed == expected(value), (index, value, observed, expected(value))
print(f"fingerprint digest: known stable vector and {len(cases)} normalization/order/type/empty-group cases passed")
