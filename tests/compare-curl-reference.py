#!/usr/bin/env python3
"""Compare a Peet report with issue #450, excluding connection randomness."""
import argparse
import json
from pathlib import Path


def normalize(value):
    if isinstance(value, str):
        return "TLS_GREASE" if value.startswith("TLS_GREASE") else value
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def extensions(tls):
    result = []
    for extension in tls["extensions"]:
        item = normalize(extension)
        name = item["name"]
        if name == "TLS_GREASE":
            item = {"name": name}
        elif name == "server_name (0)":
            item = {"name": name}
        elif name == "extended_master_secret (23)":
            # Peet currently reports two equivalent names for this empty field.
            item.setdefault("master_secret_data", "")
            item.setdefault("extended_master_secret_data", "")
        elif name == "key_share (51)" and "shared_keys" in item:
            item["shared_keys_groups"] = [normalize(next(iter(key))) for key in item.pop("shared_keys")]
        result.append(item)
    return result


def differences(reference, actual):
    expected_tls, actual_tls = reference["tls"], actual["tls"]
    failures = []
    for field in ("ja3", "ja3_hash", "ja4", "ja4_r", "peetprint", "peetprint_hash",
                  "tls_version_record", "tls_version_negotiated", "ciphers"):
        if normalize(expected_tls[field]) != normalize(actual_tls.get(field)):
            failures.append("tls." + field)
    if extensions(expected_tls) != extensions(actual_tls):
        failures.append("tls.extensions (ordered payloads, excluding SNI and ephemeral key bytes)")
    for field in ("akamai_fingerprint", "akamai_fingerprint_hash"):
        if reference["http2"][field] != actual.get("http2", {}).get(field):
            failures.append("http2." + field)
    if actual.get("http_version") != "h2":
        failures.append("http_version")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    reference = json.loads((Path(__file__).parent / "fixtures/transport-reference-impit465.json").read_text())
    actual = json.loads(args.report.read_text())
    try:
        failures = differences(reference, actual)
    except (KeyError, TypeError, ValueError, StopIteration) as error:
        parser.exit(1, "Invalid or incomplete report: " + str(error) + "\n")
    if failures:
        parser.exit(1, "MISMATCH: " + ", ".join(failures) + "\n")
    print("MATCH: JA3, JA4, Peetprint, HTTP/2, cipher order and ordered extension payloads")
    print(reference["scope"])


if __name__ == "__main__":
    main()
