#!/usr/bin/env python3
"""Collect immutable post-reconstruction exports using an existing SSH master.

Usage: python3 sign-smplx-post-transfer.py --export-root /remote/export \
    --output-root /local/bundle

The CLI polls until the source index says completed and every archive is verified.
It never starts a new SSH connection. Interrupted/failed runs can be rerun with
the same arguments; proven outputs are rehashed, never overwritten. Failures and
their staging directories remain available for inspection. Move conflicting old
data aside explicitly before retrying. transfer-report.json is the current proof;
transfer-journal.jsonl records progress and preserves failures across invocations.
Only transfer/verification is certified here, not motion quality or training use.
"""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import sys
from datetime import datetime, timezone


INDEX_SCHEMA = "signbridge-post-reconstruction-export-index-v1"
REPORT_SCHEMA = "signbridge-post-reconstruction-transfer-v1"
IDENTITY_FIELDS = (
    "key", "kind", "archive_name", "internal_manifest_name", "source_dir", "members",
    "extract_base", "source_root", "result_rel", "chunk", "attempt", "manifest_sha256",
    "report_sha256", "expected_files", "archive_sha256", "archive_bytes",
    "internal_manifest_sha256", "internal_files",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def relative_name(value, allow_dot=False):
    require(isinstance(value, str) and value and
            not any(ord(c) < 32 or ord(c) == 127 for c in value) and "\\" not in value,
            "Unsafe path: " + repr(value))
    if value == "." and allow_dot:
        return value
    parts = value.split("/")
    require(not value.startswith("/") and all(p not in ("", ".", "..") for p in parts)
            and re.match(r"^[A-Za-z]:", value) is None, "Unsafe path: " + repr(value))
    return value


def basename(value):
    relative_name(value)
    require("/" not in value, "Expected a single path member: " + value)
    return value


def safe_local(path):
    """Do not resolve away evidence of a symlink, including broken symlinks."""
    path = Path(os.path.abspath(path))
    for parent in (*reversed(path.parents), path):
        require(not parent.is_symlink(), "Local symlink is forbidden: " + str(parent))
    return path


def output_dirs(root):
    root = safe_local(root)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("archives", "results", ".staging"):
        safe_local(root / name).mkdir(exist_ok=True)
    return root


def sha256(path, allow_hardlinks=False):
    path = safe_local(path)
    require(path.is_file() and (allow_hardlinks or path.stat().st_nlink == 1),
            "Expected a regular unlinked file: " + str(path))
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def expected_hash(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            "Invalid expected SHA256")


def item_identity(item):
    return {key: item[key] for key in IDENTITY_FIELDS if key in item}


def validate_item(item):
    require(isinstance(item, dict), "Invalid index item")
    for key in ("key", "archive_name", "internal_manifest_name"):
        basename(item[key])
    require(item["archive_name"].endswith(".tar") and
            item["internal_manifest_name"].endswith(".internal.SHA256SUMS"),
            "Unexpected archive/manifest name")
    relative_name(item["extract_base"], allow_dot=True)
    members = item["members"]
    require(isinstance(members, list) and members and len(set(members)) == len(members),
            "Invalid/duplicate top members")
    for name in members:
        basename(name)
    require(item.get("status") in ("pending", "archiving", "complete", "failed"),
            "Unknown source item status")
    if item["status"] == "complete":
        for key in ("archive_sha256", "internal_manifest_sha256"):
            expected_hash(item[key])
        for key in ("archive_bytes", "internal_files"):
            require(type(item[key]) is int and item[key] >= 0, "Invalid size/count: " + key)
    if item.get("kind") == "attempt":
        require(members == [item["attempt"]] and
                item["result_rel"] == str(PurePosixPath(item["extract_base"]) / item["attempt"]) and
                item["source_root"] == item["source_dir"].rstrip("/") + "/" + item["attempt"],
                "Attempt source/result path identity differs")
        for key in ("manifest_sha256", "report_sha256"):
            expected_hash(item[key])


def parse_manifest(path):
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        require(len(line) > 66 and line[64:66] in ("  ", " *"),
                "Invalid internal manifest line")
        checksum, name = line[:64], relative_name(line[66:])
        expected_hash(checksum)
        require(name not in entries, "duplicate internal manifest path: " + name)
        entries[name] = checksum
    return entries


def inspect_archive(archive, entries, item):
    files, directories, seen, tops = {}, set(), set(), set()
    with tarfile.open(archive, "r:") as stream:
        for member in stream:
            name = relative_name(member.name.rstrip("/") if member.isdir() else member.name)
            require(name not in seen, "duplicate tar member: " + name)
            seen.add(name)
            top = name.split("/", 1)[0]
            require(top in item["members"], "Unexpected top member: " + name)
            tops.add(top)
            require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE)
                    and member.sparse is None, "Forbidden tar member type/link/special: " + name)
            require(set(member.pax_headers) <= {"path", "mtime", "atime", "ctime", "size"},
                    "Unsafe tar member extended attributes: " + name)
            if member.isdir():
                directories.add(name)
            else:
                files[name] = member.size
            directories.update(str(p) for p in PurePosixPath(name).parents if str(p) != ".")
    require(tops == set(item["members"]), "Missing allowed top member")
    require(set(files) == set(entries), "Archive regular file set differs from internal manifest")
    require(not set(files) & directories, "Conflicting file/directory member path")
    require(len(entries) == item["internal_files"], "Internal file count differs")
    if "expected_files" in item:
        require(len(entries) == item["expected_files"], "Expected file count differs")
    return files, directories


