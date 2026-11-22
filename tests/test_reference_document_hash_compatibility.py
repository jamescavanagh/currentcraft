"""Synthetic regression: fixing application layering must preserve reference digests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from app.application.ingest.reference_documents import ReferenceIngestProfile
from app.infrastructure.ingest.reference_documents import build_bundle


def legacy_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


class ReferenceDigestCompatibility(unittest.TestCase):
    def test_profile_digest_matches_existing_canonical_encoding(self):
        profile = ReferenceIngestProfile(profile_id="synthetic-unicode-é", version="1")
        self.assertEqual(profile.digest(), legacy_digest(profile.model_dump(mode="json")))

    def test_bundle_digest_matches_existing_canonical_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private"
            root.mkdir()
            raw = 'Synthetic text: é, unicode  , and escaped quotes "value".\n'.encode("utf-8")
            (root / "source.txt").write_bytes(raw)
            profile = ReferenceIngestProfile(profile_id="synthetic-profile", version="1")
            bundle = build_bundle(root, "source.txt", "ref_synthetic_hash_test", hashlib.sha256(raw).hexdigest(), profile)
            self.assertEqual(bundle.payload_digest(), legacy_digest(bundle.model_dump(mode="json", exclude={"payload_sha256"})))


if __name__ == "__main__":
    unittest.main()
