"""CPU-only, synthetic media contract for the offline post-fit review builder."""

import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "src/tools/sign-smplx-post-review.py"
FLAGS = {"human_approved": False, "semantic_approved": False,
         "training_ready": False, "model_training_ready": False,
         "training_started": False, "text_verified": ""}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, data=None):
    result = subprocess.run(args, input=data, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr.decode(errors="replace"))
    return result.stdout


def ffmpeg(*args, data=None):
    return command(["ffmpeg", "-v", "error", "-nostdin", "-y",
                    "-threads", "1", "-filter_threads", "1", *map(str, args)], data)


class Fixture:
    def __init__(self, root):
        self.root = root
        self.source = root / "source"
        self.input = self.source / "input"
        self.render = self.source / "render"
        self.fit = self.source / "fit"
        self.clip = self.source / "clip.mp4"
        self.audit = root / "audit.json"
        self.output = root / "review"
        self.colors = [(240, 20, 20), (20, 230, 20), (20, 20, 240), (230, 230, 20)]
        for folder, colors in ((self.input, self.colors),
                               (self.render, list(reversed(self.colors)))):
            folder.mkdir(parents=True)
            ppm = root / (folder.name + "-ppm")
            ppm.mkdir()
            for frame, color in enumerate(colors, 1):
                (ppm / f"{frame:06d}.ppm").write_bytes(
                    b"P6\n48 32\n255\n" + bytes(color) * (48 * 32))
            ffmpeg("-start_number", "1", "-i", ppm / "%06d.ppm",
                   "-frames:v", "4", "-threads", "1", folder / "%06d.jpg")
        self.fit.mkdir()
        # The clip is deliberately different from the original input JPEGs.
        ffmpeg("-f", "lavfi", "-i", "color=c=purple:s=48x32:r=5",
               "-frames:v", "4", "-c:v", "libx264", "-threads", "1",
               "-pix_fmt", "yuv420p", self.clip)
        self.row = {"uid": "candidate-1", "annotation_id": "fit-1", "chunk": "chunk-1",
                    "source_id": "source-1", "source_sha256": "a" * 64,
                    "label_candidate": "候选", "fps": 5, "frames_expected": 4,
                    "missing_detection_frames": [], "status": "candidate_only",
                    "quality_tier": "no_automatic_motion_red_flag", "technical_errors": [],
                    "raw_rotation_metrics": None, "review_frames": [4, 2],
                    "clip_path": str(self.clip), "input_directory": str(self.input),
                    "render_directory": str(self.render), "fit_directory": str(self.fit),
                    **FLAGS}

    def run(self, rows=None, output=None, audit_text=None):
        self.audit.write_text(audit_text if audit_text is not None else json.dumps(
            {"records": rows if rows is not None else [self.row]}, ensure_ascii=False))
        before = {p.relative_to(self.source).as_posix(): digest(p)
                  for p in self.source.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, "-B", str(TOOL), "--audit", str(self.audit),
                                 "--output", str(output or self.output), "--workers", "3"],
                                capture_output=True, text=True)
        after = {p.relative_to(self.source).as_posix(): digest(p)
                 for p in self.source.rglob("*") if p.is_file()}
        if before != after:
            raise AssertionError("Builder changed source media")
        report_path = (output or self.output) / "report.json"
        return result, json.loads(report_path.read_text()) if report_path.is_file() else None


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class PostReviewTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file(), "Offline all-candidate media builder is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture(Path(self.temp.name))

    def assert_flags(self, obj):
        for key, value in FLAGS.items():
            self.assertEqual(obj[key], value, key)

    def test_all_candidates_exact_contact_frames_original_bytes_and_manifest(self):
        f = self.fixture
        unsafe = "</script><img src=x onerror=alert(1)> ../../候选"
        second = {**f.row, "uid": "../../escape", "label_candidate": unsafe,
                  "missing_detection_frames": [2], "quality_tier": "quarantine_missing_detections"}
        result, report = f.run([f.row, second])
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = report["summary"]
        self.assertEqual(summary["total_records"], 2)
        self.assertEqual(summary["successful_candidates"], 2)
        self.assertEqual(summary["successful_media"], 6)
        self.assertEqual(summary["processed_frames"], 8)
        self.assertEqual(summary["failure_count"], 0)
        self.assertEqual(summary["quarantined_candidates"], 1)
        for obj in [report, summary, *report["records"]]:
            self.assert_flags(obj)
            self.assertEqual(obj.get("quality_assessments"), {
                "collision": "unassessed", "semantic": "unassessed", "human_visual": "unassessed"})
        for row in report["records"]:
            self.assertEqual(row["label_status"], "candidate_only")
            self.assertIsNone(row["raw_rotation_metrics"])
            self.assertEqual(row["review_frames"], [4, 2])
            self.assertEqual(row["processed_frames"], 4)
            self.assertEqual(row["failures"], [])
            for kind in ("contact", "original", "comparison"):
                asset = row["media"][kind]
                path = f.output / asset["path"]
                self.assertTrue(path.resolve().is_relative_to(f.output.resolve()))
                self.assertEqual(digest(path), asset["sha256"])
            original = row["media"]["original"]
            self.assertEqual((f.output / original["path"]).read_bytes(), f.clip.read_bytes())
            comparison = row["media"]["comparison"]
            self.assertEqual(comparison["frames"], 4)
            self.assertEqual(comparison["height"], 360)
            self.assertLessEqual(comparison["width"], 1280)
            self.assertEqual(comparison["codec"], "h264")
            decoded = json.loads(command(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                          "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json",
                                          str(f.output / comparison["path"])]))["streams"][0]
            self.assertEqual(decoded["nb_read_frames"], "4")
            self.assertEqual(decoded["avg_frame_rate"], "5/1")
            pixels = ffmpeg("-i", f.output / row["media"]["contact"]["path"],
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
            width = row["media"]["contact"]["width"]
            # Row order must follow [4, 2], and left must use input JPEG, not the purple clip.
            for y, color in ((90, f.colors[3]), (270, f.colors[1])):
                offset = (y * width + 160) * 3
                self.assertTrue(all(abs(pixels[offset + i] - color[i]) < 22 for i in range(3)))
        self.assertEqual(report["records"][1]["review_status"], "quarantined_candidate")
        files = {p.relative_to(f.output).as_posix(): digest(p)
                 for p in f.output.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
        manifest = dict((name, sha) for sha, name in
                        (line.split("  ", 1) for line in (f.output / "SHA256SUMS").read_text().splitlines()))
        self.assertEqual(manifest, files)
        script = (f.output / "review-data.js").read_text()
        self.assertNotIn("</script>", script)
        self.assertIn("\\u003c/script\\u003e", script)
        self.assertEqual(report["records"][1]["label_candidate"], unsafe)

    def test_failures_count_all_rows_and_independent_media_tasks_continue(self):
        f = self.fixture
        bad = {**f.row, "uid": "bad", "clip_path": str(f.source / "absent.mp4"),
               "render_directory": str(f.source / "absent-render")}
        result, report = f.run([bad, None, f.row])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(report["summary"]["total_records"], 3)
        self.assertEqual(len(report["records"]), 3)
        self.assertEqual(report["summary"]["successful_candidates"], 1)
        self.assertEqual(report["summary"]["processed_frames"], 4)
        self.assertEqual(report["summary"]["failed_candidates"], 2)
        self.assertGreaterEqual(len(report["records"][0]["failures"]), 3)
        self.assertEqual(report["summary"]["failure_count"],
                         sum(len(row["failures"]) for row in report["records"]))

    def test_corrupt_unsampled_render_fails_full_decode_but_keeps_valid_assets(self):
        f = self.fixture
        f.row["review_frames"] = [1]
        (f.render / "000003.jpg").write_bytes(b"not actually a jpeg")
        result, report = f.run()
        self.assertEqual(result.returncode, 2, result.stderr)
        row = report["records"][0]
        self.assertIsNotNone(row["media"]["contact"])
        self.assertIsNotNone(row["media"]["original"])
        self.assertIsNone(row["media"]["comparison"])
        self.assertEqual(row["processed_frames"], 0)
        self.assertTrue(any(e["stage"] == "comparison" for e in row["failures"]))
        self.assertFalse(any(p.name == "comparison.mp4" for p in f.output.rglob("*")))

    def test_jpeg_disguised_as_mp4_is_not_a_real_original_clip(self):
        f = self.fixture
        fake = f.source / "fake.mp4"
        shutil.copyfile(f.input / "000001.jpg", fake)
        result, report = f.run([{**f.row, "clip_path": str(fake), "frames_expected": 1,
                                 "review_frames": [1]}])
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report["records"][0]["media"]["original"])
        self.assertIsNone(report["records"][0]["media"]["comparison"])

    def test_jpeg_header_with_corrupt_payload_cannot_hide_in_unsampled_frames(self):
        f = self.fixture
        f.row["review_frames"] = [1]
        (f.render / "000003.jpg").write_bytes(b"\xff\xd8\xffbroken payload")
        result, report = f.run()
        self.assertEqual(result.returncode, 2)
        row = report["records"][0]
        self.assertIsNone(row["media"]["comparison"])
        self.assertIsNotNone(row["media"]["contact"])
        self.assertTrue(any(e["stage"] == "comparison" for e in row["failures"]))

    def test_short_clip_invalid_frames_and_true_flags_cannot_be_promoted(self):
        f = self.fixture
        short = f.source / "short.mp4"
        ffmpeg("-i", f.clip, "-frames:v", "2", "-c:v", "libx264", "-threads", "1", short)
        result, report = f.run([{**f.row, "clip_path": str(short), "human_approved": True,
                                 "review_frames": [0, 5]}])
        self.assertEqual(result.returncode, 2)
        row = report["records"][0]
        self.assert_flags(row)
        self.assertEqual(row["review_status"], "quarantined_candidate")
        self.assertIsNone(row["media"]["original"])
        self.assertIsNone(row["media"]["comparison"])
        self.assertGreaterEqual(len(row["failures"]), 3)

    def test_source_path_traversal_and_escaping_symlinks_are_rejected(self):
        f = self.fixture
        outside = f.root / "outside.jpg"
        shutil.copyfile(f.render / "000001.jpg", outside)
        outside_hash = digest(outside)
        (f.render / "000001.jpg").unlink()
        (f.render / "000001.jpg").symlink_to(outside)
        result, report = f.run([{**f.row, "review_frames": [1],
                                 "clip_path": str(f.source) + "/../source/clip.mp4"},
                                {**f.row, "clip_path": "javascript:alert(1)", "review_frames": [1]}])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary"]["successful_candidates"], 0)
        self.assertTrue(all(row["media"]["original"] is None for row in report["records"]))
        self.assertTrue(all(row["media"]["contact"] is None for row in report["records"]))
        self.assertEqual(digest(outside), outside_hash)

    def test_existing_output_and_source_nested_output_fail_without_writes(self):
        f = self.fixture
        f.output.mkdir()
        marker = f.output / "keep"
        marker.write_text("untouched")
        result, report = f.run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(report)
        self.assertEqual(marker.read_text(), "untouched")
        nested = f.input / "review"
        result, _ = f.run(output=nested)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(nested.exists())

    def test_duplicate_uids_and_unknown_quality_do_not_drop_candidates(self):
        f = self.fixture
        result, report = f.run([f.row, {**f.row, "quality_tier": None}])
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = [row["media"]["original"]["path"] for row in report["records"]]
        self.assertEqual(len(set(paths)), 2)
        self.assertEqual(report["records"][1]["quality_tier"], None)
        self.assertEqual(report["summary"]["total_records"], 2)

    def test_nonfinite_metadata_stays_unknown_without_aborting_other_rows(self):
        f = self.fixture
        raw = json.dumps({"records": [{**f.row, "raw_rotation_metrics": {"peak": float("inf")}}]})
        result, report = f.run(audit_text=raw.replace("Infinity", "1e999"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["records"][0]["raw_rotation_metrics"], {"peak": None})

    def test_empty_audit_still_produces_offline_assets(self):
        result, report = self.fixture.run([])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["summary"]["total_records"], 0)
        for name in ("index.html", "review.js", "review.css", "review-data.js", "SHA256SUMS"):
            self.assertTrue((self.fixture.output / name).is_file())

    def test_approval_claims_fail_even_when_all_media_assets_succeed(self):
        f = self.fixture
        result, report = f.run([{**f.row, "human_approved": True}])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary"]["successful_media"], 3)
        self.assertEqual(report["summary"]["failed_candidates"], 1)
        self.assertEqual(report["summary"]["successful_candidates"], 0)
        self.assertEqual(report["summary"]["processed_frames"], 4)
        self.assert_flags(report["records"][0])

    def test_contact_sheet_composition_uses_no_per_image_subprocesses(self):
        f = self.fixture
        module = runpy.run_path(str(TOOL))
        output = f.root / "sheet-only"
        output.mkdir()
        with patch("subprocess.run", side_effect=AssertionError("Contact composition must decode with Pillow")):
            result = module["contact_sheet"](f.row, output, output)
        self.assertEqual(result["review_frames"], [4, 2])
        self.assertEqual(result["width"], 640)
        self.assertEqual(result["height"], 360)
        self.assertTrue((output / result["path"]).is_file())

    def test_each_completed_row_is_checkpointed_and_progress_stays_compact(self):
        f = self.fixture
        result, report = f.run([f.row, None, {**f.row, "uid": "last"}])
        self.assertEqual(result.returncode, 2)
        journal = f.output / "progress.jsonl"
        self.assertTrue(journal.is_file(), "Completed rows need a flushed journal before the final report")
        entries = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry["completed_candidates"] for entry in entries], [1, 2, 3])
        self.assertEqual(sorted(entry["record"]["row_index"] for entry in entries), [0, 1, 2])
        for entry in entries:
            full = report["records"][entry["record"]["row_index"]]
            self.assertEqual(entry["record"]["uid"], full["uid"])
            self.assertEqual(entry["record"]["review_status"], full["review_status"])
            self.assertEqual(entry["record"]["failure_count"], len(full["failures"]))
            self.assert_flags(full)
        progress = [json.loads(line) for line in result.stderr.splitlines() if line.strip()]
        self.assertEqual(progress[-1]["completed_candidates"], 3)
        self.assertEqual(progress[-1]["total_candidates"], 3)
        self.assertEqual(progress[-1]["failure_count"], report["summary"]["failure_count"])
        self.assertLess(len(progress), 5)


if __name__ == "__main__":
    unittest.main()
