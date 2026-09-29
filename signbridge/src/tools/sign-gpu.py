"""Acquire official public reconstruction assets and stage a verified local GPU handoff."""

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sign_motion", HERE / "sign-motion.py")
motion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motion)
data = motion.data

DETECTOR_FILE = "pretrained_models/mmdet/faster_rcnn_r50_fpn_1x_coco_20200130-047c8118.pth"
CONFIG_FILE = "pretrained_models/mmdet/mmdet_faster_rcnn_r50_fpn_coco.py"
DETECTOR_SHA256 = "047c8118fc5ca88ba5ae1fab72f2cd6b070501fe3af2f3cba5cfa9a89b44b03e"
CONFIG_SHA256 = "bb2905aaf5ff6aa4ce75d9aa63070368a96e9add16e3baab28debdea7c064c48"
CONFIG_COMMIT = "7be5368f7891b3750d5e94f76987f5ffad2a9c66"
PUBLIC_ASSETS = (
    (CONFIG_FILE, "https://raw.githubusercontent.com/openxrlab/xrmocap/" + CONFIG_COMMIT +
     "/configs/modules/human_perception/mmdet_faster_rcnn_r50_fpn_coco.py", CONFIG_SHA256),
    (DETECTOR_FILE, "https://download.openmmlab.com/mmdetection/v2.0/faster_rcnn/"
     "faster_rcnn_r50_fpn_1x_coco/faster_rcnn_r50_fpn_1x_coco_20200130-047c8118.pth", DETECTOR_SHA256),
)
MODEL_REPO = "caizhongang/SMPLer-X"
MODEL_FILENAME = "smpler_x_h32_correct.pth.tar"