def verify_tree(root, item, entries, layout):
    files, directories = layout
    observed, observed_dirs, hashes, byte_count = set(), set(), {}, 0
    stack = [root / name for name in item["members"]]
    while stack:
        path = safe_local(stack.pop())
        name = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            observed_dirs.add(name)
            stack.extend(path.iterdir())
        else:
            require(stat.S_ISREG(mode) and name in entries, "Unexpected payload file/type: " + name)
            require(path.stat().st_size == files[name], "Payload file size differs: " + name)
            value = sha256(path)
            require(value == entries[name], "Payload SHA256 differs: " + name)
            hashes[name] = value
            observed.add(name)
            byte_count += files[name]
    require(observed == set(entries) and observed_dirs == directories,
            "Extracted file set/directory set differs")
    attempt_hashes = {}
    if item.get("kind") == "attempt":
        top = item["attempt"]
        for filename, field in (("SHA256SUMS", "manifest_sha256"), ("report.json", "report_sha256")):
            require(hashes.get(top + "/" + filename) == item[field], "Attempt SHA256 differs: " + filename)
            attempt_hashes[field] = item[field]
        original = parse_manifest(root / top / "SHA256SUMS")
        expected = {top + "/" + name: value for name, value in original.items()}
        require(expected == {name: value for name, value in entries.items() if name != top + "/SHA256SUMS"},
                "Attempt original manifest file set/digests differ")
    return {"verified_files": len(observed), "verified_bytes": byte_count,
            "verified_directories": len(observed_dirs), **attempt_hashes}


def extract_archive(archive, destination):
    native = shutil.which("bsdtar")
    if native:
        result = subprocess.run(
            [native, "-xf", str(archive), "-C", str(destination), "--no-same-owner",
             "--no-same-permissions", "--no-acls", "--no-xattrs", "--no-fflags"],
            capture_output=True, text=True, env={**os.environ, "COPYFILE_DISABLE": "1"},
        )
        require(result.returncode == 0, "Native extraction failed: " + result.stderr.strip())
        return "bsdtar"
    # The same already-validated headers are used without extractall or metadata restoration.
    with tarfile.open(archive, "r:") as stream:
        for member in stream:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 4 * 1024 * 1024)
    return "stdlib"


