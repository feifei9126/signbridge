"""Compile the pure Swift export boundary and exercise real files on macOS."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PluginExportTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'macOS Swift compiler required')
    def test_verified_export_reuse_and_rejection_cases(self):
        with tempfile.TemporaryDirectory(prefix='signbridge-export-compile-') as temp:
            folder = Path(temp)
            shutil.copy2(ROOT / 'tests/mac-plugin-export.test.swift', folder / 'main.swift')
            compiled = subprocess.run(['swiftc', str(ROOT / 'src/tools/mac-plugin-export.swift'), str(folder / 'main.swift'),
                                       '-o', str(folder / 'export-tests')], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(folder / 'export-tests')], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('PASS: verified export', run.stdout)


if __name__ == '__main__': unittest.main()
