"""Offline launcher tests: no network, password, GPU or actual user data."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-hand-pilot.py"
spec = importlib.util.spec_from_file_location("sign_hand_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class HandPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = pilot.PREFIX + "20261007-160000-Ab1c23"

    def archive(self, files, extra_member=None):
        archive = self.root / "return.tar.gz"
        manifest = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n" for name, data in files.items())
        with tarfile.open(archive, "w:gz") as stream:
            for name, data in {**files, "SHA256SUMS": manifest.encode()}.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
            if extra_member:
                stream.addfile(extra_member)
        checksum = self.root / "return.tar.gz.sha256"
        checksum.write_text(pilot.digest(archive) + "  return.tar.gz\n")
        return archive, checksum

    def state(self):
        return {"schema": "signbridge-hand-pilot-launch-v1", "remote_job": self.job, "host": pilot.HOST,
                "port": pilot.PORT, "fits": pilot.FITS, "fit_run_sha256": pilot.FIT_SHA,
                "tool_sha256": "a" * 64, "training_ready": False}

    def test_fixed_scope_and_generated_shell_are_valid(self):
        script = pilot.driver(self.job)
        path = self.root / "run.sh"
        path.write_text(script)
        subprocess.run(["bash", "-n", str(path)], check=True)
        self.assertIn("flock -n", script)
        self.assertIn("--max-nfev 120", script)
        self.assertIn(pilot.FIT_SHA, script)
        self.assertIn("archive-ready", script)
        self.assertNotIn("pip install", script)
        self.assertNotIn("inference.py", script)
        self.assertNotIn("train.py", script)
        self.assertNotIn("rm -", script)

    def test_driver_packages_logs_and_evidence_after_gpu_failure(self):
        # Substitute only paths in the already-validated template, never execute GPU work.
        base = self.root / "remote"
        job = base / "job"
        job.mkdir(parents=True)
        python = base / "envs/smplerx/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/usr/bin/env bash\necho 'synthetic GPU failure'\nexit 2\n")
        python.chmod(0o700)
        tool = job / "sign-hand-refine.py"
        tool.write_text("# mock tool; not real GPU work\n")
        (job / "tool.sha256").write_text(pilot.digest(tool) + "  sign-hand-refine.py\n")
        # macOS lacks util-linux flock; this fixture tests packaging, not locking.
        commands = self.root / "commands"
        commands.mkdir()
        flock = commands / "flock"
        flock.write_text("#!/usr/bin/env bash\nexit 0\n")
        flock.chmod(0o700)
        script = pilot.driver(self.job).replace(self.job, str(job)).replace(pilot.BASE, str(base))
        path = job / "run.sh"
        path.write_text(script)
        with (job / "driver.log").open("w") as log:
            result = subprocess.run(["bash", str(path)], stdout=log, stderr=subprocess.STDOUT, check=False,
                                    env={**os.environ, "PATH": str(commands) + ":" + os.environ["PATH"],
                                         "COPYFILE_DISABLE": "1"})
        self.assertEqual(result.returncode, 2)
        self.assertTrue((job / "archive-ready").is_file())
        output = self.root / "download"
        pilot.extract_verified(job / "return.tar.gz", job / "return.tar.gz.sha256", output)
        self.assertEqual((output / "exit-code").read_text(), "2\n")
        self.assertIn("synthetic GPU failure", (output / "driver.log").read_text())

    def test_unsafe_remote_job_and_tampered_state_are_rejected(self):
        for name in (self.job + "; echo bad", "/tmp/other", self.job + "/../", "$(id)"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pilot.driver(name)
        path = self.root / "state.json"
        state = self.state()
        pilot.write_json(path, state)
        self.assertEqual(pilot.load_state(path), state)
        for patch_values in ({"host": "root@evil"}, {"port": 22}, {"training_ready": True},
                             {"fits": "/tmp/fake"}, {"tool_sha256": "bad"}, {"fit_run_sha256": "a" * 64},
                             {"launch_phase": "pretend-success"}):
            pilot.write_json(path, {**state, **patch_values})
            with self.assertRaises(ValueError):
                pilot.load_state(path)

    def test_archive_every_file_hashes_and_destination_not_overwritten(self):
        archive, checksum = self.archive({"driver.log": b"example", "exit-code": b"2\n",
                                          "results/report.json": b'{"training_ready":false}'})
        destination = self.root / "verified"
        pilot.extract_verified(archive, checksum, destination)
        self.assertEqual((destination / "exit-code").read_text(), "2\n")
        with self.assertRaises(FileExistsError):
            pilot.extract_verified(archive, checksum, destination)
        archive.write_bytes(archive.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            pilot.extract_verified(archive, checksum, self.root / "second")

    def test_archive_links_traversal_duplicates_and_oversize_are_rejected(self):
        members = []
        for name in ("../escaped", "/absolute", "driver.log"):
            members.append(tarfile.TarInfo(name))
        symlink = tarfile.TarInfo("symlink")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "../escaped"
        members.append(symlink)
        hardlink = tarfile.TarInfo("hardlink")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "driver.log"
        members.append(hardlink)
        for index, member in enumerate(members):
            archive, checksum = self.archive({"driver.log": b"data"}, member)
            with self.subTest(member=member.name), self.assertRaises(ValueError):
                pilot.extract_verified(archive, checksum, self.root / ("out-%d" % index))
        files = {"item-%03d" % i: b"" for i in range(101)}
        archive, checksum = self.archive(files)
        with self.assertRaisesRegex(ValueError, "limits"):
            pilot.extract_verified(archive, checksum, self.root / "too-many")

    def test_inner_manifest_tamper_is_rejected(self):
        archive = self.root / "return.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for name, data in {"exit-code": b"2", "SHA256SUMS": ("0" * 64 + "  exit-code\n").encode()}.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
        checksum = self.root / "return.tar.gz.sha256"
        checksum.write_text(pilot.digest(archive) + "  return.tar.gz\n")
        with self.assertRaisesRegex(ValueError, "file checksum"):
            pilot.extract_verified(archive, checksum, self.root / "bad-inner")

    def test_pending_launch_is_reused_without_new_upload_or_gpu_task(self):
        directory = self.root / "runs"
        directory.mkdir()
        state = self.state()
        pilot.write_json(directory / "latest.json", state)
        calls = []
        def ssh(command):
            calls.append(command)
            return "running\n"
        connection = types.SimpleNamespace(ssh=ssh, copy=lambda *args: self.fail("must not upload"))
        with contextlib.redirect_stdout(io.StringIO()):
            result = pilot.launch(connection, directory)
        self.assertEqual(result, state)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("nohup", calls[0])
        self.assertNotIn("mktemp", calls[0])
        connection.ssh = lambda command: "finished\n"
        with self.assertRaisesRegex(ValueError, "prior pilot"):
            pilot.launch(connection, directory)

    def test_remote_probe_distinguishes_missing_upload_running_and_broken_jobs(self):
        job = self.root / "probe"
        script = pilot.status_probe(self.job).replace(self.job, str(job))
        def state():
            return subprocess.check_output(["bash", "-c", script], text=True).strip()
        self.assertEqual(state(), "missing-job")
        job.mkdir()
        self.assertEqual(state(), "not-started-or-dispatch-unconfirmed")
        (job / "process-started").touch()
        (job / "driver.pid").write_text(str(os.getpid()) + "\n")
        self.assertEqual(state(), "running")
        (job / "exit-code").write_text("2\n")
        self.assertEqual(state(), "finalizing")
        (job / "driver.pid").write_text("not-a-PID\n")
        self.assertEqual(state(), "stopped-without-archive")
        (job / "archive-failed").touch()
        self.assertEqual(state(), "archive-failed")
        (job / "archive-ready").touch()
        self.assertEqual(state(), "finished")

    def test_failed_upload_or_dispatch_records_stage_without_silently_restarting(self):
        for failure in ("upload", "dispatch"):
            with self.subTest(failure=failure):
                directory = self.root / failure
                directory.mkdir()
                commands = []
                copies = []
                def ssh(command):
                    commands.append(command)
                    if "mktemp" in command:
                        return self.job + "\n"
                    if "nohup" in command:
                        raise subprocess.CalledProcessError(255, "ssh")
                    return "not-started-or-dispatch-unconfirmed\n"
                def copy(source, destination):
                    copies.append((source, destination))
                    if failure == "upload":
                        raise subprocess.CalledProcessError(1, "scp")
                connection = types.SimpleNamespace(ssh=ssh, copy=copy)
                with self.assertRaisesRegex(ValueError, "不自动重启"):
                    pilot.launch(connection, directory)
                record = pilot.load_state(directory / "latest.json")
                self.assertEqual(record["launch_phase"], "uploading" if failure == "upload" else "dispatching")
                self.assertIn("launch_error", record)
                previous_copies = len(copies)
                previous_commands = len(commands)
                with self.assertRaisesRegex(ValueError, "未确认启动或已中断"):
                    pilot.launch(connection, directory)
                self.assertEqual(len(copies), previous_copies)
                self.assertEqual(len(commands), previous_commands + 1)
                self.assertNotIn("nohup", commands[-1])

    def test_successful_dispatch_records_phase_and_wait_shell_is_valid(self):
        directory = self.root / "launch"
        directory.mkdir()
        copies = []
        commands = []
        def ssh(command):
            commands.append(command)
            return self.job + "\n" if "mktemp" in command else ""
        connection = types.SimpleNamespace(ssh=ssh, copy=lambda *args: copies.append(args))
        with contextlib.redirect_stdout(io.StringIO()):
            state = pilot.launch(connection, directory)
        self.assertEqual(state["launch_phase"], "dispatched")
        self.assertEqual(len(copies), 3)
        self.assertEqual(pilot.load_state(directory / "latest.json"), state)
        self.assertEqual(sum("nohup" in command for command in commands), 1)
        def validate_wait(command):
            subprocess.run(["bash", "-n", "-c", command], check=True)
            self.assertIn("stopped-without-archive", command)
            self.assertIn("startup unconfirmed", command)
            return "ready\n"
        connection.ssh = validate_wait
        self.assertTrue(pilot.wait_for_archive(connection, self.job, 30))

    def test_broken_remote_jobs_are_not_reused_as_pending(self):
        directory = self.root / "recorded"
        directory.mkdir()
        pilot.write_json(directory / "latest.json", self.state())
        for status in ("archive-failed", "missing-job", "stopped-without-archive", "not-started-or-dispatch-unconfirmed"):
            connection = types.SimpleNamespace(ssh=lambda _, status=status: status + "\n",
                                                copy=lambda *args: self.fail("must not upload"))
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "不自动重启"):
                pilot.launch(connection, directory)

    def test_plan_has_no_connection(self):
        with patch.object(pilot, "Connection", side_effect=AssertionError("plan must be offline")):
            with patch("sys.argv", [str(SCRIPT), "plan"]), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(pilot.main(), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["frames_1based"], [91, 159])
        self.assertFalse(plan["training_ready"])
        self.assertFalse(plan["dependency_changes"])
        self.assertFalse(plan["neural_inference"])


if __name__ == "__main__":
    unittest.main()