def collect_archive(item, output, source, previous=None):
    """Fetch, verify in a fresh stage, then publish without replacing old data."""
    validate_item(item)
    require(item["status"] == "complete", "Source archive is not complete")
    output = output_dirs(output)
    stage = Path(tempfile.mkdtemp(prefix=item["key"] + "-", dir=output / ".staging"))
    try:
        identity = item_identity(item)
        if previous is not None:
            require(previous.get("identity") == identity, "Existing proof identity differs")
        archive_paths = []
        reused = True
        for name, expected in ((item["archive_name"], item["archive_sha256"]),
                               (item["internal_manifest_name"], item["internal_manifest_sha256"])):
            saved = safe_local(output / "archives" / name)
            if saved.exists():
                path = saved
            else:
                require(previous is None, "Missing proven archive/manifest: " + name)
                reused = False
                path = stage / name
                source.fetch(name, path)
            # Prefetched archives can be hardlinked to an older verified bundle.
            # Read and rehash them in place; never replace, chmod, or unlink them.
            require(sha256(path, allow_hardlinks=True) == expected,
                    "Archive/internal manifest SHA256 differs: " + name)
            archive_paths.append(path)
        archive, manifest = archive_paths
        require(archive.stat().st_size == item["archive_bytes"], "Archive size differs")
        entries = parse_manifest(manifest)
        layout = inspect_archive(archive, entries, item)
        base = safe_local(output / "results" / item["extract_base"])
        if previous is not None:
            counts = verify_tree(base, item, entries, layout)
            method = previous.get("extractor", "unknown")
        else:
            for name in item["members"]:
                require(not os.path.lexists(base / name), "Refusing existing unproven output: " + str(base / name))
            extracted = stage / "extracted"
            extracted.mkdir()
            method = extract_archive(archive, extracted)
            counts = verify_tree(extracted, item, entries, layout)
            base.mkdir(parents=True, exist_ok=True)
            for name in item["members"]:
                require(not os.path.lexists(base / name), "Refusing existing output: " + str(base / name))
                os.rename(extracted / name, base / name)
        for path in archive_paths:
            saved = output / "archives" / path.name
            if path != saved:
                # Atomic and exclusive: link cannot replace a concurrent/old file.
                os.link(path, saved)
                path.unlink()
        proof = {"identity": identity, "archive_sha256": item["archive_sha256"],
                 "archive_bytes": item["archive_bytes"],
                 "internal_manifest_sha256": item["internal_manifest_sha256"],
                 "reverified": previous is not None, "reused_archive": reused,
                 "extractor": method, "verified_at": stamp(), **counts}
    except Exception as error:
        raise ValueError(str(error) + "; preserved stage: " + str(stage)) from error
    shutil.rmtree(stage)
    return proof


def validate_index(index, export_root, previous=None):
    require(isinstance(index, dict) and index.get("schema") == INDEX_SCHEMA,
            "Unsupported export index schema")
    require(index.get("export_root") == export_root, "Export root identity differs")
    require(index.get("status") in ("prepared", "pending", "running", "exporting", "archiving",
                                    "completed", "failed"), "Unknown source index status")
    require(isinstance(index.get("items"), list), "Invalid index items")
    keys, names, destinations = set(), set(), []
    for item in index["items"]:
        validate_item(item)
        require(item["key"] not in keys, "duplicate item key")
        keys.add(item["key"])
        for field in ("archive_name", "internal_manifest_name"):
            require(item[field] not in names, "duplicate archive/manifest name")
            names.add(item[field])
        for member in item["members"]:
            path = PurePosixPath(item["extract_base"]) / member
            require(all(path != old and path not in old.parents and old not in path.parents
                        for old in destinations), "Overlapping output member paths")
            destinations.append(path)
    if previous is not None:
        old_items = {item["key"]: item for item in previous["items"]}
        require(keys == set(old_items), "Source item set changed during transfer")
        for item in index["items"]:
            old = old_items[item["key"]]
            # Pending rows acquire completion hashes; their routing must not change.
            fields = IDENTITY_FIELDS if old["status"] == "complete" else IDENTITY_FIELDS[:-4]
            require(all(old.get(key) == item.get(key) for key in fields),
                    "Immutable source item identity changed: " + item["key"])
            require(old["status"] != "complete" or item["status"] == "complete",
                    "Completed source item regressed: " + item["key"])
    require(index["status"] != "completed" or all(item["status"] == "complete" for item in index["items"]),
            "Source completed index still contains pending/failed items")


