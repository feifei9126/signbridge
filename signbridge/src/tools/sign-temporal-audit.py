"""Read-only temporal hand correspondence audit; never modifies or approves motion."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
FINGERTIP_IDS = (4, 8, 12, 16, 20)
TEMPORAL_HAND_IDS = (0,) + FINGERTIP_IDS
SEGMENTS = {
    "pilot-greeting-hello-001": (set(range(88, 95)), ("left", "right")),
    "pilot-hospital-cough-003": (set(range(156, 163)), ("right",)),
}


def load_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = load_tool("temporal_contact_evidence", Path(__file__).with_name("sign-contact-audit.py"))
digest = evidence.digest
contained_file = evidence.contained_file
read_json = evidence.load_json


def load_hand_tools():
    return evidence.load_model_helper()


def pair_observation(points_left, points_right, unit, required_sides=("left", "right")):
    if len(required_sides) == 1:
        return {"status": "not_applicable_single_hand", "unit": unit, "minimum_pair": None,
                "distance_matrix": None, "interpolated": False}
    if points_left is None or points_right is None:
        return {"status": "missing_hand_observation", "unit": unit, "minimum_pair": None,
                "distance_matrix": None, "interpolated": False}
    left = np.asarray(points_left, dtype=np.float64)
    right = np.asarray(points_right, dtype=np.float64)
    if left.ndim != 2 or left.shape[0] != 5 or right.shape != left.shape or left.shape[1] not in (2, 3):
        raise ValueError("Expected matching finite 2D/3D fingertip coordinates")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("Non-finite fingertip coordinates")
    distances = np.linalg.norm(left[:, None] - right[None, :], axis=-1)
    index = np.unravel_index(distances.argmin(), distances.shape)
    return {"status": "both_hands_observed", "unit": unit,
            "minimum_pair": {"left_finger": FINGERS[index[0]], "right_finger": FINGERS[index[1]],
                              "distance": float(distances[index])},
            "distance_matrix": distances.tolist(), "interpolated": False}


def summarize_pair_sequence(rows, expected_frames, required_sides):
    expected_frames = list(expected_frames)
    if [row["frame_1based"] for row in rows] != expected_frames or \
       len(set(expected_frames)) != len(expected_frames) or expected_frames != sorted(expected_frames):
        raise ValueError("Pair sequence frame identity/order differs")
    single_hand = len(required_sides) == 1
    values = {name: [row.get(name) for row in rows] for name in ("mediapipe", "wilor", "smplx_3d")}
    summary = {
        "frames": expected_frames,
        "nearest_pair_sequence": values,
        "pair_changes": {name: [] for name in values},
        "missing_pairs": {name: [] for name in values},
        "not_applicable": [],
        "cross_source_disagreements": [],
        "training_ready": False,
    }
    for index, frame in enumerate(expected_frames):
        pairs = {name: values[name][index] for name in values}
        if single_hand:
            summary["not_applicable"].append(frame)
            continue
        for name, value in pairs.items():
            if value is None:
                summary["missing_pairs"][name].append(frame)
            elif index and frame == expected_frames[index - 1] + 1 and \
                 values[name][index - 1] is not None and value != values[name][index - 1]:
                summary["pair_changes"][name].append(frame)
        observed = {name: value for name, value in pairs.items() if value is not None}
        if len(set(tuple(value) for value in observed.values())) > 1:
            summary["cross_source_disagreements"].append({"frame_1based": frame, "pairs": observed})
    return summary


def rotation_step_degrees(current, previous):
    from scipy.spatial.transform import Rotation

    current = np.asarray(current, dtype=np.float64)
    previous = np.asarray(previous, dtype=np.float64)
    if current.ndim != 3 or current.shape[1:] != (3, 3) or previous.shape != current.shape or \
       not all(np.isfinite(r).all() and np.allclose(r @ r.transpose(0, 2, 1), np.eye(3), atol=1e-4)
               and np.allclose(np.linalg.det(r), 1., atol=1e-4) for r in (current, previous)):
        raise ValueError("Expected proper rotation matrices")
    delta = Rotation.from_matrix(current @ previous.transpose(0, 2, 1))
    return float(np.rad2deg(delta.magnitude().max()))


def summarize_transitions(rows, expected_frames=None):
    ids = [row["frame_1based"] for row in rows]
    if ids != sorted(set(ids)):
        raise ValueError("Rotation sequence frame identity/order differs")
    expected_frames = ids if expected_frames is None else list(expected_frames)
    transitions = []
    suspicious = []
    for previous, current in zip(rows, rows[1:]):
        if current["frame_1based"] != previous["frame_1based"] + 1:
            continue
        entry = {
            "from_frame": previous["frame_1based"],
            "to_frame": current["frame_1based"],
            "max_finger_degrees": rotation_step_degrees(current["hand_pose"], previous["hand_pose"]),
            "wrist_orientation_degrees": rotation_step_degrees(
                current["global_orient"][None], previous["global_orient"][None]),
            "wrist_step_pixels": float(np.linalg.norm(current["wrist"] - previous["wrist"])),
        }
        entry["suspicious"] = bool(entry["max_finger_degrees"] > 45 or
                                     entry["wrist_orientation_degrees"] > 30 or
                                     entry["wrist_step_pixels"] > 40)
        transitions.append(entry)
        if entry["suspicious"]:
            suspicious.append(current["frame_1based"])
    return {"transitions": transitions, "suspicious_frames": suspicious,
            "training_ready": False, "continuity_complete": ids == expected_frames and
            len(transitions) == max(0, len(expected_frames) - 1)}


def summarize_points(rows, point_key, unit, expected_frames=None):
    ids = [row["frame_1based"] for row in rows]
    if ids != sorted(set(ids)):
        raise ValueError("Point sequence frame identity/order differs")
    expected_frames = ids if expected_frames is None else list(expected_frames)
    transitions = []
    for previous, current in zip(rows, rows[1:]):
        if current["frame_1based"] != previous["frame_1based"] + 1:
            continue
        old = np.asarray(previous[point_key], dtype=np.float64)
        new = np.asarray(current[point_key], dtype=np.float64)
        if old.shape not in ((6, 2), (6, 3)) or new.shape != old.shape or \
           not np.isfinite(old).all() or not np.isfinite(new).all():
            raise ValueError("Expected finite wrist plus five fingertip points")
        deltas = np.linalg.norm(new - old, axis=-1)
        local_delta = (new[1:] - new[0]) - (old[1:] - old[0])
        entry = {"from_frame": previous["frame_1based"], "to_frame": current["frame_1based"],
                 "max_point_step": float(deltas.max()), "mean_point_step": float(deltas.mean()),
                 "wrist_step": float(deltas[0]), "unit": unit,
                 "max_wrist_relative_step": float(np.linalg.norm(local_delta, axis=-1).max())}
        if point_key == "points" and unit == "m" and "translation" in current and "translation" in previous:
            translation_delta = current["translation"] - previous["translation"]
            entry.update(translation_step=float(np.linalg.norm(translation_delta)),
                         depth_translation_step=float(abs(translation_delta[2])),
                         max_translation_removed_step=float(np.linalg.norm(
                             new - current["translation"] - (old - previous["translation"]), axis=-1).max()))
        transitions.append(entry)
    return {"transitions": transitions, "largest_max_point_step": max(
        (row["max_point_step"] for row in transitions), default=0.0),
        "largest_max_wrist_relative_step": max((row["max_wrist_relative_step"] for row in transitions), default=0.0),
        "missing_frames": sorted(set(expected_frames) - set(ids)),
        "point_order": ["wrist"] + list(FINGERS),
        "coordinate_space": "wrist_relative" if point_key == "wrist_relative_points" else
            ("image_pixels" if unit == "px" else "per_frame_model_camera"),
        "training_ready": False, "continuity_complete": ids == expected_frames and
        len(transitions) == max(0, len(expected_frames) - 1)}


def temporal_points(points):
    points = np.asarray(points, dtype=np.float64)
    if points.shape != (21, 3) or not np.isfinite(points).all():
        raise ValueError("Expected finite 21x3 hand points")
    return points[list(TEMPORAL_HAND_IDS)]


def nearest_labels(result):
    pair = result.get("minimum_pair")
    return None if pair is None else [pair["left_finger"], pair["right_finger"]]


def report_contract(windows):
    return {
        "schema": "signbridge-temporal-hand-audit-v1",
        "status": "audited_pending_visual_review",
        "scope": "WiLoR/SMPL-X short windows only; no smoothing or parameter replacement",
        "windows": windows,
        "contact_approved": False,
        "training_ready": False,
        "source_fits_modified": False,
        "finger_order": list(FINGERS),
        "rotation_review_thresholds": {"max_finger_degrees": 45, "wrist_orientation_degrees": 30,
                                       "wrist_step_pixels": 40, "quality_acceptance_rule": False},
        "limitations": [
            "short windows do not establish full-video temporal quality",
            "suspicious transitions can be genuine signing motion or reconstruction error",
            "nearest fingertip pairs are geometric diagnostics, not contact labels",
            "mirror status and sign-language semantics remain unverified",
            "SMPL-X absolute coordinates include per-frame camera/root estimates; metre steps are not measured world motion",
            "wrist-relative steps remove common translation, not orientation/shape changes; not a jitter score",
            "pixels and model-space metres cannot be directly compared",
        ],
    }


def verify_manifest(root):
    return evidence.verify_manifest(root, Path(root) / "SHA256SUMS")


def verified_report(results, expected_sha):
    root = Path(results).resolve()
    manifest = verify_manifest(root.parent)
    report = contained_file(root, "report.json")
    if digest(report) != expected_sha or manifest.get("results/report.json") != expected_sha:
        raise ValueError("Evidence report hash mismatch")
    return read_json(report), manifest


def keyed_cases(report, segment, expected):
    rows = [row for row in report.get("cases", []) if row.get("segment_id") == segment]
    indexed = {row["frame_1based"]: row for row in rows}
    if len(rows) != len(indexed) or set(indexed) != expected:
        raise ValueError("Unexpected frame scope: " + segment)
    return indexed


def make_sheet(images, summaries, output):
    from PIL import Image, ImageDraw

    sheet = Image.new("RGB", (1280, 80 + 4 * 280), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), "Short-window diagnostics, NOT contact/semantic approval", fill="black")
    draw.text((12, 28), "Circle=MediaPipe / square=WiLoR; filled=left / hollow=right. MP/W=pixels; S=model-space 3D.", fill="black")
    for i, (name, color) in enumerate(zip(FINGERS, evidence.FINGER_COLORS)):
        draw.rectangle((12 + i * 135, 50, 22 + i * 135, 60), fill=color)
        draw.text((30 + i * 135, 47), name, fill="black")
    for index, (segment, frame, image) in enumerate(images):
        x = (index % 4) * 320
        y = 80 + (index // 4) * 280
        thumb = image.copy()
        thumb.thumbnail((310, 190))
        sheet.paste(thumb, (x + 5, y + 75))
        summary = summaries[(segment, frame)]
        pairs = {name: summary.get(name) for name in ("mediapipe", "wilor", "smplx_3d")}
        def label(pair):
            if len(SEGMENTS[segment][1]) == 1:
                return "N/A (single-hand scope)"
            return "missing" if pair is None else " - ".join(pair)
        text = [("Hello" if "greeting" in segment else "Cough") + " f" + str(frame),
                "MP: " + label(pairs["mediapipe"]), "W: " + label(pairs["wilor"]),
                "S: " + label(pairs["smplx_3d"])]
        for line, value in enumerate(text):
            draw.text((x + 7, y + line * 16), value, fill="black")
    sheet.save(output, quality=95)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--wilor-results", type=Path, required=True)
    parser.add_argument("--wilor-report-sha256", required=True)
    parser.add_argument("--fusion-results", type=Path, required=True)
    parser.add_argument("--fusion-report-sha256", required=True)
    parser.add_argument("--smplerx-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(audit(args))
    return 0


def audit(args):
    from PIL import Image

    batch = Path(args.batch).resolve()
    wilor_root = Path(args.wilor_results).resolve()
    fusion_root = Path(args.fusion_results).resolve()
    output = Path(args.output).resolve()
    protected = (batch, wilor_root.parent, fusion_root.parent, Path(args.smplerx_root).resolve())
    if output.exists() or any(root == output or root in output.parents or output in root.parents for root in protected):
        raise ValueError("Audit output must be new and separate")

    wilor_report, wilor_manifest = verified_report(wilor_root, args.wilor_report_sha256)
    fusion_report, fusion_manifest = verified_report(fusion_root, args.fusion_report_sha256)
    if wilor_report.get("schema") != "signbridge-wilor-keyframe-pilot-v1" or \
       fusion_report.get("schema") != "signbridge-mano-smplx-alignment-v1":
        raise ValueError("Unexpected evidence report schema")
    if wilor_report.get("training_ready") is not False or fusion_report.get("training_ready") is not False:
        raise ValueError("Unexpected training-ready source evidence")
    if fusion_report.get("wilor_report_sha256") != args.wilor_report_sha256:
        raise ValueError("Fusion/WiLoR report linkage mismatch")
    expected_cases = {(segment, frame) for segment, (ids, _) in SEGMENTS.items() for frame in ids}
    for report in (wilor_report, fusion_report):
        rows = report.get("cases", [])
        if len(rows) != len(expected_cases) or \
           {(r["segment_id"], r["frame_1based"]) for r in rows} != expected_cases:
            raise ValueError("Evidence short-window scope differs")

    batch_manifest = verify_manifest(batch)
    contract_path = contained_file(batch, "contract.json")
    tasks_path = contained_file(batch, "tasks.jsonl")
    contract = read_json(contract_path)
    if contract.get("schema") != "signbridge-smplerx-input-v1" or contract.get("model_training_ready") is not False:
        raise ValueError("Unexpected batch contract")
    for report in (wilor_report, fusion_report):
        for name in ("contract.json", "tasks.jsonl", "SHA256SUMS"):
            evidence.require_source_digest(report, "batch/" + name, digest(batch / name))
    for name in ("contract.json", "tasks.jsonl"):
        if batch_manifest.get(name) != digest(batch / name):
            raise ValueError("Unlisted batch contract/tasks")
    task_rows = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]
    tasks = {row["segment_id"]: row for row in task_rows}
    if len(tasks) != len(task_rows):
        raise ValueError("Duplicate batch tasks")

    hand_tools = load_hand_tools()
    model_path = contained_file(args.smplerx_root, hand_tools.MODEL_FILE)
    if digest(model_path) != hand_tools.MODEL_SHA256:
        raise ValueError("Unexpected SMPL-X model")
    evidence.require_source_digest(fusion_report, "SMPLer-X/" + hand_tools.MODEL_FILE, digest(model_path))
    model = hand_tools.SparseSMPLX(model_path)
    windows = {}
    images = []
    summary_index = {}

    for segment, (expected_frames, required_sides) in SEGMENTS.items():
        task = tasks.get(segment)
        if task is None:
            raise ValueError("Missing batch task: " + segment)
        if not np.isfinite(task["fps"]) or task["fps"] <= 0 or \
           task.get("model_training_ready") is not False:
            raise ValueError("Invalid task FPS/readiness")
        frame_manifest_path = contained_file(batch, task["frame_manifest"])
        if batch_manifest.get(task["frame_manifest"]) != digest(frame_manifest_path):
            raise ValueError("Frame manifest hash mismatch")
        for report in (wilor_report, fusion_report):
            evidence.require_source_digest(report, "batch/" + task["frame_manifest"], digest(frame_manifest_path))
        listed = [json.loads(line) for line in frame_manifest_path.read_text().splitlines() if line.strip()]
        frames = {row["frame_id"]: row for row in listed}
        if len(frames) != len(listed) or list(frames) != list(range(1, task["frames"] + 1)):
            raise ValueError("Frame manifest identity/order differs")
        obs_path = contained_file(batch, "samples/" + segment + "/observations.npz")
        if batch_manifest.get(str(obs_path.relative_to(batch))) != digest(obs_path):
            raise ValueError("Observation hash mismatch")
        evidence.require_source_digest(wilor_report, "batch/" + str(obs_path.relative_to(batch)), digest(obs_path))
        with np.load(obs_path, allow_pickle=False) as observations:
            if observations["timestamps_seconds"].shape != (task["frames"],) or \
               not np.allclose(observations["timestamps_seconds"], np.arange(task["frames"]) / task["fps"], atol=1e-6, rtol=0):
                raise ValueError("Observation timestamps differ")
            for side in required_sides:
                if observations[side + "_hand_image"].shape != (task["frames"], 21, 3) or \
                   observations[side + "_hand_image_detected"].shape != (task["frames"],) or \
                   observations[side + "_hand_image_detected"].dtype.kind != "b":
                    raise ValueError("Invalid observation shape/mask")
            wilor_cases = keyed_cases(wilor_report, segment, expected_frames)
            fusion_cases = keyed_cases(fusion_report, segment, expected_frames)
            frame_rows = []
            wilor_side_rows = {side: [] for side in required_sides}
            fusion_side_rows = {side: [] for side in required_sides}
            mediapipe_side_rows = {side: [] for side in required_sides}
            pair_rows = []
            missing = {"mediapipe": {side: [] for side in required_sides}, "wilor": [], "fusion": []}
            for frame in sorted(expected_frames):
                manifest_row = frames.get(frame)
                if manifest_row is None:
                    raise ValueError("Missing frame manifest row")
                expected_folder = segment + "/%06d" % frame
                expected_image = "samples/" + segment + "/images/%06d.jpg" % frame
                if manifest_row["image"] != expected_image or not np.isclose(
                    manifest_row["clip_seconds"], (frame - 1) / task["fps"], atol=1e-6, rtol=0):
                    raise ValueError("Frame/image identity or time mismatch")
                image = contained_file(batch, manifest_row["image"])
                if digest(image) != manifest_row["sha256"] or batch_manifest.get(str(image.relative_to(batch))) != digest(image):
                    raise ValueError("Frame/image digest mismatch")
                for report in (wilor_report, fusion_report):
                    evidence.require_source_digest(report, "batch/" + expected_image, digest(image))
                with Image.open(image) as opened:
                    width, height = opened.size
                    image_copy = opened.convert("RGB")
                detected = {side: bool(observations[side + "_hand_image_detected"][frame - 1]) for side in required_sides}
                mp_points = {}
                for side in required_sides:
                    if not detected[side]:
                        missing["mediapipe"][side].append(frame)
                        continue
                    points = observations[side + "_hand_image"][frame - 1, [0] + list(FINGERTIP_IDS), :2]
                    if not np.isfinite(points).all() or np.max(np.abs(points)) > 2:
                        raise ValueError("Invalid detected MediaPipe observation")
                    points = points * np.asarray([width, height])
                    mp_points[side] = points[1:]
                    mediapipe_side_rows[side].append({"frame_1based": frame, "points": points,
                                                      "wrist_relative_points": points - points[:1]})

                wi_case = wilor_cases[frame]
                if wi_case["output_relative"] != expected_folder or \
                   wi_case.get("required_sides") != list(required_sides) or wi_case.get("training_ready") is not False:
                    raise ValueError("WiLoR frame/output identity differs")
                wi_hands = {}
                for item in wi_case["hands"]:
                    side = item["side"]
                    if side not in required_sides or side in wi_hands:
                        raise ValueError("Ambiguous WiLoR hand identity")
                    name = item["parameters_file"]
                    if Path(name).name != name or not name.startswith(side + "-") or not name.endswith(".npz"):
                        raise ValueError("Unsafe WiLoR parameter name")
                    relative = "results/" + wi_case["output_relative"] + "/" + item["parameters_file"]
                    source = contained_file(wilor_root.parent, relative)
                    if wilor_manifest.get(relative) != digest(source):
                        raise ValueError("WiLoR parameter digest mismatch")
                    with np.load(source, allow_pickle=False) as values:
                        evidence.verify_wilor_tip_vertices(values, side, [width, height])
                        if values["projected_joints"].shape != (21, 2) or not np.isfinite(values["projected_joints"]).all():
                            raise ValueError("Invalid WiLoR projected joints")
                        wi_hands[side] = values["projected_joints"][list(FINGERTIP_IDS)].astype(np.float64)
                        points = values["projected_joints"][[0] + list(FINGERTIP_IDS)].astype(np.float64)
                        wilor_side_rows[side].append({"frame_1based": frame, "hand_pose": values["hand_pose"].copy(),
                                                     "global_orient": values["global_orient"][0].copy(),
                                                     "wrist": values["projected_joints"][0].copy(),
                                                     "points": points,
                                                     "wrist_relative_points": points - points[:1]})
                if set(wi_hands) != set(required_sides):
                    raise ValueError("Missing required WiLoR hand; refusing to fill/interpolate")

                fu_case = fusion_cases[frame]
                if fu_case["output_relative"] != expected_folder or \
                   fu_case.get("required_sides") != list(required_sides) or fu_case.get("training_ready") is not False:
                    raise ValueError("Fusion frame/output identity differs")
                relative = "results/" + fu_case["output_relative"] + "/candidate.npz"
                fusion_file = contained_file(fusion_root.parent, relative)
                if fusion_manifest.get(relative) != digest(fusion_file):
                    raise ValueError("Fusion candidate digest mismatch")
                params = hand_tools.read_native(fusion_file)
                baseline_relative = "results/" + fu_case["output_relative"] + "/baseline.npz"
                baseline_file = contained_file(fusion_root.parent, baseline_relative)
                if fusion_manifest.get(baseline_relative) != digest(baseline_file):
                    raise ValueError("Fusion baseline digest mismatch")
                hand_tools.preserved(hand_tools.read_native(baseline_file), params, required_sides,
                                     allow_elbow=True)
                smplx_hands = {side: model.hand(params, side) for side in required_sides}
                for side in required_sides:
                    points = temporal_points(smplx_hands[side])
                    fusion_side_rows[side].append({"frame_1based": frame,
                                                   "points": points,
                                                   "wrist_relative_points": points - points[:1],
                                                   "translation": params["transl"].ravel().astype(np.float64)})

                mp_pair = pair_observation(mp_points.get("left"), mp_points.get("right"), "px", required_sides)
                wi_pair = pair_observation(wi_hands.get("left"), wi_hands.get("right"), "px", required_sides)
                smplx_pair = pair_observation(
                    None if "left" not in smplx_hands else smplx_hands["left"][list(FINGERTIP_IDS)],
                    None if "right" not in smplx_hands else smplx_hands["right"][list(FINGERTIP_IDS)], "m", required_sides)
                pair_rows.append({"frame_1based": frame, "mediapipe": nearest_labels(mp_pair),
                                  "wilor": nearest_labels(wi_pair), "smplx_3d": nearest_labels(smplx_pair),
                                  "mediapipe_result": mp_pair, "wilor_result": wi_pair, "smplx_result": smplx_pair})
                frame_rows.append({"frame_1based": frame, "image_sha256": digest(image),
                                   "mediapipe_detected": detected, "wilor_sides": sorted(wi_hands),
                                   "pair_labels": {key: value for key, value in pair_rows[-1].items()
                                                   if key in ("mediapipe", "wilor", "smplx_3d")},
                                   "pair_observations": {"mediapipe": mp_pair, "wilor": wi_pair, "smplx_3d": smplx_pair},
                                   "source_fusion_sha256": digest(fusion_file), "mirror_status": task["mirror_status"],
                                   "source_baseline_sha256": digest(baseline_file),
                                   "protected_parameters_match_baseline": True,
                                   "training_ready": False})
                evidence.draw_observation_points(image_copy, mp_points, wi_hands)
                bounds_points = np.concatenate(list(wi_hands.values()))
                low = np.maximum(np.floor(bounds_points.min(axis=0) - [65, 70]), [0, 0]).astype(int)
                high = np.minimum(np.ceil(bounds_points.max(axis=0) + [65, 55]), [width, height]).astype(int)
                images.append((segment, frame, image_copy.crop((low[0], low[1], high[0], high[1]))))

            pair_summary = summarize_pair_sequence(pair_rows, sorted(expected_frames), required_sides)
            temporal = {"wilor": {}, "wilor_wrist_relative": {},
                        "fusion": {}, "fusion_wrist_relative": {},
                        "mediapipe": {}, "mediapipe_wrist_relative": {}}
            for side in required_sides:
                temporal["wilor"][side] = summarize_transitions(wilor_side_rows[side], sorted(expected_frames))
                temporal["fusion"][side] = summarize_points(fusion_side_rows[side], "points", "m", sorted(expected_frames))
                temporal["mediapipe"][side] = summarize_points(mediapipe_side_rows[side], "points", "px", sorted(expected_frames))
                temporal["wilor_wrist_relative"][side] = summarize_points(
                    wilor_side_rows[side], "wrist_relative_points", "px", sorted(expected_frames))
                temporal["fusion_wrist_relative"][side] = summarize_points(
                    fusion_side_rows[side], "wrist_relative_points", "m", sorted(expected_frames))
                temporal["mediapipe_wrist_relative"][side] = summarize_points(
                    mediapipe_side_rows[side], "wrist_relative_points", "px", sorted(expected_frames))
            window = {"segment_id": segment, "frames": sorted(expected_frames),
                      "required_sides": list(required_sides), "missing": missing,
                      "pair_sequence": pair_summary, "temporal": temporal,
                      "frame_rows": frame_rows, "training_ready": False}
            windows[segment] = window
            summary_index.update({(segment, row["frame_1based"]): row for row in pair_rows})

    output_report = report_contract(windows)
    output_report["source_reports"] = {"wilor_sha256": args.wilor_report_sha256,
                                       "fusion_sha256": args.fusion_report_sha256,
                                       "batch_contract_sha256": digest(contract_path),
                                       "batch_tasks_sha256": digest(tasks_path),
                                       "smplx_model_sha256": digest(model_path)}
    output_report["audit_tool_sha256"] = digest(__file__)
    output_report["evidence_tool_sha256"] = digest(Path(__file__).with_name("sign-contact-audit.py"))
    for root in (batch, wilor_root.parent, fusion_root.parent):
        verify_manifest(root)
    # Render before writing the completion report so failed media cannot look like a complete audit.
    output.mkdir(parents=True)
    make_sheet(images, summary_index, output / "temporal-review-sheet.jpg")
    report_path = output / "report.json"
    report_path.write_text(json.dumps(output_report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    manifest_lines = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        manifest_lines.append(digest(path) + "  " + str(path.relative_to(output)))
    (output / "SHA256SUMS").write_text("\n".join(manifest_lines) + "\n")
    return report_path


if __name__ == "__main__":
    raise SystemExit(main())