def checked_download(url, path, expected):
    path = Path(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Missing trusted SHA-256 for download")
    if path.is_file():
        if data.sha256_file(path) != expected:
            raise ValueError(f"Existing file has a different SHA-256: {path}")
        return "verified_existing"
    if path.exists():
        raise ValueError(f"Download target is not a regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    if partial.exists():
        raise ValueError(f"Partial download exists; inspect and remove before retrying: {partial}")
    try:
        with urllib.request.urlopen(url, timeout=60) as source, partial.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
        if data.sha256_file(partial) != expected:
            raise ValueError(f"Downloaded file SHA-256 mismatch: {path}")
        partial.rename(path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return "downloaded"


def model_metadata():
    url = f"https://huggingface.co/api/models/{MODEL_REPO}?blobs=true"
    with urllib.request.urlopen(url, timeout=40) as response:
        info = json.load(response)
    revision = info["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid Hugging Face repository revision")
    matches = [row for row in info["siblings"] if row.get("rfilename") == MODEL_FILENAME]
    if len(matches) != 1:
        raise ValueError("Corrected H32 checkpoint is absent or ambiguous")
    record = matches[0]
    expected = record.get("lfs", {}).get("oid")
    size = record.get("lfs", {}).get("size")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Hugging Face LFS metadata lacks the model SHA-256")
    if not isinstance(size, int) or size <= 0:
        raise ValueError("Hugging Face LFS metadata lacks the model size")
    return revision, expected, size


def get_revision(root):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def assets(args):
    root = args.smplerx_root.resolve()
    if get_revision(root) != motion.SMPLERX_COMMIT:
        raise ValueError("SMPLer-X source revision differs from pinned inference source")
    records = []
    for relative, url, expected in PUBLIC_ASSETS:
        path = root / relative
        state = checked_download(url, path, expected)
        records.append({"path": relative, "url": url, "sha256": expected, "state": state})
    if args.download_model:
        revision, expected, size = model_metadata()
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{revision}/{MODEL_FILENAME}"
        destination = root / "pretrained_models/smpler_x_h32.pth.tar"
        state = checked_download(url, destination, expected)
        if destination.stat().st_size != size:
            raise ValueError("Official model size differs from Hugging Face LFS metadata")
        records.append({"path": "pretrained_models/smpler_x_h32.pth.tar", "url": url,
                        "upstream_filename": MODEL_FILENAME, "revision": revision,
                        "sha256": expected, "bytes": size, "state": state})
    manifest = root / "pretrained_models/signbridge-public-assets.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        for old in previous.get("assets", []):
            if old["path"] not in {row["path"] for row in records}:
                records.append(old)
    data.write_json(manifest, {"schema": "signbridge-public-assets-v1", "assets": records})
    print(json.dumps({"manifest": str(manifest), "assets": records}, ensure_ascii=False))
    return 0


def verify_assets(root):
    manifest = root / "pretrained_models/signbridge-public-assets.json"
    if not manifest.is_file():
        raise ValueError("Missing public asset provenance; run assets before staging")
    info = json.loads(manifest.read_text())
    if info.get("schema") != "signbridge-public-assets-v1":
        raise ValueError("Unsupported public asset provenance")
    pinned = {CONFIG_FILE: CONFIG_SHA256, DETECTOR_FILE: DETECTOR_SHA256}
    for item in info["assets"]:
        if item["path"] in pinned and item["sha256"] != pinned[item["path"]]:
            raise ValueError(f"Unexpected official asset SHA-256: {item['path']}")
        path = motion.artifact(root, item["path"])
        if data.sha256_file(path) != item["sha256"]:
            raise ValueError(f"Public asset hash changed: {path}")
    model = root / "pretrained_models/smpler_x_h32.pth.tar"
    if model.exists() and "pretrained_models/smpler_x_h32.pth.tar" not in {item["path"] for item in info["assets"]}:
        raise ValueError("Model checkpoint lacks verified provenance")
    needed = {CONFIG_FILE, DETECTOR_FILE}
    if not needed.issubset({item["path"] for item in info["assets"]}):
        raise ValueError("Public detector asset provenance is incomplete")
    return info


def validate_source(batch, root):
    if batch == root or batch.is_relative_to(root) or root.is_relative_to(batch):
        raise ValueError("Source and batch must be separate directories")
    tasks = motion.verify_pack(batch)
    if get_revision(root) != motion.SMPLERX_COMMIT:
        raise ValueError("Unexpected SMPLer-X source revision")
    assets_info = verify_assets(root)
    return tasks, assets_info


def stage(args):
    batch, root = args.batch.resolve(), args.smplerx_root.resolve()
    tasks, assets_info = validate_source(batch, root)
    if any(ch.isspace() for ch in str(args.output.resolve())):
        raise ValueError("Stage path must not contain whitespace (upstream SMPLer-X cp)")
    output = motion.new_output(args.output, (batch, root))
    shutil.copytree(batch, output / "batch", symlinks=False)
    shutil.copytree(root, output / "SMPLer-X", symlinks=False,
                    ignore=shutil.ignore_patterns("*.part", "__pycache__", "*.pyc"))
    tools = output / "tools"
    tools.mkdir()
    for name in ("sign-data.py", "sign-motion.py", "sign-gpu.py"):
        shutil.copyfile(HERE / name, tools / name)
    data.write_json(output / "stage.json", {
        "schema": "signbridge-smplerx-stage-v1", "created_at": motion.now(),
        "smplerx_commit": motion.SMPLERX_COMMIT,
        "tasks_sha256": data.sha256_file(output / "batch/tasks.jsonl"),
        "samples": len(tasks), "frames": sum(t["frames"] for t in tasks),
        "public_assets": assets_info["assets"],
        "has_model_checkpoint": (output / "SMPLer-X/pretrained_models/smpler_x_h32.pth.tar").is_file(),
    })
    entries = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and not path.is_symlink():
            relative = path.relative_to(output).as_posix()
            entries.append(f"{data.sha256_file(path)}  {relative}\n")
    (output / "SHA256SUMS").write_text("".join(entries))
    verify(output)
    print(json.dumps({"stage": str(output), "samples": len(tasks),
                      "frames": sum(t["frames"] for t in tasks)}, ensure_ascii=False))
    return 0


def verify(output):
    output = Path(output).resolve()
    info = json.loads((output / "stage.json").read_text())
    if info.get("schema") != "signbridge-smplerx-stage-v1":
        raise ValueError("Unsupported GPU stage schema")
    root = output / "SMPLer-X"
    tasks, _ = validate_source(output / "batch", root)
    if len(tasks) != info["samples"] or sum(t["frames"] for t in tasks) != info["frames"]:
        raise ValueError("Staged batch metadata changed")
    if data.sha256_file(output / "batch/tasks.jsonl") != info["tasks_sha256"]:
        raise ValueError("Staged task hash changed")
    lines = (output / "SHA256SUMS").read_text().splitlines()
    if not lines:
        raise ValueError("Empty staged hash manifest")
    entries = set()
    for line in lines:
        checksum, relative = line.split("  ", 1)
        if relative in entries:
            raise ValueError("Repeated path in staged hash manifest")
        entries.add(relative)
        if data.sha256_file(motion.artifact(output, relative)) != checksum:
            raise ValueError(f"GPU stage hash changed: {relative}")
    observed = {path.relative_to(output).as_posix() for path in output.rglob("*")
                if path.is_file() and not path.is_symlink()} - {"SHA256SUMS"}
    if observed != entries:
        raise ValueError("Staged file inventory differs from SHA256SUMS")
    return {"samples": len(tasks), "frames": sum(t["frames"] for t in tasks),
            "files": len(entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    asset_command = commands.add_parser("assets", help="Download/verify official public assets")
    asset_command.add_argument("--smplerx-root", type=Path, required=True)
    asset_command.add_argument("--download-model", action="store_true", help="Fetch corrected H32 via LFS SHA-256")
    asset_command.set_defaults(action=assets)
    stage_command = commands.add_parser("stage", help="Create a local portable GPU handoff")
    stage_command.add_argument("--batch", type=Path, required=True)
    stage_command.add_argument("--smplerx-root", type=Path, required=True)
    stage_command.add_argument("--output", type=Path, required=True)
    stage_command.set_defaults(action=stage)
    verify_command = commands.add_parser("verify", help="Verify a staged handoff after moving it")
    verify_command.add_argument("--stage", type=Path, required=True)
    verify_command.set_defaults(action=lambda args: print(json.dumps(verify(args.stage))) or 0)
    args = parser.parse_args()
    try:
        return args.action(args)
    except (ValueError, OSError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
