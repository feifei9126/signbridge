"""Continuous SMPLer-X candidate batches preserve exact time and provenance."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-source-catchup-smplx.py"
spec = importlib.util.spec_from_file_location("catchup_smplx", SCRIPT)
smplx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smplx)


class SequenceBatchTests(unittest.TestCase):
    def refs(self):
        return [
            {
                "annotation_id": "phrase-001",
                "source_id": "source-001",
                "source_sha256": "a" * 64,
                "label": "你好！",
                "frames": 100,
                "fps": 25.0,
                "start_seconds": 0.0,
                "end_seconds": 4.0,
                "clip": "clip-001.mp4",
                "clip_sha256": "c" * 64,
                "training_ready": False,
                "human_approved": False,
            },
            {
                "annotation_id": "phrase-002",
                "source_id": "source-002",
                "source_sha256": "b" * 64,
                "label": "谢谢！",
                "frames": 200,
                "fps": 25.0,
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                "clip": "clip-002.mp4",
                "clip_sha256": "d" * 64,
                "training_ready": False,
                "human_approved": False,
            },
        ]

    def test_keyframes_map_to_the_exact_clip_and_frame(self):
        links = [
            {"annotation_id": "phrase-001", "frame_1based": 1, "case_id": "case-1"},
            {"annotation_id": "phrase-001", "frame_1based": 100, "case_id": "case-2"},
            {"annotation_id": "phrase-002", "frame_1based": 75, "case_id": "case-3"},
        ]
        result = smplx.build_case_records(self.refs(), [])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["frames"], 100)
        self.assertFalse(result[0]["training_ready"])
        self.assertEqual(result[0]["text_verified"], "")
        mapping = smplx.build_frame_map(self.refs(), links)
        self.assertEqual(mapping[0]["keyframe_case_id"], "case-1")
        self.assertEqual(mapping[0]["clip_frame_1based"], 1)
        self.assertEqual(mapping[1]["clip_frame_1based"], 100)
        self.assertEqual(mapping[2]["clip_frame_1based"], 75)
        self.assertFalse(mapping[0]["training_ready"])

    def test_unknown_or_out_of_range_keyframe_is_rejected(self):
        for row in (
            {"annotation_id": "missing", "frame_1based": 1, "case_id": "case-1"},
            {"annotation_id": "phrase-001", "frame_1based": 101, "case_id": "case-1"},
            {"annotation_id": "phrase-001", "frame_1based": 0, "case_id": "case-1"},
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                smplx.build_frame_map(self.refs(), [row])

    def test_unapproved_annotation_cannot_be_promoted_during_batching(self):
        with self.assertRaises(ValueError):
            smplx.build_case_records(
                [{**self.refs()[0], "human_approved": True}], []
            )
        with self.assertRaises(ValueError):
            smplx.build_case_records(
                [{**self.refs()[0], "training_ready": True}], []
            )

    def test_empty_and_duplicate_sequences_are_rejected(self):
        with self.assertRaises(ValueError):
            smplx.build_case_records([], [])
        with self.assertRaises(ValueError):
            smplx.build_case_records(self.refs() * 2, [])

    def test_frame_map_is_explicit_and_preserves_all_independent_keyframes(self):
        rows = self.refs()
        keyframes = [
            {"annotation_id": "phrase-001", "frame_1based": 50, "case_id": "frame-1"},
            {"annotation_id": "phrase-002", "frame_1based": 100, "case_id": "frame-2"},
        ]
        mapping = smplx.build_frame_map(rows, keyframes)
        self.assertEqual(mapping[0]["keyframe_case_id"], "frame-1")
        self.assertEqual(mapping[0]["clip_frame_1based"], 50)
        self.assertEqual(mapping[1]["clip_frame_1based"], 100)
        self.assertFalse(mapping[0]["training_ready"])

    def test_duplicate_or_out_of_range_keyframe_mapping_is_rejected(self):
        duplicate = [
            {"annotation_id": "phrase-001", "frame_1based": 50, "case_id": "frame-1"},
            {"annotation_id": "phrase-001", "frame_1based": 50, "case_id": "frame-2"},
        ]
        with self.assertRaises(ValueError):
            smplx.build_frame_map(self.refs(), duplicate)
        out_of_range = [{"annotation_id": "phrase-001", "frame_1based": 101, "case_id": "frame-1"}]
        with self.assertRaises(ValueError):
            smplx.build_frame_map(self.refs(), out_of_range)


if __name__ == "__main__":
    unittest.main()
