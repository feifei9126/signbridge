"""Local, CPU-only contract fixtures for the post-reconstruction audit."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image


TOOL = Path(__file__).resolve().parents[1] / "src/tools/sign-smplx-post-audit.py"
SHAPES = {
    "global_orient": (1, 3), "body_pose": (21, 3),
    "left_hand_pose": (15, 3), "right_hand_pose": (15, 3),
    "jaw_pose": (1, 3), "betas": (1, 10), "expression": (1, 10),
    "transl": (1, 3), "leye_pose": (1, 3), "reye_pose": (1, 3),
}
FLAGS = {"human_approved": False, "training_ready": False,
         "model_training_ready": False, "text_verified": ""}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def manifest(root):
    files = sorted(p for p in root.rglob("*") if p.is_file() and p != root / "SHA256SUMS")
    (root / "SHA256SUMS").write_text("".join(
        f"{sha(p)}  {p.relative_to(root).as_posix()}\n" for p in files))


class Bundle:
    """A reduced instance of the real export contract, never production data."""

    def __init__(self, root, missing=(), reused=False, count=1):
        self.root = root
        self.results = root / "results"
        self.output = root / "audit"
        self.index_path = root / "export-index.json"
        self.package = self.results / "chunks/chunk-011"
        self.attempt = self.results / "attempts/chunk-011-attempt-1"
        self.remote = "/remote/new/attempts/chunk-011-attempt-1"
        self.original = "/remote/old/attempts/chunk-011-attempt-1"
        self.ids = [f"fit_case{i}" for i in range(count)]
        self.cases = []
        self.aliases = []
        self.records = []
        for number, sid in enumerate(self.ids):
            clip = self.package / "clips" / sid / "clip.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 25, (32, 32))
            if not writer.isOpened():
                raise RuntimeError("Fixture video writer unavailable")
            for frame in range(4):
                writer.write(np.full((32, 32, 3), frame * 40, np.uint8))
            writer.release()
            case = {"annotation_id": sid, "source_id": f"source-{number}",
                    "source_sha256": hashlib.sha256(sid.encode()).hexdigest(),
                    "label_candidate": "候选", "frames": 4, "fps": 25.0,
                    "start_seconds": 0.0, "end_seconds": 0.16,
                    "clip": f"clips/{sid}/clip.mp4", "clip_sha256": sha(clip), **FLAGS}
            self.cases.append(case)
            self.aliases.append({"fit_sequence_id": sid, "candidate_id": f"candidate-{number}",
                                 "source_id": case["source_id"], "source_sha256": case["source_sha256"],
                                 "label_candidate": case["label_candidate"],
                                 "candidate_clip_sha256": case["clip_sha256"], **FLAGS})
            for folder in ("input-frames/" + sid, "fits/" + sid + "/smplx",
                           "fits/" + sid + "/meta", "fits/" + sid + "/img", "logs"):
                (self.attempt / folder).mkdir(parents=True, exist_ok=True)
            for frame in range(1, 5):
                image = self.attempt / "input-frames" / sid / f"{frame:06d}.jpg"
                Image.new("RGB", (16, 16), (frame * 40, 0, 0)).save(image)
                shutil.copyfile(image, self.attempt / "fits" / sid / "img" / image.name)
                if reused:
                    original_image = self.results / "historical/interrupted/chunk-011-attempt-1/input-frames" / sid / image.name
                    original_image.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(image, original_image)
                if frame in missing:
                    continue
                np.savez(self.attempt / "fits" / sid / "smplx" / f"{frame:05d}_0.npz",
                         **{key: np.zeros(shape, np.float32) for key, shape in SHAPES.items()})
                origin = self.original if reused else self.remote
                write_json(self.attempt / "fits" / sid / "meta" / f"{frame:05d}_0.json",
                           {"img_path": f"{origin}/input-frames/{sid}/{frame:06d}.jpg", "bbox_id": 0})
            log = self.attempt / "logs" / (sid + ".log")
            log.write_text("fixture inference log\n")
            self.records.append({**{k: case[k] for k in ("annotation_id", "source_id", "source_sha256", "label_candidate")},
                                 "sequence_index": number + 1, "frames_expected": 4,
                                 "render_frames": 4, "smplx_parameter_files": 4 - len(missing),
                                 "smplx_missing_detection_frames": list(missing), "log_sha256": sha(log), **FLAGS})
        # Runtime configuration directories must not be mistaken for candidates.
        runtime = self.attempt / "fits/runtime" / self.ids[0] / "config.json"
        write_json(runtime, {"fixture": True})
        self.report = {"schema": "signbridge-smplerx-candidate-sequences-run-v1",
                       "status": "smplerx_sequences_completed_pending_quality_review",
                       "sequence_count": count, "frames_expected": count * 4,
                       "completed_sequences": count, "completed_frames": count * 4,
                       "candidate_records": self.records, "text_verified_count": 0,
                       "training_started": False, **FLAGS}
        if reused:
            self.report.update(
                report_kind="verified_completed_prefix_reconciliation_not_a_new_inference_run",
                original_attempt=self.original,
                native_parameters_or_images_regenerated=False, raw_metadata_preserved=True,
                reused_input_mapping=[{"annotation_id": sid,
                                      "original_input_directory": f"{self.original}/input-frames/{sid}",
                                      "copied_input_directory": f"{self.remote}/input-frames/{sid}"}
                                     for sid in self.ids])
        self.index = {"schema": "signbridge-post-reconstruction-export-index-v1",
                      "sequences_total": count, "frames_total": 4 * count,
                      "structurally_complete": count if not missing else 0,
                      "quarantined": count if missing else 0,
                      "items": [{"kind": "attempt", "chunk": "chunk-011",
                                 "source_root": self.remote, "result_rel": "attempts/chunk-011-attempt-1"}],
                      "origin_mappings": [
                          {"remote_prefix": "/remote/old", "local_relative": "historical/control"},
                          {"remote_prefix": self.original, "local_relative": "historical/interrupted/chunk-011-attempt-1"},
                          {"remote_prefix": "/remote/new", "local_relative": "."}], **FLAGS}
        self.refresh()

    def refresh(self):
        write_rows(self.package / "sequences.jsonl", self.cases)
        write_rows(self.package / "aliases.jsonl", self.aliases)
        write_rows(self.package / "keyframes.jsonl", [])
        write_json(self.package / "manifest.json", {
            "schema": "signbridge-smplerx-candidate-sequences-v1", "sequence_count": len(self.cases),
            "frames": sum(c["frames"] for c in self.cases), "candidate_alias_count": len(self.aliases),
            "keyframe_count": 0, "text_verified_count": 0, "training_started": False, **FLAGS})
        manifest(self.package)
        chunk_index = {"schema": "signbridge-smplerx-candidate-chunk-index-v1",
                       "sequence_count": len(self.cases), "frame_count": sum(c["frames"] for c in self.cases),
                       "candidate_alias_count": len(self.aliases), "chunks": [{
                           "path": "chunk-011", "chunk_index_1based": 1,
                           "sequence_count": len(self.cases), "frames": sum(c["frames"] for c in self.cases),
                           "candidate_alias_count": len(self.aliases),
                           "package_manifest_sha256": sha(self.package / "SHA256SUMS")}]}
        write_json(self.results / "chunks/chunk-index.json", chunk_index)
        self.index["input_index_sha256"] = sha(self.results / "chunks/chunk-index.json")
        self.report["input_manifest_sha256"] = sha(self.package / "manifest.json")
        write_json(self.attempt / "report.json", self.report)
        manifest(self.attempt)
        if self.index["items"]:
            item = next(i for i in self.index["items"] if i["kind"] == "attempt")
            item.update(manifest_sha256=sha(self.attempt / "SHA256SUMS"), report_sha256=sha(self.attempt / "report.json"))
        write_json(self.index_path, self.index)

    def command(self, *extra):
        return [sys.executable, "-B", str(TOOL), "--results", str(self.results),
                "--export-index", str(self.index_path), "--output", str(self.output),
                "--workers", "4", *extra]

    def run(self, *extra):
        result = subprocess.run(self.command(*extra), capture_output=True, text=True, timeout=15)
        report_path = self.output / "report.json"
        if not report_path.is_file():
            raise AssertionError(f"CLI did not write complete report: {result.returncode}: {result.stderr}")
        return result, json.loads(report_path.read_text())

    def transfer(self, status="running", attempt_status="pending"):
        self.index["export_root"] = "/remote/export"
        self.index["status"] = "completed"
        self.index["items"].append({"key": "inputs", "kind": "inputs", "source_dir": "/remote/new",
                                    "members": ["chunks"], "extract_base": "."})
        for item in self.index["items"]:
            item.setdefault("key", item.get("chunk", "inputs"))
            item.update(archive_name=item["key"] + ".tar", archive_sha256="a" * 64,
                        internal_manifest_name=item["key"] + ".internal.SHA256SUMS",
                        internal_manifest_sha256="b" * 64, archive_bytes=1024,
                        internal_files=10, status="complete")
        write_json(self.index_path, self.index)
        identity_fields = ("key", "kind", "archive_name", "internal_manifest_name", "source_dir", "members",
                           "extract_base", "source_root", "result_rel", "chunk", "attempt", "manifest_sha256",
                           "report_sha256", "expected_files", "archive_sha256", "archive_bytes",
                           "internal_manifest_sha256", "internal_files")
        items = {}
        for item in self.index["items"]:
            proof = {"identity": {k: item[k] for k in identity_fields if k in item},
                     **{k: item[k] for k in ("archive_sha256", "archive_bytes", "internal_manifest_sha256")},
                     "verified_files": item["internal_files"], "verified_bytes": 512}
            if item["kind"] == "attempt":
                proof.update({k: item[k] for k in ("manifest_sha256", "report_sha256")})
            items[item["key"]] = {"status": attempt_status if item["kind"] == "attempt" else "verified", "proof": proof}
        self.transfer_path = self.root / "transfer-report.json"
        self.transfer_report = {"schema": "signbridge-post-reconstruction-transfer-v1", "export_root": "/remote/export",
                                "items": items, "status": status, "source_status": "completed", "failures": []}
        self.save_transfer()
        return self.transfer_path

    def save_transfer(self):
        temporary = self.transfer_path.with_suffix(".tmp")
        write_json(temporary, self.transfer_report)
        temporary.replace(self.transfer_path)


class PostAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def assert_error(self, bundle, fragment):
        result, report = bundle.run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(fragment, json.dumps(report))
        self.assertTrue(report["summary"]["promotion_blocked"])
        self.assertEqual(len(report["records"]), len(bundle.cases))
        self.assertTrue(all(row["quality_tier"] == "technical_error" for row in report["records"]))
        return report

    def test_complete_native_sequence_and_explicit_nonapproval(self):
        bundle = Bundle(self.root)
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        row = report["records"][0]
        self.assertEqual(row["quality_tier"], "no_automatic_motion_red_flag")
        self.assertEqual(row["technical_errors"], [])
        self.assertEqual(row["missing_detection_frames"], [])
        self.assertEqual(row["review_frames"], [1, 2, 3, 4])
        for obj in (report, row):
            for key, value in FLAGS.items():
                self.assertIs(obj[key], value) if value is False else self.assertEqual(obj[key], value)
        for key in ("uid", "annotation_id", "chunk", "source_id", "source_sha256", "label_candidate", "fps",
                    "frames_expected", "status", "raw_rotation_metrics", "log_sha256", "report_sha256"):
            self.assertIn(key, row)
        for key in ("clip_path", "input_directory", "render_directory", "fit_directory"):
            self.assertTrue(Path(row[key]).is_absolute())
            self.assertTrue(Path(row[key]).exists())
        self.assertEqual(report["summary"]["sequences"], 1)
        self.assertEqual(report["summary"]["aliases"], 1)
        self.assertEqual(report["summary"]["frames_expected"], 4)
        self.assertEqual(row["raw_rotation_metrics"]["body"]["adjacent_p95_deg"], 0)
        self.assertFalse(any(bundle.output.rglob("*.npz")))

    def test_missing_detections_are_quarantined_without_temporal_arrays(self):
        bundle = Bundle(self.root, missing=(2,))
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        row = report["records"][0]
        self.assertEqual(row["quality_tier"], "missing_detections_quarantine")
        self.assertEqual(row["missing_detection_frames"], [2])
        self.assertEqual(row["raw_rotation_metrics"], {})
        self.assertFalse((bundle.attempt / "fits/fit_case0/smplx/00002_0.npz").exists())

    def test_full_sequence_missing_detection_without_native_dirs_is_quarantine(self):
        bundle = Bundle(self.root, missing=(1, 2, 3, 4))
        fit = bundle.attempt / "fits/fit_case0"
        shutil.rmtree(fit / "smplx")
        shutil.rmtree(fit / "meta")
        bundle.refresh()
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        row = report["records"][0]
        self.assertEqual(row["quality_tier"], "missing_detections_quarantine")
        self.assertEqual(row["technical_errors"], [])
        self.assertEqual(row["missing_detection_frames"], [1, 2, 3, 4])
        self.assertEqual(row["raw_rotation_metrics"], {})
        self.assertFalse(row["feature_extraction_allowed"])
        self.assertFalse(row["missing_frames_filled"])

    def test_full_sequence_missing_detection_still_requires_complete_images(self):
        bundle = Bundle(self.root, missing=(1, 2, 3, 4))
        fit = bundle.attempt / "fits/fit_case0"
        shutil.rmtree(fit / "smplx")
        shutil.rmtree(fit / "meta")
        (bundle.attempt / "input-frames/fit_case0/000004.jpg").write_bytes(b"broken")
        bundle.refresh()
        result, report = bundle.run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(report["records"][0]["quality_tier"], "technical_error")
        self.assertIn("JPEG", json.dumps(report["records"][0]["technical_errors"]))

    def test_full_sequence_missing_detection_does_not_hide_clip_hash_errors(self):
        bundle = Bundle(self.root, missing=(1, 2, 3, 4))
        fit = bundle.attempt / "fits/fit_case0"
        shutil.rmtree(fit / "smplx")
        shutil.rmtree(fit / "meta")
        bundle.cases[0]["clip_sha256"] = "0" * 64
        bundle.aliases[0]["candidate_clip_sha256"] = "0" * 64
        bundle.refresh()
        result, report = bundle.run()
        self.assertEqual(result.returncode, 2, result.stderr)
        row = report["records"][0]
        self.assertEqual(row["quality_tier"], "technical_error")
        self.assertIn("clip_sha256", json.dumps(row["technical_errors"]))

    def test_false_missing_detection_report_is_technical_error(self):
        bundle = Bundle(self.root, missing=(2,))
        bundle.records[0]["smplx_missing_detection_frames"] = []
        bundle.refresh()
        self.assert_error(bundle, "missing_detection_frames")

    def test_hash_tamper_and_unlisted_manifest_file(self):
        for mutation in ("tamper", "unlisted", "missing", "duplicate"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp))
                if mutation == "tamper":
                    (bundle.attempt / "logs/fit_case0.log").write_text("tampered")
                elif mutation == "unlisted":
                    (bundle.attempt / "extra.txt").write_text("unlisted")
                elif mutation == "missing":
                    (bundle.attempt / "fits/fit_case0/meta/00001_0.json").unlink()
                else:
                    path = bundle.attempt / "SHA256SUMS"
                    path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
                self.assert_error(bundle, "manifest")

    def test_log_hash_and_clip_sha_and_full_decode_counts_and_fps(self):
        for mutation in ("log", "clip_hash", "clip_count", "fps"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp))
                if mutation == "log":
                    bundle.records[0]["log_sha256"] = "0" * 64
                elif mutation == "clip_hash":
                    bundle.cases[0]["clip_sha256"] = "0" * 64
                    bundle.aliases[0]["candidate_clip_sha256"] = "0" * 64
                elif mutation == "clip_count":
                    path = bundle.package / bundle.cases[0]["clip"]
                    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (32, 32))
                    writer.write(np.zeros((32, 32, 3), np.uint8))
                    writer.release()
                    bundle.cases[0]["clip_sha256"] = sha(path)
                    bundle.aliases[0]["candidate_clip_sha256"] = sha(path)
                else:
                    bundle.cases[0]["fps"] = 30
                bundle.refresh()
                self.assert_error(bundle, {"log": "log_sha256", "clip_hash": "clip_sha256",
                                           "clip_count": "clip_frames", "fps": "clip_fps"}[mutation])

    def test_existing_npz_all_required_float_shapes_and_finite_including_eyes(self):
        for key in SHAPES:
            for failure in ("integer", "shape", "nonfinite", "absent"):
                with self.subTest(key=key, failure=failure), tempfile.TemporaryDirectory() as temp:
                    bundle = Bundle(Path(temp), missing=(2,))
                    path = bundle.attempt / "fits/fit_case0/smplx/00003_0.npz"
                    arrays = {k: np.zeros(shape, np.float32) for k, shape in SHAPES.items()}
                    if failure == "integer": arrays[key] = arrays[key].astype(np.int32)
                    elif failure == "shape": arrays[key] = np.zeros((3,), np.float32)
                    elif failure == "nonfinite": arrays[key].flat[0] = np.nan
                    else: del arrays[key]
                    np.savez(path, **arrays)
                    bundle.refresh()
                    self.assert_error(bundle, "native_parameters")

    def test_multiperson_or_mismatched_metadata_never_has_metrics(self):
        for mutation in ("person", "meta_set", "bbox", "wrong_origin", "input_set", "render"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp))
                base = bundle.attempt / "fits/fit_case0"
                if mutation == "person":
                    shutil.copyfile(base / "smplx/00001_0.npz", base / "smplx/00001_1.npz")
                    write_json(base / "meta/00001_1.json", {"img_path": bundle.remote + "/input-frames/fit_case0/000001.jpg", "bbox_id": 1})
                    bundle.records[0]["smplx_parameter_files"] += 1
                elif mutation == "meta_set": (base / "meta/00003_0.json").unlink()
                elif mutation in ("bbox", "wrong_origin"):
                    path = base / "meta/00003_0.json"
                    info = json.loads(path.read_text())
                    info["bbox_id" if mutation == "bbox" else "img_path"] = 1 if mutation == "bbox" else "/wrong/input-frames/fit_case0/000003.jpg"
                    write_json(path, info)
                elif mutation == "input_set":
                    (bundle.attempt / "input-frames/fit_case0/000004.jpg").rename(bundle.attempt / "input-frames/fit_case0/000005.jpg")
                else: (base / "img/000002.jpg").write_bytes(b"bad jpeg")
                bundle.refresh()
                report = self.assert_error(bundle, {"person": "person", "meta_set": "metadata", "bbox": "metadata",
                                                    "wrong_origin": "metadata", "input_set": "input", "render": "JPEG"}[mutation])
                self.assertEqual(report["records"][0]["raw_rotation_metrics"], {})

    def test_reused_prefix_preserves_original_metadata_and_hashes(self):
        bundle = Bundle(self.root, reused=True)
        before = sha(bundle.attempt / "fits/fit_case0/meta/00001_0.json")
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["records"][0]["technical_errors"], [])
        self.assertEqual(before, sha(bundle.attempt / "fits/fit_case0/meta/00001_0.json"))
        self.assertEqual(report["records"][0]["reused_input_jpegs_verified"], 4)

    def test_original_completed_attempt_materialized_under_new_results(self):
        bundle = Bundle(self.root)
        bundle.index["items"][0]["source_root"] = bundle.original
        bundle.index["origin_mappings"][1]["local_relative"] = "attempts/chunk-011-attempt-1"
        for path in (bundle.attempt / "fits/fit_case0/meta").glob("*.json"):
            info = json.loads(path.read_text())
            info["img_path"] = info["img_path"].replace(bundle.remote, bundle.original)
            write_json(path, info)
        bundle.refresh()
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["records"][0]["technical_errors"], [])

    def test_many_aliases_share_one_native_sequence_without_duplicating_frames(self):
        bundle = Bundle(self.root)
        bundle.aliases.append({**bundle.aliases[0], "candidate_id": "another-candidate", "label_candidate": "另一个词"})
        bundle.refresh()
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["summary"]["aliases"], 2)
        self.assertEqual(report["summary"]["frames_expected"], 4)

    def test_pinned_package_manifest_is_sums_but_report_links_manifest_json(self):
        bundle = Bundle(self.root)
        self.assertNotEqual(bundle.report["input_manifest_sha256"],
                            json.loads((bundle.results / "chunks/chunk-index.json").read_text())["chunks"][0]["package_manifest_sha256"])
        result, report = bundle.run()
        self.assertEqual(result.returncode, 0, json.dumps(report) + result.stderr)

    def test_malformed_report_or_candidate_fields_still_report_every_known_id(self):
        for failure in ("report_type", "record_type", "frames_type", "source_sha", "alias_type", "gap_type", "report_status"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp), count=2)
                if failure == "record_type": bundle.report["candidate_records"] = None
                elif failure == "frames_type": bundle.cases[0]["frames"] = "four"
                elif failure == "source_sha":
                    bundle.cases[0]["source_sha256"] = "not-a-digest"
                    bundle.aliases[0]["source_sha256"] = "not-a-digest"
                    bundle.records[0]["source_sha256"] = "not-a-digest"
                elif failure == "gap_type": bundle.records[0]["smplx_missing_detection_frames"] = [True]
                elif failure == "report_status": bundle.report["status"] = "failed"
                # Invalid source timing must be introduced after fixture bookkeeping.
                if failure == "frames_type":
                    bundle.cases[0]["frames"] = 4
                    bundle.refresh()
                    bundle.cases[0]["frames"] = "four"
                    write_rows(bundle.package / "sequences.jsonl", bundle.cases)
                    manifest(bundle.package)
                else:
                    bundle.refresh()
                if failure == "report_type": write_json(bundle.attempt / "report.json", [])
                if failure == "alias_type": write_rows(bundle.package / "aliases.jsonl", [None])
                result, report = bundle.run()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual([r["annotation_id"] for r in report["records"]], bundle.ids)
                self.assertTrue(report["summary"]["promotion_blocked"])

    def test_reused_hash_mismatch_and_missing_mapping_and_rewritten_origin(self):
        for failure in ("hash", "missing_mapping", "origin", "copy_target"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp), reused=True)
                if failure == "hash":
                    path = bundle.results / "historical/interrupted/chunk-011-attempt-1/input-frames/fit_case0/000003.jpg"
                    Image.new("RGB", (16, 16), (255, 255, 255)).save(path)
                elif failure == "missing_mapping": bundle.report["reused_input_mapping"] = []
                elif failure == "copy_target": bundle.report["reused_input_mapping"][0]["copied_input_directory"] += "_wrong"
                else:
                    write_json(bundle.attempt / "fits/fit_case0/meta/00001_0.json",
                               {"img_path": bundle.remote + "/input-frames/fit_case0/000001.jpg", "bbox_id": 0})
                bundle.refresh()
                self.assert_error(bundle, "reused" if failure != "origin" else "metadata")

    def test_safe_relative_paths_and_symlinks_fail_closed(self):
        for failure in ("item", "clip", "manifest", "symlink", "origin_mapping"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp))
                if failure == "item": bundle.index["items"][0]["result_rel"] = "../escape"
                elif failure == "clip": bundle.cases[0]["clip"] = "/tmp/outside.mp4"
                elif failure == "origin_mapping": bundle.index["origin_mappings"][-1]["local_relative"] = "../outside"
                elif failure == "symlink":
                    target = bundle.root / "outside.jpg"
                    shutil.copyfile(bundle.attempt / "input-frames/fit_case0/000001.jpg", target)
                    image = bundle.attempt / "input-frames/fit_case0/000001.jpg"
                    image.unlink()
                    image.symlink_to(target)
                bundle.refresh()
                if failure == "manifest":
                    path = bundle.attempt / "SHA256SUMS"
                    path.write_text(path.read_text() + "0" * 64 + "  ../escape\n")
                self.assert_error(bundle, "unsafe")

    def test_order_alias_identity_totals_and_no_silent_skips(self):
        for failure in ("order", "alias_unknown", "alias_duplicate", "alias_sha", "alias_count", "frames_total", "missing_attempt", "approval"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp), count=2)
                if failure == "order": bundle.report["candidate_records"] = list(reversed(bundle.records))
                elif failure == "alias_unknown": bundle.aliases[1]["fit_sequence_id"] = "unknown"
                elif failure == "alias_duplicate": bundle.aliases[1]["candidate_id"] = bundle.aliases[0]["candidate_id"]
                elif failure == "alias_sha": bundle.aliases[1]["source_sha256"] = "0" * 64
                elif failure == "frames_total": bundle.index["frames_total"] += 1
                elif failure == "missing_attempt": bundle.index["items"] = []
                elif failure == "approval": bundle.records[0]["human_approved"] = True
                bundle.refresh()
                if failure == "alias_count":
                    path = bundle.results / "chunks/chunk-index.json"
                    data = json.loads(path.read_text()); data["candidate_alias_count"] += 1
                    write_json(path, data)
                    bundle.index["input_index_sha256"] = sha(path)
                    write_json(bundle.index_path, bundle.index)
                result, report = bundle.run()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(len(report["records"]), 2)
                self.assertTrue(report["summary"]["promotion_blocked"])

    def test_one_broken_candidate_does_not_hide_other_candidate(self):
        bundle = Bundle(self.root, count=2)
        (bundle.attempt / "fits/fit_case0/smplx/00001_0.npz").write_bytes(b"broken zip")
        bundle.refresh()
        result, report = bundle.run()
        self.assertEqual(result.returncode, 2)
        self.assertEqual([r["annotation_id"] for r in report["records"]], bundle.ids)
        self.assertEqual(report["records"][0]["quality_tier"], "technical_error")
        self.assertEqual(report["records"][1]["quality_tier"], "no_automatic_motion_red_flag")

    def test_unexpected_candidate_npz_and_jpegs_are_checked_in_error_report(self):
        bundle = Bundle(self.root)
        extra = bundle.attempt / "fits/extra-candidate"
        (extra / "smplx").mkdir(parents=True)
        (extra / "img").mkdir()
        (extra / "smplx/bad.npz").write_bytes(b"broken archive")
        (extra / "img/bad.jpg").write_bytes(b"broken jpeg")
        bundle.refresh()
        report = self.assert_error(bundle, "unassigned_native_parameters")
        self.assertIn("unassigned_JPEG", json.dumps(report))

    def test_pinned_hashes_report_counts_and_approval_boundaries(self):
        for failure in ("report_digest", "manifest_digest", "index_digest", "item_counts", "complete_counts", "report_frames", "model_ready", "text"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp))
                if failure == "item_counts": bundle.index["items"][0]["complete_sequences"] = 0
                elif failure == "complete_counts": bundle.index["structurally_complete"] = 0
                elif failure == "report_frames": bundle.records[0]["smplx_parameter_files"] = 99
                elif failure == "model_ready": bundle.aliases[0]["model_training_ready"] = True
                elif failure == "text": bundle.cases[0]["text_verified"] = "approved"
                bundle.refresh()
                field = {"report_digest": "report_sha256", "manifest_digest": "manifest_sha256"}.get(failure)
                if field:
                    bundle.index["items"][0][field] = "0" * 64
                    write_json(bundle.index_path, bundle.index)
                if failure == "index_digest":
                    bundle.index["input_index_sha256"] = "0" * 64
                    write_json(bundle.index_path, bundle.index)
                result, report = bundle.run()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(report["summary"]["promotion_blocked"])
                for row in report["records"]:
                    self.assertFalse(row["model_training_ready"])
                    self.assertEqual(row["text_verified"], "")

    def test_input_jpeg_corruption_and_metadata_extra_person_fail(self):
        for failure in ("input_jpeg", "extra_metadata", "zero_frame", "frame_outside"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp))
                base = bundle.attempt / "fits/fit_case0"
                if failure == "input_jpeg":
                    (bundle.attempt / "input-frames/fit_case0/000004.jpg").write_bytes(b"bad")
                elif failure == "extra_metadata":
                    write_json(base / "meta/00001_1.json", {"img_path": bundle.remote + "/input-frames/fit_case0/000001.jpg", "bbox_id": 1})
                else:
                    target = "00000_0" if failure == "zero_frame" else "00005_0"
                    (base / "smplx/00001_0.npz").rename(base / "smplx" / (target + ".npz"))
                    (base / "meta/00001_0.json").rename(base / "meta" / (target + ".json"))
                bundle.refresh()
                self.assert_error(bundle, "JPEG" if failure == "input_jpeg" else "metadata" if failure == "extra_metadata" else "frame/person")

    def test_unsafe_output_under_inputs_is_not_created(self):
        bundle = Bundle(self.root)
        output = bundle.results / "audit"
        result = subprocess.run([sys.executable, "-B", str(TOOL), "--results", str(bundle.results),
                                 "--export-index", str(bundle.index_path), "--output", str(output)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_output_must_be_fresh_and_outside_inputs(self):
        bundle = Bundle(self.root)
        bundle.output.mkdir()
        sentinel = bundle.output / "report.json"
        sentinel.write_text("preserve")
        result = subprocess.run([sys.executable, "-B", str(TOOL), "--results", str(bundle.results),
                                 "--export-index", str(bundle.index_path), "--output", str(bundle.output)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "preserve")


class TransferWaitTests(unittest.TestCase):
    def start(self, bundle):
        process = subprocess.Popen(bundle.command("--wait-transfer-report", str(bundle.transfer_path),
                                                 "--transfer-poll-seconds", "0.02"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate()
        self.addCleanup(cleanup)
        return process

    def wait_progress(self, bundle, process, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            path = bundle.output / "progress.json"
            if path.exists() and predicate(json.loads(path.read_text())):
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(f"CLI exited before requested progress: {stdout} {stderr}")
            time.sleep(0.01)
        self.fail("Expected bounded progress was not written")

    def test_wait_never_hashes_unproven_paths_and_requires_terminal_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Bundle(Path(temp))
            bundle.transfer()
            log = bundle.attempt / "logs/fit_case0.log"
            original = log.read_bytes()
            log.write_bytes(b"incomplete extraction must not be read")
            process = self.start(bundle)
            self.wait_progress(bundle, process, lambda p: p["status"] == "waiting_transfer")
            self.assertFalse((bundle.output / "report.json").exists())
            self.assertIsNone(process.poll())
            log.write_bytes(original)
            bundle.transfer_report["items"]["chunk-011"]["status"] = "verified"
            bundle.save_transfer()
            self.wait_progress(bundle, process, lambda p: p["chunks_processed"] == 1)
            self.assertIsNone(process.poll(), "All chunk proofs alone cannot mark a running transfer complete")
            self.assertFalse((bundle.output / "report.json").exists())
            bundle.transfer_report["status"] = "completed"
            bundle.save_transfer()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            report = json.loads((bundle.output / "report.json").read_text())
            self.assertTrue(report["audit_complete"])
            self.assertEqual(report["summary"]["attempt_proofs_verified"], 1)
            self.assertIn('"status":"auditing"', stdout)

    def test_terminal_failure_or_missing_or_wrong_proof_reports_all_known_ids(self):
        for failure in ("failed", "source_failed", "interrupted", "completed_missing", "wrong_identity", "wrong_hash"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bundle = Bundle(Path(temp), count=2)
                bundle.transfer(status="completed" if failure.startswith("completed") or failure.startswith("wrong") else failure)
                item = bundle.transfer_report["items"]["chunk-011"]
                if failure == "wrong_identity":
                    item["status"] = "verified"
                    item["proof"]["identity"]["source_root"] = "/different/root"
                if failure == "wrong_hash":
                    item["status"] = "verified"
                    item["proof"]["manifest_sha256"] = "0" * 64
                bundle.save_transfer()
                result, report = bundle.run("--wait-transfer-report", str(bundle.transfer_path), "--transfer-poll-seconds", "0.02")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("transfer", json.dumps(report).lower())
                self.assertEqual([r["annotation_id"] for r in report["records"]], bundle.ids)
                self.assertFalse(report["audit_complete"])
                self.assertTrue(all(r["quality_tier"] == "technical_error" for r in report["records"]))
                self.assertTrue(all(r["missing_detection_frames"] == [] for r in report["records"]))

    def test_origin_fault_is_technical_even_with_verified_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Bundle(Path(temp))
            bundle.index["origin_mappings"][-1]["local_relative"] = "wrong-directory"
            bundle.refresh()
            bundle.transfer(status="completed", attempt_status="verified")
            result, report = bundle.run("--wait-transfer-report", str(bundle.transfer_path))
            self.assertEqual(result.returncode, 2, result.stderr)
            row = report["records"][0]
            self.assertEqual(row["quality_tier"], "technical_error")
            self.assertEqual(row["missing_detection_frames"], [])
            self.assertIn("attempt_origin", json.dumps(row["technical_errors"]))


class RotationTests(unittest.TestCase):
    def module(self):
        self.assertTrue(TOOL.exists(), "post-reconstruction audit implementation is missing")
        spec = importlib.util.spec_from_file_location("post_audit", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_hash_cache_ignores_access_time_but_detects_modified_evidence(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.txt"
            path.write_text("original")
            stat = path.stat()
            properties = {name: getattr(stat, name) for name in
                          ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            before = SimpleNamespace(**properties, st_atime_ns=1)
            after = SimpleNamespace(**properties, st_atime_ns=2)
            evidence = module.Evidence()
            with patch.object(Path, "stat", side_effect=[before, after]):
                try:
                    digest = evidence.sha(path)
                except ValueError as error:
                    self.fail("Access-time-only update was mistaken for evidence mutation: " + str(error))
                self.assertEqual(digest, sha(path))
            with patch.object(Path, "open", side_effect=AssertionError("cache must not reread")):
                self.assertEqual(evidence.sha(path), hashlib.sha256(b"original").hexdigest())
            path.write_text("changed length")
            with self.assertRaisesRegex(ValueError, "changed"):
                evidence.sha(path)

    def test_so3_known_rotations_and_midpoint_residual(self):
        module = self.module()
        poses = np.zeros((3, 1, 3))
        poses[:, 0, 2] = np.deg2rad([0, 45, 90])
        metrics = module.rotation_metrics(poses)
        self.assertAlmostEqual(metrics["max_adjacent_deg"], 45, places=5)
        self.assertAlmostEqual(metrics["adjacent_p95_deg"], 45, places=5)
        self.assertAlmostEqual(metrics["midpoint_residual_p95_deg"], 0, places=5)
        poses[:, 0, 2] = np.deg2rad([0, 120, 0])
        metrics = module.rotation_metrics(poses)
        self.assertAlmostEqual(metrics["midpoint_residual_max_deg"], 120, places=5)
        self.assertEqual(metrics["large_jump_frames"], [2, 3])
        self.assertEqual(metrics["worst_midpoint_frames"][0]["frame_1based"], 2)

    def test_so3_wrap_and_single_frame_are_not_false_jumps(self):
        module = self.module()
        poses = np.zeros((3, 1, 3))
        poses[:, 0, 2] = np.deg2rad([179, 180, -179])
        metrics = module.rotation_metrics(poses)
        self.assertAlmostEqual(metrics["max_adjacent_deg"], 1, places=5)
        self.assertAlmostEqual(metrics["midpoint_residual_max_deg"], 0, places=5)
        metrics = module.rotation_metrics(poses[:1])
        self.assertIsNone(metrics["adjacent_p95_deg"])
        self.assertIsNone(metrics["midpoint_residual_p95_deg"])

    def test_high_raw_motion_is_review_flag_and_never_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Bundle(Path(temp))
            path = bundle.attempt / "fits/fit_case0/smplx/00002_0.npz"
            arrays = {key: np.zeros(shape, np.float32) for key, shape in SHAPES.items()}
            arrays["left_hand_pose"][:, 2] = np.deg2rad(120)
            np.savez(path, **arrays)
            bundle.refresh()
            result, report = bundle.run()
            self.assertEqual(result.returncode, 0, result.stderr)
            row = report["records"][0]
            self.assertEqual(row["quality_tier"], "high_priority_motion_review")
            self.assertFalse(row["human_approved"])
            self.assertIn(2, row["review_frames"])
            self.assertIn("uncalibrated", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
