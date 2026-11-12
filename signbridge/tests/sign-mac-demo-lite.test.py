import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-mac-demo-lite.py'


def load():
    spec = importlib.util.spec_from_file_location('sign_mac_demo_lite', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_site(root):
    files = {'manifest.json': b'{}', 'demo/model.html': b'<html></html>'}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write_build(root, {n: hashlib.sha256(d).hexdigest() for n, d in files.items()})
    return files


def write_build(root, digests):
    (root / 'BUILD.json').write_text(json.dumps({'files': digests}))


class SignMacDemoLiteTest(unittest.TestCase):
    def test_valid_site_is_accepted(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            make_site(root)
            self.assertEqual(sorted(m.verified_site(root)), ['demo/model.html', 'manifest.json'])

    def test_tampered_file_is_rejected(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            make_site(root)
            (root / 'manifest.json').write_bytes(b'{"x":1}')
            with self.assertRaises(ValueError):
                m.verified_site(root)

    def test_site_without_required_members_is_rejected(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            make_site(root)
            write_build(root, {'manifest.json': hashlib.sha256(b'{}').hexdigest()})
            with self.assertRaises(ValueError):
                m.verified_site(root)

    def test_build_manifest_cannot_list_itself(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            files = make_site(root)
            digests = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
            digests['BUILD.json'] = 'x'
            write_build(root, digests)
            with self.assertRaises(ValueError):
                m.verified_site(root)

    def test_parent_traversal_member_is_rejected(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'site'
            root.mkdir()
            files = make_site(root)
            (root.parent / 'outside.txt').write_bytes(b'x')
            digests = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
            digests['../outside.txt'] = hashlib.sha256(b'x').hexdigest()
            write_build(root, digests)
            with self.assertRaises(ValueError):
                m.verified_site(root)

    def test_symlinked_member_is_rejected_even_when_content_matches(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'site'
            root.mkdir()
            make_site(root)
            outside = root.parent / 'outside.json'
            outside.write_bytes(b'{}')
            (root / 'manifest.json').unlink()
            (root / 'manifest.json').symlink_to(outside)
            with self.assertRaises(ValueError):
                m.verified_site(root)

    def test_symlinked_site_root_is_rejected(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            (base / 'real').mkdir()
            make_site(base / 'real')
            (base / 'link').symlink_to(base / 'real')
            with self.assertRaises(ValueError):
                m.verified_site(base / 'link')

    def test_existing_output_directory_is_never_reused(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError):
                m.build(Path(temp) / 'site', temp)

    @unittest.skipUnless(shutil.which('node'), 'node is required to read locales.js')
    def test_native_interface_labels_exist_in_locales(self):
        m = load()
        text, labels = m.native_labels()
        for key in m.REQUIRED_LABELS:
            self.assertTrue(labels.get(key), key)
        self.assertEqual(json.loads(text), labels)


if __name__ == '__main__':
    unittest.main()
