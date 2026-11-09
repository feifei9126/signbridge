#!/usr/bin/env python3
"""Independently re-read frozen CSL source annotations and optional expanded tables.

Standard library only. Never opens media, trains, watches a video, grants linguistic
approval, or modifies inputs. A technical source pass is not a full action pass.
Exit 0: technical checks pass; 1: recorded differences; 2: input/CLI error.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata


HEADERS = ["Number", "Translator", "Chinese Sentences", "Gloss", "Note"]
SPLITS = ("train", "dev", "test")
QUARANTINE = {"csl_ce_csl_train_03571", "csl_ce_csl_train_03572"}
EXCLUDED_TYPES = {"section_title", "theory_context", "grammar_concept"}
DIMENSIONS = {"semantics", "handshape", "palm_orientation", "location", "path",
              "nonmanual", "boundaries", "temporal_stability", "collision"}
GATE_KEYS = {"training_ready", "model_training_ready", "trainready", "training_allowed",
             "full_action_pass", "full_ready", "full_action_human_approved"}
EXPECTED = {"samples": 6315, "ce": 5988, "tutorial": 573, "captions": 255,
            "foundation": 127, "excluded": 21, "actions": 283, "gloss": 3859,
            "characters": 2087}
SCHEMA = "signbridge-independent-expanded-source-audit-v1"


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def record_hash(value):
    """Stable object digest; CSV row hashes separately retain header insertion order."""
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8"))


def unique_index(rows, key, label):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result:
            raise ValueError(f"Duplicate {label} identity: {identity}")
        result[identity] = row
    return result


def gates_clear(value):
    if isinstance(value, dict):
        return all(not (key in GATE_KEYS and item is not False)
                   and gates_clear(item) for key, item in value.items())
    if isinstance(value, list):
        return all(gates_clear(item) for item in value)
    return True


def tokenize(raw):
    """Independent parsing; no import of a producer or its validation helpers."""
    tokens = []
    for position, part in enumerate(raw.split("/")):
        label = part.strip()
        kind = "empty" if not label else (
            "punctuation" if all(unicodedata.category(c).startswith("P") for c in label)
            else "gloss")
        tokens.append(dict(position=position, raw=part, label=label, kind=kind))
    return tokens


class MetadataReader:
    """Hash only metadata actually read; compare to a frozen manifest when present."""

    def __init__(self, root, name, require_manifest=True):
        self.root = Path(root).resolve(strict=True)
        self.name = name
        self.cache = {}
        self.inputs = []
        self.manifest = {}
        path = self.root / "SHA256SUMS"
        if path.exists():
            raw = self.read("SHA256SUMS")
            for line in raw.decode("utf-8").splitlines():
                checksum, relative = line.split("  ", 1)
                if not re.fullmatch(r"[0-9a-f]{64}", checksum) or relative in self.manifest:
                    raise ValueError("Malformed/duplicate frozen manifest: " + str(path))
                self.manifest[relative] = checksum
        elif require_manifest:
            raise ValueError("Missing frozen manifest: " + str(path))

    def path(self, relative):
        part = Path(relative)
        path = self.root / part
        if part.is_absolute() or ".." in part.parts or "\\" in str(relative):
            raise ValueError("Unsafe metadata path: " + str(relative))
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Metadata leaves input root: " + str(relative))
        if any(p.is_symlink() for p in (path, *path.parents) if p != self.root):
            raise ValueError("Symlink metadata input: " + str(path))
        return path

    def read(self, relative):
        relative = str(relative)
        if relative in self.cache:
            return self.cache[relative]
        path = self.path(relative)
        manifest_snapshot = bool(re.fullmatch(r"[0-9a-f]{16}-SHA256SUMS", path.name))
        if path.name != "SHA256SUMS" and not manifest_snapshot and path.suffix not in {".json", ".jsonl", ".csv", ".md", ".txt"}:
            raise ValueError("Only metadata may be read/hashed: " + str(path))
        raw = path.read_bytes()
        checksum = digest(raw)
        expected = self.manifest.get(relative)
        status = ("self_digest_only" if relative == "SHA256SUMS" else
                  "pass" if checksum == expected else "fail" if expected else "absent")
        self.inputs.append({"root": self.name, "path": str(path), "relative_path": relative,
                            "bytes": len(raw), "sha256": checksum,
                            "frozen_manifest_sha256": expected, "manifest_status": status})
        self.cache[relative] = raw
        return raw

    def json(self, relative):
        return json.loads(self.read(relative))

    def jsonl(self, relative):
        return [json.loads(line) for line in self.read(relative).decode("utf-8").splitlines()
                if line.strip()]

    def assert_unchanged(self):
        for relative, raw in self.cache.items():
            if self.path(relative).read_bytes() != raw:
                raise ValueError("Input metadata changed during audit: " + str(self.root / relative))


def csv_records(reader, relative, split=None):
    data = reader.read(relative)
    rows = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    if next(rows, None) != HEADERS:
        raise ValueError("Unexpected CSV header: " + str(reader.root / relative))
    result = []
    for number, fields in enumerate(rows, 1):
        if not fields:
            continue
        if len(fields) != len(HEADERS):
            raise ValueError("CSV field count differs: " + str(relative))
        raw = dict(zip(HEADERS, fields))
        label = {"relative_path": f"label/{split}.csv" if split else str(relative),
                 "sha256": digest(data), "record_number": number,
                 "csv_line_end": rows.line_num, "record_sha256": digest(compact(raw).encode())}
        item = {"raw": raw, "source_label": label}
        if split:
            identity = raw["Number"]
            if not re.fullmatch(re.escape(split) + r"-[0-9]+", identity):
                raise ValueError("CSV identity/split differs: " + identity)
            tokens = tokenize(raw["Gloss"])
            item.update(id="csl_ce_csl_" + identity.replace("-", "_"), source_id=identity,
                        source_split=split, source_translator=raw["Translator"],
                        gloss_tokens=tokens,
                        gloss_sequence=[t["label"] for t in tokens if t["kind"] == "gloss"])
        result.append(item)
    return result


def result_row(identity, scope, checks, **details):
    return {"schema": SCHEMA, "id": identity, "scope": scope,
            "source_status": "fail" if any(value is False for value in checks.values()) else "pass",
            "checks": checks, "differences": [key for key, value in checks.items() if value is False],
            "annotation_status": "unknown", "word_motion_alignment_status": "unknown",
            "full_action_pass": False, "training_ready": False, "model_training_ready": False,
            "human_reviewed_this_audit": False, "video_viewed_this_audit": False, **details}


def audit_ce(sample, origin):
    identity = origin["id"] if origin else sample["id"]
    sample = sample or {}
    origin = origin or {}
    checks = {"sample_present": bool(sample), "original_csv_row_present": bool(origin)}
    for key in ("id", "source_id", "source_split", "source_translator", "raw", "gloss_tokens", "gloss_sequence"):
        checks[key] = key in origin and sample.get(key) == origin[key]
    for key in ("relative_path", "sha256", "record_number", "csv_line_end", "record_sha256"):
        checks["source_label." + key] = bool(origin) and (
            sample.get("source_label", {}).get(key) == origin.get("source_label", {}).get(key))
    checks["proposed_text"] = bool(origin) and sample.get("proposed_text") == origin["raw"]["Chinese Sentences"]
    checks["training_gates_stay_closed"] = gates_clear(sample)
    checks["no_invented_word_spans"] = sample.get("word_spans", []) == []
    quarantined = identity in QUARANTINE
    checks["quarantine_status"] = (sample.get("status") == "quarantined_label_conflict" if quarantined
                                   else sample.get("status") == "retained")
    checks["quarantine_location"] = (
        str(sample.get("local_video", "")).startswith("quarantine/") if quarantined else
        str(sample.get("local_video", "")).startswith("ce-csl/"))
    return result_row(identity, "CE-CSL", checks,
                      disposition="quarantine" if quarantined else "retained",
                      original_source=origin, sample_record_sha256=record_hash(sample) if sample else None,
                      observed_source_label=sample.get("source_label"),
                      preserved_unknowns={k: sample.get(k) for k in (
                          "signer_id", "mirror_status", "anatomical_handedness", "text_verified",
                          "project_split", "word_boundaries_verified")})


def audit_tutorial(refined, source, annotation):
    refined, source = refined or {}, source or {}
    checks = {"refinement_present": bool(refined), "source_present": bool(source),
              "snapshot_exact": refined == annotation, "training_gates_stay_closed": gates_clear(refined)}
    for target, original in (
        ("original_lexical_id", "id"), ("canonical_text", "canonical_text"),
        ("source_unit_type", "unit_type"), ("meaning_clean", "meaning"),
        ("do_not_equate", "do_not_equate"), ("source_id", "source_id"),
        ("source_sha256", "source_sha256"), ("lesson_number", "lesson_number"),
        ("course_title", "course_title"), ("evidence_status", "evidence_status"),
        ("word_motion_alignment_verified", "word_motion_alignment_verified"),
    ):
        checks[target] = original in source and refined.get(target) == source[original]
    checks["uncertainties_preserved"] = set(source.get("uncertainties", [])).issubset(
        set(refined.get("review_uncertainties", [])))
    identity = source.get("id", refined.get("original_lexical_id", "missing"))
    return result_row(identity, "tutorial", checks, original_lexical=source, refined_annotation=refined,
                      original_record_sha256=record_hash(source), refined_record_sha256=record_hash(refined),
                      annotation_status="unresolved" if source.get("evidence_status") == "unresolved" else "unknown")


def audit_caption(refined, window, sample, correction, source):
    refined, window, sample, source = refined or {}, window or {}, sample or {}, source or {}
    checks = {"refinement_present": bool(refined), "window_present": bool(window),
              "sample_present": bool(sample), "source_present": bool(source),
              "training_gates_stay_closed": gates_clear(refined),
              "id": refined.get("id") == window.get("id") == sample.get("id"),
              "source_sha256": refined.get("source_sha256") == window.get("source_sha256")
              == sample.get("source_sha256") == source.get("sha256"),
              "source_id": window.get("source_id") == sample.get("source_id") == source.get("id"),
              "raw_text": refined.get("raw_text") == window.get("label_candidate")
              == sample.get("raw", {}).get("Chinese Sentences"),
              "nominal_window": window.get("source_window_seconds_nominal") == sample.get("source_window_seconds_nominal"),
              "clip_metadata_digest": window.get("local_video_sha256") == sample.get("media_sha256"),
              "clip_path": window.get("local_video") == sample.get("local_video"),
              "correction_snapshot": refined.get("visual_correction") == correction}
    if correction:
        for key, value in (("candidate_id", refined.get("id")),
                           ("raw_text", refined.get("raw_text")),
                           ("source_sha256", window.get("source_sha256")),
                           ("source_clip_sha256", window.get("local_video_sha256"))):
            checks["correction." + key] = correction.get(key) == value
        for field, original in (("clean_text", "corrected_text"), ("refined_unit_type", "refined_unit_type"), ("reason", "reason")):
            checks[field] = refined.get(field) == correction.get(original)
    else:
        checks["uncorrected_text_exact"] = refined.get("clean_text") == window.get("label_candidate")
        checks["unreviewed_caption_class_not_certified"] = refined.get("refined_unit_type") in {"word_candidate", "phrase", "sentence"}
    eligible = refined.get("clean_text") is not None and refined.get("refined_unit_type") not in EXCLUDED_TYPES
    checks["exclusion"] = refined.get("lexicon_eligible") is eligible
    return result_row(refined.get("id", window.get("id", "missing")), "caption", checks,
                      excluded_from_lexicon=not eligible, original_window=window,
                      refined_annotation=refined, correction_snapshot=correction,
                      source_metadata=source,
                      visual_correction_independently_viewed=False)


def base_text_key(text):
    """Only for checking the *existing* foundation's documented source links."""
    return text.strip().rstrip("。！？!?")


