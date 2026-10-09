"""Bounded stable-crop inference must preserve original source and frame scope."""

import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-stable-crop.py'


class StableCropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('stable_crop', SCRIPT)
        cls.crop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.crop)

    def test_fixed_box_is_median_center_and_size_without_temporal_interpolation(self):
        boxes = [[0., 0., 192., 256.], [12., 10., 198., 264.], [6., 8., 186., 248.]]
        result = self.crop.stable_box(boxes)
        centers = np.asarray(boxes)[:, :2] + np.asarray(boxes)[:, 2:] / 2
        np.testing.assert_allclose(result[:2] + result[2:]/2, np.median(centers, axis=0))
        np.testing.assert_array_equal(result[2:], [192., 256.])
        self.assertEqual(result.dtype, np.float32)
        with self.assertRaises(ValueError):
            self.crop.stable_box([[0, 0, 100, 100]])

    def test_adapted_script_changes_only_bbox_and_one_parser_argument(self):
        source = "import numpy as np\nimport json\ndef parse_args():\n    parser.add_argument('--bbox_thr', type=int, default=50)\ndef main():\n    bbox = process_bbox(mmdet_box_xywh, original_img_width, original_img_height)\n    do_model_inference()\n"
        changed = self.crop.adapt_inference(source)
        self.assertIn("parser.add_argument('--fixed_bbox_file', required=True)", changed)
        self.assertIn('bbox = np.asarray(json.loads(Path(args.fixed_bbox_file).read_text()), dtype=np.float32)', changed)
        self.assertIn('    do_model_inference()', changed)
        self.assertNotIn('bbox = process_bbox', changed)
        compile(changed, '<adapted>', 'exec')
        with self.assertRaises(ValueError):
            self.crop.adapt_inference(source.replace('    bbox = process_bbox', '    changed_bbox = process_bbox'))

    def test_upstream_end_argument_is_frame_count_not_last_frame(self):
        argv = self.crop.command(Path('/python'), Path('/job/stable-inference.py'),
                                 Path('/images'), 88, 94, Path('/job/fits'), Path('/job/box.json'))
        self.assertEqual(argv[argv.index('--start')+1], '88')
        self.assertEqual(argv[argv.index('--end')+1], '7')
        self.assertEqual(argv[argv.index('--fixed_bbox_file')+1], '/job/box.json')

    def test_plan_has_exact_14_frames_and_never_claims_training_or_full_sequence(self):
        self.assertEqual(sum(len(ids) for ids in self.crop.WINDOWS.values()), 14)
        value = self.crop.report_contract()
        self.assertFalse(value['training_ready'])
        self.assertFalse(value['full_sequence_refined'])
        self.assertFalse(value['original_fits_overwritten'])

    def test_projected_hand_inside_crop_is_required(self):
        points = np.zeros((21,2)) + [120.,120.]
        self.crop.validate_crop_points([0.,0.,192.,256.], points)
        points[4] = [999.,999.]
        with self.assertRaises(ValueError):
            self.crop.validate_crop_points([0.,0.,192.,256.], points)


if __name__ == '__main__':
    unittest.main()
