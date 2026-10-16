"""Downloaded candidate evidence is audited without repairing or approving motion."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-candidate-fit-review.py'
spec = importlib.util.spec_from_file_location('candidate_fit_review', SCRIPT)
review = importlib.util.module_from_spec(spec)
if SCRIPT.exists():
    spec.loader.exec_module(review)


class CandidateReviewTests(unittest.TestCase):
    def native(self, folder, number=1, person=0, **changes):
        values = {name: np.zeros(shape, dtype=np.float32) for name, shape in review.NATIVE_SHAPES.items()}
        values.update(changes)
        path = folder / f'{number:05d}_{person}.npz'
        np.savez(path, **values)
        return path

    def test_required_audit_helpers_exist(self):
        self.assertTrue(callable(getattr(review, 'native_inventory', None)),
                        'Need an exact native frame/person inventory audit')

    def test_missing_and_multiple_detections_stay_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.native(p, 1)
            self.native(p, 3)
            self.native(p, 3, 1)
            before = {f.name: f.read_bytes() for f in p.iterdir()}
            result = review.native_inventory(p, 3)
            self.assertEqual(result['missing_frames'], [2])
            self.assertEqual(result['multiple_person_frames'], [3])
            self.assertFalse(result['complete_single_person'])
            self.assertEqual(before, {f.name: f.read_bytes() for f in p.iterdir()})

    def test_out_of_range_parameter_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.native(p, 3)
            with self.assertRaisesRegex(ValueError, 'frame'):
                review.native_inventory(p, 2)

    def test_dtype_shape_and_nan_rejected_for_every_native_field(self):
        for field, shape in review.NATIVE_SHAPES.items():
            for value in [np.zeros(shape, np.int32), np.full(shape, np.nan), np.zeros((1, 2))]:
                with self.subTest(field=field, shape=value.shape), tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp)
                    self.native(p, **{field: value})
                    with self.assertRaisesRegex(ValueError, 'native'):
                        review.native_inventory(p, 1)

    def test_complete_frame_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.native(p, 1)
            self.native(p, 2)
            result = review.native_inventory(p, 2)
            self.assertTrue(result['complete_single_person'])
            self.assertEqual(result['parameter_files'], 2)

    def test_nominal_frame_map_is_exact_and_never_promoted_to_pts(self):
        rows = [{'frame_1based': i, 'clip_seconds': (i - 1) / 25,
                 'source_seconds_nominal': 12 + (i - 1) / 25, 'interpolated': False}
                for i in range(1, 5)]
        case = {'frames': 4, 'start_seconds': 12., 'fps': 25.}
        review.validate_frame_map(rows, case)
        rows[2]['interpolated'] = True
        with self.assertRaisesRegex(ValueError, 'frame map'):
            review.validate_frame_map(rows, case)

    def test_rotations_use_so3_and_measure_midpoint_residual(self):
        values = np.zeros((3, 1, 3), np.float32)
        values[:, 0, 2] = np.deg2rad([179, 181, 183])
        result = review.rotation_metrics(values)
        self.assertAlmostEqual(result['adjacent_degrees']['p95'], 2., places=4)
        self.assertLess(result['geodesic_midpoint_residual_degrees']['maximum'], .001)

    def test_checksum_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'root'
            p.mkdir()
            (p / 'SHA256SUMS').write_text('0' * 64 + '  ../outside\n')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                review.verify_checksums(p)

    def test_checksum_manifest_must_cover_every_result_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'report.json').write_text(json.dumps({'training_ready': False}))
            digest = review.sequence.data.sha256_file(p / 'report.json')
            (p / 'SHA256SUMS').write_text(digest + '  report.json\n')
            self.assertEqual(review.verify_checksums(p), 1)
            (p / 'unexpected.npz').write_bytes(b'not covered')
            with self.assertRaisesRegex(ValueError, 'coverage'):
                review.verify_checksums(p)


if __name__ == '__main__':
    unittest.main()