def audit_foundation(unit, target, lexical, captions):
    unit, target = unit or {}, target or {}
    checks = {"unit_present": bool(unit), "target_present": bool(target),
              "gates_closed": gates_clear(unit), "target_gates_closed": gates_clear(target)}
    for field, original in (("text", "text"), ("meaning", "meaning"), ("category", "category"),
                            ("do_not_equate", "do_not_equate"), ("target_structure_type", "target_unit_type")):
        checks[field] = original in target and unit.get(field) == target[original]
    expected_lexical = [x for x in lexical.values()
                        if base_text_key(x["canonical_text"]) == base_text_key(target.get("text", ""))]
    expected_captions = [x for x in captions.values() if x.get("lexicon_eligible") and
                         base_text_key(x["clean_text"]) == base_text_key(target.get("text", ""))]
    checks["source_lexical_ids"] = unit.get("source_lexical_ids") == [x["id"] for x in expected_lexical]
    checks["source_caption_ids"] = unit.get("source_caption_ids") == [x["id"] for x in expected_captions]
    forms = [{"id": x["id"], "source_id": x["source_id"], "meaning": x["meaning"],
              "manual_form_note": x.get("manual_form_note"), "nonmanual_note": x.get("nonmanual_note"),
              "intervals": x["source_intervals"], "uncertainties": x["uncertainties"],
              "evidence_status": x["evidence_status"]} for x in expected_lexical]
    checks["each_source_form_exact"] = unit.get("source_forms") == forms
    expected_id = "basic-" + digest((base_text_key(unit.get("text", "")) + "\0" + unit.get("unit_type", "")).encode())[:20]
    checks["id"] = unit.get("id") == expected_id
    return result_row(unit.get("id", "missing"), "foundation", checks,
                      original_target=target, original_foundation_unit=unit,
                      original_target_record_sha256=record_hash(target),
                      original_unit_record_sha256=record_hash(unit))


