import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

TOOL = Path(__file__).parents[1] / 'src/tools/sign-public-motion-package.py'

class PublicMotionPackageTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('public_package', TOOL)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'build'
        self.build.mkdir()
        payload = b'public demo only'
        (self.build / 'example.txt').write_bytes(payload)
        (self.build / 'BUILD.json').write_text(json.dumps({
            'schema': 'signbridge-build-v1', 'profile': 'public-motion-demo',
            'public_motion_release': 'public-motion-v1',
            'training_ready': False, 'model_training_ready': False, 'deployment_ready': False,
            'files': {'example.txt': hashlib.sha256(payload).hexdigest()}}))

    def test_deterministic_verified_zip_and_internal_inventory(self):
        a, b = self.root / 'a.zip', self.root / 'b.zip'
        self.tool.package(self.build, a)
        self.tool.package(self.build, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        with zipfile.ZipFile(a) as z:
            self.assertEqual(sorted(z.namelist()), ['BUILD.json', 'example.txt'])
        inventory = json.loads(a.with_suffix('.zip.contents.json').read_text())
        self.assertEqual(inventory['archive_sha256'], hashlib.sha256(a.read_bytes()).hexdigest())
        self.assertEqual(inventory['files']['example.txt'], hashlib.sha256(b'public demo only').hexdigest())
        with self.assertRaises(FileExistsError): self.tool.package(self.build, a)

    def test_changed_or_unlisted_private_file_is_rejected(self):
        (self.build / 'example.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'digest'): self.tool.package(self.build, self.root / 'bad.zip')
        (self.build / 'example.txt').write_text('public demo only')
        (self.build / 'private.json').write_text('secret')
        with self.assertRaisesRegex(ValueError, 'Unlisted'): self.tool.package(self.build, self.root / 'private.zip')

    def test_traversal_symlink_wrong_profile_and_readiness_rejected(self):
        info = json.loads((self.build / 'BUILD.json').read_text())
        for update in [{'profile': 'local-research'}, {'training_ready': True}, {'files': {'../outside.txt': '0' * 64}}]:
            (self.build / 'BUILD.json').write_text(json.dumps({**info, **update}))
            with self.assertRaises(ValueError): self.tool.package(self.build, self.root / 'unsafe.zip')
        (self.build / 'BUILD.json').write_text(json.dumps(info))
        (self.build / 'example.txt').unlink()
        (self.root / 'outside.txt').write_text('public demo only')
        (self.build / 'example.txt').symlink_to(self.root / 'outside.txt')
        with self.assertRaisesRegex(ValueError, 'symlink'): self.tool.package(self.build, self.root / 'link.zip')

if __name__ == '__main__':
    unittest.main()
