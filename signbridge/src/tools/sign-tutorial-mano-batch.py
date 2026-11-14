"""Run pinned WiLoR/MANO inference over an evidence-bound tutorial keyframe batch."""
import argparse
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def load_sibling(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wilor = load_sibling("sign-wilor-pilot.py", "tutorial_batch_wilor")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def validate_manifest(manifest, root):
    if manifest.get("schema") != "signbridge-tutorial-smplerx-independent-frames-v2":
        raise ValueError("Unsupported tutorial batch schema")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 500 or manifest.get("frames") != len(cases):
        raise ValueError("Tutorial keyframe batch must contain 1-500 cases")
    ids, indices = set(), set()
    for expected_index, row in enumerate(cases, 1):
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.replace("-", "").replace("_", "").isalnum() or case_id in ids:
            raise ValueError("Invalid or duplicate tutorial case ID")
        ids.add(case_id)
        index = row.get("gpu_input_frame_1based")
        if type(index) is not int or index != expected_index or index in indices:
            raise ValueError("GPU input frame index must match ordered case position")
        indices.add(index)
        if row.get("training_ready") is not False or row.get("human_approved") is not False:
            raise ValueError("Tutorial data cannot be promoted by the inference batch")
        for key in ("image", "observations"):
            path = (root / row[key]).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                raise ValueError("Batch asset escaped the input root or is missing")
            if wilor.sha256(path) != row[key + "_sha256"]:
                raise ValueError("Batch asset digest changed: " + str(path))
    if indices != set(range(1, len(cases) + 1)):
        raise ValueError("GPU frame indices must be contiguous")
    return cases


def run(args):
    import gc
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from PIL import Image

    root, wilor_root, mano_root, out = [p.resolve() for p in (args.inputs, args.wilor_root, args.mano_root, args.output)]
    manifest_path = root / "manifest.json"
    manifest_digest = wilor.sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    cases = validate_manifest(manifest, root)
    if out.exists() or out in root.parents or root in out.parents or out in wilor_root.parents or wilor_root in out.parents:
        raise ValueError("Choose a fresh output directory separate from all inputs")
    if subprocess.check_output(["git", "-C", str(wilor_root), "rev-parse", "HEAD"], text=True).strip() != wilor.COMMIT:
        raise ValueError("WiLoR commit does not match the pinned source")
    wilor.check_source(wilor_root)
    for name, (size, digest) in wilor.ASSETS.items():
        wilor.check_asset(wilor_root / name, size, digest)
    mano_path = mano_root / "MANO_RIGHT.pkl"
    wilor.check_asset(mano_path, wilor.MANO_BYTES, wilor.MANO_SHA)
    out.mkdir(parents=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ["YOLO_CONFIG_DIR"] = str(out / "yolo-settings")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    report = {"schema": "signbridge-tutorial-mano-batch-v1", "status": "running",
              "created_at": datetime.now(timezone.utc).isoformat(), "manifest_sha256": manifest_digest,
              "cases_expected": len(cases), "cases_completed": 0, "mano_candidates": 0,
              "human_approved": False, "training_ready": False, "training_started": False,
              "smplx_parameters_created": False, "independent_frames_only": True, "cases": []}
    write = lambda: (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write()
    stage, started = "imports", time.monotonic()
    try:
        if not torch.cuda.is_available():
            raise ValueError("CUDA is required for the 400-frame WiLoR batch")
        torch.set_num_threads(2)
        torch.manual_seed(20261012)
        device = torch.device("cuda")
        sys.path.insert(0, str(wilor_root))
        from wilor.configs import get_config
        from wilor.datasets.vitdet_dataset import ViTDetDataset
        from wilor.models import WiLoR
        from wilor.utils import recursive_to
        from wilor.utils.renderer import cam_crop_to_full
        from ultralytics import YOLO

        cfg = get_config(str(wilor_root / "pretrained_models/model_config.yaml"), update_cachedir=False)
        cfg.defrost()
        cfg.MODEL.BBOX_SHAPE = [192, 256]
        cfg.MODEL.BACKBONE.pop("PRETRAINED_WEIGHTS", None)
        cfg.MANO.MODEL_PATH = str(mano_path)
        cfg.MANO.DATA_DIR = str(mano_root)
        cfg.MANO.MEAN_PARAMS = str(wilor_root / "mano_data/mano_mean_params.npz")
        cfg.freeze()
        model = WiLoR(cfg, init_renderer=False)
        checkpoint_path = wilor_root / "pretrained_models/wilor_final.ckpt"
        load_options = {"map_location": "cpu"}
        if "weights_only" in inspect.signature(torch.load).parameters:
            load_options["weights_only"] = True
        checkpoint = torch.load(checkpoint_path, **load_options)
        result = model.load_state_dict(checkpoint["state_dict"], strict=True)
        if result.missing_keys or result.unexpected_keys:
            raise ValueError("WiLoR strict checkpoint load failed")
        del checkpoint
        gc.collect()
        model.requires_grad_(False).eval().to(device)
        detector = YOLO(str(wilor_root / "pretrained_models/detector.pt"))
        if detector.names != {0: "left", 1: "right"}:
            raise ValueError("Unexpected detector side vocabulary")
        report.update(wilor_commit=wilor.COMMIT, checkpoint_strict_load_passed=True,
                      runtime={"python": sys.version.split()[0], "torch": torch.__version__,
                               "ultralytics": ultralytics.__version__, "cuda": torch.version.cuda,
                               "gpu": torch.cuda.get_device_name(0)})
        write()
        for index, case in enumerate(cases, 1):
            stage = "frame:%06d" % index
            image_path = root / case["image"]
            image = cv2.imread(str(image_path))
            if image is None:
                raise ValueError("Could not decode tutorial image: " + str(image_path))
            height, width = image.shape[:2]
            frame_dir = out / "frames" / case["case_id"]
            frame_dir.mkdir(parents=True)
            shutil.copy2(image_path, frame_dir / "original.jpg")
            detection = detector.predict(image, conf=.3, device="cuda", verbose=False, max_det=8)[0]
            boxes = detection.boxes.xyxy.detach().cpu().numpy()
            classes = detection.boxes.cls.detach().cpu().numpy()
            confidences = detection.boxes.conf.detach().cpu().numpy()
            if (not np.isfinite(boxes).all() or not np.isfinite(confidences).all() or
                    not np.isin(classes, [0, 1]).all() or len(boxes) > 8 or
                    (len(boxes) and not (boxes[:, 2:] > boxes[:, :2]).all())):
                raise ValueError("Invalid WiLoR detector output")
            record = {"gpu_input_frame_1based": index, "case_id": case["case_id"],
                      "annotation_id": case["annotation_id"], "label": case["label"],
                      "source_sha256": case["source_sha256"],
                      "source_reference_frame_1based": case.get("source_reference_frame_1based", case.get("frame_1based")),
                      "source_seconds_nominal": case["source_seconds_nominal"],
                      "image_sha256": case["image_sha256"], "detector_count": len(boxes),
                      "hands": [], "human_approved": False, "training_ready": False}
            report["cases"].append(record)
            if len(boxes):
                dataset = ViTDetDataset(cfg, image, boxes, classes, rescale_factor=2., fp16=False)
                loader = torch.utils.data.DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)
                for detection_index, batch in enumerate(loader):
                    double = [key for key, value in batch.items()
                              if isinstance(value, torch.Tensor) and value.dtype == torch.float64]
                    batch = {key: value.float() if key in double else value for key, value in batch.items()}
                    batch = recursive_to(batch, device)
                    with torch.inference_mode():
                        predicted = model(batch)
                        camera = predicted["pred_cam"].clone()
                        right = batch["right"].bool()
                        camera[:, 1] *= torch.where(right, 1., -1.)
                        focal = float(cfg.EXTRA.FOCAL_LENGTH / cfg.MODEL.IMAGE_SIZE * max(width, height))
                        translation = cam_crop_to_full(camera, batch["box_center"].float(),
                                                       batch["box_size"].float(), batch["img_size"].float(), focal).cpu().numpy()
                    for j in range(len(batch["right"])):
                        det_index = len(record["hands"])
                        is_right = bool(batch["right"][j].item())
                        arrays = {"vertices": predicted["pred_vertices"][j].detach().cpu().numpy(),
                                  "joints": predicted["pred_keypoints_3d"][j].detach().cpu().numpy(),
                                  "global_orient": predicted["pred_mano_params"]["global_orient"][j].detach().cpu().numpy(),
                                  "hand_pose": predicted["pred_mano_params"]["hand_pose"][j].detach().cpu().numpy(),
                                  "betas": predicted["pred_mano_params"]["betas"][j].detach().cpu().numpy(),
                                  "camera_translation": translation[j]}
                        wilor.check_outputs(arrays)
                        vertices, joints, faces = wilor.to_image_handedness(arrays["vertices"], arrays["joints"], model.mano.faces, is_right)
                        projected = wilor.project_full(joints + translation[j], focal, width, height)
                        slot_points = np.full((21, 2), np.nan, dtype=np.float32)
                        with np.load(root / case["observations"], allow_pickle=False) as observation:
                            side = "right" if is_right else "left"
                            if bool(observation[side + "_detected"]):
                                slot_points = observation[side].astype(np.float32)
                        params_path = frame_dir / ("hand-%02d.npz" % det_index)
                        np.savez_compressed(params_path, **arrays, image_vertices=vertices, image_joints=joints,
                                            image_faces=faces, projected_joints=projected,
                                            detector_bbox=boxes[det_index], detector_confidence=confidences[det_index],
                                            detector_right=np.asarray(is_right), focal_length=np.asarray(focal),
                                            image_size=np.asarray([width, height]), mediapipe_slot_xy=slot_points)
                        record["hands"].append({"side": side, "detector_confidence": float(confidences[det_index]),
                                                "parameters": str(params_path.relative_to(out)),
                                                "parameters_sha256": wilor.sha256(params_path),
                                                "training_ready": False, "anatomical_side_verified": False})
            record["case_complete"] = True
            report["cases_completed"] = index
            report["mano_candidates"] += len(record["hands"])
            write()
            if index % 25 == 0 or index == len(cases):
                print(json.dumps({"completed": index, "total": len(cases), "mano_candidates": report["mano_candidates"]}), flush=True)
        if wilor.sha256(manifest_path) != manifest_digest:
            raise ValueError("Tutorial input manifest changed during batch")
        report.update(status="mano_batch_completed_pending_smplerx_alignment", elapsed_seconds=time.monotonic()-started,
                      output_images=len(cases), training_started=False, smplx_parameters_created=False)
    except Exception as error:
        report.update(status="failed", failure_stage=stage, error=str(error), traceback=traceback.format_exc(),
                      elapsed_seconds=time.monotonic()-started)
        raise
    finally:
        write()
    files = sorted(path for path in out.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(wilor.sha256(path) + "  " + str(path.relative_to(out)) + "\n" for path in files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "wilor-root", "mano-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
