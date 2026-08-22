from __future__ import annotations

import gzip
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import task31y_readonly_admission_v2 as verifier


class Task31YReadonlyAdmissionV2Tests(unittest.TestCase):
    def test_gzip_payload_is_decompressed_before_payload_sha_validation(self):
        payload = b'{"data":{"postInfoById":{"id":"t3_example"}}}'
        compressed = verifier.deterministic_gzip(payload)
        with TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "artifact.json.gz"
            artifact.write_bytes(compressed)

            verified = verifier.read_verified_gzip_payload(
                artifact,
                sha256(payload).hexdigest(),
            )

        self.assertEqual(verified, payload)
        self.assertNotEqual(
            sha256(compressed).hexdigest(),
            sha256(payload).hexdigest(),
        )

    def test_gzip_payload_rejects_tamper_and_nondeterministic_encoding(self):
        payload = b'{"data":{"postInfoById":{"id":"t3_example"}}}'
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            tampered = root / "tampered.json.gz"
            encoded = bytearray(verifier.deterministic_gzip(payload))
            encoded[-1] ^= 0x01
            tampered.write_bytes(encoded)
            with self.assertRaisesRegex(
                verifier.AdmissionContractError,
                "raw_artifact_integrity_failed",
            ):
                verifier.read_verified_gzip_payload(
                    tampered,
                    sha256(payload).hexdigest(),
                )

            nondeterministic = root / "nondeterministic.json.gz"
            nondeterministic.write_bytes(gzip.compress(payload, mtime=1))
            with self.assertRaisesRegex(
                verifier.AdmissionContractError,
                "raw_artifact_integrity_failed",
            ):
                verifier.read_verified_gzip_payload(
                    nondeterministic,
                    sha256(payload).hexdigest(),
                )

    def test_digest_domains_cannot_be_compared(self):
        digest = "a" * 64
        expected = verifier.DigestEvidence("legacy_receipt_digest_v1", digest)
        actual = verifier.DigestEvidence(verifier.INVENTORY_DOMAIN, digest)

        with self.assertRaisesRegex(
            verifier.AdmissionContractError,
            "raw_digest_domain_mismatch",
        ):
            verifier.assert_same_digest(
                expected,
                actual,
                label="raw",
            )

    def test_inventory_digest_is_stable_and_symlink_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "a.txt").write_bytes(b"a")
            (root / "nested" / "b.txt").write_bytes(b"b")

            first, first_rows = verifier.inventory_digest(root)
            second, second_rows = verifier.inventory_digest(root)

            self.assertEqual(first.domain, verifier.INVENTORY_DOMAIN)
            self.assertEqual(first, second)
            self.assertEqual(first_rows, second_rows)

            (root / "unsafe").symlink_to(root / "a.txt")
            with self.assertRaisesRegex(
                verifier.AdmissionContractError,
                "inventory_symlink",
            ):
                verifier.inventory_digest(root)

    def test_task31y_baseline_contract_is_complete(self):
        self.assertEqual(set(verifier.ROOTS), set(verifier.BASELINE_ROOT_DIGESTS))
        self.assertEqual(len(verifier.EXPECTED_FAILED_IDS), 12)
        for digest in (
            verifier.BASELINE_RECEIPT_SHA256,
            verifier.TASK31Y_BUNDLE_SHA256,
            verifier.EXPECTED_SOURCE_SHA256,
            verifier.BASELINE_PROVIDER_DIGEST,
            verifier.BASELINE_RAW_INVENTORY_DIGEST,
            verifier.BASELINE_ARTIFACT_MAPPING_DIGEST,
            verifier.BASELINE_CHECKPOINT_MAPPING_DIGEST,
            *verifier.BASELINE_ROOT_DIGESTS.values(),
        ):
            self.assertRegex(digest, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
