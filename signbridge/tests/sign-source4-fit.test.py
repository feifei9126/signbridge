import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "sign-source4-fit.py"
SPEC = importlib.util.spec_from_file_location("sign_source4_fit", SCRIPT)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def candidate(annotation_id="new-source-cap-0001", source_id="source-123"):
    return {
        "annotation_id": annotation_id,
        "source_id": source_id,
        "source_sha256": "a" * 64,
        "relative_path": "lesson.mp4",
        "label_candidate": "你好",
        "text_verified": "你好",
        "start_seconds_nominal": 2.0,
        "end_seconds_nominal": 4.0,
        "human_approved": True,
        "semantics_approved": True,
        "boundaries_approved": True,
        "training_ready": False,
        "model_training_ready": False,
        "smplx_parameters_created": False,
        "mirror_status": "unknown",
        "language": "unconfirmed",
        "signer_identity": "unconfirmed",
        "review_attestation_sha256": "b" * 64,
    }


def reference(annotation_id="new-source-cap-0001", source_id="source-123"):
    return {
        "annotation_id": annotation_id,
        "source_id": source_id,
        "source_sha256": "a" * 64,
        "label": "你好",
        "start_seconds": 2.0,
        "end_seconds": 4.0,
        "frames": 50,
        "fps": 25.0,
        "artifacts": {
            "clip.mp4": f"samples/{annotation_id}/clip.mp4",
            "landmarks.npz": f"samples/{annotation_id}/landmarks.npz",
        },
        "human_approved": False,
        "training_ready": False,
        "smplx_parameters_created": False,
    }


class BuildFittingTasksTests(unittest.TestCase):
    def setUp(self):
        self.approved = [candidate()]
        self.references = [reference()]
        self.sources = {
            "source-123": {
                "sha256": "a" * 64,
                "relative_path": "lesson.mp4",
                "authorization_status": "user_reported",
            }
        }

    def build(self):
        return tool.build_fitting_tasks(
            self.approved, self.references, self.sources, {"new-source-cap-0001"}
        )

    def test_accepts_exact_user_approved_set_for_fitting_only(self):
        task = self.build()[0]
        self.assertEqual(task["text_verified"], "你好")
        self.assertEqual(task["label_review_status"], "approved_for_fitting")
        self.assertFalse(task["human_approved"])
        self.assertFalse(task["model_training_ready"])
        self.assertFalse(task["training_ready"])

    def test_rejects_candidate_outside_attested_shortlist(self):
        with self.assertRaisesRegex(ValueError, "approved ID set"):
            tool.build_fitting_tasks(
                self.approved, self.references, self.sources, {"different-id"}
            )

    def test_rejects_source_digest_or_path_mismatch(self):
        self.sources["source-123"]["sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "source provenance"):
            self.build()

    def test_rejects_annotation_timing_mismatch(self):
        self.references[0]["start_seconds"] = 1.0
        with self.assertRaisesRegex(ValueError, "timing differs"):
            self.build()

    def test_rejects_unreviewed_or_promoted_candidate(self):
        self.approved[0]["human_approved"] = False
        with self.assertRaisesRegex(ValueError, "review approval"):
            self.build()
        self.approved[0]["human_approved"] = True
        self.approved[0]["training_ready"] = True
        with self.assertRaisesRegex(ValueError, "must remain false"):
            self.build()

    def test_keeps_2d_reference_separate_from_training_targets(self):
        task = self.build()[0]
        self.assertEqual(task["observation_representation"], "mediapipe-2d-reference-only")
        self.assertFalse(task["smplx_parameters_created"])
        self.assertFalse(task["model_training_ready"])


if __name__ == "__main__":
    unittest.main()
