"""Checks for dataset labels, boundaries, paths and evaluation split leakage."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "sign-data.py"
spec = importlib.util.spec_from_file_location("sign_data", SCRIPT)
data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data)


class SignDataTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"sources": [
            {"source_id": "s1", "duration_seconds": 10, "sha256": "same"},
            {"source_id": "s2", "duration_seconds": 20, "sha256": "other"},
            {"source_id": "duplicate", "duration_seconds": 10, "sha256": "same"},
        ]}
        self.segment = {
            "segment_id": "pilot-01", "source_id": "s1", "start_seconds": 1,
            "end_seconds": 4, "text_candidate": "你好", "text_verified": "",
            "sample_type": "sentence", "language": "zh-CSL", "signer_id": "person-a",
            "split_group": "lesson-one", "split": "unassigned",
            "semantics_status": "needs_review", "boundaries_status": "needs_review",
            "mirror_status": "unknown", "reviewer": "",
        }

    def test_subtitle_candidate_is_not_an_approved_label(self):
        rows = data.validate_segments(self.manifest, [self.segment])
        self.assertFalse(data.label_ready(rows[0]))
        self.assertEqual(rows[0]["text_verified"], "")

    def test_approved_semantics_requires_reviewed_text_and_reviewer(self):
        for patch in [{}, {"text_verified": "你好"}]:
            row = {**self.segment, "semantics_status": "approved", **patch}
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                data.validate_segments(self.manifest, [row])

    def test_semantics_approval_does_not_approve_boundaries_or_mirroring(self):
        row = {**self.segment, "semantics_status": "approved", "text_verified": "你好", "reviewer": "r"}
        self.assertFalse(data.label_ready(row))
        row["boundaries_status"] = "approved"
        self.assertFalse(data.label_ready(row))
        row["mirror_status"] = "normal"
        self.assertTrue(data.label_ready(row))

    def test_nonfinite_reversed_and_out_of_bounds_times_are_rejected(self):
        for start, end in [(float("nan"), 3), (1, float("inf")), (-1, 3), (4, 4), (4, 3), (1, 11)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                data.validate_segments(self.manifest, [{**self.segment, "start_seconds": start, "end_seconds": end}])

    def test_duplicate_ids_and_filename_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            data.validate_segments(self.manifest, [self.segment, self.segment])
        for name in ["../outside", "/tmp/x", "pilot/sub", "<script>"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                data.validate_segments(self.manifest, [{**self.segment, "segment_id": name}])

    def test_unknown_source_and_invalid_status_are_rejected(self):
        for field, value in [("source_id", "missing"), ("semantics_status", "auto_approved"),
                             ("boundaries_status", "automatic"), ("mirror_status", "guess"), ("split", "dev")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                data.validate_segments(self.manifest, [{**self.segment, field: value}])

    def test_same_video_and_duplicate_content_cannot_cross_splits(self):
        first = {**self.segment, "split": "train"}
        for source in ["s1", "duplicate"]:
            second = {**self.segment, "segment_id": "pilot-02", "source_id": source,
                      "signer_id": "different", "split_group": "different", "split": "test"}
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "split leakage"):
                data.validate_segments(self.manifest, [first, second])

    def test_same_signer_or_lesson_cannot_cross_splits(self):
        first = {**self.segment, "split": "train"}
        for signer, lesson in [("person-a", "different"), ("different", "lesson-one")]:
            second = {**self.segment, "source_id": "s2", "segment_id": "pilot-02",
                      "signer_id": signer, "split_group": lesson, "split": "validation"}
            with self.subTest(signer=signer, lesson=lesson), self.assertRaisesRegex(ValueError, "split leakage"):
                data.validate_segments(self.manifest, [first, second])

    def test_independent_groups_allow_evaluation_split(self):
        first = {**self.segment, "split": "train"}
        second = {**self.segment, "source_id": "s2", "segment_id": "pilot-02",
                  "signer_id": "person-b", "split_group": "other-lesson", "split": "test"}
        rows = data.validate_segments(self.manifest, [first, second])
        self.assertEqual([row["split"] for row in rows], ["train", "test"])

    def test_ocr_requires_recorded_user_authorization(self):
        self.manifest["sources"][0]["authorization_status"] = "scope_unverified"
        with self.assertRaisesRegex(ValueError, "authorization"):
            data.validate_ocr_range(self.manifest, "s1", 1, 3)
        self.manifest["sources"][0]["authorization_status"] = "user_reported"
        self.assertEqual(data.validate_ocr_range(self.manifest, "s1", 1, 3)["source_id"], "s1")

    def test_ocr_range_rejects_unknown_source_and_invalid_times(self):
        self.manifest["sources"][0]["authorization_status"] = "user_reported"
        with self.assertRaisesRegex(ValueError, "Unknown source"):
            data.validate_ocr_range(self.manifest, "missing", 1, 3)
        for start, end in [(-1, 3), (5, 4), (0, 11), (0, float("nan")), (0, float("inf"))]:
            with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, "Invalid OCR"):
                data.validate_ocr_range(self.manifest, "s1", start, end)

    def test_audit_rejects_falsely_filled_hand_and_incorrect_masks(self):
        import numpy as np
        shapes = {"pose_image": (33, 4), "pose_world": (33, 4),
                  "left_hand_image": (21, 3), "right_hand_image": (21, 3),
                  "face_image": (468, 3)}
        arrays = {key: np.full((2, *shape), np.nan, dtype=np.float32) for key, shape in shapes.items()}
        arrays.update({key + "_detected": np.zeros(2, dtype=bool) for key in shapes})
        arrays["timestamps_seconds"] = np.array([0., 0.04])
        arrays["source_timestamps_seconds"] = np.array([10., 10.04])
        data.validate_landmark_arrays(arrays, 2)
        arrays["left_hand_image"][0, 0, :] = 0
        with self.assertRaisesRegex(ValueError, "partial points"):
            data.validate_landmark_arrays(arrays, 2)
        arrays["left_hand_image"][0, :, :] = 0
        with self.assertRaisesRegex(ValueError, "mask disagrees"):
            data.validate_landmark_arrays(arrays, 2)
        arrays["left_hand_image"][0, :, :] = np.nan
        arrays["timestamps_seconds"][1] = 0
        with self.assertRaisesRegex(ValueError, "time series"):
            data.validate_landmark_arrays(arrays, 2)

    def test_source_path_cannot_leave_source_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            source = {"relative_path": "../outside.mp4"}
            (Path(temporary) / "outside.mp4").write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                data.source_path({"source_root": str(root)}, source)


if __name__ == "__main__":
    unittest.main()
