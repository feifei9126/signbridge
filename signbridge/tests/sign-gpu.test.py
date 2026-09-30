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

    def test_body_assets_require_pinned_lfs_metadata_and_reverify_existing_files(self):
        payloads = {gpu.BODY_PREFIX + name: ("demo:" + name).encode()
                    for name in gpu.BODY_NAMES}
        entries = [{"path": name, "type": "file", "size": len(payload),
                    "lfs": {"sha256": hashlib.sha256(payload).hexdigest(),
                            "size": len(payload)}} for name, payload in payloads.items()]
        args = SimpleNamespace(smplerx_root=self.root)

        def fetch(request, timeout=40):
            url = request if isinstance(request, str) else request.full_url
            if url.startswith("https://huggingface.co/api/spaces/"):
                return io.BytesIO(json.dumps(entries).encode())
            name = url.split("/common/utils/human_model_files/", 1)[1]
            return io.BytesIO(payloads[gpu.BODY_PREFIX + name])

        with patch.object(gpu, "get_revision", return_value=gpu.motion.SMPLERX_COMMIT), \
             patch.object(gpu.urllib.request, "urlopen", side_effect=fetch):
            self.assertEqual(gpu.body_assets(args), 0)
            manifest = json.loads((self.root / gpu.BODY_PREFIX / "signbridge-body-assets.json").read_text())
            self.assertEqual(len(manifest["assets"]), len(gpu.BODY_NAMES))
            self.assertEqual(manifest["revision"], gpu.BODY_REVISION)
            self.assertEqual(gpu.body_assets(args), 0)
            self.assertTrue(all(a["state"] == "verified_existing" for a in json.loads(
                (self.root / gpu.BODY_PREFIX / "signbridge-body-assets.json").read_text())["assets"]))
            first = self.root / gpu.BODY_PREFIX / gpu.BODY_NAMES[0]
            first.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "different SHA-256"):
                gpu.body_assets(args)
            self.assertEqual(first.read_bytes(), b"changed")

            first.write_bytes(payloads[gpu.BODY_PREFIX + gpu.BODY_NAMES[0]])
            self.assertEqual(len(gpu.verify_body_assets(self.root)["assets"]), len(gpu.BODY_NAMES))
            first.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Body asset hash changed"):
                gpu.verify_body_assets(self.root)
            first.write_bytes(payloads[gpu.BODY_PREFIX + gpu.BODY_NAMES[0]])

            entries[0]["lfs"].pop("sha256")
            with self.assertRaisesRegex(ValueError, "missing LFS SHA-256"):
                gpu.body_metadata()

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
