import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-build-inputs.py'
spec = importlib.util.spec_from_file_location('build_inputs', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildInputTests(unittest.TestCase):
    def test_current_snapshot_does_not_overwrite_or_create_approvals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, value in [('t08-motion.json', '{}'), ('t08-candidates.json', '{}'), ('research.json', '[]'), ('experimental-index.json', '{"clips":[]}')]:
                (root / name).write_text(value)
            output = root / 'inputs.json'
            result = module.snapshot(root, root, output)
            self.assertEqual(len(result['demo']), 3)
            self.assertFalse(result['training_ready'])
            with self.assertRaises(FileExistsError):
                module.snapshot(root, root, output)

    def test_snapshot_rejects_assets_outside_the_selected_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'research.json').write_text('[]')
            (root / 'experimental-index.json').write_text(json.dumps({'clips': [{'asset': '../secret'}]}))
            (root / 't08-motion.json').write_text('{}')
            (root / 't08-candidates.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                module.snapshot(root, root, root / 'inputs.json')

    def test_snapshot_binds_motion_approval_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'experimental').mkdir()
            for name, value in [('t08-motion.json', '{}'), ('t08-candidates.json', '{}'), ('research.json', '[]')]:
                (root / name).write_text(value)
            (root / 'experimental/motion-approval.json').write_text('{}')
            index = {
                'clips': [],
                'motion_approval': {'asset': 'experimental/motion-approval.json'},
            }
            (root / 'experimental-index.json').write_text(json.dumps(index))
            result = module.snapshot(root, root, root / 'inputs.json')
            self.assertIn('experimental/motion-approval.json', result['experimental'])
            self.assertEqual(len(result['experimental']), 2)


if __name__ == '__main__':
    unittest.main()
