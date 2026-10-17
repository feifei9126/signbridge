"""Behavioral contracts for the isolated learned Chinese semantics milestone."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-learned.py'
spec = importlib.util.spec_from_file_location('csl_learned', TOOL)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class LearnedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / 'run'
        model.train_run(cls.root, count=8000, epochs=14, seed=17)
        cls.parser = model.load_model(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_text_disjoint_explicit_synthetic_splits(self):
        sets = []
        groups = []
        for split in ['train', 'validation', 'test']:
            rows = [json.loads(x) for x in (self.root / f'{split}.jsonl').read_text().splitlines()]
            self.assertTrue(all(x['label_source'] == 'assistant_synthetic_chinese' for x in rows))
            sets.append({x['text'] for x in rows})
            groups.append({x['split_group'] for x in rows})
            self.assertFalse({x['text'] for x in rows} & {model.clean(t) for t, _ in model.CHALLENGE})
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
        meta = json.loads((self.root / 'model.json').read_text())
        self.assertFalse(meta['csl_translation_trained'])
        self.assertFalse(meta['human_approved'])

    def test_roles_are_learned_and_order_matters(self):
        a, b = [self.parser.predict(x) for x in ['我帮你', '你帮我']]
        self.assertEqual(a['status'], 'parsed')
        self.assertEqual(b['status'], 'parsed')
        self.assertEqual(a['roles']['actor'], '我')
        self.assertEqual(a['roles']['patient'], '你')
        self.assertEqual(b['roles']['actor'], '你')
        self.assertEqual(b['roles']['patient'], '我')
        self.assertNotEqual(a['meaning_key'], b['meaning_key'])
        self.assertEqual(a['motion_status'], 'requires_csl_alignment_review')
        self.assertNotIn('motions', a)

    def test_learned_weights_are_required_not_just_support_tables(self):
        import numpy as np
        blank = model.Parser(self.parser.metadata, np.zeros_like(self.parser.weights), np.zeros_like(self.parser.transitions))
        self.assertEqual(blank.predict('我帮你')['status'], 'abstained')
        self.assertEqual(self.parser.predict('我帮你')['status'], 'parsed')

    def test_unknown_complex_scope_and_unicode_abstain(self):
        for text in ['', '我去火星', '如果你来我就去', '我不想去', '我帮你你帮我', '😀', '我' * 501]:
            with self.subTest(text=text[:30]):
                self.assertEqual(self.parser.predict(text)['status'], 'abstained')

    def test_known_characters_do_not_bypass_argument_support(self):
        for text in ['我喝书', '我买医院', '我去水', '我们去你', '我学习水']:
            with self.subTest(text=text):
                self.assertEqual(self.parser.predict(text)['status'], 'abstained')

    def test_generated_request_labels_do_not_mix_past_time_or_aspect(self):
        for row in model.corpus(1000):
            roles = row['roles']
            if 'politeness' in roles:
                self.assertNotIn('time', roles)
                self.assertNotIn('aspect', roles)
                self.assertIn(roles['actor'], ['你', '你们'])
            if roles['predicate'] == '学习' and 'patient' in roles:
                self.assertEqual(roles['patient'], '手语')

    def test_service_payload_does_not_expose_training_tables(self):
        out = self.parser.predict('我帮你')
        self.assertNotIn('vocabulary', out)
        self.assertNotIn('feature_names', out)
        self.assertNotIn('train_examples', out)

    def test_model_digest_checked_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            target = Path(tmp) / 'copy'
            shutil.copytree(self.root, target)
            p = target / 'weights.npz'
            p.write_bytes(p.read_bytes() + b'tamper')
            with self.assertRaisesRegex(ValueError, 'digest'):
                model.load_model(target)

    def test_never_overwrite_previous_run(self):
        with self.assertRaises(FileExistsError):
            model.train_run(self.root, count=10, epochs=1, seed=17)


if __name__ == '__main__':
    unittest.main()
