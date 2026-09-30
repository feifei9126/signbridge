"""Tests for pinned public assets and a portable, tamper-evident GPU stage."""

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "src/tools/sign-gpu.py"
spec = importlib.util.spec_from_file_location("sign_gpu", source)
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)
fixture_spec = importlib.util.spec_from_file_location("motion_tests", ROOT / "tests/sign-motion.test.py")
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)


class GpuTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_download_checks_sha_and_preserves_existing(self):
        payload = b"official checkpoint"
        expected = hashlib.sha256(payload).hexdigest()
        target = self.root / "model.pth"
        with patch.object(gpu.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            self.assertEqual(gpu.checked_download("https://example.invalid/model", target, expected), "downloaded")
        self.assertEqual(gpu.checked_download("https://example.invalid/model", target, expected), "verified_existing")
        target.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "different SHA-256"):
            gpu.checked_download("https://example.invalid/model", target, expected)
        self.assertEqual(target.read_bytes(), b"tampered")

    def test_download_rejects_bad_hash_without_leaving_partial(self):
        target = self.root / "model.pth"
        with patch.object(gpu.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong")):
            with self.assertRaisesRegex(ValueError, "mismatch"):
                gpu.checked_download("https://example.invalid/model", target, "a" * 64)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_model_metadata_requires_lfs_digest_and_revision(self):
        digest = "b" * 64
        record = {"sha": "c" * 40, "siblings": [
            {"rfilename": gpu.MODEL_FILENAME, "lfs": {"oid": digest, "size": 123}}]}
        with patch.object(gpu.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            self.assertEqual(gpu.model_metadata(), ("c" * 40, digest, 123))
        record["siblings"][0]["lfs"]["sha256"] = digest
        record["siblings"][0]["lfs"].pop("oid")
        with patch.object(gpu.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            self.assertEqual(gpu.model_metadata(), ("c" * 40, digest, 123))
        record["siblings"][0]["lfs"]["oid"] = "d" * 64
        with patch.object(gpu.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            with self.assertRaisesRegex(ValueError, "lacks the model SHA-256"):
                gpu.model_metadata()
        record["siblings"][0]["lfs"].pop("oid")
        record["siblings"][0]["lfs"].pop("sha256")
        with patch.object(gpu.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            with self.assertRaisesRegex(ValueError, "lacks the model SHA-256"):
                gpu.model_metadata()

    def test_stage_rechecks_copied_batch_and_detects_modified_file(self):
        fixture = fixtures.MotionTests(methodName="test_command_uses_one_based_images_and_end_as_frame_count")
        fixture.setUp()
        self.addCleanup(fixture.temporary.cleanup)
        batch = fixture.export_fixture()
        upstream = self.root / "SMPLer-X"
        upstream.mkdir()
        (upstream / "inference.py").write_text("# upstream placeholder")
        expected_assets = {"assets": [{"path": gpu.CONFIG_FILE, "sha256": gpu.CONFIG_SHA256},
                                      {"path": gpu.DETECTOR_FILE, "sha256": gpu.DETECTOR_SHA256}]}
        output = self.root / "gpu-stage"
        with patch.object(gpu, "get_revision", return_value=gpu.motion.SMPLERX_COMMIT), \
             patch.object(gpu, "verify_assets", return_value=expected_assets):
            gpu.stage(SimpleNamespace(batch=batch, smplerx_root=upstream, output=output))
            self.assertEqual(gpu.verify(output)["frames"], fixture.frames)
            image = output / "batch/samples/pilot-01/images/000001.jpg"
            image.write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "checksum changed"):
                gpu.verify(output)
            image.write_bytes((batch / "samples/pilot-01/images/000001.jpg").read_bytes())
            stage_file = output / "stage.json"
            stage_file.write_text(stage_file.read_text().replace("created_at", "altered_at"))
            with self.assertRaisesRegex(ValueError, "hash changed"):
                gpu.verify(output)


if __name__ == "__main__":
    unittest.main()
