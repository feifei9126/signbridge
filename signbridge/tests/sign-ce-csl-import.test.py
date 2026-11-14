"""CE-CSL is sequence-level candidate evidence, never timed or playable words."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-ce-csl-import.py'


def load_tool():
    spec = importlib.util.spec_from_file_location('ce_csl_import', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe(_):
    return {'status': 'passed', 'full_decode_performed': False,
            'metadata': {'width': 640, 'height': 480, 'fps': 25.0,
                         'duration_seconds': 2.0, 'container_reported_frames': 50}}


class CeCslImportTests(unittest.TestCase):
    def fixture(self, root):
        for split, sentence, gloss in [
                ('train', '我参加考试。', '我/考试1/考试2/考试1/。'),
                ('dev', '她吃饭。', '她/吃饭/。'),
                ('test', '我参加考试。', '我/考试1/考试2/考试1/。')]:
            label = root / 'label' / f'{split}.csv'
            label.parent.mkdir(exist_ok=True, parents=True)
            with label.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['Number', 'Translator', 'Chinese Sentences', 'Gloss', 'Note'])
                writer.writerow([f'{split}-00001', 'A', sentence, gloss, '原始备注，保留'])
            video = root / 'video' / split / 'A' / f'{split}-00001.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(b'identical-reference' if split != 'dev' else b'different-reference')

    def run_import(self, module, root, output, **kwargs):
        return module.run_import(root, output, 'User confirmed local project use',
                                 probe=probe, workers=1, **kwargs)

    def test_import_preserves_raw_fields_splits_and_candidate_only_states(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            original = (root / 'label/train.csv').read_bytes()
            report = self.run_import(module, root, output)
            rows = [json.loads(line) for line in (output / 'samples.jsonl').read_text().splitlines()]
            self.assertEqual(report['samples'], 3)
            self.assertEqual(report['split_counts'], {'train': 1, 'dev': 1, 'test': 1})
            self.assertEqual(rows[0]['raw']['Gloss'], '我/考试1/考试2/考试1/。')
            self.assertEqual(rows[0]['source_translator'], 'A')
            self.assertEqual(rows[0]['source_split'], 'train')
            self.assertEqual(rows[0]['project_split'], 'unassigned')
            self.assertEqual(rows[0]['gloss_sequence'], ['我', '考试1', '考试2', '考试1'])
            for row in rows:
                self.assertEqual(row['text_verified'], '')
                self.assertEqual(row['word_spans'], [])
                self.assertFalse(row['native_3d_available'])
                self.assertFalse(row['human_approved'])
                self.assertFalse(row['training_ready'])
                self.assertFalse(row['model_training_ready'])
                self.assertFalse(row['can_play'])
            self.assertEqual((root / 'label/train.csv').read_bytes(), original)

    def test_gloss_lexicon_keeps_variants_and_eval_only_terms_out_of_train_export(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            self.run_import(module, root, output)
            terms = [json.loads(line) for line in (output / 'gloss-lexicon.jsonl').read_text().splitlines()]
            by_label = {term['gloss']: term for term in terms}
            self.assertNotIn('。', by_label)
            self.assertEqual(by_label['考试1']['counts_by_split'], {'train': 2, 'dev': 0, 'test': 2})
            self.assertNotEqual(by_label['考试1']['id'], by_label['考试2']['id'])
            train = [json.loads(line) for line in (output / 'splits/train/gloss-lexicon.jsonl').read_text().splitlines()]
            self.assertEqual({x['gloss'] for x in train}, {'我', '考试1', '考试2'})
            self.assertTrue(all(x['counts_by_split']['dev'] == 0 and x['counts_by_split']['test'] == 0 for x in train))

    def test_cross_split_duplicates_remain_explicit_and_query_defaults_to_train(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            self.run_import(module, root, output)
            duplicates = json.loads((output / 'duplicates.json').read_text())
            self.assertEqual(len(duplicates['video_sha256']), 1)
            self.assertTrue(duplicates['video_sha256'][0]['cross_split'])
            self.assertEqual(len(duplicates['sentence']), 1)
            hits = module.query(output, gloss='考试1')
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]['source_split'], 'train')
            self.assertEqual(len(module.query(output, gloss='考试1', split='all')), 2)
            self.assertEqual(module.query(output, gloss="考试1' OR 1=1 --"), [])

    def test_missing_video_is_reported_without_creating_motion_or_discarding_label(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            (root / 'video/dev/A/dev-00001.mp4').unlink()
            report = self.run_import(module, root, output)
            self.assertEqual(report['missing_videos'], ['video/dev/A/dev-00001.mp4'])
            self.assertEqual(report['samples'], 3)
            self.assertEqual(module.query(output, gloss='吃饭', split='dev')[0]['video']['status'], 'missing')

    def test_cannot_overwrite_or_write_into_source(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            self.run_import(module, root, output)
            with self.assertRaises(FileExistsError):
                self.run_import(module, root, output)
            with self.assertRaises(ValueError):
                self.run_import(module, root, root / 'output')

    def test_rejects_path_traversal_and_outside_symlinks(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            file = root / 'label/train.csv'
            file.write_text(file.read_text(encoding='utf-8-sig').replace(',A,', ',../outside,'), encoding='utf-8')
            with self.assertRaises(ValueError):
                self.run_import(module, root, output)
            self.assertFalse(output.exists())
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            video = root / 'video/train/A/train-00001.mp4'
            video.unlink()
            external = Path(tmp) / 'outside.mp4'
            external.write_bytes(b'outside')
            video.symlink_to(external)
            with self.assertRaises(ValueError):
                self.run_import(module, root, output)

    def test_hash_manifest_binds_every_output(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            self.run_import(module, root, output)
            entries = (output / 'SHA256SUMS').read_text().splitlines()
            self.assertEqual(len(entries), len([p for p in output.rglob('*') if p.is_file()]) - 1)
            for line in entries:
                expected, name = line.split('  ', 1)
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), expected)

    def test_csv_mutation_during_import_does_not_claim_verified_snapshot(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / 'source', Path(tmp) / 'output'
            self.fixture(root)
            def changing_probe(path):
                file = root / 'label/train.csv'
                file.write_bytes(file.read_bytes() + b'\n')
                return probe(path)
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.run_import(root, output, 'Confirmed use', probe=changing_probe, workers=1)
            self.assertFalse((output / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
