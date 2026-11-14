"""Create a hash-bound, review-only index of CSL tutorial word evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args):
    source = args.source.resolve(); output = args.output.resolve()
    if output.exists(): raise ValueError("Use a new evidence output directory")
    output.mkdir(parents=True)
    rows = [json.loads(line) for line in (source / "fitting-reference-index.jsonl").read_text().splitlines() if line.strip()]
    selected = []
    for row in rows:
        selected.append({
            "annotation_id": row["annotation_id"], "label": row["label"], "category": row.get("category"),
            "sample_type": row.get("sample_type"), "hand_shape_note": row.get("hand_shape_note", ""),
            "source_window_seconds": row.get("source_window_seconds"), "source_sha256": row["source_sha256"],
            "clip": row["artifacts"]["clip.mp4"], "overlay": row["artifacts"].get("overlay.mp4"),
            "keyframes": row["artifacts"].get("keyframes.jpg"), "observation": row["artifacts"].get("landmarks.npz"),
            "usable_hand_observation_frames": row.get("usable_hand_observation_frames"),
            "anatomical_handedness": row.get("anatomical_handedness"), "mirror_status": row.get("mirror_status"),
            "human_approved": row.get("human_approved", False), "training_ready": row.get("training_ready", False),
            "semantic_evidence_status": "assistant_candidate_only",
            "limitations": ["Tutorial instruction/sample labels are not universal CSL truth.",
                            "No word-level onset/offset or human semantic approval is inferred.",
                            "2D observations and static references do not establish a complete 3D motion asset."],
        })
    target_labels = {"去", "来", "今天", "昨天", "明天"}
    focus = [row for row in selected if row["label"] in target_labels]
    report = {"schema": "signbridge-csl-semantic-evidence-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "source_index": str(source / "fitting-reference-index.jsonl"), "source_index_sha256": sha(source / "fitting-reference-index.jsonl"),
              "cases": selected, "focus_cases": focus,
              "target_language": "CSL", "human_approved": False, "training_ready": False,
              "model_training_ready": False, "training_started": False,
              "interpretation": "assistant candidate evidence for bounded semantic prototype; not a translation lexicon or training approval."}
    (output / "semantic-evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "REVIEW.md").write_text("# 中国手语语义原型词级证据\n\n" +
      "本索引只收录既有教学视频的词级/步骤说明候选。它不确认中国手语统一语序、手型、镜像、解剖侧别或句子边界。\n\n" +
      "## 重点候选\n\n" + "\n".join(f"- {x['label']}：{x['annotation_id']}，来源窗口 {x['source_window_seconds']}，状态 assistant_candidate_only" for x in focus) +
      "\n\n完整字段见 semantic-evidence.json。没有新增训练或人工批准。\n")
    manifest = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS": manifest.append(sha(path) + "  " + str(path.relative_to(output)))
    (output / "SHA256SUMS").write_text("\n".join(manifest) + "\n")
    print(json.dumps({"cases": len(selected), "focus_cases": len(focus), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
