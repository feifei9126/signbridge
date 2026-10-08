"""Mac launcher: upload only the hand tool, run an isolated GPU pilot, fetch evidence.

Uses standard-library Python and the user's SSH client. Credentials stay in SSH.
Normal run does not install dependencies. Only the explicit prepare-render command may
install the missing Ubuntu GLU runtime; no CUDA/Python upgrade, inference or training.
"""

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HOST = "root@connect.cqa1.seetacloud.com"
PORT = 22210
BASE = "/root/autodl-tmp/signbridge"
FITS = BASE + "/pilot-job-20261007-122150-DECIeP/fits"
FIT_SHA = "20f320c5bb3f4082e60d73b9f19ee3972a534785135f9098e34291f030526908"
PREFIX = BASE + "/hand-keyframe-pilot-"
REPO = Path(__file__).resolve().parents[3]


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path, info):
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def job_path(value):
    if not re.fullmatch(re.escape(PREFIX) + r"[0-9]{8}-[0-9]{6}-[A-Za-z0-9]{6}", value):
        raise ValueError("Unexpected remote job path; refusing to execute")
    return value


def driver(job):
    """No untrusted shell substitution: only a validated, newly created job path."""
    job = job_path(job)
    return """#!/usr/bin/env bash
set -uo pipefail
umask 077
JOB=%s
BASE=%s
printf '%%s\n' "$$" > "$JOB/driver.pid"
touch "$JOB/process-started"
exec 9>"$BASE/.hand-keyframe-pilot.lock"
if ! flock -n 9; then
  echo "Another hand pilot is running; no duplicate GPU task was started."
  RC=75
else
  export PYOPENGL_PLATFORM=egl MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
  cd "$JOB" || exit 70
  echo "Only frames 91 and 159; original fits remain unchanged; training_ready=false."
  if sha256sum -c tool.sha256; then
    "$BASE/envs/smplerx/bin/python" -u "$JOB/sign-hand-refine.py" pilot \\
      --batch "$BASE/sign-language-gpu-stage-v2/batch" \\
      --fits %s \\
      --smplerx-root "$BASE/sign-language-gpu-stage-v2/SMPLer-X" \\
      --fit-run-sha256 %s --max-nfev 120 --output "$JOB/results"
    RC=$?
  else
    RC=74
  fi
fi
printf '%%s\\n' "$RC" > "$JOB/exit-code"
echo "Hand pilot exit code: $RC; NOT training-ready."
# Finalize a small evidence archive even when the numerical gate/renderer failed.
cd "$JOB" || exit 70
FILES=(driver.log exit-code driver.pid process-started run.sh sign-hand-refine.py tool.sha256)
if [ -d results ]; then FILES+=(results); fi
{ for f in "${FILES[@]}"; do
    if [ -d "$f" ]; then find "$f" -type f -print0; else printf '%%s\\0' "$f"; fi
  done; } | sort -z | xargs -0 sha256sum > SHA256SUMS
# No more writes to driver.log after hashing it.
tar -czf return.tar.gz.tmp SHA256SUMS "${FILES[@]}"
PACK_RC=$?
if [ "$PACK_RC" -eq 0 ]; then
  mv return.tar.gz.tmp return.tar.gz
  sha256sum return.tar.gz > return.tar.gz.sha256
  touch archive-ready
else
  touch archive-failed
fi
exit "$RC"
""" % (shlex.quote(job), shlex.quote(BASE), shlex.quote(FITS), shlex.quote(FIT_SHA))