def write_json(path, value):
    path = safe_local(path)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SshSource:
    """Read files over the existing authenticated master, with no fallback dial."""

    def __init__(self, args):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+", args.ssh_host), "Invalid SSH host")
        require(1 <= args.ssh_port <= 65535, "Invalid SSH port")
        require(args.export_root.startswith("/"), "Remote export root must be absolute")
        relative_name(args.export_root.lstrip("/"))
        require(args.ssh_control_path.startswith("/") and args.host_key_alias and
                not any(c in args.host_key_alias + args.ssh_control_path for c in "\r\n\x00"),
                "Invalid SSH control path/host key alias")
        self.export_root = args.export_root.rstrip("/")
        self.host = args.ssh_host
        self.command = ["ssh", "-F", "/dev/null", "-p", str(args.ssh_port)]
        for option in (
            "BatchMode=yes", "StrictHostKeyChecking=yes", "HostKeyAlias=" + args.host_key_alias,
            "ControlPath=" + args.ssh_control_path, "ControlMaster=no", "ProxyCommand=false",
            "PasswordAuthentication=no", "KbdInteractiveAuthentication=no", "PubkeyAuthentication=no",
            "HostbasedAuthentication=no", "GSSAPIAuthentication=no", "IdentityAgent=none", "IdentityFile=none",
        ):
            self.command.extend(["-o", option])
        result = subprocess.run([*self.command, "-O", "check", self.host], capture_output=True)
        require(result.returncode == 0, "Existing authenticated SSH master is unavailable")

    def fetch(self, name, destination):
        basename(name)
        command = "cat -- " + shlex.quote(self.export_root + "/" + name)
        with destination.open("wb") as stream:
            result = subprocess.run([*self.command, self.host, command], stdout=stream, stderr=subprocess.PIPE)
        require(result.returncode == 0, "SSH fetch failed for " + name + ": " +
                result.stderr.decode("utf-8", errors="replace").strip())


