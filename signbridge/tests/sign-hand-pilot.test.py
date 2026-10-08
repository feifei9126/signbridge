"""Offline launcher tests: no network, password, GPU or actual user data."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shlex
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

    def test_review_driver_is_read_only_and_has_no_optimizer_budget(self):
        old_job = self.job.replace("Ab1c23", "Cd4e56")
        script = pilot.driver(self.job, review_source=old_job, review_sha="a" * 64)
        subprocess.run(["bash", "-n", "-c", script], check=True)
        self.assertIn(" review ", script)
        self.assertIn("--previous-results", script)
        self.assertIn("--previous-report-sha256", script)
        self.assertIn(old_job + "/results", script)
        self.assertNotIn("--max-nfev", script)
        self.assertNotIn('sign-hand-refine.py" pilot', script)
        self.assertNotIn("pip install", script)
        self.assertNotIn("apt-get", script)
        with self.assertRaises(ValueError):
            pilot.driver(self.job, review_source=old_job, review_sha="bad")

    def test_elbow_pilot_is_explicit_and_has_separate_state(self):
        script = pilot.driver(self.job, allow_elbow=True)
        self.assertIn("--allow-elbow", script)
        self.assertIn("--max-nfev 200", script)
        subprocess.run(["bash", "-n", "-c", script], check=True)
        directory = self.root / "elbow-runs"
        directory.mkdir()
        pilot.write_json(directory / "latest.json", self.state())
        old = (directory / "latest.json").read_bytes()
        new_job = self.job.replace("Ab1c23", "Gh1j23")
        connection = types.SimpleNamespace(ssh=lambda command: new_job + "\n" if "mktemp" in command else "",
                                            copy=lambda *args: None)
        with contextlib.redirect_stdout(io.StringIO()):
            state = pilot.launch(connection, directory, allow_elbow=True)
        self.assertEqual(state["fit_mode"], "hand_plus_elbow")
        self.assertEqual(pilot.load_state(directory / "latest-elbow.json"), state)
        self.assertEqual((directory / "latest.json").read_bytes(), old)
        self.assertIn("--allow-elbow", (directory / Path(new_job).name / "run.sh").read_text())
        path = self.root / "bad-elbow-state.json"
        for changes in ({"elbow_limit_degrees": 35}, {"fit_mode": "all_body"}):
            pilot.write_json(path, {**state, **changes})
            with self.assertRaises(ValueError):
                pilot.load_state(path)

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
        def finished_ssh(command):
            return "finished\n" if "archive-ready" in command else "0\n"
        connection.ssh = finished_ssh
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

    def test_failed_completed_job_with_updated_tool_gets_new_isolated_job(self):
        directory = self.root / "retry"
        directory.mkdir()
        state = self.state()
        state["tool_sha256"] = "b" * 64
        pilot.write_json(directory / "latest.json", state)
        commands = []
        def ssh(command):
            commands.append(command)
            if "archive-ready" in command:
                return "finished\n"
            if "exit-code" in command:
                return "2\n"
            if "mktemp" in command:
                return self.job.replace("Ab1c23", "Cd4e56") + "\n"
            return ""
        connection = types.SimpleNamespace(ssh=ssh, copy=lambda *args: None)
        with contextlib.redirect_stdout(io.StringIO()):
            result = pilot.launch(connection, directory)
        self.assertNotEqual(result["remote_job"], self.job)
        self.assertEqual(result["launch_phase"], "dispatched")
        self.assertTrue(any("mktemp" in command for command in commands))

    def test_prepare_render_is_explicit_and_only_targets_glu(self):
        calls = []
        connection = types.SimpleNamespace(ssh=lambda command, capture=True: calls.append((command, capture)))
        with contextlib.redirect_stdout(io.StringIO()):
            pilot.prepare_render(connection)
        self.assertEqual(len(calls), 1)
        command, capture = calls[0]
        self.assertFalse(capture)
        self.assertIn("libGLU.so.1", command)
        self.assertIn("libglu1-mesa", command)
        self.assertIn("apt-get update", command)
        self.assertIn("--no-upgrade", command)
        self.assertIn("--no-remove", command)
        self.assertIn("apt-get -s", command)
        self.assertIn("Refusing changes outside", command)
        self.assertIn("PYOPENGL_PLATFORM=egl", command)
        self.assertIn("import pyrender", command)
        self.assertNotIn("pip install", command)
        self.assertNotIn("apt-get upgrade", command)
        self.assertNotIn("train.py", command)
        self.assertNotIn("inference.py", command)
        self.assertNotIn("nohup", command)
        subprocess.run(["bash", "-n", "-c", command], check=True)

    def test_prepare_shell_refuses_upgrades_or_unrelated_packages_before_install(self):
        calls = []
        connection = types.SimpleNamespace(ssh=lambda command, capture=True: calls.append(command))
        with contextlib.redirect_stdout(io.StringIO()):
            pilot.prepare_render(connection)
        shell = shlex.split(calls[0])[2]
        commands = self.root / "prepare-commands"
        commands.mkdir()
        log = self.root / "os-actions.log"
        for name, code in {
            "ldconfig": '#!/bin/sh\nif [ "$HAVE_GLU" = 1 ]; then echo libGLU.so.1; fi\n',
            "apt-get": '#!/bin/sh\necho "apt-get $*" >> "$ACTION_LOG"\ncase "$*" in *-s*) printf "%s\\n" "$SIMULATION" ;; esac\n',
            "gpu-python": '#!/bin/sh\necho library-import-check >> "$ACTION_LOG"\n',
        }.items():
            path = commands / name
            path.write_text(code)
            path.chmod(0o700)
        shell = shell.replace(pilot.BASE + "/envs/smplerx/bin/python", str(commands / "gpu-python"))
        plans = [
            ("Inst libglu1-mesa (9.0.1 test [amd64])", 0),
            ("Inst libglu1-mesa (9.0.1 test [amd64])\nInst libopengl0 (1.3 test [amd64])", 0),
            ("Inst libglu1-mesa [old] (new test [amd64])", 78),
            ("Inst cuda-runtime (new test [amd64])", 78),
            ("Remv libgl1 [old]", 78),
        ]
        for plan, expected in plans:
            log.write_text("")
            result = subprocess.run(["bash", "-c", shell], check=False, capture_output=True, text=True,
                env={**os.environ, "PATH": str(commands) + ":" + os.environ["PATH"], "HAVE_GLU": "0",
                     "SIMULATION": plan, "ACTION_LOG": str(log)})
            with self.subTest(plan=plan):
                self.assertEqual(result.returncode, expected, result.stderr)
                actions = log.read_text()
                install = "apt-get install -y"
                self.assertEqual(install in actions, expected == 0)
                self.assertEqual("library-import-check" in actions, expected == 0)
        log.write_text("")
        result = subprocess.run(["bash", "-c", shell], check=False, capture_output=True, text=True,
            env={**os.environ, "PATH": str(commands) + ":" + os.environ["PATH"], "HAVE_GLU": "1",
                 "SIMULATION": "must not run apt", "ACTION_LOG": str(log)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log.read_text(), "library-import-check\n")

    def test_prepare_command_does_not_launch_fit_or_require_previous_state(self):
        connection = types.SimpleNamespace(close=lambda: None)
        with patch.object(pilot, "REPO", self.root), \
             patch.object(pilot, "Connection", return_value=connection), \
             patch.object(pilot, "prepare_render") as prepare, \
             patch.object(pilot, "launch", side_effect=AssertionError("no GPU launch")), \
             patch.object(pilot, "load_state", side_effect=AssertionError("no state read")), \
             patch("sys.argv", [str(SCRIPT), "prepare-render"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pilot.main(), 0)
        prepare.assert_called_once_with(connection)

    def test_failed_collect_displays_error_without_claiming_candidates_exist(self):
        report = {"schema": "signbridge-hand-keyframe-pilot-v1", "status": "failed",
                  "training_ready": False, "full_sequence_refined": False,
                  "error": 'Library "GLU" not found.', "failure_stage": "render_preflight", "cases": []}
        tool = b"# mock tool\n"
        archive, checksum = self.archive({"sign-hand-refine.py": tool, "driver.log": b"GPU fixture failure",
                                        "exit-code": b"2\n", "results/report.json": json.dumps(report).encode()})
        state = self.state()
        state["tool_sha256"] = hashlib.sha256(tool).hexdigest()
        def copy(source, destination):
            original = checksum if source.endswith(".sha256") else archive
            Path(destination).write_bytes(original.read_bytes())
        connection = types.SimpleNamespace(copy=copy)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(pilot.collect(connection, state, self.root), 2)
        text = output.getvalue()
        self.assertIn("GLU", text)
        self.assertIn("render_preflight", text)
        self.assertNotIn("本次只产生关键帧候选", text)
        self.assertIn("不能视为完整修正", text)

    def test_review_launch_uses_new_state_without_replacing_fitting_latest(self):
        directory = self.root / "review-launch"
        directory.mkdir()
        state = self.state()
        pilot.write_json(directory / "latest.json", state)
        latest_before = (directory / "latest.json").read_bytes()
        new_job = self.job.replace("Ab1c23", "Cd4e56")
        commands, copied = [], []
        def ssh(command):
            commands.append(command)
            if "mktemp" in command:
                return new_job + "\n"
            if "sha256sum" in command:
                return "a" * 64 + "  results/report.json\n"
            return "finished\n" if "archive-ready" in command else ""
        connection = types.SimpleNamespace(ssh=ssh, copy=lambda *args: copied.append(args))
        with contextlib.redirect_stdout(io.StringIO()):
            review = pilot.launch(connection, directory, review_source=state)
        self.assertEqual(review["mode"], "review")
        self.assertEqual(review["review_source_job"], self.job)
        self.assertEqual(review["review_report_sha256"], "a" * 64)
        self.assertEqual(review["remote_job"], new_job)
        self.assertEqual((directory / "latest.json").read_bytes(), latest_before)
        self.assertEqual(pilot.load_state(directory / "latest-review.json"), review)
        driver = (directory / Path(new_job).name / "run.sh").read_text()
        self.assertIn("--previous-results", driver)
        self.assertEqual(len(copied), 3)
        different_source = {**state, "remote_job": self.job.replace("Ab1c23", "Ef7g89")}
        with self.assertRaisesRegex(ValueError, "source differs"):
            pilot.launch(connection, directory, review_source=different_source)
        self.assertEqual(len(copied), 3)
        for mutation in ({"review_source_job": "/tmp/evil"}, {"review_report_sha256": "bad"}):
            path = self.root / "invalid-review.json"
            pilot.write_json(path, {**review, **mutation})
            with self.assertRaises(ValueError):
                pilot.load_state(path)

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
