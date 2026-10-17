import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-data-readiness.py'
spec = importlib.util.spec_from_file_location('readiness', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReadinessTest(unittest.TestCase):
    def test_artifact_corruption_and_path_escape_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'clip.mp4').write_bytes(b'original')
            artifact = {'relative_path': 'clip.mp4', 'sha256': hashlib.sha256(b'original').hexdigest()}
            self.assertEqual(module.verify_artifact(root, artifact)['status'], 'verified')
            (root / 'clip.mp4').write_bytes(b'changed')
            self.assertEqual(module.verify_artifact(root, artifact)['status'], 'digest_mismatch')
            self.assertEqual(module.verify_artifact(root, {'relative_path': '../secret'})['status'], 'unsafe_path')
            self.assertEqual(module.verify_artifact(root, {'relative_path': '/etc/passwd'})['status'], 'unsafe_path')

    def test_does_not_create_word_labels_or_promote_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / 'audit.json'
            audit.write_text(json.dumps({'counts_by_source_batch': {}, 'records': [
                {'uid': 'failed', 'kind': 'native', 'batches': [4], 'errors': ['missing'], 'missing_frames': [1]}]}))
            (root / 'fitting-reference-index.jsonl').write_text('')
            report = module.run(audit, root, root / 'out')
            queue = json.loads((root / 'out/alignment-review-queue.jsonl').read_text())
            self.assertFalse(queue['structurally_complete_native'])
            self.assertEqual(queue['word_spans'], [])
            self.assertFalse(report['model_training_ready'])
            self.assertEqual(report['ready_word_aligned_csl_pairs_established_by_this_tool'], 0)


if __name__ == '__main__':
    unittest.main()
