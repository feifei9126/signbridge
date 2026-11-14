"""Local-only fixtures for the post-reconstruction transfer CLI."""

import contextlib
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "src/tools/sign-smplx-post-transfer.py"


def module(*features):
    if not TOOL.is_file():
        raise AssertionError("post-transfer tool is not implemented")
    spec = importlib.util.spec_from_file_location("post_transfer", TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    for feature in features:
        if not hasattr(result, feature):
            raise AssertionError(feature + " is not implemented")
    return result


def digest(value):
    return hashlib.sha256(value).hexdigest()


class LocalSource:
    """Only the remote byte-fetch boundary is replaced; verification stays real."""

    export_root = "/remote/export"

    def __init__(self, root):
        self.root = root
        self.fetched = []

    def fetch(self, name, destination):
        self.fetched.append(name)
        shutil.copyfile(self.root / name, destination)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.remote = self.root / "remote"
        self.remote.mkdir()
        self.output = self.root / "bundle"
        self.source = LocalSource(self.remote)

    def fixture(self, key="chunk-001", *, records=None, payload=None, manifest=None):
        top = key + "-attempt-1"
        payload = payload if payload is not None else {
            top + "/report.json": b'{"status":"done"}\n',
            top + "/fits/00001.npz": b"native pose bytes",
        }
        if records is None:
            records = [(top, "dir", b"")]
            records += [(name, "file", value) for name, value in payload.items()]
        archive_name = key + ".tar"
        archive = self.remote / archive_name
        with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as stream:
            for name, kind, value in records:
                member = tarfile.TarInfo(name)
                member.mode = 0o755 if kind == "dir" else 0o644
                if kind == "dir":
                    member.type = tarfile.DIRTYPE
                elif kind in ("sym", "hard"):
                    member.type = tarfile.SYMTYPE if kind == "sym" else tarfile.LNKTYPE
                    member.linkname = value.decode()
                elif kind == "fifo":
                    member.type = tarfile.FIFOTYPE
                else:
                    member.size = len(value)
                stream.addfile(member, io.BytesIO(value) if kind == "file" else None)
        manifest = manifest if manifest is not None else "".join(
            digest(value) + "  " + name + "\n" for name, value in sorted(payload.items())
        ).encode()
        manifest_name = key + ".internal.SHA256SUMS"
        (self.remote / manifest_name).write_bytes(manifest)
        return {
            "key": key, "kind": "historical-interrupted", "status": "complete",
            "source_dir": "/remote/attempts", "members": [top], "extract_base": "attempts",
            "archive_name": archive_name, "internal_manifest_name": manifest_name,
            "archive_sha256": digest(archive.read_bytes()), "archive_bytes": archive.stat().st_size,
            "internal_manifest_sha256": digest(manifest), "internal_files": len(payload),
        }

    def collect(self, item, proof=None):
        return module().collect_archive(item, self.output, self.source, proof)

    def index(self, items, status="completed"):
        value = {"schema": "signbridge-post-reconstruction-export-index-v1",
                 "status": status, "export_root": self.source.export_root, "items": items}
        (self.remote / "export-index.json").write_text(json.dumps(value))
        return value

    def test_valid_fresh_collection_hashes_files_and_publishes_top_member(self):
        item = self.fixture()
        proof = self.collect(item)
        self.assertEqual(proof["verified_files"], 2)
        self.assertEqual(proof["archive_sha256"], item["archive_sha256"])
        self.assertEqual(proof["internal_manifest_sha256"], item["internal_manifest_sha256"])
        self.assertFalse(proof["reverified"])
        self.assertEqual((self.output / "results/attempts/chunk-001-attempt-1/fits/00001.npz")
                         .read_bytes(), b"native pose bytes")
        for name in (item["archive_name"], item["internal_manifest_name"]):
            self.assertEqual((self.output / "archives" / name).read_bytes(),
                             (self.remote / name).read_bytes())

    def test_resume_rehashes_proven_files_and_preserves_inode_mtime_and_unrelated_output(self):
        item = self.fixture()
        proof = self.collect(item)
        path = self.output / "results/attempts/chunk-001-attempt-1/report.json"
        before = path.stat()
        unrelated = self.output / "results/unrelated.txt"
        unrelated.write_bytes(b"keep")
        self.source.fetched.clear()
        resumed = self.collect(item, proof)
        self.assertTrue(resumed["reverified"])
        self.assertEqual(self.source.fetched, [])
        self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))
        self.assertEqual(unrelated.read_bytes(), b"keep")
        path.write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "SHA256|size"):
            self.collect(item, resumed)
        self.assertEqual(path.read_bytes(), b"damaged")

    def test_existing_unproven_top_member_is_never_overwritten(self):
        item = self.fixture()
        existing = self.output / "results/attempts/chunk-001-attempt-1"
        existing.mkdir(parents=True)
        (existing / "keep").write_bytes(b"old evidence")
        with self.assertRaisesRegex(ValueError, "existing|unproven"):
            self.collect(item)
        self.assertEqual((existing / "keep").read_bytes(), b"old evidence")

    def test_rejects_absolute_traversal_and_ambiguous_member_paths(self):
        for name in ("/escape", "../escape", "chunk-001-attempt-1/../../escape",
                     "chunk-001-attempt-1/../escape", "C:/escape", "chunk-001-attempt-1\\evil",
                     "chunk-001-attempt-1//report.json"):
            with self.subTest(name=name):
                item = self.fixture(records=[(name, "file", b"evil")])
                with self.assertRaisesRegex(ValueError, "path|member"):
                    self.collect(item)
                self.assertFalse((self.root / "escape").exists())
        self.assertFalse((self.output / "results/attempts/chunk-001-attempt-1").exists())

    def test_rejects_symlink_hardlink_and_special_members_before_native_extraction(self):
        for kind in ("sym", "hard", "fifo"):
            with self.subTest(kind=kind):
                item = self.fixture(records=[("chunk-001-attempt-1/link", kind, b"/escape")])
                with patch.object(module().subprocess, "run", side_effect=AssertionError("extracted")):
                    with self.assertRaisesRegex(ValueError, "type|link|special"):
                        self.collect(item)

    def test_rejects_duplicate_tar_files_and_directories(self):
        for kind in ("file", "dir"):
            with self.subTest(kind=kind):
                name = "chunk-001-attempt-1/report.json"
                item = self.fixture(records=[(name, kind, b"one"), (name, kind, b"two")])
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    self.collect(item)

    def test_rejects_missing_and_unexpected_payload_files_and_unlisted_top_entries(self):
        for records in ([("chunk-001-attempt-1/report.json", "file", b'{"status":"done"}\n')],
                        [("chunk-001-attempt-1/extra", "file", b"extra")],
                        [("other/file", "file", b"escape scope")]):
            with self.subTest(records=records):
                item = self.fixture(records=records)
                with self.assertRaisesRegex(ValueError, "file set|member|top"):
                    self.collect(item)

    def test_rejects_duplicate_and_unsafe_internal_manifest_entries(self):
        good = digest(b"x") + "  chunk-001-attempt-1/report.json\n"
        for manifest in ((good + good).encode(), (digest(b"x") + "  ../escape\n").encode(),
                         b"not a checksum\n"):
            with self.subTest(manifest=manifest):
                item = self.fixture(manifest=manifest)
                with self.assertRaisesRegex(ValueError, "manifest|path|duplicate"):
                    self.collect(item)

    def test_rejects_corrupt_outer_hash_internal_hash_size_and_file_digest(self):
        for field in ("archive_sha256", "internal_manifest_sha256", "archive_bytes",
                      "internal_files", "payload"):
            with self.subTest(field=field):
                item = self.fixture(key=field)
                if field.endswith("sha256"):
                    item[field] = "0" * 64
                elif field in ("archive_bytes", "internal_files"):
                    item[field] += 1
                else:
                    manifest = self.remote / item["internal_manifest_name"]
                    manifest.write_text(manifest.read_text().replace(digest(b"native pose bytes"), "0" * 64))
                    item["internal_manifest_sha256"] = digest(manifest.read_bytes())
                with self.assertRaisesRegex(ValueError, "SHA256|size|count"):
                    self.collect(item)

    def test_attempt_binds_original_manifest_and_report_hashes(self):
        top = "chunk-001-attempt-1"
        source_manifest = (digest(b"pose") + "  fits/pose.npz\n" +
                           digest(b"report") + "  report.json\n").encode()
        item = self.fixture(payload={top + "/SHA256SUMS": source_manifest,
                                     top + "/report.json": b"report", top + "/fits/pose.npz": b"pose"})
        item.update(kind="attempt", chunk="chunk-001", attempt=top,
                    source_root="/remote/attempts/" + top, result_rel="attempts/" + top,
                    manifest_sha256=digest(source_manifest), report_sha256=digest(b"report"),
                    expected_files=3)
        proof = self.collect(item)
        self.assertEqual(proof["manifest_sha256"], item["manifest_sha256"])
        for field in ("manifest_sha256", "report_sha256"):
            changed = {**item, field: "0" * 64}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.collect(changed, proof)

    def test_symlinked_output_parent_cannot_redirect_writes(self):
        item = self.fixture()
        outside = self.root / "outside"
        outside.mkdir()
        self.output.mkdir()
        (self.output / "results").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.collect(item)
        self.assertEqual(list(outside.iterdir()), [])

    def test_matching_cached_archive_can_be_reused_without_trusting_old_results(self):
        item = self.fixture()
        archives = self.output / "archives"
        archives.mkdir(parents=True)
        shutil.copyfile(self.remote / item["archive_name"], archives / item["archive_name"])
        self.collect(item)
        self.assertNotIn(item["archive_name"], self.source.fetched)
        self.assertIn(item["internal_manifest_name"], self.source.fetched)

    def test_prefetched_hardlinked_archive_and_prefetch_record_are_preserved(self):
        item = self.fixture()
        archives = self.output / "archives"
        archives.mkdir(parents=True)
        cached = archives / item["archive_name"]
        import os
        os.link(self.remote / item["archive_name"], cached)
        before = cached.stat()
        prefetch = self.output / "prefetch-verification.json"
        prefetch.write_bytes(b'{"prefetched":true}\n')
        self.index([item])
        report = self.run_collector()
        self.assertEqual(report["status"], "completed")
        self.assertNotIn(item["archive_name"], self.source.fetched)
        self.assertIn(item["internal_manifest_name"], self.source.fetched)
        self.assertEqual((cached.stat().st_ino, cached.stat().st_mtime_ns, cached.stat().st_nlink),
                         (before.st_ino, before.st_mtime_ns, before.st_nlink))
        self.assertEqual(prefetch.read_bytes(), b'{"prefetched":true}\n')

    def test_cli_allows_three_workers_with_default_still_two(self):
        m = module()
        args = self.ssh_args(m)
        self.assertEqual(args.workers, 2)
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                args = m.parser().parse_args(["--export-root", self.source.export_root,
                    "--output-root", str(self.output), "--workers", "3"])
            except SystemExit:
                self.fail("CLI must allow the operator's requested three workers")
        self.index([self.fixture("chunk-00" + str(i)) for i in range(1, 4)])
        with contextlib.redirect_stdout(io.StringIO()):
            report = m.Collector(self.output, self.source, workers=args.workers, poll_seconds=0.01).run()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["counts"]["verified"], 3)

    def test_native_extraction_failure_preserves_downloads_without_publishing(self):
        item = self.fixture()
        m = module()
        with patch.object(m.shutil, "which", return_value="/native/bsdtar"), \
                patch.object(m.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr="disk full")):
            with self.assertRaisesRegex(ValueError, "disk full.*preserved stage"):
                m.collect_archive(item, self.output, self.source)
        self.assertFalse((self.output / "results/attempts/chunk-001-attempt-1").exists())
        self.assertEqual(len(list((self.output / ".staging").glob("*/chunk-001.tar"))), 1)

    def test_stdlib_fallback_uses_the_same_verification(self):
        item = self.fixture()
        m = module()
        with patch.object(m.shutil, "which", return_value=None):
            proof = m.collect_archive(item, self.output, self.source)
        self.assertEqual(proof["extractor"], "stdlib")
        self.assertEqual(proof["verified_files"], 2)

    def run_collector(self, m=None):
        m = m or module("Collector")
        with contextlib.redirect_stdout(io.StringIO()):
            return m.Collector(self.output, self.source, workers=2, poll_seconds=0.01).run()

    def test_collector_saves_final_index_report_counts_and_progress_journal(self):
        items = [self.fixture(), self.fixture("chunk-002")]
        index = self.index(items)
        report = self.run_collector()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["counts"], {"total": 2, "verified": 2, "files": 4,
                                           "bytes": sum(r["proof"]["verified_bytes"]
                                                        for r in report["items"].values())})
        self.assertEqual(json.loads((self.output / "export-index.json").read_text()), index)
        self.assertEqual(json.loads((self.output / "transfer-report.json").read_text()), report)
        events = [json.loads(line) for line in (self.output / "transfer-journal.jsonl").read_text().splitlines()]
        self.assertEqual(sum(event["event"] == "verified" for event in events), 2)
        resumed = self.run_collector()
        self.assertTrue(all(row["proof"]["reverified"] for row in resumed["items"].values()))

    def test_pending_source_is_never_complete_even_when_all_current_archives_are_verified(self):
        self.index([self.fixture()], "exporting")
        m = module("Collector", "time")
        with patch.object(m.time, "sleep", side_effect=KeyboardInterrupt):
            report = self.run_collector(m)
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["source_status"], "exporting")
        self.assertEqual(report["counts"]["verified"], 1)

    def test_pending_items_are_not_fetched_or_counted_as_verified(self):
        item = self.fixture()
        item["status"] = "pending"
        self.index([item], "prepared")
        m = module("Collector", "time")
        with patch.object(m.time, "sleep", side_effect=KeyboardInterrupt):
            report = self.run_collector(m)
        self.assertEqual(report["counts"]["verified"], 0)
        self.assertNotIn(item["archive_name"], self.source.fetched)
        self.assertNotEqual(report["status"], "completed")

    def test_source_failure_is_reported_and_complete_siblings_are_preserved(self):
        first, second = self.fixture(), self.fixture("chunk-002")
        second.update(status="failed", error="remote disk reserve insufficient")
        index = self.index([first, second], "failed")
        index["error"] = "export stopped"
        (self.remote / "export-index.json").write_text(json.dumps(index))
        report = self.run_collector()
        self.assertEqual(report["status"], "source_failed")
        self.assertEqual(report["items"][first["key"]]["status"], "verified")
        self.assertEqual(report["items"][second["key"]]["status"], "source_failed")
        self.assertIn("remote disk reserve", json.dumps(report["failures"]))
        self.assertNotIn(second["archive_name"], self.source.fetched)

    def test_completed_index_with_pending_item_and_item_failure_with_running_source_fail_closed(self):
        item = self.fixture()
        for source_status, item_status in (("completed", "pending"), ("exporting", "failed")):
            with self.subTest(source_status=source_status):
                item["status"] = item_status
                self.index([item], source_status)
                report = self.run_collector()
                self.assertIn(report["status"], ("failed", "source_failed"))
                self.assertEqual(report["counts"]["verified"], 0)

    def test_new_failures_are_appended_on_resume_and_failed_stages_are_retained(self):
        item = self.fixture()
        item["archive_sha256"] = "0" * 64
        self.index([item])
        first = self.run_collector()
        stages = set((self.output / ".staging").iterdir())
        second = self.run_collector()
        self.assertEqual(first["status"], "failed")
        self.assertEqual(second["status"], "failed")
        self.assertGreater(len(second["failures"]), len(first["failures"]))
        self.assertTrue(stages <= set((self.output / ".staging").iterdir()))

    def test_resume_corruption_clears_current_verification_but_keeps_previous_proof(self):
        item = self.fixture()
        self.index([item])
        self.run_collector()
        path = self.output / "results/attempts/chunk-001-attempt-1/report.json"
        path.write_bytes(b"bad")
        report = self.run_collector()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["counts"]["verified"], 0)
        self.assertEqual(report["items"][item["key"]]["status"], "failed")
        self.assertIn("proof", report["items"][item["key"]])
        self.assertEqual(path.read_bytes(), b"bad")

    def test_index_path_collisions_and_duplicate_archive_names_are_rejected(self):
        for change in ("key", "archive_name", "internal_manifest_name", "destination", "traversal"):
            with self.subTest(change=change):
                first, second = self.fixture(), self.fixture("chunk-002")
                if change == "destination":
                    second["members"] = first["members"]
                elif change == "traversal":
                    second["extract_base"] = "../outside"
                else:
                    second[change] = first[change]
                self.index([first, second])
                self.assertEqual(self.run_collector()["status"], "failed")
        self.assertFalse((self.output / "results/attempts/chunk-001-attempt-1").exists())

    def test_polls_while_two_transfers_are_inflight_and_never_exceeds_two_workers(self):
        items = [self.fixture("chunk-00" + str(i)) for i in range(1, 5)]
        self.index(items, "exporting")
        release, both, repolled = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        state = {"active": 0, "peak": 0, "polls": 0}
        fetch = self.source.fetch

        def blocking_fetch(name, destination):
            if name == "export-index.json":
                with lock:
                    state["polls"] += 1
                    if state["polls"] >= 2:
                        self.index(items, "completed")
                        repolled.set()
            if name.endswith(".tar"):
                with lock:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                    if state["active"] == 2:
                        both.set()
                if not release.wait(3):
                    raise AssertionError("test did not release blocked transfer")
                with lock:
                    state["active"] -= 1
            fetch(name, destination)

        self.source.fetch = blocking_fetch
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.run_collector)
            try:
                self.assertTrue(both.wait(2), "two archives did not overlap")
                self.assertTrue(repolled.wait(2), "index polling waited for archive completion")
                self.assertEqual(state["peak"], 2)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=3)["status"], "completed")

    def ssh_args(self, m):
        return m.parser().parse_args(["--export-root", self.source.export_root,
                                      "--output-root", str(self.output)])

    def test_ssh_transport_preserves_trust_and_can_only_reuse_the_existing_master(self):
        m = module("parser", "SshSource")
        args = self.ssh_args(m)
        self.assertEqual((args.ssh_host, args.ssh_port, args.ssh_control_path, args.host_key_alias,
                          args.workers, args.poll_seconds),
                         ("root@connect.cqa1.seetacloud.com", 37077,
                          "/tmp/signbridge-wordfit-37077.sock",
                          "[connect.cqa1.seetacloud.com]:26919", 2, 5))
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            if "stdout" in kwargs:
                kwargs["stdout"].write(b"remote bytes")
            return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

        with patch.object(m.subprocess, "run", side_effect=fake_run):
            source = m.SshSource(args)
            destination = self.root / "download"
            source.fetch("inputs.tar", destination)
        self.assertEqual(destination.read_bytes(), b"remote bytes")
        self.assertIn("-O", calls[0])
        self.assertIn("check", calls[0])
        for argv in calls:
            for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ControlMaster=no",
                           "HostKeyAlias=" + args.host_key_alias, "ProxyCommand=false",
                           "ControlPath=" + args.ssh_control_path, "IdentityAgent=none",
                           "IdentityFile=none", "PubkeyAuthentication=no"):
                self.assertIn(option, argv)
            self.assertEqual(argv[argv.index("-F") + 1], "/dev/null")
        self.assertEqual(calls[-1][-2:], [args.ssh_host, "cat -- /remote/export/inputs.tar"])

    def test_missing_ssh_master_fails_before_any_fetch(self):
        m = module("parser", "SshSource")
        with patch.object(m.subprocess, "run", return_value=SimpleNamespace(returncode=255, stderr=b"no master")) as run:
            with self.assertRaisesRegex(ValueError, "master"):
                m.SshSource(self.ssh_args(m))
        self.assertEqual(run.call_count, 1)

    def test_cli_completed_and_source_failed_exit_codes(self):
        m = module("main", "SshSource")
        self.index([self.fixture()])
        args = ["--export-root", self.source.export_root, "--output-root", str(self.output)]
        with patch.object(m, "SshSource", return_value=self.source), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(args), 0)
            self.index([], "failed")
            self.assertEqual(m.main(args), 1)


if __name__ == "__main__":
    unittest.main()
