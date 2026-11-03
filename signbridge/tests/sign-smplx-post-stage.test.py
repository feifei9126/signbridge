"""Partition frozen review evidence without certifying automatic candidates."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np


TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-smplx-post-stage.py'


def load_tool():
    spec = importlib.util.spec_from_file_location('post_stage_test', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertTrue(TOOL.is_file(), 'Post-fit partition tool must exist')
        self.tool = load_tool()

    def row(self, name='one', tier='no_automatic_motion_red_flag'):
        flags = dict(self.tool.FLAGS)
        return dict(uid='chunk:' + name, annotation_id=name, chunk='chunk',
                    source_id='source', source_sha256='b' * 64, label_candidate='我',
                    fps=25.0, frames_expected=4, missing_detection_frames=[],
                    technical_errors=[], motion_review_flags=[], quality_tier=tier,
                    raw_rotation_metrics={}, **flags)

    def test_partition_covers_ids_once_and_rejects_duplicates_unknown_or_approval(self):
        a = self.row()
        b = self.row('two', 'high_priority_motion_review')
        c = self.row('three', 'missing_detections_quarantine')
        manual, eligible = self.tool.partition([a, b, c])
        self.assertEqual([r['uid'] for r in manual], [b['uid'], c['uid']])
        self.assertEqual(eligible, [a])
        for rows in ([a, a], [{**a, 'quality_tier': 'approved'}],
                     [{**a, 'human_approved': True}], [{**a, 'text_verified': '我'}],
                     [{**a, 'frames_expected': True}], [{**a, 'fps': float('nan')}],
                     [{**a, 'motion_review_flags': ['extra']}],
                     [{**a, 'missing_detection_frames': [1]}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.tool.partition(rows)

    def native(self, row, jump=False):
        attempt = self.root / row['annotation_id']
        fit = attempt / 'fits' / row['annotation_id']
        (fit / 'smplx').mkdir(parents=True)
        (fit / 'meta').mkdir()
        sums = []
        for frame in range(1, 5):
            params = {k: np.zeros(shape, dtype=np.float32)
                      for k, shape in self.tool.SHAPES.items()}
            params['leye_pose'] = params['leye_pose'].astype(np.float64)
            if jump and frame == 2:
                params['global_orient'][0, 0] = 2.5
            native = fit / 'smplx' / f'{frame:05d}_0.npz'
            np.savez_compressed(native, **params)
            meta = fit / 'meta' / f'{frame:05d}_0.json'
            meta.write_text(json.dumps({'bbox_id': 0}))
            for path in (native, meta):
                sums.append(f'{sha(path)}  {path.relative_to(attempt).as_posix()}\n')
        (attempt / 'SHA256SUMS').write_text(''.join(sums))
        row['fit_directory'] = str(fit)
        return fit

    def test_native_stack_preserves_shapes_dtypes_values_and_frame_order(self):
        row = self.row()
        fit = self.native(row)
        arrays, sources, metrics = self.tool.read_native(row)
        self.assertEqual(arrays['frame_ids_1based'].tolist(), [1, 2, 3, 4])
        for key, shape in self.tool.SHAPES.items():
            self.assertEqual(arrays[key].shape, (4, *shape))
            with np.load(fit / 'smplx/00001_0.npz') as original:
                np.testing.assert_array_equal(arrays[key][0], original[key])
                self.assertEqual(arrays[key].dtype, original[key].dtype)
        self.assertEqual(len(sources), 8)
        self.assertEqual(metrics['additional_rotation_flags'], [])

    def test_root_rotation_risk_is_not_silently_accepted(self):
        row = self.row()
        self.native(row, jump=True)
        _, _, metrics = self.tool.read_native(row)
        self.assertIn('global_orient:adjacent_over_90deg', metrics['additional_rotation_flags'])

    def test_missing_extra_or_hash_tampered_native_rejected(self):
        for variant in ('missing', 'extra', 'tamper', 'metadata'):
            row = self.row(variant)
            fit = self.native(row)
            if variant == 'missing':
                (fit / 'smplx/00002_0.npz').unlink()
            elif variant == 'extra':
                (fit / 'smplx/99999_0.npz').write_bytes(b'extra')
            elif variant == 'metadata':
                (fit / 'meta/00001_0.json').write_bytes(b'tampered')
            else:
                (fit / 'smplx/00001_0.npz').write_bytes(b'tampered')
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                self.tool.read_native(row)

    def test_numeric_content_dedup_keeps_fps_dtype_and_exact_values(self):
        arrays = {'frame_ids_1based': np.arange(1, 5),
                  'body_pose': np.zeros((4, 21, 3), dtype=np.float32)}
        digest = self.tool.content_hash(arrays, 25)
        self.assertEqual(digest, self.tool.content_hash(copy.deepcopy(arrays), 25.0))
        self.assertNotEqual(digest, self.tool.content_hash(arrays, 30))
        changed = copy.deepcopy(arrays)
        changed['body_pose'][0, 0, 0] = 1e-7
        self.assertNotEqual(digest, self.tool.content_hash(changed, 25))
        changed['body_pose'] = arrays['body_pose'].astype(np.float64)
        self.assertNotEqual(digest, self.tool.content_hash(changed, 25))

    def test_containment_rejects_traversal_and_symlinks(self):
        (self.root / 'file').write_text('x')
        (self.root / 'link').symlink_to(self.root / 'file')
        for value in ('../file', '/etc/passwd', 'link', 'file/../file'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.tool.contained(self.root, value)

    def test_archive_roundtrip_checks_all_members_and_hashes(self):
        folder = self.root / 'bundle'
        folder.mkdir()
        (folder / 'notes.txt').write_text('原始候选，未批准')
        self.tool.seal(folder)
        result = self.tool.archive(folder)
        self.assertEqual(result['verified_files'], 1)
        self.assertEqual(result['sha256'], sha(Path(result['archive'])))
        with zipfile.ZipFile(result['archive']) as archive:
            self.assertEqual(archive.read('bundle/notes.txt').decode(), '原始候选，未批准')

    def test_build_freezes_manual_and_preserves_aliases_when_exact_motions_share_asset(self):
        rows = [self.row('one'), self.row('two'), self.row('jump'),
                self.row('pending', 'high_priority_motion_review')]
        for row in rows[:3]:
            self.native(row, jump=row['annotation_id'] == 'jump')
        results = self.root / 'results'
        chunks = results / 'chunks/chunk'
        chunks.mkdir(parents=True)
        aliases = [{**self.tool.FLAGS, 'fit_sequence_id': r['annotation_id'],
                    'source_sha256': r['source_sha256'], 'candidate_id': 'alias-' + r['annotation_id'],
                    'label_candidate': r['label_candidate']} for r in rows]
        (chunks / 'aliases.jsonl').write_text(''.join(json.dumps(a) + '\n' for a in aliases))
        self.tool.seal(chunks)
        audit = self.root / 'audit.json'
        audit.write_text(json.dumps({'records': rows, 'results': str(results), 'audit_complete': True,
                                    'status': 'audit_completed_pending_human_review', 'summary': {}}))
        review_root = self.root / 'review'
        review_root.mkdir()
        review_rows = []
        for row in rows:
            folder = review_root / 'media' / row['annotation_id']
            folder.mkdir(parents=True)
            media = {}
            for kind, name in [('original', 'original.mp4'), ('comparison', 'comparison.mp4'),
                               ('contact', 'contact.jpg')]:
                file = folder / name
                file.write_bytes(b'opaque previously decoded media')
                media[kind] = {'path': file.relative_to(review_root).as_posix(), 'sha256': sha(file)}
            review_rows.append({**row, 'media': media, 'processed_frames': 4})
        source_report = {'records': review_rows, 'audit_sha256': sha(audit), 'summary': {}}
        (review_root / 'report.json').write_text(json.dumps(source_report))
        for name in ('index.html', 'review.js', 'review.css'):
            (review_root / name).write_text('existing application asset')
        self.tool.seal(review_root)
        output = self.root / 'stage'
        with patch.object(self.tool.review_tool, 'scoped_locales', return_value={}):
            report = self.tool.build(audit, review_root, output)
        summary = report['summary']
        self.assertEqual(summary['manual_review_sequences'], 2)
        self.assertEqual(summary['technical_candidate_sequences'], 2)
        self.assertEqual(summary['unique_native_assets'], 1)
        self.assertEqual(summary['exact_native_duplicates'], 1)
        self.assertEqual(summary['candidate_aliases'], 2)
        self.assertEqual(len(report['archives']), 2)
        library = json.loads((output / 'technical-round/index.json').read_text())
        self.assertEqual(library['records'][1]['exact_duplicate_of'], rows[0]['uid'])
        for row in library['records']:
            for key, value in self.tool.FLAGS.items():
                self.assertEqual(row[key], value)
        manual = json.loads((output / 'manual-review/report.json').read_text())
        self.assertEqual({r['uid'] for r in manual['records']}, {rows[2]['uid'], rows[3]['uid']})
        self.assertEqual(len(list((output / 'technical-round/native').glob('*.npz'))), 1)
        with self.assertRaises(ValueError):
            self.tool.build(audit, review_root, output)


if __name__ == '__main__':
    unittest.main()
