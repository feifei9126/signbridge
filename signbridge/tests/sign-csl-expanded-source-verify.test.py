"""Independent source audit: corruption, quarantine and non-promotion tests.

Run with PYTHONDONTWRITEBYTECODE=1 python3 tests/sign-csl-expanded-source-verify.test.py.
Fixtures are synthetic metadata; no videos are opened or claimed reviewed.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "src/tools/sign-csl-expanded-source-verify.py"
SPEC = importlib.util.spec_from_file_location("expanded_source_verify", TOOL)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def ce_fixture(number="train-00001"):
    raw = dict(zip(
        audit.HEADERS, [number, "J", "不要走。", " 不 /走//。/", "原始注释"]
    ))
    tokens = audit.tokenize(raw["Gloss"])
    origin = {
        "id": "csl_ce_csl_" + number.replace("-", "_"),
        "raw": raw,
        "source_id": number,
        "source_split": "train",
        "source_translator": "J",
        "source_label": {
            "relative_path": "label/train.csv", "sha256": "a" * 64,
            "record_number": 1, "csv_line_end": 2,
            "record_sha256": hashlib.sha256(json.dumps(
                raw, ensure_ascii=False, separators=(",", ":")
            ).encode()).hexdigest(),
        },
        "gloss_tokens": tokens,
        "gloss_sequence": [t["label"] for t in tokens if t["kind"] == "gloss"],
    }
    sample = {
        **copy.deepcopy(origin), "dataset_id": "CE-CSL", "status": "retained",
        "local_video": "ce-csl/video/train/J/" + number + ".mp4",
        "media_sha256": "b" * 64, "proposed_text": raw["Chinese Sentences"],
        "signer_id": None, "mirror_status": "unknown", "word_spans": [],
        "training_ready": False, "model_training_ready": False,
        "word_boundaries_verified": False, "human_approved": False,
    }
    return sample, origin


def tutorial_fixture():
    source = {
        "id": "lexical-one", "canonical_text": "多", "unit_type": "word",
        "source_id": "tutorial-one", "source_sha256": "c" * 64,
        "lesson_number": 1, "course_title": "例课", "meaning": "程度增加。",
        "do_not_equate": ["数字五"], "evidence_status": "unresolved",
        "word_motion_alignment_verified": False, "source_intervals": [],
        "manual_form_note": "unknown", "uncertainties": ["动作未知"],
        "training_ready": False, "model_training_ready": False,
    }
    refined = {
        "original_lexical_id": "lexical-one", "canonical_text": "多",
        "source_unit_type": "word", "refined_unit_type": "word",
        "source_id": "tutorial-one", "source_sha256": "c" * 64,
        "lesson_number": 1, "course_title": "例课", "meaning_clean": "程度增加。",
        "do_not_equate": ["数字五"], "evidence_status": "unresolved",
        "word_motion_alignment_verified": False, "review_uncertainties": ["动作未知"],
        "training_ready": False, "model_training_ready": False,
    }
    return refined, source


class SourceAuditTests(unittest.TestCase):
    def assert_never_promotes(self, row):
        self.assertIs(row["full_action_pass"], False)
        self.assertIs(row["training_ready"], False)
        self.assertIs(row["model_training_ready"], False)
        self.assertEqual(row["word_motion_alignment_status"], "unknown")
        self.assertIs(row["video_viewed_this_audit"], False)

    def test_slashes_empty_slots_punctuation_and_order_are_preserved(self):
        result = audit.tokenize(" 你 /好//。/!?/3/ ")
        self.assertEqual([t["raw"] for t in result], [" 你 ", "好", "", "。", "!?", "3", " "])
        self.assertEqual([t["kind"] for t in result],
                         ["gloss", "gloss", "empty", "punctuation", "punctuation", "gloss", "empty"])
        self.assertEqual([t["position"] for t in result], list(range(7)))

    def test_matching_ce_has_only_technical_source_pass(self):
        row = audit.audit_ce(*ce_fixture())
        self.assertEqual(row["source_status"], "pass")
        self.assert_never_promotes(row)
        self.assertIsNone(row["preserved_unknowns"]["signer_id"])
        self.assertEqual(row["preserved_unknowns"]["mirror_status"], "unknown")

    def test_ce_rejects_each_provenance_corruption(self):
        mutations = [
            ("source_split", "dev"), ("source_translator", "K"),
            ("source_id", "train-09999"), ("gloss_sequence", ["走", "不"]),
            ("gloss_tokens", []), ("raw", {"Gloss": "走/不"}),
            ("proposed_text", "走。"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                sample, origin = ce_fixture()
                sample[field] = value
                self.assertEqual(audit.audit_ce(sample, origin)["source_status"], "fail")
        for field in ce_fixture()[1]["source_label"]:
            with self.subTest(label_field=field):
                sample, origin = ce_fixture()
                sample["source_label"][field] = "wrong"
                self.assertEqual(audit.audit_ce(sample, origin)["source_status"], "fail")

    def test_quarantine_is_mandatory_even_with_matching_source(self):
        for number in ("train-03571", "train-03572"):
            sample, origin = ce_fixture(number)
            self.assertEqual(audit.audit_ce(sample, origin)["source_status"], "fail")
            sample["status"] = "quarantined_label_conflict"
            sample["local_video"] = "quarantine/" + sample["local_video"]
            row = audit.audit_ce(sample, origin)
            self.assertEqual(row["source_status"], "pass")
            self.assertEqual(row["disposition"], "quarantine")
            self.assert_never_promotes(row)
            sample["training_ready"] = True
            self.assertEqual(audit.audit_ce(sample, origin)["source_status"], "fail")

    def test_missing_ce_is_accounted_for(self):
        _, origin = ce_fixture("train-03571")
        row = audit.audit_ce(None, origin)
        self.assertEqual(row["source_status"], "fail")
        self.assertEqual(row["id"], origin["id"])
        self.assertEqual(row["disposition"], "quarantine")

    def test_tutorial_preserves_unknown_and_compares_meaning_and_exclusions(self):
        refined, source = tutorial_fixture()
        row = audit.audit_tutorial(refined, source, copy.deepcopy(refined))
        self.assertEqual(row["source_status"], "pass")
        self.assertEqual(row["annotation_status"], "unresolved")
        self.assert_never_promotes(row)
        for key, value in (("meaning_clean", "数字五。"), ("do_not_equate", []),
                           ("source_sha256", "d" * 64), ("evidence_status", "pass")):
            with self.subTest(key=key):
                modified = {**refined, key: value}
                self.assertEqual(audit.audit_tutorial(modified, source, refined)["source_status"], "fail")

    def test_tutorial_cannot_self_attest_by_altering_annotation_snapshot(self):
        refined, source = tutorial_fixture()
        refined["meaning_clean"] = "数字五。"
        row = audit.audit_tutorial(refined, source, copy.deepcopy(refined))
        self.assertEqual(row["source_status"], "fail")

    def caption_fixture(self):
        sample = {
            "id": "caption-one", "source_id": "extra-one", "source_sha256": "e" * 64,
            "raw": {"Chinese Sentences": "延量"}, "media_sha256": "f" * 64,
            "source_window_seconds_nominal": [7, 11], "local_video": "clip.mp4",
            "training_ready": False, "model_training_ready": False,
        }
        window = {
            "id": "caption-one", "source_id": "extra-one", "source_sha256": "e" * 64,
            "label_candidate": "延量", "local_video_sha256": "f" * 64,
            "source_window_seconds_nominal": [7, 11], "local_video": "clip.mp4",
        }
        correction = {
            "candidate_id": "caption-one", "raw_text": "延量", "corrected_text": "邮局",
            "source_sha256": "e" * 64, "source_clip_sha256": "f" * 64,
            "refined_unit_type": "word", "reason": "旧记录的画面说明",
        }
        refined = {
            "id": "caption-one", "source_sha256": "e" * 64, "raw_text": "延量",
            "clean_text": "邮局", "refined_unit_type": "word", "lexicon_eligible": True,
            "reason": correction["reason"], "visual_correction": copy.deepcopy(correction),
            "source_authority": "assistant_actual_midframe_review",
            "training_ready": False, "model_training_ready": False,
        }
        source = {"id": "extra-one", "sha256": "e" * 64}
        return refined, window, sample, correction, source

    def test_caption_correction_is_traced_without_claiming_visual_review(self):
        row = audit.audit_caption(*self.caption_fixture())
        self.assertEqual(row["source_status"], "pass")
        self.assertEqual(row["annotation_status"], "unknown")
        self.assert_never_promotes(row)

    def test_caption_section_titles_cannot_become_lexical_units(self):
        args = self.caption_fixture()
        refined, window, sample, fix, source = args
        fix.update(corrected_text=None, refined_unit_type="section_title")
        refined.update(clean_text=None, refined_unit_type="section_title", lexicon_eligible=False,
                       visual_correction=copy.deepcopy(fix))
        self.assertEqual(audit.audit_caption(*args)["source_status"], "pass")
        refined["lexicon_eligible"] = True
        self.assertEqual(audit.audit_caption(*args)["source_status"], "fail")

    def test_caption_wrong_source_window_or_correction_is_detected(self):
        for index, key, value in ((0, "source_sha256", "0" * 64),
                                  (2, "source_window_seconds_nominal", [8, 12]),
                                  (3, "source_clip_sha256", "0" * 64),
                                  (4, "sha256", "0" * 64)):
            with self.subTest(index=index, key=key):
                args = self.caption_fixture()
                args[index][key] = value
                self.assertEqual(audit.audit_caption(*args)["source_status"], "fail")

    def test_identical_form_never_collapses_distinct_meanings(self):
        refined, source = tutorial_fixture()
        second = {**source, "id": "lexical-two", "canonical_text": "司机",
                  "meaning": "驾驶的人。", "do_not_equate": ["汽车", "开车"]}
        first = {**source, "canonical_text": "汽车", "meaning": "车辆。",
                 "do_not_equate": ["司机", "开车"]}
        risks = audit.classification_risks([first, second], [], [])
        found = [x for x in risks if x["kind"] == "do_not_equate_collision"]
        self.assertTrue(found)
        self.assertIn("lexical-one", json.dumps(found))
        self.assertIn("lexical-two", json.dumps(found))
        self.assertTrue(all(x["auto_merge_allowed"] is False for x in risks))

    def test_duplicate_ids_do_not_get_silently_overwritten(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.unique_index([{"id": "same"}, {"id": "same"}], "id", "fixture")

    def test_caption_normalization_requires_same_id_exact_text_unique_type(self):
        caption = {"id": "caption-question", "clean_text": "你家在哪里", "refined_unit_type": "word_candidate"}
        base = {"base-question": {"id": "base-question", "text": "你家在哪里", "unit_type": "sentence",
                                  "source_caption_ids": ["caption-question"]}}
        self.assertEqual(audit.caption_classification(caption, base), ("sentence", ["base-question"], True))
        for key, value in (("source_caption_ids", ["other"]), ("text", "你家在哪里？")):
            with self.subTest(key=key):
                modified = copy.deepcopy(base)
                modified["base-question"][key] = value
                self.assertEqual(audit.caption_classification(caption, modified)[0], "word")
        base["another"] = {**base["base-question"], "id": "another", "unit_type": "phrase"}
        self.assertEqual(audit.caption_classification(caption, base)[0], "word")

    def test_caption_normalization_proof_cannot_grant_motion_approval(self):
        original = {"id": "one", "clean_text": "你家在哪里", "refined_unit_type": "word_candidate", "lexicon_eligible": True}
        base = {"base-one": {"id": "base-one", "text": "你家在哪里", "unit_type": "sentence", "source_caption_ids": ["one"]}}
        item = {"original_refined_unit_type": "word_candidate", "effective_chinese_unit_type": "sentence",
                "classification_normalization": {
                    "original_candidate_type": "word_candidate", "effective_chinese_type": "sentence",
                    "foundation_ids": ["base-one"],
                    "basis": "same_caption_ID_and_exact_text_already_classified_in_foundation",
                    "motion_or_word_boundary_approval": False}}
        self.assertTrue(all(audit.audit_caption_classification(item, original, base).values()))
        for key, value in (("motion_or_word_boundary_approval", True), ("foundation_ids", ["wrong"]),
                           ("basis", "text_only")):
            with self.subTest(key=key):
                modified = copy.deepcopy(item)
                modified["classification_normalization"][key] = value
                self.assertFalse(all(audit.audit_caption_classification(modified, original, base).values()))

    def test_excluded_caption_requires_explicit_original_type_and_null_effective_type(self):
        original = {"id": "title", "clean_text": None, "refined_unit_type": "section_title", "lexicon_eligible": False}
        item = {"original_refined_unit_type": "section_title", "effective_chinese_unit_type": None,
                "classification_normalization": None}
        self.assertTrue(all(audit.audit_caption_classification(item, original, {}).values()))
        for key in item:
            with self.subTest(key=key):
                modified = dict(item)
                del modified[key]
                self.assertFalse(all(audit.audit_caption_classification(modified, original, {}).values()))
        item["effective_chinese_unit_type"] = "word"
        self.assertFalse(all(audit.audit_caption_classification(item, original, {}).values()))

    def gloss_fixture(self):
        return {"id": "gloss-temporary", "unit_type": "dataset_gloss", "sample_ids": ["retained", "quarantine"],
                "retained_sample_ids": ["retained"], "quarantined_sample_ids": ["quarantine"],
                "occurrences_all_by_split": {"train": 2}, "occurrences_retained_by_split": {"train": 1},
                "declared_original_occurrences_by_split": {"train": 2}, "sign_equivalence_certified": False,
                "training_ready": False, "model_training_ready": False}

    def check_gloss(self, item):
        return audit.audit_gloss(item, "暂时", {"train": 2}, {"train": 1}, {"retained", "quarantine"}, {"quarantine"})

    def test_gloss_preserves_all_references_and_separate_retained_and_quarantine(self):
        row = self.check_gloss(self.gloss_fixture())
        self.assertEqual(row["source_status"], "pass")
        self.assert_never_promotes(row)

    def test_gloss_missing_all_reference_is_a_real_v3_contract_difference(self):
        item = self.gloss_fixture()
        item["sample_ids"] = ["retained"]
        self.assertEqual(self.check_gloss(item)["differences"], ["sample_ids"])

    def test_gloss_quarantine_cannot_leak_into_retained_even_when_counts_match(self):
        item = self.gloss_fixture()
        item["retained_sample_ids"].append("quarantine")
        self.assertIn("quarantine_not_in_retained", self.check_gloss(item)["differences"])

    def test_variants_look_one_and_two_are_not_folded_or_deduplicated(self):
        tokens = audit.tokenize("看1/看2/看1")
        self.assertEqual([x["label"] for x in tokens], ["看1", "看2", "看1"])

    def test_metadata_reader_accepts_bound_manifest_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            name = "6094cdbfdca350e6-SHA256SUMS"
            (root / name).write_text("manifest snapshot")
            reader = audit.MetadataReader(root, "expanded", require_manifest=False)
            self.assertEqual(reader.read(name), b"manifest snapshot")

    def test_metadata_reader_checks_manifest_and_does_not_open_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = b'{"id":"one"}\n'
            (root / "rows.jsonl").write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            (root / "SHA256SUMS").write_text(digest + "  rows.jsonl\n")
            reader = audit.MetadataReader(root, "fixture")
            self.assertEqual(reader.jsonl("rows.jsonl"), [{"id": "one"}])
            self.assertEqual(reader.inputs[-1]["manifest_status"], "pass")
            with self.assertRaisesRegex(ValueError, "metadata"):
                reader.read("video.mp4")
            (root / "rows.jsonl").write_text('{"id":"changed"}\n')
            with self.assertRaisesRegex(ValueError, "changed"):
                reader.assert_unchanged()

    def test_manifest_mismatch_is_recorded_as_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "rows.jsonl").write_text('{"id":"one"}\n')
            (root / "SHA256SUMS").write_text("0" * 64 + "  rows.jsonl\n")
            reader = audit.MetadataReader(root, "fixture")
            reader.jsonl("rows.jsonl")
            self.assertEqual(reader.inputs[-1]["manifest_status"], "fail")

    def test_output_never_overwrites_or_enters_input_library(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            with self.assertRaises(ValueError):
                audit.prepare_output(source / "audit", [source])
            destination = root / "result"
            destination.mkdir()
            with self.assertRaises(FileExistsError):
                audit.prepare_output(destination, [source])
            self.assertTrue(source.is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
