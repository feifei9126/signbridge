"""Catch-up indexing keeps caption evidence, duplicates and incomplete stages explicit."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-source-catchup.py'


class CatchupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('catchup', SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def line(self, text, x=.65, y=.72, height=.07):
        return {'text': text, 'confidence': .8, 'bounding_box': [x, y, .25, height]}

    def row(self, seconds, *lines):
        return {'source_seconds': seconds, 'image': f'frame-{seconds}.jpg',
                'image_sha256': 'a' * 64, 'lines': list(lines)}

    def test_sentence_panel_preserves_multiline_order_and_excludes_watermark(self):
        lines = [self.line('对我的帮助', y=.64), self.line('普济手语学校', y=.45),
                 self.line('十分感谢你', y=.74), self.line('公益', x=.05, y=.8)]
        self.assertEqual(self.module.panel_text(lines), '十分感谢你对我的帮助')

    def test_instruction_present_does_not_become_complete_demonstration(self):
        rows = [self.row(t, self.line('谢谢你'), self.line('拇指弯动', y=.23)) for t in [2., 4., 6.]]
        self.assertEqual(self.module.panel_demonstrations(rows, 20.), [])

    def test_short_caption_without_repeat_is_not_a_demonstration(self):
        self.assertEqual(self.module.panel_demonstrations([self.row(2., self.line('谢谢你'))], 20.), [])

    def test_last_continuous_title_run_is_kept_with_unverified_boundaries(self):
        rows = [self.row(t, self.line('谢谢你')) for t in [2., 4., 6.]]
        rows += [self.row(8., self.line('谢谢你'), self.line('拇指弯动', y=.23))]
        rows += [self.row(t, self.line('谢谢你')) for t in [12., 14., 16.]]
        result = self.module.panel_demonstrations(rows, 20.)
        self.assertEqual(len(result), 1)
        self.assertEqual([result[0]['start_seconds'], result[0]['end_seconds']], [11., 17.])
        self.assertFalse(result[0]['training_ready'])
        self.assertFalse(result[0]['semantics_approved'])
        self.assertFalse(result[0]['boundaries_approved'])
        self.assertEqual(len(result[0]['evidence']), 3)

    def test_gap_or_empty_frame_breaks_continuity(self):
        rows = [self.row(2., self.line('谢谢你')), self.row(4.), self.row(6., self.line('谢谢你'))]
        self.assertEqual(self.module.panel_demonstrations(rows, 10.), [])

    def test_hong_kong_language_hint_is_not_csl_training_approval(self):
        value = self.module.language_hint('香港手語新手教室.mp4')
        self.assertEqual(value, 'HKSL_title_hint_unverified')
        self.assertEqual(self.module.language_hint('普通教学.mp4'), 'unconfirmed')

    def test_content_dedup_uses_hash_and_keeps_all_aliases(self):
        rows = [{'sha256': 'a' * 64, 'relative_path': 'one.mp4'},
                {'sha256': 'a' * 64, 'relative_path': 'renamed.mp4'},
                {'sha256': 'b' * 64, 'relative_path': 'third.mp4'}]
        groups = self.module.group_by_hash(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups['a' * 64]), 2)

    def test_ocr_coordinates_cannot_be_nonfinite_or_outside_image(self):
        for bounds in ([.65, float('nan'), .25, .07], [.65, 1.2, .25, .07]):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                self.module.panel_text([{'text': '谢谢你', 'confidence': .8, 'bounding_box': bounds}])


    def test_even_frame_selection_is_ordered_bounded_and_includes_endpoints(self):
        self.assertEqual(self.module.even_indices(1, 5), [0])
        self.assertEqual(self.module.even_indices(3, 5), [0, 1, 2])
        indices = self.module.even_indices(100, 5)
        self.assertEqual(len(indices), 5)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 99)
        self.assertEqual(indices, sorted(set(indices)))
        with self.assertRaises(ValueError):
            self.module.even_indices(0, 5)


if __name__ == '__main__':
    unittest.main()
