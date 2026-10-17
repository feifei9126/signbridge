"""A public research kit must be reproducible without including private data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-research-package.py'
spec = importlib.util.spec_from_file_location('research_package', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ResearchPackageTests(unittest.TestCase):
    def prepare(self, root):
        repo = root / 'repo'
        client = root / 'client'
        for name in module.SOURCE_FILES:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# synthetic fixture\n')
        (repo / 'LICENSE').write_text('License fixture\n')
        for name in module.CLIENT_FILES - {'BUILD.json'}:
            path = client / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('<html>fixture</html>' if name.endswith('.html') else '// client\n')
        files = {name: hashlib.sha256((client / name).read_bytes()).hexdigest() for name in module.CLIENT_FILES - {'BUILD.json'}}
        (client / 'BUILD.json').write_text(json.dumps({'schema': 'signbridge-private-client-build-v1', 'private_assets_included': False, 'csl_translation_trained': False, 'files': files}))
        return repo, client

    def test_publication_has_exact_allowlist_and_verifiable_internal_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, client = self.prepare(root)
            secret = repo / 'local-data/private.mp4'
            secret.parent.mkdir()
            secret.write_bytes(b'should-never-upload')
            out = root / 'release'
            result = module.package(repo, client, out, 'a' * 40)
            with zipfile.ZipFile(out / module.KIT_NAME) as archive:
                names = set(archive.namelist())
                self.assertFalse(any(name.endswith(('.npz', '.pt', '.mp4', '.glb')) for name in names))
                self.assertNotIn('local-data/private.mp4', names)
                manifest = json.loads(archive.read('MANIFEST.json'))
                self.assertFalse(manifest['weights_included'])
                self.assertFalse(manifest['csl_translation_trained'])
                for name, expected in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
            self.assertEqual(result['source_commit'], 'a' * 40)
            with self.assertRaises(FileExistsError):
                module.package(repo, client, out, 'a' * 40)

    def test_client_corruption_unknown_files_and_symlinks_are_rejected(self):
        for case in ['tamper', 'extra', 'symlink']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, client = self.prepare(root)
                if case == 'tamper':
                    (client / 'private/client.js').write_text('tampered')
                elif case == 'extra':
                    (client / 'weights.npz').write_bytes(b'private')
                else:
                    (client / 'worker.js').unlink()
                    (client / 'worker.js').symlink_to(repo / 'LICENSE')
                with self.assertRaises(ValueError):
                    module.package(repo, client, root / 'release', 'a' * 40)


if __name__ == '__main__':
    unittest.main()
