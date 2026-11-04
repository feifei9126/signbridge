import importlib.util
from pathlib import Path
import tempfile
import json
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-core-units.py'


class CoreUnitsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file())
        spec = importlib.util.spec_from_file_location('core_units_test', TOOL)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)

    def test_slice_uses_exact_source_frame_rows_and_never_creates_approval(self):
        clip = {'id': 'native_fit_example', 'text': '我', 'aliases': ['我'], 'fps': 25,
                'frames': 10, 'source_uid': 'chunk:fit_example', 'human_approved': False,
                'semantics_approved': False, 'boundaries_approved': False, 'text_verified': '',
                'training_ready': False, 'model_training_ready': False, 'training_started': False,
                'bones': ['test'], 'quaternions': [[i] for i in range(10)]}
        proposal = {'key': 'speaker', 'text': '我', 'source_id': clip['id'],
                    'start': 3, 'end': 8, 'role': 'person', 'note': '候选边界'}
        result = self.api.slice_clip(clip, proposal, 'a' * 64)
        self.assertEqual(result['quaternions'], clip['quaternions'][2:8])
        self.assertEqual(result['frames'], 6)
        self.assertEqual(result['source_frame_range_1based'], [3, 8])
        self.assertEqual(result['source_frame_ids_1based'], list(range(3, 9)))
        for field in ['human_approved', 'semantics_approved', 'boundaries_approved',
                      'training_ready', 'model_training_ready']:
            self.assertIs(result[field], False)
        self.assertEqual(result['text_verified'], '')
        self.assertEqual(clip['frames'], 10)
        for start, end in [(0, 4), (3, 20), (3, 5), (True, 5)]:
            with self.assertRaises(ValueError):
                self.api.slice_clip(clip, {**proposal, 'start': start, 'end': end}, 'a' * 64)

    def test_lexical_caption_support_does_not_count_a_navigation_menu(self):
        self.assertFalse(self.api.label_support('家', ['家|医院|学校|复习']))
        self.assertTrue(self.api.label_support('家', ['手语：家']))
        self.assertTrue(self.api.label_support('家', ['家（房子）']))
        self.assertFalse(self.api.label_support('谢', ['手语：好啊，谢谢，不客气']))


if __name__ == '__main__':
    unittest.main()
