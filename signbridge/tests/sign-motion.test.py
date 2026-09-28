"""Checks review provenance, frame continuity and the SMPL-X to SOKE contract.

Synthetic motion fixtures are confined to temporary test directories.
"""

import contextlib
import copy
import csv
import importlib.util
import io
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "sign-motion.py"
spec = importlib.util.spec_from_file_location("sign_motion", SCRIPT)
motion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motion)


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.batch = self.root / "batch"
        sample_dir = self.batch / "samples" / "pilot-01"
        sample_dir.mkdir(parents=True)
        self.frames = 5
        self.row = {
            "segment_id": "pilot-01", "source_id": "source-a", "start_seconds": 2.0,
            "end_seconds": 2.2, "text_candidate": "你好", "text_verified": "",
            "sample_type": "sentence", "language": "zh-CSL", "signer_id": "person-a",
            "split_group": "lesson-a", "split": "unassigned", "semantics_status": "needs_review",
            "boundaries_status": "needs_review", "mirror_status": "unknown", "reviewer": "",
        }
        self.manifest = {
            "source_root": str(self.root / "original"),
            "sources": [{"source_id": "source-a", "sha256": "source-hash", "duration_seconds": 10,
                         "authorization_status": "user_reported"}],
        }
        self.prepared = {**self.row, "source_sha256": "source-hash", "frames": self.frames,
                         "fps": 25.0, "authorization_status": "user_reported",
                         "artifacts": {n: "samples/pilot-01/" + n for n in ["clip.mp4", "landmarks.npz"]}}
        motion.write_jsonl(self.batch / "prepared.jsonl", [self.prepared])
        self.manifest_path = self.root / "sources.json"
        motion.data.write_json(self.manifest_path, self.manifest)
        self.segments = self.root / "segments.csv"
        with self.segments.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=motion.data.SEGMENT_FIELDS)
            writer.writeheader()
            writer.writerow(self.row)
        times = np.arange(self.frames, dtype=np.float64) / 25
        arrays = {"timestamps_seconds": times, "source_timestamps_seconds": times + 2.0}
        for name, shape in {"pose_image": (33, 4), "pose_world": (33, 4),
                            "left_hand_image": (21, 3), "right_hand_image": (21, 3),
                            "face_image": (468, 3)}.items():
            arrays[name] = np.full((self.frames, *shape), np.nan, dtype=np.float32)
            arrays[name + "_detected"] = np.zeros(self.frames, dtype=bool)
        np.savez_compressed(sample_dir / "landmarks.npz", **arrays)
        writer = cv2.VideoWriter(str(sample_dir / "clip.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                 25, (64, 64))
        self.assertTrue(writer.isOpened())
        for index in range(self.frames):
            writer.write(np.full((64, 64, 3), index * 30, dtype=np.uint8))
        writer.release()

    def quiet(self, action, args):
        with contextlib.redirect_stdout(io.StringIO()):
            return action(args)

    def export_fixture(self):
        reviewed = self.root / "reviewed"
        self.quiet(motion.review, SimpleNamespace(manifest=self.manifest_path, segments=self.segments,
                   batch=self.batch, reviewer="user", statement="人工核对过了，下一步", output=reviewed))
        output = self.root / "fitting"
        self.quiet(motion.export, SimpleNamespace(reviewed=reviewed, output=output))
        return output

    def native_fixture(self):
        arrays = {}
        for index, (name, _, shape) in enumerate(motion.PARAMETERS):
            arrays[name] = (np.arange(np.prod(shape), dtype=np.float32).reshape(shape) * .001 + index * .1)
        arrays.update(transl=np.zeros((1, 3), dtype=np.float32),
                      leye_pose=np.zeros((1, 3), dtype=np.float32),
                      reye_pose=np.zeros((1, 3), dtype=np.float32))
        return arrays

    def fit_fixture(self, packet):
        fits = self.root / "fits"
        directory = fits / "pilot-01" / "smplx"
        directory.mkdir(parents=True)
        for index in range(1, self.frames + 1):
            np.savez(directory / f"{index:05d}_0.npz", **self.native_fixture())
        motion.data.write_json(fits / "run.json", {
            "schema": "signbridge-smplerx-run-v1", "preflight": {"actual_commit": motion.SMPLERX_COMMIT},
            "tasks_sha256": motion.data.sha256_file(packet / "tasks.jsonl"),
            "status": "inferred_pending_import_audit", "completed": ["pilot-01"],
        })
        return fits

    def test_review_accepts_current_text_and_bounds_without_inventing_mirror(self):
        original = copy.deepcopy(self.prepared)
        rows = motion.confirm_rows(self.manifest, [self.row], [self.prepared], "user")
        self.assertEqual(rows[0]["text_verified"], "你好")
        self.assertEqual(rows[0]["semantics_status"], "approved")
        self.assertEqual(rows[0]["boundaries_status"], "approved")
        self.assertEqual(rows[0]["mirror_status"], "unknown")
        self.assertEqual(rows[0]["split"], "unassigned")
        self.assertFalse(rows[0]["label_ready"])
        self.assertFalse(rows[0]["model_training_ready"])
        self.assertEqual(self.prepared, original)

    def test_review_rejects_stale_ranges_labels_hashes_and_rejected_samples(self):
        for patch_values in [{"start_seconds": 1.0}, {"text_candidate": "再见"},
                             {"source_sha256": "changed"}]:
            with self.subTest(patch=patch_values), self.assertRaises(ValueError):
                motion.confirm_rows(self.manifest, [self.row], [{**self.prepared, **patch_values}], "user")
        with self.assertRaisesRegex(ValueError, "rejected"):
            motion.confirm_rows(self.manifest, [{**self.row, "semantics_status": "rejected"}],
                                [self.prepared], "user")
        with self.assertRaisesRegex(ValueError, "exact current"):
            motion.confirm_rows(self.manifest, [self.row], [self.prepared, self.prepared], "user")

    def test_export_preserves_all_frames_and_observation_missing_masks(self):
        packet = self.export_fixture()
        tasks = motion.verify_pack(packet)
        self.assertEqual(tasks[0]["frames"], self.frames)
        self.assertEqual(tasks[0]["image_transform"], "none")
        frames = motion.read_jsonl(packet / "samples/pilot-01/frames.jsonl")
        self.assertEqual([f["frame_id"] for f in frames], [1, 2, 3, 4, 5])
        self.assertAlmostEqual(frames[-1]["source_seconds_nominal"], 2.16)
        with np.load(packet / "samples/pilot-01/observations.npz") as tracks:
            self.assertTrue(np.isnan(tracks["left_hand_image"]).all())
            self.assertFalse(tracks["left_hand_image_detected"].any())

    def test_export_rejects_changed_review_decision(self):
        packet = self.export_fixture()
        reviewed = self.root / "reviewed"
        decision = reviewed / "review-decision.json"
        decision.write_text(decision.read_text().replace("你好", "再见"))
        with self.assertRaisesRegex(ValueError, "decision changed"):
            self.quiet(motion.export, SimpleNamespace(reviewed=reviewed, output=self.root / "fitting-new"))
        self.assertTrue((packet / "tasks.jsonl").is_file())

    def test_fitting_packet_detects_modified_image_and_task_manifest(self):
        packet = self.export_fixture()
        image = packet / "samples/pilot-01/images/000001.jpg"
        original = image.read_bytes()
        image.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum changed"):
            motion.verify_pack(packet)
        image.write_bytes(original)
        (packet / "tasks.jsonl").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "checksum changed"):
            motion.verify_pack(packet)

    def test_paths_do_not_escape_batch_or_overwrite_inputs(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        with self.assertRaises(ValueError):
            motion.artifact(self.batch, "../outside.txt")
        (self.batch / "link").symlink_to(outside)
        with self.assertRaises(ValueError):
            motion.artifact(self.batch, "link")
        with self.assertRaises(ValueError):
            motion.new_output(self.batch / "nested", [self.batch])
        with self.assertRaises(ValueError):
            motion.safe_id("../unsafe")

    def test_command_uses_one_based_images_and_end_as_frame_count(self):
        task = {"segment_id": "pilot-01", "images": "samples/pilot-01/images", "frames": 5}
        cmd = motion.fitting_command(task, self.batch, self.root, Path("/python"), self.root, "smpler_x_h32")
        self.assertEqual(cmd[cmd.index("--start") + 1], "1")
        self.assertEqual(cmd[cmd.index("--end") + 1], "5")
        self.assertNotIn("--multi_person", cmd)

    def test_soke_dimensions_order_and_shape_removal(self):
        path = self.root / "native.npz"
        np.savez(path, **self.native_fixture())
        params = {k: v[None] for k, v in motion.native_parameters(path).items()}
        features = motion.soke_features(params)
        expected = np.concatenate([params["smplx_body_pose"][:, 33:], params["smplx_lhand_pose"],
                                   params["smplx_rhand_pose"], params["smplx_jaw_pose"],
                                   params["smplx_expr"]], axis=1)
        self.assertEqual(features.shape, (1, 133))
        np.testing.assert_array_equal(features, expected)
        params["smplx_root_pose"][:] = 99
        params["smplx_shape"][:] = 88
        np.testing.assert_array_equal(motion.soke_features(params), expected)

    def test_native_parameters_reject_pca_missing_and_nonfinite_arrays(self):
        for change in ["pca", "missing", "nan"]:
            arrays = self.native_fixture()
            if change == "pca":
                arrays["left_hand_pose"] = np.zeros((1, 6), dtype=np.float32)
            elif change == "missing":
                del arrays["body_pose"]
            else:
                arrays["right_hand_pose"][0, 0] = np.nan
            path = self.root / (change + ".npz")
            np.savez(path, **arrays)
            with self.subTest(change=change), self.assertRaises(ValueError):
                motion.native_parameters(path)

    def test_track_rejects_missing_frames_and_ambiguous_people(self):
        packet = self.export_fixture()
        fits = self.fit_fixture(packet)
        task = motion.read_jsonl(packet / "tasks.jsonl")[0]
        first = fits / "pilot-01/smplx/00001_0.npz"
        original = first.read_bytes()
        first.unlink()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            motion.collect_fit(task, fits / "pilot-01")
        first.write_bytes(original)
        (fits / "pilot-01/smplx/00001_1.npz").write_bytes(original)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            motion.collect_fit(task, fits / "pilot-01")

    def test_rotation_quality_handles_axis_angle_wraparound(self):
        angles = np.zeros((2, 45), dtype=np.float32)
        angles[:, 0] = [.2, .2 + 2 * np.pi]
        quality = motion.rotation_quality(angles)
        self.assertLess(quality["max_adjacent_rotation_degrees"], .01)
        self.assertEqual(quality["frame_transitions_over_90_degrees"], 0)

    def test_import_creates_compatible_poses_without_approving_motion(self):
        packet = self.export_fixture()
        fits = self.fit_fixture(packet)
        output = self.root / "motions"
        result = self.quiet(motion.import_smplerx, SimpleNamespace(batch=packet, fits=fits, output=output))
        self.assertEqual(result, 0)
        features = np.load(output / "samples/pilot-01/features-133.npy")
        self.assertEqual(features.shape, (5, 133))
        self.assertFalse(motion.read_jsonl(output / "motions.jsonl")[0]["model_training_ready"])
        paths = sorted((output / "poses/pilot-01").glob("*.pkl"))
        self.assertEqual(len(paths), 5)
        with paths[0].open("rb") as stream:
            self.assertEqual(set(pickle.load(stream)), {target for _, target, _ in motion.PARAMETERS})
        self.assertEqual(motion.read_jsonl(output / "soke-annotations.jsonl")[0]["split"], "unassigned")
        self.assertFalse((output / "csl_clean.train").exists())

    def test_partial_batch_import_skips_unfitted_samples(self):
        packet = self.export_fixture()
        extra = motion.read_jsonl(packet / "tasks.jsonl")[0].copy()
        extra["segment_id"] = "pilot-02"
        # The importer checks the original exported packet, so fabricate a second
        # task through the verifier while retaining its actual run hash.
        fits = self.fit_fixture(packet)
        with patch.object(motion, "verify_pack", return_value=[motion.read_jsonl(packet / "tasks.jsonl")[0], extra]):
            result = self.quiet(motion.import_smplerx, SimpleNamespace(batch=packet, fits=fits,
                                output=self.root / "partial"))
        self.assertEqual(result, 0)
        report = json.loads((self.root / "partial/verification.json").read_text())
        self.assertEqual(report["converted"], 1)
        self.assertEqual([v["segment_id"] for v in report["skipped"]], ["pilot-02"])

    def test_incomplete_fit_is_rejected_without_padded_motion(self):
        packet = self.export_fixture()
        fits = self.fit_fixture(packet)
        (fits / "pilot-01/smplx/00003_0.npz").unlink()
        output = self.root / "motions"
        result = self.quiet(motion.import_smplerx, SimpleNamespace(batch=packet, fits=fits, output=output))
        self.assertEqual(result, 2)
        self.assertEqual(motion.read_jsonl(output / "motions.jsonl"), [])
        self.assertFalse((output / "samples").exists())
        self.assertEqual(len(json.loads((output / "verification.json").read_text())["rejected"]), 1)

    def test_import_rejects_missing_or_changed_run_provenance(self):
        packet = self.export_fixture()
        fits = self.fit_fixture(packet)
        run_path = fits / "run.json"
        report = json.loads(run_path.read_text())
        report["tasks_sha256"] = "different"
        motion.data.write_json(run_path, report)
        with self.assertRaisesRegex(ValueError, "expected model"):
            self.quiet(motion.import_smplerx, SimpleNamespace(batch=packet, fits=fits, output=self.root / "out"))
        run_path.unlink()
        with self.assertRaisesRegex(ValueError, "requires run.json"):
            self.quiet(motion.import_smplerx, SimpleNamespace(batch=packet, fits=fits, output=self.root / "out"))

    def test_fit_preserves_virtualenv_python_symlink(self):
        packet = self.export_fixture()
        python = self.root / "venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(Path("/usr/bin/python3"))
        with patch.object(motion, "preflight", return_value={"ready": False}) as check:
            self.quiet(motion.fit, SimpleNamespace(batch=packet, smplerx_root=self.root / "model",
                       python=python, model="smpler_x_h32", segment_id=None, dry_run=True,
                       output=self.root / "plan"))
        self.assertEqual(check.call_args.args[1], python)
        self.assertNotEqual(check.call_args.args[1], python.resolve())


if __name__ == "__main__":
    unittest.main()