def classification_risks(lexical, refined, captions):
    """Concrete source records and constraints; no inferred sign equivalence."""
    result = []

    def add(kind, identities, evidence, repair):
        result.append({"kind": kind, "record_ids": identities, "evidence": evidence,
                       "suggested_repair": repair, "auto_merge_allowed": False,
                       "semantic_correctness": "unknown", "training_ready": False})

    by_surface = defaultdict(list)
    by_form = defaultdict(list)
    for row in lexical:
        by_surface[row["canonical_text"]].append(row)
        if row.get("manual_form_note"):
            by_form[row["manual_form_note"]].append(row)
        if row.get("evidence_status") == "unresolved":
            add("unresolved_annotation", [row["id"]], row,
                "保留 unresolved 和来源上下文；补齐连续动作与义项证据后单独复核。")
    for text, rows in by_surface.items():
        if len(rows) > 1 and len({(x.get("meaning"), x.get("manual_form_note")) for x in rows}) > 1:
            add("same_surface_different_context", [x["id"] for x in rows],
                {"text": text, "source_senses": rows},
                "检索可分组，但逐来源保留意义、手形、区间和不等同约束；不能平均或复制动作。")
    for form, rows in by_form.items():
        if len({x["canonical_text"] for x in rows}) > 1:
            add("same_form_different_label", [x["id"] for x in rows],
                {"manual_form_note": form, "source_senses": rows},
                "文字动作说明相同不证明义项相同；保留独立词条与来源意义。")
    labels = {x["canonical_text"] for x in lexical if len(x["canonical_text"]) >= 2}
    for row in lexical:
        hits = sorted({text for constraint in row.get("do_not_equate", []) for text in labels
                       if text != row["canonical_text"] and text in constraint})
        if hits:
            related = [x for text in hits for x in by_surface[text]]
            add("do_not_equate_collision", [row["id"], *[x["id"] for x in related]],
                {"record": row, "referenced_distinct_senses": related},
                "落实 do_not_equate 为来源义项约束；不得以同字、同动作说明或相邻标签消除区别。")
    source_map = {x["id"]: x for x in lexical}
    for row in refined:
        source = source_map.get(row["original_lexical_id"], {})
        if row.get("refined_unit_type") != source.get("unit_type"):
            add("classification_revision", [row["original_lexical_id"]],
                {"source_type": source.get("unit_type"), "refined_annotation": row},
                "保留原分类和修订理由；分类技术一致不代表动作边界或手语句法获认证。")
    for row in captions:
        if not row.get("lexicon_eligible"):
            add("nonlexical_caption_exclusion", [row["id"]], row,
                "保留来源记录供追溯，但禁止进入中文词条或动作词库。")
    return result


def technical_check(checks, label, passed, **detail):
    checks.append({"check": label, "status": "pass" if passed else "fail", **detail})


def check_set(checks, label, actual, expected):
    actual, expected = set(actual), set(expected)
    technical_check(checks, label, actual == expected,
                    missing=sorted(expected - actual), unexpected=sorted(actual - expected))


def normalize_counts(value):
    return {split: value.get(split, 0) for split in SPLITS}


def caption_classification(caption, base):
    """Inherit a unique Chinese type only from same caption ID AND trimmed text."""
    original_type = caption["refined_unit_type"]
    fallback = "word" if original_type == "word_candidate" else original_type
    matches = [unit for unit in base.values()
               if caption["id"] in unit.get("source_caption_ids", [])
               and isinstance(caption.get("clean_text"), str)
               and unit["text"].strip() == caption["clean_text"].strip()]
    types = {unit["unit_type"] for unit in matches}
    effective = next(iter(types)) if len(types) == 1 else fallback
    return effective, sorted(unit["id"] for unit in matches), effective != fallback


def audit_caption_classification(item, original, base):
    effective, matched_base_ids, changed = caption_classification(original, base)
    if not original["lexicon_eligible"]:
        return {
            "original_caption_classification_retained": item.get("original_refined_unit_type") == original["refined_unit_type"],
            "excluded_has_no_effective_lexical_type": "effective_chinese_unit_type" in item and item["effective_chinese_unit_type"] is None,
            "excluded_has_no_classification_normalization": "classification_normalization" in item and item["classification_normalization"] is None}
    checks = {
        "original_caption_classification_retained": item.get("original_refined_unit_type") == original["refined_unit_type"],
        "effective_chinese_classification": item.get("effective_chinese_unit_type") == effective}
    if changed:
        expected = {
            "original_candidate_type": original["refined_unit_type"],
            "effective_chinese_type": effective, "foundation_ids": matched_base_ids,
            "basis": "same_caption_ID_and_exact_text_already_classified_in_foundation",
            "motion_or_word_boundary_approval": False}
        checks["normalization_exact_source_evidence"] = item.get("classification_normalization") == expected
    else:
        checks["no_extra_classification_change"] = item.get("classification_normalization") is None
    return checks


def audit_gloss(item, text, all_counts, retained_counts, all_sample_ids, quarantined_ids):
    actual_ids = item.get("sample_ids", [])
    actual_retained = item.get("retained_sample_ids", [])
    actual_quarantine = item.get("quarantined_sample_ids", [])
    c = {"namespace": item.get("unit_type") == "dataset_gloss",
         "all_split_counts": normalize_counts(item.get("occurrences_all_by_split", {})) == normalize_counts(all_counts),
         "retained_split_counts": normalize_counts(item.get("occurrences_retained_by_split", {})) == normalize_counts(retained_counts),
         "declared_split_counts": normalize_counts(item.get("declared_original_occurrences_by_split", {})) == normalize_counts(all_counts),
         "sample_ids": set(actual_ids) == all_sample_ids,
         "retained_sample_ids": "retained_sample_ids" in item and set(actual_retained) == all_sample_ids - quarantined_ids,
         "quarantine_ids": set(actual_quarantine) == quarantined_ids,
         "all_ids_accounted_separately": set(actual_retained) | set(actual_quarantine) == all_sample_ids,
         "quarantine_not_in_retained": not (set(actual_retained) & set(actual_quarantine)),
         "ids_not_duplicated": all(len(values) == len(set(values)) for values in (actual_ids, actual_retained, actual_quarantine)),
         "gates_closed": gates_clear(item), "no_sign_equivalence": item.get("sign_equivalence_certified") is False}
    return result_row(item.get("id", text), "expanded.gloss_index", c,
                      text=text, expected_all_by_split=normalize_counts(all_counts),
                      expected_retained_by_split=normalize_counts(retained_counts),
                      expected_retained_sample_ids=sorted(all_sample_ids - quarantined_ids),
                      expected_quarantined_sample_ids=sorted(quarantined_ids),
                      observed_sample_ids=actual_ids, observed_retained_sample_ids=actual_retained,
                      observed_quarantined_sample_ids=actual_quarantine)


