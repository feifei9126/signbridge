"""Read-only 2D/3D contact-correspondence audit; never modifies or approves motion."""

import argparse
import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import numpy as np

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
FINGER_COLORS = ((231, 111, 81), (42, 157, 143), (233, 196, 106),
                 (106, 76, 147), (69, 123, 157))
FINGERTIP_IDS = (4, 8, 12, 16, 20)
OPENPOSE_TIP_TO_FINGER = dict(zip(FINGERTIP_IDS, FINGERS))
MANO_TIP_VERTICES = (744, 320, 443, 554, 671)
MANO_OPENPOSE_MAP = (0, 13, 14, 15, 16, 1, 2, 3, 17, 4, 5, 6, 18, 10, 11, 12, 19, 7, 8, 9, 20)
FRAME_IDS = (88, 89, 90, 91)
SEGMENT = "pilot-greeting-hello-001"
WINDOW_CASES = {
    "pilot-greeting-hello-001": set(range(88, 95)),
    "pilot-hospital-cough-003": set(range(156, 163)),
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def contained_file(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    path = (root / relative).resolve()
    if relative.is_absolute() or root not in path.parents or not path.is_file():
        raise ValueError("Missing input or unsafe path: " + str(relative))
    return path


def verify_manifest(root, manifest_path):
    root = Path(root).resolve()
    result = {}
    for line in Path(manifest_path).read_text(encoding="utf-8").splitlines():
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError("Malformed SHA256SUMS entry") from error
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or relative in result:
            raise ValueError("Invalid or duplicate SHA256SUMS entry: " + relative)
        path = contained_file(root, relative)
        if digest(path) != expected:
            raise ValueError("Evidence digest mismatch: " + relative)
        result[relative] = expected
    if not result:
        raise ValueError("Empty SHA256SUMS manifest")
    return result


def pairwise_distance_matrix(left, right, labels=FINGERS):
    left, right = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if left.ndim != 2 or right.shape != left.shape or left.shape[0] != len(labels):
        raise ValueError("Expected matching fingertip point arrays in the requested label order")
    if left.shape[1] not in (2, 3) or not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("Expected finite 2D or 3D fingertip coordinates")
    return np.linalg.norm(left[:, None, :] - right[None, :, :], axis=-1)


def pairwise_observation(left, right, unit, labels=FINGERS):
    if left is None or right is None:
        missing = [side for side, value in (("left", left), ("right", right)) if value is None]
        return {
            "status": "missing_" + "_and_".join(missing) + "_hand_observation",
            "unit": unit,
            "left_finger_order": list(labels),
            "right_finger_order": list(labels),
            "distance_matrix": None,
            "minimum_pair": None,
            "interpolated": False,
            "note": "nearest fingertip is not confirmed contact",
        }
    distances = pairwise_distance_matrix(left, right, labels)
    i, j = np.unravel_index(distances.argmin(), distances.shape)
    return {
        "status": "both_hands_observed",
        "unit": unit,
        "left_finger_order": list(labels),
        "right_finger_order": list(labels),
        "distance_matrix": distances.tolist(),
        "minimum_pair": {
            "left_finger": labels[i],
            "right_finger": labels[j],
            "distance": float(distances[i, j]),
        },
        "interpolated": False,
        "note": "nearest fingertip is not confirmed contact",
    }


def pairwise_minimum(left, right, labels=FINGERS):
    result = pairwise_observation(left, right, "unspecified", labels)
    return {**result["minimum_pair"], "distance_matrix": result["distance_matrix"],
            "note": result["note"]}


def observation_pair(left, right):
    return pairwise_observation(left, right, "px")


def openpose_pair_labels(pair):
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise ValueError("Expected a two-tip OpenPose index pair")
    if any(type(index) is not int for index in pair):
        raise ValueError("OpenPose indices must be integers without coercion")
    try:
        return [OPENPOSE_TIP_TO_FINGER[index] for index in pair]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Unknown OpenPose fingertip index") from error


def hand_geometry_metrics(points, unit):
    """Within-hand geometry only; independently estimated hands are not shared 3D truth."""
    if points is None:
        return {"status": "missing_hand_observation", "unit": unit, "interpolated": False}
    points = np.asarray(points, dtype=np.float64)
    dimension = {"px": 2, "m": 3}.get(unit)
    if points.shape != (21, dimension) or not np.isfinite(points).all():
        raise ValueError("Invalid hand geometry coordinates or units")
    palm = float(np.median(np.linalg.norm(points[[5, 9, 13, 17]] - points[0], axis=-1)))
    lengths = {}
    for index, finger in enumerate(FINGERS):
        chain = points[[0, 1 + 4 * index, 2 + 4 * index, 3 + 4 * index, 4 + 4 * index]]
        lengths[finger] = float(np.linalg.norm(np.diff(chain, axis=0), axis=-1).sum())
    return {"status": "measured" if palm > 1e-10 else "degenerate_palm_scale", "unit": unit,
            "palm_scale": palm, "finger_chain_lengths": lengths,
            "finger_chain_over_palm": {key: value / palm if palm > 1e-10 else None
                                       for key, value in lengths.items()},
            "definition": "palm=median wrist-to-MCP; chains=wrist-to-MCP-to-PIP-to-DIP-to-tip",
            "note": "model/observation geometry, not measured anatomy or contact truth"}


def require_source_digest(report, suffix, expected):
    """Match recorded remote paths by an exact suffix, never execute or open them."""
    matches = [value for name, value in report.get("source_sha256", {}).items()
               if name.endswith("/" + suffix)]
    if len(matches) != 1 or matches[0] != expected:
        raise ValueError("Recorded source digest mismatch: " + suffix)


def verify_mano_mapping(root, report):
    wrapper = contained_file(root, "wilor/models/mano_wrapper.py")
    require_source_digest(report, "wilor/models/mano_wrapper.py", digest(wrapper))
    assignments = [node for node in ast.walk(ast.parse(wrapper.read_text(encoding="utf-8")))
                   if isinstance(node, ast.Assign) and any(
                       isinstance(target, ast.Name) and target.id == "mano_to_openpose"
                       for target in node.targets)]
    if len(assignments) != 1 or tuple(ast.literal_eval(assignments[0].value)) != MANO_OPENPOSE_MAP:
        raise ValueError("WiLoR MANO/OpenPose mapping differs")
    return {"wrapper_sha256": digest(wrapper), "mano_to_openpose": list(MANO_OPENPOSE_MAP),
            "openpose_fingertip_indices": list(FINGERTIP_IDS),
            "mano_tip_vertex_ids": list(MANO_TIP_VERTICES), "finger_order": list(FINGERS)}


def verify_wilor_tip_vertices(values, side, image_size):
    if values["right"].shape != () or values["right"].dtype.kind != "b" or \
       bool(values["right"]) != (side == "right") or \
       not np.array_equal(values["image_size"], image_size):
        raise ValueError("Invalid WiLoR side identity or image dimensions")
    errors = {}
    for joint_key, vertex_key in (("joints", "vertices"), ("image_joints", "image_vertices")):
        joints, vertices = values[joint_key], values[vertex_key]
        if joints.shape != (21, 3) or vertices.shape != (778, 3) or \
           not np.isfinite(joints).all() or not np.isfinite(vertices).all():
            raise ValueError("Invalid WiLoR native/image geometry")
        error = float(np.max(np.abs(joints[list(FINGERTIP_IDS)] - vertices[list(MANO_TIP_VERTICES)])))
        if error > 1e-6:
            raise ValueError("WiLoR fingertip joint/vertex correspondence mismatch")
        errors[joint_key + "_tip_vertex_max_error_metres"] = error
    return errors


def compare_pair_labels(pairs):
    names = tuple(pairs)
    comparisons = {}
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            a, b = pairs[first], pairs[second]
            comparisons[first + "_vs_" + second + "_disagree"] = (
                None if a is None or b is None else list(a) != list(b)
            )
    return {
        "nearest_pair_by_source": {key: None if value is None else list(value)
                                   for key, value in pairs.items()},
        "pair_disagreements": comparisons,
        "contact_inferred": False,
    }


def draw_observation_points(image, mediapipe_points, wilor_points):
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 138, 322, 290), fill=(255, 255, 255), outline=(35, 45, 55), width=1)
    draw.text((26, 148), "Finger color; marker shows source/side", fill=(20, 30, 40))
    draw.text((26, 166), "Circle = MediaPipe; square = WiLoR", fill=(20, 30, 40))
    draw.text((26, 184), "Filled = left; hollow = right", fill=(20, 30, 40))
    for index, (finger, color) in enumerate(zip(FINGERS, FINGER_COLORS)):
        y = 207 + index * 15
        draw.ellipse((28, y, 36, y + 8), fill=color, outline=color)
        draw.text((43, y - 2), finger, fill=(20, 30, 40))

    for source_name, point_map in (("mediapipe", mediapipe_points), ("wilor", wilor_points)):
        for side, points in point_map.items():
            for color, point in zip(FINGER_COLORS, points):
                x, y = map(float, point)
                bounds = (x - 5, y - 5, x + 5, y + 5)
                fill = color if side == "left" else None
                if source_name == "mediapipe":
                    draw.ellipse(bounds, outline=color, width=3, fill=fill)
                else:
                    draw.rectangle(bounds, outline=color, width=3, fill=fill)