class Collector:
    def __init__(self, output, source, workers=2, poll_seconds=5):
        require(type(workers) is int and 1 <= workers <= 3, "workers must be between 1 and 3")
        require(math.isfinite(poll_seconds) and poll_seconds > 0, "poll-seconds must be positive and finite")
        self.output = output_dirs(output)
        self.source, self.workers, self.poll_seconds = source, workers, poll_seconds
        self.path = safe_local(self.output / "transfer-report.json")
        self.report = {"schema": REPORT_SCHEMA, "export_root": source.export_root,
                       "items": {}, "failures": [], "started_at": stamp()}
        if self.path.exists():
            self.report = json.loads(self.path.read_text(encoding="utf-8"))
            require(self.report.get("schema") == REPORT_SCHEMA and
                    self.report.get("export_root") == source.export_root, "Existing transfer report identity differs")
        for row in self.report["items"].values():
            row["status"] = "pending_reverification"
        self.report.update(status="running", source_status="unknown")
        self.index = None
        self.active, self.attempted, self.verified = {}, set(), set()
        self.local_failed = self.source_failed = False

    def event(self, event, **values):
        value = {"at": stamp(), "event": event, **values}
        path = safe_local(self.output / "transfer-journal.jsonl")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)

    def save(self):
        proofs = [self.report["items"][key]["proof"] for key in self.verified]
        self.report["counts"] = {"total": len(self.index["items"]) if self.index else 0,
                                 "verified": len(proofs), "files": sum(p["verified_files"] for p in proofs),
                                 "bytes": sum(p["verified_bytes"] for p in proofs)}
        self.report["updated_at"] = stamp()
        write_json(self.path, self.report)

    def failure(self, message, key=None, source=False):
        failure = {"at": stamp(), "scope": "source" if source else "local", "error": str(message)}
        if key is not None:
            failure["key"] = key
            row = self.report["items"].setdefault(key, {})
            row.update(status="source_failed" if source else "failed", error=str(message))
            self.verified.discard(key)
        self.report["failures"].append(failure)
        if source:
            self.source_failed = True
        else:
            self.local_failed = True
        self.event("failure", **failure)
        self.save()

    def poll(self):
        descriptor, name = tempfile.mkstemp(prefix="index-", suffix=".json", dir=self.output / ".staging")
        os.close(descriptor)
        path = Path(name)
        self.source.fetch("export-index.json", path)
        index = json.loads(path.read_text(encoding="utf-8"))
        validate_index(index, self.source.export_root, self.index)
        require(set(self.report["items"]) <= {row["key"] for row in index["items"]},
                "Source index dropped previously recorded items")
        old_status = self.report["source_status"]
        self.index = index
        self.report["source_status"] = index["status"]
        os.replace(path, safe_local(self.output / "export-index.json"))
        for item in index["items"]:
            self.report["items"].setdefault(item["key"], {"status": "pending"})
            if item["status"] == "failed":
                self.failure(item.get("error", "Source item failed"), item["key"], source=True)
        if index["status"] == "failed":
            self.failure(index.get("error", "Source export failed"), source=True)
        if old_status != index["status"]:
            self.event("source", status=index["status"], items=len(index["items"]))
        self.save()

    def harvest(self):
        for future in list(self.active):
            if not future.done():
                continue
            key = self.active.pop(future)
            try:
                proof = future.result()
                self.report["items"][key] = {"status": "verified", "proof": proof}
                self.verified.add(key)
                self.event("verified", key=key, files=proof["verified_files"], reverified=proof["reverified"])
                self.save()
            except Exception as error:
                self.failure(error, key)

    def finish(self, status):
        self.report["status"] = status
        self.save()
        self.event("finished", status=status, **self.report["counts"])
        return self.report

    def run(self):
        self.save()
        executor = ThreadPoolExecutor(max_workers=self.workers)
        next_poll = 0
        try:
            while True:
                self.harvest()
                terminal_source = self.index and self.index["status"] in ("completed", "failed")
                if time.monotonic() >= next_poll and not terminal_source and not self.local_failed and not self.source_failed:
                    try:
                        self.poll()
                    except Exception as error:
                        self.failure(error)
                    next_poll = time.monotonic() + self.poll_seconds
                if self.index:
                    for item in self.index["items"]:
                        key = item["key"]
                        if len(self.active) >= self.workers:
                            break
                        if item["status"] != "complete" or key in self.attempted:
                            continue
                        self.attempted.add(key)
                        previous = self.report["items"][key].get("proof")
                        future = executor.submit(collect_archive, item, self.output, self.source, previous)
                        self.active[future] = key
                if not self.active:
                    if self.local_failed:
                        return self.finish("failed")
                    if self.source_failed:
                        return self.finish("source_failed")
                    if self.index and self.index["status"] == "completed":
                        require(len(self.verified) == len(self.index["items"]), "Not all source items were verified")
                        return self.finish("completed")
                delay = max(0.001, next_poll - time.monotonic())
                if self.active:
                    # Source-terminal exports need no more polling; wake on each completed job.
                    wait(self.active, timeout=delay if not terminal_source else None, return_when=FIRST_COMPLETED)
                else:
                    time.sleep(delay)
        except KeyboardInterrupt:
            executor.shutdown(wait=True)
            self.harvest()
            return self.finish("interrupted")
        except Exception as error:
            executor.shutdown(wait=True)
            self.harvest()
            self.failure(error)
            return self.finish("failed")
        finally:
            executor.shutdown(wait=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--export-root", required=True)
    result.add_argument("--output-root", required=True, type=Path)
    result.add_argument("--ssh-host", default="root@connect.cqa1.seetacloud.com")
    result.add_argument("--ssh-port", default=37077, type=int)
    result.add_argument("--ssh-control-path", default="/tmp/signbridge-wordfit-37077.sock")
    result.add_argument("--host-key-alias", default="[connect.cqa1.seetacloud.com]:26919")
    result.add_argument("--workers", default=2, type=int, choices=(1, 2, 3))
    result.add_argument("--poll-seconds", default=5, type=float)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        require(math.isfinite(args.poll_seconds) and args.poll_seconds > 0,
                "poll-seconds must be positive and finite")
        source = SshSource(args)
        report = Collector(args.output_root, source, args.workers, args.poll_seconds).run()
        return {"completed": 0, "interrupted": 130}.get(report["status"], 1)
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
