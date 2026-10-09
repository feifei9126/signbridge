"""Pinned WiLoR inference on two audited keyframes, never training or SMPL-X replacement."""

import argparse
import gc
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

COMMIT = "fcb911312a38fa8badd30d9656a167485d61b8f9"
ASSETS = {
    "pretrained_models/detector.pt": (53582271, "5ef3df44e42d2db52d4ffe91f83a22ce9925e2acc9abebf453f2c5d22e380033"),
    "pretrained_models/wilor_final.ckpt": (2564989533, "3e97aafc7dd08d883a4cc5a027df61fdb6fda6136dbd1319405413862ada6bb2"),
}
MANO_BYTES = 3821356
MANO_SHA = "45d60aa3b27ef9107a7afd4e00808f307fd91111e1cfa35afd5c4a62de264767"
SOURCE_DIGESTS = {
    "wilor/models/wilor.py": "9744194093a8307d2fba26c4a85edd39d99e1a556f3867372b62d29bce514fdc",
    "wilor/models/mano_wrapper.py": "dbe78558c3ccaa6deaba7731858565dcdd193fb0ee7b6543c059a07f0408239a",
    "wilor/models/backbones/vit.py": "5424ff143d2a8db9f0a722da34857bff2559c4867d9295fb3648e0293f5de013",
    "wilor/models/heads/refinement_net.py": "5878350b52af6c4cd27541ee02579ea7fe30549ef8e101a72fe2cf6a82eef59d",
    "wilor/datasets/vitdet_dataset.py": "e525c2dde01c90180eafab4fcfad6bc1bcc94b64597385f1776fc460e4af40f3",
    "wilor/datasets/utils.py": "24229bd14758b5f73a3531ceb73f4c93f3955278df21800f5a34115221e534fd",
    "wilor/configs/__init__.py": "2570cce9c9bf45b46fbe53b94b57655638d90fe6a3183854a766cf128eedb3ba",
    "pretrained_models/model_config.yaml": "64e75699eb7f1234ee16ba1bbb983db35e03f584fe4bd524559432b1efec3d2c",
    "mano_data/mano_mean_params.npz": "efc0ec58e4a5cef78f3abfb4e8f91623b8950be9eff8b8e0dbb0d036ebc63988",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def check_asset(path, expected_bytes, expected_sha):
    path = Path(path)
    require(path.is_file() and path.stat().st_size == expected_bytes, "Asset size differs: " + str(path))
    actual = sha256(path)
    require(actual == expected_sha, "Asset SHA-256 differs: " + str(path))
    return actual


def check_source(root):
    for name, digest in SOURCE_DIGESTS.items():
        require(sha256(Path(root) / name) == digest, "Native source SHA-256 differs: " + name)


def project_full(points, focal, width, height):
    require(points.ndim == 2 and points.shape[1] == 3 and np.isfinite(points).all() and
            (points[:, 2] > 1e-8).all(), "Invalid positive-z projection points")
    require(focal > 0 and width > 0 and height > 0, "Invalid perspective intrinsics")
    return points[:, :2] / points[:, 2:] * focal + np.asarray([width / 2, height / 2])


def check_render_projection(original, rendered, camera_vertices, focal):
    """Reject render distortions even when an EGL context returns visible pixels."""
    height, width = original.shape[:2]
    xy = project_full(camera_vertices, focal, width, height)
    return check_render_bounds(original, rendered, xy)


def check_render_bounds(original, rendered, projected_vertices):
    """Compare mask with given 2D projection, including offset/anisotropic native cameras."""
    require(original.shape == rendered.shape and rendered.dtype == np.uint8, "Invalid rendered image")
    xy = np.asarray(projected_vertices)
    require(xy.ndim == 2 and xy.shape[1] == 2 and len(xy) > 0 and np.isfinite(xy).all(),
            "Invalid analytical projection")
    ys, xs = np.where(np.any(rendered != original, axis=-1))
    require(len(xs) > 0, "No visible hand mesh pixels")
    low, high = xy.min(axis=0), xy.max(axis=0)
    require(xs.min() >= np.floor(low[0]) - 2 and xs.max() <= np.ceil(high[0]) + 2 and
            ys.min() >= np.floor(low[1]) - 2 and ys.max() <= np.ceil(high[1]) + 2,
            "Rendered mesh differs from analytical perspective projection")
    return {"render_projection_bbox_passed": True, "rendered_pixels": int(len(xs)),
            "rendered_mask_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
            "projected_vertex_bbox": [low.tolist(), high.tolist()]}


def to_image_handedness(vertices, joints, faces, is_right):
    require(is_right in (False, True) and np.isfinite(vertices).all() and np.isfinite(joints).all(),
            "Invalid detector handedness or mesh values")
    vertices, joints, faces = vertices.copy(), joints.copy(), faces.copy()
    if not is_right:
        vertices[:, 0] *= -1
        joints[:, 0] *= -1
        faces = faces[:, [0, 2, 1]]
    return vertices, joints, faces


def check_outputs(arrays):
    expected = {"vertices": (778, 3), "joints": (21, 3), "global_orient": (1, 3, 3),
                "hand_pose": (15, 3, 3), "betas": (10,), "camera_translation": (3,)}
    for key, shape in expected.items():
        value = arrays[key]
        require(value.shape == shape and value.dtype.kind == "f" and np.isfinite(value).all(),
                "Invalid WiLoR output: " + key)
    for key in ("global_orient", "hand_pose"):
        rotation = arrays[key]
        require(np.allclose(rotation @ rotation.transpose(0, 2, 1), np.eye(3), atol=1e-4) and
                np.allclose(np.linalg.det(rotation), 1, atol=1e-4), "Invalid rotation matrix: " + key)


def short_window_cases():
    return [("pilot-greeting-hello-001", n, ("left", "right")) for n in range(88, 95)] + \
           [("pilot-hospital-cough-003", n, ("right",)) for n in range(156, 163)]


def temporal_summary(rows, required_sides):
    """Observed adjacent frames only; no bridging of missing or ambiguous identity."""
    from scipy.spatial.transform import Rotation
    result = {}
    for side in required_sides:
        data = {"missing_frames": [], "ambiguous_frames": [], "transitions": [],
                "suspicious_transitions": [], "training_ready": False}
        previous = None
        for row in sorted(rows, key=lambda r: r["frame_1based"]):
            hands = [h for h in row["hands"] if h["side"] == side]
            frame = row["frame_1based"]
            if len(hands) != 1:
                data["missing_frames" if not hands else "ambiguous_frames"].append(frame)
                previous = None
                continue
            current = hands[0]
            if previous is not None and frame == previous[0] + 1:
                old = previous[1]
                angle = Rotation.from_matrix(current["hand_pose"] @ old["hand_pose"].transpose(0, 2, 1)).magnitude()
                wrist = Rotation.from_matrix(current["global_orient"] @ old["global_orient"].transpose(0, 2, 1)).magnitude()
                pixel_step = float(np.linalg.norm(current["projected_joints"][0] - old["projected_joints"][0]))
                entry = {"from_frame": previous[0], "to_frame": frame,
                         "max_finger_degrees": float(np.rad2deg(angle.max())),
                         "wrist_orientation_degrees": float(np.rad2deg(wrist.max())),
                         "wrist_step_pixels": pixel_step}
                data["transitions"].append(entry)
                if entry["max_finger_degrees"] > 45 or entry["wrist_orientation_degrees"] > 30 or pixel_step > 40:
                    data["suspicious_transitions"].append(frame)
            previous = (frame, current)
        data["continuity_complete"] = not data["missing_frames"] and not data["ambiguous_frames"] and \
            len(data["transitions"]) == max(0, len(rows) - 1)
        result[side] = data
    return result


def sibling_hand_tool():
    path = Path(__file__).with_name("sign-hand-refine.py")
    spec = importlib.util.spec_from_file_location("sign_hand_refine_wilor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args):
    from PIL import Image, ImageDraw
    root, mano, batch = args.wilor_root.resolve(), args.mano_model.resolve(), args.batch.resolve()
    output = args.output.resolve()
    helper = sibling_hand_tool()
    window = getattr(args, "short_window", False)
    selected = helper.task_cases(batch, cases=short_window_cases() if window else None)
    require(not output.exists() and all(output != p and p not in output.parents and output not in p.parents
                                       for p in (root, batch, mano.parent)), "Output must be new and separate")
    output.mkdir(parents=True)
    report = {"schema": "signbridge-wilor-keyframe-pilot-v1", "status": "running",
              "created_at": datetime.now(timezone.utc).isoformat(), "training_ready": False,
              "deployment_ready": False, "training_started": False, "full_sequence_refined": False,
              "smplx_parameters_replaced": False,
              "scope": "frames 88-94 and 156-162, 14 images, no temporal smoothing" if window else
                       "frames 91 and 159, detector-driven hand estimates",
              "hand_pose_convention": "MANO rotation matrices, right-canonical prediction; image-space left mirror stored separately",
              "source_sha256": {}, "cases": []}
    path = output / "report.json"

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    save()
    stage = "input_assets"
    started = time.monotonic()
    try:
        actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        require(actual == COMMIT, "Wrong WiLoR source commit")
        check_source(root)
        report["wilor_commit"] = actual
        for name, (size, digest) in ASSETS.items():
            report["source_sha256"][str(root / name)] = check_asset(root / name, size, digest)
        report["source_sha256"][str(mano)] = check_asset(mano, MANO_BYTES, MANO_SHA)
        native_files = list(root.glob("wilor/**/*.py")) + [root / "pretrained_models/model_config.yaml",
            root / "mano_data/mano_mean_params.npz", Path(__file__).resolve(), Path(helper.__file__).resolve(),
            batch / "contract.json", batch / "tasks.jsonl", batch / "SHA256SUMS"]
        report["source_sha256"].update({str(p): sha256(p) for p in native_files})
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
        os.environ.setdefault("MPLBACKEND", "Agg")
        os.environ["YOLO_CONFIG_DIR"] = str(output / "yolo-settings")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        stage = "runtime_imports"
        import torch
        import cv2
        import ultralytics
        import pytorch_lightning
        import smplx
        import trimesh
        require(args.device != "cuda" or torch.cuda.is_available(), "Requested CUDA is unavailable")
        torch.set_num_threads(2)
        torch.manual_seed(20261009)
        device = torch.device(args.device)
        sys.path.insert(0, str(root))
        from wilor.models import WiLoR
        from wilor.configs import get_config
        from wilor.datasets.vitdet_dataset import ViTDetDataset
        from wilor.utils import recursive_to
        from wilor.utils.renderer import cam_crop_to_full
        from ultralytics import YOLO
        require(root in Path(sys.modules["wilor.models"].__file__).resolve().parents,
                "Wrong WiLoR package origin")
        cfg = get_config(str(root / "pretrained_models/model_config.yaml"), update_cachedir=False)
        cfg.defrost()
        cfg.MODEL.BBOX_SHAPE = [192, 256]
        cfg.MODEL.BACKBONE.pop("PRETRAINED_WEIGHTS", None)
        cfg.MANO.MODEL_PATH = str(mano)
        cfg.MANO.DATA_DIR = str(mano.parent)
        cfg.MANO.MEAN_PARAMS = str(root / "mano_data/mano_mean_params.npz")
        cfg.freeze()
        stage = "native_checkpoint_load"
        print("Loading native WiLoR and verified checkpoint; no training.", flush=True)
        model = WiLoR(cfg, init_renderer=False)
        checkpoint = torch.load(root / "pretrained_models/wilor_final.ckpt", map_location="cpu", weights_only=True)
        loaded = model.load_state_dict(checkpoint["state_dict"], strict=True)
        require(not loaded.missing_keys and not loaded.unexpected_keys, "Incomplete checkpoint load")
        del checkpoint
        gc.collect()
        model.requires_grad_(False).eval().to(device)
        detector = YOLO(str(root / "pretrained_models/detector.pt"))
        require(detector.names == {0: "left", 1: "right"}, "Unexpected detector handedness vocabulary")
        report["runtime"] = {"python": sys.version.split()[0], "torch": torch.__version__,
            "torchvision": __import__("torchvision").__version__, "ultralytics": ultralytics.__version__,
            "pytorch_lightning": pytorch_lightning.__version__, "smplx": getattr(smplx, "__version__", "0.1.28"),
            "device": str(device), "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None}
        report["checkpoint_strict_load_passed"] = True
        stage = "renderer_preflight"
        report["renderer_preflight"] = helper.renderer_preflight()
        for task, number, expected_sides, image_path, observations in selected:
            segment = task["segment_id"]
            folder = output / segment / ("%06d" % number) if window else output / segment
            folder.mkdir(parents=True)
            stage = "detector:" + segment
            image = cv2.imread(str(image_path))
            require(image is not None, "Cannot read frame image")
            height, width = image.shape[:2]
            source = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            source.save(folder / "original.jpg")
            report["source_sha256"].update({str(p): sha256(p) for p in (image_path, observations,
                                                    batch / task["frame_manifest"])})
            detections = detector.predict(image, conf=.3, device=str(device), verbose=False, max_det=6)[0]
            boxes = detections.boxes.xyxy.detach().cpu().numpy()
            classes = detections.boxes.cls.detach().cpu().numpy()
            confidences = detections.boxes.conf.detach().cpu().numpy()
            require(np.isfinite(boxes).all() and np.isfinite(confidences).all() and
                    np.isin(classes, [0, 1]).all() and (boxes[:, 2:] > boxes[:, :2]).all(),
                    "Invalid hand detector output")
            case = {"segment_id": segment, "frame_1based": number, "required_sides": list(expected_sides),
                    "output_relative": str(folder.relative_to(output)),
                    "detector_class_names": {str(k): str(v) for k, v in detector.names.items()},
                    "hands": [], "training_ready": False, "mirror_status": task["mirror_status"]}
            report["cases"].append(case)
            # Keep all detections visible/auditable; no hidden selection by target fit.
            dataset = ViTDetDataset(cfg, image, boxes, classes, rescale_factor=2., fp16=False)
            combined = np.asarray(source).copy()
            for index, crop in enumerate(torch.utils.data.DataLoader(dataset, batch_size=1, num_workers=0)):
                stage = "wilor_forward:" + segment
                crop = recursive_to(crop, device)
                with torch.inference_mode():
                    predicted = model(crop)
                    camera = predicted["pred_cam"].clone()
                    right = bool(int(crop["right"][0].item()))
                    camera[:, 1] *= 1 if right else -1
                    focal = float(cfg.EXTRA.FOCAL_LENGTH / cfg.MODEL.IMAGE_SIZE * max(width, height))
                    translation = cam_crop_to_full(camera, crop["box_center"].float(), crop["box_size"].float(),
                                                   crop["img_size"].float(), focal)[0].cpu().numpy()
                arrays = {"vertices": predicted["pred_vertices"][0].cpu().numpy(),
                          "joints": predicted["pred_keypoints_3d"][0].cpu().numpy(),
                          "global_orient": predicted["pred_mano_params"]["global_orient"][0].cpu().numpy(),
                          "hand_pose": predicted["pred_mano_params"]["hand_pose"][0].cpu().numpy(),
                          "betas": predicted["pred_mano_params"]["betas"][0].cpu().numpy(),
                          "camera_translation": translation}
                check_outputs(arrays)
                vertices, joints, faces = to_image_handedness(arrays["vertices"], arrays["joints"], model.mano.faces,
                                                            right)
                camera_vertices, camera_joints = vertices + translation, joints + translation
                points = project_full(camera_joints, focal, width, height)
                arrays.update(image_vertices=vertices, image_joints=joints, image_faces=faces,
                              projected_joints=points, detector_bbox=boxes[index],
                              detector_confidence=np.asarray(confidences[index]), right=np.asarray(right),
                              focal_length=np.asarray(focal), image_size=np.asarray([width, height]))
                name = ("right" if right else "left") + "-%02d" % index
                np.savez_compressed(folder / (name + ".npz"), **arrays)
                trimesh.Trimesh(vertices=vertices, faces=faces, process=False).export(folder / (name + ".obj"))
                stage = "render:" + segment
                camera_config = {"focal": np.asarray([focal, focal]), "princpt": np.asarray([width / 2, height / 2])}
                result = Image.fromarray(helper.render_overlay(np.asarray(source), camera_vertices, faces,
                                                               camera_config, diagnostic=True))
                render_check = check_render_projection(np.asarray(source), np.asarray(result), camera_vertices, focal)
                combined = helper.render_overlay(combined, camera_vertices, faces, camera_config, diagnostic=True)
                result.save(folder / (name + "-overlay.jpg"))
                low, high = points.min(axis=0), points.max(axis=0)
                center = np.rint((low + high) / 2).astype(int)
                radius = int(np.ceil(max(high - low) / 2 + 65))
                require(0 < radius < 2 * max(width, height), "Unreasonable hand review crop")
                box = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)
                panels = [p.crop(box).resize((480, 480)) for p in (source, result)]
                helper.save_comparison(folder / (name + "-compare.jpg"), panels,
                                       ["Original", "WiLoR - NOT approved"])
                record = {"side": "right" if right else "left", "detection_index": index,
                          "confidence": float(confidences[index]), "bbox": boxes[index].tolist(),
                          "numerical_outputs_passed": True, "pose_accepted_for_training": False,
                          **render_check,
                          "mesh_file": name + ".obj", "parameters_file": name + ".npz"}
                case["hands"].append(record)
                print(json.dumps({"frame": number, **record}), flush=True)
            found = {h["side"] for h in case["hands"]}
            case["required_hand_detection_passed"] = set(expected_sides) <= found
            Image.fromarray(combined).save(folder / "combined-overlay.jpg")
            marked = source.copy()
            drawer = ImageDraw.Draw(marked)
            for h in case["hands"]:
                drawer.rectangle(h["bbox"], outline="red", width=3)
                drawer.text((h["bbox"][0], max(0, h["bbox"][1] - 15)), h["side"], fill="red")
            marked.save(folder / "detector.jpg")
            save()
        stage = "source_recheck"
        if window:
            report["temporal_audit"] = {}
            for segment in sorted({c["segment_id"] for c in report["cases"]}):
                rows = []
                cases = [c for c in report["cases"] if c["segment_id"] == segment]
                for c in cases:
                    hands = []
                    for item in c["hands"]:
                        filename = output / c["output_relative"] / item["parameters_file"]
                        with np.load(filename, allow_pickle=False) as a:
                            hands.append({"side": item["side"], **{key: a[key].copy() for key in
                                         ("hand_pose", "global_orient", "projected_joints")}})
                    rows.append({"frame_1based": c["frame_1based"], "hands": hands})
                report["temporal_audit"][segment] = temporal_summary(rows, cases[0]["required_sides"])
        for name, digest in report["source_sha256"].items():
            require(sha256(name) == digest, "Source changed during inference: " + name)
        ready = all(c["required_hand_detection_passed"] for c in report["cases"])
        if window:
            ready = ready and all(s["continuity_complete"] for v in report["temporal_audit"].values()
                                  for s in v.values())
        report.update(status="inferred_pending_visual_review" if ready else "missing_required_hand",
                      elapsed_seconds=time.monotonic() - started, source_files_unchanged=True,
                      limitations=["Short windows only; temporal jumps flagged, no smoothing/contact/semantic acceptance" if window
                                   else "Two keyframes only; no temporal/contact/semantic acceptance",
                                   "Detector handedness follows official demo; mirror status still unknown",
                                   "MANO and SMPL-X rotations/cameras not retargeted or merged",
                                   "Native pose arrays are right-canonical rotation matrices, not axis angles",
                                   "No training run and no training-ready data promotion"])
        save()
        return 0 if ready else 2
    except Exception as exc:
        report.update(status="failed", error=str(exc), failure_stage=stage, traceback=traceback.format_exc())
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wilor-root", type=Path, required=True)
    parser.add_argument("--mano-model", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--short-window", action="store_true", help="Only frames 88-94 and 156-162; no smoothing")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