class Connection:
    def __init__(self, directory):
        # Short socket path (Unix-domain sockets have strict platform length limits).
        self.socket = str(directory / "ssh")
        self.options = ["-o", "ControlMaster=auto", "-o", "ControlPersist=600",
                        "-o", "ControlPath=" + self.socket, "-o", "ConnectTimeout=20",
                        "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"]

    def ssh(self, command, capture=True):
        return subprocess.run(["ssh", *self.options, "-p", str(PORT), HOST, command], check=True,
                              text=True, stdout=subprocess.PIPE if capture else None).stdout

    def copy(self, source, destination):
        subprocess.run(["scp", *self.options, "-P", str(PORT), source, destination], check=True)

    def close(self):
        subprocess.run(["ssh", "-S", self.socket, "-p", str(PORT), "-O", "exit", HOST],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def load_state(path):
    info = json.loads(path.read_text())
    job_path(info["remote_job"])
    if (info.get("schema") != "signbridge-hand-pilot-launch-v1" or
            info.get("host") != HOST or info.get("port") != PORT or info.get("fits") != FITS or
            info.get("fit_run_sha256") != FIT_SHA or info.get("training_ready") is not False or
            info.get("launch_phase", "legacy") not in ("legacy", "prepared", "uploading", "uploaded", "dispatching", "dispatched") or
            not re.fullmatch(r"[0-9a-f]{64}", info.get("tool_sha256", ""))):
        raise ValueError("Unexpected hand pilot state")
    return info


def status_probe(job):
    """Distinguish a live job from an interrupted upload/dispatch; never auto-restart."""
    return """JOB=%s
if [ ! -d "$JOB" ]; then
  echo missing-job
elif [ -f "$JOB/archive-ready" ]; then
  echo finished
elif [ -f "$JOB/archive-failed" ]; then
  echo archive-failed
elif [ -f "$JOB/process-started" ] && [ -f "$JOB/driver.pid" ]; then
  read -r PID < "$JOB/driver.pid"
  if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
    if [ -f "$JOB/exit-code" ]; then echo finalizing; else echo running; fi
  else
    echo stopped-without-archive
  fi
else
  echo not-started-or-dispatch-unconfirmed
fi
""" % shlex.quote(job_path(job))


def remote_status(connection, job):
    status = connection.ssh("bash -c " + shlex.quote(status_probe(job))).strip()
    if status not in ("finished", "running", "finalizing", "archive-failed", "missing-job",
                      "stopped-without-archive", "not-started-or-dispatch-unconfirmed"):
        raise ValueError("Unexpected remote job status: " + status)
    return status


def remote_exit_code(connection, job):
    value = connection.ssh("if [ -f " + shlex.quote(job_path(job) + "/exit-code") +
                           " ]; then cat " + shlex.quote(job_path(job) + "/exit-code") +
                           "; else echo unknown; fi").strip()
    if value == "unknown":
        return None
    if not re.fullmatch(r"-?[0-9]+", value):
        raise ValueError("Unexpected remote exit code: " + value)
    return int(value)


def wait_for_archive(connection, job, seconds):
    iterations = max(1, seconds // 5)
    command = """probe() {
%s
}
for ((i=0;i<%d;i++)); do
  STATUS=$(probe)
  if [ "$STATUS" = finished ]; then printf 'ready\n'; exit 0; fi
  if [[ "$STATUS" = archive-failed || "$STATUS" = missing-job || "$STATUS" = stopped-without-archive ]]; then
    echo "Pilot cannot finish automatically: $STATUS; use status for logs. No restart attempted." >&2
    exit 74
  fi
  # Allow dispatch startup time, but do not wait forever after a failed upload/nohup.
  if [ "$STATUS" = not-started-or-dispatch-unconfirmed ] && [ "$i" -ge 3 ]; then
    echo "Pilot startup unconfirmed; use status. Do not launch a duplicate." >&2
    exit 74
  fi
  sleep 5
done
printf 'running-or-archive-pending\n'
""" % (status_probe(job), iterations)
    return connection.ssh("bash -c " + shlex.quote(command)).strip() == "ready"


def extract_verified(archive, checksum, destination):
    """Reject tar links/traversal/duplicate paths; verify every regular file."""
    line = checksum.read_text().strip()
    expected, name = line.split("  ", 1)
    if name != "return.tar.gz" or not re.fullmatch(r"[0-9a-f]{64}", expected) or expected != digest(archive):
        raise ValueError("Evidence archive checksum mismatch")
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        names = set()
        size = 0
        for member in members:
            path = Path(member.name)
            target = (destination / path).resolve()
            if (member.name in names or path.is_absolute() or ".." in path.parts or
                    destination.resolve() not in target.parents or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe/duplicate evidence archive path: " + member.name)
            names.add(member.name)
            size += member.size
        if len(members) > 100 or size > 100 * 1024 * 1024:
            raise ValueError("Evidence archive exceeds key-frame pilot limits")
        destination.mkdir(exist_ok=False)
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as source, target.open("xb") as output:
                    output.write(source.read())
    manifest = destination / "SHA256SUMS"
    recorded = set()
    for line in manifest.read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = (destination / name).resolve()
        if (name in recorded or not re.fullmatch(r"[0-9a-f]{64}", expected) or destination.resolve() not in path.parents or
                not path.is_file() or expected != digest(path)):
            raise ValueError("Evidence file checksum mismatch: " + name)
        recorded.add(name)
    actual = {str(p.relative_to(destination)) for p in destination.rglob("*")
              if p.is_file() and p != manifest}
    if recorded != actual:
        raise ValueError("Evidence manifest missing/extra files")
    return destination


def prepare_render(connection):
    """Explicit, bounded OS-library repair; never start a fitting job."""
    code = '''import ctypes
import ctypes.util
path = ctypes.util.find_library("GLU")
if not path:
    raise RuntimeError("libGLU.so.1 is still unavailable")
ctypes.CDLL(path)
import pyrender
from OpenGL import platform
if type(platform.PLATFORM).__name__ != "EGLPlatform":
    raise RuntimeError("Expected EGLPlatform")
print("GLU:", path)
print("pyrender import and EGL backend selection passed; actual rendering is checked before fitting.")
'''
    command = r'''set -eu
if ! ldconfig -p | grep -q 'libGLU.so.1'; then
  export DEBIAN_FRONTEND=noninteractive LC_ALL=C
  apt-get update
  PLAN=$(apt-get -s --no-install-recommends --no-upgrade --no-remove install libglu1-mesa)
  printf '%%s\n' "$PLAN"
  if printf '%%s\n' "$PLAN" | awk '
    $1 == "Remv" { unsafe = 1 }
    $1 == "Inst" {
      package = $2; sub(/:.*/, "", package)
      if ((package != "libglu1-mesa" && package != "libopengl0") || $3 ~ /^\[/) unsafe = 1
    }
    END { exit !unsafe }'; then
    echo 'Refusing changes outside new GLU/OpenGL runtime libraries; no packages installed.' >&2
    exit 78
  fi
  apt-get install -y --no-install-recommends --no-upgrade --no-remove libglu1-mesa
fi
PYOPENGL_PLATFORM=egl MPLBACKEND=Agg %s -c %s
''' % (shlex.quote(BASE + "/envs/smplerx/bin/python"), shlex.quote(code))
    print("仅检查 GLU；缺失时安装 libglu1-mesa，不升级 CUDA/Python、不启动试修。", flush=True)
    connection.ssh("bash -c " + shlex.quote(command), capture=False)


def collect(connection, state, directory):
    job = job_path(state["remote_job"])
    folder = Path(tempfile.mkdtemp(prefix="download-", dir=directory))
    for name in ("return.tar.gz", "return.tar.gz.sha256"):
        connection.copy(HOST + ":" + job + "/" + name, str(folder / name))
    results = extract_verified(folder / "return.tar.gz", folder / "return.tar.gz.sha256", folder / "verified")
    if digest(results / "sign-hand-refine.py") != state["tool_sha256"]:
        raise ValueError("Returned tool differs from the tool selected at launch")
    print("下载与校验完成：" + str(results), flush=True)
    print("服务器日志：" + str(results / "driver.log"), flush=True)
    exit_code = int((results / "exit-code").read_text().strip())
    report = results / "results/report.json"
    if report.is_file():
        info = json.loads(report.read_text())
        if (info.get("schema") != "signbridge-hand-keyframe-pilot-v1" or
                info.get("training_ready") is not False or info.get("full_sequence_refined") is not False):
            raise ValueError("Unexpected pilot report/training-ready claim")
        print("试修状态：" + info["status"], flush=True)
        if info.get("error"):
            print("失败原因：" + str(info["error"]), flush=True)
            print("失败阶段：" + str(info.get("failure_stage", "旧报告未记录，请查看日志")), flush=True)
        for case in info.get("cases", []):
            if case.get("segment_id") not in ("pilot-greeting-hello-001", "pilot-hospital-cough-003"):
                raise ValueError("Unexpected evidence segment")
            for side in case.get("observed_hands", []):
                if side not in ("left", "right"):
                    raise ValueError("Unexpected evidence hand side")
                image = results / "results" / case["segment_id"] / (side + "-hand-compare.jpg")
                if image.is_file():
                    print("手部 A/B 对比：" + str(image), flush=True)
        if exit_code == 0 and info["status"] != "keyframe_candidates_pending_visual_review":
            raise ValueError("Exit code/report status disagree")
    elif exit_code == 0:
        raise ValueError("Successful process has no audit report")
    if exit_code == 0:
        print("本次只产生关键帧候选，整段视频尚未修正，尚未开始训练。", flush=True)
    else:
        print("试修未完成；已保存的局部结果不能视为完整修正，尚未开始训练。", flush=True)
    return 0 if exit_code == 0 else 2


def launch(connection, directory):
    tool = Path(__file__).with_name("sign-hand-refine.py")
    if not tool.is_file():
        raise ValueError("Missing hand refinement tool")
    latest = directory / "latest.json"
    if latest.is_file():
        previous = load_state(latest)
        job = previous["remote_job"]
        status = remote_status(connection, job)
        if status in ("running", "finalizing"):
            print("已有未完成/待打包的试修，复用状态，不重复启动：" + job, flush=True)
            return previous
        if status == "finished":
            previous_exit = remote_exit_code(connection, job)
            current_tool_sha = digest(tool)
            if previous_exit is not None and previous_exit != 0 and previous.get("tool_sha256") != current_tool_sha:
                print("上一轮试修已失败，检测到工具已更新；将创建新的隔离试修，不覆盖旧证据。", flush=True)
            else:
                raise ValueError("A prior pilot already exists. Use collect/status; do not silently repeat GPU work")
        else:
            raise ValueError("已有试修记录，但任务未确认启动或已中断：" + status +
                             "；请用 status 检查。为防重复，不自动重启。状态文件：" + str(latest))
    # Prefix and date command are fixed constants; validate returned data before any use.
    remote = connection.ssh("test -d " + shlex.quote(BASE) + " && umask 077 && mktemp -d " +
                            PREFIX + '"$(date +%Y%m%d-%H%M%S)"-XXXXXX').strip()
    job = job_path(remote)
    local = directory / Path(job).name
    local.mkdir(exist_ok=False)
    state = {"schema": "signbridge-hand-pilot-launch-v1", "remote_job": job, "host": HOST, "port": PORT,
             "fits": FITS, "fit_run_sha256": FIT_SHA, "tool_sha256": digest(tool), "training_ready": False,
             "launch_phase": "prepared"}
    def save(phase):
        state["launch_phase"] = phase
        write_json(local / "state.json", state)
        write_json(directory / "latest.json", state)
    save("prepared")
    (local / "run.sh").write_text(driver(job))
    (local / "tool.sha256").write_text(digest(tool) + "  sign-hand-refine.py\n")
    try:
        save("uploading")
        for source in (tool, local / "run.sh", local / "tool.sha256"):
            connection.copy(str(source), HOST + ":" + job + "/" + source.name)
        save("uploaded")
        save("dispatching")
        connection.ssh("nohup bash " + shlex.quote(job + "/run.sh") + " > " +
                       shlex.quote(job + "/driver.log") + " 2>&1 < /dev/null &")
        save("dispatched")
    except (OSError, subprocess.CalledProcessError) as exc:
        state["launch_error"] = str(exc)
        save(state["launch_phase"])
        raise ValueError("上传/启动未确认完成，已保留状态；不自动重启。请用 status 检查：" +
                         str(local / "state.json")) from exc
    print("已提交服务器后台试修，请以服务器状态和报告确认实际运行：" + job, flush=True)
    print("状态记录：" + str(local / "state.json"), flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "collect", "status", "plan", "prepare-render"), nargs="?", default="run")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--wait-seconds", type=int, default=300, choices=range(5, 901), metavar="5..900")
    args = parser.parse_args()
    directory = REPO / "local-data/hand-keyframe-runs"
    if args.command == "plan":
        print(json.dumps({"host": HOST, "port": PORT, "fits": FITS, "fit_run_sha256": FIT_SHA,
                          "frames_1based": [91, 159], "hands": 3, "training_ready": False,
                          "dependency_changes": False, "neural_inference": False}, indent=2))
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sbh-", dir="/tmp") as temporary:
        connection = Connection(Path(temporary))
        try:
            if args.command == "prepare-render":
                prepare_render(connection)
                print("GLU 加载与 pyrender 导入检查通过；实际离屏渲染将在试修前检查。", flush=True)
                return 0
            if args.command == "run":
                state = launch(connection, directory)
            else:
                state = load_state(args.state or directory / "latest.json")
            job = state["remote_job"]
            if args.command == "status":
                print("上传/启动阶段：" + state.get("launch_phase", "legacy"), flush=True)
                print("服务器状态：" + remote_status(connection, job), flush=True)
                connection.ssh("if [ -f " + shlex.quote(job + "/exit-code") + " ]; then cat " +
                               shlex.quote(job + "/exit-code") + "; fi; if [ -f " +
                               shlex.quote(job + "/driver.log") + " ]; then tail -n 30 " +
                               shlex.quote(job + "/driver.log") + "; else echo '日志尚未创建，未确认启动'; fi",
                               capture=False)
                return 0
            print("等待关键帧拟合和原生 A/B 渲染；密码仅由 SSH 在当前终端读取。", flush=True)
            if wait_for_archive(connection, job, args.wait_seconds):
                return collect(connection, state, directory)
            print("任务/打包尚未结束，后台任务不会因本命令退出而停止，请勿重复运行 run。", flush=True)
            print("稍后将命令末尾的 run 替换为 collect 下载；替换为 status 查看日志。", flush=True)
            return 0
        finally:
            connection.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print("未宣称修正成功：" + str(exc), file=sys.stderr)
        sys.exit(2)