def verify_expanded(reader, context):
    """Validate public table contracts against original source rows, not producer code."""
    checks, rows = [], []
    filenames = {"units": "units.jsonl", "gloss_index": "gloss-index.jsonl",
                 "source_evidence": "source-evidence.jsonl", "sentences": "sentences.jsonl",
                 "source_samples": "source-samples.jsonl", "actions": "actions.jsonl",
                 "written_characters": "written-characters.jsonl", "excluded_labels": "excluded-labels.jsonl",
                 "media_inventory": "media-inventory.jsonl"}
    tables = {name: reader.jsonl(filename) for name, filename in filenames.items()}
    indexes = {name: unique_index(data, "character" if name == "written_characters" else
                                  "sha256" if name == "media_inventory" else "id", name)
               for name, data in tables.items()}
    samples, ce, lexical, refined, captions, base = (
        context[key] for key in ("samples", "ce", "lexical", "refined", "captions", "base"))
    evidence = indexes["source_evidence"]
    expected_evidence = {**{"foundation:" + k: ("foundation", x) for k, x in base.items()},
                         **{"tutorial:" + k: ("tutorial", x) for k, x in lexical.items()},
                         **{"caption:" + k: ("caption", x) for k, x in captions.items()}}
    check_set(checks, "source_evidence_exact_955_ids", evidence, expected_evidence)
    for identity, (kind, original) in expected_evidence.items():
        item = evidence.get(identity, {})
        c = {"present": bool(item), "kind": item.get("kind") == kind, "closed_gates": gates_clear(item)}
        if kind == "foundation":
            fields = {k: original.get(k) for k in ("meaning", "do_not_equate", "source_lexical_ids", "source_caption_ids")}
        elif kind == "tutorial":
            fields = {k: original.get(k) for k in ("meaning", "source_id", "source_sha256", "source_video",
                      "source_intervals", "manual_form_note", "nonmanual_note", "do_not_equate", "evidence_status",
                      "word_motion_alignment_verified", "human_approved")}
            fields["source_unit_type"] = original["unit_type"]
            annotation = refined[identity.split(":", 1)[1]]
            for k in ("refined_unit_type", "classification_reason"):
                fields[k] = annotation[k]
            c["source_uncertainties_preserved"] = set(original.get("uncertainties", [])).issubset(set(item.get("uncertainties", [])))
        else:
            window = context["windows"][identity.split(":", 1)[1]]
            fields = {k: original.get(k) for k in ("source_sha256", "raw_text", "clean_text",
                                                  "lexicon_eligible", "visual_correction")}
            fields.update(source_id=window["source_id"], clip_sha256=window["local_video_sha256"],
                          local_video=window["local_video"],
                          source_window_seconds_nominal=window["source_window_seconds_nominal"],
                          classification_reason=original["reason"], meaning=None)
            c.update(audit_caption_classification(item, original, base))
        for key, value in fields.items():
            c[key] = key in item and item[key] == value
        rows.append(result_row(identity, "expanded.source_evidence", c,
                               expected_record=original, observed_record=item))

    # Typed exact means whitespace trim only; no punctuation stripping, NFKC or digit folding.
    expected_groups = defaultdict(set)
    base_ids = defaultdict(set)
    for identity, unit in base.items():
        key = (unit["text"].strip(), unit["unit_type"])
        expected_groups[key].add("foundation:" + identity)
        base_ids[key].add(identity)
    for identity, source in lexical.items():
        key = (source["canonical_text"].strip(), refined[identity]["refined_unit_type"])
        expected_groups[key].add("tutorial:" + identity)
    for identity, caption in captions.items():
        if caption["lexicon_eligible"]:
            kind, _, _ = caption_classification(caption, base)
            expected_groups[(caption["clean_text"].strip(), kind)].add("caption:" + identity)
    actual_groups = defaultdict(list)
    for unit in tables["units"]:
        actual_groups[(unit["text"].strip(), unit["unit_type"])].append(unit)
    technical_check(checks, "typed_exact_group_keys", set(actual_groups) == set(expected_groups),
                    missing=[list(k) for k in sorted(set(expected_groups) - set(actual_groups))],
                    unexpected=[list(k) for k in sorted(set(actual_groups) - set(expected_groups))])
    for key in sorted(set(expected_groups) | set(actual_groups)):
        units = actual_groups.get(key, [])
        expected_ids = expected_groups.get(key, set())
        unit = units[0] if units else {}
        ids = unit.get("source_evidence_ids", [])
        senses = unit.get("source_senses", [])
        sense_ids = [s["id"] for s in senses]
        c = {"one_unit_per_typed_key": len(units) == 1,
             "source_evidence_membership_exact": set(ids) == expected_ids and len(ids) == len(set(ids)),
             "source_senses_membership_exact": set(sense_ids) == expected_ids and len(sense_ids) == len(set(sense_ids)),
             "every_source_sense_exact": all(s == evidence.get(s["id"]) for s in senses),
             "base_ids_preserved": set(unit.get("base_foundation_ids", [])) == base_ids.get(key, set()),
             "base_primary_id_preserved": not base_ids.get(key) or unit.get("id") in base_ids[key],
             "no_gloss_character_namespace": key[1] not in {"dataset_gloss", "written_character_component"},
             "gates_closed": gates_clear(unit), "not_full_action_passed": unit.get("passed") is False,
             "no_complete_action_passes": unit.get("full_action_two_round_passes") == 0,
             "no_unknown_actions": all(x in context["actions"] for x in unit.get("action_ids", []))}
        # A merged retrieval group must not transfer one sense's actions to every other sense.
        for action_id in unit.get("action_ids", []):
            action = context["actions"].get(action_id, {})
            source_match = any(s.get("source_sha256") == action.get("source_sha256") for s in senses
                               if s.get("kind") in {"tutorial", "caption"})
            base_match = any(action_id in base[x].get("action_ids", []) for x in base_ids.get(key, set()))
            c["action_source_binding:" + action_id] = source_match or base_match
        expected_actions = {action_id for x in base_ids.get(key, set()) for action_id in base[x].get("action_ids", [])}
        for sense in senses:
            if sense.get("kind") == "caption":
                candidate_id = sense["id"].split(":", 1)[1]
                if candidate_id in context["actions"]:
                    expected_actions.add(candidate_id)
            elif sense.get("kind") == "tutorial":
                lexical_id = sense["id"].split(":", 1)[1]
                for candidate in samples.values():
                    if candidate.get("dataset_id") != "tutorial-basic-candidates":
                        continue
                    note = json.loads(candidate["raw"].get("Note") or "{}")
                    if (candidate["id"] in context["actions"] and lexical_id in note.get("lexical_ids", [])
                            and candidate.get("source_sha256") == sense.get("source_sha256")
                            and candidate["raw"]["Chinese Sentences"].strip() == key[0]):
                        expected_actions.add(candidate["id"])
        c["action_ids_exact_source_membership"] = set(unit.get("action_ids", [])) == expected_actions
        c["no_duplicate_action_membership"] = len(unit.get("action_ids", [])) == len(set(unit.get("action_ids", [])))
        rows.append(result_row(unit.get("id", repr(key)), "expanded.units", c,
                               typed_key=list(key), expected_source_evidence_ids=sorted(expected_ids),
                               observed_source_evidence_ids=ids,
                               expected_action_ids=sorted(expected_actions), observed_action_ids=unit.get("action_ids", [])))
    check_set(checks, "base_127_ids_preserved", [x for u in tables["units"] for x in u.get("base_foundation_ids", [])], base)
    technical_check(checks, "unique_base_memberships", sum(len(u.get("base_foundation_ids", [])) for u in tables["units"]) == len(base))

    for identity in sorted(set(samples) | set(indexes["source_samples"])):
        original, item = samples.get(identity), indexes["source_samples"].get(identity)
        rows.append(result_row(identity, "expanded.source_samples", {
            "original_sample_exact": original is not None and item == original},
            expected_record_sha256=record_hash(original), observed_record_sha256=record_hash(item)))
    check_set(checks, "sentences_exact_original_ce_ids", indexes["sentences"], ce)
    for identity, original in ce.items():
        item = indexes["sentences"].get(identity, {})
        sample = samples[identity]
        fields = {"chinese": original["raw"]["Chinese Sentences"], "raw_gloss": original["raw"]["Gloss"],
                  "gloss_sequence": original["gloss_sequence"], "source_split": original["source_split"],
                  "source_label": original["source_label"], "status": sample["status"],
                  "local_video": sample["local_video"], "media_sha256": sample["media_sha256"],
                  "word_spans": [], "whole_sequence_only_not_word_frame_alignment": True}
        c = {k: k in item and item[k] == v for k, v in fields.items()}
        c["gates_closed"] = gates_clear(item)
        rows.append(result_row(identity, "expanded.sentences", c,
                               disposition="quarantine" if identity in QUARANTINE else "retained"))

    counts_all, counts_retained = defaultdict(Counter), defaultdict(Counter)
    sample_ids, quarantine_ids = defaultdict(set), defaultdict(set)
    for identity, item in ce.items():
        for token in item["gloss_sequence"]:
            split = item["source_split"]
            counts_all[token][split] += 1
            sample_ids[token].add(identity)
            if identity in QUARANTINE:
                quarantine_ids[token].add(identity)
            else:
                counts_retained[token][split] += 1
    gloss_by_text = unique_index(tables["gloss_index"], "text", "gloss text")
    check_set(checks, "gloss_exact_original_labels", gloss_by_text, counts_all)
    for text in sorted(set(counts_all) | set(gloss_by_text)):
        item = gloss_by_text.get(text, {})
        rows.append(audit_gloss(item, text, counts_all[text], counts_retained[text], sample_ids[text], quarantine_ids[text]))
    check_set(checks, "gloss_ids_original_namespace", indexes["gloss_index"],
              {x["id"] for x in context["lexicon"] if x.get("in_ce_csl")})

    check_set(checks, "actions_283_exact_original_ids", indexes["actions"], context["actions"])
    for identity, original in context["actions"].items():
        item = indexes["actions"].get(identity, {})
        c = {"whole_original_action_exact": item == original, "gates_closed": gates_clear(item)}
        rounds = item.get("validation_rounds", [])
        c["two_technical_rounds_retained"] = len(rounds) == 2 and {r.get("round") for r in rounds} == {1, 2}
        for i, entry in enumerate(rounds, 1):
            c[f"round{i}.nine_dimensions"] = set(entry.get("checks", {})) == DIMENSIONS
            c[f"round{i}.not_passed"] = entry.get("result") != "passed"
            c[f"round{i}.not_all_dimensions_passed"] = not all(x == "pass" for x in entry.get("checks", {}).values())
            for field in ("source_sha256", "clip_sha256", "action_version_sha256", "annotation_sha256"):
                c[f"round{i}.{field}"] = field in entry and entry[field] == item.get(field)
        gate = item.get("training_gate", {})
        c["gate_no_full_passes"] = gate.get("training_allowed") is False and gate.get("independent_passes") == 0
        c["same_version_required"] = gate.get("same_version_required") is True and gate.get("any_revision_invalidates_rounds") is True
        rows.append(result_row(identity, "expanded.actions", c,
                               observed_action_version_sha256=item.get("action_version_sha256"),
                               observed_validation_rounds=rounds, observed_training_gate=gate))

    expected_characters = set(context["characters"])
    actual_characters = set(indexes["written_characters"])
    check_set(checks, "written_character_coverage", actual_characters, expected_characters)
    for character, item in indexes["written_characters"].items():
        rows.append(result_row(character, "expanded.written_characters", {
            "original_written_record_exact": item == context["characters"].get(character),
            "written_only": item.get("kind") == "written_character_component",
            "no_inferred_sign": item.get("independent_sign_action_inferred") is False,
            "no_action_mapping": not any(item.get(k) for k in ("action_ids", "motion_id", "action_id", "source_senses")),
            "gates_closed": gates_clear(item)}))
    excluded = {"caption:" + x["id"] for x in captions.values() if not x["lexicon_eligible"]}
    check_set(checks, "excluded_21_preserved", indexes["excluded_labels"], excluded)
    member_ids = {sid for unit in tables["units"] for sid in unit.get("source_evidence_ids", [])}
    technical_check(checks, "excluded_21_never_in_units", not (excluded & member_ids),
                    leaked_ids=sorted(excluded & member_ids))
    for name, expected in (("actions", EXPECTED["actions"]), ("gloss_index", EXPECTED["gloss"]),
                           ("written_characters", EXPECTED["characters"]), ("source_samples", EXPECTED["samples"]),
                           ("sentences", EXPECTED["ce"]), ("source_evidence", 955)):
        technical_check(checks, "expanded_count:" + name, len(tables[name]) == expected,
                        expected=expected, observed=len(tables[name]))

    # Bind the expanded provenance and copied snapshots to the actual frozen metadata.
    input_hashes = reader.json("provenance/input-hashes.json")
    for source_reader in context["source_readers"]:
        for name in ("SHA256SUMS", "samples.jsonl", "tutorial/lexical-evidence.jsonl", "lexicon.jsonl",
                     "foundation-units.jsonl", "refined-tutorial.jsonl", "refined-captions.jsonl",
                     "action-checks.jsonl", "characters.jsonl", "media-inventory.jsonl", "duplicates-and-conflicts.json"):
            source_path = source_reader.root / name
            if not source_path.is_file():
                continue
            checksum = digest(source_reader.read(name))
            declared = input_hashes.get(str(source_path))
            technical_check(checks, "expanded_original_sha_binding:" + source_reader.name + ":" + name,
                            declared == checksum, observed=declared, expected=checksum)
            snapshot = f"source-snapshots/{checksum[:16]}-{source_path.name}"
            technical_check(checks, "expanded_source_snapshot:" + source_reader.name + ":" + name,
                            digest(reader.read(snapshot)) == checksum)
    check_set(checks, "media_inventory_original_records", indexes["media_inventory"],
              context["media_inventory"])
    technical_check(checks, "media_inventory_payloads_exact",
                    indexes["media_inventory"] == context["media_inventory"])

    # Use only SELECTs through a read-only connection; compare each full decoded payload.
    database = reader.path("database.sqlite")
    before = database.stat()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as sql:
        sql.execute("PRAGMA query_only=ON")
        integrity = sql.execute("PRAGMA integrity_check").fetchall()
        technical_check(checks, "sqlite_integrity", integrity == [("ok",)], observed=integrity)
        names = {x[0] for x in sql.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        check_set(checks, "sqlite_table_set", names, filenames)
        for name in filenames:
            if name not in names:
                continue
            sql_rows = sql.execute(f'SELECT id, payload FROM "{name}"').fetchall()
            expected = indexes[name]
            check_set(checks, "sqlite_ids:" + name, [x[0] for x in sql_rows], expected)
            for identity, payload in sql_rows:
                actual = json.loads(payload)
                if actual != expected.get(identity):
                    rows.append(result_row(identity, "expanded.sqlite." + name,
                                           {"payload_exact": False}, observed_record=actual,
                                           expected_record=expected.get(identity)))
            technical_check(checks, "sqlite_payloads:" + name,
                            all(json.loads(payload) == expected.get(identity) for identity, payload in sql_rows),
                            rows_compared=len(sql_rows))
    after = database.stat()
    technical_check(checks, "sqlite_unchanged_during_read", (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
    # The SQLite metadata hash is bounded; no media are read to calculate this digest.
    sql_digest = digest(database.read_bytes())
    reader.inputs.append({"root": reader.name, "path": str(database), "relative_path": "database.sqlite",
                          "bytes": after.st_size, "sha256": sql_digest,
                          "frozen_manifest_sha256": reader.manifest.get("database.sqlite"),
                          "manifest_status": "absent" if not reader.manifest.get("database.sqlite") else
                          "pass" if reader.manifest["database.sqlite"] == sql_digest else "fail"})
    return rows, checks, {name: len(data) for name, data in tables.items()}


def prepare_output(output, sources):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a NEW output directory: " + str(output))
    resolved = output.resolve()
    for source in sources:
        source = Path(source).resolve()
        if resolved.is_relative_to(source) or source.is_relative_to(resolved):
            raise ValueError("Keep audit output separate from all input libraries")
    output.mkdir(parents=True, exist_ok=False)
    return output


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(compact(row) + "\n")


def run(database, foundation, output, expanded=None):
    db = MetadataReader(database, "reference")
    base_reader = MetadataReader(foundation, "foundation")
    expanded_reader = MetadataReader(expanded, "expanded", require_manifest=False) if expanded else None
    samples_list = db.jsonl("samples.jsonl")
    samples = unique_index(samples_list, "id", "samples")
    source_rows = [row for split in SPLITS for row in csv_records(
        db, f"provenance/original-ce-csl/label/{split}.csv", split)]
    ce = unique_index(source_rows, "id", "original CE")
    lexical_list = db.jsonl("tutorial/lexical-evidence.jsonl")
    lexical = unique_index(lexical_list, "id", "lexical")
    refined_list = base_reader.jsonl("refined-tutorial.jsonl")
    refined = unique_index(refined_list, "original_lexical_id", "refined tutorial")
    annotations = unique_index(base_reader.json("source-annotations/tutorial-refinement-main-v2.json")["annotations"],
                               "original_lexical_id", "tutorial annotation snapshot")
    captions_list = base_reader.jsonl("refined-captions.jsonl")
    captions = unique_index(captions_list, "id", "captions")
    windows = unique_index(db.jsonl("additional-candidates/windows.jsonl"), "id", "caption windows")
    corrections = unique_index(base_reader.json("source-annotations/caption-visual-corrections.json")["records"],
                               "candidate_id", "caption correction")
    tutorial_sources = unique_index(db.jsonl("tutorial/original-source-aliases.jsonl"), "source_id", "tutorial source")
    extra_sources = unique_index(db.jsonl("additional-sources/source-map.jsonl"), "id", "additional source")
    base_list = base_reader.jsonl("foundation-units.jsonl")
    base = unique_index(base_list, "id", "base foundation")
    targets = base_reader.json("source-annotations/foundation-targets-v2.json")["records"]
    target_map = unique_index(targets, "text", "base target")
    actions_list = base_reader.jsonl("action-checks.jsonl")
    actions = unique_index(actions_list, "id", "original action")
    lexicon = db.jsonl("lexicon.jsonl")
    characters = unique_index(base_reader.jsonl("characters.jsonl"), "character", "original written character")
    media_inventory = unique_index(db.jsonl("media-inventory.jsonl"), "sha256", "original media inventory")
    checks = []
    for key, count in (("samples", len(samples)), ("ce", len(ce)), ("tutorial", len(lexical)),
                       ("captions", len(captions)), ("foundation", len(base)), ("actions", len(actions)),
                       ("excluded", sum(not x["lexicon_eligible"] for x in captions_list))):
        technical_check(checks, "source_count:" + key, count == EXPECTED[key], expected=EXPECTED[key], observed=count)
    check_set(checks, "original_ce_to_samples", [x["id"] for x in samples_list if x["dataset_id"] == "CE-CSL"], ce)
    check_set(checks, "tutorial_refinements_exact_ids", refined, lexical)
    check_set(checks, "tutorial_annotation_snapshot_exact_ids", annotations, lexical)
    check_set(checks, "caption_refinements_exact_ids", captions, windows)
    check_set(checks, "foundation_targets_exact_texts", [x["text"] for x in base_list], target_map)

    sample_audit = [audit_ce(samples.get(identity), origin) for identity, origin in ce.items()]
    sample_audit.extend(audit_ce(x, None) for x in samples_list if x["dataset_id"] == "CE-CSL" and x["id"] not in ce)
    csv_by_dataset = {}
    for family, names in (
        ("tutorial-basic-candidates", ["candidates/label/candidates.csv"]),
        ("additional-caption-candidates", ["additional-candidates/label/extra-folder-1.csv", "additional-candidates/label/extra-folder-2-shouyu.csv"]),
        ("additional-course-sources", ["additional-sources/label/extra-folder-1.csv", "additional-sources/label/extra-folder-2-shouyu.csv"]),
    ):
        data = [x for name in names for x in csv_records(db, name)]
        raw_index = unique_index([x["raw"] for x in data], "Number", family + " CSV")
        csv_by_dataset[family] = {x["raw"]["Number"]: x for x in data}
        check_set(checks, "non_ce_csv_coverage:" + family,
                  [x["raw"]["Number"] for x in samples_list if x["dataset_id"] == family], raw_index)
    for sample in samples_list:
        family = sample["dataset_id"]
        if family == "CE-CSL":
            continue
        original = csv_by_dataset.get(family, {}).get(sample["raw"]["Number"], {})
        source = (tutorial_sources if family == "tutorial-basic-candidates" else extra_sources).get(sample.get("source_id"), {})
        c = {"original_csv_row_present": bool(original), "raw_csv_exact": sample.get("raw") == original.get("raw"),
             "source_present": bool(source), "source_digest_metadata": sample.get("source_sha256") == source.get("sha256"),
             "gates_closed": gates_clear(sample)}
        sample_audit.append(result_row(sample["id"], family, c, original_label_row=original,
                                       sample_record_sha256=record_hash(sample),
                                       preserved_unknowns={k: sample.get(k) for k in ("mirror_status", "signer_id", "word_spans")}))

    # Independently check retained/quarantined exports against original rows.
    for split in SPLITS:
        exported = csv_records(db, f"ce-csl/label/{split}.csv")
        actual = unique_index([x["raw"] for x in exported], "Number", "retained export")
        expected = {x["raw"]["Number"]: x["raw"] for x in source_rows if x["source_split"] == split and x["id"] not in QUARANTINE}
        technical_check(checks, "retained_csv_exact:" + split, actual == expected,
                        observed=len(actual), expected=len(expected))
    quarantined = {x["raw"]["Number"]: x["raw"] for x in csv_records(db, "quarantine/ce-csl/label/quarantined.csv")}
    technical_check(checks, "quarantine_original_rows_exact", quarantined == {
        x["raw"]["Number"]: x["raw"] for x in source_rows if x["id"] in QUARANTINE})
    media_groups = defaultdict(list)
    for sample in samples_list:
        if sample.get("media_sha256"):
            media_groups[sample["media_sha256"]].append(sample)
    risks = classification_risks(lexical_list, refined_list, captions_list)
    for checksum, group in media_groups.items():
        if len({compact(x["raw"]) for x in group}) > 1:
            risks.append({"kind": "same_media_different_raw_labels", "media_sha256_from_metadata": checksum,
                          "record_ids": [x["id"] for x in group],
                          "evidence": [{"id": x["id"], "raw": x["raw"], "status": x["status"]} for x in group],
                          "suggested_repair": "保留冲突双方；来源标签核实前继续隔离，不投票选标签。",
                          "auto_merge_allowed": False, "training_ready": False})
    tutorial_audit = [audit_tutorial(refined.get(identity), source, annotations.get(identity)) for identity, source in lexical.items()]
    for row in tutorial_audit:
        source = row["original_lexical"]
        binding = tutorial_sources.get(source.get("source_id"), {})
        row["checks"]["original_source_alias_binding"] = binding.get("sha256") == source.get("source_sha256") and source.get("source_video") in binding.get("aliases", [])
        if not row["checks"]["original_source_alias_binding"]:
            row["source_status"] = "fail"
            row["differences"].append("original_source_alias_binding")
    caption_audit = [audit_caption(captions.get(identity), window, samples.get(identity), corrections.get(identity),
                                    extra_sources.get(window["source_id"])) for identity, window in windows.items()]
    foundation_audit = [audit_foundation(unit, target_map.get(unit["text"]), lexical, captions) for unit in base_list]
    context = dict(samples=samples, ce=ce, lexical=lexical, refined=refined, captions=captions,
                   base=base, actions=actions, lexicon=lexicon, windows=windows,
                   characters=characters, media_inventory=media_inventory, source_readers=[db, base_reader])
    expanded_audit, expanded_checks, expanded_counts = [], [], None
    if expanded_reader:
        expanded_audit, expanded_checks, expanded_counts = verify_expanded(expanded_reader, context)
        checks.extend(expanded_checks)
    readers = [db, base_reader] + ([expanded_reader] if expanded_reader else [])
    inputs = [item for reader in readers for item in reader.inputs]
    for item in inputs:
        technical_check(checks, "frozen_metadata:" + item["root"] + ":" + item["relative_path"],
                        item["manifest_status"] in {"pass", "self_digest_only"} or
                        (item["root"] == "expanded" and item["manifest_status"] == "absent"),
                        observed=item["manifest_status"],
                        interpretation="this_audit_snapshot_only" if item["manifest_status"] == "absent" else "frozen_manifest")
    for reader in readers:
        reader.assert_unchanged()
    all_rows = sample_audit + tutorial_audit + caption_audit + foundation_audit + expanded_audit
    failures = [x for x in all_rows if x["source_status"] == "fail"]
    failed_checks = [x for x in checks if x["status"] == "fail"]
    report = {"schema": SCHEMA, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_status": "fail" if failures or failed_checks else "pass",
              "annotation_status": "unknown", "full_action_pass": False,
              "training_ready": False, "model_training_ready": False,
              "human_reviewed_this_audit": False, "video_viewed_this_audit": False,
              "media_payloads_opened_or_rehashed": 0, "training_started": False,
              "technical_rounds_are_complete_action_passes": False,
              "input_roots": {x.name: str(x.root) for x in readers},
              "counts": {"sample_audit": len(sample_audit), "original_ce_rows": len(ce),
                         "original_ce_by_split": dict(Counter(x["source_split"] for x in source_rows)),
                         "ce_quarantined_ids": sorted(QUARANTINE),
                         "tutorial_audit": len(tutorial_audit), "caption_audit": len(caption_audit),
                         "foundation_audit": len(foundation_audit),
                         "caption_excluded": sum(x["excluded_from_lexicon"] for x in caption_audit),
                         "expanded": expanded_counts,
                         "record_failures": len(failures), "global_failures": len(failed_checks),
                         "risk_kinds": dict(Counter(x["kind"] for x in risks)),
                         "source_status_by_scope": {scope: dict(Counter(x["source_status"] for x in all_rows if x["scope"] == scope))
                                                    for scope in sorted({x["scope"] for x in all_rows})}},
              "failed_checks": failed_checks,
              "failed_records": [{"id": x["id"], "scope": x["scope"], "differences": x["differences"]} for x in failures],
              "tool_sha256": digest(Path(__file__).read_bytes()),
              "limits": ["仅回读并比对来源文字、标注和技术门禁；未观看视频或执行人工审核。",
                         "媒体哈希仅引用冻结元数据，未打开媒体；媒体字节复验由独立 worker 承担。",
                         "source pass 不认证词义、镜像、手别、词界、词动作对齐或完整动作正确。",
                         "原状态 unresolved/unknown 原样保留；本次审核永不签发完整动作通过或训练许可。"]}
    out = prepare_output(output, [x.root for x in readers])
    for filename, data in (("sample-audit.jsonl", sample_audit), ("tutorial-audit.jsonl", tutorial_audit),
                           ("caption-audit.jsonl", caption_audit), ("foundation-audit.jsonl", foundation_audit),
                           ("expanded-audit.jsonl", expanded_audit), ("risk-audit.jsonl", risks),
                           ("checks.jsonl", checks), ("inputs.jsonl", inputs)):
        write_jsonl(out / filename, data)
    (out / "foundation-targets.snapshot.json").write_bytes(base_reader.read("source-annotations/foundation-targets-v2.json"))
    (out / "foundation-units.snapshot.jsonl").write_bytes(base_reader.read("foundation-units.jsonl"))
    write_json(out / "report.json", report)
    write_json(out / "schema.json", {
        "schema": SCHEMA, "record_files": ["sample-audit.jsonl", "tutorial-audit.jsonl", "caption-audit.jsonl", "foundation-audit.jsonl", "expanded-audit.jsonl"],
        "source_status": {"pass": "technical source/metadata consistency only", "fail": "one or more concrete differences"},
        "checks": "Boolean per field; differences lists all false checks",
        "annotation_status": "unknown or source unresolved; never inferred pass",
        "csv_record_sha256": "SHA256(UTF8(JSON of raw fields in CSV header order, ensure_ascii=False, separators=(',',':'), no trailing newline))",
        "object_record_sha256": "SHA256(UTF8(JSON sorted keys, compact separators, no trailing newline))",
        "typed_exact_key": "(text.strip(), unit_type); eligible captions inherit a unique base type only for same caption ID + exact trimmed text, otherwise word_candidate maps to word",
        "always_false": ["full_action_pass", "training_ready", "model_training_ready", "human_reviewed_this_audit", "video_viewed_this_audit"],
        "command": "python3 sign-csl-expanded-source-verify.py --database REFERENCE --foundation FOUNDATION --output NEW_DIRECTORY [--expanded EXPANDED]",
        "exit_codes": {"0": "technical checks pass", "1": "differences recorded", "2": "input or command error"}})
    text = ["# 独立来源与标注复核", "", f"技术来源状态：{report['source_status']}；记录差异 {len(failures)}，全局差异 {len(failed_checks)}。", "",
            f"回读原始 CE CSV {len(ce)} 行，审核全样本 {len(sample_audit)}、教程 {len(tutorial_audit)}、caption {len(caption_audit)}、基础目标 {len(foundation_audit)}。",
            "03571/03572 保留原行并必须隔离；字幕排除项逐条保留。", "",
            "逐条记录见 sample/tutorial/caption/foundation/expanded-audit.jsonl；具体风险见 risk-audit.jsonl；全局差异见 report.json。", "",
            *report["limits"], "", "原始基础目标和基础词条以字节一致快照保留；输入 SHA256 见 inputs.jsonl。", "",
            "## CLI 与恢复", "", "运行 --help 查看参数；输出必须为新目录。原库均以只读方式访问，恢复无需更改原库；如需丢弃此次产物，仅删除本审核输出目录。", ""]
    (out / "report.md").write_text("\n".join(text), encoding="utf-8")
    (out / "SHA256SUMS").write_text("".join(f"{digest(p.read_bytes())}  {p.name}\n" for p in sorted(out.iterdir()) if p.is_file()), encoding="utf-8")
    # Re-open every delivered JSON/JSONL file and its manifest before reporting completion.
    for p in out.iterdir():
        if p.suffix == ".json":
            json.loads(p.read_bytes())
        elif p.suffix == ".jsonl":
            for line in p.read_text(encoding="utf-8").splitlines():
                json.loads(line)
    for line in (out / "SHA256SUMS").read_text().splitlines():
        checksum, relative = line.split("  ", 1)
        if digest((out / relative).read_bytes()) != checksum:
            raise ValueError("Output verification failed: " + relative)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Frozen reference database directory")
    parser.add_argument("--foundation", required=True, type=Path, help="Frozen base foundation v4 directory")
    parser.add_argument("--output", required=True, type=Path, help="New source audit directory")
    parser.add_argument("--expanded", type=Path, help="Optional completed expanded database; JSONL and SQLite checked independently")
    args = parser.parse_args()
    try:
        report = run(args.database, args.foundation, args.output, args.expanded)
    except (OSError, ValueError, KeyError, sqlite3.Error, csv.Error) as error:
        print(compact({"status": "error", "type": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2
    print(compact({"source_status": report["source_status"], "counts": report["counts"],
                   "output": str(args.output.resolve()), "full_action_pass": False, "training_ready": False}))
    return 0 if report["source_status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