def make_review_sheet(images, frame_reports):
    from PIL import Image, ImageDraw

    sheet = Image.new("RGB", (1280, 850), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((20, 12), "Contact correspondence audit: geometric diagnostics, NOT contact labels", fill="black")
    draw.text((20, 30), "Circle=MediaPipe / square=WiLoR; filled=left / hollow=right", fill="black")
    for index, (finger, color) in enumerate(zip(FINGERS, FINGER_COLORS)):
        x = 20 + 130 * index
        draw.rectangle((x, 48, x + 10, 58), fill=color)
        draw.text((x + 16, 46), finger, fill="black")
    for index, ((frame, image), report) in enumerate(zip(images, frame_reports)):
        projected = report["wilor_fingertips_pixels"]
        points = np.concatenate([np.asarray(projected[side]) for side in ("left", "right")])
        low = np.floor(points.min(axis=0) - [55, 65]).astype(int)
        high = np.ceil(points.max(axis=0) + [55, 50]).astype(int)
        bounds = (max(0, low[0]), max(0, low[1]), min(image.width, high[0]), min(image.height, high[1]))
        crop = image.crop(bounds)
        scale = min(620 / crop.width, 330 / crop.height)
        crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                           Image.Resampling.LANCZOS)
        x, y = (index % 2) * 640, 80 + (index // 2) * 380
        sheet.paste(crop, (x + (640 - crop.width) // 2, y + 36))
        missing = report["sources"]["mediapipe_2d"]["status"]
        label = "Frame %d" % frame + ("; MediaPipe right hand MISSING" if "missing" in missing else "")
        draw.text((x + 20, y + 10), label, fill="black")
    return sheet


def report_contract(frames):
    return {
        "schema": "signbridge-contact-observation-audit-v1",
        "status": "audited_pending_correspondence_review",
        "scope": SEGMENT,
        "frames": frames,
        "contact_ground_truth": False,
        "contact_approved": False,
        "training_ready": False,
        "source_fits_modified": False,
        "limitations": [
            "nearest projected tip pair is not a human contact label",
            "WiLoR and SMPL-X/MANO are model estimates, not independent ground truth",
            "MediaPipe/WiLoR distances are pixels; SMPL-X distances are model-space metres",
            "original SMPL-X camera metadata is absent locally; no projected SMPL-X 2D matrix is claimed",
            "mirror_status_unknown",
            "frame 90 lacks MediaPipe right-hand observation; no interpolation",
            "camera, depth, occlusion and fingertip correspondence remain uncertain",
        ],
    }


def keyed_cases(report, segment, expected_frames):
    cases = [row for row in report.get("cases", []) if row.get("segment_id") == segment]
    result = {row["frame_1based"]: row for row in cases}
    if len(result) != len(cases) or set(result) != expected_frames:
        raise ValueError("Unexpected short-window frame scope for " + segment)
    return result


def load_model_helper():
    spec = importlib.util.spec_from_file_location(
        "contact_audit_hand_model", Path(__file__).with_name("sign-hand-refine.py")
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def audit(args):
    from PIL import Image

    batch, window, fusion, contact = (Path(p).resolve() for p in
                                      (args.batch, args.wilor_results, args.fusion_results,
                                       args.contact_results))
    roots = (batch, window.parent, fusion.parent, contact.parent,
             Path(args.smplerx_root).resolve(), Path(args.wilor_root).resolve())
    target = Path(args.output).resolve()
    if target.exists() or any(root == target or root in target.parents or target in root.parents
                              for root in roots):
        raise ValueError("Audit output must be new and separate from all inputs")

    reports = []
    manifests = []
    for root, expected_sha in ((window, args.wilor_report_sha256),
                               (fusion, args.fusion_report_sha256),
                               (contact, args.contact_report_sha256)):
        tree_root = root.parent
        manifest = verify_manifest(tree_root, tree_root / "SHA256SUMS")
        report_path = contained_file(root, "report.json")
        if digest(report_path) != expected_sha or manifest.get("results/report.json") != expected_sha:
            raise ValueError("Source report hash mismatch")
        reports.append(load_json(report_path))
        manifests.append(manifest)
    wilor_report, fusion_report, contact_report = reports
    wilor_manifest, fusion_manifest, contact_manifest = manifests
    schemas = ("signbridge-wilor-keyframe-pilot-v1", "signbridge-mano-smplx-alignment-v1",
               "signbridge-contact-hypothesis-pilot-v1")
    if any(report.get("schema") != schema for report, schema in zip(reports, schemas)):
        raise ValueError("Unexpected evidence report schema")
    if any(report.get("training_ready") is not False for report in reports):
        raise ValueError("Unexpected training-ready evidence")
    if fusion_report.get("wilor_report_sha256") != args.wilor_report_sha256 or \
       contact_report.get("fusion_report_sha256") != args.fusion_report_sha256 or \
       contact_report.get("wilor_report_sha256") != args.wilor_report_sha256:
        raise ValueError("Unexpected source report linkage")
    if contact_report.get("contact_approved") is not False or \
       contact_report.get("original_fits_overwritten") is not False or \
       contact_report.get("status") != "contact_proposals_rejected" or \
       contact_report.get("scope") != "greeting 88-91 only; no network inference, no finger or camera fitting":
        raise ValueError("Contact pilot is not a rejected, read-only hypothesis")

    contract_path = contained_file(batch, "contract.json")
    tasks_path = contained_file(batch, "tasks.jsonl")
    batch_manifest_path = contained_file(batch, "SHA256SUMS")
    batch_manifest = verify_manifest(batch, batch_manifest_path)
    contract = load_json(contract_path)
    for report in reports:
        for name in ("contract.json", "tasks.jsonl", "SHA256SUMS"):
            require_source_digest(report, "batch/" + name, digest(batch / name))
    if contract.get("schema") != "signbridge-smplerx-input-v1" or \
       contract.get("model_training_ready") is not False or \
       batch_manifest.get("contract.json") != digest(contract_path) or \
       batch_manifest.get("tasks.jsonl") != digest(tasks_path):
        raise ValueError("Batch contract or source manifest mismatch")
    task_rows = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    tasks = [row for row in task_rows if row.get("segment_id") == SEGMENT]
    if len(tasks) != 1:
        raise ValueError("Expected exactly one greeting segment in the batch")
    task = tasks[0]
    obs_path = contained_file(batch, "samples/" + SEGMENT + "/observations.npz")
    frame_manifest_path = contained_file(batch, task["frame_manifest"])
    if batch_manifest.get(str(obs_path.relative_to(batch))) != digest(obs_path) or \
       batch_manifest.get(task["frame_manifest"]) != digest(frame_manifest_path):
        raise ValueError("Observation/frame manifest hash mismatch")
    listed = [json.loads(line) for line in frame_manifest_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    if len(listed) != task["frames"] or task["frames"] != 166 or not np.isfinite(task["fps"]) or task["fps"] <= 0:
        raise ValueError("Unexpected source frame count or FPS")

    wilor_cases = keyed_cases(wilor_report, SEGMENT, WINDOW_CASES[SEGMENT])
    fusion_cases = keyed_cases(fusion_report, SEGMENT, WINDOW_CASES[SEGMENT])
    keyed_cases(wilor_report, "pilot-hospital-cough-003", WINDOW_CASES["pilot-hospital-cough-003"])
    keyed_cases(fusion_report, "pilot-hospital-cough-003", WINDOW_CASES["pilot-hospital-cough-003"])
    contact_cases = {row["frame_1based"]: row for row in contact_report.get("cases", [])}
    if len(contact_cases) != len(contact_report.get("cases", [])) or set(contact_cases) != set(FRAME_IDS):
        raise ValueError("Contact experiment frame scope differs")

    mapping_audit = verify_mano_mapping(args.wilor_root, wilor_report)
    observation_relative = str(obs_path.relative_to(batch))
    require_source_digest(wilor_report, "batch/" + observation_relative, digest(obs_path))
    for report in reports:
        require_source_digest(report, "batch/" + task["frame_manifest"], digest(frame_manifest_path))
    helper = load_model_helper()
    model_path = contained_file(args.smplerx_root, helper.MODEL_FILE)
    if digest(model_path) != helper.MODEL_SHA256:
        raise ValueError("Unexpected SMPL-X model file")
    for report in (fusion_report, contact_report):
        require_source_digest(report, "SMPLer-X/" + helper.MODEL_FILE, digest(model_path))
    model = helper.SparseSMPLX(model_path)
    arrays = np.load(obs_path, allow_pickle=False)
    try:
        if arrays["timestamps_seconds"].shape != (task["frames"],) or \
           not np.allclose(arrays["timestamps_seconds"], np.arange(task["frames"]) / task["fps"],
                           atol=1e-6, rtol=0):
            raise ValueError("Observation timestamps do not match source FPS")
        for side in ("left", "right"):
            if arrays[side + "_hand_image"].shape != (task["frames"], 21, 3) or \
               arrays[side + "_hand_image_detected"].shape != (task["frames"],) or \
               arrays[side + "_hand_image_detected"].dtype.kind != "b":
                raise ValueError("Unexpected MediaPipe observation shape")

        outputs = []
        images = []
        for frame in FRAME_IDS:
            row = listed[frame - 1]
            if row.get("frame_id") != frame or \
               not np.isclose(row["clip_seconds"], (frame - 1) / task["fps"], atol=1e-6, rtol=0):
                raise ValueError("Original frame identity/timestamp mismatch")
            image = contained_file(batch, row["image"])
            image_sha = digest(image)
            if image_sha != row["sha256"] or batch_manifest.get(str(image.relative_to(batch))) != image_sha:
                raise ValueError("Original frame manifest/hash mismatch")
            for report in reports:
                require_source_digest(report, "batch/" + row["image"], image_sha)
            with Image.open(image) as opened:
                width, height = opened.size
                annotated = opened.convert("RGB")
            detected = {side: bool(arrays[side + "_hand_image_detected"][frame - 1])
                        for side in ("left", "right")}
            mp_points = {}
            for side in ("left", "right"):
                if detected[side]:
                    normalized = arrays[side + "_hand_image"][frame - 1, list(FINGERTIP_IDS), :2]
                    if not np.isfinite(normalized).all() or np.max(np.abs(normalized)) > 2:
                        raise ValueError("Invalid MediaPipe fingertip observation")
                    mp_points[side] = normalized * np.asarray([width, height])

            wi_case = wilor_cases[frame]
            wi_hands = {}
            wi_geometry = {}
            wi_tip_checks = {}
            expected_folder = SEGMENT + "/%06d" % frame
            if wi_case["output_relative"] != expected_folder or wi_case.get("training_ready") is not False:
                raise ValueError("WiLoR frame/output identity differs")
            for item in wi_case.get("hands", []):
                side = item.get("side")
                if side not in ("left", "right") or side in wi_hands:
                    raise ValueError("Missing or duplicate WiLoR hand identity")
                relative = "results/" + wi_case["output_relative"] + "/" + item["parameters_file"]
                source = contained_file(window.parent, relative)
                if wilor_manifest.get(relative) != digest(source):
                    raise ValueError("WiLoR parameter digest mismatch")
                with np.load(source, allow_pickle=False) as values:
                    joints = values["projected_joints"]
                    wi_tip_checks[side] = verify_wilor_tip_vertices(values, side, [width, height])
                    wi_geometry[side] = values["image_joints"].copy()
                    is_right = bool(values["right"])
                    if joints.shape != (21, 2) or not np.isfinite(joints).all() or \
                       is_right != (side == "right"):
                        raise ValueError("Invalid WiLoR projected joints or side identity")
                    wi_hands[side] = joints[list(FINGERTIP_IDS)].astype(np.float64, copy=True)
            if set(wi_hands) != {"left", "right"}:
                raise ValueError("WiLoR did not observe both hands in the selected window")

            fusion_case = fusion_cases[frame]
            if fusion_case["output_relative"] != expected_folder or fusion_case.get("training_ready") is not False:
                raise ValueError("Fusion frame/output identity differs")
            relative = "results/" + fusion_case["output_relative"] + "/candidate.npz"
            fusion_file = contained_file(fusion.parent, relative)
            if fusion_manifest.get(relative) != digest(fusion_file):
                raise ValueError("Fusion candidate digest mismatch")
            contact_case = contact_cases[frame]
            if contact_case["output_relative"] != "%06d" % frame or \
               contact_case.get("candidate_gate_passed") is not False or \
               contact_case.get("training_ready") is not False:
                raise ValueError("Unexpected contact frame/rejection state")
            for name in ("previous-fusion.npz", "saved-candidate.npz"):
                rel = "results/" + contact_case["output_relative"] + "/" + name
                saved = contained_file(contact.parent, rel)
                if contact_manifest.get(rel) != digest(fusion_file) or digest(saved) != digest(fusion_file):
                    raise ValueError("Rejected contact result differs from previous fusion")
            params = helper.read_native(fusion_file)
            smplx_geometry = {side: model.hand(params, side) for side in ("left", "right")}
            smplx_points = {side: points[list(FINGERTIP_IDS)] for side, points in smplx_geometry.items()}
            geometry = {}
            for side in ("left", "right"):
                mano = hand_geometry_metrics(wi_geometry[side], "m")
                smplx = hand_geometry_metrics(smplx_geometry[side], "m")
                geometry[side] = {"wilor_mano": mano, "smplx_fusion": smplx,
                    "smplx_over_mano_palm_scale": smplx["palm_scale"] / mano["palm_scale"]
                        if mano["palm_scale"] > 1e-10 else None,
                    "smplx_over_mano_finger_chain_lengths": {
                        finger: smplx["finger_chain_lengths"][finger] / mano["finger_chain_lengths"][finger]
                            if mano["finger_chain_lengths"][finger] > 1e-10 else None
                        for finger in FINGERS},
                    "scale_fitted": False, "anatomy_confirmed": False}


            mp_result = pairwise_observation(mp_points.get("left"), mp_points.get("right"), "px")
            wi_result = pairwise_observation(wi_hands["left"], wi_hands["right"], "px")
            smplx_result = pairwise_observation(smplx_points["left"], smplx_points["right"], "m")
            solver_indices = contact_cases[frame]["tip_pair_openpose_indices"]
            solver_labels = openpose_pair_labels(solver_indices)
            labels = {
                "mediapipe": None if mp_result["minimum_pair"] is None else
                    [mp_result["minimum_pair"]["left_finger"], mp_result["minimum_pair"]["right_finger"]],
                "wilor": [wi_result["minimum_pair"]["left_finger"], wi_result["minimum_pair"]["right_finger"]],
                "smplx_3d": [smplx_result["minimum_pair"]["left_finger"],
                             smplx_result["minimum_pair"]["right_finger"]],
            }
            comparison = compare_pair_labels(labels)
            comparison["fixed_contact_solver_pair"] = {
                "openpose_tip_indices": list(solver_indices),
                "left_finger": solver_labels[0],
                "right_finger": solver_labels[1],
                "selection_rule": contact_cases[frame]["pair_selection"],
                "matches_nearest_by_source": {
                    name: None if value is None else value == solver_labels
                    for name, value in labels.items()
                },
            }
            outputs.append({
                "frame_1based": frame,
                "clip_seconds": (frame - 1) / task["fps"],
                "original_image_sha256": image_sha,
                "mirror_status": task["mirror_status"],
                "sources": {
                    "mediapipe_2d": {**mp_result, "left_hand_observed": detected["left"],
                                     "right_hand_observed": detected["right"]},
                    "wilor_2d": wi_result,
                    "smplx_fusion_3d": {
                        **smplx_result,
                        "coordinate_space": "fused SMPL-X model/camera coordinate space",
                        "projected_to_image": False,
                    },
                },
                "correspondence": comparison,
                "wilor_parameter_sha256": {
                    item["side"]: wilor_manifest["results/" + wi_case["output_relative"] + "/" +
                                   item["parameters_file"]]
                    for item in wi_case["hands"]
                },
                "wilor_fingertips_pixels": {side: points.tolist() for side, points in wi_hands.items()},
                "fusion_candidate_sha256": digest(fusion_file),
                "wilor_tip_vertex_checks": wi_tip_checks,
                "hand_geometry": geometry,
                "contact_confirmed": False,
                "training_ready": False,
            })

            draw_observation_points(annotated, mp_points, wi_hands)
            images.append((frame, annotated))
    finally:
        arrays.close()

    output = report_contract(outputs)
    output["evidence_reports"] = {
        "wilor_sha256": args.wilor_report_sha256,
        "fusion_sha256": args.fusion_report_sha256,
        "contact_pilot_sha256": args.contact_report_sha256,
    }
    output["batch_source_sha256"] = {
        "contract.json": digest(contract_path),
        "tasks.jsonl": digest(tasks_path),
        task["frame_manifest"]: digest(frame_manifest_path),
        str(obs_path.relative_to(batch)): digest(obs_path),
    }
    mapping_audit.update(wilor_tip_vertex_checks_passed=True,
                         smplx_tip_vertex_ids=helper.TIPS, smplx_finger_joint_chains=helper.JOINTS,
                         smplx_helper_sha256=digest(Path(__file__).with_name("sign-hand-refine.py")))
    output["mapping_audit"] = mapping_audit
    output["limitations"].append("MANO/SMPL-X within-hand scales are model estimates; no shape/scale fitting was performed")
    output["smplx_model_sha256"] = digest(model_path)
    output["audit_tool_sha256"] = digest(__file__)
    for root in (window.parent, fusion.parent, contact.parent, batch):
        verify_manifest(root, root / "SHA256SUMS")
    target.mkdir(parents=True)
    for frame, annotated in images:
        folder = target / ("%06d" % frame)
        folder.mkdir()
        annotated.save(folder / "observation-contact-points.png")
    make_review_sheet(images, outputs).save(target / "review-sheet.jpg", quality=95)
    report_path = target / "report.json"
    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    manifest_lines = []
    for path in sorted(p for p in target.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        manifest_lines.append(digest(path) + "  " + str(path.relative_to(target)))
    (target / "SHA256SUMS").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--wilor-results", type=Path, required=True)
    parser.add_argument("--wilor-report-sha256", required=True)
    parser.add_argument("--fusion-results", type=Path, required=True)
    parser.add_argument("--fusion-report-sha256", required=True)
    parser.add_argument("--contact-results", type=Path, required=True)
    parser.add_argument("--contact-report-sha256", required=True)
    parser.add_argument("--wilor-root", type=Path, required=True)
    parser.add_argument("--smplerx-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(audit(args))
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(main())
    except Exception as error:
        raise SystemExit("Contact observation audit failed: " + str(error)) from error
