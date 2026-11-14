"""Audit and package local review evidence for continuous SMPLer-X candidates."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
SHAPES = {
    "global_orient": (1, 3),
    "body_pose": (21, 3),
    "left_hand_pose": (15, 3),
    "right_hand_pose": (15, 3),
    "jaw_pose": (1, 3),
    "leye_pose": (1, 3),
    "reye_pose": (1, 3),
    "betas": (1, 10),
    "expression": (1, 10),
    "transl": (1, 3),
}
NATIVE_SHAPES = SHAPES


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sequence = load_tool("sign-source-catchup-smplx.py", "candidate_fit_sequence")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contained(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    path = (root / relative).resolve()
    if relative.is_absolute() or root not in path.parents or not path.is_file():
        raise ValueError("Artifact path escapes or is missing: " + str(relative))
    return path


def verify_checksums(root):
    root = Path(root).resolve()
    checksum_file = root / "SHA256SUMS"
    if not checksum_file.is_file():
        raise ValueError("Missing result checksum manifest")
    records = {}
    for line in checksum_file.read_text().splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise ValueError("Invalid checksum manifest entry")
        digest, relative = parts
        if relative in records:
            raise ValueError("Duplicate checksum manifest path: " + relative)
        try:
            path = contained(root, relative)
        except ValueError as error:
            raise ValueError("Unsafe checksum manifest path: " + relative) from error
        if sha(path) != digest:
            raise ValueError("Result checksum mismatch: " + relative)
        records[relative] = digest
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path != checksum_file
    }
    if set(records) != actual:
        raise ValueError("Checksum manifest coverage differs from result files")
    return len(records)


def native_inventory(folder, expected_frames):
    folder = Path(folder)
    persons = {}
    for path in folder.glob("*.npz"):
        match = re.fullmatch(r"(\d{5})_(\d+)\.npz", path.name)
        if not match:
            raise ValueError("Invalid native parameter filename: " + path.name)
        frame, person = int(match.group(1)), int(match.group(2))
        if not 1 <= frame <= expected_frames:
            raise ValueError("Native parameter frame outside expected frame range: " + path.name)
        try:
            with np.load(path, allow_pickle=False) as values:
                for field, shape in SHAPES.items():
                    if field not in values.files:
                        raise ValueError("Missing native parameter " + field)
                    value = values[field]
                    if value.shape != shape or value.dtype.kind != "f" or not np.isfinite(value).all():
                        raise ValueError("Invalid native parameter shape/dtype/value: " + field)
        except (OSError, ValueError) as error:
            raise ValueError("Invalid native parameter file " + path.name + ": " + str(error)) from error
        persons.setdefault(frame, []).append(person)
    missing = sorted(set(range(1, expected_frames + 1)) - set(persons))
    multiple = sorted(frame for frame, tracks in persons.items() if len(tracks) > 1)
    return {
        "parameter_files": sum(map(len, persons.values())),
        "fitted_frames": len(persons),
        "missing_frames": missing,
        "multiple_person_frames": multiple,
        "nonzero_person_ids": sorted({person for tracks in persons.values() for person in tracks if person != 0}),
        "complete_single_person": (
            not missing
            and not multiple
            and all(tracks == [0] for tracks in persons.values())
        ),
    }


def validate_frame_map(rows, case):
    frames = case["frames"]
    fps = float(case["fps"])
    start = float(case["start_seconds"])
    if len(rows) != frames:
        raise ValueError("Candidate frame map count differs")
    for number, row in enumerate(rows, 1):
        expected_clip = (number - 1) / fps
        expected_source = start + expected_clip
        if (
            row.get("frame_1based") != number
            or row.get("interpolated") is not False
            or not np.isclose(row.get("clip_seconds", float("nan")), expected_clip, rtol=0, atol=1e-7)
            or not np.isclose(row.get("source_seconds_nominal", float("nan")), expected_source, rtol=0, atol=1e-7)
        ):
            raise ValueError("Candidate frame map differs at frame " + str(number))


def validate_metadata(info, remote_output_root, sid, frame, person):
    expected = Path(remote_output_root) / "input-frames" / sid / f"{frame:06d}.jpg"
    if Path(info.get("img_path", "")) != expected or info.get("bbox_id") != person:
        raise ValueError("Parameter metadata input path/frame/person differs")


def _percentiles(values):
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return {"p50": None, "p95": None, "maximum": None}
    return {
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "maximum": float(np.max(values)),
    }


def _rotation_matrices(poses):
    values = np.asarray(poses, dtype=np.float64)
    if values.ndim < 2 or values.shape[-1] != 3 or not np.isfinite(values).all():
        raise ValueError("Rotation poses must be finite axis-angle triples")
    return np.asarray([cv2.Rodrigues(value)[0] for value in values.reshape(-1, 3)]).reshape(
        *values.shape[:-1], 3, 3
    )


def rotation_metrics(poses, frame_numbers=None):
    rotations = _rotation_matrices(poses)
    if rotations.ndim == 3:
        rotations = rotations[:, None, :, :]
    if rotations.ndim != 4:
        raise ValueError("Rotations must have frame and joint axes")
    numbers = np.arange(len(rotations)) if frame_numbers is None else np.asarray(frame_numbers)
    if numbers.shape != (len(rotations),):
        raise ValueError("Rotation frame numbers do not match poses")
    adjacent, residual, large_frame_transitions = [], [], 0
    for index in range(len(rotations) - 1):
        if numbers[index + 1] != numbers[index] + 1:
            continue
        relative = rotations[index + 1] @ rotations[index].swapaxes(-1, -2)
        cosine = np.clip((np.trace(relative, axis1=-2, axis2=-1) - 1) / 2, -1, 1)
        angles = np.degrees(np.arccos(cosine))
        adjacent.extend(angles.tolist())
        large_frame_transitions += int(np.any(angles > 90))
    for index in range(1, len(rotations) - 1):
        if numbers[index] != numbers[index - 1] + 1 or numbers[index + 1] != numbers[index] + 1:
            continue
        relative = rotations[index - 1].swapaxes(-1, -2) @ rotations[index + 1]
        vectors = np.asarray([cv2.Rodrigues(value)[0].reshape(3) for value in relative])
        midpoint = np.einsum(
            "jab,jbc->jac",
            rotations[index - 1],
            np.asarray([cv2.Rodrigues(value * 0.5)[0] for value in vectors]),
        )
        error = midpoint.swapaxes(-1, -2) @ rotations[index]
        cosine = np.clip((np.trace(error, axis1=-2, axis2=-1) - 1) / 2, -1, 1)
        residual.extend(np.degrees(np.arccos(cosine)).tolist())
    adjacent = np.asarray(adjacent, dtype=np.float64)
    return {
        "adjacent_degrees": _percentiles(adjacent),
        "frame_transitions_over_90_degrees": large_frame_transitions,
        "geodesic_midpoint_residual_degrees": _percentiles(residual),
        "interpolated_or_smoothed": False,
    }


def probe_clip(path, ffprobe):
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
    return {"frames": int(stream["nb_read_frames"]), "fps": numerator / denominator}


def check_jpegs(folder, frames):
    folder = Path(folder)
    expected = {f"{i:06d}.jpg" for i in range(1, frames + 1)}
    actual = {path.name for path in folder.glob("*.jpg")}
    if actual != expected:
        raise ValueError("Input/render JPEG frame set differs: " + str(folder))
    for path in sorted(folder.glob("*.jpg")):
        if cv2.imread(str(path)) is None:
            raise ValueError("Undecodable input/render JPEG: " + str(path))


def case_metrics(fit, frames, inventory):
    fitted_frames = sorted(
        frame
        for frame in range(1, frames + 1)
        if (Path(fit) / "smplx" / f"{frame:05d}_0.npz").is_file()
    )
    parameters = [
        sequence.motion.native_parameters(Path(fit) / "smplx" / f"{frame:05d}_0.npz")
        for frame in fitted_frames
    ]
    metrics = {}
    for name in (
        "smplx_root_pose",
        "smplx_body_pose",
        "smplx_lhand_pose",
        "smplx_rhand_pose",
        "smplx_jaw_pose",
    ):
        poses = (
            np.stack([row[name] for row in parameters]).reshape(len(parameters), -1, 3)
            if parameters
            else np.empty((0, 1, 3))
        )
        metrics[name] = rotation_metrics(poses, fitted_frames)
    translations = np.stack([row["transl"] for row in parameters]) if parameters else np.empty((0, 3))
    steps = [
        np.linalg.norm(translations[index + 1] - translations[index])
        for index in range(len(fitted_frames) - 1)
        if fitted_frames[index + 1] == fitted_frames[index] + 1
    ]
    metrics["translation_adjacent_distance_model_units"] = _percentiles(steps)
    metrics["missing_detection_frames"] = inventory["missing_frames"]
    metrics["multiple_person_frames"] = inventory["multiple_person_frames"]
    metrics["incomplete_or_ambiguous"] = not inventory["complete_single_person"]
    return metrics


def contact_sheet(case, input_dir, render_dir, path):
    font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font = ImageFont.truetype(str(font_path), 18) if font_path.is_file() else ImageFont.load_default()
    selected = sorted(set(np.linspace(1, case["frames"], min(8, case["frames"]), dtype=int).tolist()))
    sheet = Image.new("RGB", (840, len(selected) * 345 + 68), "#111827")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), case["label_candidate"] + " | 动作质量未审批", font=font, fill="white")
    for index, number in enumerate(selected):
        for column, folder in enumerate((input_dir, render_dir)):
            source = Path(folder) / f"{number:06d}.jpg"
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((408, 310))
                sheet.paste(image, (column * 420 + (420 - image.width) // 2, 48 + index * 345))
            draw.text(
                (column * 420 + 8, 48 + index * 345 + 313),
                ("原视频" if column == 0 else "SMPL-X 网格") + f" | 帧 {number}",
                font=font,
                fill="white",
            )
    sheet.save(path, quality=90)


def comparison_video(case, input_dir, render_dir, output, ffmpeg):
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-framerate",
        str(case["fps"]),
        "-start_number",
        "1",
        "-i",
        str(Path(input_dir) / "%06d.jpg"),
        "-framerate",
        str(case["fps"]),
        "-start_number",
        "1",
        "-i",
        str(Path(render_dir) / "%06d.jpg"),
        "-filter_complex",
        "[0:v]scale=480:-2[a];[1:v]scale=480:-2[b];[a][b]hstack=inputs=2[v]",
        "-map",
        "[v]",
        "-frames:v",
        str(case["frames"]),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(command, check=True, timeout=max(120, case["frames"] * 2))
    result = probe_clip(output, Path(shutil.which("ffprobe")))
    if result["frames"] != case["frames"]:
        raise ValueError("Comparison video frame count differs: " + case["annotation_id"])


def audit_case(case, source_record, run, result_root, attempt, ffprobe, ffmpeg, output):
    sid, frames = case["annotation_id"], case["frames"]
    run_root = Path(result_root)
    input_dir = run_root / "input-frames" / sid
    fit = run_root / "fits" / sid
    for folder in (input_dir, fit / "smplx", fit / "meta", fit / "img"):
        if not folder.is_dir():
            raise ValueError("Missing sequence artifact directory: " + str(folder))
    source = probe_clip(Path(attempt["package_root"]) / case["clip"], ffprobe)
    if source["frames"] != frames or abs(source["fps"] - case["fps"]) > 0.01:
        raise ValueError("Candidate clip frame count/FPS differs: " + sid)
    validate_frame_map(
        [json.loads(line) for line in (Path(attempt["package_root"]) / "clips" / sid / "frames.jsonl").read_text().splitlines() if line.strip()],
        case,
    )
    check_jpegs(input_dir, frames)
    check_jpegs(fit / "img", frames)
    inventory = native_inventory(fit / "smplx", frames)
    record = {row["annotation_id"]: row for row in run["candidate_records"]}.get(sid)
    if record is None:
        raise ValueError("Run report is missing candidate: " + sid)
    log = run_root / "logs" / (sid + ".log")
    if not log.is_file() or sha(log) != record["log_sha256"]:
        raise ValueError("Candidate inference log checksum differs: " + sid)
    parameters = sorted((fit / "smplx").glob("*.npz"))
    metadata_files = sorted((fit / "meta").glob("*.json"))
    expected_metadata = {path.stem + ".json" for path in parameters}
    if {path.name for path in metadata_files} != expected_metadata:
        raise ValueError("Native parameter and metadata frame/person sets differ: " + sid)
    for parameter in parameters:
        info = json.loads((fit / "meta" / (parameter.stem + ".json")).read_text())
        frame_match = re.fullmatch(r"(\d{5})_(\d+)", parameter.stem)
        if frame_match is None:
            raise ValueError("Parameter metadata does not map to its input frame: " + parameter.name)
        validate_metadata(info, attempt["remote_output_root"], sid, int(frame_match.group(1)), int(frame_match.group(2)))
    missing = inventory["missing_frames"]
    if record["smplx_missing_detection_frames"] != missing:
        raise ValueError("Reported missing detections differ from native parameter inventory: " + sid)
    if record["smplx_parameter_files"] != len(parameters) or record["render_frames"] != frames:
        raise ValueError("Run report parameter/render counts differ from output files: " + sid)
    metrics = case_metrics(fit, frames, inventory)
    contact = output / (sid + "-contact.jpg")
    video = output / (sid + "-comparison.mp4")
    contact_sheet(case, input_dir, fit / "img", contact)
    comparison_video(case, input_dir, fit / "img", video, ffmpeg)
    return {
        "annotation_id": sid,
        "source_id": case["source_id"],
        "source_sha256": case["source_sha256"],
        "label_candidate": case["label_candidate"],
        "text_verified": "",
        "human_approved": False,
        "training_ready": False,
        "model_training_ready": False,
        "frames_expected": frames,
        "frames_decoded": source["frames"],
        "fps": source["fps"],
        "input_jpegs_decoded": frames,
        "renders_decoded": frames,
        "native_parameter_inventory": inventory,
        "metadata_files": len(metadata_files),
        "metadata_mapping_verified": True,
        "log_sha256": record["log_sha256"],
        "log_sha256_verified": True,
        "source_window_seconds": [case["start_seconds"], case["end_seconds"]],
        "nominal_source_time_not_original_pts_exact": True,
        "review_flags": source_record["review_flags"],
        "raw_quality_metrics": metrics,
        "contact_sheet": contact.name,
        "comparison_video": video.name,
        "comparison_video_frames": frames,
        "temporal_interpolation": False,
        "parameter_smoothing": False,
    }


def build(args):
    package = Path(args.package).resolve()
    pilot_root = Path(args.pilot_results).resolve()
    remaining_root = Path(args.remaining_results).resolve()
    output = Path(args.output).resolve()
    ffprobe, ffmpeg = Path(args.ffprobe).resolve(), Path(args.ffmpeg).resolve()
    if output.exists() or any(output == path or output in path.parents or path in output.parents for path in (package, pilot_root, remaining_root)):
        raise ValueError("Choose a new review output separate from all evidence inputs")
    manifest, cases, keyframes, manifest_sha = sequence.validate_package(package)
    if len(cases) != 12 or sum(row["frames"] for row in cases) != 2779 or keyframes:
        raise ValueError("Source-6 frozen package sequence/frame totals differ")
    for root in (pilot_root, remaining_root):
        verify_checksums(root)
    pilot = json.loads((pilot_root / "report.json").read_text())
    remaining = json.loads((remaining_root / "report.json").read_text())
    if (
        pilot.get("status") != "smplerx_sequences_completed_pending_quality_review"
        or remaining.get("status") != "smplerx_sequences_completed_pending_quality_review"
        or pilot.get("training_started") is not False
        or remaining.get("training_started") is not False
    ):
        raise ValueError("Candidate inference reports are incomplete or promoted")
    source_report_path = package.parent / "report.json"
    source_report = json.loads(source_report_path.read_text())
    source_rows = {row["annotation_id"]: row for row in source_report["references"]}
    if set(source_rows) != {case["annotation_id"] for case in cases}:
        raise ValueError("Coarse source review and reconstruction package IDs differ")
    attempts = [
        {
            "root": pilot_root,
            "run": pilot,
            "package_root": pilot_root.parent / "pilot-package",
            "ids": {row["annotation_id"] for row in pilot.get("candidate_records", [])},
        },
        {
            "root": remaining_root,
            "run": remaining,
            "package_root": remaining_root.parent / "remaining-package",
            "ids": {row["annotation_id"] for row in remaining.get("candidate_records", [])},
        },
    ]
    archive_evidence = []
    for attempt in attempts:
        subset_manifest, subset_cases, _, subset_sha = sequence.validate_package(attempt["package_root"])
        if (
            subset_sha != attempt["run"].get("input_manifest_sha256")
            or subset_manifest.get("parent_manifest_sha256") != manifest_sha
            or {row["annotation_id"] for row in subset_cases} != attempt["ids"]
            or len(attempt["run"].get("candidate_records", [])) != len(subset_cases)
            or attempt["run"].get("completed_sequences") != len(subset_cases)
            or attempt["run"].get("completed_frames") != sum(row["frames"] for row in subset_cases)
            or any(row not in cases for row in subset_cases)
            or attempt["run"].get("human_approved") is not False
            or attempt["run"].get("training_ready") is not False
        ):
            raise ValueError("Derived input package/output/approval binding differs")
        launch_name = "launch.json" if attempt["root"] == pilot_root else "remaining-launch.json"
        launch = json.loads((attempt["root"].parent / launch_name).read_text())
        attempt["remote_output_root"] = Path(launch["output"])
        archive_record_path = attempt["root"].parent.parent / "remote-archive.json"
        download_record_path = attempt["root"].parent.parent / "download-verification.json"
        archive_record = json.loads(archive_record_path.read_text())
        download_record = json.loads(download_record_path.read_text())
        if (
            archive_record.get("archive_sha256") != download_record.get("outer_archive_sha256")
            or archive_record.get("internal_manifest_sha256") != download_record.get("internal_manifest_sha256")
            or download_record.get("outer_and_internal_hashes_verified") is not True
        ):
            raise ValueError("Downloaded archive provenance does not match its verification record")
        archive_evidence.append(
            {
                "attempt": attempt["root"].name,
                "archive_sha256": archive_record["archive_sha256"],
                "internal_manifest_sha256": archive_record["internal_manifest_sha256"],
                "files_hashed": archive_record["files_hashed"],
                "download_and_all_hashes_verified": True,
            }
        )
    if attempts[0]["ids"] & attempts[1]["ids"]:
        raise ValueError("Inference attempts must contain disjoint candidate IDs")
    if set.union(*(attempt["ids"] for attempt in attempts)) != {case["annotation_id"] for case in cases}:
        raise ValueError("Completed inference IDs do not exactly cover the candidate package")
    if sum(attempt["run"].get("completed_frames", 0) for attempt in attempts) != manifest["frames"]:
        raise ValueError("Completed run frame totals differ from candidate manifest")
    output.mkdir(parents=True)
    results = []
    for case in cases:
        source_row = source_rows[case["annotation_id"]]
        attempt = next(row for row in attempts if case["annotation_id"] in row["ids"])
        results.append(
            audit_case(case, source_row, attempt["run"], attempt["root"], attempt, ffprobe, ffmpeg, output)
        )
    report = {
        "schema": "signbridge-source6-combined-candidate-review-v1",
        "status": "structural_audit_passed_motion_quality_unreviewed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_manifest_sha256": manifest_sha,
        "source_refinement_report_sha256": sha(source_report_path),
        "audit_tool_sha256": sha(Path(__file__)),
        "sequences": len(results),
        "frames": sum(row["frames_expected"] for row in results),
        "independent_mano_keyframes": 0,
        "inference_attempts": [
            {"name": "pilot-v1", "sequences": len(attempts[0]["ids"]), "frames": pilot["completed_frames"]},
            {"name": "remaining-v1", "sequences": len(attempts[1]["ids"]), "frames": remaining["completed_frames"]},
        ],
        "archive_evidence": archive_evidence,
        "records": results,
        "missed_detections_preserved_without_interpolation": True,
        "multiple_person_tracks_explicit": True,
        "raw_native_parameters_unmodified": True,
        "text_verified_count": 0,
        "human_approved": False,
        "training_ready": False,
        "model_training_ready": False,
        "training_started": False,
        "checkpoint_modified": False,
        "demo_updated": False,
        "limitations": [
            "Text and boundaries are coarse proposals, not human verified sign-language labels.",
            "Source timestamps use nominal 25 FPS clip mapping rather than original PTS.",
            "Frame-wise fit completeness and numerical continuity do not establish signing accuracy.",
            "Raw angular metrics are review signals, not thresholds for acceptance.",
            "Motion quality, language, mirror, handedness, signer and split remain unreviewed.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    markdown = [
        "# 第 6 批连续 SMPL-X 候选审阅",
        "",
        "两次固定模型重建共覆盖 12 个候选、2,779 帧。参数为未经平滑的原生逐帧输出；独立 MANO 关键帧为 0。结构审计不是动作质量审批或训练。",
        "",
        "归档、内部文件摘要、候选包、输入帧、参数／元数据／渲染集合和推理日志均逐项核验。无拟合的帧保持缺失；不插值、不补零。原片时间映射仍是名义 25 FPS，不等同原始 PTS。",
        "",
        "![试跑结果概览](overview.png)",
        "",
    ]
    for row in results:
        metric = row["raw_quality_metrics"]
        markdown.extend(
            [
                "## " + row["label_candidate"],
                "",
                f"{row['frames_expected']} 帧；参数文件 {row['native_parameter_inventory']['parameter_files']}；缺失拟合帧 {len(row['native_parameter_inventory']['missing_frames'])}；多人轨迹帧 {len(row['native_parameter_inventory']['multiple_person_frames'])}。",
                "",
                "复核标记：" + ("、".join(row["review_flags"]) if row["review_flags"] else "未附自动边界标记"),
                "",
                f"![原片与网格抽帧：{row['label_candidate']}]({row['contact_sheet']})",
                "",
                f"[打开完整逐帧原片／网格对照视频]({row['comparison_video']})",
                "",
                "| 参数组 | 相邻旋转 P95 | 球面中点残差 P95 | 大于 90° 过渡 |",
                "|---|---:|---:|---:|",
            ]
        )
        for key, label in (
            ("smplx_body_pose", "身体"),
            ("smplx_lhand_pose", "左手"),
            ("smplx_rhand_pose", "右手"),
        ):
            values = metric[key]
            adjacent = values["adjacent_degrees"]["p95"]
            residual = values["geodesic_midpoint_residual_degrees"]["p95"]
            markdown.append(
                f"| {label} | {adjacent if adjacent is not None else 'n/a'}° | {residual if residual is not None else 'n/a'}° | {values['frame_transitions_over_90_degrees']} |"
            )
        markdown.extend(["", "动作含义、边界准确性、镜像、人物及 Demo 适用性仍需人工确认。", ""])
    (output / "REVIEW.md").write_text("\n".join(markdown) + "\n")
    html_parts = [
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>第 6 批 SMPL-X 候选审阅</title>",
        "<style>body{max-width:1100px;margin:24px auto;padding:0 16px;font:16px system-ui;color:#18202a}section{border-top:1px solid #aaa;padding:20px 0}img,video{max-width:100%;height:auto}video{width:min(100%,960px)}li{margin:6px 0}</style><h1>第 6 批 SMPL-X 候选审阅</h1>",
        "<p>12 段 / 2,779 帧。结构检查已执行；动作质量、文本和边界尚未人工审批。输出是未经平滑的重建。</p><img src=\"overview.png\" alt=\"12 个候选的重建检查矩阵\"><p><a href=\"REVIEW.md\">详细指标和限制</a></p>",
    ]
    for row in results:
        html_parts.extend(
            [
                "<section><h2>" + html.escape(row["label_candidate"]) + "</h2>",
                "<p>" + str(row["frames_expected"]) + " 帧；缺失拟合 " + str(len(row["native_parameter_inventory"]["missing_frames"])) + "；多人轨迹 " + str(len(row["native_parameter_inventory"]["multiple_person_frames"])) + "</p>",
                "<img src=\"" + row["contact_sheet"] + "\" alt=\"原视频与 SMPL-X 网格关键帧对照\">",
                "<video controls preload=\"metadata\" src=\"" + row["comparison_video"] + "\"></video></section>",
            ]
        )
    html_parts.append("</html>")
    (output / "index.html").write_text("\n".join(html_parts) + "\n")
    overview = Image.new("RGB", (1200, ((len(results) + 2) // 3) * 300), "#101820")
    draw = ImageDraw.Draw(overview)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font = ImageFont.truetype(str(font_path), 18) if font_path.is_file() else ImageFont.load_default()
    for index, (case, row) in enumerate(zip(cases, results)):
        attempt = next(item for item in attempts if case["annotation_id"] in item["ids"])
        center = max(1, (case["frames"] + 1) // 2)
        input_dir = attempt["root"] / "input-frames" / case["annotation_id"]
        render_dir = attempt["root"] / "fits" / case["annotation_id"] / "img"
        x, y = (index % 3) * 400, (index // 3) * 300
        draw.text((x + 8, y + 4), row["label_candidate"][:27], font=font, fill="white")
        for side, folder in enumerate((input_dir, render_dir)):
            with Image.open(folder / f"{center:06d}.jpg") as image:
                image = image.convert("RGB")
                image.thumbnail((190, 255))
                left = x + 8 + side * 194 + (190 - image.width) // 2
                overview.paste(image, (left, y + 30))
            draw.text((x + 10 + side * 194, y + 280), "原片" if side == 0 else "SMPL-X", font=font, fill="white")
    overview.save(output / "overview.png")
    (output / "SHA256SUMS").write_text(
        "".join(sha(path) + "  " + path.name + "\n" for path in sorted(output.iterdir()) if path.is_file())
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--pilot-results", type=Path, required=True)
    parser.add_argument("--remaining-results", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    report = build(parser.parse_args())
    print(json.dumps({key: report[key] for key in ("status", "sequences", "frames")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
