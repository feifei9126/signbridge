"""CPU-only media audit regression tests; retain fixtures and failed audit outputs."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-expanded-media.py'
SPEC = importlib.util.spec_from_file_location('expanded_media_test_tool', TOOL)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
# Resolve the media tools from PATH so the suite runs on both macOS and Linux.
FFPROBE = Path((shutil.which('ffprobe') or '/usr/bin/ffprobe'))
FFMPEG = Path((shutil.which('ffmpeg') or '/usr/bin/ffmpeg'))


class MediaTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('SIGNBRIDGE_MEDIA_TEST_ROOT')
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        # macOS may spell the system temporary directory /var or /private/var.
        # Canonicalize the fixture root, while retaining deliberate child symlinks.
        self.root = Path(tempfile.mkdtemp(prefix='media-test-', dir=parent)).resolve()
        self.db = self.root / 'database'
        self.db.mkdir()

    def freeze(self, payload=b'invalid mp4', sample_frames=None):
        clip = self.db / 'clip.mp4'
        clip.write_bytes(payload)
        row = {'relative_path': 'clip.mp4', 'sha256': m.sha(clip), 'bytes': len(payload)}
        samples = [{'id': 'csl_test', 'local_video': 'clip.mp4',
                    'media_sha256': row['sha256'], 'dataset_id': 'test',
                    'status': 'quarantined_label_conflict', 'training_ready': False}]
        if sample_frames is not None:
            samples[0]['frames'] = sample_frames
        (self.db / 'media-inventory.jsonl').write_text(json.dumps(row) + '\n')
        (self.db / 'samples.jsonl').write_text(json.dumps(samples[0]) + '\n')
        manifest = self.db / 'SHA256SUMS'
        manifest.write_text(''.join(f'{m.sha(p)}  {p.name}\n'
                                    for p in sorted(self.db.iterdir()) if p != manifest))
        return row, m.sha(manifest)

    def run_audit(self, manifest_hash, output=None, **kwargs):
        output = output or self.root / 'audit'
        with contextlib.redirect_stdout(io.StringIO()):
            report = m.run_audit(self.db, output, manifest_hash,
                                 ffprobe=FFPROBE, workers=2, timeout=20, **kwargs)
        records = [json.loads(x) for x in (output / 'records.jsonl').read_text().splitlines()]
        return report, records, output

    def make_clip(self):
        self.assertTrue(FFMPEG.is_file(), 'Use existing ffmpeg; do not install')
        path = self.root / f'generated-{len(list(self.root.glob("generated-*.mp4")))}.mp4'
        subprocess.run([str(FFMPEG), '-v', 'error', '-threads', '1', '-f', 'lavfi',
                        '-i', 'color=c=red:s=32x24:r=10', '-frames:v', '7',
                        '-an', '-c:v', 'mpeg4', '-threads', '1', str(path)],
                       check=True, capture_output=True, timeout=20)
        return path.read_bytes()

    def test_real_decode_counts_frames_and_keeps_quarantine_and_provenance(self):
        _, pinned = self.freeze(self.make_clip(), sample_frames=7)
        report, records, output = self.run_audit(pinned)
        record = records[0]
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['failed'], 0)
        self.assertEqual(record['framecount'], 7)
        self.assertEqual(record['dimensions'], [32, 24])
        self.assertEqual(record['fps'], 10)
        self.assertEqual(record['exitcode'], 0)
        self.assertTrue(record['full_decode'])
        self.assertEqual(record['expected_frames'], [7])
        self.assertEqual(record['samples'][0]['status'], 'quarantined_label_conflict')
        self.assertFalse(report['training_ready'])
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(m.sha(output / 'provenance.json'), report['provenance_sha256'])
        self.assertEqual(json.loads((output / 'progress.json').read_text())['completed'], 1)
        self.assertEqual(report['manifest_verification']['checked'], 3)
        before = (output / 'records.jsonl').read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_audit(pinned, output)
        self.assertEqual((output / 'records.jsonl').read_bytes(), before)

    def test_missing_expected_frames_stays_unknown_and_container_is_not_authority(self):
        _, pinned = self.freeze(self.make_clip())
        sample_path = self.db / 'samples.jsonl'
        sample = json.loads(sample_path.read_text())
        sample['video'] = {'probe': {'metadata': {'container_reported_frames': 99}}}
        sample_path.write_text(json.dumps(sample) + '\n')
        manifest = self.db / 'SHA256SUMS'
        manifest.write_text(''.join(f'{m.sha(p)}  {p.name}\n' for p in sorted(self.db.iterdir())
                                    if p != manifest))
        report, records, _ = self.run_audit(m.sha(manifest))
        self.assertEqual(report['failed'], 0)
        self.assertIsNone(records[0]['expected_frames'])
        self.assertEqual(records[0]['container_reported'][0]['frames'], 99)
        self.assertFalse(records[0]['container_reported'][0]['matches_decoded'])

    def test_wrong_media_hash_is_failure_even_when_decoder_succeeds(self):
        _, pinned = self.freeze(self.make_clip())
        (self.db / 'clip.mp4').write_bytes(self.make_clip() + b'changed')
        report, records, _ = self.run_audit(pinned)
        self.assertEqual(report['status'], 'completed_with_failures')
        self.assertIn('sha256_mismatch', [e['category'] for e in records[0]['errors']])
        self.assertFalse(records[0]['passed'])

    def test_pinned_manifest_mismatch_retains_failure_report(self):
        self.freeze()
        report, records, output = self.run_audit('0' * 64)
        self.assertEqual(report['status'], 'failed_preflight')
        self.assertFalse(records)
        self.assertIn('manifest_sha256_mismatch', report['failure_categories'])
        self.assertTrue((output / 'failures.jsonl').read_text())

    def test_outside_symlink_is_never_hashed_or_decoded(self):
        _, pinned = self.freeze()
        external = self.root / 'outside.mp4'
        external.write_bytes(b'outside')
        (self.db / 'clip.mp4').unlink()
        (self.db / 'clip.mp4').symlink_to(external)
        with patch.object(m.subprocess, 'Popen', wraps=subprocess.Popen) as spawn:
            report, records, _ = self.run_audit(pinned)
        self.assertFalse(records[0]['passed'])
        self.assertIsNone(records[0]['sha256'])
        self.assertIn('unsafe_path', report['failure_categories'])
        self.assertFalse(any(str(external) in call.args[0] for call in spawn.call_args_list))

    def test_bad_decode_and_expected_count_mismatch_are_preserved(self):
        _, pinned = self.freeze()
        report, records, output = self.run_audit(pinned)
        self.assertGreater(records[0]['exitcode'], 0)
        self.assertTrue(records[0]['stderr'])
        self.assertFalse(records[0]['full_decode'])
        self.assertIn('decode_exit_nonzero', report['failure_categories'])
        self.assertTrue((output / 'failures.jsonl').read_text())
        other = self.root / 'count-database'
        other.mkdir()
        self.db = other
        _, pinned = self.freeze(self.make_clip(), sample_frames=8)
        report, records, _ = self.run_audit(pinned, self.root / 'count-audit')
        self.assertIn('expected_framecount_mismatch', report['failure_categories'])
        self.assertFalse(records[0]['passed'])
        self.assertTrue(records[0]['full_decode'])

    def test_timeout_and_zero_exit_decoder_errors_cannot_pass(self):
        for code, stdout, stderr, timed_out, category in [
            (-9, '', 'partial stderr', True, 'decode_timeout'),
            (0, '{"streams":[]}', 'decoder error', False, 'decode_stderr'),
            (0, 'not json', '', False, 'invalid_probe_output'),
        ]:
            with self.subTest(category=category):
                row, _ = self.freeze()
                with patch.object(m, 'probe', return_value={
                    'exitcode': code, 'stdout': stdout, 'stderr': stderr,
                    'timed_out': timed_out, 'command': ['fake'], 'elapsed_seconds': 0,
                }):
                    record = m.audit_media(self.db, row, {row['relative_path']: row['sha256']},
                                           [], FFPROBE, 1)
                self.assertFalse(record['passed'])
                self.assertFalse(record['full_decode'])
                self.assertIn(category, [e['category'] for e in record['errors']])

    def test_actual_timeout_kills_and_reaps_process_and_retains_partial_stderr(self):
        executable = self.root / 'slow-ffprobe'
        executable.write_text('#!/bin/sh\nprintf "decoder-started\\n" >&2\n'
                              'exec /bin/sleep 30\n')
        executable.chmod(0o755)
        # Leave startup headroom when the full suite is also using CPU threads.
        result = m.probe(self.root / 'unused.mp4', executable, 3)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['exitcode'], -9)
        self.assertIn('decoder-started', result['stderr'])
        self.assertLess(result['elapsed_seconds'], 10)

    def test_aliases_decode_once_and_unsafe_alias_does_not_stop_other_media(self):
        row, _ = self.freeze(self.make_clip())
        alias = self.db / 'alias.mp4'
        alias.write_bytes((self.db / 'clip.mp4').read_bytes())
        samples = self.db / 'samples.jsonl'
        second = {'id': 'csl_alias', 'local_video': 'alias.mp4',
                  'media_sha256': row['sha256'], 'dataset_id': 'test', 'status': 'retained'}
        samples.write_text(samples.read_text() + json.dumps(second) + '\n')
        manifest = self.db / 'SHA256SUMS'
        manifest.write_text(''.join(f'{m.sha(p)}  {p.name}\n' for p in sorted(self.db.iterdir())
                                    if p != manifest))
        pinned = m.sha(manifest)
        with patch.object(m, 'probe', wraps=m.probe) as decoder:
            report, records, _ = self.run_audit(pinned)
        self.assertEqual(decoder.call_count, 1)
        self.assertEqual(report['full_decodes'], 1)
        self.assertEqual(set(records[0]['aliases']), {'clip.mp4', 'alias.mp4'})
        self.assertEqual(len(records[0]['samples']), 2)
        outside = self.root / 'outside-alias.mp4'
        outside.write_bytes(alias.read_bytes())
        alias.unlink()
        alias.symlink_to(outside)
        report, records, _ = self.run_audit(pinned, self.root / 'unsafe-alias-audit')
        self.assertEqual(report['status'], 'completed_with_failures')
        self.assertIn('unsafe_path', report['failure_categories'])
        self.assertTrue(records[0]['passed'])
        self.assertEqual(report['completed'], 1)

    def test_worker_and_timeout_bounds_and_protected_output(self):
        _, pinned = self.freeze()
        for kwargs in [{'workers': 5}, {'timeout': 0}, {'timeout': float('nan')}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                m.run_audit(self.db, self.root / 'bad', pinned, **kwargs)
        with self.assertRaises(ValueError):
            m.run_audit(self.db, self.db / 'audit', pinned)


if __name__ == '__main__':
    unittest.main()
