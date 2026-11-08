import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'src/tools/sign-mac-demo-bundle.py'


class ManifestTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('mac_bundle_test', PATH)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

    def test_only_verified_members_are_selected(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp); (r / 'tools').mkdir()
            data = b'public'; (r / 'tools/one.py').write_bytes(data)
            (r / 'tools/unlisted-secret.log').write_text('must-not-ship')
            (r / 'PACKAGE-SHA256SUMS').write_text(hashlib.sha256(data).hexdigest() + '  tools/one.py\n')
            self.assertEqual(list(m.verified_members(r)), ['tools/one.py'])

    def test_parent_symlinks_rejected_even_if_content_hash_matches(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp); target=r/'outside';target.mkdir();(target/'secret').write_bytes(b'x')
            (r/'tools').symlink_to(target)
            (r/'PACKAGE-SHA256SUMS').write_text(hashlib.sha256(b'x').hexdigest()+'  tools/secret\n')
            with self.assertRaises(ValueError):m.verified_members(r)

    def test_required_top_level_inputs_cannot_be_omitted_or_unlisted_symlinks(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'model-config.json').write_bytes(b'{}')
            (root/'external').write_text('outside');(root/'README.md').symlink_to(root/'external')
            (root/'PACKAGE-SHA256SUMS').write_text(hashlib.sha256(b'{}').hexdigest()+'  model-config.json\n')
            with self.assertRaises(ValueError):m.verified_members(root,['model-config.json','README.md','provenance.json'])

    def test_installer_targets_applications_without_relocating_existing_demo(self):
        m = self.module()
        rows = m.fixed_components([{'RootRelativeBundlePath':'SignBridge Demo.app','BundleIsRelocatable':True}])
        self.assertFalse(rows[0]['BundleIsRelocatable'])
        self.assertTrue(rows[0]['BundleHasStrictIdentifier'])
        self.assertEqual(rows[0]['RootRelativeBundlePath'],'SignBridge Demo.app')


if __name__ == '__main__': unittest.main()
