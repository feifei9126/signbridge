"""The demo package has a stable public identity and excludes live session files."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-extension-model-package.py'


class PackageTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('extension_package_test', TOOL)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

    def test_public_key_identity_is_fixed(self):
        m = self.module()
        self.assertEqual(m.extension_id(), 'imnkigcbpjdnaaobmefpjcdkdblkfdeo')
        self.assertEqual(len(base64.b64decode(m.PUBLIC_KEY)), 294)
        self.assertNotIn('PRIVATE KEY', m.PUBLIC_KEY)

    def test_seal_verifies_hashes_and_omits_live_state(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); root = parent / 'delivery'; root.mkdir()
            for name in m.MEMBERS:
                if '.' in name or name.endswith('.command'): (root / name).write_text('fixture')
                else:
                    (root / name).mkdir(); (root / name / 'fixture.json').write_text('{}')
            (root / 'running-service.json').write_text('live-session-must-not-be-shipped')
            archive = parent / 'demo.zip'; result = m.seal(root, archive)
            self.assertEqual(result['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
            with zipfile.ZipFile(archive) as z:
                self.assertNotIn('running-service.json', z.namelist())
                for line in z.read('PACKAGE-SHA256SUMS').decode().splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
            second = parent / 'second.zip'; m.seal(root, second)
            self.assertEqual(archive.read_bytes(), second.read_bytes())
            with self.assertRaises(ValueError): m.seal(root, archive)

    def test_package_paths_and_symlinks_rejected(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['../private', '/tmp/file', 'a\\b', './file']:
                with self.assertRaises(ValueError): m.member(root, name)
            (root / 'link').symlink_to('/tmp')
            with self.assertRaises(ValueError): m.member(root, 'link/file')


if __name__ == '__main__': unittest.main()
