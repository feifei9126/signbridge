import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-demo-serve.py'


class DemoServeTest(unittest.TestCase):
    def test_local_server_chooses_free_port_and_serves_demo_and_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'demo').mkdir()
            (root / 'demo/index.html').write_text('<title>test-demo</title>')
            (root / 'demo/t08-motion.json').write_text('{"test":true}')
            process = subprocess.Popen([sys.executable, str(TOOL), '--directory', str(root), '--no-open'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = process.stdout.readline().strip()
                url = line.removeprefix('SignBridge Demo: ')
                self.assertTrue(url.startswith('http://127.0.0.1:'))
                with urlopen(url, timeout=5) as response:
                    self.assertIn(b'test-demo', response.read())
                with urlopen(url.replace('index.html', 't08-motion.json'), timeout=5) as response:
                    self.assertEqual(response.read(), b'{"test":true}')
            finally:
                process.terminate()
                process.communicate(timeout=5)

    def test_missing_build_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(TOOL), '--directory', temp, '--no-open'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('npm run build', result.stderr)


if __name__ == '__main__':
    unittest.main()
